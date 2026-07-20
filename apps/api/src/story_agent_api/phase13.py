from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .models import (
    CanonDocument,
    CanonGenerationProposal,
    CompetitorProfile,
    IdeationMessage,
    IdeationSession,
    MarketResearchBrief,
    ModelConfig,
    ModelProvider,
    ModelRoleBinding,
    ModelRun,
    OpeningCandidate,
    OpeningExperiment,
    ReaderEvaluation,
    ResearchEvidence,
    ResearchFinding,
    ResearchJob,
    ResearchQuery,
    ResearchSource,
    ResearchSourceVersion,
    StoryBriefProposal,
    StoryBriefVersion,
    StoryOpportunity,
    StyleBaseline,
)
from .research_providers import (
    ContentFetchProvider,
    DeterministicContentFetchProvider,
    DeterministicSearchProvider,
    FirecrawlContentFetchProvider,
    ResearchProviderError,
    ResearchSourcePolicy,
    SearchProvider,
    TavilySearchProvider,
)
from .schemas import (
    CompetitorExclude,
    IdeationMessageCreate,
    IdeationSessionCreate,
    IncubationCanonProposalCreate,
    MarketResearchBriefCreate,
    OpeningCandidateAction,
    OpeningChapterApproval,
    OpeningExpand,
    OpeningExperimentCreate,
    ResearchJobAction,
    ResearchJobCreate,
    StoryBriefProposalAction,
    StoryBriefProposalCreate,
    StoryOpportunityAction,
    StoryOpportunityCreate,
)
from .services import StoryError, dumps, safe_json_loads, stable_digest


def _now() -> datetime:
    return datetime.now(timezone.utc)


PERSPECTIVES = (
    "platform_trends",
    "genre_leaders",
    "reader_praise",
    "reader_dropoff",
    "opening_strategy",
    "serial_engine",
)
SCORE_LIMITS = {
    "platformFit": 15,
    "openingHook": 15,
    "emotionalPayoff": 15,
    "differentiation": 15,
    "serialEngine": 15,
    "characterStickiness": 10,
    "worldEngine": 10,
    "readability": 5,
}
DEFAULT_OPENING_STRATEGIES = [
    {"key": "strong-event", "label": "Strong event", "focus": "Open with a concrete disruptive event and an immediate choice."},
    {"key": "strong-character", "label": "Strong character", "focus": "Open with the protagonist's active desire colliding with a personal cost."},
    {"key": "strong-mystery", "label": "Strong mystery", "focus": "Open with a specific question whose answer changes the protagonist's next action."},
]


class Phase13Service:
    """Persistent, provider-agnostic market research and story incubation.

    Provider work is deliberately done between short SQLite write transactions.
    The default providers are deterministic and empty, so a local installation
    never makes a network call merely by creating a research job.
    """

    def __init__(self, service: Any):
        self.service = service
        self.search_provider: SearchProvider = DeterministicSearchProvider()
        self.fetch_provider: ContentFetchProvider = DeterministicContentFetchProvider()

    def _complete_model_json(
        self,
        project: Any,
        role: str,
        run_role: str,
        request_id: str,
        system: str,
        payload: dict[str, Any],
        *,
        budget_job_id: str | None = None,
        max_output_tokens: int | None = None,
        max_retries: int | None = None,
        stream_response: bool = False,
    ) -> tuple[dict[str, Any], str]:
        """Run one bounded JSON call plus one explicit repair attempt.

        Phase 8 owns the provider, credential, retry and ModelRun mechanics.
        Keeping the call outside every Phase 13 write transaction lets callers
        re-check their frozen authority immediately before persistence.
        """
        messages = [
            {"role": "system", "content": f"{system}\nReturn one JSON object only."},
            {"role": "user", "content": dumps(payload)},
        ]
        if budget_job_id:
            self._assert_research_model_budget(project, budget_job_id)
        text, run_id = self.service.phase8._complete_role(
            project, role, messages, request_id, response_json=True, run_role=run_role,
            max_output_tokens=max_output_tokens, max_retries=max_retries, stream_response=stream_response,
        )
        if budget_job_id:
            self._charge_research_model_run(project, budget_job_id, run_id)
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                return value, run_id
        except (TypeError, ValueError):
            pass
        if budget_job_id:
            self._assert_research_model_budget(project, budget_job_id)
        repair, repair_run_id = self.service.phase8._complete_role(
            project,
            role,
            [
                {"role": "system", "content": "Repair the invalid response. Return one JSON object only; do not add commentary."},
                {"role": "user", "content": dumps({"invalidResponse": text[:4000], "requiredPayload": payload})},
            ],
            request_id,
            response_json=True,
            run_role=f"{run_role}:repair",
            max_output_tokens=max_output_tokens,
            max_retries=max_retries,
            stream_response=stream_response,
        )
        if budget_job_id:
            self._charge_research_model_run(project, budget_job_id, repair_run_id)
        try:
            value = json.loads(repair)
        except (TypeError, ValueError) as exc:
            raise StoryError(422, "INCUBATOR_MODEL_JSON_INVALID", "The model did not return a valid JSON object after one repair attempt.") from exc
        if not isinstance(value, dict):
            raise StoryError(422, "INCUBATOR_MODEL_JSON_INVALID", "The model did not return a JSON object after one repair attempt.")
        return value, repair_run_id

    def _assert_research_model_budget(self, project: Any, job_id: str) -> None:
        """Stop before another paid model call once the job budget is spent."""
        with self.service.db.project(project.id, project.folder_path) as session:
            job = session.get(ResearchJob, job_id)
            if not job or job.project_id != project.id:
                raise StoryError(404, "RESEARCH_JOB_NOT_FOUND", "Research job was not found.")
            limits = safe_json_loads(job.limits_json, {})
            if job.status == "cancelled":
                raise StoryError(409, "RESEARCH_JOB_CANCELLED", "Research job was cancelled.")
            if self._runtime_exceeded(job.started_at, limits):
                raise StoryError(409, "RESEARCH_RUNTIME_LIMIT", "The research task exceeded its runtime budget.")
            if job.estimated_cost >= float(limits.get("maxCost", 5.0)):
                raise StoryError(409, "RESEARCH_COST_LIMIT", "The research task exhausted its cost budget.")

    def _charge_research_model_run(self, project: Any, job_id: str, run_id: str) -> None:
        """Include completed model cost in the research job's authoritative budget."""
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = session.get(ResearchJob, job_id)
            run = session.get(ModelRun, run_id)
            if not job or job.project_id != project.id or not run:
                raise StoryError(409, "RESEARCH_JOB_DRIFT", "Research job changed while model cost was recorded.")
            job.estimated_cost += max(0.0, float(run.estimated_cost or 0.0))
            job.updated_at = _now()

    # ------------------------------------------------------------------
    # Research brief and job lifecycle
    # ------------------------------------------------------------------
    def create_brief(self, project_id: str, payload: MarketResearchBriefCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        data = payload.model_dump(mode="json", by_alias=True)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            current = session.scalar(select(MarketResearchBrief).where(
                MarketResearchBrief.project_id == project.id, MarketResearchBrief.status == "current"
            ))
            current_revision = current.revision if current else 0
            if current_revision != payload.expected_revision:
                raise StoryError(409, "RESEARCH_BRIEF_REVISION_CONFLICT", "Research brief revision conflict.", {"currentRevision": current_revision})
            if current:
                current.status = "superseded"
                current.revision += 1
                current.updated_at = _now()
            now = _now()
            snapshot = self._brief_snapshot(data)
            row = MarketResearchBrief(
                id=str(uuid4()), project_id=project.id,
                version_number=(current.version_number + 1) if current else 1,
                format=data["format"], platform=data["platform"], genre=data["genre"], audience=data["audience"],
                target_chapters=data.get("targetChapters"), target_words=data.get("targetWords"),
                emotional_value_json=dumps(data["emotionalValue"]), research_date_range_json=dumps(data["researchDateRange"]),
                included_domains_json=dumps(data["includedDomains"]), excluded_domains_json=dumps(data["excludedDomains"]),
                reference_works_json=dumps(data["referenceWorks"]), forbidden_content_json=dumps(data["forbiddenContent"]),
                commercial_goals_json=dumps(data["commercialGoals"]), notes=data["notes"], checksum=stable_digest(snapshot),
                # The API updates a moving "current" brief rather than a
                # stable resource ID. Carry the revision forward so a stale
                # browser cannot overwrite a newer brief with the same
                # expectedRevision value.
                status="current", revision=current_revision + 1, created_at=now, updated_at=now,
            )
            session.add(row)
            session.add(self.service._audit("research_brief.saved", "market_research_brief", row.id, {"revision": row.revision}, request_id))
            session.flush()
            return self._brief_dict(row)

    def list_briefs(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._brief_dict(item) for item in session.scalars(
                select(MarketResearchBrief).where(MarketResearchBrief.project_id == project.id).order_by(MarketResearchBrief.version_number.desc())
            ).all()]

    def create_job(self, project_id: str, payload: ResearchJobCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        search_secret_ref = payload.search_secret_ref
        fetch_secret_ref = payload.fetch_secret_ref
        try:
            if payload.search_api_key:
                search_secret_ref = f"research-provider:{project.id}:tavily"
                self.service.secret_store.set_secret(search_secret_ref, payload.search_api_key)
            elif payload.search_provider == "tavily" and not search_secret_ref:
                reusable = f"research-provider:{project.id}:tavily"
                if self.service.secret_store.get_secret(reusable):
                    search_secret_ref = reusable
            if payload.fetch_api_key:
                fetch_secret_ref = f"research-provider:{project.id}:firecrawl"
                self.service.secret_store.set_secret(fetch_secret_ref, payload.fetch_api_key)
            elif payload.fetch_provider == "firecrawl" and not fetch_secret_ref:
                reusable = f"research-provider:{project.id}:firecrawl"
                if self.service.secret_store.get_secret(reusable):
                    fetch_secret_ref = reusable
        except Exception as exc:
            raise StoryError(503, "CREDENTIAL_STORE_UNAVAILABLE", "Unable to save research credentials in the operating-system credential store.") from exc
        with self.service.db.project_write(project.id, project.folder_path) as session:
            brief = session.get(MarketResearchBrief, payload.brief_id) if payload.brief_id else session.scalar(select(MarketResearchBrief).where(
                MarketResearchBrief.project_id == project.id, MarketResearchBrief.status == "current"
            ))
            if not brief or brief.project_id != project.id:
                raise StoryError(404, "RESEARCH_BRIEF_NOT_FOUND", "Research brief was not found for this project.")
            if brief.status != "current":
                raise StoryError(409, "RESEARCH_BRIEF_SUPERSEDED", "Research jobs can only be created from the current research brief.")
            if brief.revision != payload.expected_brief_revision:
                raise StoryError(409, "RESEARCH_BRIEF_REVISION_CONFLICT", "Research brief revision conflict.", {"currentRevision": brief.revision})
            request_fingerprint = stable_digest({"brief": brief.id, "revision": brief.revision, "payload": payload.model_dump(mode="json", by_alias=True, exclude={"run_immediately", "search_api_key", "fetch_api_key"})})
            if payload.idempotency_key:
                existing = session.scalar(select(ResearchJob).where(
                    ResearchJob.project_id == project.id, ResearchJob.idempotency_key == payload.idempotency_key
                ))
                if existing:
                    if existing.diagnostic_json == request_fingerprint:
                        result = self._job_dict(existing)
                    else:
                        raise StoryError(409, "RESEARCH_JOB_IDEMPOTENCY_CONFLICT", "The idempotency key was already used with another request.")
                else:
                    result = None
                if result:
                    return result
            now = _now()
            config = {
                "searchProvider": payload.search_provider,
                "searchSecretRef": search_secret_ref,
                "fetchProvider": payload.fetch_provider,
                "fetchSecretRef": fetch_secret_ref,
            }
            row = ResearchJob(
                id=str(uuid4()), project_id=project.id, brief_id=brief.id, brief_revision=brief.revision,
                brief_checksum=brief.checksum, status="queued", idempotency_key=payload.idempotency_key,
                provider_config_json=dumps(config), limits_json=dumps(payload.limits.model_dump(mode="json", by_alias=True)),
                diagnostic_json=request_fingerprint, revision=1, created_at=now, updated_at=now,
            )
            session.add(row)
            session.add(self.service._audit("research_job.queued", "research_job", row.id, {"attempt": 1}, request_id))
            session.flush()
            job_id = row.id
            result = self._job_dict(row)
        if payload.run_immediately:
            return self.run_job(job_id, request_id)
        return result

    def list_jobs(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._job_dict(item) for item in session.scalars(
                select(ResearchJob).where(ResearchJob.project_id == project.id).order_by(ResearchJob.created_at.desc())
            ).all()]

    def get_job(self, job_id: str) -> dict[str, Any]:
        project, row = self._project_for_job(job_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            current = session.get(ResearchJob, row.id)
            assert current
            return self._job_dict(current)

    def cancel_job(self, job_id: str, payload: ResearchJobAction, request_id: str) -> dict[str, Any]:
        project, _ = self._project_for_job(job_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(ResearchJob, job_id)
            assert row
            self._expect_revision(row, payload.expected_revision, "RESEARCH_JOB_REVISION_CONFLICT")
            if row.status in {"accepted", "rejected", "cancelled"}:
                raise StoryError(409, "RESEARCH_JOB_NOT_CANCELLABLE", "Research job is already terminal.")
            row.status, row.revision, row.updated_at = "cancelled", row.revision + 1, _now()
            row.completed_at = row.updated_at
            session.add(self.service._audit("research_job.cancelled", "research_job", row.id, {}, request_id))
            return self._job_dict(row)

    def start_job(self, job_id: str, payload: ResearchJobAction, request_id: str) -> dict[str, Any]:
        """Start a queued job that was deliberately created without running.

        This is also the explicit user-visible entry point needed after a
        research brief has been edited: revision is checked before provider
        calls begin, so stale UI cannot consume a provider budget.
        """
        project, _ = self._project_for_job(job_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(ResearchJob, job_id)
            assert row
            self._expect_revision(row, payload.expected_revision, "RESEARCH_JOB_REVISION_CONFLICT")
            if row.status != "queued":
                raise StoryError(409, "RESEARCH_JOB_NOT_QUEUED", "Only a queued research job can be started.")
        return self.run_job(job_id, request_id)

    def resume_job(self, job_id: str, payload: ResearchJobAction, request_id: str) -> dict[str, Any]:
        project, _ = self._project_for_job(job_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(ResearchJob, job_id)
            assert row
            self._expect_revision(row, payload.expected_revision, "RESEARCH_JOB_REVISION_CONFLICT")
            if row.status not in {"insufficient_evidence", "failed", "cancelled"}:
                raise StoryError(409, "RESEARCH_JOB_NOT_RESUMABLE", "Only a failed, cancelled, or insufficient job can be resumed.")
            row.status, row.attempt, row.revision, row.updated_at = "queued", row.attempt + 1, row.revision + 1, _now()
            row.error_code = row.error_message = None
            session.add(self.service._audit("research_job.resumed", "research_job", row.id, {"attempt": row.attempt}, request_id))
        return self.run_job(job_id, request_id)

    def run_job(self, job_id: str, request_id: str) -> dict[str, Any]:
        project, _ = self._project_for_job(job_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = session.get(ResearchJob, job_id)
            assert job
            if job.status != "queued":
                return self._job_dict(job)
            brief = session.get(MarketResearchBrief, job.brief_id)
            if not self._brief_matches_job(session, job):
                job.status, job.error_code, job.completed_at = "failed", "RESEARCH_BRIEF_DRIFT", _now()
                job.revision += 1
                job.updated_at = job.completed_at
                session.add(self.service._audit("research_job.drifted", "research_job", job.id, {}, request_id))
                return self._job_dict(job)
            job.status, job.started_at, job.updated_at = "planning", _now(), _now()
            job.revision += 1
            snapshot = self._brief_dict(brief)
            limits = safe_json_loads(job.limits_json, {})
            attempt = job.attempt
        try:
            self._providers_for(job)
            planned = self._model_queries(project, snapshot, request_id, job_id)
        except StoryError as exc:
            return self._fail_job(project, job_id, exc.code, exc.message, request_id)
        planned = planned[:int(limits.get("maxQueries", 6))]
        for sequence, (perspective, query_text) in enumerate(planned, start=1):
            if self._job_has_brief_drift(project, job_id):
                return self._fail_job(project, job_id, "RESEARCH_BRIEF_DRIFT", "The research brief changed while the job was running.", request_id)
            if not self._job_is_active(project, job_id):
                return self.get_job(job_id)
            if self._runtime_exceeded(job.started_at, limits):
                return self._fail_job(project, job_id, "RESEARCH_RUNTIME_LIMIT", "The research task exceeded its runtime budget.", request_id)
            fingerprint = stable_digest({"perspective": perspective, "query": query_text})
            with self.service.db.project_write(project.id, project.folder_path) as session:
                existing = session.scalar(select(ResearchQuery).where(ResearchQuery.job_id == job_id, ResearchQuery.fingerprint == fingerprint))
                if existing and existing.status == "succeeded":
                    continue
                if not existing:
                    existing = ResearchQuery(id=str(uuid4()), project_id=project.id, job_id=job_id, attempt=attempt, perspective=perspective, query_text=query_text, sequence_number=sequence, fingerprint=fingerprint, created_at=_now())
                    session.add(existing)
                existing.status = "running"
                job = session.get(ResearchJob, job_id)
                assert job
                job.status = "searching"
                job.updated_at = _now()
            try:
                search_provider, _ = self._providers_for(job)
                response = search_provider.search(query_text, snapshot["includedDomains"], snapshot["researchDateRange"], int(limits.get("maxPages", 30)))
            except ResearchProviderError as exc:
                with self.service.db.project_write(project.id, project.folder_path) as session:
                    query = session.scalar(select(ResearchQuery).where(ResearchQuery.job_id == job_id, ResearchQuery.fingerprint == fingerprint))
                    if query:
                        query.status, query.error_code, query.error_message, query.completed_at = "failed", exc.code, exc.message, _now()
                return self._fail_job(project, job_id, exc.code, exc.message, request_id)
            except StoryError as exc:
                return self._fail_job(project, job_id, exc.code, exc.message, request_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                query = session.scalar(select(ResearchQuery).where(ResearchQuery.job_id == job_id, ResearchQuery.fingerprint == fingerprint))
                job = session.get(ResearchJob, job_id)
                if not query or not job or job.status == "cancelled":
                    return self.get_job(job_id)
                if not self._brief_matches_job(session, job):
                    return self._fail_job_in_session(session, job, "RESEARCH_BRIEF_DRIFT", "The research brief changed while the job was running.", request_id)
                if self._cost_exceeded(job, response.estimated_cost, limits):
                    return self._fail_job_in_session(session, job, "RESEARCH_COST_LIMIT", "The research task exceeded its cost budget.", request_id)
                query.status, query.result_count, query.request_units, query.estimated_cost, query.completed_at = "succeeded", len(response.results), response.request_units, response.estimated_cost, _now()
                query.provider_metadata_json = dumps(response.provider_metadata)
                job.query_count += 1
                job.request_units += response.request_units
                job.estimated_cost += response.estimated_cost
                job.updated_at = _now()
                snapshot_in_session = self._brief_dict(session.get(MarketResearchBrief, job.brief_id))
                for result in response.results:
                    if self._source_is_allowed(result.url, snapshot_in_session["includedDomains"], snapshot_in_session["excludedDomains"]):
                        self._upsert_search_source(session, project.id, job, query, result)
        with self.service.db.project(project.id, project.folder_path) as session:
            sources = session.scalars(select(ResearchSource).where(ResearchSource.job_id == job_id, ResearchSource.status == "discovered")).all()
            max_pages = int(limits.get("maxPages", 30))
            source_ids = [source.id for source in sources[:max_pages]]
        for source_id in source_ids:
            if self._job_has_brief_drift(project, job_id):
                return self._fail_job(project, job_id, "RESEARCH_BRIEF_DRIFT", "The research brief changed while the job was running.", request_id)
            if not self._job_is_active(project, job_id):
                return self.get_job(job_id)
            if self._runtime_exceeded(job.started_at, limits):
                return self._fail_job(project, job_id, "RESEARCH_RUNTIME_LIMIT", "The research task exceeded its runtime budget.", request_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                source = session.get(ResearchSource, source_id)
                job = session.get(ResearchJob, job_id)
                if not source or not job or source.status != "discovered":
                    continue
                if job.fetched_chars >= int(limits.get("maxTotalChars", 200_000)):
                    break
                source.status, job.status, job.updated_at = "fetching", "fetching", _now()
                url, max_chars = source.canonical_url, int(limits.get("maxCharsPerPage", 20_000))
            try:
                _, fetch_provider = self._providers_for(job)
                fetched = fetch_provider.fetch(url, max_chars)
            except ResearchProviderError as exc:
                with self.service.db.project_write(project.id, project.folder_path) as session:
                    source = session.get(ResearchSource, source_id)
                    if source:
                        source.status, source.failure_reason, source.updated_at = "failed", exc.code, _now()
                continue
            except StoryError as exc:
                return self._fail_job(project, job_id, exc.code, exc.message, request_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                source, job = session.get(ResearchSource, source_id), session.get(ResearchJob, job_id)
                if not source or not job or job.status == "cancelled":
                    return self.get_job(job_id)
                if not self._brief_matches_job(session, job):
                    return self._fail_job_in_session(session, job, "RESEARCH_BRIEF_DRIFT", "The research brief changed while the job was running.", request_id)
                if self._cost_exceeded(job, fetched.estimated_cost, limits):
                    return self._fail_job_in_session(session, job, "RESEARCH_COST_LIMIT", "The research task exceeded its cost budget.", request_id)
                total_limit = int(limits.get("maxTotalChars", 200_000))
                remaining = max(0, total_limit - job.fetched_chars)
                content = fetched.content[:remaining]
                checksum = stable_digest({"url": fetched.final_url, "content": content})
                previous = session.scalar(select(ResearchSourceVersion).where(ResearchSourceVersion.source_id == source.id, ResearchSourceVersion.content_checksum == checksum))
                if not previous:
                    number = (session.scalar(select(func.max(ResearchSourceVersion.version_number)).where(ResearchSourceVersion.source_id == source.id)) or 0) + 1
                    session.add(ResearchSourceVersion(id=str(uuid4()), project_id=project.id, job_id=job.id, source_id=source.id, version_number=number, final_url=fetched.final_url, content_checksum=checksum, bounded_content=content, summary=fetched.summary[:2000], char_count=len(content), truncated=fetched.truncated or len(content) < len(fetched.content), fetch_metadata_json=dumps(fetched.provider_metadata), fetched_at=fetched.fetched_at))
                    job.fetched_chars += len(content)
                source.status, source.title, source.updated_at = "fetched", fetched.title[:1000] or source.title, _now()
                source.revision += 1
                job.page_count += 1
                job.request_units += fetched.request_units
                job.estimated_cost += fetched.estimated_cost
                job.updated_at = _now()
        if self._runtime_exceeded(job.started_at, limits):
            return self._fail_job(project, job_id, "RESEARCH_RUNTIME_LIMIT", "The research task exceeded its runtime budget.", request_id)
        try:
            return self._analyze_job(project, job_id, request_id)
        except StoryError as exc:
            return self._fail_job(project, job_id, exc.code, exc.message, request_id)

    def _analyze_job(self, project: Any, job_id: str, request_id: str) -> dict[str, Any]:
        with self.service.db.project(project.id, project.folder_path) as session:
            job = session.get(ResearchJob, job_id)
            assert job
            if job.status == "cancelled":
                return self._job_dict(job)
            versions = list(session.scalars(select(ResearchSourceVersion).where(ResearchSourceVersion.job_id == job.id)).all())
            sources = {item.id: item for item in session.scalars(select(ResearchSource).where(ResearchSource.job_id == job.id)).all()}
            query_perspectives = {item.id: item.perspective for item in session.scalars(select(ResearchQuery).where(ResearchQuery.job_id == job.id)).all()}
            frozen = {
                "revision": job.revision,
                "briefChecksum": job.brief_checksum,
                "reportRevision": job.report_revision,
                "startedAt": job.started_at,
                "limits": safe_json_loads(job.limits_json, {}),
            }
        extracted: list[tuple[ResearchSourceVersion, int, dict[str, Any]]] = []
        external_reports: list[dict[str, Any]] = []
        for version in versions:
            source = sources.get(version.source_id)
            if not source or source.excluded or not version.bounded_content:
                continue
            if self._job_has_brief_drift(project, job_id):
                return self._fail_job(project, job_id, "RESEARCH_BRIEF_DRIFT", "The research brief changed while evidence was analyzed.", request_id)
            if not self._job_is_active(project, job_id):
                return self.get_job(job_id)
            if self._runtime_exceeded(frozen["startedAt"], frozen["limits"]):
                return self._fail_job(project, job_id, "RESEARCH_RUNTIME_LIMIT", "The research task exceeded its runtime budget.", request_id)
            content = version.bounded_content
            is_integrated_report = source.source_type == "manual" and query_perspectives.get(source.query_id) == "integrated_report"
            if is_integrated_report:
                excerpt = content[:600].strip()
                if excerpt:
                    extracted.append((version, 0, {"evidence": [{
                        "claimType": "inference",
                        "claim": "A user-supplied external research report was provided for human review.",
                        "excerpt": excerpt,
                        "locator": {"start": 0, "end": len(excerpt)},
                        "confidence": 0.45,
                    }]}))
                    external_reports.append({"sourceVersionId": version.id, "title": source.title, "reportContent": content[:6000]})
                continue
            chunks = [(0, content)] if not is_integrated_report else [(offset, content[offset:offset + 4000]) for offset in range(0, len(content), 4000)]
            for offset, source_content in chunks:
                output, _ = self._complete_model_json(
                    project,
                    "research_analyst",
                    "research_analyst:evidence",
                    request_id,
                    "Extract at most two short evidence items. Each item needs claimType (fact/opinion/inference), claim, excerpt copied exactly from sourceContent, locator start/end offsets, confidence 0..1, and perspectives. Do not reproduce long text or invent evidence.",
                    {"phase14Step": "evidence", "sourceVersionId": version.id, "sourceContent": source_content},
                    budget_job_id=job_id,
                    max_output_tokens=1800,
                    max_retries=0,
                )
                extracted.append((version, offset, output))
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = session.get(ResearchJob, job_id)
            assert job
            if job.status == "cancelled":
                return self._job_dict(job)
            if job.revision != frozen["revision"] or job.brief_checksum != frozen["briefChecksum"]:
                return self._fail_job_in_session(session, job, "RESEARCH_BRIEF_DRIFT", "Research changed while evidence was analyzed.", request_id)
            job.status, job.updated_at = "analyzing", _now()
            evidence_rows: list[ResearchEvidence] = []
            for version, offset, output in extracted:
                for raw in output.get("evidence", []) if isinstance(output.get("evidence"), list) else []:
                    if not isinstance(raw, dict):
                        continue
                    excerpt = str(raw.get("excerpt") or "").strip()[:600]
                    start = raw.get("locator", {}).get("start") if isinstance(raw.get("locator"), dict) else None
                    end = raw.get("locator", {}).get("end") if isinstance(raw.get("locator"), dict) else None
                    if isinstance(start, int):
                        start += offset
                    if isinstance(end, int):
                        end += offset
                    if not excerpt or excerpt not in version.bounded_content or not isinstance(start, int) or not isinstance(end, int) or start < 0 or end > len(version.bounded_content) or version.bounded_content[start:end] != excerpt:
                        continue
                    existing = session.scalar(select(ResearchEvidence).where(ResearchEvidence.source_version_id == version.id, ResearchEvidence.excerpt == excerpt))
                    if existing:
                        evidence_rows.append(existing)
                        continue
                    claim_type = str(raw.get("claimType") or "inference")
                    if claim_type not in {"fact", "opinion", "inference"}:
                        continue
                    row = ResearchEvidence(id=str(uuid4()), project_id=project.id, job_id=job.id, source_id=version.source_id, source_version_id=version.id, claim_type=claim_type, claim=str(raw.get("claim") or "").strip()[:1000], excerpt=excerpt, locator_json=dumps({"start": start, "end": end}), confidence=max(0.0, min(1.0, float(raw.get("confidence", 0.0)))), checksum=stable_digest({"claim": raw.get("claim"), "excerpt": excerpt}), created_at=_now())
                    session.add(row)
                    evidence_rows.append(row)
            session.flush()
            evidence_payload = [self._evidence_dict(row) for row in evidence_rows]
        if self._job_has_brief_drift(project, job_id):
            return self._fail_job(project, job_id, "RESEARCH_BRIEF_DRIFT", "The research brief changed before report analysis.", request_id)
        if not self._job_is_active(project, job_id):
            return self.get_job(job_id)
        report, _ = self._complete_model_json(
            project,
            "research_analyst",
            "research_analyst:report",
            request_id,
            "Analyze supplied short evidence into at most two competitor profiles and four concise research findings. External research reports are user-supplied secondary material: do not turn them into verified facts, and mark conclusions based on them as inference or opinion with uncertainties. Facts must cite evidenceIds; unsupported items must be inference with uncertainties. Do not imitate authors or reconstruct source text.",
            {"phase14Step": "research_report", "evidence": evidence_payload, "sources": [{"id": source.id, "title": source.title, "domain": source.domain} for source in sources.values()], "externalReports": external_reports},
            budget_job_id=job_id,
            max_output_tokens=4096,
        )
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = session.get(ResearchJob, job_id)
            assert job
            if job.status == "cancelled" or job.revision != frozen["revision"] or job.brief_checksum != frozen["briefChecksum"]:
                return self._fail_job_in_session(session, job, "RESEARCH_BRIEF_DRIFT", "Research changed while the report was analyzed.", request_id)
            report_revision = job.report_revision + 1
            evidence_ids = {row.id for row in session.scalars(select(ResearchEvidence).where(ResearchEvidence.job_id == job.id)).all()}
            for raw in report.get("competitors", []) if isinstance(report.get("competitors"), list) else []:
                if not isinstance(raw, dict):
                    continue
                refs = set(raw.get("evidenceIds", []))
                if not refs or not refs.issubset(evidence_ids):
                    continue
                profile = raw.get("profile") if isinstance(raw.get("profile"), dict) else {}
                name = str(raw.get("name") or "").strip()[:240]
                if name:
                    session.add(CompetitorProfile(id=str(uuid4()), project_id=project.id, job_id=job.id, report_revision=report_revision, name=name, profile_json=dumps(profile), evidence_ids_json=dumps(sorted(refs)), confidence=max(0.0, min(1.0, float(raw.get("confidence", 0.0)))), checksum=stable_digest({"name": name, "profile": profile, "evidence": sorted(refs)}), status="active", revision=1, created_at=_now(), updated_at=_now()))
            for raw in report.get("findings", []) if isinstance(report.get("findings"), list) else []:
                if not isinstance(raw, dict):
                    continue
                refs = set(raw.get("evidenceIds", []))
                claim_type = str(raw.get("claimType") or "inference")
                if not refs.issubset(evidence_ids):
                    continue
                if claim_type == "fact" and not refs:
                    continue
                uncertainties = raw.get("uncertainties", [])
                if claim_type in {"opinion", "inference"} and not uncertainties:
                    continue
                statement = str(raw.get("statement") or "").strip()[:2000]
                if not statement:
                    continue
                session.add(ResearchFinding(id=str(uuid4()), project_id=project.id, job_id=job.id, report_revision=report_revision, category=str(raw.get("category") or "general")[:80], statement=statement, claim_type=claim_type if claim_type in {"fact", "opinion", "inference"} else "inference", evidence_ids_json=dumps(sorted(refs)), confidence=max(0.0, min(1.0, float(raw.get("confidence", 0.0)))), uncertainties_json=dumps(uncertainties), checksum=stable_digest(raw), status="active", revision=1, created_at=_now()))
            source_types = sorted({source.source_type for source in sources.values() if source.status == "fetched" and not source.excluded})
            limits = safe_json_loads(job.limits_json, {})
            evidence_sources = {row.source_id for row in session.scalars(select(ResearchEvidence).where(ResearchEvidence.job_id == job.id)).all()}
            evidence_query_ids = {source.query_id for source in sources.values() if source.id in evidence_sources and source.query_id}
            evidence_perspectives = sorted({query.perspective for query in session.scalars(select(ResearchQuery).where(ResearchQuery.job_id == job.id, ResearchQuery.id.in_(evidence_query_ids))).all()}) if evidence_query_ids else []
            query_rows = list(session.scalars(select(ResearchQuery).where(ResearchQuery.job_id == job.id)).all())
            source_counts = {query_id: count for query_id, count in session.execute(select(ResearchSource.query_id, func.count(ResearchSource.id)).where(ResearchSource.job_id == job.id).group_by(ResearchSource.query_id)).all()}
            manual_report_query_ids = {query.id for query in query_rows if query.perspective == "integrated_report"}
            integrated_report_evidence = any(source.query_id in manual_report_query_ids for source in sources.values() if source.id in evidence_sources)
            coverage = {
                "sourceTypes": source_types,
                "sourceTypeCount": len(source_types),
                "evidenceCount": len(evidence_ids),
                "minimumSourceTypes": int(limits.get("minimumSourceTypes", 3)),
                "coveredPerspectives": sorted({query.perspective for query in query_rows if query.status == "succeeded"}),
                "evidencePerspectives": evidence_perspectives,
                "searchResultCount": sum(query.result_count for query in query_rows),
                "discoveredSourceCount": sum(source_counts.get(query.id, 0) for query in query_rows),
                "failedQueryCount": sum(1 for query in query_rows if query.status == "failed"),
                "failedFetchCount": sum(1 for source in sources.values() if source.status == "failed"),
                "manualSourceCount": sum(1 for source in sources.values() if source.status == "fetched" and source.source_type == "manual" and not source.excluded),
                "integratedManualReportEvidence": integrated_report_evidence,
            }
            standard_coverage = len(source_types) >= coverage["minimumSourceTypes"] and set(evidence_perspectives) == set(PERSPECTIVES)
            manual_coverage = coverage["manualSourceCount"] >= len(PERSPECTIVES) and set(evidence_perspectives) == set(PERSPECTIVES)
            integrated_report_coverage = integrated_report_evidence and bool(evidence_ids)
            coverage["manualCoverageMet"] = manual_coverage or integrated_report_coverage
            coverage["integratedManualReportCoverageMet"] = integrated_report_coverage
            job.coverage_json, job.report_revision = dumps(coverage), report_revision
            job.report_checksum = stable_digest({"job": job.id, "reportRevision": report_revision, "coverage": coverage, "evidence": sorted(evidence_ids)})
            enough = standard_coverage or manual_coverage or integrated_report_coverage
            job.status, job.completed_at, job.updated_at, job.revision = ("awaiting_review" if enough else "insufficient_evidence"), _now(), _now(), job.revision + 1
            session.add(self.service._audit("research_job.awaiting_review" if enough else "research_job.insufficient_evidence", "research_job", job.id, coverage, request_id))
            return self._job_dict(job)

    def _analyze_job_placeholder(self, project: Any, job_id: str, request_id: str) -> dict[str, Any]:
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = session.get(ResearchJob, job_id)
            assert job
            if job.status == "cancelled":
                return self._job_dict(job)
            job.status, job.updated_at = "analyzing", _now()
            report_revision = job.report_revision + 1
            versions = session.scalars(select(ResearchSourceVersion).where(ResearchSourceVersion.job_id == job.id)).all()
            sources = {source.id: source for source in session.scalars(select(ResearchSource).where(ResearchSource.job_id == job.id)).all()}
            evidence_ids: list[str] = []
            for version in versions:
                if not version.bounded_content:
                    continue
                existing = session.scalar(select(ResearchEvidence).where(ResearchEvidence.source_version_id == version.id))
                if existing:
                    evidence_ids.append(existing.id)
                    continue
                excerpt = version.bounded_content[:600].strip()
                if not excerpt:
                    continue
                claim = f"Public source {sources[version.source_id].domain} contains material relevant to the research scope."
                evidence = ResearchEvidence(id=str(uuid4()), project_id=project.id, job_id=job.id, source_id=version.source_id, source_version_id=version.id, claim_type="fact", claim=claim, excerpt=excerpt, locator_json=dumps({"start": 0, "end": len(excerpt)}), confidence=0.5, checksum=stable_digest({"claim": claim, "excerpt": excerpt}), created_at=_now())
                session.add(evidence)
                evidence_ids.append(evidence.id)
            for source in sources.values():
                if source.status != "fetched" or source.excluded:
                    continue
                existing = session.scalar(select(CompetitorProfile).where(
                    CompetitorProfile.job_id == job.id,
                    CompetitorProfile.name == source.title,
                    CompetitorProfile.report_revision == report_revision,
                ))
                if existing:
                    continue
                source_evidence = [item.id for item in session.scalars(select(ResearchEvidence).where(ResearchEvidence.source_id == source.id)).all()]
                profile = {
                    "readingPromise": "Bounded public-source research only.",
                    "targetReader": "notEstablished",
                    "openingHook": "notEstablished",
                    "protagonistDesire": "notEstablished",
                    "emotionalPayoff": "notEstablished",
                    "worldDistinctiveness": "notEstablished",
                    "serialEngine": "notEstablished",
                    "phaseSatisfaction": "notEstablished",
                    "praiseReasons": [],
                    "dropoffReasons": [],
                    "risks": ["No unsupported reconstruction or imitation."],
                }
                session.add(CompetitorProfile(
                    id=str(uuid4()), project_id=project.id, job_id=job.id, report_revision=report_revision,
                    name=source.title or source.domain, profile_json=dumps(profile), evidence_ids_json=dumps(source_evidence),
                    confidence=0.3 if source_evidence else 0.0, checksum=stable_digest({"source": source.id, "profile": profile}),
                    status="active", revision=1, created_at=_now(), updated_at=_now(),
                ))
            findings = [
                ("platform_trends", "Research coverage is bounded to the saved public-source scope."),
                ("opening_strategy", "Opening conclusions require linked public evidence and remain inference."),
            ]
            for category, statement in findings:
                existing = session.scalar(select(ResearchFinding).where(
                    ResearchFinding.job_id == job.id,
                    ResearchFinding.report_revision == report_revision,
                    ResearchFinding.category == category,
                ))
                if not existing:
                    session.add(ResearchFinding(
                        id=str(uuid4()), project_id=project.id, job_id=job.id, report_revision=report_revision,
                        category=category, statement=statement, claim_type="inference", evidence_ids_json=dumps(evidence_ids),
                        confidence=0.5 if evidence_ids else 0.0, uncertainties_json=dumps(["Requires human review."]),
                        checksum=stable_digest({"category": category, "statement": statement, "evidence": evidence_ids}),
                        status="active", revision=1, created_at=_now(),
                    ))
            source_types = sorted({source.source_type for source in sources.values() if source.status == "fetched" and not source.excluded})
            limits = safe_json_loads(job.limits_json, {})
            coverage = {"sourceTypes": source_types, "sourceTypeCount": len(source_types), "evidenceCount": len(evidence_ids), "minimumSourceTypes": int(limits.get("minimumSourceTypes", 3)), "coveredPerspectives": sorted({query.perspective for query in session.scalars(select(ResearchQuery).where(ResearchQuery.job_id == job.id, ResearchQuery.status == "succeeded")).all()})}
            job.coverage_json = dumps(coverage)
            job.report_revision = report_revision
            job.report_checksum = stable_digest({"job": job.id, "reportRevision": report_revision, "coverage": coverage, "evidence": sorted(evidence_ids)})
            enough = len(source_types) >= coverage["minimumSourceTypes"] and len(evidence_ids) >= len(PERSPECTIVES)
            job.status = "awaiting_review" if enough else "insufficient_evidence"
            job.completed_at, job.updated_at, job.revision = _now(), _now(), job.revision + 1
            event = "research_job.awaiting_review" if enough else "research_job.insufficient_evidence"
            session.add(self.service._audit(event, "research_job", job.id, coverage, request_id))
            return self._job_dict(job)

    # ------------------------------------------------------------------
    # Findings, competitors, and opportunities
    # ------------------------------------------------------------------
    def list_sources(self, job_id: str) -> list[dict[str, Any]]:
        project, _ = self._project_for_job(job_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            versions = session.scalars(select(ResearchSourceVersion).where(ResearchSourceVersion.job_id == job_id).order_by(ResearchSourceVersion.version_number)).all()
            by_source: dict[str, list[ResearchSourceVersion]] = {}
            for version in versions:
                by_source.setdefault(version.source_id, []).append(version)
            return [self._source_dict(source, by_source.get(source.id, [])) for source in session.scalars(select(ResearchSource).where(ResearchSource.job_id == job_id).order_by(ResearchSource.created_at)).all()]

    def list_queries(self, job_id: str) -> list[dict[str, Any]]:
        project, _ = self._project_for_job(job_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._query_dict(item) for item in session.scalars(select(ResearchQuery).where(ResearchQuery.job_id == job_id).order_by(ResearchQuery.sequence_number, ResearchQuery.created_at)).all()]

    def add_manual_material(self, job_id: str, payload: Any, request_id: str) -> dict[str, Any]:
        """Store user-supplied research as a versioned, auditable source.

        Manual material is intentionally never fetched.  It is only eligible
        for the same extraction and approval pipeline used by public sources.
        """
        project, _ = self._project_for_job(job_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = session.get(ResearchJob, job_id)
            assert job
            self._expect_revision(job, payload.expected_revision, "RESEARCH_JOB_REVISION_CONFLICT")
            if job.status not in {"failed", "cancelled", "insufficient_evidence", "awaiting_review"}:
                raise StoryError(409, "RESEARCH_MANUAL_MATERIAL_NOT_ALLOWED", "Manual material can only be added to a stopped research job.")
            if not self._brief_matches_job(session, job):
                raise StoryError(409, "RESEARCH_BRIEF_DRIFT", "The research brief changed and this job can no longer accept material.")
            limits = safe_json_loads(job.limits_json, {})
            content = str(payload.content).strip()[:int(limits.get("maxCharsPerPage", 20_000))]
            now = _now()
            source_id = str(uuid4())
            perspective = payload.perspective or "integrated_report"
            source_url = str(payload.source_url or "").strip()
            canonical = ResearchSourcePolicy().validate_url(source_url) if source_url else f"manual://research/{source_id}"
            if session.scalar(select(ResearchSource.id).where(ResearchSource.job_id == job.id, ResearchSource.canonical_url == canonical)):
                raise StoryError(409, "RESEARCH_MANUAL_SOURCE_DUPLICATE", "This source is already attached to the research job.")
            domain = urlsplit(canonical).hostname or "manual-entry"
            query = ResearchQuery(
                id=str(uuid4()), project_id=project.id, job_id=job.id, attempt=job.attempt,
                perspective=perspective, query_text=f"Manual research: {payload.title}"[:1000],
                sequence_number=(session.scalar(select(func.max(ResearchQuery.sequence_number)).where(ResearchQuery.job_id == job.id)) or 0) + 1,
                fingerprint=stable_digest({"manual": True, "perspective": perspective, "title": payload.title, "content": content}),
                status="succeeded", result_count=1, created_at=now, completed_at=now,
                provider_metadata_json=dumps({"origin": "manual", "kind": "integrated_report" if payload.perspective is None else "perspective_material"}),
            )
            source = ResearchSource(
                id=source_id, project_id=project.id, job_id=job.id, query_id=query.id,
                canonical_url=canonical, title=str(payload.title).strip(), domain=domain,
                source_type="manual", provider_metadata_json=dumps({"origin": "manual", "kind": "integrated_report" if payload.perspective is None else "perspective_material", "sourceUrlProvided": bool(source_url)}),
                status="fetched", created_at=now, updated_at=now,
            )
            version = ResearchSourceVersion(
                id=str(uuid4()), project_id=project.id, job_id=job.id, source_id=source.id, version_number=1,
                final_url=canonical, content_checksum=stable_digest({"url": canonical, "content": content}),
                bounded_content=content, summary="User-supplied research material.", char_count=len(content), truncated=len(content) < len(str(payload.content).strip()),
                fetch_metadata_json=dumps({"origin": "manual"}), fetched_at=now,
            )
            session.add_all([query, source, version])
            job.query_count += 1
            job.page_count += 1
            job.fetched_chars += len(content)
            job.status, job.error_code, job.error_message = "insufficient_evidence", None, None
            job.revision, job.updated_at = job.revision + 1, now
            session.add(self.service._audit("research_manual_material.added", "research_job", job.id, {"sourceId": source.id, "perspective": perspective, "kind": "integrated_report" if payload.perspective is None else "perspective_material", "hasSourceUrl": bool(source_url)}, request_id))
            return self._job_dict(job)

    def analyze_manual_materials(self, job_id: str, payload: Any, request_id: str) -> dict[str, Any]:
        project, _ = self._project_for_job(job_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = session.get(ResearchJob, job_id)
            assert job
            self._expect_revision(job, payload.expected_revision, "RESEARCH_JOB_REVISION_CONFLICT")
            if job.status not in {"failed", "cancelled", "insufficient_evidence", "awaiting_review"}:
                raise StoryError(409, "RESEARCH_MANUAL_ANALYSIS_NOT_ALLOWED", "Manual material can only be analyzed after the research job has stopped.")
            count = session.scalar(select(func.count(ResearchSourceVersion.id)).where(ResearchSourceVersion.job_id == job.id, ResearchSourceVersion.bounded_content != "")) or 0
            if not count:
                raise StoryError(409, "RESEARCH_MANUAL_MATERIAL_REQUIRED", "Add research material before requesting analysis.")
            job.status, job.error_code, job.error_message = "analyzing", None, None
            job.revision, job.updated_at, job.started_at = job.revision + 1, _now(), _now()
            session.add(self.service._audit("research_manual_material.analysis_started", "research_job", job.id, {"sourceVersionCount": count}, request_id))
        try:
            return self._analyze_job(project, job_id, request_id)
        except StoryError as exc:
            return self._fail_job(project, job_id, exc.code, exc.message, request_id)

    def list_evidence(self, job_id: str) -> list[dict[str, Any]]:
        project, _ = self._project_for_job(job_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._evidence_dict(item) for item in session.scalars(select(ResearchEvidence).where(ResearchEvidence.job_id == job_id).order_by(ResearchEvidence.created_at)).all()]

    def list_competitors(self, job_id: str) -> list[dict[str, Any]]:
        project, _ = self._project_for_job(job_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._competitor_dict(item) for item in session.scalars(select(CompetitorProfile).where(CompetitorProfile.job_id == job_id).order_by(CompetitorProfile.created_at)).all()]

    def list_findings(self, job_id: str) -> list[dict[str, Any]]:
        project, _ = self._project_for_job(job_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._finding_dict(item) for item in session.scalars(select(ResearchFinding).where(ResearchFinding.job_id == job_id).order_by(ResearchFinding.created_at)).all()]

    def decide_research_job(self, job_id: str, payload: ResearchJobAction, request_id: str, *, accepted: bool) -> dict[str, Any]:
        project, _ = self._project_for_job(job_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(ResearchJob, job_id)
            assert row
            self._expect_revision(row, payload.expected_revision, "RESEARCH_JOB_REVISION_CONFLICT")
            if row.status != "awaiting_review":
                raise StoryError(409, "RESEARCH_JOB_NOT_AWAITING_REVIEW", "Only evidence-complete research can be accepted or rejected.")
            row.status, row.revision, row.updated_at, row.completed_at = ("accepted" if accepted else "rejected"), row.revision + 1, _now(), _now()
            session.add(self.service._audit(f"research_job.{'accepted' if accepted else 'rejected'}", "research_job", row.id, {}, request_id))
            return self._job_dict(row)

    def exclude_competitor(self, competitor_id: str, payload: CompetitorExclude, request_id: str) -> dict[str, Any]:
        project, competitor = self._project_for_competitor(competitor_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row, job = session.get(CompetitorProfile, competitor.id), session.get(ResearchJob, competitor.job_id)
            assert row and job
            self._expect_revision(row, payload.expected_revision, "COMPETITOR_REVISION_CONFLICT")
            self._expect_revision(job, payload.expected_job_revision, "RESEARCH_JOB_REVISION_CONFLICT")
            next_revision = job.report_revision + 1
            clones: list[CompetitorProfile] = []
            for existing in session.scalars(select(CompetitorProfile).where(
                CompetitorProfile.job_id == job.id,
                CompetitorProfile.report_revision == job.report_revision,
            )).all():
                clone = CompetitorProfile(
                    id=str(uuid4()), project_id=project.id, job_id=job.id,
                    report_revision=next_revision, name=existing.name,
                    profile_json=existing.profile_json, evidence_ids_json=existing.evidence_ids_json,
                    confidence=existing.confidence, excluded=existing.id == row.id,
                    exclusion_reason=payload.reason if existing.id == row.id else None,
                    checksum=existing.checksum, status="excluded" if existing.id == row.id else "active",
                    revision=1, created_at=_now(), updated_at=_now(),
                )
                session.add(clone)
                clones.append(clone)
            for finding in session.scalars(select(ResearchFinding).where(
                ResearchFinding.job_id == job.id,
                ResearchFinding.report_revision == job.report_revision,
            )).all():
                session.add(ResearchFinding(
                    id=str(uuid4()), project_id=project.id, job_id=job.id,
                    report_revision=next_revision, category=finding.category,
                    statement=finding.statement, claim_type=finding.claim_type,
                    evidence_ids_json=finding.evidence_ids_json, confidence=finding.confidence,
                    uncertainties_json=finding.uncertainties_json, checksum=finding.checksum,
                    status=finding.status, revision=1, created_at=_now(),
                ))
            job.report_revision = next_revision
            job.report_checksum = stable_digest({
                "job": job.id,
                "reportRevision": next_revision,
                "competitors": sorted(item.checksum for item in clones if not item.excluded),
            })
            job.revision += 1
            job.updated_at = _now()
            excluded = next(item for item in clones if item.excluded)
            session.add(self.service._audit("competitor.excluded", "competitor_profile", excluded.id, {"reason": payload.reason, "reportRevision": next_revision, "replaces": row.id}, request_id))
            session.flush()
            return self._competitor_dict(excluded)

    def create_opportunities(self, job_id: str, payload: StoryOpportunityCreate, request_id: str) -> list[dict[str, Any]]:
        project, _ = self._project_for_job(job_id)
        generated: list[dict[str, Any]] | None = None
        if payload.opportunities is None:
            with self.service.db.project(project.id, project.folder_path) as session:
                job = session.get(ResearchJob, job_id)
                assert job
                self._expect_revision(job, payload.expected_job_revision, "RESEARCH_JOB_REVISION_CONFLICT")
                if job.status != "accepted":
                    raise StoryError(409, "RESEARCH_NOT_ACCEPTED", "Accept the evidence-complete research report before creating story opportunities.")
                evidence = [self._evidence_dict(item) for item in session.scalars(select(ResearchEvidence).where(ResearchEvidence.job_id == job.id)).all()]
                # Story opportunity generation needs the audited evidence IDs
                # and concise claims, not full source excerpts or project
                # metadata. Keeping this snapshot small avoids needlessly
                # slow model calls while preserving citation validation below.
                report = {
                    "jobId": job.id,
                    "reportRevision": job.report_revision,
                    "reportChecksum": job.report_checksum,
                    "findings": [{
                        "id": item.id,
                        "category": item.category,
                        "statement": item.statement[:600],
                        "claimType": item.claim_type,
                        "evidenceIds": safe_json_loads(item.evidence_ids_json, []),
                        "confidence": item.confidence,
                        "uncertainties": safe_json_loads(item.uncertainties_json, [])[:3],
                    } for item in session.scalars(select(ResearchFinding).where(
                        ResearchFinding.job_id == job.id,
                        ResearchFinding.report_revision == job.report_revision,
                    )).all()],
                    "evidence": [{
                        "id": item["id"],
                        "claimType": item["claimType"],
                        "claim": item["claim"][:600],
                        "confidence": item["confidence"],
                    } for item in evidence],
                }
            generated = []
            for candidate_index in range(1, 4):
                output, _ = self._complete_model_json(
                    project,
                    "story_incubator",
                    "story_incubator:opportunities" if candidate_index == 1 else f"story_incubator:opportunities:{candidate_index}",
                    request_id,
                    "Generate exactly one lightweight story-direction card grounded only in the supplied evidence IDs. This is not a StoryBrief or Canon: do not build a complete world, character bible, plot outline, chapter plan, or ending. It must be substantially different from previousDirections. Return a tentative title under 20 Chinese characters, a two-to-three-sentence summary under 180 Chinese characters, and a one-sentence highConcept under 80 Chinese characters. Keep protagonist, coreDesire, coreConflict, worldMechanism, firstThreeChapterPromise, and serialEngine to one tentative phrase each; use notEstablished when the direction does not need that decision yet. Score components are integers within their documented caps and may total less than 100. Return one item in the opportunities array. Never imitate an author or copy source text.",
                    {
                        "phase14Step": "opportunities",
                        "candidateIndex": candidate_index,
                        "previousDirections": [item.get("highConcept") for item in generated],
                        "report": report,
                        "scoreLimits": SCORE_LIMITS,
                    },
                    max_output_tokens=4096,
                    max_retries=0,
                    stream_response=True,
                )
                candidates = output.get("opportunities") if isinstance(output.get("opportunities"), list) else None
                if not candidates or len(candidates) != 1 or not isinstance(candidates[0], dict):
                    raise StoryError(422, "STORY_OPPORTUNITY_MODEL_INVALID", "The story incubator did not return exactly one opportunity for the requested direction.")
                generated.append(candidates[0])
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = session.get(ResearchJob, job_id)
            assert job
            self._expect_revision(job, payload.expected_job_revision, "RESEARCH_JOB_REVISION_CONFLICT")
            if job.status != "accepted":
                raise StoryError(409, "RESEARCH_NOT_ACCEPTED", "Accept the evidence-complete research report before creating story opportunities.")
            if generated is not None and job.report_checksum != report["reportChecksum"]:
                raise StoryError(409, "RESEARCH_REPORT_DRIFT", "The research report changed while opportunities were generated.")
            drafts = payload.opportunities or generated
            if len(drafts) < 3 or len(drafts) > 5:
                raise StoryError(422, "STORY_OPPORTUNITY_COUNT_INVALID", "Create three to five opportunities.")
            evidence_ids = {item.id for item in session.scalars(select(ResearchEvidence).where(ResearchEvidence.job_id == job.id)).all()}
            rows: list[StoryOpportunity] = []
            for draft_model in drafts:
                draft = draft_model.model_dump(mode="json", by_alias=True) if hasattr(draft_model, "model_dump") else draft_model
                scores, total = self._validate_scores(draft.get("scoreComponents", {}))
                refs = set(draft.get("evidenceIds", []))
                if not refs or not refs.issubset(evidence_ids):
                    raise StoryError(422, "OPPORTUNITY_EVIDENCE_INVALID", "An opportunity references evidence outside this research job.")
                by_component = draft.get("evidenceByComponent", {})
                if not isinstance(by_component, dict):
                    raise StoryError(422, "OPPORTUNITY_EVIDENCE_INVALID", "Opportunity component evidence must be an object.")
                component_refs: set[str] = set()
                for component, raw_refs in by_component.items():
                    if component not in SCORE_LIMITS or not isinstance(raw_refs, list):
                        raise StoryError(422, "OPPORTUNITY_EVIDENCE_INVALID", "Opportunity component evidence is malformed.")
                    values = {str(item) for item in raw_refs}
                    if not values.issubset(evidence_ids):
                        raise StoryError(422, "OPPORTUNITY_EVIDENCE_INVALID", "Opportunity component evidence references another research job.")
                    component_refs.update(values)
                if component_refs and not component_refs.issubset(refs):
                    raise StoryError(422, "OPPORTUNITY_EVIDENCE_INVALID", "Component evidence must also appear in the opportunity evidence list.")
                title = str(draft.get("title") or draft["highConcept"]).strip()[:80]
                summary = str(draft.get("summary") or draft["highConcept"]).strip()[:600]
                story = {key: draft.get(key) for key in ("protagonist", "coreDesire", "coreConflict", "worldMechanism", "firstThreeChapterPromise", "serialEngine", "differentiation", "risks", "evidenceByComponent")}
                story.update({"title": title, "summary": summary})
                checksum = stable_digest({"highConcept": draft["highConcept"], "story": story, "scores": scores, "evidence": sorted(refs), "report": job.report_checksum})
                row = StoryOpportunity(id=str(uuid4()), project_id=project.id, job_id=job.id, report_revision=job.report_revision, report_checksum=job.report_checksum, high_concept=draft["highConcept"], story_json=dumps(story), score_components_json=dumps(scores), total_score=total, evidence_coverage=draft["evidenceCoverage"], confidence=draft["confidence"], uncertainties_json=dumps(draft.get("uncertainties", [])), evidence_ids_json=dumps(sorted(refs)), checksum=checksum, status="pending", is_current=False, revision=1, created_at=_now(), updated_at=_now())
                session.add(row)
                rows.append(row)
            session.add(self.service._audit("story_opportunities.created", "research_job", job.id, {"count": len(rows)}, request_id))
            session.flush()
            return [self._opportunity_dict(row) for row in rows]

    def list_opportunities(self, project_id: str, job_id: str | None = None) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            query = select(StoryOpportunity).where(StoryOpportunity.project_id == project.id)
            if job_id:
                job = session.get(ResearchJob, job_id)
                if not job or job.project_id != project.id:
                    raise StoryError(404, "RESEARCH_JOB_NOT_FOUND", "Research job was not found for this project.")
                query = query.where(StoryOpportunity.job_id == job_id)
            rows = session.scalars(query.order_by(StoryOpportunity.created_at.desc())).all()
            return [self._opportunity_dict(row) for row in rows]

    def decide_opportunity(self, opportunity_id: str, payload: StoryOpportunityAction, request_id: str, *, accepted: bool) -> dict[str, Any]:
        project, opportunity = self._project_for_opportunity(opportunity_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(StoryOpportunity, opportunity.id)
            assert row
            self._expect_revision(row, payload.expected_revision, "STORY_OPPORTUNITY_REVISION_CONFLICT")
            if row.status != "pending":
                raise StoryError(409, "STORY_OPPORTUNITY_NOT_PENDING", "Story opportunity has already been decided.")
            job = session.get(ResearchJob, row.job_id)
            if not job or job.status != "accepted" or job.report_checksum != row.report_checksum or job.report_revision != row.report_revision:
                raise StoryError(409, "RESEARCH_REPORT_DRIFT", "The research report changed after this opportunity was created.")
            now = _now()
            if accepted:
                for current in session.scalars(select(StoryOpportunity).where(StoryOpportunity.project_id == project.id, StoryOpportunity.is_current.is_(True))).all():
                    current.is_current, current.status, current.revision, current.updated_at = False, "superseded", current.revision + 1, now
                row.status, row.is_current = "accepted", True
            else:
                row.status, row.is_current = "rejected", False
            row.revision, row.updated_at, row.decided_at = row.revision + 1, now, now
            session.add(self.service._audit(f"story_opportunity.{'accepted' if accepted else 'rejected'}", "story_opportunity", row.id, {}, request_id))
            return self._opportunity_dict(row)

    # ------------------------------------------------------------------
    # Multi-turn ideation and StoryBrief authority chain
    # ------------------------------------------------------------------
    def create_ideation_session(self, project_id: str, payload: IdeationSessionCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            opportunity = session.get(StoryOpportunity, payload.opportunity_id)
            if not opportunity or opportunity.project_id != project.id or opportunity.status != "accepted" or not opportunity.is_current:
                raise StoryError(404, "ACCEPTED_OPPORTUNITY_NOT_FOUND", "An accepted opportunity is required for an ideation session.")
            self._expect_revision(opportunity, payload.expected_opportunity_revision, "STORY_OPPORTUNITY_REVISION_CONFLICT")
            job = session.get(ResearchJob, opportunity.job_id)
            assert job
            if job.status != "accepted":
                raise StoryError(409, "RESEARCH_NOT_ACCEPTED", "Accept the evidence-complete research report before ideation.")
            state = {"confirmedDecisions": [], "openQuestions": [], "aiSuggestions": [], "conflicts": [], "evidenceIds": safe_json_loads(opportunity.evidence_ids_json, [])}
            row = IdeationSession(id=str(uuid4()), project_id=project.id, opportunity_id=opportunity.id, opportunity_revision=opportunity.revision, opportunity_checksum=opportunity.checksum, research_job_id=job.id, research_report_checksum=job.report_checksum, state_json=dumps(state), status="active", revision=1, created_at=_now(), updated_at=_now())
            session.add(row)
            session.add(self.service._audit("ideation_session.created", "ideation_session", row.id, {}, request_id))
            session.flush()
            return self._session_dict(row, [])

    def list_ideation_sessions(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._session_dict(row, self._session_messages(session, row.id)) for row in session.scalars(select(IdeationSession).where(IdeationSession.project_id == project.id).order_by(IdeationSession.created_at.desc())).all()]

    def get_ideation_session(self, project_id: str, session_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            row = session.get(IdeationSession, session_id)
            if not row or row.project_id != project.id:
                raise StoryError(404, "IDEATION_SESSION_NOT_FOUND", "Ideation session was not found for this project.")
            return self._session_dict(row, self._session_messages(session, row.id))

    def add_ideation_message(self, session_id: str, payload: IdeationMessageCreate, request_id: str) -> dict[str, Any]:
        project, session_row = self._project_for_ideation_session(session_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            row = session.get(IdeationSession, session_row.id)
            assert row
            self._expect_revision(row, payload.expected_session_revision, "IDEATION_SESSION_REVISION_CONFLICT")
            opportunity, job = self._assert_ideation_upstream(session, row)
            frozen_state = safe_json_loads(row.state_json, {})
            messages = self._session_messages(session, row.id)
        output, model_run_id = self._complete_model_json(
            project,
            "story_incubator",
            "story_incubator:ideation",
            request_id,
            "Respond to one creative co-creation turn. Return reply, confirmedDecisions, openQuestions, aiSuggestions, conflicts, and evidenceIds. Keep unsupported assertions uncertain and never treat the response as an accepted StoryBrief.",
            {"phase14Step": "ideation", "userMessage": payload.content, "state": frozen_state, "messages": messages, "opportunity": self._opportunity_dict(opportunity), "researchReportChecksum": job.report_checksum},
        )
        reply = str(output.get("reply") or "").strip()
        if not reply:
            raise StoryError(422, "IDEATION_MODEL_INVALID", "The story incubator did not return a co-creation reply.")
        state = {key: output.get(key, frozen_state.get(key, [])) for key in ("confirmedDecisions", "openQuestions", "aiSuggestions", "conflicts", "evidenceIds")}
        if not all(isinstance(value, list) for value in state.values()):
            raise StoryError(422, "IDEATION_MODEL_INVALID", "The story incubator returned an invalid co-creation state.")
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(IdeationSession, session_row.id)
            assert row
            self._expect_revision(row, payload.expected_session_revision, "IDEATION_SESSION_REVISION_CONFLICT")
            _, job = self._assert_ideation_upstream(session, row)
            job_evidence_ids = set(session.scalars(select(ResearchEvidence.id).where(ResearchEvidence.job_id == job.id)).all())
            state_evidence_ids = {str(item) for item in state["evidenceIds"]}
            if not state_evidence_ids.issubset(job_evidence_ids):
                raise StoryError(422, "IDEATION_EVIDENCE_INVALID", "The co-creation reply references evidence outside its frozen research report.")
            seq = (session.scalar(select(func.max(IdeationMessage.sequence_number)).where(IdeationMessage.session_id == row.id)) or 0) + 1
            user = IdeationMessage(id=str(uuid4()), project_id=project.id, session_id=row.id, sequence_number=seq, role="user", content=payload.content, structured_state_json="{}", evidence_ids_json="[]", created_at=_now())
            session.add(user)
            assistant = IdeationMessage(id=str(uuid4()), project_id=project.id, session_id=row.id, sequence_number=seq + 1, role="assistant", content=reply, structured_state_json=dumps(state), evidence_ids_json=dumps(state["evidenceIds"]), model_run_id=model_run_id, created_at=_now())
            session.add(assistant)
            row.state_json, row.revision, row.updated_at = dumps(state), row.revision + 1, _now()
            session.add(self.service._audit("ideation_message.recorded", "ideation_session", row.id, {}, request_id))
            return self._message_dict(assistant)

    def create_story_brief_proposal(self, session_id: str, payload: StoryBriefProposalCreate, request_id: str) -> dict[str, Any]:
        project, session_row = self._project_for_ideation_session(session_id)
        generated: dict[str, Any] | None = None
        model_run_id: str | None = None
        with self.service.db.project(project.id, project.folder_path) as session:
            row = session.get(IdeationSession, session_row.id)
            assert row
            self._expect_revision(row, payload.expected_session_revision, "IDEATION_SESSION_REVISION_CONFLICT")
            self._assert_ideation_upstream(session, row)
            user_message_count = int(session.scalar(select(func.count()).select_from(IdeationMessage).where(
                IdeationMessage.session_id == row.id,
                IdeationMessage.role == "user",
            )) or 0)
            if user_message_count < 2:
                raise StoryError(
                    409,
                    "IDEATION_DISCUSSION_REQUIRED",
                    "Discuss the selected direction for at least two user turns before freezing a StoryBrief.",
                    {"currentUserTurns": user_message_count, "requiredUserTurns": 2},
                )
        if payload.brief is None:
            with self.service.db.project(project.id, project.folder_path) as session:
                row = session.get(IdeationSession, session_row.id)
                assert row
                self._expect_revision(row, payload.expected_session_revision, "IDEATION_SESSION_REVISION_CONFLICT")
                opportunity, job = self._assert_ideation_upstream(session, row)
                state = safe_json_loads(row.state_json, {})
                messages = self._session_messages(session, row.id)
            output, model_run_id = self._complete_model_json(
                project,
                "story_incubator",
                "story_incubator:story-brief",
                request_id,
                "Generate a complete structured StoryBrief from the accepted opportunity and co-creation session. Do not imitate authors or claim unsupported research facts.",
                {"phase14Step": "story_brief", "projectTitle": project.title, "opportunity": self._opportunity_dict(opportunity), "researchReportChecksum": job.report_checksum, "state": state, "messages": messages},
            )
            generated = output.get("brief") if isinstance(output.get("brief"), dict) else output
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(IdeationSession, session_row.id)
            assert row
            self._expect_revision(row, payload.expected_session_revision, "IDEATION_SESSION_REVISION_CONFLICT")
            opportunity, job = self._assert_ideation_upstream(session, row)
            current = session.scalar(select(StoryBriefVersion).where(StoryBriefVersion.project_id == project.id, StoryBriefVersion.is_current.is_(True)))
            proposed = payload.brief or generated
            if not isinstance(proposed, dict):
                raise StoryError(422, "STORY_BRIEF_MODEL_INVALID", "The story incubator did not return a StoryBrief.")
            self._validate_brief(proposed)
            diff = {"baseVersionId": current.id if current else None, "changedFields": sorted(proposed)}
            proposal = StoryBriefProposal(id=str(uuid4()), project_id=project.id, session_id=row.id, base_brief_version_id=current.id if current else None, opportunity_id=opportunity.id, opportunity_revision=opportunity.revision, opportunity_checksum=opportunity.checksum, research_job_id=job.id, research_report_checksum=job.report_checksum, proposed_brief_json=dumps(proposed), diff_json=dumps(diff), checksum=stable_digest(proposed), model_run_id=model_run_id, status="pending", revision=1, created_at=_now(), updated_at=_now())
            session.add(proposal)
            session.add(self.service._audit("story_brief_proposal.created", "story_brief_proposal", proposal.id, {}, request_id))
            session.flush()
            return self._brief_proposal_dict(proposal)

    def list_story_brief_versions(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._brief_version_dict(row) for row in session.scalars(select(StoryBriefVersion).where(StoryBriefVersion.project_id == project.id).order_by(StoryBriefVersion.version_number.desc())).all()]

    def list_story_brief_proposals(self, project_id: str, session_id: str | None = None) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            query = select(StoryBriefProposal).where(StoryBriefProposal.project_id == project.id)
            if session_id:
                ideation = session.get(IdeationSession, session_id)
                if not ideation or ideation.project_id != project.id:
                    raise StoryError(404, "IDEATION_SESSION_NOT_FOUND", "Ideation session was not found for this project.")
                query = query.where(StoryBriefProposal.session_id == session_id)
            rows = session.scalars(query.order_by(StoryBriefProposal.created_at.desc())).all()
            return [self._brief_proposal_dict(row) for row in rows]

    def current_story_brief(self, project_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            row = session.scalar(select(StoryBriefVersion).where(StoryBriefVersion.project_id == project.id, StoryBriefVersion.is_current.is_(True)))
            if not row:
                raise StoryError(404, "STORY_BRIEF_NOT_FOUND", "No accepted StoryBrief exists for this project.")
            return self._brief_version_dict(row)

    def decide_story_brief_proposal(self, proposal_id: str, payload: StoryBriefProposalAction, request_id: str, *, accepted: bool) -> dict[str, Any]:
        project, candidate = self._project_for_brief_proposal(proposal_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(StoryBriefProposal, candidate.id)
            assert row
            self._expect_revision(row, payload.expected_revision, "STORY_BRIEF_PROPOSAL_REVISION_CONFLICT")
            if row.status != "pending":
                raise StoryError(409, "STORY_BRIEF_PROPOSAL_NOT_PENDING", "StoryBrief proposal has already been decided.")
            opportunity = session.get(StoryOpportunity, row.opportunity_id)
            job = session.get(ResearchJob, row.research_job_id)
            if not opportunity or not job or opportunity.status != "accepted" or not opportunity.is_current or job.status != "accepted" or opportunity.checksum != row.opportunity_checksum or opportunity.revision != row.opportunity_revision or job.report_checksum != row.research_report_checksum:
                raise StoryError(409, "STORY_BRIEF_UPSTREAM_DRIFT", "StoryBrief proposal upstream authority changed.")
            now = _now()
            if accepted:
                for current in session.scalars(select(StoryBriefVersion).where(StoryBriefVersion.project_id == project.id, StoryBriefVersion.is_current.is_(True))).all():
                    current.is_current = False
                    current.revision += 1
                number = (session.scalar(select(func.max(StoryBriefVersion.version_number)).where(StoryBriefVersion.project_id == project.id)) or 0) + 1
                version = StoryBriefVersion(id=str(uuid4()), project_id=project.id, session_id=row.session_id, proposal_id=row.id, opportunity_id=row.opportunity_id, opportunity_checksum=row.opportunity_checksum, research_job_id=row.research_job_id, research_report_checksum=row.research_report_checksum, version_number=number, brief_json=row.proposed_brief_json, checksum=row.checksum, is_current=True, revision=1, created_at=now, accepted_at=now)
                session.add(version)
                row.status, row.applied_at = "accepted", now
            else:
                row.status, row.rejected_at = "rejected", now
            row.revision, row.updated_at = row.revision + 1, now
            session.add(self.service._audit(f"story_brief_proposal.{'accepted' if accepted else 'rejected'}", "story_brief_proposal", row.id, {}, request_id))
            return self._brief_proposal_dict(row)

    # ------------------------------------------------------------------
    # Generic canon proposal and opening candidates
    # ------------------------------------------------------------------
    def create_canon_proposal(self, project_id: str, payload: IncubationCanonProposalCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            brief = session.scalar(select(StoryBriefVersion).where(StoryBriefVersion.project_id == project.id, StoryBriefVersion.is_current.is_(True)))
            if not brief:
                raise StoryError(409, "STORY_BRIEF_NOT_ACCEPTED", "An accepted StoryBrief is required before creating a Canon draft.")
            self._expect_revision(brief, payload.expected_story_brief_revision, "STORY_BRIEF_REVISION_CONFLICT")
            opportunity, job, doc = session.get(StoryOpportunity, brief.opportunity_id), session.get(ResearchJob, brief.research_job_id), session.get(CanonDocument, "story-core")
            if not opportunity or not job or not doc or opportunity.status != "accepted" or not opportunity.is_current or job.status != "accepted" or opportunity.checksum != brief.opportunity_checksum or job.report_checksum != brief.research_report_checksum:
                raise StoryError(409, "CANON_UPSTREAM_DRIFT", "The accepted StoryBrief upstream authority changed.")
            brief_data = safe_json_loads(brief.brief_json, {})
            frozen = {"briefId": brief.id, "briefRevision": brief.revision, "briefChecksum": brief.checksum, "opportunityId": opportunity.id, "reportChecksum": job.report_checksum, "canonRevision": doc.revision}
        output, model_run_id = self._complete_model_json(
            project,
            "story_incubator",
            "story_incubator:canon",
            request_id,
            "Generate a generic story Canon proposal. Return markdown, structured (entities, relations, rules), and do not introduce named-author imitation, Night Watch residue, forced power systems, or chapter plans.",
            {"phase14Step": "canon", "storyBrief": brief_data, "instructions": payload.instructions},
        )
        markdown, generated_structured = str(output.get("markdown") or "").strip(), output.get("structured")
        if not markdown or not isinstance(generated_structured, dict):
            raise StoryError(422, "CANON_MODEL_INVALID", "The story incubator did not return a Canon proposal.")
        analyzed, _ = self._complete_model_json(
            project,
            "research_analyst",
            "research_analyst:canon-analyzer",
            request_id,
            "Independently extract the supplied Canon into structured entities, relations, and rules. Preserve only claims present in the Canon. Return structured only.",
            {"phase14Step": "canon_analyze", "storyBrief": brief_data, "canonMarkdown": markdown},
        )
        structured = analyzed.get("structured") if isinstance(analyzed.get("structured"), dict) else analyzed
        structured = structured if isinstance(structured, dict) else {}
        structured["_generationCrossCheck"] = self._canon_cross_check(generated_structured, structured)
        readiness = self._generic_canon_checks(markdown, structured, brief_data)
        if not readiness["ready"]:
            missing = [item["code"] for item in readiness["checks"] if item["status"] == "blocked"]
            repaired, _ = self._complete_model_json(
                project,
                "story_incubator",
                "story_incubator:canon-repair",
                request_id,
                "Repair only the listed Canon completeness failures. Return the complete markdown and structured entities, relations, and rules. Do not add unrelated systems or chapter plans.",
                {"phase14Step": "canon_repair", "missingChecks": missing, "storyBrief": brief_data, "markdown": markdown, "structured": generated_structured},
            )
            repaired_markdown = str(repaired.get("markdown") or "").strip()
            repaired_structured = repaired.get("structured")
            if repaired_markdown and isinstance(repaired_structured, dict):
                markdown, generated_structured = repaired_markdown, repaired_structured
                analyzed, _ = self._complete_model_json(
                    project,
                    "research_analyst",
                    "research_analyst:canon-analyzer-recheck",
                    request_id,
                    "Independently extract the supplied Canon into structured entities, relations, and rules. Preserve only claims present in the Canon. Return structured only.",
                    {"phase14Step": "canon_analyze", "storyBrief": brief_data, "canonMarkdown": markdown},
                )
                structured = analyzed.get("structured") if isinstance(analyzed.get("structured"), dict) else analyzed
                structured = structured if isinstance(structured, dict) else {}
                structured["_generationCrossCheck"] = self._canon_cross_check(generated_structured, structured)
                readiness = self._generic_canon_checks(markdown, structured, brief_data)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            brief = session.scalar(select(StoryBriefVersion).where(StoryBriefVersion.project_id == project.id, StoryBriefVersion.is_current.is_(True)))
            if not brief or brief.id != frozen["briefId"] or brief.revision != frozen["briefRevision"] or brief.checksum != frozen["briefChecksum"]:
                raise StoryError(409, "CANON_STORY_BRIEF_DRIFT", "The StoryBrief changed while the Canon proposal was generated.")
            opportunity = session.get(StoryOpportunity, brief.opportunity_id)
            job = session.get(ResearchJob, brief.research_job_id)
            if not opportunity or not job or opportunity.id != frozen["opportunityId"] or opportunity.status != "accepted" or not opportunity.is_current or job.status != "accepted" or job.report_checksum != frozen["reportChecksum"]:
                raise StoryError(409, "CANON_UPSTREAM_DRIFT", "The accepted StoryBrief upstream authority changed.")
            doc = session.get(CanonDocument, "story-core")
            if not doc or doc.revision != frozen["canonRevision"]:
                raise StoryError(409, "CANON_REVISION_CONFLICT", "Canon changed while the proposal was generated.")
            metadata = {"incubation": True, "storyBriefVersionId": brief.id, "storyBriefRevision": brief.revision, "storyBriefChecksum": brief.checksum, "opportunityId": opportunity.id, "researchReportChecksum": job.report_checksum, "brief": brief_data}
            proposal = CanonGenerationProposal(id=str(uuid4()), project_id=project.id, base_revision=doc.revision, status="pending" if readiness["ready"] else "failed", brief_json=dumps(metadata), content_markdown=markdown, structured_json=dumps(structured), readiness_json=dumps(readiness), model_run_id=model_run_id, revision=1, created_at=_now(), updated_at=_now())
            session.add(proposal)
            session.add(self.service._audit("incubation_canon_proposal.created", "canon_generation_proposal", proposal.id, {"storyBriefVersionId": brief.id}, request_id))
            session.flush()
            return self.service.phase8._canon_proposal_dict(proposal)

    def assert_canon_proposal_upstream(self, session: Any, proposal: CanonGenerationProposal) -> None:
        """Validate the frozen Phase 13 authority at Canon apply time."""
        metadata = safe_json_loads(proposal.brief_json, {})
        if not metadata.get("incubation"):
            return
        brief_id = metadata.get("storyBriefVersionId")
        brief = session.get(StoryBriefVersion, brief_id) if isinstance(brief_id, str) else None
        if not brief or not brief.is_current or brief.revision != metadata.get("storyBriefRevision") or brief.checksum != metadata.get("storyBriefChecksum"):
            raise StoryError(409, "CANON_STORY_BRIEF_DRIFT", "The StoryBrief changed after this Canon draft was created.")
        opportunity = session.get(StoryOpportunity, brief.opportunity_id)
        job = session.get(ResearchJob, brief.research_job_id)
        if not opportunity or not opportunity.is_current or opportunity.status != "accepted" or not job or job.status != "accepted" or job.report_checksum != metadata.get("researchReportChecksum"):
            raise StoryError(409, "CANON_RESEARCH_DRIFT", "The research authority changed after this Canon draft was created.")

    def create_opening_experiment(self, project_id: str, payload: OpeningExperimentCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            brief = session.scalar(select(StoryBriefVersion).where(StoryBriefVersion.project_id == project.id, StoryBriefVersion.is_current.is_(True)))
            doc = session.get(CanonDocument, "story-core")
            if not brief or not doc:
                raise StoryError(409, "OPENING_UPSTREAM_MISSING", "An accepted StoryBrief and Canon draft are required.")
            self._expect_revision(brief, payload.expected_story_brief_revision, "STORY_BRIEF_REVISION_CONFLICT")
            self._expect_revision(doc, payload.expected_canon_revision, "CANON_REVISION_CONFLICT")
            if doc.status == "locked":
                raise StoryError(409, "OPENING_CANON_LOCKED", "Opening candidates must be explored before Canon is locked.")
            strategies = [item.model_dump(mode="json", by_alias=True) for item in payload.strategies] if payload.strategies else DEFAULT_OPENING_STRATEGIES
            if len({item["key"] for item in strategies}) != 3:
                raise StoryError(422, "OPENING_STRATEGIES_INVALID", "Opening experiment requires three distinct strategies.")
            frozen = {"briefId": brief.id, "briefRevision": brief.revision, "briefChecksum": brief.checksum, "canonRevision": doc.revision, "canonChecksum": stable_digest({"markdown": doc.content_markdown, "revision": doc.revision})}
            brief_data, canon_markdown = safe_json_loads(brief.brief_json, {}), doc.content_markdown
        generated: list[tuple[dict[str, Any], dict[str, Any], str, list[tuple[str, dict[str, Any], str]]]] = []
        for strategy in strategies:
            output, run_id = self._complete_model_json(project, "story_incubator", f"story_incubator:opening:{strategy['key']}", request_id, "Write one distinct first chapter for the given opening strategy. Return chapter with title and content only. Respect the StoryBrief word range and Canon. Do not imitate authors or reuse source text.", {"phase14Step": "opening", "strategy": strategy, "storyBrief": brief_data, "canonMarkdown": canon_markdown[:8000]})
            chapter = output.get("chapter") if isinstance(output.get("chapter"), dict) else output
            content = str(chapter.get("content") or "").strip() if isinstance(chapter, dict) else ""
            title = str(chapter.get("title") or strategy["label"]).strip() if isinstance(chapter, dict) else ""
            if not content:
                raise StoryError(422, "OPENING_MODEL_INVALID", "The story incubator did not return an opening chapter.")
            self._validate_opening_content(content, brief_data)
            chapter = {"chapterNumber": 1, "title": title[:300], "content": content, "manualApproved": False}
            reviews: list[tuple[str, dict[str, Any], str]] = []
            for role in ("reader_simulator", "opening_editor"):
                review, review_run_id = self._complete_model_json(project, role, f"{role}:opening-review", request_id, "Independently review this opening. Return scores, findings with source ranges and suggestions, recommendation, and summary. Do not read another reviewer and do not use fixed scores.", {"phase14Step": "opening_review", "strategy": strategy, "chapter": chapter, "storyBrief": brief_data})
                if not isinstance(review.get("scores"), dict) or not str(review.get("summary") or "").strip():
                    raise StoryError(422, "OPENING_REVIEW_MODEL_INVALID", "The opening reviewer did not return a valid review.")
                self._validate_opening_review(review, content)
                reviews.append((role, review, review_run_id))
            generated.append((strategy, chapter, run_id, reviews))
        contents = [item[1]["content"] for item in generated]
        if any(self._opening_similarity(contents[left], contents[right]) >= 0.85 for left in range(len(contents)) for right in range(left + 1, len(contents))):
            raise StoryError(422, "OPENING_CANDIDATES_NOT_DISTINCT", "Opening candidates are too similar to be meaningful alternatives.")
        with self.service.db.project_write(project.id, project.folder_path) as session:
            brief = session.scalar(select(StoryBriefVersion).where(StoryBriefVersion.project_id == project.id, StoryBriefVersion.is_current.is_(True)))
            doc = session.get(CanonDocument, "story-core")
            if not brief or not doc or brief.id != frozen["briefId"] or brief.revision != frozen["briefRevision"] or brief.checksum != frozen["briefChecksum"] or doc.revision != frozen["canonRevision"] or stable_digest({"markdown": doc.content_markdown, "revision": doc.revision}) != frozen["canonChecksum"]:
                raise StoryError(409, "OPENING_UPSTREAM_DRIFT", "StoryBrief or Canon changed while openings were generated.")
            canon_checksum = frozen["canonChecksum"]
            experiment = OpeningExperiment(id=str(uuid4()), project_id=project.id, story_brief_version_id=brief.id, story_brief_revision=brief.revision, story_brief_checksum=brief.checksum, canon_document_id=doc.id, canon_revision=doc.revision, canon_checksum=canon_checksum, strategies_json=dumps(strategies), status="generating", revision=1, created_at=_now(), updated_at=_now())
            session.add(experiment)
            for strategy, chapter, run_id, reviews in generated:
                candidate = OpeningCandidate(id=str(uuid4()), project_id=project.id, experiment_id=experiment.id, strategy_key=strategy["key"], strategy_label=strategy["label"], strategy_json=dumps(strategy), chapters_json=dumps([chapter]), chapter_count=1, text_checksum=stable_digest(chapter), model_run_id=run_id, status="candidate", revision=1, created_at=_now(), updated_at=_now())
                session.add(candidate)
                for role, review, review_run_id in reviews:
                    scores, findings = review["scores"], review.get("findings", [])
                    session.add(ReaderEvaluation(id=str(uuid4()), project_id=project.id, experiment_id=experiment.id, candidate_id=candidate.id, reviewer_role=role, scores_json=dumps(scores), findings_json=dumps(findings if isinstance(findings, list) else []), recommendation=str(review.get("recommendation") or "revise")[:40], summary=str(review["summary"])[:4000], model_run_id=review_run_id, checksum=stable_digest({"role": role, "scores": scores, "findings": findings}), created_at=_now()))
            experiment.status, experiment.revision, experiment.updated_at = "awaiting_selection", 2, _now()
            session.add(self.service._audit("opening_experiment.created", "opening_experiment", experiment.id, {"strategies": [item["key"] for item in strategies]}, request_id))
            session.flush()
            return self._experiment_dict(session, experiment)

    def list_opening_experiments(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._experiment_dict(session, row) for row in session.scalars(select(OpeningExperiment).where(OpeningExperiment.project_id == project.id).order_by(OpeningExperiment.created_at.desc())).all()]

    def get_opening_experiment(self, experiment_id: str) -> dict[str, Any]:
        project, experiment = self._project_for_experiment(experiment_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            row = session.get(OpeningExperiment, experiment.id)
            assert row
            return self._experiment_dict(session, row)

    def decide_opening_candidate(self, candidate_id: str, payload: OpeningCandidateAction, request_id: str, *, selected: bool) -> dict[str, Any]:
        project, candidate = self._project_for_candidate(candidate_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row, experiment = session.get(OpeningCandidate, candidate.id), session.get(OpeningExperiment, candidate.experiment_id)
            assert row and experiment
            self._expect_revision(row, payload.expected_revision, "OPENING_CANDIDATE_REVISION_CONFLICT")
            self._expect_revision(experiment, payload.expected_experiment_revision, "OPENING_EXPERIMENT_REVISION_CONFLICT")
            if experiment.status != "awaiting_selection" or row.status != "candidate":
                raise StoryError(409, "OPENING_CANDIDATE_NOT_SELECTABLE", "Opening candidate is not available for a decision.")
            now = _now()
            if selected:
                for other in session.scalars(select(OpeningCandidate).where(OpeningCandidate.experiment_id == experiment.id, OpeningCandidate.id != row.id, OpeningCandidate.status == "candidate")).all():
                    other.status, other.revision, other.updated_at = "not_selected", other.revision + 1, now
                # Selection only chooses a direction.  A StyleBaseline is an
                # authority for subsequent writing and must not exist until
                # all three expanded chapters have been explicitly reviewed.
                row.status, experiment.status, experiment.selected_candidate_id = "selected", "selected", row.id
            else:
                row.status = "rejected"
                remaining = session.scalar(select(func.count()).select_from(OpeningCandidate).where(OpeningCandidate.experiment_id == experiment.id, OpeningCandidate.status == "candidate"))
                if remaining == 0:
                    experiment.status = "return_to_ideation"
            row.revision, row.updated_at, row.decided_at = row.revision + 1, now, now
            experiment.revision, experiment.updated_at = experiment.revision + 1, now
            session.add(self.service._audit(f"opening_candidate.{'selected' if selected else 'rejected'}", "opening_candidate", row.id, {}, request_id))
            return self._candidate_dict(session, row)

    def expand_opening_to_three_chapters(self, experiment_id: str, payload: OpeningExpand, request_id: str) -> dict[str, Any]:
        project, experiment_row = self._project_for_experiment(experiment_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            experiment = session.get(OpeningExperiment, experiment_row.id)
            candidate = session.get(OpeningCandidate, payload.selected_candidate_id)
            assert experiment
            self._expect_revision(experiment, payload.expected_revision, "OPENING_EXPERIMENT_REVISION_CONFLICT")
            if not candidate or candidate.project_id != project.id or candidate.experiment_id != experiment.id:
                raise StoryError(404, "OPENING_CANDIDATE_NOT_FOUND", "Opening candidate was not found in this experiment.")
            self._expect_revision(candidate, payload.expected_candidate_revision, "OPENING_CANDIDATE_REVISION_CONFLICT")
            if experiment.selected_candidate_id != candidate.id or candidate.status != "selected":
                raise StoryError(409, "OPENING_CANDIDATE_NOT_SELECTED", "Only a human-selected candidate may expand to three chapters.")
            brief = session.get(StoryBriefVersion, experiment.story_brief_version_id)
            frozen = {"experimentRevision": experiment.revision, "candidateRevision": candidate.revision, "candidateId": candidate.id}
            chapters = safe_json_loads(candidate.chapters_json, [])
        output, _ = self._complete_model_json(project, "story_incubator", "story_incubator:opening-expand", request_id, "Write experimental chapters two and three for the selected opening. Return chapters with exactly chapterNumber 2 and 3, title, content. They remain experiments and must not be official manuscript text.", {"phase14Step": "opening_expand", "storyBrief": safe_json_loads(brief.brief_json, {}) if brief else {}, "selectedChapters": chapters})
        additions = output.get("chapters") if isinstance(output.get("chapters"), list) else []
        if {item.get("chapterNumber") for item in additions if isinstance(item, dict)} != {2, 3}:
            raise StoryError(422, "OPENING_EXPANSION_MODEL_INVALID", "The story incubator must return chapters two and three.")
        addition_contents = [str(item.get("content") or "").strip() for item in additions if isinstance(item, dict)]
        if any(not content for content in addition_contents):
            raise StoryError(422, "OPENING_EXPANSION_MODEL_INVALID", "Expanded opening chapters cannot be empty.")
        brief_data = safe_json_loads(brief.brief_json, {}) if brief else {}
        for content in addition_contents:
            self._validate_opening_content(content, brief_data)
        existing_content = str(chapters[0].get("content") or "") if chapters and isinstance(chapters[0], dict) else ""
        all_contents = [existing_content, *addition_contents]
        if any(self._opening_similarity(all_contents[left], all_contents[right]) >= 0.85 for left in range(len(all_contents)) for right in range(left + 1, len(all_contents))):
            raise StoryError(422, "OPENING_CHAPTERS_NOT_DISTINCT", "Expanded opening chapters must advance with distinct content.")
        with self.service.db.project_write(project.id, project.folder_path) as session:
            experiment = session.get(OpeningExperiment, experiment_row.id)
            candidate = session.get(OpeningCandidate, payload.selected_candidate_id)
            assert experiment
            self._expect_revision(experiment, payload.expected_revision, "OPENING_EXPERIMENT_REVISION_CONFLICT")
            if not candidate or candidate.project_id != project.id or candidate.experiment_id != experiment.id:
                raise StoryError(404, "OPENING_CANDIDATE_NOT_FOUND", "Opening candidate was not found in this experiment.")
            self._expect_revision(candidate, payload.expected_candidate_revision, "OPENING_CANDIDATE_REVISION_CONFLICT")
            if experiment.selected_candidate_id != candidate.id or candidate.status != "selected":
                raise StoryError(409, "OPENING_CANDIDATE_NOT_SELECTED", "Only a human-selected candidate may expand to three chapters.")
            if experiment.revision != frozen["experimentRevision"] or candidate.revision != frozen["candidateRevision"] or candidate.id != frozen["candidateId"]:
                raise StoryError(409, "OPENING_UPSTREAM_DRIFT", "The selected opening changed while the expansion was generated.")
            chapters = safe_json_loads(candidate.chapters_json, [])
            chapters.extend({"chapterNumber": item["chapterNumber"], "title": str(item.get("title") or "")[:300], "content": str(item.get("content") or ""), "manualApproved": False} for item in additions if isinstance(item, dict) and str(item.get("content") or "").strip())
            if len(chapters) != 3:
                raise StoryError(422, "OPENING_EXPANSION_MODEL_INVALID", "The expanded opening is incomplete.")
            candidate.chapters_json, candidate.chapter_count, candidate.text_checksum, candidate.revision, candidate.updated_at = dumps(chapters), 3, stable_digest(chapters), candidate.revision + 1, _now()
            experiment.status, experiment.revision, experiment.updated_at = "three_chapter_experiment", experiment.revision + 1, _now()
            session.add(self.service._audit("opening_experiment.expanded", "opening_experiment", experiment.id, {"candidateId": candidate.id}, request_id))
            return self._experiment_dict(session, experiment)

    def approve_opening_chapter(self, candidate_id: str, payload: OpeningChapterApproval, request_id: str) -> dict[str, Any]:
        """Record a human gate for one expanded opening chapter.

        The experiment may inform a production style baseline only after all
        three chapters are both present and explicitly approved.  The chapter
        text itself remains an experiment and is never written to ChapterCommit.
        """
        project, candidate_row = self._project_for_candidate(candidate_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            candidate = session.get(OpeningCandidate, candidate_row.id)
            assert candidate
            self._expect_revision(candidate, payload.expected_revision, "OPENING_CANDIDATE_REVISION_CONFLICT")
            experiment = session.get(OpeningExperiment, candidate.experiment_id)
            if not experiment or experiment.selected_candidate_id != candidate.id or candidate.status != "selected":
                raise StoryError(409, "OPENING_CANDIDATE_NOT_SELECTED", "Only the selected opening candidate can be approved.")
            chapters = safe_json_loads(candidate.chapters_json, [])
            if len(chapters) != 3:
                raise StoryError(409, "OPENING_THREE_CHAPTERS_REQUIRED", "Expand the selected opening into three chapters before approving it.")
            target = next((item for item in chapters if item.get("chapterNumber") == payload.chapter_number), None)
            if not isinstance(target, dict):
                raise StoryError(404, "OPENING_CHAPTER_NOT_FOUND", "The opening chapter was not found.")
            target["manualApproved"] = True
            now = _now()
            candidate.chapters_json = dumps(chapters)
            candidate.revision += 1
            candidate.updated_at = now
            if all(item.get("manualApproved") is True for item in chapters):
                self._activate_style_baseline(session, project.id, experiment, candidate, now)
                experiment.status = "manual_approval_complete"
                experiment.revision += 1
                experiment.updated_at = now
            session.add(self.service._audit("opening_chapter.approved", "opening_candidate", candidate.id, {"chapterNumber": payload.chapter_number}, request_id))
            return self._candidate_dict(session, candidate)

    def readiness(self, project_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        required_roles = {"research_planner", "research_analyst", "story_incubator", "reader_simulator", "opening_editor"}
        role_labels = {
            "research_planner": "市场调研规划",
            "research_analyst": "研究证据分析",
            "story_incubator": "故事创意孵化",
            "reader_simulator": "目标读者模拟",
            "opening_editor": "开篇编辑评审",
        }
        missing_roles: list[str] = []
        unavailable_roles: list[str] = []
        untested_providers: set[str] = set()
        with self.service.db.catalog() as catalog_session:
            bindings = catalog_session.scalars(
                select(ModelRoleBinding)
                .where(ModelRoleBinding.role.in_(required_roles))
                .options(selectinload(ModelRoleBinding.model).selectinload(ModelConfig.provider))
            ).all()
            by_role = {binding.role: binding for binding in bindings}
            for role in sorted(required_roles):
                binding = by_role.get(role)
                model = binding.model if binding else None
                provider: ModelProvider | None = model.provider if model else None
                if not model:
                    missing_roles.append(role)
                elif not model.is_enabled or not provider or not provider.is_enabled or not provider.api_key_ref:
                    unavailable_roles.append(role)
                elif provider.last_test_status != "success":
                    untested_providers.add(provider.name)
        if missing_roles:
            model_check = {"code": "INCUBATION_MODEL_ROLE_MISSING", "status": "blocked", "detail": "请先绑定孵化所需模型角色：" + "、".join(role_labels[role] for role in missing_roles), "actionPath": "/settings"}
        elif unavailable_roles:
            model_check = {"code": "INCUBATION_MODEL_UNAVAILABLE", "status": "blocked", "detail": "请启用模型、Provider 和密钥：" + "、".join(role_labels[role] for role in unavailable_roles), "actionPath": "/settings"}
        elif untested_providers:
            model_check = {"code": "INCUBATION_PROVIDER_NOT_TESTED", "status": "blocked", "detail": "请先完成 Provider 连接测试：" + "、".join(sorted(untested_providers)), "actionPath": "/settings"}
        else:
            model_check = {"code": "INCUBATION_MODELS_READY", "status": "ready", "detail": "五个孵化模型角色均已可用，并且通过连接测试。", "actionPath": "/settings"}
        with self.service.db.project(project.id, project.folder_path) as session:
            brief = session.scalar(select(StoryBriefVersion).where(StoryBriefVersion.project_id == project.id, StoryBriefVersion.is_current.is_(True)))
            baseline = session.scalar(select(StyleBaseline).where(StyleBaseline.project_id == project.id, StyleBaseline.is_current.is_(True)))
            selected = session.scalar(select(OpeningCandidate).where(OpeningCandidate.project_id == project.id, OpeningCandidate.status == "selected"))
            doc = session.get(CanonDocument, "story-core")
            checks = [
                model_check,
                {"code": "STORY_BRIEF_ACCEPTED", "status": "ready" if brief else "blocked", "detail": "StoryBrief 已由你确认。" if brief else "请先确认一个 StoryBrief 提案。"},
                {"code": "CANON_DRAFT", "status": "ready" if doc and doc.status == "draft" and bool(doc.content_markdown.strip()) else "blocked", "detail": "Canon 草稿已经建立。" if doc and doc.status == "draft" else "请先生成并应用 Canon 候选。"},
                {"code": "OPENING_SELECTED", "status": "ready" if selected else "blocked", "detail": "开篇方向已由你选择。" if selected else "请从三个开篇候选中明确选择一个方向。"},
                {"code": "STYLE_BASELINE", "status": "ready" if baseline else "blocked", "detail": "三章人工批准的实验稿已建立文风基线。" if baseline else "请扩写选中的开篇，并人工批准全部三章实验稿。"},
                {"code": "FIRST_THREE_MANUAL_ONLY", "status": "warning", "detail": "正式作品的前三章仍需人工批准；创意孵化不会自动开启托管。"},
            ]
            ready = all(item["status"] == "ready" for item in checks if item["status"] != "warning")
            return {"projectId": project.id, "ready": ready, "stage": "ready_for_manual_handoff" if ready else "incubating", "checks": checks, "currentStoryBriefId": brief.id if brief else None, "selectedOpeningCandidateId": selected.id if selected else None, "styleBaselineId": baseline.id if baseline else None, "updatedAt": _now()}

    def assert_canon_lockable(self, session: Any, project_id: str, document: CanonDocument) -> None:
        """Protect incubation Canon from being locked before opening review.

        Ordinary Canon documents preserve the pre-existing lock behaviour.  An
        incubation Canon is identified by its applied proposal matching the
        current document, which avoids imposing this new workflow on legacy
        projects or manually replaced Canon text.
        """
        applied = session.scalars(select(CanonGenerationProposal).where(
            CanonGenerationProposal.project_id == project_id,
            CanonGenerationProposal.status == "applied",
        )).all()
        incubation_rows = [
            row for row in applied
            if safe_json_loads(row.brief_json, {}).get("incubation") is True
            and row.content_markdown == document.content_markdown
        ]
        if not incubation_rows:
            return
        baseline = session.scalar(select(StyleBaseline).where(
            StyleBaseline.project_id == project_id,
            StyleBaseline.is_current.is_(True),
        ))
        candidate = session.get(OpeningCandidate, baseline.candidate_id) if baseline else None
        chapters = safe_json_loads(candidate.chapters_json, []) if candidate else []
        complete = bool(
            baseline
            and candidate
            and candidate.status == "selected"
            and candidate.chapter_count == 3
            and len(chapters) == 3
            and all(isinstance(item, dict) and item.get("manualApproved") is True for item in chapters)
        )
        if not complete:
            raise StoryError(
                409,
                "OPENING_MANUAL_APPROVAL_REQUIRED",
                "An incubation Canon can be locked only after all three selected opening chapters are manually approved.",
            )

    def recover_interrupted_research(self) -> None:
        for project in self.service.list_projects():
            with self.service.db.project_write(project.id, project.folder_path) as session:
                for row in session.scalars(select(ResearchJob).where(ResearchJob.status.in_(["planning", "searching", "fetching", "analyzing"]))).all():
                    row.status, row.error_code, row.completed_at, row.revision, row.updated_at = "failed", "STARTUP_RECOVERY", _now(), row.revision + 1, _now()

    def repair_restored_metadata(self, project_id: str, folder_path: str, old_project_id: str) -> None:
        """Give Phase 13 records a fresh identity namespace after restore.

        A backup clone must not share request, source, opportunity, Brief, or
        opening IDs with its source project. SQLite rows have no DB-level
        foreign keys here, so the complete mapping is applied in one short
        transaction before the restored project is exposed.
        """
        with self.service.db.project_write(project_id, folder_path) as session:
            tables = (
                MarketResearchBrief, ResearchJob, ResearchQuery, ResearchSource,
                ResearchSourceVersion, ResearchEvidence, CompetitorProfile,
                ResearchFinding, StoryOpportunity, IdeationSession, IdeationMessage,
                StoryBriefVersion, StoryBriefProposal, OpeningExperiment,
                OpeningCandidate, ReaderEvaluation, StyleBaseline,
            )
            rows_by_table = {table: list(session.scalars(select(table)).all()) for table in tables}
            id_map = {row.id: str(uuid4()) for rows in rows_by_table.values() for row in rows}

            # Rewrite primary IDs first. All relationships use application
            # columns rather than database foreign keys, and are rewritten
            # immediately below in this same transaction.
            for rows in rows_by_table.values():
                for row in rows:
                    row.id = id_map[row.id]

            relation_fields = {
                ResearchJob: ("brief_id",),
                ResearchQuery: ("job_id",),
                ResearchSource: ("job_id", "query_id"),
                ResearchSourceVersion: ("job_id", "source_id"),
                ResearchEvidence: ("job_id", "source_id", "source_version_id"),
                CompetitorProfile: ("job_id",),
                ResearchFinding: ("job_id",),
                StoryOpportunity: ("job_id",),
                IdeationSession: ("opportunity_id", "research_job_id"),
                IdeationMessage: ("session_id",),
                StoryBriefVersion: ("session_id", "proposal_id", "opportunity_id", "research_job_id"),
                StoryBriefProposal: ("session_id", "base_brief_version_id", "opportunity_id", "research_job_id"),
                OpeningExperiment: ("story_brief_version_id", "selected_candidate_id"),
                OpeningCandidate: ("experiment_id",),
                ReaderEvaluation: ("experiment_id", "candidate_id"),
                StyleBaseline: ("experiment_id", "candidate_id", "story_brief_version_id"),
            }
            for table, fields in relation_fields.items():
                for row in rows_by_table[table]:
                    for field in fields:
                        value = getattr(row, field)
                        if value in id_map:
                            setattr(row, field, id_map[value])

            def remap(value: Any) -> Any:
                if isinstance(value, str):
                    if value == old_project_id:
                        return project_id
                    return id_map.get(value, value)
                if isinstance(value, list):
                    return [remap(item) for item in value]
                if isinstance(value, dict):
                    return {key: remap(item) for key, item in value.items()}
                return value

            json_fields = {
                ResearchJob: ("provider_config_json", "limits_json", "coverage_json", "diagnostic_json"),
                ResearchQuery: ("provider_metadata_json",),
                ResearchSource: ("provider_metadata_json",),
                ResearchSourceVersion: ("fetch_metadata_json",),
                ResearchEvidence: ("locator_json", "finding_refs_json"),
                CompetitorProfile: ("profile_json", "evidence_ids_json"),
                ResearchFinding: ("evidence_ids_json", "uncertainties_json"),
                StoryOpportunity: ("story_json", "score_components_json", "uncertainties_json", "evidence_ids_json"),
                IdeationSession: ("state_json",),
                IdeationMessage: ("structured_state_json", "evidence_ids_json"),
                StoryBriefVersion: ("brief_json",),
                StoryBriefProposal: ("proposed_brief_json", "diff_json"),
                OpeningExperiment: ("strategies_json",),
                OpeningCandidate: ("strategy_json", "chapters_json"),
                ReaderEvaluation: ("scores_json", "findings_json"),
                StyleBaseline: ("style_rules_json", "forbidden_patterns_json"),
            }
            for table, fields in json_fields.items():
                for row in rows_by_table[table]:
                    for field in fields:
                        raw = getattr(row, field)
                        if raw:
                            setattr(row, field, dumps(remap(safe_json_loads(raw, {}))))

            # Audit rows are cross-table references, so carry the new resource
            # IDs forward without rewriting opaque historical payload text.
            from .models import AuditEvent
            for event in session.scalars(select(AuditEvent)).all():
                if event.entity_id in id_map:
                    event.entity_id = id_map[event.entity_id]
                event.payload_json = dumps(remap(safe_json_loads(event.payload_json, {})))

    # ------------------------------------------------------------------
    # Internal helpers and serializers
    # ------------------------------------------------------------------
    @staticmethod
    def _expect_revision(row: Any, expected: int, code: str) -> None:
        if row.revision != expected:
            raise StoryError(409, code, "Revision conflict.", {"currentRevision": row.revision})

    def _project_for_job(self, job_id: str) -> tuple[Any, ResearchJob]:
        for project in self.service.list_projects():
            with self.service.db.project(project.id, project.folder_path) as session:
                row = session.get(ResearchJob, job_id)
                if row:
                    return project, row
        raise StoryError(404, "RESEARCH_JOB_NOT_FOUND", "Research job was not found.")

    def _project_for_competitor(self, competitor_id: str) -> tuple[Any, CompetitorProfile]:
        return self._find_project_row(CompetitorProfile, competitor_id, "COMPETITOR_NOT_FOUND")

    def _project_for_opportunity(self, opportunity_id: str) -> tuple[Any, StoryOpportunity]:
        return self._find_project_row(StoryOpportunity, opportunity_id, "STORY_OPPORTUNITY_NOT_FOUND")

    def _project_for_ideation_session(self, session_id: str) -> tuple[Any, IdeationSession]:
        return self._find_project_row(IdeationSession, session_id, "IDEATION_SESSION_NOT_FOUND")

    def _project_for_brief_proposal(self, proposal_id: str) -> tuple[Any, StoryBriefProposal]:
        return self._find_project_row(StoryBriefProposal, proposal_id, "STORY_BRIEF_PROPOSAL_NOT_FOUND")

    def _project_for_experiment(self, experiment_id: str) -> tuple[Any, OpeningExperiment]:
        return self._find_project_row(OpeningExperiment, experiment_id, "OPENING_EXPERIMENT_NOT_FOUND")

    def _project_for_candidate(self, candidate_id: str) -> tuple[Any, OpeningCandidate]:
        return self._find_project_row(OpeningCandidate, candidate_id, "OPENING_CANDIDATE_NOT_FOUND")

    def _find_project_row(self, table: Any, row_id: str, code: str) -> tuple[Any, Any]:
        for project in self.service.list_projects():
            with self.service.db.project(project.id, project.folder_path) as session:
                row = session.get(table, row_id)
                if row:
                    return project, row
        raise StoryError(404, code, "Requested resource was not found.")

    def _job_is_active(self, project: Any, job_id: str) -> bool:
        with self.service.db.project(project.id, project.folder_path) as session:
            row = session.get(ResearchJob, job_id)
            return bool(row and row.status not in {"cancelled", "failed"})

    def _job_has_brief_drift(self, project: Any, job_id: str) -> bool:
        with self.service.db.project(project.id, project.folder_path) as session:
            row = session.get(ResearchJob, job_id)
            return bool(row and not self._brief_matches_job(session, row))

    @staticmethod
    def _brief_matches_job(session: Any, job: ResearchJob) -> bool:
        brief = session.get(MarketResearchBrief, job.brief_id)
        return bool(
            brief
            and brief.project_id == job.project_id
            and brief.status == "current"
            and brief.revision == job.brief_revision
            and brief.checksum == job.brief_checksum
        )

    def _providers_for(self, job: ResearchJob) -> tuple[SearchProvider, ContentFetchProvider]:
        config = safe_json_loads(job.provider_config_json, {})
        search_name = config.get("searchProvider", "deterministic")
        fetch_name = config.get("fetchProvider", "deterministic")
        if search_name == "deterministic":
            search: SearchProvider = self.search_provider
        elif search_name == "tavily":
            search = TavilySearchProvider(self._secret(config.get("searchSecretRef"), "SEARCH_API_KEY_MISSING"))
        else:
            raise StoryError(422, "SEARCH_PROVIDER_INVALID", "Unsupported search provider.")
        if fetch_name == "deterministic":
            fetch: ContentFetchProvider = self.fetch_provider
        elif fetch_name == "firecrawl":
            fetch = FirecrawlContentFetchProvider(self._secret(config.get("fetchSecretRef"), "FETCH_API_KEY_MISSING"))
        else:
            raise StoryError(422, "FETCH_PROVIDER_INVALID", "Unsupported content fetch provider.")
        return search, fetch

    def _secret(self, ref: Any, code: str) -> str:
        if not isinstance(ref, str) or not ref.strip():
            raise StoryError(409, code, "Provider credential reference is not configured.")
        try:
            value = self.service.secret_store.get_secret(ref)
        except Exception as exc:
            raise StoryError(503, "CREDENTIAL_STORE_UNAVAILABLE", "Unable to read provider credentials.") from exc
        if not value:
            raise StoryError(409, code, "Provider credential is not available.")
        return value

    def _fail_job(self, project: Any, job_id: str, code: str, message: str, request_id: str) -> dict[str, Any]:
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(ResearchJob, job_id)
            assert row
            return self._fail_job_in_session(session, row, code, message, request_id)

    @staticmethod
    def _runtime_exceeded(started_at: datetime | None, limits: dict[str, Any]) -> bool:
        if not started_at:
            return False
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        return (_now() - started_at).total_seconds() > int(limits.get("maxRuntimeSeconds", 180))

    @staticmethod
    def _cost_exceeded(job: ResearchJob, additional_cost: float, limits: dict[str, Any]) -> bool:
        return job.estimated_cost + max(0.0, additional_cost) > float(limits.get("maxCost", 5.0))

    def _fail_job_in_session(self, session: Any, row: ResearchJob, code: str, message: str, request_id: str) -> dict[str, Any]:
        row.status, row.error_code, row.error_message, row.completed_at = "failed", code, message, _now()
        row.revision, row.updated_at = row.revision + 1, row.completed_at
        session.add(self.service._audit("research_job.failed", "research_job", row.id, {"code": code}, request_id))
        return self._job_dict(row)

    @staticmethod
    def _brief_snapshot(data: dict[str, Any]) -> dict[str, Any]:
        return {key: data.get(key) for key in ("format", "platform", "genre", "audience", "targetChapters", "targetWords", "emotionalValue", "researchDateRange", "includedDomains", "excludedDomains", "referenceWorks", "forbiddenContent", "commercialGoals", "notes")}

    @staticmethod
    def _planned_queries(brief: dict[str, Any]) -> list[tuple[str, str]]:
        base = f"{brief['platform']} {brief['genre']} {brief['audience']}"
        suffixes = ("platform trends", "leading works", "reader praise", "reader dropoff reasons", "opening hook strategy", "serial retention engine")
        return list(zip(PERSPECTIVES, [f"{base} {suffix}" for suffix in suffixes], strict=True))

    def _model_queries(self, project: Any, brief: dict[str, Any], request_id: str, job_id: str) -> list[tuple[str, str]]:
        output, _ = self._complete_model_json(
            project,
            "research_planner",
            "research_planner:query-plan",
            request_id,
            (
                "You are a market-research query planner. Produce exactly one concise public-web query for each required perspective. "
                "Return this exact JSON shape: {\"queries\":[{\"perspective\":\"platform_trends\",\"query\":\"...\"}]}. "
                "The queries array must contain all supplied perspective keys exactly once. "
                "Do not invent facts, copyrighted text, or named-author imitation."
            ),
            {
                "phase14Step": "query_plan",
                "brief": brief,
                "perspectives": list(PERSPECTIVES),
                "requiredOutput": {"queries": [{"perspective": "one supplied perspective key", "query": "one concise public-web query"}]},
            },
            budget_job_id=job_id,
        )
        try:
            return self._validate_model_queries(output)
        except StoryError as first_error:
            repaired, _ = self._complete_model_json(
                project,
                "research_planner",
                "research_planner:query-plan:schema-repair",
                request_id,
                (
                    "Repair the query plan structure without changing the research brief. "
                    "Return exactly one queries array containing every required perspective exactly once. "
                    "Each item must contain only a supplied perspective key and a non-empty public-web query."
                ),
                {
                    "phase14Step": "query_plan_schema_repair",
                    "brief": brief,
                    "perspectives": list(PERSPECTIVES),
                    "invalidOutput": output,
                    "validationError": first_error.code,
                    "requiredOutput": {"queries": [{"perspective": "one supplied perspective key", "query": "one concise public-web query"}]},
                },
                budget_job_id=job_id,
            )
            return self._validate_model_queries(repaired)

    @staticmethod
    def _validate_model_queries(output: dict[str, Any]) -> list[tuple[str, str]]:
        items = output.get("queries")
        if not isinstance(items, list):
            raise StoryError(422, "RESEARCH_QUERY_PLAN_INVALID", "The research planner did not return a queries array.")
        planned: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            perspective = str(item.get("perspective") or "").strip()
            query = str(item.get("query") or "").strip()
            if perspective not in PERSPECTIVES or not query or perspective in seen:
                raise StoryError(422, "RESEARCH_QUERY_PLAN_INVALID", "The research planner returned an invalid or duplicate perspective.")
            seen.add(perspective)
            planned.append((perspective, query[:1000]))
        if set(seen) != set(PERSPECTIVES):
            raise StoryError(422, "RESEARCH_QUERY_PLAN_INCOMPLETE", "The research planner must cover every required perspective.")
        return planned

    @staticmethod
    def _source_type(domain: str) -> str:
        domain = domain.lower()
        if any(part in domain for part in ("review", "reddit", "forum", "comment")):
            return "reader_review"
        if any(part in domain for part in ("publisher", "platform", "book")):
            return "platform_official"
        return "other"

    @staticmethod
    def _source_is_allowed(url: str, included_domains: list[str], excluded_domains: list[str]) -> bool:
        """Apply saved source scope after provider search results return.

        Providers may treat include-domain filtering as advisory.  Enforcing the
        scope here keeps exclusions deterministic and prevents a result from
        being persisted merely because a provider ignored the request.
        """
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        if not host:
            return False

        def matches(domain: str) -> bool:
            normalized = str(domain or "").lower().strip().rstrip(".")
            return bool(normalized) and (host == normalized or host.endswith(f".{normalized}"))

        if any(matches(domain) for domain in excluded_domains):
            return False
        return not included_domains or any(matches(domain) for domain in included_domains)

    def _activate_style_baseline(self, session: Any, project_id: str, experiment: OpeningExperiment, candidate: OpeningCandidate, now: datetime) -> None:
        for baseline in session.scalars(select(StyleBaseline).where(
            StyleBaseline.project_id == project_id,
            StyleBaseline.is_current.is_(True),
        )).all():
            baseline.is_current = False
            baseline.revision += 1
        style_rules = [
            "Use concrete scene action before explanation.",
            "Keep the protagonist's immediate desire visible.",
            "End a chapter with a consequence-bearing next question.",
        ]
        forbidden = [
            "Do not imitate named authors.",
            "Avoid repeated archive or serial-number exposition.",
        ]
        baseline = StyleBaseline(
            id=str(uuid4()), project_id=project_id, experiment_id=experiment.id,
            candidate_id=candidate.id, story_brief_version_id=experiment.story_brief_version_id,
            story_brief_checksum=experiment.story_brief_checksum, canon_revision=experiment.canon_revision,
            canon_checksum=experiment.canon_checksum, sample_checksum=candidate.text_checksum,
            style_rules_json=dumps(style_rules), forbidden_patterns_json=dumps(forbidden),
            checksum=stable_digest({"sample": candidate.text_checksum, "rules": style_rules, "forbidden": forbidden}),
            is_current=True, revision=1, created_at=now,
        )
        session.add(baseline)

    def _upsert_search_source(self, session: Any, project_id: str, job: ResearchJob, query: ResearchQuery, result: Any) -> None:
        canonical = result.url.split("#", 1)[0]
        source = session.scalar(select(ResearchSource).where(ResearchSource.job_id == job.id, ResearchSource.canonical_url == canonical))
        now = _now()
        if not source:
            source = ResearchSource(id=str(uuid4()), project_id=project_id, job_id=job.id, query_id=query.id, canonical_url=canonical, title=result.title[:1000], domain=result.domain or (urlsplit(canonical).hostname or ""), source_type=result.source_type if result.source_type != "other" else self._source_type(result.domain), published_at=result.published_at, provider_metadata_json=dumps(result.provider_metadata), status="discovered", created_at=now, updated_at=now)
            session.add(source)

    def _report_checksum(self, session: Any, job: ResearchJob) -> str:
        evidence = sorted(session.scalars(select(ResearchEvidence.id).where(ResearchEvidence.job_id == job.id)).all())
        competitors = sorted(row.checksum for row in session.scalars(select(CompetitorProfile).where(CompetitorProfile.job_id == job.id, CompetitorProfile.excluded.is_(False))).all())
        return stable_digest({"job": job.id, "reportRevision": job.report_revision, "evidence": evidence, "competitors": competitors})

    @staticmethod
    def _validate_scores(raw: dict[str, Any]) -> tuple[dict[str, int], int]:
        normalized = {key: int(raw.get(key, -1)) for key in SCORE_LIMITS}
        if any(value < 0 or value > SCORE_LIMITS[key] for key, value in normalized.items()):
            raise StoryError(422, "OPPORTUNITY_SCORE_COMPONENT_INVALID", "Each opportunity score component must be within its fixed weight.")
        total = sum(normalized.values())
        return normalized, total

    def _default_opportunities(self, session: Any, job: ResearchJob) -> list[dict[str, Any]]:
        raise StoryError(500, "MODEL_BACKED_OPPORTUNITIES_REQUIRED", "Story opportunities must be generated by the configured model role.")

    def _assert_ideation_upstream(self, session: Any, row: IdeationSession) -> tuple[StoryOpportunity, ResearchJob]:
        opportunity, job = session.get(StoryOpportunity, row.opportunity_id), session.get(ResearchJob, row.research_job_id)
        if not opportunity or not job or opportunity.project_id != row.project_id or opportunity.checksum != row.opportunity_checksum or opportunity.revision != row.opportunity_revision or job.report_checksum != row.research_report_checksum:
            raise StoryError(409, "IDEATION_UPSTREAM_DRIFT", "The accepted opportunity or research report changed.")
        return opportunity, job

    @staticmethod
    def _validate_brief(brief: dict[str, Any]) -> None:
        required = {"format", "platform", "audience", "premise", "readerPromise", "theme", "tone", "pov", "pace", "endingDirection", "protagonist", "coreDesire", "coreConflict", "worldMechanism", "serialEngine", "emotionalRewards", "differentiators", "forbiddenContent", "referenceTraits"}
        missing = sorted(key for key in required if key not in brief or brief[key] in (None, ""))
        if missing:
            raise StoryError(422, "STORY_BRIEF_INCOMPLETE", "StoryBrief is missing required fields.", {"missing": missing})

    def _derive_brief(self, title: str, opportunity: StoryOpportunity, session_row: IdeationSession, job: ResearchJob) -> dict[str, Any]:
        story = safe_json_loads(opportunity.story_json, {})
        state = safe_json_loads(session_row.state_json, {})
        return {"title": title, "format": "long-form", "platform": "undecided", "audience": "Defined by the market research brief", "targetChapters": None, "targetWords": None, "chapterWordRange": {}, "premise": opportunity.high_concept, "readerPromise": story.get("firstThreeChapterPromise", "A concrete opening promise"), "theme": "Choice and consequence", "tone": "Specific, scene-led, and readable", "pov": "close third person", "pace": "purposeful", "endingDirection": "A consequence-bearing resolution", "protagonist": story.get("protagonist", "A protagonist"), "coreDesire": story.get("coreDesire", "A clear desire"), "coreConflict": story.get("coreConflict", "A clear conflict"), "worldMechanism": story.get("worldMechanism", "notApplicable"), "serialEngine": story.get("serialEngine", "Escalating choices"), "emotionalRewards": ["tension", "release"], "differentiators": story.get("differentiation", []), "forbiddenContent": [], "referenceTraits": ["abstract market mechanisms only"], "researchReportId": job.id, "researchReportChecksum": job.report_checksum, "acceptedOpportunityId": opportunity.id, "confirmedDecisions": state.get("confirmedDecisions", []), "openQuestions": state.get("openQuestions", [])}

    @staticmethod
    def _generic_canon(title: str, brief: dict[str, Any], instructions: str) -> tuple[str, dict[str, Any]]:
        protagonist = str(brief.get("protagonist", "Protagonist"))
        world = str(brief.get("worldMechanism", "notApplicable"))
        markdown = "\n".join([
            f"# {title} Story Core", "", "## Story Core", str(brief.get("premise", "")), "", "## Character and Desire", f"{protagonist}: {brief.get('coreDesire', '')}", "", "## Conflict and World", f"Conflict: {brief.get('coreConflict', '')}", f"World mechanism: {world}", "", "## Boundaries", f"Forbidden content: {', '.join(brief.get('forbiddenContent', [])) or 'notApplicable'}", f"Style: {brief.get('tone', '')}", "", "## Notes", instructions.strip() or "Draft only. Human confirmation is required before locking.",
        ])
        entities = [{"canonicalName": protagonist, "entityTypeName": "person", "aliasesJson": [], "attributesJson": {"name": protagonist, "desire": brief.get("coreDesire", "")}}]
        rules = [{"ruleCode": "STORY-CORE-CONFLICT", "category": "story", "statement": str(brief.get("coreConflict", "")), "severity": "high", "constraintJson": {"hard": True}}, {"ruleCode": "STYLE-BOUNDARY", "category": "style", "statement": str(brief.get("tone", "")), "severity": "medium", "constraintJson": {"hard": True}}]
        return markdown, {"entities": entities, "relations": [], "rules": rules}

    @staticmethod
    def _canon_cross_check(generated: dict[str, Any], analyzed: dict[str, Any]) -> dict[str, Any]:
        def names(payload: dict[str, Any], collection: str, field: str) -> set[str]:
            items = payload.get(collection, [])
            if not isinstance(items, list):
                return set()
            return {str(item.get(field) or "").strip().casefold() for item in items if isinstance(item, dict) and str(item.get(field) or "").strip()}

        generated_entities, analyzed_entities = names(generated, "entities", "canonicalName"), names(analyzed, "entities", "canonicalName")
        generated_rules, analyzed_rules = names(generated, "rules", "ruleCode"), names(analyzed, "rules", "ruleCode")
        missing_entities = sorted(generated_entities - analyzed_entities)
        unexpected_entities = sorted(analyzed_entities - generated_entities)
        missing_rules = sorted(generated_rules - analyzed_rules)
        unexpected_rules = sorted(analyzed_rules - generated_rules)
        return {
            "ready": not missing_entities and not unexpected_entities and not missing_rules and not unexpected_rules,
            "missingEntities": missing_entities,
            "unexpectedEntities": unexpected_entities,
            "missingRules": missing_rules,
            "unexpectedRules": unexpected_rules,
        }

    @staticmethod
    def _generic_canon_checks(markdown: str, structured: dict[str, Any], brief: dict[str, Any] | None = None) -> dict[str, Any]:
        brief = brief or {}
        entities = structured.get("entities", [])
        relations = structured.get("relations", [])
        rules = structured.get("rules", [])
        entities_valid = isinstance(entities, list) and bool(entities) and all(
            isinstance(item, dict)
            and bool(str(item.get("canonicalName") or "").strip())
            and bool(str(item.get("entityTypeName") or "").strip())
            and isinstance(item.get("attributesJson", {}), dict)
            for item in entities
        )
        relations_valid = isinstance(relations, list) and all(isinstance(item, dict) for item in relations)
        rules_valid = isinstance(rules, list) and bool(rules) and all(
            isinstance(item, dict)
            and bool(str(item.get("ruleCode") or "").strip())
            and bool(str(item.get("statement") or "").strip())
            and isinstance(item.get("constraintJson", {}), dict)
            for item in rules
        )
        normalized = markdown.casefold()
        protagonist = str(brief.get("protagonist") or "").strip().casefold()
        entity_names = {str(item.get("canonicalName") or "").strip().casefold() for item in entities if isinstance(item, dict)} if isinstance(entities, list) else set()
        cross_check = structured.get("_generationCrossCheck", {"ready": True})
        # A single generic phrase such as “雾城” must not make an otherwise
        # valid user concept impossible. Treat the old seed as leaked only
        # when distinctive names appear without being requested by the Brief,
        # or when several weaker template terms travel together.
        brief_text = dumps(brief)
        night_watch_terms = ("夜巡人", "沈砚", "夜巡司", "巡夜灯", "镇纸钉", "潮湿账页", "雾城", "七卷", "六阶")
        residue = {term for term in night_watch_terms if term in markdown and term not in brief_text}
        distinctive_residue = residue.intersection({"沈砚", "夜巡司", "巡夜灯", "镇纸钉", "潮湿账页"})
        residue_blocked = bool(distinctive_residue) or len(residue) >= 2
        checks = [
            {"code": "CANON_GENERIC_CORE", "status": "ready" if ("story core" in normalized or "故事内核" in markdown) else "blocked", "detail": "Story core must be explicit."},
            {"code": "CANON_GENERIC_CONFLICT", "status": "ready" if ("conflict" in normalized or "冲突" in markdown) else "blocked", "detail": "Core conflict must be explicit."},
            {"code": "CANON_GENERIC_BOUNDARIES", "status": "ready" if ("boundar" in normalized or "边界" in markdown or "禁止" in markdown) else "blocked", "detail": "Writing boundaries must be explicit."},
            {"code": "CANON_GENERIC_ENTITIES", "status": "ready" if entities_valid else "blocked", "detail": "At least one valid structured entity is required."},
            {"code": "CANON_GENERIC_RELATIONS", "status": "ready" if relations_valid else "blocked", "detail": "Relations must be a structured list."},
            {"code": "CANON_GENERIC_RULES", "status": "ready" if rules_valid else "blocked", "detail": "At least one enforceable structured rule is required."},
            {"code": "CANON_GENERIC_PROTAGONIST", "status": "ready" if (not protagonist or protagonist in entity_names) else "blocked", "detail": "The StoryBrief protagonist must exist in structured Canon."},
            {"code": "CANON_GENERIC_ANALYZER_CROSSCHECK", "status": "ready" if isinstance(cross_check, dict) and cross_check.get("ready") is True else "blocked", "detail": "Independent Canon extraction must agree with generated entities and rules."},
            {"code": "CANON_GENERIC_NO_NIGHT_WATCH", "status": "blocked" if residue_blocked else "ready", "detail": "No unrequested Night Watch template residue is allowed in a generic project.", "evidence": sorted(residue)},
        ]
        return {"ready": all(item["status"] == "ready" for item in checks), "checks": checks}

    @staticmethod
    def _narrative_length(content: str) -> int:
        cjk = len(re.findall(r"[\u3400-\u9fff]", content))
        latin_words = len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", content))
        return cjk + latin_words

    @staticmethod
    def _chapter_word_range(brief: dict[str, Any]) -> tuple[int, int]:
        raw = brief.get("chapterWordRange", {})
        if not isinstance(raw, dict):
            raw = {}
        minimum = int(raw.get("min", 800) or 800)
        maximum = int(raw.get("max", 3000) or 3000)
        if minimum < 100 or maximum < minimum or maximum > 20_000:
            raise StoryError(422, "STORY_BRIEF_WORD_RANGE_INVALID", "StoryBrief chapterWordRange must be a valid min/max range.")
        return minimum, maximum

    @classmethod
    def _validate_opening_content(cls, content: str, brief: dict[str, Any]) -> None:
        minimum, maximum = cls._chapter_word_range(brief)
        length = cls._narrative_length(content)
        if length < minimum or length > maximum:
            raise StoryError(422, "OPENING_WORD_RANGE_INVALID", "Opening chapter is outside the StoryBrief word range.", {"length": length, "minimum": minimum, "maximum": maximum})

    @staticmethod
    def _opening_similarity(left: str, right: str) -> float:
        def grams(value: str) -> set[str]:
            normalized = re.sub(r"\s+", "", value.casefold())
            return {normalized[index:index + 3] for index in range(max(0, len(normalized) - 2))}
        left_grams, right_grams = grams(left), grams(right)
        if not left_grams or not right_grams:
            return 1.0 if left.strip() == right.strip() else 0.0
        return len(left_grams & right_grams) / len(left_grams | right_grams)

    @staticmethod
    def _validate_opening_review(review: dict[str, Any], content: str) -> None:
        required_scores = {"firstScreenHook", "characterDesire", "emotionalPull", "sceneTension", "expositionDensity", "terminologyRepetition", "dialogueActionExplanationBalance", "continueReading"}
        scores = review.get("scores")
        if not isinstance(scores, dict) or not required_scores.issubset(scores) or any(not isinstance(scores[key], (int, float)) or scores[key] < 0 or scores[key] > 100 for key in required_scores):
            raise StoryError(422, "OPENING_REVIEW_MODEL_INVALID", "Opening review must contain every bounded score.")
        findings = review.get("findings", [])
        if not isinstance(findings, list):
            raise StoryError(422, "OPENING_REVIEW_MODEL_INVALID", "Opening review findings must be a list.")
        for finding in findings:
            location = finding.get("range", {}) if isinstance(finding, dict) else {}
            if not isinstance(location, dict) or not isinstance(location.get("start"), int) or not isinstance(location.get("end"), int) or location["start"] < 0 or location["end"] < location["start"] or location["end"] > len(content) or not str(finding.get("suggestion") or "").strip():
                raise StoryError(422, "OPENING_REVIEW_MODEL_INVALID", "Every opening finding must contain a valid source range and suggestion.")

    @staticmethod
    def _opening_chapter(brief: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
        protagonist = brief.get("protagonist", "The protagonist")
        desire = brief.get("coreDesire", "a pressing goal")
        conflict = brief.get("coreConflict", "an immediate complication")
        return {"chapterNumber": 1, "title": strategy["label"], "content": f"{protagonist} acts to pursue {desire}. {strategy['focus']} The action immediately meets {conflict}. Before the scene can settle, a consequence forces a new choice."}

    def _evaluate_candidate(self, project_id: str, experiment_id: str, candidate: OpeningCandidate, role: str) -> ReaderEvaluation:
        chapter = safe_json_loads(candidate.chapters_json, [{}])[0]
        text = str(chapter.get("content", ""))
        findings = []
        if len(text) < 80:
            findings.append({"code": "OPENING_SHORT", "severity": "warning", "range": {"start": 0, "end": len(text)}, "suggestion": "Give the first scene enough concrete action."})
        scores = {"firstScreenHook": 75, "characterDesire": 75, "emotionalPull": 70, "sceneTension": 70, "expositionDensity": 20, "terminologyRepetition": 0, "dialogueActionExplanationBalance": 70, "continueReading": 72}
        return ReaderEvaluation(id=str(uuid4()), project_id=project_id, experiment_id=experiment_id, candidate_id=candidate.id, reviewer_role=role, scores_json=dumps(scores), findings_json=dumps(findings), recommendation="continue" if not findings else "revise", summary=f"Independent {role} review.", checksum=stable_digest({"role": role, "scores": scores, "findings": findings}), created_at=_now())

    @staticmethod
    def _brief_dict(row: MarketResearchBrief) -> dict[str, Any]:
        return {"id": row.id, "projectId": row.project_id, "versionNumber": row.version_number, "format": row.format, "platform": row.platform, "genre": row.genre, "audience": row.audience, "targetChapters": row.target_chapters, "targetWords": row.target_words, "emotionalValue": safe_json_loads(row.emotional_value_json, []), "researchDateRange": safe_json_loads(row.research_date_range_json, {}), "includedDomains": safe_json_loads(row.included_domains_json, []), "excludedDomains": safe_json_loads(row.excluded_domains_json, []), "referenceWorks": safe_json_loads(row.reference_works_json, []), "forbiddenContent": safe_json_loads(row.forbidden_content_json, []), "commercialGoals": safe_json_loads(row.commercial_goals_json, []), "notes": row.notes, "checksum": row.checksum, "status": row.status, "revision": row.revision, "createdAt": row.created_at, "updatedAt": row.updated_at}

    @staticmethod
    def _job_dict(row: ResearchJob) -> dict[str, Any]:
        config = safe_json_loads(row.provider_config_json, {})
        public_config = {
            "searchProvider": config.get("searchProvider", "deterministic"),
            "fetchProvider": config.get("fetchProvider", "deterministic"),
            # Credential references are deliberately not exposed through the
            # API.  Callers only need to know whether each provider can read a
            # configured secret from the OS credential store.
            "searchSecretConfigured": bool(config.get("searchSecretRef")),
            "fetchSecretConfigured": bool(config.get("fetchSecretRef")),
        }
        return {"id": row.id, "projectId": row.project_id, "briefId": row.brief_id, "briefRevision": row.brief_revision, "briefChecksum": row.brief_checksum, "attempt": row.attempt, "status": row.status, "idempotencyKey": row.idempotency_key, "providerConfig": public_config, "limits": safe_json_loads(row.limits_json, {}), "coverage": safe_json_loads(row.coverage_json, {}), "reportChecksum": row.report_checksum, "reportRevision": row.report_revision, "queryCount": row.query_count, "pageCount": row.page_count, "fetchedChars": row.fetched_chars, "requestUnits": row.request_units, "estimatedCost": row.estimated_cost, "errorCode": row.error_code, "errorMessage": row.error_message, "diagnostic": None, "revision": row.revision, "createdAt": row.created_at, "startedAt": row.started_at, "completedAt": row.completed_at, "updatedAt": row.updated_at}

    @staticmethod
    def _query_dict(row: ResearchQuery) -> dict[str, Any]:
        return {"id": row.id, "jobId": row.job_id, "perspective": row.perspective, "query": row.query_text, "sequenceNumber": row.sequence_number, "status": row.status, "resultCount": row.result_count, "errorCode": row.error_code, "errorMessage": row.error_message, "createdAt": row.created_at, "completedAt": row.completed_at}

    @staticmethod
    def _source_dict(row: ResearchSource, versions: list[ResearchSourceVersion]) -> dict[str, Any]:
        return {"id": row.id, "projectId": row.project_id, "jobId": row.job_id, "queryId": row.query_id, "canonicalUrl": row.canonical_url, "title": row.title, "domain": row.domain, "sourceType": row.source_type, "publishedAt": row.published_at, "providerMetadata": safe_json_loads(row.provider_metadata_json, {}), "status": row.status, "failureReason": row.failure_reason, "excluded": row.excluded, "revision": row.revision, "createdAt": row.created_at, "updatedAt": row.updated_at, "versions": [{"id": item.id, "projectId": item.project_id, "jobId": item.job_id, "sourceId": item.source_id, "versionNumber": item.version_number, "finalUrl": item.final_url, "contentChecksum": item.content_checksum, "boundedContent": item.bounded_content, "summary": item.summary, "charCount": item.char_count, "truncated": item.truncated, "fetchMetadata": safe_json_loads(item.fetch_metadata_json, {}), "fetchedAt": item.fetched_at} for item in versions]}

    @staticmethod
    def _evidence_dict(row: ResearchEvidence) -> dict[str, Any]:
        return {"id": row.id, "projectId": row.project_id, "jobId": row.job_id, "sourceId": row.source_id, "sourceVersionId": row.source_version_id, "claimType": row.claim_type, "claim": row.claim, "excerpt": row.excerpt, "locator": safe_json_loads(row.locator_json, {}), "confidence": row.confidence, "findingRefs": safe_json_loads(row.finding_refs_json, []), "checksum": row.checksum, "createdAt": row.created_at}

    @staticmethod
    def _competitor_dict(row: CompetitorProfile) -> dict[str, Any]:
        return {"id": row.id, "projectId": row.project_id, "jobId": row.job_id, "reportRevision": row.report_revision, "name": row.name, "profile": safe_json_loads(row.profile_json, {}), "evidenceIds": safe_json_loads(row.evidence_ids_json, []), "confidence": row.confidence, "excluded": row.excluded, "exclusionReason": row.exclusion_reason, "checksum": row.checksum, "status": row.status, "revision": row.revision, "createdAt": row.created_at, "updatedAt": row.updated_at}

    @staticmethod
    def _finding_dict(row: ResearchFinding) -> dict[str, Any]:
        return {"id": row.id, "projectId": row.project_id, "jobId": row.job_id, "reportRevision": row.report_revision, "category": row.category, "statement": row.statement, "claimType": row.claim_type, "evidenceIds": safe_json_loads(row.evidence_ids_json, []), "confidence": row.confidence, "uncertainties": safe_json_loads(row.uncertainties_json, []), "checksum": row.checksum, "status": row.status, "revision": row.revision, "createdAt": row.created_at}

    @staticmethod
    def _opportunity_dict(row: StoryOpportunity) -> dict[str, Any]:
        return {"id": row.id, "projectId": row.project_id, "jobId": row.job_id, "reportRevision": row.report_revision, "reportChecksum": row.report_checksum, "highConcept": row.high_concept, "story": safe_json_loads(row.story_json, {}), "scoreComponents": safe_json_loads(row.score_components_json, {}), "totalScore": row.total_score, "evidenceCoverage": row.evidence_coverage, "confidence": row.confidence, "uncertainties": safe_json_loads(row.uncertainties_json, []), "evidenceIds": safe_json_loads(row.evidence_ids_json, []), "checksum": row.checksum, "status": row.status, "isCurrent": row.is_current, "revision": row.revision, "createdAt": row.created_at, "updatedAt": row.updated_at, "decidedAt": row.decided_at}

    @staticmethod
    def _message_dict(row: IdeationMessage) -> dict[str, Any]:
        return {"id": row.id, "projectId": row.project_id, "sessionId": row.session_id, "sequenceNumber": row.sequence_number, "role": row.role, "content": row.content, "structuredState": safe_json_loads(row.structured_state_json, {}), "evidenceIds": safe_json_loads(row.evidence_ids_json, []), "modelRunId": row.model_run_id, "createdAt": row.created_at}

    def _session_messages(self, session: Any, session_id: str) -> list[dict[str, Any]]:
        return [self._message_dict(row) for row in session.scalars(select(IdeationMessage).where(IdeationMessage.session_id == session_id).order_by(IdeationMessage.sequence_number)).all()]

    def _session_dict(self, row: IdeationSession, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {"id": row.id, "projectId": row.project_id, "opportunityId": row.opportunity_id, "opportunityRevision": row.opportunity_revision, "opportunityChecksum": row.opportunity_checksum, "researchJobId": row.research_job_id, "researchReportChecksum": row.research_report_checksum, "state": safe_json_loads(row.state_json, {}), "status": row.status, "revision": row.revision, "createdAt": row.created_at, "updatedAt": row.updated_at, "messages": messages}

    @staticmethod
    def _brief_proposal_dict(row: StoryBriefProposal) -> dict[str, Any]:
        return {"id": row.id, "projectId": row.project_id, "sessionId": row.session_id, "baseBriefVersionId": row.base_brief_version_id, "opportunityId": row.opportunity_id, "opportunityRevision": row.opportunity_revision, "opportunityChecksum": row.opportunity_checksum, "researchJobId": row.research_job_id, "researchReportChecksum": row.research_report_checksum, "proposedBrief": safe_json_loads(row.proposed_brief_json, {}), "diff": safe_json_loads(row.diff_json, {}), "checksum": row.checksum, "modelRunId": row.model_run_id, "status": row.status, "revision": row.revision, "createdAt": row.created_at, "updatedAt": row.updated_at, "appliedAt": row.applied_at, "rejectedAt": row.rejected_at}

    @staticmethod
    def _brief_version_dict(row: StoryBriefVersion) -> dict[str, Any]:
        return {"id": row.id, "projectId": row.project_id, "sessionId": row.session_id, "proposalId": row.proposal_id, "opportunityId": row.opportunity_id, "opportunityChecksum": row.opportunity_checksum, "researchJobId": row.research_job_id, "researchReportChecksum": row.research_report_checksum, "versionNumber": row.version_number, "brief": safe_json_loads(row.brief_json, {}), "checksum": row.checksum, "isCurrent": row.is_current, "revision": row.revision, "createdAt": row.created_at, "acceptedAt": row.accepted_at}

    def _candidate_dict(self, session: Any, row: OpeningCandidate) -> dict[str, Any]:
        evaluations = session.scalars(select(ReaderEvaluation).where(ReaderEvaluation.candidate_id == row.id).order_by(ReaderEvaluation.reviewer_role)).all()
        return {"id": row.id, "projectId": row.project_id, "experimentId": row.experiment_id, "strategyKey": row.strategy_key, "strategyLabel": row.strategy_label, "strategy": safe_json_loads(row.strategy_json, {}), "chapters": safe_json_loads(row.chapters_json, []), "chapterCount": row.chapter_count, "textChecksum": row.text_checksum, "modelRunId": row.model_run_id, "status": row.status, "revision": row.revision, "createdAt": row.created_at, "updatedAt": row.updated_at, "decidedAt": row.decided_at, "evaluations": [{"id": item.id, "projectId": item.project_id, "experimentId": item.experiment_id, "candidateId": item.candidate_id, "reviewerRole": item.reviewer_role, "scores": safe_json_loads(item.scores_json, {}), "findings": safe_json_loads(item.findings_json, []), "recommendation": item.recommendation, "summary": item.summary, "modelRunId": item.model_run_id, "checksum": item.checksum, "createdAt": item.created_at} for item in evaluations]}

    def _experiment_dict(self, session: Any, row: OpeningExperiment) -> dict[str, Any]:
        candidates = [self._candidate_dict(session, item) for item in session.scalars(select(OpeningCandidate).where(OpeningCandidate.experiment_id == row.id).order_by(OpeningCandidate.strategy_key)).all()]
        return {"id": row.id, "projectId": row.project_id, "storyBriefVersionId": row.story_brief_version_id, "storyBriefRevision": row.story_brief_revision, "storyBriefChecksum": row.story_brief_checksum, "canonDocumentId": row.canon_document_id, "canonRevision": row.canon_revision, "canonChecksum": row.canon_checksum, "strategies": safe_json_loads(row.strategies_json, []), "status": row.status, "selectedCandidateId": row.selected_candidate_id, "revision": row.revision, "createdAt": row.created_at, "updatedAt": row.updated_at, "candidates": candidates}

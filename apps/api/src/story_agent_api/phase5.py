from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .model_provider import ModelProviderError, OpenAICompatibleModelProvider
from .models import (
    AuditEvent,
    CanonDocument,
    ChapterCommit,
    ChapterContract,
    ChapterDraft,
    ChapterExtraction,
    ChapterJob,
    ModelRun,
    Plan,
    PlanNode,
    ProjectMeta,
    QualityFinding,
    QualityRun,
    SourceVersion,
    StateSnapshot,
    utc_now,
)
from .schemas import (
    ChapterApproveRequest,
    ChapterCommitRequest,
    ChapterContractDerive,
    ChapterContractLock,
    ChapterContractUpdate,
    ChapterJobCreate,
    ChapterJobRetry,
    ChapterJobRun,
    ChapterRevisionRequest,
    ContextCompileRequest,
    QualityFindingAcceptRisk,
)
from .services import StoryError, dumps, loads, stable_digest, token_estimate


ACTIVE_JOB_STATUSES = {"compiling_context", "drafting", "extracting", "validating", "reviewing", "revising", "committing", "cancel_requested"}
BLOCKING_SEVERITIES = {"error", "blocker"}
MAX_REVISION_ROUNDS = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def _word_count(value: str) -> int:
    ascii_words = re.findall(r"[A-Za-z0-9_]+", value)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", value)
    return len(ascii_words) + len(cjk_chars)


def _json_object_from_text(value: str) -> dict[str, Any]:
    try:
        data = json.loads(value)
    except ValueError:
        match = re.search(r"\{.*\}", value, flags=re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("JSON payload is not an object")
    return data


class Phase5Service:
    def __init__(self, service: Any):
        self.service = service

    # ------------------------------------------------------------------
    # Startup recovery
    # ------------------------------------------------------------------
    def recover_interrupted_jobs(self) -> None:
        now = utc_now()
        for project in self.service.list_projects():
            with self.service.db.project_write(project.id, project.folder_path) as session:
                jobs = session.scalars(select(ChapterJob).where(ChapterJob.status.in_(ACTIVE_JOB_STATUSES))).all()
                for job in jobs:
                    if job.status == "cancel_requested":
                        job.status = "cancelled"
                        job.error_code = "startup_recovery_cancelled"
                    else:
                        job.status = "interrupted"
                        job.error_code = "startup_recovery"
                    job.finished_at = now
                    job.updated_at = now

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------
    def derive_chapter_contract(self, project_id: str, payload: ChapterContractDerive, request_id: str) -> dict[str, Any]:
        if payload.target_words_min > payload.target_words_max:
            raise StoryError(422, "INVALID_CHAPTER_WORD_TARGET", "targetWordsMin must not exceed targetWordsMax.")
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            locked_docs = session.scalars(select(CanonDocument).where(CanonDocument.status == "locked").order_by(CanonDocument.id.asc())).all()
            if not locked_docs:
                raise StoryError(409, "CANON_NOT_LOCKED", "Canon must be locked before deriving chapter contracts.")
            plan = session.scalar(select(Plan))
            node = self._resolve_contract_node(session, payload, plan)
            latest_snapshot = session.scalar(
                select(StateSnapshot)
                .where(StateSnapshot.project_id == project.id)
                .order_by(StateSnapshot.snapshot_number.desc(), StateSnapshot.created_at.desc())
            )
            future_nodes = []
            if plan:
                future_nodes = [
                    self.service._node_dict(item)
                    for item in session.scalars(select(PlanNode).where(PlanNode.target_chapter > payload.chapter_number).order_by(PlanNode.target_chapter.asc())).all()
                ]
            objective = {
                "mustAdvance": self.service._node_dict(node) if node else {},
                "authorNote": payload.author_note,
            }
            allowed_scope = {
                "chapterNumber": payload.chapter_number,
                "planNodeId": node.id if node else payload.plan_node_id,
                "mayAdvance": _safe_loads(node.contracts_json, []) if node else [],
                "completionConditions": _safe_loads(node.completion_conditions_json, []) if node else [],
            }
            forbidden_scope = {
                "mustNotAdvance": future_nodes,
                "futureKeywords": [item.get("title", "") for item in future_nodes if item.get("title")],
            }
            now = _now()
            item = ChapterContract(
                id=str(uuid4()),
                project_id=project.id,
                chapter_number=payload.chapter_number,
                title=payload.title or (node.title if node else f"Chapter {payload.chapter_number}"),
                plan_node_id=node.id if node else payload.plan_node_id,
                plan_node_revision=node.revision if node else 1,
                canon_revision_digest=stable_digest([{"id": doc.id, "revision": doc.revision, "checksum": stable_digest(doc.content_markdown)} for doc in locked_docs]),
                state_snapshot_id=latest_snapshot.id if latest_snapshot else None,
                objective_json=dumps(objective),
                allowed_scope_json=dumps(allowed_scope),
                forbidden_scope_json=dumps(forbidden_scope),
                required_characters_json=dumps(self._strings_from_payload(node, "prerequisites_json")),
                required_foreshadows_json=dumps(self._strings_from_payload(node, "foreshadows_json")),
                required_hooks_json=dumps(self._strings_from_payload(node, "contracts_json")),
                completion_conditions_json=dumps(self._strings_from_payload(node, "completion_conditions_json")),
                pov=payload.pov,
                target_words_min=payload.target_words_min,
                target_words_max=payload.target_words_max,
                pace=node.pace if node else "smooth",
                status="draft",
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(item)
            session.add(self.service._audit("chapter_contract.derived", "chapter_contract", item.id, {"requestId": request_id}, request_id))
            session.flush()
            return self._contract_dict(item)

    def list_chapter_contracts(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            rows = session.scalars(select(ChapterContract).where(ChapterContract.project_id == project.id).order_by(ChapterContract.chapter_number.asc(), ChapterContract.created_at.desc())).all()
            return [self._contract_dict(item) for item in rows]

    def get_chapter_contract(self, project_id: str, contract_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return self._contract_dict(self._get_contract(session, project.id, contract_id))

    def update_chapter_contract(self, project_id: str, contract_id: str, payload: ChapterContractUpdate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            item = self._get_contract(session, project.id, contract_id)
            if item.status == "locked":
                raise StoryError(409, "CHAPTER_CONTRACT_LOCKED", "Locked chapter contracts cannot be edited in place.")
            if item.revision != payload.expected_revision:
                raise StoryError(409, "CHAPTER_CONTRACT_REVISION_CONFLICT", "Chapter contract revision conflict.", {"currentRevision": item.revision})
            changes = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
            mapping = {
                "objective": "objective_json",
                "allowed_scope": "allowed_scope_json",
                "forbidden_scope": "forbidden_scope_json",
                "required_characters": "required_characters_json",
                "required_foreshadows": "required_foreshadows_json",
                "required_hooks": "required_hooks_json",
                "completion_conditions": "completion_conditions_json",
            }
            for key, value in changes.items():
                if key in mapping:
                    setattr(item, mapping[key], dumps(value))
                else:
                    setattr(item, key, value)
            if item.target_words_min > item.target_words_max:
                raise StoryError(422, "INVALID_CHAPTER_WORD_TARGET", "targetWordsMin must not exceed targetWordsMax.")
            item.revision += 1
            item.updated_at = _now()
            session.add(self.service._audit("chapter_contract.updated", "chapter_contract", item.id, {"requestId": request_id}, request_id))
            session.flush()
            return self._contract_dict(item)

    def lock_chapter_contract(self, project_id: str, contract_id: str, payload: ChapterContractLock, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        try:
            with self.service.db.project_write(project.id, project.folder_path) as session:
                item = self._get_contract(session, project.id, contract_id)
                if item.revision != payload.expected_revision:
                    raise StoryError(409, "CHAPTER_CONTRACT_REVISION_CONFLICT", "Chapter contract revision conflict.", {"currentRevision": item.revision})
                if item.status == "locked":
                    return self._contract_dict(item)
                if item.status != "draft":
                    raise StoryError(409, "CHAPTER_CONTRACT_NOT_RESUMABLE", "Only draft contracts can be locked.")
                now = _now()
                item.status = "locked"
                item.revision += 1
                item.locked_at = now
                item.updated_at = now
                session.add(self.service._audit("chapter_contract.locked", "chapter_contract", item.id, {"requestId": request_id}, request_id))
                session.flush()
                return self._contract_dict(item)
        except IntegrityError as exc:
            raise StoryError(409, "CHAPTER_CONTRACT_LOCK_CONFLICT", "Only one locked contract is allowed per project chapter.") from exc

    # ------------------------------------------------------------------
    # Jobs and drafts
    # ------------------------------------------------------------------
    def create_chapter_job(self, project_id: str, payload: ChapterJobCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        key = payload.idempotency_key or f"default:{payload.chapter_contract_id}"
        with self.service.db.project_write(project.id, project.folder_path) as session:
            contract = self._get_contract(session, project.id, payload.chapter_contract_id)
            if contract.status != "locked":
                raise StoryError(409, "CHAPTER_CONTRACT_NOT_LOCKED", "Chapter contract must be locked before creating a job.")
            existing = session.scalar(select(ChapterJob).where(
                ChapterJob.project_id == project.id,
                ChapterJob.chapter_contract_id == contract.id,
                ChapterJob.idempotency_key == key,
            ))
            if existing:
                return self._job_dict(existing, contract)
            now = _now()
            job = ChapterJob(
                id=str(uuid4()),
                project_id=project.id,
                chapter_contract_id=contract.id,
                status="queued",
                attempt_number=1,
                current_revision_round=0,
                idempotency_key=key,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            session.add(self.service._audit("chapter_job.created", "chapter_job", job.id, {"contractId": contract.id, "requestId": request_id}, request_id))
            session.flush()
            return self._job_dict(job, contract)

    def list_chapter_jobs(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            rows = session.scalars(select(ChapterJob).where(ChapterJob.project_id == project.id).order_by(ChapterJob.created_at.desc())).all()
            return [self._job_dict(item, session.get(ChapterContract, item.chapter_contract_id)) for item in rows]

    def get_chapter_job(self, project_id: str, job_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))

    def run_chapter_job(self, project_id: str, job_id: str, payload: ChapterJobRun, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            if job.status in ACTIVE_JOB_STATUSES:
                raise StoryError(409, "CHAPTER_JOB_ALREADY_RUNNING", "Chapter job is already running.")
            if job.status not in {"queued", "failed", "interrupted", "human_review"}:
                raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "Chapter job cannot be run from its current status.")
            contract = self._get_contract(session, project.id, job.chapter_contract_id)
            if contract.status != "locked":
                raise StoryError(409, "CHAPTER_CONTRACT_NOT_LOCKED", "Chapter contract must be locked before running.")
            now = _now()
            job.status = "compiling_context"
            job.started_at = job.started_at or now
            job.error_code = None
            job.diagnostic_json = None
            job.revision += 1
            job.updated_at = now

        try:
            context = self.service.phase4.compile_context(project.id, ContextCompileRequest(
                query=f"chapter {self._contract_number(project, job_id)}",
                role="chinese_writer",
                selected_node_id=self._contract_plan_node_id(project, job_id),
                token_budget=6000,
            ), request_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                job.status = "drafting"
                job.context_trace_id = context["traceId"]
                job.updated_at = _now()
            contract_data = self.get_chapter_contract(project.id, self._job_contract_id(project, job_id))
            draft_text, draft_run_id = self._complete_role_text(
                project,
                "chinese_writer",
                request_id,
                self._writer_messages(contract_data, context, payload.author_note),
                response_json=False,
            )
            draft = self._store_draft(project.id, project.folder_path, job_id, contract_data["id"], draft_text, draft_run_id, context["traceId"], "generated")
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                job.status = "extracting"
                job.updated_at = _now()
            extraction = self._extract_for_draft(project, draft["id"], request_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                job.status = "validating"
                job.updated_at = _now()
            self._validate_extraction(project, extraction["id"])
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                job.status = "human_review"
                job.updated_at = _now()
                session.add(self.service._audit("chapter_job.draft_ready", "chapter_job", job.id, {"draftId": draft["id"], "requestId": request_id}, request_id))
                session.flush()
                return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))
        except StoryError as exc:
            self._fail_job(project.id, project.folder_path, job_id, exc.code, {"message": exc.message, "details": exc.details})
            raise
        except ModelProviderError as exc:
            self._fail_job(project.id, project.folder_path, job_id, exc.code, {"message": exc.message, "retryable": exc.retryable})
            raise StoryError(502, exc.code, exc.message) from exc
        except Exception as exc:
            self._fail_job(project.id, project.folder_path, job_id, "CHAPTER_PIPELINE_FAILED", {"errorType": type(exc).__name__})
            raise

    def cancel_chapter_job(self, project_id: str, job_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            if job.status in ACTIVE_JOB_STATUSES:
                job.status = "cancel_requested"
                job.error_code = "cancel_requested"
            else:
                job.status = "cancelled"
                job.error_code = "cancelled"
                job.finished_at = _now()
            job.revision += 1
            job.updated_at = _now()
            session.add(self.service._audit("chapter_job.cancelled", "chapter_job", job.id, {"requestId": request_id}, request_id))
            return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))

    def retry_chapter_job(self, project_id: str, job_id: str, payload: ChapterJobRetry, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            if job.status not in {"failed", "interrupted", "cancelled", "human_review"}:
                raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "Chapter job cannot be retried from its current status.")
            job.status = "queued"
            job.attempt_number += 1
            job.error_code = None
            job.diagnostic_json = dumps({"retryReason": payload.reason})
            job.revision += 1
            job.updated_at = _now()
            session.add(self.service._audit("chapter_job.retry_queued", "chapter_job", job.id, {"reason": payload.reason, "requestId": request_id}, request_id))
            return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))

    def list_chapter_drafts(self, project_id: str, chapter_number: int) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            rows = session.scalars(
                select(ChapterDraft)
                .join(ChapterContract, ChapterContract.id == ChapterDraft.chapter_contract_id)
                .where(ChapterDraft.project_id == project.id, ChapterContract.chapter_number == chapter_number)
                .order_by(ChapterDraft.created_at.desc())
            ).all()
            return [self._draft_dict(item) for item in rows]

    def get_chapter_draft(self, project_id: str, draft_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            draft = self._get_draft(session, project.id, draft_id)
            out = self._draft_dict(draft)
            extraction = session.scalar(select(ChapterExtraction).where(ChapterExtraction.chapter_draft_id == draft.id).order_by(ChapterExtraction.created_at.desc()))
            if extraction:
                out["extraction"] = self._extraction_dict(extraction)
            return out

    # Quality/approval/commit methods are completed in the later work packages.
    def get_quality_report(self, project_id: str, job_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            current = self._current_draft(session, job.id)
            findings = session.scalars(select(QualityFinding).where(QualityFinding.project_id == project.id, QualityFinding.chapter_draft_id == current.id).order_by(QualityFinding.created_at.asc())).all() if current else []
            return {"jobId": job.id, "currentDraftId": current.id if current else None, "openBlockingCount": self._open_blocking_count(findings), "runs": [], "findings": [self._finding_dict(item) for item in findings]}

    def accept_quality_risk(self, project_id: str, finding_id: str, payload: QualityFindingAcceptRisk, request_id: str) -> dict[str, Any]:
        raise StoryError(501, "PHASE5_QUALITY_NOT_IMPLEMENTED", "Quality risk acceptance is implemented in the quality work package.")

    def revise_chapter_job(self, project_id: str, job_id: str, payload: ChapterRevisionRequest, request_id: str) -> dict[str, Any]:
        raise StoryError(501, "PHASE5_REVISION_NOT_IMPLEMENTED", "Revision is implemented in the quality work package.")

    def approve_chapter_job(self, project_id: str, job_id: str, payload: ChapterApproveRequest, request_id: str) -> dict[str, Any]:
        raise StoryError(501, "PHASE5_APPROVAL_NOT_IMPLEMENTED", "Approval is implemented in the commit work package.")

    def commit_chapter_job(self, project_id: str, job_id: str, payload: ChapterCommitRequest, request_id: str) -> dict[str, Any]:
        raise StoryError(501, "PHASE5_COMMIT_NOT_IMPLEMENTED", "Commit is implemented in the commit work package.")

    # ------------------------------------------------------------------
    # Model and persistence helpers
    # ------------------------------------------------------------------
    def _complete_role_text(self, project: Any, role: str, request_id: str, messages: list[dict[str, str]], *, response_json: bool) -> tuple[str, str]:
        resolved = self.service._resolve_role_model(role)
        if not resolved:
            raise StoryError(409, "CHAPTER_MODEL_ROLE_NOT_CONFIGURED", f"Model role is not configured: {role}", {"role": role})
        provider = resolved["provider"]
        model = resolved["model"]
        if not provider.is_enabled or not model.is_enabled:
            raise StoryError(409, "CHAPTER_MODEL_ROLE_NOT_CONFIGURED", f"Model role is disabled: {role}", {"role": role})
        if not provider.api_key_ref:
            raise StoryError(409, "MODEL_API_KEY_MISSING", "Provider API key is missing.", {"providerId": provider.id})
        api_key = self.service.secret_store.get_secret(provider.api_key_ref)
        if not api_key:
            raise StoryError(409, "MODEL_API_KEY_MISSING", "Provider API key is missing.", {"providerId": provider.id})
        run_id = str(uuid4())
        started = time.perf_counter()
        now = _now()
        with self.service.db.project_write(project.id, project.folder_path) as session:
            session.add(ModelRun(
                id=run_id,
                session_id=None,
                role=role,
                provider_id=provider.id,
                provider_name=provider.name,
                model_config_id=model.id,
                model_id=model.model_id,
                status="running",
                request_id=request_id,
                retry_count=0,
                started_at=now,
            ))
        client = OpenAICompatibleModelProvider(provider.base_url, api_key, provider.timeout_seconds, provider.max_retries)
        request_payload: dict[str, Any] = {
            "model": model.model_id,
            "messages": messages,
            "temperature": min(float(model.temperature), 0.7),
            "max_tokens": model.max_output_tokens,
        }
        if response_json:
            request_payload["response_format"] = {"type": "json_object"}
        try:
            result = asyncio.run(client.complete_chat(request_payload))
        except ModelProviderError as exc:
            self._complete_model_run_failure(project.id, project.folder_path, run_id, exc.code, started, {"retryable": exc.retryable})
            raise
        duration = int((time.perf_counter() - started) * 1000)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            run = session.get(ModelRun, run_id)
            if run:
                run.status = "succeeded"
                run.prompt_tokens = result.prompt_tokens
                run.completion_tokens = result.completion_tokens
                run.total_tokens = result.total_tokens
                run.retry_count = result.retry_count
                run.duration_ms = duration
                if result.actual_model:
                    run.model_id = result.actual_model
                run.ended_at = _now()
        return result.text, run_id

    def _complete_model_run_failure(self, project_id: str, folder_path: str, run_id: str, error_code: str, started: float, diagnostic: dict[str, Any]) -> None:
        duration = int((time.perf_counter() - started) * 1000)
        with self.service.db.project_write(project_id, folder_path) as session:
            run = session.get(ModelRun, run_id)
            if run:
                run.status = "failed"
                run.error_code = error_code
                run.duration_ms = duration
                run.diagnostic_json = dumps(diagnostic)
                run.ended_at = _now()

    def _store_draft(self, project_id: str, folder_path: str, job_id: str, contract_id: str, content: str, model_run_id: str | None, context_trace_id: str | None, kind: str, parent_id: str | None = None) -> dict[str, Any]:
        text = content.strip()
        if not text:
            raise StoryError(422, "CHAPTER_DRAFT_EMPTY", "Generated chapter draft is empty.")
        with self.service.db.project_write(project_id, folder_path) as session:
            next_version = (session.scalar(select(ChapterDraft.version_number).where(ChapterDraft.chapter_job_id == job_id).order_by(ChapterDraft.version_number.desc())) or 0) + 1
            now = _now()
            draft = ChapterDraft(
                id=str(uuid4()),
                project_id=project_id,
                chapter_job_id=job_id,
                chapter_contract_id=contract_id,
                version_number=next_version,
                parent_draft_id=parent_id,
                kind=kind,
                content_markdown=text,
                word_count=_word_count(text),
                checksum=stable_digest(text),
                model_run_id=model_run_id,
                context_trace_id=context_trace_id,
                status="candidate",
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(draft)
            session.flush()
            return self._draft_dict(draft)

    def _extract_for_draft(self, project: Any, draft_id: str, request_id: str) -> dict[str, Any]:
        with self.service.db.project(project.id, project.folder_path) as session:
            draft = self._get_draft(session, project.id, draft_id)
            contract = self._get_contract(session, project.id, draft.chapter_contract_id)
            content = draft.content_markdown
            contract_payload = self._contract_dict(contract)
        messages = [
            {"role": "system", "content": "Extract structured story state from the chapter. Return only JSON object with entities, facts, events, foreshadows, boundaries arrays. Facts that change current state must include expectedCurrentValue."},
            {"role": "user", "content": dumps({"contract": contract_payload, "chapterMarkdown": content})},
        ]
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                text, run_id = self._complete_role_text(project, "fact_extractor", request_id, messages + ([{"role": "system", "content": "Repair: return valid JSON object only."}] if attempt else []), response_json=True)
                data = _json_object_from_text(text)
                payload = self._normalize_extraction_payload(contract_payload, data)
                with self.service.db.project_write(project.id, project.folder_path) as session:
                    now = _now()
                    row = ChapterExtraction(
                        id=str(uuid4()),
                        project_id=project.id,
                        chapter_draft_id=draft_id,
                        model_run_id=run_id,
                        payload_json=dumps(payload),
                        schema_version=1,
                        status="candidate",
                        validation_errors_json="[]",
                        checksum=stable_digest(payload),
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                    session.flush()
                    return self._extraction_dict(row)
            except (ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                continue
        with self.service.db.project_write(project.id, project.folder_path) as session:
            now = _now()
            row = ChapterExtraction(
                id=str(uuid4()),
                project_id=project.id,
                chapter_draft_id=draft_id,
                model_run_id=None,
                payload_json="{}",
                schema_version=1,
                status="rejected",
                validation_errors_json=dumps([{"code": "invalid_json", "message": str(last_error)}]),
                checksum=stable_digest({}),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        raise StoryError(422, "CHAPTER_EXTRACTION_INVALID", "Fact extraction did not return valid JSON.")

    def _validate_extraction(self, project: Any, extraction_id: str) -> dict[str, Any]:
        with self.service.db.project_write(project.id, project.folder_path) as session:
            extraction = session.get(ChapterExtraction, extraction_id)
            if not extraction or extraction.project_id != project.id:
                raise StoryError(404, "CHAPTER_EXTRACTION_NOT_FOUND", "Chapter extraction not found.")
            data = _safe_loads(extraction.payload_json, {})
            try:
                self.service.phase4._validate_state_payload(session, project.id, data)
            except StoryError as exc:
                extraction.status = "rejected"
                extraction.validation_errors_json = dumps([{"code": exc.code, "message": exc.message, "details": exc.details}])
                extraction.updated_at = _now()
                raise StoryError(422, "CHAPTER_EXTRACTION_INVALID", "Chapter extraction failed validation.", {"sourceCode": exc.code, **exc.details}) from exc
            extraction.status = "validated"
            extraction.validation_errors_json = "[]"
            extraction.updated_at = _now()
            session.flush()
            return self._extraction_dict(extraction)

    def _normalize_extraction_payload(self, contract: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        return {
            "sourceId": f"chapter-{contract['chapterNumber']:04d}",
            "versionNumber": 1,
            "sourceKind": "chapter",
            "summary": str(data.get("summary") or contract["title"]),
            "entities": data.get("entities") if isinstance(data.get("entities"), list) else [],
            "facts": data.get("facts") if isinstance(data.get("facts"), list) else [],
            "events": data.get("events") if isinstance(data.get("events"), list) else [],
            "foreshadows": data.get("foreshadows") if isinstance(data.get("foreshadows"), list) else [],
            "boundaries": data.get("boundaries") if isinstance(data.get("boundaries"), list) else [],
        }

    # ------------------------------------------------------------------
    # Dict and lookup helpers
    # ------------------------------------------------------------------
    def _resolve_contract_node(self, session: Session, payload: ChapterContractDerive, plan: Plan | None) -> PlanNode | None:
        if payload.plan_node_id:
            node = session.get(PlanNode, payload.plan_node_id)
            if not node:
                raise StoryError(404, "PLAN_NODE_NOT_FOUND", "Plan node not found.")
            return node
        if not plan:
            return None
        return session.scalar(
            select(PlanNode)
            .where(PlanNode.target_chapter == payload.chapter_number)
            .order_by(PlanNode.importance.desc(), PlanNode.id.asc())
        ) or session.scalar(
            select(PlanNode)
            .where(PlanNode.range_min <= payload.chapter_number, PlanNode.range_max >= payload.chapter_number)
            .order_by(PlanNode.importance.desc(), PlanNode.target_chapter.asc())
        )

    def _strings_from_payload(self, node: PlanNode | None, attr: str) -> list[str]:
        if not node:
            return []
        value = _safe_loads(getattr(node, attr), [])
        return [item for item in value if isinstance(item, str)]

    def _get_contract(self, session: Session, project_id: str, contract_id: str) -> ChapterContract:
        item = session.get(ChapterContract, contract_id)
        if not item or item.project_id != project_id:
            raise StoryError(404, "CHAPTER_CONTRACT_NOT_FOUND", "Chapter contract not found.")
        return item

    def _get_job(self, session: Session, project_id: str, job_id: str) -> ChapterJob:
        item = session.get(ChapterJob, job_id)
        if not item or item.project_id != project_id:
            raise StoryError(404, "CHAPTER_JOB_NOT_FOUND", "Chapter job not found.")
        return item

    def _get_draft(self, session: Session, project_id: str, draft_id: str) -> ChapterDraft:
        item = session.get(ChapterDraft, draft_id)
        if not item or item.project_id != project_id:
            raise StoryError(404, "CHAPTER_DRAFT_NOT_FOUND", "Chapter draft not found.")
        return item

    def _contract_number(self, project: Any, job_id: str) -> int:
        with self.service.db.project(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            return self._get_contract(session, project.id, job.chapter_contract_id).chapter_number

    def _contract_plan_node_id(self, project: Any, job_id: str) -> str | None:
        with self.service.db.project(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            return self._get_contract(session, project.id, job.chapter_contract_id).plan_node_id

    def _job_contract_id(self, project: Any, job_id: str) -> str:
        with self.service.db.project(project.id, project.folder_path) as session:
            return self._get_job(session, project.id, job_id).chapter_contract_id

    def _current_draft(self, session: Session, job_id: str) -> ChapterDraft | None:
        return session.scalar(select(ChapterDraft).where(ChapterDraft.chapter_job_id == job_id).order_by(ChapterDraft.version_number.desc()))

    def _fail_job(self, project_id: str, folder_path: str, job_id: str, error_code: str, diagnostic: dict[str, Any]) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            job = session.get(ChapterJob, job_id)
            if job:
                job.status = "failed"
                job.error_code = error_code
                job.diagnostic_json = dumps(diagnostic)
                job.finished_at = _now()
                job.updated_at = _now()

    def _writer_messages(self, contract: dict[str, Any], context: dict[str, Any], author_note: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": "You are the chinese_writer for Story Agent. Write only the current chapter body in Chinese markdown. Do not output state JSON. Do not summarize future chapters."},
            {"role": "user", "content": dumps({"chapterContract": contract, "contextPackage": context, "authorNote": author_note})},
        ]

    def _open_blocking_count(self, findings: list[QualityFinding]) -> int:
        return sum(1 for item in findings if item.status == "open" and item.severity in BLOCKING_SEVERITIES)

    def _contract_dict(self, item: ChapterContract) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "chapterNumber": item.chapter_number,
            "title": item.title,
            "planNodeId": item.plan_node_id,
            "planNodeRevision": item.plan_node_revision,
            "canonRevisionDigest": item.canon_revision_digest,
            "stateSnapshotId": item.state_snapshot_id,
            "objective": _safe_loads(item.objective_json, {}),
            "allowedScope": _safe_loads(item.allowed_scope_json, {}),
            "forbiddenScope": _safe_loads(item.forbidden_scope_json, {}),
            "requiredCharacters": _safe_loads(item.required_characters_json, []),
            "requiredForeshadows": _safe_loads(item.required_foreshadows_json, []),
            "requiredHooks": _safe_loads(item.required_hooks_json, []),
            "completionConditions": _safe_loads(item.completion_conditions_json, []),
            "pov": item.pov,
            "targetWordsMin": item.target_words_min,
            "targetWordsMax": item.target_words_max,
            "pace": item.pace,
            "status": item.status,
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
            "lockedAt": item.locked_at,
        }

    def _job_dict(self, item: ChapterJob, contract: ChapterContract | None = None) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "chapterContractId": item.chapter_contract_id,
            "status": item.status,
            "attemptNumber": item.attempt_number,
            "currentRevisionRound": item.current_revision_round,
            "contextTraceId": item.context_trace_id,
            "idempotencyKey": item.idempotency_key,
            "errorCode": item.error_code,
            "diagnostic": _safe_loads(item.diagnostic_json, None),
            "revision": item.revision,
            "createdAt": item.created_at,
            "startedAt": item.started_at,
            "finishedAt": item.finished_at,
            "updatedAt": item.updated_at,
            "contract": self._contract_dict(contract) if contract else None,
        }

    def _draft_dict(self, item: ChapterDraft) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "chapterJobId": item.chapter_job_id,
            "chapterContractId": item.chapter_contract_id,
            "versionNumber": item.version_number,
            "parentDraftId": item.parent_draft_id,
            "kind": item.kind,
            "contentMarkdown": item.content_markdown,
            "wordCount": item.word_count,
            "checksum": item.checksum,
            "modelRunId": item.model_run_id,
            "contextTraceId": item.context_trace_id,
            "status": item.status,
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }

    def _extraction_dict(self, item: ChapterExtraction) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "chapterDraftId": item.chapter_draft_id,
            "modelRunId": item.model_run_id,
            "payload": _safe_loads(item.payload_json, {}),
            "schemaVersion": item.schema_version,
            "status": item.status,
            "validationErrors": _safe_loads(item.validation_errors_json, []),
            "checksum": item.checksum,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }

    def _finding_dict(self, item: QualityFinding) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "qualityRunId": item.quality_run_id,
            "chapterDraftId": item.chapter_draft_id,
            "ruleCode": item.rule_code,
            "severity": item.severity,
            "category": item.category,
            "message": item.message,
            "evidence": _safe_loads(item.evidence_json, []),
            "location": _safe_loads(item.location_json, {}),
            "suggestedFix": item.suggested_fix,
            "fingerprint": item.fingerprint,
            "status": item.status,
            "acceptedReason": item.accepted_reason,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }

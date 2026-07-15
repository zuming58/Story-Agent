from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AdaptationWorkspace,
    AutomationPolicy,
    CanonDocument,
    CanonEntity,
    CanonEntityType,
    CanonRelation,
    CanonRule,
    ChapterCommit,
    Plan,
    PlanNode,
    ProjectMeta,
    ShortStoryOrigin,
    ShortStoryStrategy,
    StoryMarker,
    utc_now,
)
from .schemas import ProjectCreate, ProjectOut, ShortStoryMaterializeCreate
from .services import StoryError, dumps, remap_json_identifier, safe_json_loads, stable_digest


ACTIVE_ORIGIN_STATUSES = {"creating", "staged"}


class Phase12Service:
    def __init__(self, service: Any):
        self.service = service

    def recover_interrupted_short_story_origins(self) -> None:
        now = utc_now()
        for project in self.service.list_projects():
            with self.service.db.project_write(project.id, project.folder_path) as session:
                for origin in session.scalars(select(ShortStoryOrigin).where(ShortStoryOrigin.status.in_(ACTIVE_ORIGIN_STATUSES))).all():
                    origin.status = "interrupted"
                    origin.diagnostic_json = dumps({"recovered": "startup_recovery"})
                    origin.revision += 1
                    origin.updated_at = now

    def materialize_short_story(self, source_project_id: str, workspace_id: str, payload: ShortStoryMaterializeCreate, request_id: str) -> dict[str, Any]:
        source_project = self.service.get_project(source_project_id)
        now = utc_now()
        staged_target_project_id: str | None = None
        with self.service.db.project_write(source_project.id, source_project.folder_path) as session:
            workspace = self.service.phase11._get_workspace(session, source_project.id, workspace_id)
            existing = None
            if payload.idempotency_key:
                existing = session.scalar(select(ShortStoryOrigin).where(
                    ShortStoryOrigin.project_id == source_project.id,
                    ShortStoryOrigin.idempotency_key == payload.idempotency_key,
                ))
                if existing and existing.status == "completed":
                    if not self._completed_request_matches(existing, source_project.id, workspace.id, payload):
                        raise StoryError(409, "SHORT_STORY_MATERIALIZE_IDEMPOTENCY_CONFLICT", "The idempotency key was already used for a different materialization request.")
                    return self._materialize_result(existing)
            self.service.phase11._check_workspace_revision(workspace, payload.expected_workspace_revision)
            strategy = self._validated_source_strategy(session, workspace)
            budget = self._validated_chapter_budget(strategy, payload.target_chapter_count or workspace.target_chapter_count)
            target_chapter_count = len(budget)
            target_word_count = payload.target_word_count or strategy.target_word_count
            minimum_viable_words = target_chapter_count * 500
            if target_word_count < minimum_viable_words:
                raise StoryError(
                    422,
                    "SHORT_STORY_WORD_BUDGET_INVALID",
                    "Target word count is too small for the selected chapter count.",
                    {
                        "targetWordCount": target_word_count,
                        "targetChapterCount": target_chapter_count,
                        "minimumTargetWordCount": minimum_viable_words,
                    },
                )
            target_title = payload.target_title or f"{source_project.title} · 短篇版"
            request_fingerprint = self._request_fingerprint(
                source_project.id,
                workspace.id,
                payload.expected_workspace_revision,
                strategy.id,
                strategy.revision,
                strategy.checksum,
                target_title,
                target_chapter_count,
                target_word_count,
            )
            if payload.idempotency_key:
                if existing:
                    if existing.request_fingerprint != request_fingerprint:
                        raise StoryError(409, "SHORT_STORY_MATERIALIZE_IDEMPOTENCY_CONFLICT", "The idempotency key was already used for a different materialization request.")
                    origin = existing
                    staged_target_project_id = origin.target_project_id
                    origin.status = "creating"
                    origin.diagnostic_json = None
                    origin.revision += 1
                    origin.updated_at = now
                else:
                    origin = self._new_origin(source_project.id, workspace, strategy, target_title, target_chapter_count, target_word_count, payload.idempotency_key, request_fingerprint)
                    session.add(origin)
            else:
                origin = self._new_origin(source_project.id, workspace, strategy, target_title, target_chapter_count, target_word_count, None, request_fingerprint)
                session.add(origin)
            self.service.phase11._ensure_workspace_source_not_drifted(session, workspace)
            session.flush()
            source_snapshot = self._source_snapshot(session, source_project.id, workspace, strategy, budget)
            origin.source_manifest_json = dumps(source_snapshot["sourceManifest"])
            origin.strategy_snapshot_json = dumps(source_snapshot["strategy"])
            origin.source_strategy_revision = strategy.revision
            origin.source_strategy_checksum = strategy.checksum
            origin.updated_at = now
            origin_id = origin.id

        target_project = None
        try:
            if staged_target_project_id:
                try:
                    target_project = self.service.get_project(staged_target_project_id)
                except StoryError as exc:
                    if exc.code != "PROJECT_NOT_FOUND":
                        raise
            if target_project is None:
                target_project = self.service.create_project(ProjectCreate(title=target_title, mode="short-form", total_chapters=target_chapter_count))
                with self.service.db.project_write(source_project.id, source_project.folder_path) as session:
                    origin = session.get(ShortStoryOrigin, origin_id)
                    assert origin
                    origin.target_project_id = target_project.id
                    origin.status = "staged"
                    origin.revision += 1
                    origin.updated_at = utc_now()
            self._populate_target_project(target_project, source_snapshot, origin_id, payload.idempotency_key, request_fingerprint, target_word_count)
            with self.service.db.project_write(source_project.id, source_project.folder_path) as session:
                origin = session.get(ShortStoryOrigin, origin_id)
                assert origin
                origin.target_project_id = target_project.id
                origin.status = "completed"
                origin.completed_at = utc_now()
                origin.revision += 1
                origin.updated_at = utc_now()
                session.add(self.service._audit("short_story.materialized", "short_story_origin", origin.id, {"targetProjectId": target_project.id, "requestId": request_id}, request_id))
                session.flush()
                return self._materialize_result(origin)
        except Exception as exc:
            with self.service.db.project_write(source_project.id, source_project.folder_path) as session:
                origin = session.get(ShortStoryOrigin, origin_id)
                if origin:
                    origin.status = "failed"
                    origin.target_project_id = target_project.id if target_project else None
                    origin.diagnostic_json = dumps({"errorType": type(exc).__name__, "code": getattr(exc, "code", None)})
                    origin.revision += 1
                    origin.updated_at = utc_now()
            raise

    def get_origin(self, project_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            origin = self._origin_for_project(session, project.id)
            if not origin:
                raise StoryError(404, "SHORT_STORY_ORIGIN_NOT_FOUND", "Short story origin not found.")
            return self._origin_dict(origin)

    def assert_total_chapter_update(self, project: Any, total_chapters: int) -> None:
        if project.mode != "short-form":
            return
        with self.service.db.project(project.id, project.folder_path) as session:
            origin = self._origin_for_project(session, project.id)
            if origin and origin.status == "completed" and total_chapters != origin.target_chapter_count:
                raise StoryError(
                    409,
                    "SHORT_STORY_TOTAL_IMMUTABLE",
                    "Materialized short-story chapter count is immutable.",
                    {"currentTotalChapters": project.total_chapters, "originTargetChapterCount": origin.target_chapter_count},
                )

    def readiness(self, project_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        checks: list[dict[str, Any]] = []

        def add(code: str, status: str, title: str, detail: str, chapter_number: int | None = None) -> None:
            checks.append({"code": code, "status": status, "title": title, "detail": detail, "chapterNumber": chapter_number})

        with self.service.db.project(project.id, project.folder_path) as session:
            meta = session.get(ProjectMeta, project.id)
            total = meta.total_chapters if meta else project.total_chapters
            current = meta.current_chapter if meta else project.current_chapter
            origin = self._origin_for_project(session, project.id)
            canon = session.get(CanonDocument, "story-core")
            plan = session.scalar(select(Plan))
            nodes = session.scalars(select(PlanNode).order_by(PlanNode.target_chapter)).all()
            beats: list[dict[str, Any]] = []
            for node in nodes:
                for beat in safe_json_loads(node.chapter_beats_json, []):
                    if isinstance(beat, dict):
                        beats.append(beat)
            beat_numbers = [beat.get("chapterNumber", beat.get("chapter_number")) for beat in beats]
            current_commits = set(session.scalars(select(ChapterCommit.chapter_number).where(
                ChapterCommit.project_id == project.id,
                ChapterCommit.is_current.is_(True),
                ChapterCommit.status == "official",
            )).all())

        add("SHORT_STORY_PROJECT_MODE", "ready" if project.mode == "short-form" else "blocked", "Short-form project", "Project mode is short-form." if project.mode == "short-form" else "Project is not a short-form project.")
        add("SHORT_STORY_CHAPTER_RANGE", "ready" if 1 <= total <= 30 else "blocked", "Chapter range", f"Short story has {total} planned chapters." if 1 <= total <= 30 else "Short stories must have 1-30 chapters.")
        add("SHORT_STORY_CURRENT_PROGRESS", "ready" if 0 <= current <= total else "blocked", "Current progress", f"Current chapter is {current}." if 0 <= current <= total else "Current chapter is outside the planned range.")
        add("SHORT_STORY_CANON_LOCKED", "ready" if canon and canon.status == "locked" else "blocked", "Canon locked", "Target Canon is locked." if canon and canon.status == "locked" else "Lock target Canon before production.")
        missing = [chapter for chapter in range(1, total + 1) if beat_numbers.count(chapter) == 0]
        duplicates = sorted({chapter for chapter in beat_numbers if isinstance(chapter, int) and beat_numbers.count(chapter) > 1})
        extras = [chapter for chapter in beat_numbers if not isinstance(chapter, int) or chapter < 1 or chapter > total]
        plan_range_ready = bool(plan and plan.chapter_start == 1 and plan.chapter_end == total)
        plan_ready = bool(plan and plan_range_ready and not missing and not duplicates and not extras and len(beats) == total)
        plan_detail = "Every chapter has exactly one short-story beat."
        if not plan_ready:
            plan_detail = f"Plan range or beats are inconsistent; missing={missing}, duplicates={duplicates}, extras={extras}."
        add("SHORT_STORY_PLAN_READY", "ready" if plan_ready else "blocked", "Chapter beats", plan_detail, missing[0] if missing else None)
        budget_errors: list[int] = []
        strategy_budget = safe_json_loads(origin.strategy_snapshot_json, {}).get("chapterBudget", []) if origin else []
        expected_by_chapter = {
            item.get("chapterNumber"): item
            for item in strategy_budget
            if isinstance(item, dict) and isinstance(item.get("chapterNumber"), int)
        }
        for beat in beats:
            chapter = beat.get("chapterNumber", beat.get("chapter_number"))
            pace_budget = beat.get("paceBudget", beat.get("pace_budget"))
            if not isinstance(chapter, int) or not isinstance(pace_budget, dict):
                if isinstance(chapter, int):
                    budget_errors.append(chapter)
                continue
            events = pace_budget.get("majorEvents", pace_budget.get("major_events"))
            maximum = pace_budget.get("maxMajorEvents", pace_budget.get("max_major_events"))
            target_min = pace_budget.get("targetWordsMin", pace_budget.get("target_words_min"))
            target_max = pace_budget.get("targetWordsMax", pace_budget.get("target_words_max"))
            if (
                not isinstance(events, list)
                or not events
                or not isinstance(maximum, int)
                or isinstance(maximum, bool)
                or maximum < len(events)
                or not isinstance(target_min, int)
                or isinstance(target_min, bool)
                or not isinstance(target_max, int)
                or isinstance(target_max, bool)
                or target_min < 1
                or target_max < target_min
            ):
                budget_errors.append(chapter)
                continue
            expected = expected_by_chapter.get(chapter)
            if expected and (events != expected.get("majorEvents") or maximum != expected.get("maxMajorEvents")):
                budget_errors.append(chapter)
        origin_ready = not origin or (
            origin.status == "completed"
            and origin.target_project_id == project.id
            and origin.target_chapter_count == total
        )
        add("SHORT_STORY_ORIGIN_READY", "ready" if origin_ready else "blocked", "Materialization origin", "Origin matches the target project." if origin_ready else "Origin status or target chapter count does not match this project.")
        add("SHORT_STORY_PLAN_BUDGET", "ready" if not budget_errors and len(beats) == total else "blocked", "Chapter budgets", "Every chapter retains its event and word budget." if not budget_errors and len(beats) == total else "Invalid chapter budgets: " + "、".join(map(str, sorted(set(budget_errors)))), min(budget_errors) if budget_errors else None)
        extra_commits = [chapter for chapter in current_commits if chapter > total or chapter > 30]
        add("SHORT_STORY_COMMIT_RANGE", "ready" if not extra_commits else "blocked", "Official commit range", "Official commits are within range." if not extra_commits else "Out-of-range commits: " + "、".join(map(str, sorted(extra_commits))), min(extra_commits) if extra_commits else None)
        return {
            "projectId": project.id,
            "ready": not any(item["status"] == "blocked" for item in checks),
            "totalChapters": total,
            "currentChapter": current,
            "origin": self._origin_dict(origin) if origin else None,
            "checks": checks,
            "updatedAt": utc_now(),
        }

    def repair_restored_metadata(self, project_id: str, folder_path: str, source_project_id: str) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            for origin in session.scalars(select(ShortStoryOrigin)).all():
                origin.project_id = project_id
                external_target = bool(
                    origin.source_project_id == source_project_id
                    and origin.target_project_id
                    and origin.target_project_id != source_project_id
                )
                if external_target:
                    origin.status = "detached"
                    origin.idempotency_key = None
                    origin.diagnostic_json = dumps({
                        "recovered": "backup_restore_source_clone",
                        "originalSourceProjectId": source_project_id,
                        "originalTargetProjectId": origin.target_project_id,
                    })
                    origin.revision += 1
                    origin.updated_at = utc_now()
                    continue
                if origin.source_project_id == source_project_id:
                    origin.source_project_id = project_id
                    origin.idempotency_key = None
                if origin.target_project_id == source_project_id:
                    origin.target_project_id = project_id
                origin.source_manifest_json = dumps(remap_json_identifier(safe_json_loads(origin.source_manifest_json, {}), source_project_id, project_id))
                origin.strategy_snapshot_json = dumps(remap_json_identifier(safe_json_loads(origin.strategy_snapshot_json, {}), source_project_id, project_id))
                if origin.status in ACTIVE_ORIGIN_STATUSES:
                    origin.status = "interrupted"
                    origin.diagnostic_json = dumps({"recovered": "backup_restore"})
                    origin.revision += 1
                origin.updated_at = utc_now()

    def _validated_source_strategy(self, session: Session, workspace: AdaptationWorkspace) -> ShortStoryStrategy:
        if workspace.kind != "short_story":
            raise StoryError(409, "SHORT_STORY_WORKSPACE_REQUIRED", "Only short story workspaces can be materialized.")
        if workspace.status not in {"ready", "locked"}:
            raise StoryError(409, "SHORT_STORY_WORKSPACE_NOT_READY", "Workspace must be ready or locked before materialization.")
        strategy = self.service.phase11._active_strategy(session, workspace)
        if not strategy:
            raise StoryError(409, "SHORT_STORY_STRATEGY_REQUIRED", "Apply a short story strategy before materialization.")
        if strategy.checksum != self.service.phase11._strategy_checksum(strategy):
            raise StoryError(409, "SHORT_STORY_STRATEGY_CHECKSUM_INVALID", "Short story strategy checksum is invalid.")
        blocking = self.service.phase11._open_blocking_findings(session, workspace.id)
        if blocking:
            raise StoryError(409, "ADAPTATION_FINDINGS_BLOCKING", "Open adaptation findings block materialization.", {"findingCount": len(blocking)})
        return strategy

    def _validated_chapter_budget(self, strategy: ShortStoryStrategy, requested_count: int | None) -> list[dict[str, Any]]:
        raw = safe_json_loads(strategy.chapter_budget_json, [])
        if not isinstance(raw, list) or not raw:
            raise StoryError(409, "SHORT_STORY_CHAPTER_BUDGET_INVALID", "Short story strategy must include chapterBudget.")
        budget: list[dict[str, Any]] = []
        seen: set[int] = set()
        for item in raw:
            if not isinstance(item, dict):
                raise StoryError(409, "SHORT_STORY_CHAPTER_BUDGET_INVALID", "Each chapter budget item must be an object.")
            chapter = item.get("chapterNumber", item.get("chapter_number"))
            if not isinstance(chapter, int) or isinstance(chapter, bool) or chapter < 1 or chapter > 30:
                raise StoryError(409, "SHORT_STORY_CHAPTER_BUDGET_INVALID", "Chapter budget numbers must be within 1-30.", {"chapterNumber": chapter})
            if chapter in seen:
                raise StoryError(409, "SHORT_STORY_CHAPTER_BUDGET_DUPLICATE", "Chapter budget contains duplicate chapter numbers.", {"chapterNumber": chapter})
            events = item.get("majorEvents", item.get("events", []))
            if not isinstance(events, list) or not events or not all(isinstance(event, str) and event.strip() for event in events):
                raise StoryError(409, "SHORT_STORY_CHAPTER_BUDGET_EMPTY_EVENTS", "Every short story chapter needs at least one major event.", {"chapterNumber": chapter})
            max_events = item.get("maxMajorEvents", max(1, len(events)))
            if not isinstance(max_events, int) or isinstance(max_events, bool) or max_events < 1 or max_events > 100:
                raise StoryError(409, "SHORT_STORY_EVENT_BUDGET_INVALID", "maxMajorEvents must be an integer within 1-100.", {"chapterNumber": chapter, "maxMajorEvents": max_events})
            if len(events) > max_events:
                raise StoryError(409, "SHORT_STORY_EVENT_BUDGET", "Chapter major events exceed maxMajorEvents.", {"chapterNumber": chapter, "eventCount": len(events), "maxMajorEvents": max_events})
            seen.add(chapter)
            budget.append({
                **item,
                "chapterNumber": chapter,
                "majorEvents": [event.strip() for event in events],
                "maxMajorEvents": max_events,
            })
        budget.sort(key=lambda value: value["chapterNumber"])
        expected = list(range(1, len(budget) + 1))
        actual = [item["chapterNumber"] for item in budget]
        if actual != expected:
            raise StoryError(409, "SHORT_STORY_CHAPTER_BUDGET_GAP", "Chapter budget must be continuous from chapter 1.", {"chapterNumbers": actual})
        if requested_count is not None and requested_count != len(budget):
            raise StoryError(409, "SHORT_STORY_TARGET_CHAPTER_CONFLICT", "Requested target chapter count does not match strategy chapterBudget.", {"requested": requested_count, "strategy": len(budget)})
        return budget

    def _new_origin(
        self,
        project_id: str,
        workspace: AdaptationWorkspace,
        strategy: ShortStoryStrategy,
        target_title: str,
        target_chapter_count: int,
        target_word_count: int,
        idempotency_key: str | None,
        request_fingerprint: str,
    ) -> ShortStoryOrigin:
        now = utc_now()
        return ShortStoryOrigin(
            id=str(uuid4()),
            project_id=project_id,
            source_project_id=project_id,
            source_workspace_id=workspace.id,
            source_strategy_id=strategy.id,
            source_strategy_revision=strategy.revision,
            source_strategy_checksum=strategy.checksum,
            source_manifest_json=dumps(safe_json_loads(workspace.source_manifest_json, {})),
            strategy_snapshot_json=dumps(self._strategy_snapshot(strategy)),
            target_title=target_title,
            target_chapter_count=target_chapter_count,
            target_word_count=target_word_count,
            status="creating",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            revision=1,
            created_at=now,
            updated_at=now,
        )

    def _source_snapshot(self, session: Session, project_id: str, workspace: AdaptationWorkspace, strategy: ShortStoryStrategy, budget: list[dict[str, Any]]) -> dict[str, Any]:
        source_manifest = self.service.phase11._current_manifest_for_workspace(session, workspace)
        canon = session.get(CanonDocument, "story-core")
        assert canon
        entity_types = session.scalars(select(CanonEntityType)).all()
        entities = session.scalars(select(CanonEntity)).all()
        relations = session.scalars(select(CanonRelation)).all()
        rules = session.scalars(select(CanonRule)).all()
        return {
            "sourceProjectId": project_id,
            "sourceWorkspace": self.service.phase11._workspace_dict(session, workspace),
            "sourceManifest": source_manifest,
            "strategy": {**self._strategy_snapshot(strategy), "chapterBudget": budget},
            "canon": {
                "document": {
                    "id": canon.id,
                    "title": canon.title,
                    "kind": canon.kind,
                    "contentMarkdown": canon.content_markdown,
                    "revision": canon.revision,
                    "checksum": self.service.phase11._canon_manifest(canon)["checksum"],
                },
                "entityTypes": [self._row_payload(row, ["id", "name", "display_name", "schema_json", "is_system", "status", "revision", "source_document_id"]) for row in entity_types],
                "entities": [self._row_payload(row, ["id", "entity_type_id", "canonical_name", "aliases_json", "attributes_json", "status", "revision", "source_document_id"]) for row in entities],
                "relations": [self._row_payload(row, ["id", "subject_entity_id", "predicate", "object_entity_id", "object_value_json", "status", "revision", "source_document_id"]) for row in relations],
                "rules": [self._row_payload(row, ["id", "rule_code", "category", "statement", "severity", "constraint_json", "status", "revision", "source_document_id"]) for row in rules],
            },
        }

    @staticmethod
    def _row_payload(row: Any, fields: list[str]) -> dict[str, Any]:
        return {field: getattr(row, field) for field in fields}

    @staticmethod
    def _strategy_snapshot(strategy: ShortStoryStrategy) -> dict[str, Any]:
        return {
            "id": strategy.id,
            "workspaceId": strategy.workspace_id,
            "revision": strategy.revision,
            "checksum": strategy.checksum,
            "coreHook": strategy.core_hook,
            "openingHook": strategy.opening_hook,
            "mainConflict": strategy.main_conflict,
            "emotionalCurve": safe_json_loads(strategy.emotional_curve_json, []),
            "ending": strategy.ending,
            "pointOfView": strategy.point_of_view,
            "targetWordCount": strategy.target_word_count,
            "chapterBudget": safe_json_loads(strategy.chapter_budget_json, []),
            "characterMergePlan": safe_json_loads(strategy.character_merge_plan_json, []),
            "foreshadowPlan": safe_json_loads(strategy.foreshadow_plan_json, {}),
            "compressionRules": safe_json_loads(strategy.compression_rules_json, {}),
            "forbiddenReveals": safe_json_loads(strategy.forbidden_reveals_json, []),
        }

    @staticmethod
    def _request_fingerprint(
        source_project_id: str,
        workspace_id: str,
        workspace_revision: int,
        strategy_id: str,
        strategy_revision: int,
        strategy_checksum: str,
        target_title: str,
        target_chapter_count: int,
        target_word_count: int,
        *,
        include_source_project: bool = True,
    ) -> str:
        value = {
            "workspaceId": workspace_id,
            "workspaceRevision": workspace_revision,
            "strategyId": strategy_id,
            "strategyRevision": strategy_revision,
            "strategyChecksum": strategy_checksum,
            "targetTitle": target_title,
            "targetChapterCount": target_chapter_count,
            "targetWordCount": target_word_count,
        }
        if include_source_project:
            value["sourceProjectId"] = source_project_id
        return stable_digest(value)

    def _completed_request_matches(
        self,
        origin: ShortStoryOrigin,
        source_project_id: str,
        workspace_id: str,
        payload: ShortStoryMaterializeCreate,
    ) -> bool:
        values = (
            source_project_id,
            workspace_id,
            payload.expected_workspace_revision,
            origin.source_strategy_id,
            origin.source_strategy_revision,
            origin.source_strategy_checksum,
            payload.target_title or origin.target_title,
            payload.target_chapter_count or origin.target_chapter_count,
            payload.target_word_count or origin.target_word_count,
        )
        current = self._request_fingerprint(*values)
        legacy = self._request_fingerprint(*values, include_source_project=False)
        return origin.request_fingerprint in {current, legacy}

    def _populate_target_project(
        self,
        target_project: Any,
        source_snapshot: dict[str, Any],
        origin_id: str,
        idempotency_key: str | None,
        request_fingerprint: str,
        target_word_count: int,
    ) -> None:
        strategy = source_snapshot["strategy"]
        budget = strategy["chapterBudget"]
        now = utc_now()
        average_words = int(target_word_count / max(1, len(budget)))
        target_min = max(350, int(average_words * 0.7))
        target_max = max(target_min, int(average_words * 1.3))
        with self.service.db.project_write(target_project.id, target_project.folder_path) as session:
            meta = session.get(ProjectMeta, target_project.id)
            if meta:
                meta.mode = "short-form"
                meta.current_chapter = 0
                meta.total_chapters = len(budget)
                meta.updated_at = now
            self._install_target_canon(session, target_project.title, source_snapshot)
            self._install_target_plan(session, target_project.title, strategy, target_min, target_max)
            policy = session.get(AutomationPolicy, target_project.id)
            if not policy:
                policy = AutomationPolicy(project_id=target_project.id, created_at=now, updated_at=now)
                session.add(policy)
            policy.chapters_per_run = min(3, len(budget))
            policy.target_words_min = target_min
            policy.target_words_max = target_max
            policy.max_revision_rounds = 2
            policy.updated_at = now
            origin = session.get(ShortStoryOrigin, origin_id)
            if origin is None:
                origin = ShortStoryOrigin(id=origin_id, created_at=now, revision=1)
                session.add(origin)
            origin.project_id = target_project.id
            origin.source_project_id = source_snapshot["sourceProjectId"]
            origin.source_workspace_id = source_snapshot["sourceWorkspace"]["id"]
            origin.source_strategy_id = strategy["id"]
            origin.source_strategy_revision = strategy["revision"]
            origin.source_strategy_checksum = strategy["checksum"]
            origin.source_manifest_json = dumps(source_snapshot["sourceManifest"])
            origin.strategy_snapshot_json = dumps(strategy)
            origin.target_project_id = target_project.id
            origin.target_title = target_project.title
            origin.target_chapter_count = len(budget)
            origin.target_word_count = target_word_count
            origin.status = "completed"
            origin.idempotency_key = idempotency_key
            origin.request_fingerprint = request_fingerprint
            origin.diagnostic_json = None
            origin.completed_at = now
            origin.updated_at = now
            session.add(self.service._audit("short_story.origin_installed", "short_story_origin", origin.id, {"sourceProjectId": origin.source_project_id}, "system"))

    def _install_target_canon(self, session: Session, title: str, source_snapshot: dict[str, Any]) -> None:
        canon_payload = source_snapshot["canon"]
        strategy = source_snapshot["strategy"]
        now = utc_now()
        document = session.get(CanonDocument, "story-core")
        content = (
            f"{canon_payload['document']['contentMarkdown']}\n\n"
            "## 短篇生产边界\n"
            f"- 核心钩子：{strategy.get('coreHook', '')}\n"
            f"- 主冲突：{strategy.get('mainConflict', '')}\n"
            f"- 结局闭环：{strategy.get('ending', '')}\n"
            f"- 人物合并：{dumps(strategy.get('characterMergePlan', []))}\n"
            f"- 压缩规则：{dumps(strategy.get('compressionRules', {}))}\n"
            f"- 禁止提前揭示：{dumps(strategy.get('forbiddenReveals', []))}\n"
        )
        if document:
            document.title = f"{title} Story Core"
            document.kind = "story"
            document.content_markdown = content
            document.status = "locked"
            document.revision += 1
            document.updated_at = now
            document.locked_at = now
        else:
            session.add(CanonDocument(
                id="story-core",
                title=f"{title} Story Core",
                kind="story",
                content_markdown=content,
                status="locked",
                revision=1,
                created_at=now,
                updated_at=now,
                locked_at=now,
            ))
        entity_type_ids: dict[str, str] = {}
        for item in canon_payload.get("entityTypes", []):
            row = session.get(CanonEntityType, item["id"])
            if row is None:
                row = session.scalar(select(CanonEntityType).where(CanonEntityType.name == item["name"]))
            if row is None:
                row = CanonEntityType(id=item["id"], name=item["name"], created_at=now)
                session.add(row)
            entity_type_ids[item["id"]] = row.id
            row.display_name = item["display_name"]
            row.schema_json = item["schema_json"]
            row.is_system = item["is_system"]
            row.status = item["status"]
            row.revision = max(row.revision or 1, item["revision"])
            row.source_document_id = item.get("source_document_id")
            row.updated_at = now
            row.locked_at = now if item["status"] == "locked" else None
        session.flush()
        entity_ids: dict[str, str] = {}
        for item in canon_payload.get("entities", []):
            row = session.get(CanonEntity, item["id"])
            if row is None:
                row = session.scalar(select(CanonEntity).where(CanonEntity.canonical_name == item["canonical_name"]))
            if row is None:
                row = CanonEntity(id=item["id"], canonical_name=item["canonical_name"], created_at=now)
                session.add(row)
            entity_ids[item["id"]] = row.id
            row.entity_type_id = entity_type_ids.get(item["entity_type_id"], item["entity_type_id"])
            row.aliases_json = item["aliases_json"]
            row.attributes_json = item["attributes_json"]
            row.status = item["status"]
            row.revision = max(row.revision or 1, item["revision"])
            row.source_document_id = item.get("source_document_id")
            row.updated_at = now
            row.locked_at = now if item["status"] == "locked" else None
        session.flush()
        for item in canon_payload.get("relations", []):
            row = session.get(CanonRelation, item["id"])
            if row is None:
                row = CanonRelation(id=item["id"], created_at=now)
                session.add(row)
            row.subject_entity_id = entity_ids.get(item["subject_entity_id"], item["subject_entity_id"])
            source_object_id = item.get("object_entity_id")
            row.object_entity_id = entity_ids.get(source_object_id, source_object_id) if source_object_id else None
            row.predicate = item["predicate"]
            row.object_value_json = item.get("object_value_json")
            row.status = item["status"]
            row.revision = max(row.revision or 1, item["revision"])
            row.source_document_id = item.get("source_document_id")
            row.updated_at = now
            row.locked_at = now if item["status"] == "locked" else None
        for item in canon_payload.get("rules", []):
            row = session.get(CanonRule, item["id"])
            if row is None:
                row = session.scalar(select(CanonRule).where(CanonRule.rule_code == item["rule_code"]))
            if row is None:
                row = CanonRule(id=item["id"], rule_code=item["rule_code"], created_at=now)
                session.add(row)
            row.category = item["category"]
            row.statement = item["statement"]
            row.severity = item["severity"]
            row.constraint_json = item["constraint_json"]
            row.status = item["status"]
            row.revision = max(row.revision or 1, item["revision"])
            row.source_document_id = item.get("source_document_id")
            row.updated_at = now
            row.locked_at = now if item["status"] == "locked" else None

    def _install_target_plan(self, session: Session, title: str, strategy: dict[str, Any], target_min: int, target_max: int) -> None:
        plan = session.scalar(select(Plan))
        if not plan:
            plan = Plan(id=str(uuid4()), book_title=title, volume_title="短篇", arc_title="短篇主线", chapter_start=1, chapter_end=len(strategy["chapterBudget"]), revision=1)
            session.add(plan)
            session.flush()
        else:
            plan.book_title = title
            plan.volume_title = "短篇"
            plan.arc_title = "短篇主线"
            plan.chapter_start = 1
            plan.chapter_end = len(strategy["chapterBudget"])
            plan.revision += 1
        for node in session.scalars(select(PlanNode)).all():
            session.delete(node)
        for marker in session.scalars(select(StoryMarker)).all():
            session.delete(marker)
        beats = []
        forbidden_reveals = [str(item) for item in strategy.get("forbiddenReveals", []) if isinstance(item, str)]
        foreshadow_plan = strategy.get("foreshadowPlan", {})
        retained_foreshadows = self._string_values(foreshadow_plan.get("retain", [])) if isinstance(foreshadow_plan, dict) else []
        resolved_foreshadows = self._string_values(foreshadow_plan.get("resolved", [])) if isinstance(foreshadow_plan, dict) else []
        for item in strategy["chapterBudget"]:
            chapter = item["chapterNumber"]
            major_events = [str(value) for value in item.get("majorEvents", item.get("events", []))]
            hooks = [str(value) for value in item.get("hooks", []) if isinstance(value, str)]
            if chapter == 1 and strategy.get("openingHook"):
                hooks = [strategy["openingHook"], *hooks]
            foreshadows = [str(value) for value in item.get("foreshadows", []) if isinstance(value, str)]
            if chapter == 1:
                foreshadows = [*retained_foreshadows, *foreshadows]
            if chapter == len(strategy["chapterBudget"]):
                foreshadows = [*foreshadows, *resolved_foreshadows]
            completion_conditions = [str(value) for value in item.get("completionConditions", major_events) if isinstance(value, str)]
            if chapter == len(strategy["chapterBudget"]) and strategy.get("ending"):
                completion_conditions.append(str(strategy["ending"]))
            knowledge_boundaries = [
                value
                for value in item.get("knowledgeBoundaries", [])
                if isinstance(value, (dict, str))
            ] if isinstance(item.get("knowledgeBoundaries", []), list) else []
            beat = {
                "chapterNumber": chapter,
                "title": str(item.get("title") or f"短篇第 {chapter} 章"),
                "objective": str(item.get("objective") or "；".join(major_events)),
                "completionConditions": completion_conditions,
                "hooks": hooks,
                "foreshadows": foreshadows,
                "requiredCharacters": [str(value) for value in item.get("requiredCharacters", []) if isinstance(value, str)],
                "forbidden": forbidden_reveals,
                "knowledgeBoundaries": knowledge_boundaries,
                "allowedAbilities": self._string_values(item.get("allowedAbilities", [])),
                "forbiddenAbilities": self._string_values(item.get("forbiddenAbilities", [])),
                "allowedItems": self._string_values(item.get("allowedItems", [])),
                "forbiddenItems": self._string_values(item.get("forbiddenItems", [])),
                "paceBudget": {
                    "maxMajorEvents": item["maxMajorEvents"],
                    "majorEvents": major_events,
                    "targetWordsMin": target_min,
                    "targetWordsMax": target_max,
                },
            }
            beats.append(beat)
        session.add(PlanNode(
            id="short-story-window",
            plan_id=plan.id,
            title="短篇完整章节窗口",
            type="章节窗口",
            target_chapter=len(beats),
            range_min=1,
            range_max=len(beats),
            importance=5,
            note=f"由短篇策略 {strategy['id']} 物化；主冲突：{strategy.get('mainConflict', '')}",
            prerequisites_json=dumps(["短篇 Canon 已锁定", "短篇策略已物化"]),
            completion_conditions_json=dumps([strategy.get("ending", "完成短篇结局闭环")]),
            foreshadows_json=dumps(self._string_values(strategy.get("foreshadowPlan", {}))),
            contracts_json=dumps([strategy.get("coreHook", ""), strategy.get("mainConflict", "")]),
            chapter_beats_json=dumps(beats),
            pace="tight",
            revision=1,
        ))

    def _origin_for_project(self, session: Session, project_id: str) -> ShortStoryOrigin | None:
        return session.scalar(select(ShortStoryOrigin).where(
            ShortStoryOrigin.project_id == project_id,
            ShortStoryOrigin.target_project_id == project_id,
        ).order_by(ShortStoryOrigin.created_at.desc()))

    def _materialize_result(self, origin: ShortStoryOrigin) -> dict[str, Any]:
        target = self.service.get_project(origin.target_project_id) if origin.target_project_id else None
        return {
            "origin": self._origin_dict(origin),
            "targetProject": ProjectOut.model_validate(target).model_dump(by_alias=True) if target else None,
        }

    @classmethod
    def _string_values(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list):
            return [item for nested in value for item in cls._string_values(nested)]
        if isinstance(value, dict):
            return [item for nested in value.values() for item in cls._string_values(nested)]
        return []

    @staticmethod
    def _origin_dict(origin: ShortStoryOrigin) -> dict[str, Any]:
        return {
            "id": origin.id,
            "projectId": origin.project_id,
            "sourceProjectId": origin.source_project_id,
            "sourceWorkspaceId": origin.source_workspace_id,
            "sourceStrategyId": origin.source_strategy_id,
            "sourceStrategyRevision": origin.source_strategy_revision,
            "sourceStrategyChecksum": origin.source_strategy_checksum,
            "sourceManifest": safe_json_loads(origin.source_manifest_json, {}),
            "strategySnapshot": safe_json_loads(origin.strategy_snapshot_json, {}),
            "targetProjectId": origin.target_project_id,
            "targetTitle": origin.target_title,
            "targetChapterCount": origin.target_chapter_count,
            "targetWordCount": origin.target_word_count,
            "status": origin.status,
            "idempotencyKey": origin.idempotency_key,
            "requestFingerprint": origin.request_fingerprint,
            "diagnostic": safe_json_loads(origin.diagnostic_json, None) if origin.diagnostic_json else None,
            "revision": origin.revision,
            "createdAt": origin.created_at,
            "completedAt": origin.completed_at,
            "updatedAt": origin.updated_at,
        }

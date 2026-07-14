from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AutomationRun,
    AutomationRunItem,
    CanonDocument,
    CanonEntity,
    CanonRule,
    ChapterCommit,
    ChapterDraft,
    ChapterJob,
    EnduranceCheckpoint,
    EnduranceFinding,
    EnduranceReport,
    EnduranceRun,
    EnduranceSuite,
    Foreshadow,
    KnowledgeBoundary,
    Plan,
    PlanNode,
    ProjectMeta,
    SourceVersion,
    StateFact,
    StateSnapshot,
)
from .schemas import AutomationRunCreate, EnduranceRunCreate, EnduranceSuiteCreate, EnduranceSuiteUpdate
from .services import StoryError, dumps, loads, stable_digest


ALLOWED_COUNTS = {5, 10, 20, 30}
DEFAULT_RULES = [
    "ENDURANCE_COMMIT_SEQUENCE_GAP",
    "ENDURANCE_DUPLICATE_CURRENT_COMMIT",
    "ENDURANCE_STATE_NON_ATOMIC",
    "ENDURANCE_PACING_EARLY",
    "ENDURANCE_PACING_LATE",
    "ENDURANCE_CHARACTER_EARLY",
    "ENDURANCE_ABILITY_WINDOW",
    "ENDURANCE_ITEM_STATE_DRIFT",
    "ENDURANCE_KNOWLEDGE_LEAK",
    "ENDURANCE_FORESHADOW_MISSED",
    "ENDURANCE_REVISION_LIMIT_BREACH",
    "ENDURANCE_COST_LIMIT",
    "ENDURANCE_RESTART_DUPLICATION",
]
ACTIVE_RUN_STATUSES = {"queued", "running", "paused", "cancel_requested"}
TERMINAL_RUN_STATUSES = {"blocked", "completed", "cancelled", "interrupted", "failed"}
SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2, "blocker": 3}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _severity_at_least(value: str, threshold: str) -> bool:
    return SEVERITY_ORDER.get(value, 0) >= SEVERITY_ORDER.get(threshold, 3)


class Phase10Service:
    def __init__(self, service: Any):
        self.service = service

    def recover_interrupted_endurance(self) -> None:
        now = _now()
        for project in self.service.list_projects():
            with self.service.db.project_write(project.id, project.folder_path) as session:
                for run in session.scalars(select(EnduranceRun).where(EnduranceRun.status.in_(["queued", "running", "paused"]))).all():
                    run.status = "interrupted"
                    run.stop_reason = "startup_recovery"
                    run.completed_at = now
                    run.updated_at = now
                    run.revision += 1
                for run in session.scalars(select(EnduranceRun).where(EnduranceRun.status == "cancel_requested")).all():
                    run.status = "cancelled"
                    run.stop_reason = run.stop_reason or "cancel_requested"
                    run.completed_at = now
                    run.updated_at = now
                    run.revision += 1

    # ------------------------------------------------------------------
    # Readiness and suites
    # ------------------------------------------------------------------
    def readiness(self, project_id: str, chapter_count: int) -> dict[str, Any]:
        if chapter_count not in ALLOWED_COUNTS:
            raise StoryError(422, "ENDURANCE_CHAPTER_COUNT_INVALID", "chapterCount must be 5, 10, 20, or 30.")
        project = self.service.get_project(project_id)
        checks: list[dict[str, Any]] = []

        def add(code: str, status: str, title: str, detail: str, chapter_number: int | None = None) -> None:
            checks.append({"code": code, "status": status, "title": title, "detail": detail, "chapterNumber": chapter_number})

        with self.service.db.project(project.id, project.folder_path) as session:
            meta = session.get(ProjectMeta, project.id)
            start = (meta.current_chapter if meta else project.current_chapter) + 1
            total = meta.total_chapters if meta else project.total_chapters
            end = start + chapter_count - 1
            canon_locked = session.scalar(select(CanonDocument.id).where(CanonDocument.id == "story-core", CanonDocument.status == "locked")) is not None
            plan = session.scalar(select(Plan))
            beat_count = len(session.scalars(select(PlanNode.id).where(
                PlanNode.target_chapter >= start,
                PlanNode.target_chapter <= min(end, total),
            )).all())
            active_endurance = session.scalar(select(EnduranceRun.id).where(EnduranceRun.project_id == project.id, EnduranceRun.status.in_(ACTIVE_RUN_STATUSES)))
            active_automation = session.scalar(select(AutomationRun.id).where(AutomationRun.project_id == project.id, AutomationRun.status.in_(["queued", "running", "cancel_requested"])))

        add(
            "ENDURANCE_STANDARD_PROJECT_REQUIRED",
            "ready" if project.project_kind == "standard" else "blocked",
            "正式作品",
            "只有正式作品允许耐久运行。" if project.project_kind != "standard" else "正式作品可用于耐久验证。",
        )
        add(
            "ENDURANCE_RANGE_AVAILABLE",
            "ready" if end <= total else "blocked",
            "章节范围",
            f"计划检查第 {start}—{min(end, total)} 章。" if end <= total else "目标章节数超过作品总章数。",
            min(end, total),
        )
        add(
            "ENDURANCE_CANON_LOCKED",
            "ready" if canon_locked else "blocked",
            "Canon 锁定",
            "Canon 已锁定。" if canon_locked else "请先锁定正式 Canon。",
        )
        add(
            "ENDURANCE_PLAN_READY",
            "ready" if plan and beat_count >= min(chapter_count, max(0, total - start + 1)) else "warning",
            "章节节拍",
            "目标范围内存在章节节拍。" if plan and beat_count else "未找到完整章节节拍，漂移规则仍可运行但节奏判断会变弱。",
        )
        add(
            "ENDURANCE_ACTIVE_RUN_CLEAR",
            "ready" if not active_endurance else "blocked",
            "耐久运行互斥",
            "当前没有 active endurance run。" if not active_endurance else "同一作品已有 active endurance run。",
        )
        add(
            "ENDURANCE_AUTOMATION_CLEAR",
            "ready" if not active_automation else "blocked",
            "自动托管互斥",
            "当前没有 active automation run。" if not active_automation else "Phase 7 自动托管正在运行或等待。",
        )
        return {
            "projectId": project.id,
            "chapterCount": chapter_count,
            "startChapter": start,
            "endChapter": min(end, total),
            "ready": all(item["status"] != "blocked" for item in checks),
            "maxSafeChapterCount": max(0, min(chapter_count, total - start + 1)),
            "checks": checks,
            "updatedAt": _now(),
        }

    def create_suite(self, project_id: str, payload: EnduranceSuiteCreate) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        if payload.target_chapter_count not in ALLOWED_COUNTS:
            raise StoryError(422, "ENDURANCE_CHAPTER_COUNT_INVALID", "targetChapterCount must be 5, 10, 20, or 30.")
        with self.service.db.project_write(project.id, project.folder_path) as session:
            meta = session.get(ProjectMeta, project.id)
            start = payload.start_chapter or ((meta.current_chapter if meta else project.current_chapter) + 1)
            now = _now()
            suite = EnduranceSuite(
                id=str(uuid4()),
                project_id=project.id,
                name=payload.name,
                start_chapter=start,
                target_chapter_count=payload.target_chapter_count,
                daily_cost_limit=payload.daily_cost_limit,
                total_cost_limit=payload.total_cost_limit,
                consecutive_failure_limit=payload.consecutive_failure_limit,
                stop_severity=payload.stop_severity,
                enabled_rules_json=dumps(payload.enabled_rules or DEFAULT_RULES),
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(suite)
            session.flush()
            return self._suite_dict(suite)

    def list_suites(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._suite_dict(item) for item in session.scalars(
                select(EnduranceSuite).where(EnduranceSuite.project_id == project.id).order_by(EnduranceSuite.created_at.desc())
            ).all()]

    def update_suite(self, project_id: str, suite_id: str, payload: EnduranceSuiteUpdate) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            suite = self._get_suite(session, project.id, suite_id)
            if suite.revision != payload.expected_revision:
                raise StoryError(409, "ENDURANCE_SUITE_REVISION_CONFLICT", "Endurance suite revision conflict.", {"currentRevision": suite.revision})
            for key, value in payload.model_dump(exclude={"expected_revision"}, exclude_unset=True).items():
                if key == "enabled_rules":
                    suite.enabled_rules_json = dumps(value or DEFAULT_RULES)
                elif value is not None:
                    setattr(suite, key, value)
            suite.revision += 1
            suite.updated_at = _now()
            return self._suite_dict(suite)

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    def create_run(self, project_id: str, payload: EnduranceRunCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            suite = self._get_suite(session, project.id, payload.suite_id)
            if payload.idempotency_key:
                existing = session.scalar(select(EnduranceRun).where(
                    EnduranceRun.project_id == project.id,
                    EnduranceRun.idempotency_key == payload.idempotency_key,
                ))
                if existing:
                    return self._run_dict(session, existing, include_details=True)
            active = session.scalar(select(EnduranceRun.id).where(EnduranceRun.project_id == project.id, EnduranceRun.status.in_(ACTIVE_RUN_STATUSES)))
            if active:
                raise StoryError(409, "ENDURANCE_ACTIVE_RUN_EXISTS", "Only one active endurance run is allowed per project.", {"runId": active})
            target = payload.chapter_count or suite.target_chapter_count
            if target not in ALLOWED_COUNTS:
                raise StoryError(422, "ENDURANCE_CHAPTER_COUNT_INVALID", "chapterCount must be 5, 10, 20, or 30.")
            meta = session.get(ProjectMeta, project.id)
            start = suite.start_chapter or ((meta.current_chapter if meta else project.current_chapter) + 1)
            end = start + target - 1
            total = meta.total_chapters if meta else project.total_chapters
            if end > total:
                raise StoryError(422, "ENDURANCE_RANGE_OUT_OF_BOUNDS", "Endurance range exceeds project total chapters.", {"totalChapters": total})
            now = _now()
            run = EnduranceRun(
                id=str(uuid4()),
                project_id=project.id,
                suite_id=suite.id,
                status="queued",
                idempotency_key=payload.idempotency_key,
                start_chapter=start,
                end_chapter=end,
                target_chapter_count=target,
                completed_count=0,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(run)
            session.add(self.service._audit("endurance_run.queued", "endurance_run", run.id, {"requestId": request_id, "targetChapterCount": target}, request_id))
            session.flush()
            run_id = run.id
        self._dispatch_next_batch(project.id, run_id, request_id)
        self.evaluate_run(project.id, run_id, request_id)
        return self.get_run(project.id, run_id)

    def list_runs(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._run_dict(session, item, include_details=False) for item in session.scalars(
                select(EnduranceRun).where(EnduranceRun.project_id == project.id).order_by(EnduranceRun.created_at.desc())
            ).all()]

    def get_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return self._run_dict(session, self._get_run(session, project.id, run_id), include_details=True)

    def cancel_run(self, project_id: str, run_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        automation_run_id: str | None = None
        with self.service.db.project_write(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            if run.status in TERMINAL_RUN_STATUSES:
                return self._run_dict(session, run, include_details=True)
            automation_run_id = run.current_automation_run_id
            run.status = "cancelled" if run.status == "queued" else "cancel_requested"
            run.stop_reason = "cancel_requested"
            run.completed_at = _now() if run.status == "cancelled" else None
            run.updated_at = _now()
            run.revision += 1
            session.add(self.service._audit("endurance_run.cancel_requested", "endurance_run", run.id, {"requestId": request_id}, request_id))
        if automation_run_id:
            try:
                self.service.phase7.cancel_run(project.id, automation_run_id, request_id)
            except StoryError:
                pass
        with self.service.db.project_write(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            if run.status == "cancel_requested":
                run.status = "cancelled"
                run.completed_at = _now()
                run.updated_at = _now()
                run.revision += 1
            return self._run_dict(session, run, include_details=True)

    def resume_run(self, project_id: str, run_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            if run.status not in {"interrupted", "paused", "blocked", "failed"}:
                raise StoryError(409, "ENDURANCE_RUN_NOT_RESUMABLE", "Endurance run is not resumable in its current status.")
            self._validate_last_checkpoint(session, run)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            run.status = "running"
            run.stop_reason = None
            run.diagnostic_json = None
            run.started_at = run.started_at or _now()
            run.completed_at = None
            run.updated_at = _now()
            run.revision += 1
        self._dispatch_next_batch(project.id, run_id, request_id)
        self.evaluate_run(project.id, run_id, request_id)
        return self.get_run(project.id, run_id)

    def evaluate_run(self, project_id: str, run_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            suite = self._get_suite(session, project.id, run.suite_id)
            if run.status == "cancel_requested":
                run.status = "cancelled"
                run.stop_reason = "cancel_requested"
                run.completed_at = _now()
                run.updated_at = _now()
                run.revision += 1
                return self._run_dict(session, run, include_details=True)
            self._create_missing_checkpoints(session, project.id, run)
            self._evaluate_rules(session, project.id, run, suite)
            self._refresh_run_summary(session, run, suite)
            self._refresh_report(session, run)
            session.add(self.service._audit("endurance_run.evaluated", "endurance_run", run.id, {"requestId": request_id}, request_id))
            return self._run_dict(session, run, include_details=True)

    def list_findings(self, project_id: str, run_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            self._get_run(session, project.id, run_id)
            return [self._finding_dict(item) for item in session.scalars(
                select(EnduranceFinding).where(EnduranceFinding.run_id == run_id).order_by(EnduranceFinding.created_at.asc())
            ).all()]

    def get_report(self, project_id: str, run_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            self._get_run(session, project.id, run_id)
            report = session.scalar(select(EnduranceReport).where(EnduranceReport.run_id == run_id))
            if not report:
                raise StoryError(404, "ENDURANCE_REPORT_NOT_FOUND", "Endurance report not found.")
            return self._report_dict(report)

    def _dispatch_next_batch(self, project_id: str, run_id: str, request_id: str) -> None:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            if run.status in TERMINAL_RUN_STATUSES or run.status == "cancel_requested":
                return
            next_chapter = run.start_chapter + run.completed_count
            if next_chapter > run.end_chapter:
                return
            remaining = run.end_chapter - next_chapter + 1
            batch_count = min(5, remaining)
            run.status = "running"
            run.started_at = run.started_at or _now()
            run.updated_at = _now()
            run.revision += 1
        automation = self.service.phase7.create_manual_run(
            project.id,
            AutomationRunCreate(idempotency_key=f"endurance:{run_id}:{next_chapter}", chapter_count=batch_count if batch_count in {1, 3, 5} else 5),
            request_id,
        )
        with self.service.db.project_write(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            run.current_automation_run_id = automation["id"]
            items = automation.get("items") or []
            active_item = next((item for item in items if item.get("status") in {"waiting", "running"}), None)
            run.current_automation_run_item_id = active_item["id"] if active_item else None
            run.prompt_tokens += automation.get("promptTokens", 0)
            run.completion_tokens += automation.get("completionTokens", 0)
            run.total_tokens += automation.get("totalTokens", 0)
            run.estimated_cost += automation.get("estimatedCost", 0.0)
            run.updated_at = _now()
            run.revision += 1

    # ------------------------------------------------------------------
    # Checkpoints and rules
    # ------------------------------------------------------------------
    def _create_missing_checkpoints(self, session: Session, project_id: str, run: EnduranceRun) -> None:
        for chapter in range(run.start_chapter, run.end_chapter + 1):
            existing = session.scalar(select(EnduranceCheckpoint.id).where(
                EnduranceCheckpoint.run_id == run.id,
                EnduranceCheckpoint.chapter_number == chapter,
            ))
            if existing:
                continue
            commit = session.scalar(select(ChapterCommit).where(
                ChapterCommit.project_id == project_id,
                ChapterCommit.chapter_number == chapter,
                ChapterCommit.is_current.is_(True),
                ChapterCommit.status == "official",
            ))
            if not commit:
                continue
            source = session.get(SourceVersion, commit.source_version_id)
            snapshot = session.get(StateSnapshot, commit.state_snapshot_id) if commit.state_snapshot_id else None
            draft = session.get(ChapterDraft, commit.approved_draft_id)
            if not source or source.project_id != project_id or source.status != "official" or not snapshot or snapshot.project_id != project_id or not draft or draft.project_id != project_id or draft.status != "approved":
                continue
            plan = session.scalar(select(Plan))
            canon = session.get(CanonDocument, "story-core")
            payload = loads(source.payload_json) or {}
            cost = self._chapter_cost_summary(session, project_id, chapter)
            checkpoint_payload = {
                "runId": run.id,
                "chapterNumber": chapter,
                "chapterCommitId": commit.id,
                "sourceVersionId": source.id,
                "stateSnapshotId": snapshot.id,
                "commitRevision": commit.revision,
                "sourceRevision": source.revision,
                "snapshotRevision": snapshot.revision,
                "commitChecksum": commit.checksum,
                "sourceChecksum": source.checksum,
                "snapshotChecksum": snapshot.checksum,
                "canonRevision": canon.revision if canon else 0,
                "planRevision": plan.revision if plan else 0,
                "budgetSummary": self._budget_summary(session, chapter),
                "characterKnowledge": {"characters": payload.get("characters", []), "knowledge": payload.get("knowledge", [])},
                "abilitySummary": {"abilities": payload.get("abilities", [])},
                "itemSummary": {"items": payload.get("items", [])},
                "foreshadowSummary": {"foreshadows": payload.get("foreshadows", []), "resolutions": payload.get("foreshadowResolutions", [])},
                "costSummary": cost,
            }
            checkpoint = EnduranceCheckpoint(
                id=str(uuid4()),
                project_id=project_id,
                run_id=run.id,
                automation_run_id=run.current_automation_run_id,
                automation_run_item_id=run.current_automation_run_item_id,
                chapter_number=chapter,
                chapter_commit_id=commit.id,
                source_version_id=source.id,
                state_snapshot_id=snapshot.id,
                commit_revision=commit.revision,
                source_revision=source.revision,
                snapshot_revision=snapshot.revision,
                commit_checksum=commit.checksum,
                source_checksum=source.checksum,
                snapshot_checksum=snapshot.checksum,
                canon_revision=canon.revision if canon else 0,
                plan_revision=plan.revision if plan else 0,
                budget_summary_json=dumps(checkpoint_payload["budgetSummary"]),
                character_knowledge_json=dumps(checkpoint_payload["characterKnowledge"]),
                ability_summary_json=dumps(checkpoint_payload["abilitySummary"]),
                item_summary_json=dumps(checkpoint_payload["itemSummary"]),
                foreshadow_summary_json=dumps(checkpoint_payload["foreshadowSummary"]),
                cost_summary_json=dumps(cost),
                checkpoint_checksum=stable_digest(checkpoint_payload),
                validation_status="validated",
                created_at=_now(),
            )
            session.add(checkpoint)
            session.flush()
            run.last_checkpoint_id = checkpoint.id

    def _evaluate_rules(self, session: Session, project_id: str, run: EnduranceRun, suite: EnduranceSuite) -> None:
        enabled = set(loads(suite.enabled_rules_json) or DEFAULT_RULES)
        checkpoints = session.scalars(select(EnduranceCheckpoint).where(EnduranceCheckpoint.run_id == run.id).order_by(EnduranceCheckpoint.chapter_number)).all()
        checkpoint_by_chapter = {item.chapter_number: item for item in checkpoints}
        for chapter in range(run.start_chapter, run.end_chapter + 1):
            current_count = session.scalar(select(func.count()).select_from(ChapterCommit).where(
                ChapterCommit.project_id == project_id,
                ChapterCommit.chapter_number == chapter,
                ChapterCommit.is_current.is_(True),
                ChapterCommit.status == "official",
            )) or 0
            if "ENDURANCE_COMMIT_SEQUENCE_GAP" in enabled and current_count == 0:
                self._add_finding(session, project_id, run.id, None, "ENDURANCE_COMMIT_SEQUENCE_GAP", "blocker", chapter, {"chapter": chapter}, "恢复或重新运行该章，直到产生唯一 current official commit。")
            if "ENDURANCE_DUPLICATE_CURRENT_COMMIT" in enabled and current_count > 1:
                self._add_finding(session, project_id, run.id, None, "ENDURANCE_DUPLICATE_CURRENT_COMMIT", "blocker", chapter, {"currentCount": current_count}, "修复 current commit 唯一性后再继续耐久运行。")
        for checkpoint in checkpoints:
            commit = session.get(ChapterCommit, checkpoint.chapter_commit_id)
            source = session.get(SourceVersion, checkpoint.source_version_id)
            snapshot = session.get(StateSnapshot, checkpoint.state_snapshot_id)
            if "ENDURANCE_STATE_NON_ATOMIC" in enabled and (
                not commit or commit.project_id != project_id or not commit.is_current or commit.revision != checkpoint.commit_revision or commit.checksum != checkpoint.commit_checksum
                or not source or source.project_id != project_id or source.status != "official" or source.revision != checkpoint.source_revision or source.checksum != checkpoint.source_checksum
                or not snapshot or snapshot.project_id != project_id or snapshot.revision != checkpoint.snapshot_revision or snapshot.checksum != checkpoint.snapshot_checksum
            ):
                self._add_finding(session, project_id, run.id, checkpoint.id, "ENDURANCE_STATE_NON_ATOMIC", "blocker", checkpoint.chapter_number, {"checkpointId": checkpoint.id}, "停止运行并修复 commit/source/snapshot 引用或 checksum 漂移。")
            payload = loads(source.payload_json) if source else {}
            self._evaluate_pacing(session, project_id, run, checkpoint, payload, enabled)
            self._evaluate_characters(session, project_id, run, checkpoint, payload, enabled)
            self._evaluate_abilities(session, project_id, run, checkpoint, payload, enabled)
            self._evaluate_items(session, project_id, run, checkpoint, payload, checkpoint_by_chapter, enabled)
            self._evaluate_knowledge(session, project_id, run, checkpoint, payload, enabled)
            self._evaluate_foreshadows(session, project_id, run, checkpoint, payload, enabled)
            self._evaluate_revision_limit(session, project_id, run, checkpoint, enabled)
        if "ENDURANCE_COST_LIMIT" in enabled and suite.total_cost_limit is not None and run.estimated_cost > suite.total_cost_limit:
            self._add_finding(session, project_id, run.id, run.last_checkpoint_id, "ENDURANCE_COST_LIMIT", "blocker", None, {"estimatedCost": run.estimated_cost, "totalCostLimit": suite.total_cost_limit}, "提高预算或停止本次耐久运行。")
        if "ENDURANCE_RESTART_DUPLICATION" in enabled:
            rows = session.execute(select(AutomationRunItem.chapter_number, func.count()).where(
                AutomationRunItem.project_id == project_id,
                AutomationRunItem.status == "committed",
                AutomationRunItem.chapter_number >= run.start_chapter,
                AutomationRunItem.chapter_number <= run.end_chapter,
            ).group_by(AutomationRunItem.chapter_number)).all()
            for chapter, count in rows:
                if count > 1:
                    self._add_finding(session, project_id, run.id, checkpoint_by_chapter.get(chapter).id if checkpoint_by_chapter.get(chapter) else None, "ENDURANCE_RESTART_DUPLICATION", "error", chapter, {"automationCommittedItems": count}, "检查恢复逻辑，确认没有重复创建任务、扣费或 commit。")

    def _evaluate_pacing(self, session: Session, project_id: str, run: EnduranceRun, checkpoint: EnduranceCheckpoint, payload: dict[str, Any], enabled: set[str]) -> None:
        completed = set(_as_text_list(payload.get("completedMilestones"))) | set(_as_text_list(payload.get("milestones")))
        for node in session.scalars(select(PlanNode)).all():
            if node.title not in completed:
                continue
            if "ENDURANCE_PACING_EARLY" in enabled and checkpoint.chapter_number < node.range_min:
                self._add_finding(session, project_id, run.id, checkpoint.id, "ENDURANCE_PACING_EARLY", "error", checkpoint.chapter_number, {"planNodeId": node.id, "rangeMin": node.range_min, "title": node.title}, "不要在预算窗口前完成该里程碑。")
            if "ENDURANCE_PACING_LATE" in enabled and checkpoint.chapter_number > node.range_max:
                self._add_finding(session, project_id, run.id, checkpoint.id, "ENDURANCE_PACING_LATE", "warning", checkpoint.chapter_number, {"planNodeId": node.id, "rangeMax": node.range_max, "title": node.title}, "补齐逾期里程碑或调整规划预算。")

    def _evaluate_characters(self, session: Session, project_id: str, run: EnduranceRun, checkpoint: EnduranceCheckpoint, payload: dict[str, Any], enabled: set[str]) -> None:
        if "ENDURANCE_CHARACTER_EARLY" not in enabled:
            return
        seen = set(_as_text_list(payload.get("characters")))
        for entity in session.scalars(select(CanonEntity).where(CanonEntity.status == "locked")).all():
            attrs = loads(entity.attributes_json) or {}
            earliest = attrs.get("earliestChapter") or attrs.get("firstAllowedChapter")
            if earliest and checkpoint.chapter_number < int(earliest) and entity.canonical_name in seen:
                self._add_finding(session, project_id, run.id, checkpoint.id, "ENDURANCE_CHARACTER_EARLY", "error", checkpoint.chapter_number, {"entityId": entity.id, "name": entity.canonical_name, "earliestChapter": earliest}, "推迟人物出场或调整 Canon 中的允许窗口。")

    def _evaluate_abilities(self, session: Session, project_id: str, run: EnduranceRun, checkpoint: EnduranceCheckpoint, payload: dict[str, Any], enabled: set[str]) -> None:
        if "ENDURANCE_ABILITY_WINDOW" not in enabled:
            return
        abilities = set(_as_text_list(payload.get("abilities")))
        completed = set(_as_text_list(payload.get("completedMilestones")))
        for rule in session.scalars(select(CanonRule).where(CanonRule.status == "locked")).all():
            constraint = loads(rule.constraint_json) or {}
            name = constraint.get("name") or constraint.get("ability")
            earliest = constraint.get("earliestChapter")
            prerequisites = _as_text_list(constraint.get("prerequisites"))
            if not name or name not in abilities:
                continue
            if earliest and checkpoint.chapter_number < int(earliest):
                self._add_finding(session, project_id, run.id, checkpoint.id, "ENDURANCE_ABILITY_WINDOW", "error", checkpoint.chapter_number, {"ruleCode": rule.rule_code, "ability": name, "earliestChapter": earliest}, "能力升级早于窗口。")
            missing = [item for item in prerequisites if item not in completed]
            if missing:
                self._add_finding(session, project_id, run.id, checkpoint.id, "ENDURANCE_ABILITY_WINDOW", "error", checkpoint.chapter_number, {"ruleCode": rule.rule_code, "ability": name, "missingPrerequisites": missing}, "补足前置条件后再升级能力。")

    def _evaluate_items(self, session: Session, project_id: str, run: EnduranceRun, checkpoint: EnduranceCheckpoint, payload: dict[str, Any], checkpoint_by_chapter: dict[int, EnduranceCheckpoint], enabled: set[str]) -> None:
        if "ENDURANCE_ITEM_STATE_DRIFT" not in enabled:
            return
        current_items = _as_item_map(payload.get("items"))
        previous = None
        for chapter in sorted(ch for ch in checkpoint_by_chapter if ch < checkpoint.chapter_number):
            previous = checkpoint_by_chapter[chapter]
        if not previous:
            return
        previous_items = _as_item_map((loads(previous.item_summary_json) or {}).get("items"))
        for name, item in current_items.items():
            before = previous_items.get(name)
            if not before:
                continue
            evidence: dict[str, Any] = {"item": name}
            drift = False
            if before.get("holder") and item.get("holder") and before.get("holder") != item.get("holder") and not item.get("transfer"):
                evidence.update({"previousHolder": before.get("holder"), "holder": item.get("holder")})
                drift = True
            if _to_int(item.get("charges")) is not None and _to_int(before.get("charges")) is not None and _to_int(item.get("charges")) > _to_int(before.get("charges")):
                evidence.update({"previousCharges": before.get("charges"), "charges": item.get("charges")})
                drift = True
            if before.get("damaged") is True and item.get("damaged") is False and not item.get("repaired"):
                evidence.update({"damageRegressed": True})
                drift = True
            if drift:
                self._add_finding(session, project_id, run.id, checkpoint.id, "ENDURANCE_ITEM_STATE_DRIFT", "warning", checkpoint.chapter_number, evidence, "检查法器持有人、次数、代价或损坏状态是否连续。")

    def _evaluate_knowledge(self, session: Session, project_id: str, run: EnduranceRun, checkpoint: EnduranceCheckpoint, payload: dict[str, Any], enabled: set[str]) -> None:
        if "ENDURANCE_KNOWLEDGE_LEAK" not in enabled:
            return
        known = _as_knowledge_set(payload.get("knowledge"))
        for boundary in session.scalars(select(KnowledgeBoundary).where(KnowledgeBoundary.status == "active")).all():
            data = loads(boundary.knowledge_json) or {}
            character = data.get("character")
            fact = data.get("fact") or data.get("knowledge")
            allowed = data.get("allowedChapter") or data.get("earliestChapter")
            if character and fact and allowed and (character, fact) in known and checkpoint.chapter_number < int(allowed):
                self._add_finding(session, project_id, run.id, checkpoint.id, "ENDURANCE_KNOWLEDGE_LEAK", "blocker", checkpoint.chapter_number, {"character": character, "fact": fact, "allowedChapter": allowed}, "人物知道了不应知道的信息，需回滚或重写该章候选。")

    def _evaluate_foreshadows(self, session: Session, project_id: str, run: EnduranceRun, checkpoint: EnduranceCheckpoint, payload: dict[str, Any], enabled: set[str]) -> None:
        if "ENDURANCE_FORESHADOW_MISSED" not in enabled:
            return
        resolutions = set(_as_text_list(payload.get("foreshadowResolutions")))
        for item in session.scalars(select(Foreshadow).where(Foreshadow.project_id == project_id)).all():
            if item.latest_chapter and checkpoint.chapter_number > item.latest_chapter and item.status == "pending":
                self._add_finding(session, project_id, run.id, checkpoint.id, "ENDURANCE_FORESHADOW_MISSED", "warning", checkpoint.chapter_number, {"foreshadowId": item.id, "code": item.code, "latestChapter": item.latest_chapter}, "伏笔已过期仍未回收。")
            if item.code in resolutions and item.earliest_chapter and checkpoint.chapter_number < item.earliest_chapter:
                self._add_finding(session, project_id, run.id, checkpoint.id, "ENDURANCE_FORESHADOW_MISSED", "error", checkpoint.chapter_number, {"foreshadowId": item.id, "code": item.code, "earliestChapter": item.earliest_chapter}, "伏笔早于允许窗口被回收。")

    def _evaluate_revision_limit(self, session: Session, project_id: str, run: EnduranceRun, checkpoint: EnduranceCheckpoint, enabled: set[str]) -> None:
        if "ENDURANCE_REVISION_LIMIT_BREACH" not in enabled:
            return
        commit = session.get(ChapterCommit, checkpoint.chapter_commit_id)
        draft = session.get(ChapterDraft, commit.approved_draft_id) if commit else None
        job = session.get(ChapterJob, draft.chapter_job_id) if draft else None
        if job and job.current_revision_round > 2:
            self._add_finding(session, project_id, run.id, checkpoint.id, "ENDURANCE_REVISION_LIMIT_BREACH", "error", checkpoint.chapter_number, {"chapterJobId": job.id, "revisionRound": job.current_revision_round}, "单章修订超过两轮，需审计 Phase 5 上限。")

    def _refresh_run_summary(self, session: Session, run: EnduranceRun, suite: EnduranceSuite) -> None:
        checkpoints = session.scalars(select(EnduranceCheckpoint).where(EnduranceCheckpoint.run_id == run.id)).all()
        findings = session.scalars(select(EnduranceFinding).where(EnduranceFinding.run_id == run.id, EnduranceFinding.status == "open")).all()
        run.completed_count = len(checkpoints)
        costs = [loads(item.cost_summary_json) or {} for item in checkpoints]
        run.prompt_tokens = sum(int(item.get("promptTokens", 0)) for item in costs)
        run.completion_tokens = sum(int(item.get("completionTokens", 0)) for item in costs)
        run.total_tokens = sum(int(item.get("totalTokens", 0)) for item in costs)
        run.estimated_cost = sum(float(item.get("estimatedCost", 0.0)) for item in costs)
        stopping = [item for item in findings if _severity_at_least(item.severity, suite.stop_severity)]
        if stopping:
            run.status = "blocked"
            run.stop_reason = stopping[0].rule_code
            run.completed_at = _now()
        elif run.completed_count >= run.target_chapter_count:
            run.status = "completed"
            run.stop_reason = None
            run.completed_at = _now()
        elif run.status not in {"cancel_requested", "cancelled", "interrupted", "failed"}:
            run.status = "running"
        run.updated_at = _now()
        run.revision += 1

    def _refresh_report(self, session: Session, run: EnduranceRun) -> EnduranceReport:
        checkpoints = session.scalars(select(EnduranceCheckpoint).where(EnduranceCheckpoint.run_id == run.id)).all()
        findings = session.scalars(select(EnduranceFinding).where(EnduranceFinding.run_id == run.id)).all()
        jobs = session.scalars(select(ChapterJob).where(ChapterJob.project_id == run.project_id)).all()
        report = session.scalar(select(EnduranceReport).where(EnduranceReport.run_id == run.id))
        if not report:
            report = EnduranceReport(id=str(uuid4()), project_id=run.project_id, run_id=run.id, generated_at=_now(), updated_at=_now())
            session.add(report)
        report.success_count = len(checkpoints)
        report.isolated_count = len([item for item in findings if item.severity == "blocker"])
        report.failed_count = len([item for item in findings if item.severity == "error"])
        report.prompt_tokens = run.prompt_tokens
        report.completion_tokens = run.completion_tokens
        report.total_tokens = run.total_tokens
        report.estimated_cost = run.estimated_cost
        relevant_jobs = [job for job in jobs if run.start_chapter <= self._job_chapter_number(session, job) <= run.end_chapter]
        report.average_revision_rounds = (sum(job.current_revision_round for job in relevant_jobs) / len(relevant_jobs)) if relevant_jobs else 0.0
        quality = {"openFindings": len(findings), "bySeverity": _count_by(findings, "severity")}
        drift = {"byRule": _count_by(findings, "rule_code"), "checkpointCount": len(checkpoints)}
        report.quality_trend_json = dumps(quality)
        report.drift_trend_json = dumps(drift)
        report.stop_reason = run.stop_reason
        report.checksum = stable_digest({
            "runId": run.id,
            "status": run.status,
            "successCount": report.success_count,
            "findings": drift,
            "cost": run.estimated_cost,
        })
        report.updated_at = _now()
        return report

    def _validate_last_checkpoint(self, session: Session, run: EnduranceRun) -> None:
        if not run.last_checkpoint_id:
            return
        checkpoint = session.get(EnduranceCheckpoint, run.last_checkpoint_id)
        if not checkpoint:
            raise StoryError(409, "ENDURANCE_CHECKPOINT_MISSING", "Last checkpoint is missing.")
        commit = session.get(ChapterCommit, checkpoint.chapter_commit_id)
        source = session.get(SourceVersion, checkpoint.source_version_id)
        snapshot = session.get(StateSnapshot, checkpoint.state_snapshot_id)
        drift = (
            not commit or not commit.is_current or commit.revision != checkpoint.commit_revision or commit.checksum != checkpoint.commit_checksum
            or not source or source.status != "official" or source.revision != checkpoint.source_revision or source.checksum != checkpoint.source_checksum
            or not snapshot or snapshot.revision != checkpoint.snapshot_revision or snapshot.checksum != checkpoint.snapshot_checksum
        )
        if drift:
            raise StoryError(409, "ENDURANCE_CHECKPOINT_DRIFT", "Current official state has drifted from the last endurance checkpoint.", {"checkpointId": checkpoint.id})

    def _add_finding(self, session: Session, project_id: str, run_id: str, checkpoint_id: str | None, rule_code: str, severity: str, chapter: int | None, evidence: dict[str, Any], suggestion: str) -> None:
        fingerprint = stable_digest({"rule": rule_code, "chapter": chapter, "evidence": evidence})
        existing = session.scalar(select(EnduranceFinding).where(EnduranceFinding.run_id == run_id, EnduranceFinding.fingerprint == fingerprint))
        if existing:
            existing.status = "open"
            existing.updated_at = _now()
            return
        session.add(EnduranceFinding(
            id=str(uuid4()),
            project_id=project_id,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            rule_code=rule_code,
            severity=severity,
            chapter_number=chapter,
            evidence_json=dumps(evidence),
            suggestion=suggestion,
            status="open",
            fingerprint=fingerprint,
            revision=1,
            created_at=_now(),
            updated_at=_now(),
        ))

    # ------------------------------------------------------------------
    # Helpers and serialization
    # ------------------------------------------------------------------
    def _get_suite(self, session: Session, project_id: str, suite_id: str) -> EnduranceSuite:
        suite = session.get(EnduranceSuite, suite_id)
        if not suite or suite.project_id != project_id:
            raise StoryError(404, "ENDURANCE_SUITE_NOT_FOUND", "Endurance suite not found.")
        return suite

    def _get_run(self, session: Session, project_id: str, run_id: str) -> EnduranceRun:
        run = session.get(EnduranceRun, run_id)
        if not run or run.project_id != project_id:
            raise StoryError(404, "ENDURANCE_RUN_NOT_FOUND", "Endurance run not found.")
        return run

    @staticmethod
    def _suite_dict(item: EnduranceSuite) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "name": item.name,
            "startChapter": item.start_chapter,
            "targetChapterCount": item.target_chapter_count,
            "dailyCostLimit": item.daily_cost_limit,
            "totalCostLimit": item.total_cost_limit,
            "consecutiveFailureLimit": item.consecutive_failure_limit,
            "stopSeverity": item.stop_severity,
            "enabledRules": loads(item.enabled_rules_json) or [],
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }

    def _run_dict(self, session: Session, item: EnduranceRun, *, include_details: bool) -> dict[str, Any]:
        result = {
            "id": item.id,
            "projectId": item.project_id,
            "suiteId": item.suite_id,
            "status": item.status,
            "idempotencyKey": item.idempotency_key,
            "startChapter": item.start_chapter,
            "endChapter": item.end_chapter,
            "targetChapterCount": item.target_chapter_count,
            "completedCount": item.completed_count,
            "currentAutomationRunId": item.current_automation_run_id,
            "currentAutomationRunItemId": item.current_automation_run_item_id,
            "lastCheckpointId": item.last_checkpoint_id,
            "promptTokens": item.prompt_tokens,
            "completionTokens": item.completion_tokens,
            "totalTokens": item.total_tokens,
            "estimatedCost": item.estimated_cost,
            "stopReason": item.stop_reason,
            "diagnostic": loads(item.diagnostic_json) if item.diagnostic_json else None,
            "revision": item.revision,
            "createdAt": item.created_at,
            "startedAt": item.started_at,
            "completedAt": item.completed_at,
            "updatedAt": item.updated_at,
            "checkpoints": [],
            "findings": [],
            "report": None,
            "availableActions": self._available_actions(item),
        }
        if include_details:
            result["checkpoints"] = [self._checkpoint_dict(row) for row in session.scalars(
                select(EnduranceCheckpoint).where(EnduranceCheckpoint.run_id == item.id).order_by(EnduranceCheckpoint.chapter_number)
            ).all()]
            result["findings"] = [self._finding_dict(row) for row in session.scalars(
                select(EnduranceFinding).where(EnduranceFinding.run_id == item.id).order_by(EnduranceFinding.created_at)
            ).all()]
            report = session.scalar(select(EnduranceReport).where(EnduranceReport.run_id == item.id))
            result["report"] = self._report_dict(report) if report else None
        return result

    @staticmethod
    def _checkpoint_dict(item: EnduranceCheckpoint) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "runId": item.run_id,
            "automationRunId": item.automation_run_id,
            "automationRunItemId": item.automation_run_item_id,
            "chapterNumber": item.chapter_number,
            "chapterCommitId": item.chapter_commit_id,
            "sourceVersionId": item.source_version_id,
            "stateSnapshotId": item.state_snapshot_id,
            "commitRevision": item.commit_revision,
            "sourceRevision": item.source_revision,
            "snapshotRevision": item.snapshot_revision,
            "commitChecksum": item.commit_checksum,
            "sourceChecksum": item.source_checksum,
            "snapshotChecksum": item.snapshot_checksum,
            "canonRevision": item.canon_revision,
            "planRevision": item.plan_revision,
            "budgetSummary": loads(item.budget_summary_json) or {},
            "characterKnowledge": loads(item.character_knowledge_json) or {},
            "abilitySummary": loads(item.ability_summary_json) or {},
            "itemSummary": loads(item.item_summary_json) or {},
            "foreshadowSummary": loads(item.foreshadow_summary_json) or {},
            "costSummary": loads(item.cost_summary_json) or {},
            "checkpointChecksum": item.checkpoint_checksum,
            "validationStatus": item.validation_status,
            "createdAt": item.created_at,
        }

    @staticmethod
    def _finding_dict(item: EnduranceFinding) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "runId": item.run_id,
            "checkpointId": item.checkpoint_id,
            "ruleCode": item.rule_code,
            "severity": item.severity,
            "chapterNumber": item.chapter_number,
            "evidence": loads(item.evidence_json) or {},
            "suggestion": item.suggestion,
            "status": item.status,
            "fingerprint": item.fingerprint,
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }

    @staticmethod
    def _report_dict(item: EnduranceReport) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "runId": item.run_id,
            "successCount": item.success_count,
            "isolatedCount": item.isolated_count,
            "failedCount": item.failed_count,
            "promptTokens": item.prompt_tokens,
            "completionTokens": item.completion_tokens,
            "totalTokens": item.total_tokens,
            "estimatedCost": item.estimated_cost,
            "averageRevisionRounds": item.average_revision_rounds,
            "qualityTrend": loads(item.quality_trend_json) or {},
            "driftTrend": loads(item.drift_trend_json) or {},
            "stopReason": item.stop_reason,
            "checksum": item.checksum,
            "generatedAt": item.generated_at,
            "updatedAt": item.updated_at,
        }

    @staticmethod
    def _available_actions(item: EnduranceRun) -> list[str]:
        actions: list[str] = ["evaluate"]
        if item.status in {"running", "queued", "paused"}:
            actions.append("cancel")
        if item.status in {"interrupted", "paused", "blocked", "failed"}:
            actions.append("resume")
        return actions

    def _budget_summary(self, session: Session, chapter: int) -> dict[str, Any]:
        nodes = session.scalars(select(PlanNode).where(PlanNode.range_min <= chapter, PlanNode.range_max >= chapter)).all()
        return {"chapter": chapter, "nodes": [{"id": item.id, "title": item.title, "rangeMin": item.range_min, "targetChapter": item.target_chapter, "rangeMax": item.range_max} for item in nodes]}

    def _chapter_cost_summary(self, session: Session, project_id: str, chapter: int) -> dict[str, Any]:
        rows = session.scalars(select(AutomationRunItem).where(AutomationRunItem.project_id == project_id, AutomationRunItem.chapter_number == chapter)).all()
        return {
            "promptTokens": sum(item.prompt_tokens for item in rows),
            "completionTokens": sum(item.completion_tokens for item in rows),
            "totalTokens": sum(item.total_tokens for item in rows),
            "estimatedCost": sum(item.estimated_cost for item in rows),
        }

    def _job_chapter_number(self, session: Session, job: ChapterJob) -> int:
        from .models import ChapterContract

        contract = session.get(ChapterContract, job.chapter_contract_id)
        return contract.chapter_number if contract else 0


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                label = item.get("name") or item.get("code") or item.get("label") or item.get("title")
                if label:
                    result.append(str(label))
        return result
    return []


def _as_item_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if isinstance(item, str):
            result[item] = {"name": item}
        elif isinstance(item, dict):
            name = item.get("name") or item.get("label") or item.get("code")
            if name:
                result[str(name)] = item
    return result


def _as_knowledge_set(value: Any) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    if not isinstance(value, list):
        return result
    for item in value:
        if isinstance(item, dict):
            character = item.get("character") or item.get("name")
            fact = item.get("fact") or item.get("knowledge")
            if character and fact:
                result.add((str(character), str(fact)))
    return result


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _count_by(items: list[Any], attr: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        value = getattr(item, attr)
        result[value] = result.get(value, 0) + 1
    return result

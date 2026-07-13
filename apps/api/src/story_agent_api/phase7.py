from __future__ import annotations

import asyncio
import threading
from datetime import datetime, time, timedelta, timezone, tzinfo
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import (
    AutomationLease,
    AutomationPolicy,
    AutomationRun,
    AutomationRunItem,
    ChapterCommit,
    ChapterContract,
    ChapterJob,
    ModelConfig,
    ModelRoleBinding,
    ModelRun,
    ProjectMeta,
    utc_now,
)
from .schemas import (
    AutomationPolicyUpdate,
    AutomationRunCreate,
    ChapterApproveRequest,
    ChapterCommitRequest,
    ChapterContractDerive,
    ChapterContractLock,
    ChapterJobCreate,
    ChapterJobRetry,
    ChapterJobRun,
    ChapterRevisionRequest,
)
from .services import StoryError, dumps, loads


RUNNING_STATUSES = {"queued", "running", "cancel_requested"}
TERMINAL_STATUSES = {"completed", "partial", "blocked", "failed", "cancelled", "missed", "interrupted"}
MODEL_ROLES_FOR_AUTOMATION = {
    "chinese_writer",
    "fact_extractor",
    "continuity_reviewer",
    "story_editor",
    "style_reviewer",
    "reviser",
}
LEASE_SECONDS = 300
MIN_MODEL_CALL_COST = 0.000001
COMMON_TIMEZONE_FALLBACKS = {
    "Asia/Shanghai": timezone(timedelta(hours=8)),
    "Asia/Chongqing": timezone(timedelta(hours=8)),
    "Asia/Hong_Kong": timezone(timedelta(hours=8)),
    "Asia/Taipei": timezone(timedelta(hours=8)),
    "America/New_York": timezone(timedelta(hours=-5)),
    "America/Chicago": timezone(timedelta(hours=-6)),
    "America/Denver": timezone(timedelta(hours=-7)),
    "America/Los_Angeles": timezone(timedelta(hours=-8)),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _zone(name: str) -> tzinfo:
    if name.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name in COMMON_TIMEZONE_FALLBACKS:
            return COMMON_TIMEZONE_FALLBACKS[name]
        raise


class Phase7Service:
    def __init__(self, service: Any):
        self.service = service
        self._loop_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._running_threads: set[str] = set()

    # ------------------------------------------------------------------
    # Lifecycle and scheduler
    # ------------------------------------------------------------------
    def recover_interrupted_automation(self) -> None:
        now = _now()
        for project in self.service.list_projects():
            with self.service.db.project_write(project.id, project.folder_path) as session:
                for run in session.scalars(select(AutomationRun).where(AutomationRun.status.in_(["queued", "running", "cancel_requested"]))).all():
                    run.status = "interrupted" if run.status != "cancel_requested" else "cancelled"
                    run.stop_reason = "startup_recovery"
                    run.completed_at = now
                    run.updated_at = now
                    run.revision += 1
                    for item in session.scalars(select(AutomationRunItem).where(
                        AutomationRunItem.automation_run_id == run.id,
                        AutomationRunItem.status.in_(["waiting", "running"]),
                    )).all():
                        item.status = "interrupted" if run.status == "interrupted" else "cancelled"
                        item.error_code = "startup_recovery"
                        item.completed_at = now
                        item.updated_at = now
                session.query(AutomationLease).delete()
        self.check_due_policies(execute_due=False)

    def start_scheduler(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._loop_task is not None:
            return
        self._stop_event = asyncio.Event()
        self._loop_task = asyncio.create_task(self._scheduler_loop())

    async def stop_scheduler(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._loop_task is not None:
            await self._loop_task
        self._loop_task = None
        self._stop_event = None

    async def _scheduler_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            self.check_due_policies(execute_due=True)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=30)
            except TimeoutError:
                continue

    def check_due_policies(self, *, execute_due: bool) -> list[str]:
        created: list[str] = []
        now = _now()
        for project in self.service.list_projects():
            project_created: list[str] = []
            with self.service.db.project_write(project.id, project.folder_path) as session:
                policy = session.get(AutomationPolicy, project.id)
                if not policy or not policy.enabled:
                    continue
                self._ensure_next_run(policy, now)
                if policy.next_run_at and _as_utc(policy.next_run_at) and _as_utc(policy.next_run_at) <= now:
                    scheduled_date = self._local_date_for(policy, _as_utc(policy.next_run_at) or now)
                    if execute_due:
                        run = self._create_run_row(session, policy, "scheduled", scheduled_date, None, now)
                        project_created.append(run.id)
                    else:
                        run = self._create_run_row(session, policy, "scheduled", scheduled_date, None, now, status="missed")
                        project_created.append(run.id)
                    policy.last_scheduled_local_date = scheduled_date
                    policy.next_run_at = self._next_run_after(policy, now + timedelta(seconds=1))
                    policy.revision += 1
                    policy.updated_at = now
            created.extend(project_created)
            for run_id in project_created:
                if execute_due:
                    self.dispatch_run(project.id, run_id)
        return created

    # ------------------------------------------------------------------
    # Policy and run APIs
    # ------------------------------------------------------------------
    def get_policy(self, project_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            policy = self._get_or_create_policy(session, project.id)
            return self._policy_dict(policy)

    def update_policy(self, project_id: str, payload: AutomationPolicyUpdate) -> dict[str, Any]:
        if payload.target_words_min > payload.target_words_max:
            raise StoryError(422, "AUTOMATION_INVALID_WORD_TARGET", "targetWordsMin must not exceed targetWordsMax.")
        try:
            _zone(payload.timezone)
        except ZoneInfoNotFoundError as exc:
            raise StoryError(422, "AUTOMATION_INVALID_TIMEZONE", "Timezone must be a valid IANA timezone.", {"timezone": payload.timezone}) from exc
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            policy = self._get_or_create_policy(session, project.id)
            if policy.revision != payload.expected_revision:
                raise StoryError(409, "AUTOMATION_POLICY_REVISION_CONFLICT", "Automation policy revision conflict.", {"currentRevision": policy.revision})
            for key, value in payload.model_dump(exclude={"expected_revision"}).items():
                setattr(policy, key, value)
            policy.next_run_at = self._next_run_after(policy, _now()) if policy.enabled else None
            policy.revision += 1
            policy.updated_at = _now()
            session.add(self.service._audit("automation_policy.updated", "automation_policy", project.id, {"enabled": policy.enabled}, str(uuid4())))
            return self._policy_dict(policy)

    def create_manual_run(self, project_id: str, payload: AutomationRunCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        today = self._today_for_project(project.id, project.folder_path)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            policy = self._get_or_create_policy(session, project.id)
            if policy.daily_cost_limit is not None:
                self.assert_required_prices(project.id)
            if payload.idempotency_key:
                existing = session.scalar(select(AutomationRun).where(
                    AutomationRun.project_id == project.id,
                    AutomationRun.idempotency_key == payload.idempotency_key,
                ))
                if existing:
                    return self.get_run(project.id, existing.id)
            run = self._create_run_row(session, policy, "manual", today, payload.idempotency_key, _now())
            session.add(self.service._audit("automation_run.queued", "automation_run", run.id, {"trigger": "manual", "requestId": request_id}, request_id))
            run_id = run.id
        self.dispatch_run(project.id, run_id)
        return self.get_run(project.id, run_id)

    def list_runs(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            rows = session.scalars(select(AutomationRun).where(AutomationRun.project_id == project.id).order_by(AutomationRun.created_at.desc())).all()
            return [self._run_dict(session, row, include_items=False) for row in rows]

    def get_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            return self._run_dict(session, run, include_items=True)

    def cancel_run(self, project_id: str, run_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        active_job_id: str | None = None
        with self.service.db.project_write(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            if run.status in TERMINAL_STATUSES:
                return self._run_dict(session, run, include_items=True)
            run.status = "cancel_requested"
            run.stop_reason = "cancel_requested"
            run.revision += 1
            run.updated_at = _now()
            active = session.scalar(select(AutomationRunItem).where(
                AutomationRunItem.automation_run_id == run.id,
                AutomationRunItem.status == "running",
            ))
            active_job_id = active.chapter_job_id if active else None
            session.add(self.service._audit("automation_run.cancel_requested", "automation_run", run.id, {"requestId": request_id}, request_id))
        if active_job_id:
            try:
                self.service.phase5.cancel_chapter_job(project.id, active_job_id, request_id)
            except StoryError:
                pass
        return self.get_run(project.id, run_id)

    def resume_run(self, project_id: str, run_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            if run.status not in {"interrupted", "partial", "failed", "blocked", "cancelled"}:
                raise StoryError(409, "AUTOMATION_RUN_NOT_RESUMABLE", "Automation run cannot be resumed from its current status.")
            for item in session.scalars(select(AutomationRunItem).where(
                AutomationRunItem.automation_run_id == run.id,
                AutomationRunItem.status.in_(["interrupted", "failed", "cancelled", "isolated"]),
            )).all():
                item.status = "waiting"
                item.error_code = None
                item.diagnostic_json = None
                item.updated_at = _now()
            run.status = "queued"
            run.stop_reason = None
            run.completed_at = None
            run.revision += 1
            run.updated_at = _now()
            session.add(self.service._audit("automation_run.resumed", "automation_run", run.id, {"requestId": request_id}, request_id))
        self.dispatch_run(project.id, run_id)
        return self.get_run(project.id, run_id)

    def catch_up_run(self, project_id: str, run_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            missed = self._get_run(session, project.id, run_id)
            if missed.status != "missed":
                raise StoryError(409, "AUTOMATION_RUN_NOT_MISSED", "Only missed automation runs can be caught up.")
            policy = self._get_or_create_policy(session, project.id)
            if policy.daily_cost_limit is not None:
                self.assert_required_prices(project.id)
            catch_up = self._create_run_row(session, policy, "catch_up", missed.scheduled_local_date, None, _now())
            missed.status = "completed"
            missed.stop_reason = "catch_up_created"
            missed.completed_at = _now()
            missed.updated_at = _now()
            missed.revision += 1
            session.add(self.service._audit("automation_run.catch_up_queued", "automation_run", catch_up.id, {"missedRunId": missed.id, "requestId": request_id}, request_id))
            catch_up_id = catch_up.id
        self.dispatch_run(project.id, catch_up_id)
        return self.get_run(project.id, catch_up_id)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def dispatch_run(self, project_id: str, run_id: str) -> None:
        key = f"{project_id}:{run_id}"
        if key in self._running_threads:
            return

        def worker() -> None:
            self._running_threads.add(key)
            try:
                self.execute_run(project_id, run_id)
            finally:
                self._running_threads.discard(key)

        threading.Thread(target=worker, name=f"story-agent-automation-{run_id[:8]}", daemon=True).start()

    def execute_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        owner_id = f"automation:{run_id}"
        if not self._acquire_lease(project.id, project.folder_path, owner_id):
            self._mark_run_terminal(project.id, project.folder_path, run_id, "blocked", "AUTOMATION_LEASE_BUSY", {"ownerId": owner_id})
            return self.get_run(project.id, run_id)
        try:
            self._prepare_run(project.id, project.folder_path, run_id)
            if self._run_has_daily_limit(project.id, project.folder_path, run_id):
                self.assert_required_prices(project.id)
            while True:
                self._heartbeat(project.id, project.folder_path, owner_id)
                item = self._next_waiting_item(project.id, project.folder_path, run_id)
                if item is None:
                    self._finish_run_from_items(project.id, project.folder_path, run_id)
                    break
                if self._run_cancel_requested(project.id, project.folder_path, run_id):
                    self._cancel_waiting_items(project.id, project.folder_path, run_id)
                    self._mark_run_terminal(project.id, project.folder_path, run_id, "cancelled", "cancel_requested", {})
                    break
                if not self._budget_allows_next_chapter(project.id, project.folder_path, run_id):
                    self._mark_item_terminal(project.id, project.folder_path, item.id, "skipped", "AUTOMATION_COST_LIMIT_REACHED", {})
                    self._cancel_waiting_items(project.id, project.folder_path, run_id, status="skipped", code="AUTOMATION_COST_LIMIT_REACHED")
                    self._mark_run_terminal(project.id, project.folder_path, run_id, "blocked", "AUTOMATION_COST_LIMIT_REACHED", {})
                    break
                try:
                    self._execute_item(project, run_id, item.id)
                except StoryError as exc:
                    self._mark_item_terminal(project.id, project.folder_path, item.id, "isolated", exc.code, {"message": exc.message, "details": exc.details})
                    self._cancel_waiting_items(project.id, project.folder_path, run_id, status="skipped", code=exc.code)
                    self._mark_run_terminal(project.id, project.folder_path, run_id, "blocked", exc.code, {"message": exc.message, "details": exc.details})
                    break
                except Exception as exc:
                    self._mark_item_terminal(project.id, project.folder_path, item.id, "failed", "AUTOMATION_ITEM_FAILED", {"errorType": type(exc).__name__})
                    self._cancel_waiting_items(project.id, project.folder_path, run_id, status="skipped", code="AUTOMATION_ITEM_FAILED")
                    self._mark_run_terminal(project.id, project.folder_path, run_id, "failed", "AUTOMATION_ITEM_FAILED", {"errorType": type(exc).__name__})
                    break
            return self.get_run(project.id, run_id)
        finally:
            self._release_lease(project.id, project.folder_path, owner_id)

    def _execute_item(self, project: Any, run_id: str, item_id: str) -> None:
        with self.service.db.project_write(project.id, project.folder_path) as session:
            item = session.get(AutomationRunItem, item_id)
            if not item:
                raise StoryError(404, "AUTOMATION_RUN_ITEM_NOT_FOUND", "Automation run item not found.")
            item.status = "running"
            item.started_at = item.started_at or _now()
            item.updated_at = _now()
            chapter_number = item.chapter_number
        before_run_ids = self._model_run_ids(project.id, project.folder_path)
        existing_commit = self._current_commit(project.id, project.folder_path, chapter_number)
        if existing_commit:
            self._mark_item_committed(project.id, project.folder_path, item_id, existing_commit["id"], None, None)
            self._update_run_costs(project.id, project.folder_path, run_id, before_run_ids)
            return
        contract = self._ensure_locked_contract(project, chapter_number, run_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            item = session.get(AutomationRunItem, item_id)
            if item:
                item.chapter_contract_id = contract["id"]
                item.updated_at = _now()
        job = self._ensure_job(project, contract["id"], run_id, chapter_number)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            item = session.get(AutomationRunItem, item_id)
            if item:
                item.chapter_job_id = job["id"]
                item.updated_at = _now()
        job_state = self._advance_job_to_review(project.id, job["id"])
        job_state = self._auto_revise_until_clear(project.id, job_state)
        approved = self.service.phase5.approve_chapter_job(project.id, job_state["id"], ChapterApproveRequest(mode="guarded_auto", expected_job_revision=job_state["revision"]), str(uuid4()))
        commit = self.service.phase5.commit_chapter_job(project.id, approved["id"], ChapterCommitRequest(expected_job_revision=approved["revision"]), str(uuid4()))
        self._mark_item_committed(project.id, project.folder_path, item_id, commit["id"], contract["id"], job["id"])
        self._update_run_costs(project.id, project.folder_path, run_id, before_run_ids)

    def _advance_job_to_review(self, project_id: str, job_id: str) -> dict[str, Any]:
        job = self.service.phase5.get_chapter_job(project_id, job_id)
        if job["status"] in {"queued", "failed", "interrupted", "cancelled"}:
            if job["status"] != "queued":
                job = self.service.phase5.retry_chapter_job(project_id, job_id, ChapterJobRetry(reason="automation resume"), str(uuid4()))
            job = self.service.phase5.run_chapter_job(project_id, job_id, ChapterJobRun(), str(uuid4()))
        if job["status"] not in {"human_review", "approved", "completed"}:
            raise StoryError(409, "AUTOMATION_CHAPTER_BLOCKED", "Chapter pipeline did not reach review.", {"jobStatus": job["status"]})
        if job["status"] == "completed":
            return job
        return self.service.phase5.get_chapter_job(project_id, job_id)

    def _auto_revise_until_clear(self, project_id: str, job: dict[str, Any]) -> dict[str, Any]:
        while job["status"] == "human_review":
            quality = self.service.phase5.get_quality_report(project_id, job["id"])
            open_blocking = quality.get("openBlockingCount", 0)
            if open_blocking <= 0:
                return self.service.phase5.get_chapter_job(project_id, job["id"])
            with self.service.db.project(project_id, self.service.get_project(project_id).folder_path) as session:
                policy = session.get(AutomationPolicy, project_id)
                limit = policy.max_revision_rounds if policy else 2
            if job["currentRevisionRound"] >= limit:
                raise StoryError(409, "AUTOMATION_REVISION_LIMIT_REACHED", "Automation revision limit reached.", {"jobId": job["id"]})
            job = self.service.phase5.revise_chapter_job(project_id, job["id"], ChapterRevisionRequest(reason="automation guarded revision"), str(uuid4()))
        return job

    # ------------------------------------------------------------------
    # Internal persistence helpers
    # ------------------------------------------------------------------
    def _get_or_create_policy(self, session: Session, project_id: str) -> AutomationPolicy:
        policy = session.get(AutomationPolicy, project_id)
        if policy:
            return policy
        now = _now()
        policy = AutomationPolicy(project_id=project_id, enabled=False, created_at=now, updated_at=now)
        session.add(policy)
        session.flush()
        return policy

    def _create_run_row(
        self,
        session: Session,
        policy: AutomationPolicy,
        trigger: str,
        scheduled_date: str,
        idempotency_key: str | None,
        now: datetime,
        *,
        status: str = "queued",
    ) -> AutomationRun:
        run = AutomationRun(
            id=str(uuid4()),
            project_id=policy.project_id,
            policy_id=policy.project_id,
            scheduled_local_date=scheduled_date,
            trigger=trigger,
            status=status,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )
        if trigger == "scheduled":
            existing = session.scalar(select(AutomationRun).where(
                AutomationRun.project_id == policy.project_id,
                AutomationRun.scheduled_local_date == scheduled_date,
                AutomationRun.trigger == trigger,
            ))
            if existing:
                return existing
        if idempotency_key:
            existing = session.scalar(select(AutomationRun).where(
                AutomationRun.project_id == policy.project_id,
                AutomationRun.idempotency_key == idempotency_key,
            ))
            if existing:
                return existing
        session.add(run)
        session.flush()
        return run

    def _prepare_run(self, project_id: str, folder_path: str, run_id: str) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            run = self._get_run(session, project_id, run_id)
            policy = self._get_or_create_policy(session, project_id)
            if run.status not in {"queued", "interrupted", "partial"}:
                return
            meta = session.get(ProjectMeta, project_id)
            start = run.start_chapter or ((meta.current_chapter if meta else 0) + 1)
            total = meta.total_chapters if meta else start
            end = min(total, start + policy.chapters_per_run - 1)
            run.status = "running"
            run.started_at = run.started_at or _now()
            run.start_chapter = start
            run.end_chapter = end
            run.planned_count = max(0, end - start + 1)
            run.updated_at = _now()
            run.revision += 1
            for offset, chapter in enumerate(range(start, end + 1), start=1):
                existing = session.scalar(select(AutomationRunItem).where(
                    AutomationRunItem.automation_run_id == run.id,
                    AutomationRunItem.chapter_number == chapter,
                ))
                if not existing:
                    session.add(AutomationRunItem(
                        id=str(uuid4()),
                        project_id=project_id,
                        automation_run_id=run.id,
                        chapter_number=chapter,
                        sequence_number=offset,
                        status="waiting",
                        created_at=_now(),
                        updated_at=_now(),
                    ))

    def _get_run(self, session: Session, project_id: str, run_id: str) -> AutomationRun:
        run = session.get(AutomationRun, run_id)
        if not run or run.project_id != project_id:
            raise StoryError(404, "AUTOMATION_RUN_NOT_FOUND", "Automation run not found.")
        return run

    def _next_waiting_item(self, project_id: str, folder_path: str, run_id: str) -> AutomationRunItem | None:
        with self.service.db.project(project_id, folder_path) as session:
            return session.scalar(select(AutomationRunItem).where(
                AutomationRunItem.automation_run_id == run_id,
                AutomationRunItem.status == "waiting",
            ).order_by(AutomationRunItem.sequence_number.asc()))

    def _mark_item_terminal(self, project_id: str, folder_path: str, item_id: str, status: str, code: str | None, diagnostic: dict[str, Any]) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            item = session.get(AutomationRunItem, item_id)
            if item:
                item.status = status
                item.error_code = code
                item.diagnostic_json = dumps(diagnostic) if diagnostic else None
                item.completed_at = _now()
                item.updated_at = _now()
            run = session.get(AutomationRun, item.automation_run_id) if item else None
            if run and status in {"blocked", "failed", "isolated"}:
                run.isolated_count += 1

    def _mark_item_committed(self, project_id: str, folder_path: str, item_id: str, commit_id: str, contract_id: str | None, job_id: str | None) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            item = session.get(AutomationRunItem, item_id)
            if not item:
                return
            item.status = "committed"
            item.chapter_commit_id = commit_id
            item.chapter_contract_id = contract_id or item.chapter_contract_id
            item.chapter_job_id = job_id or item.chapter_job_id
            item.completed_at = _now()
            item.updated_at = _now()
            run = session.get(AutomationRun, item.automation_run_id)
            if run:
                run.succeeded_count += 1
                run.updated_at = _now()

    def _finish_run_from_items(self, project_id: str, folder_path: str, run_id: str) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            run = self._get_run(session, project_id, run_id)
            items = session.scalars(select(AutomationRunItem).where(AutomationRunItem.automation_run_id == run.id)).all()
            if any(item.status in {"blocked", "failed", "isolated"} for item in items):
                run.status = "partial" if any(item.status == "committed" for item in items) else "blocked"
            else:
                run.status = "completed"
            run.completed_at = _now()
            run.updated_at = _now()
            run.revision += 1

    def _mark_run_terminal(self, project_id: str, folder_path: str, run_id: str, status: str, reason: str, diagnostic: dict[str, Any]) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            run = self._get_run(session, project_id, run_id)
            run.status = status
            run.stop_reason = reason
            run.diagnostic_json = dumps(diagnostic) if diagnostic else None
            run.completed_at = _now()
            run.updated_at = _now()
            run.revision += 1

    def _cancel_waiting_items(self, project_id: str, folder_path: str, run_id: str, *, status: str = "cancelled", code: str = "cancelled") -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            for item in session.scalars(select(AutomationRunItem).where(
                AutomationRunItem.automation_run_id == run_id,
                AutomationRunItem.status == "waiting",
            )).all():
                item.status = status
                item.error_code = code
                item.completed_at = _now()
                item.updated_at = _now()

    def _run_cancel_requested(self, project_id: str, folder_path: str, run_id: str) -> bool:
        with self.service.db.project(project_id, folder_path) as session:
            run = session.get(AutomationRun, run_id)
            return bool(run and run.status == "cancel_requested")

    # ------------------------------------------------------------------
    # Chapter helpers
    # ------------------------------------------------------------------
    def _current_commit(self, project_id: str, folder_path: str, chapter_number: int) -> dict[str, Any] | None:
        with self.service.db.project(project_id, folder_path) as session:
            commit = session.scalar(select(ChapterCommit).where(
                ChapterCommit.project_id == project_id,
                ChapterCommit.chapter_number == chapter_number,
                ChapterCommit.is_current.is_(True),
            ))
            return self.service.phase5._commit_dict(commit) if commit else None

    def _ensure_locked_contract(self, project: Any, chapter_number: int, run_id: str) -> dict[str, Any]:
        with self.service.db.project(project.id, project.folder_path) as session:
            existing = session.scalar(select(ChapterContract).where(
                ChapterContract.project_id == project.id,
                ChapterContract.chapter_number == chapter_number,
                ChapterContract.status == "locked",
            ))
            if existing:
                return self.service.phase5._contract_dict(existing)
            policy = session.get(AutomationPolicy, project.id)
            target_words_min = policy.target_words_min if policy else 1500
            target_words_max = policy.target_words_max if policy else 3000
        derived = self.service.phase5.derive_chapter_contract(project.id, ChapterContractDerive(
            chapter_number=chapter_number,
            target_words_min=target_words_min,
            target_words_max=target_words_max,
        ), str(uuid4()))
        return self.service.phase5.lock_chapter_contract(project.id, derived["id"], ChapterContractLock(expected_revision=derived["revision"]), str(uuid4()))

    def _ensure_job(self, project: Any, contract_id: str, run_id: str, chapter_number: int) -> dict[str, Any]:
        key = f"automation:{run_id}:chapter:{chapter_number}"
        created = self.service.phase5.create_chapter_job(project.id, ChapterJobCreate(chapter_contract_id=contract_id, idempotency_key=key), str(uuid4()))
        return created

    # ------------------------------------------------------------------
    # Cost helpers
    # ------------------------------------------------------------------
    def assert_required_prices(self, project_id: str) -> None:
        missing: list[str] = []
        with self.service.db.catalog() as session:
            bindings = session.scalars(
                select(ModelRoleBinding)
                .where(ModelRoleBinding.role.in_(MODEL_ROLES_FOR_AUTOMATION))
                .options(selectinload(ModelRoleBinding.model).selectinload(ModelConfig.provider))
            ).all()
            by_role = {binding.role: binding for binding in bindings}
            for role in sorted(MODEL_ROLES_FOR_AUTOMATION):
                model = by_role.get(role).model if by_role.get(role) else None
                if model is None or model.input_price_per_million is None or model.output_price_per_million is None:
                    missing.append(role)
        if missing:
            raise StoryError(409, "AUTOMATION_MODEL_PRICE_REQUIRED", "Automation requires input/output prices for every required model role.", {"roles": missing})

    def _budget_allows_next_chapter(self, project_id: str, folder_path: str, run_id: str) -> bool:
        with self.service.db.project(project_id, folder_path) as session:
            policy = session.get(AutomationPolicy, project_id)
            run = session.get(AutomationRun, run_id)
            if not policy or policy.daily_cost_limit is None or not run:
                return True
            return run.estimated_cost + MIN_MODEL_CALL_COST <= policy.daily_cost_limit

    def _run_has_daily_limit(self, project_id: str, folder_path: str, run_id: str) -> bool:
        with self.service.db.project(project_id, folder_path) as session:
            policy = session.get(AutomationPolicy, project_id)
            return bool(policy and policy.daily_cost_limit is not None)

    def _model_run_ids(self, project_id: str, folder_path: str) -> set[str]:
        with self.service.db.project(project_id, folder_path) as session:
            return set(session.scalars(select(ModelRun.id)).all())

    def _update_run_costs(self, project_id: str, folder_path: str, run_id: str, before_ids: set[str]) -> None:
        prices: dict[str, tuple[float, float]] = {}
        with self.service.db.catalog() as session:
            rows = session.scalars(select(ModelConfig)).all()
            prices = {
                row.id: (row.input_price_per_million or 0.0, row.output_price_per_million or 0.0)
                for row in rows
            }
        with self.service.db.project_write(project_id, folder_path) as session:
            new_runs = session.scalars(select(ModelRun).where(ModelRun.id.not_in(before_ids))).all()
            prompt = sum(item.prompt_tokens or 0 for item in new_runs)
            completion = sum(item.completion_tokens or 0 for item in new_runs)
            total = sum(item.total_tokens or 0 for item in new_runs)
            cost = 0.0
            for item in new_runs:
                input_price, output_price = prices.get(item.model_config_id or "", (0.0, 0.0))
                cost += ((item.prompt_tokens or 0) * input_price + (item.completion_tokens or 0) * output_price) / 1_000_000
            run = session.get(AutomationRun, run_id)
            if run:
                run.prompt_tokens += prompt
                run.completion_tokens += completion
                run.total_tokens += total
                run.estimated_cost += cost
                run.updated_at = _now()
            current_item = session.scalar(select(AutomationRunItem).where(
                AutomationRunItem.automation_run_id == run_id,
                AutomationRunItem.status == "committed",
            ).order_by(AutomationRunItem.completed_at.desc()))
            if current_item:
                current_item.prompt_tokens += prompt
                current_item.completion_tokens += completion
                current_item.total_tokens += total
                current_item.estimated_cost += cost

    # ------------------------------------------------------------------
    # Lease and time helpers
    # ------------------------------------------------------------------
    def _acquire_lease(self, project_id: str, folder_path: str, owner_id: str) -> bool:
        with self.service.db.project_write(project_id, folder_path) as session:
            lease = session.get(AutomationLease, project_id)
            now = _now()
            expires = now + timedelta(seconds=LEASE_SECONDS)
            if lease and _as_utc(lease.lease_expires_at) and _as_utc(lease.lease_expires_at) > now and lease.owner_id != owner_id:
                return False
            if lease:
                lease.owner_id = owner_id
                lease.lease_expires_at = expires
                lease.heartbeat_at = now
                lease.revision += 1
            else:
                session.add(AutomationLease(project_id=project_id, owner_id=owner_id, lease_expires_at=expires, heartbeat_at=now))
            return True

    def _heartbeat(self, project_id: str, folder_path: str, owner_id: str) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            lease = session.get(AutomationLease, project_id)
            if lease and lease.owner_id == owner_id:
                lease.heartbeat_at = _now()
                lease.lease_expires_at = _now() + timedelta(seconds=LEASE_SECONDS)
                lease.revision += 1

    def _release_lease(self, project_id: str, folder_path: str, owner_id: str) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            lease = session.get(AutomationLease, project_id)
            if lease and lease.owner_id == owner_id:
                session.delete(lease)

    def _ensure_next_run(self, policy: AutomationPolicy, now: datetime) -> None:
        if policy.next_run_at is None:
            policy.next_run_at = self._next_run_after(policy, now)

    def _next_run_after(self, policy: AutomationPolicy, after: datetime) -> datetime:
        zone = _zone(policy.timezone)
        local = after.astimezone(zone)
        hour, minute = [int(part) for part in policy.time_of_day.split(":")]
        candidate = datetime.combine(local.date(), time(hour=hour, minute=minute), tzinfo=zone)
        if candidate <= local:
            candidate = datetime.combine(local.date() + timedelta(days=1), time(hour=hour, minute=minute), tzinfo=zone)
        return candidate.astimezone(timezone.utc)

    def _local_date_for(self, policy: AutomationPolicy, value: datetime) -> str:
        return value.astimezone(_zone(policy.timezone)).date().isoformat()

    def _today_for_project(self, project_id: str, folder_path: str) -> str:
        with self.service.db.project_write(project_id, folder_path) as session:
            policy = self._get_or_create_policy(session, project_id)
            return datetime.now(_zone(policy.timezone)).date().isoformat()

    # ------------------------------------------------------------------
    # Serializers
    # ------------------------------------------------------------------
    def _policy_dict(self, item: AutomationPolicy) -> dict[str, Any]:
        return {
            "projectId": item.project_id,
            "enabled": item.enabled,
            "timeOfDay": item.time_of_day,
            "timezone": item.timezone,
            "chaptersPerRun": item.chapters_per_run,
            "targetWordsMin": item.target_words_min,
            "targetWordsMax": item.target_words_max,
            "maxRevisionRounds": item.max_revision_rounds,
            "dailyCostLimit": item.daily_cost_limit,
            "stopPolicy": item.stop_policy,
            "approvalMode": item.approval_mode,
            "nextRunAt": item.next_run_at,
            "lastScheduledLocalDate": item.last_scheduled_local_date,
            "revision": item.revision,
            "createdAt": item.created_at,
            "updatedAt": item.updated_at,
        }

    def _run_dict(self, session: Session, item: AutomationRun, *, include_items: bool) -> dict[str, Any]:
        items = []
        if include_items:
            rows = session.scalars(select(AutomationRunItem).where(AutomationRunItem.automation_run_id == item.id).order_by(AutomationRunItem.sequence_number.asc())).all()
            items = [self._item_dict(row) for row in rows]
        return {
            "id": item.id,
            "projectId": item.project_id,
            "policyId": item.policy_id,
            "scheduledLocalDate": item.scheduled_local_date,
            "trigger": item.trigger,
            "status": item.status,
            "idempotencyKey": item.idempotency_key,
            "startChapter": item.start_chapter,
            "endChapter": item.end_chapter,
            "plannedCount": item.planned_count,
            "succeededCount": item.succeeded_count,
            "isolatedCount": item.isolated_count,
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
            "items": items,
        }

    def _item_dict(self, item: AutomationRunItem) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "automationRunId": item.automation_run_id,
            "chapterNumber": item.chapter_number,
            "sequenceNumber": item.sequence_number,
            "chapterContractId": item.chapter_contract_id,
            "chapterJobId": item.chapter_job_id,
            "chapterCommitId": item.chapter_commit_id,
            "status": item.status,
            "promptTokens": item.prompt_tokens,
            "completionTokens": item.completion_tokens,
            "totalTokens": item.total_tokens,
            "estimatedCost": item.estimated_cost,
            "errorCode": item.error_code,
            "diagnostic": loads(item.diagnostic_json) if item.diagnostic_json else None,
            "createdAt": item.created_at,
            "startedAt": item.started_at,
            "completedAt": item.completed_at,
            "updatedAt": item.updated_at,
        }

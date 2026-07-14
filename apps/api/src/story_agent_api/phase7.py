from __future__ import annotations

import asyncio
import contextvars
import threading
from datetime import datetime, time, timedelta, timezone, tzinfo
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, selectinload

from .models import (
    AuditEvent,
    AutomationLease,
    AutomationDailyReport,
    AutomationPolicy,
    AutomationRun,
    AutomationRunItem,
    ChapterCommit,
    ChapterContract,
    ChapterDraft,
    ChapterJob,
    CanonDocument,
    ModelConfig,
    ModelProvider,
    ModelRoleBinding,
    ModelRun,
    Plan,
    PlanNode,
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
    ChapterJobRun,
    ChapterRevisionRequest,
)
from .services import StoryError, dumps, loads, token_estimate


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
MODEL_FAILURE_THRESHOLD = 2
ACTIVE_CHAPTER_JOB_STATUSES = {
    "compiling_context",
    "drafting",
    "extracting",
    "validating",
    "reviewing",
    "revising",
    "committing",
    "cancel_requested",
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
    return ZoneInfo(name)


class Phase7Service:
    def __init__(self, service: Any):
        self.service = service
        self._loop_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._running_threads: dict[str, threading.Thread] = {}
        self._pending_dispatches: set[str] = set()
        self._dispatch_lock = threading.Lock()
        self._execution_context: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
            "automation_execution_context",
            default=None,
        )
        self._lease_owner_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            "automation_lease_owner_context",
            default=None,
        )

    # ------------------------------------------------------------------
    # Lifecycle and scheduler
    # ------------------------------------------------------------------
    def recover_interrupted_automation(self) -> None:
        self.reconcile_orphaned_automation()
        self.check_due_policies(execute_due=False)

    def reconcile_orphaned_automation(self) -> None:
        now = _now()
        for project in self.service.list_projects():
            refreshed_run_ids: list[str] = []
            with self.service.db.project_write(project.id, project.folder_path) as session:
                lease = session.get(AutomationLease, project.id)
                lease_live = bool(
                    lease
                    and _as_utc(lease.lease_expires_at)
                    and _as_utc(lease.lease_expires_at) > now
                )
                active_run_id: str | None = None
                if lease_live and lease and lease.owner_id.startswith("automation:"):
                    parts = lease.owner_id.split(":", 2)
                    if len(parts) == 3:
                        active_run_id = parts[1]
                for run in session.scalars(select(AutomationRun).where(AutomationRun.status.in_(["running", "cancel_requested"]))).all():
                    if active_run_id == run.id:
                        continue
                    recovery_reason = "automation_lease_expired" if lease and not lease_live else "startup_recovery"
                    run.status = "interrupted" if run.status != "cancel_requested" else "cancelled"
                    run.stop_reason = recovery_reason
                    run.completed_at = now
                    run.updated_at = now
                    run.revision += 1
                    for item in session.scalars(select(AutomationRunItem).where(
                        AutomationRunItem.automation_run_id == run.id,
                        AutomationRunItem.status.in_(["waiting", "running"]),
                    )).all():
                        item.status = "waiting" if run.status == "interrupted" else "cancelled"
                        item.error_code = recovery_reason
                        item.completed_at = None if item.status == "waiting" else now
                        item.updated_at = now
                        job = session.get(ChapterJob, item.chapter_job_id) if item.chapter_job_id else None
                        if job and job.status in ACTIVE_CHAPTER_JOB_STATUSES:
                            job.status = "interrupted" if run.status == "interrupted" else "cancelled"
                            job.error_code = "automation_lease_recovery"
                            job.finished_at = now
                            job.updated_at = now
                            job.revision += 1
                    refreshed_run_ids.append(run.id)
                if lease and not lease_live:
                    session.delete(lease)
            for recovered_run_id in refreshed_run_ids:
                self._refresh_daily_report(project.id, project.folder_path, recovered_run_id)

    def start_scheduler(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._loop_task is not None:
            return
        self._stop_event = asyncio.Event()
        self._loop_task = asyncio.create_task(self._scheduler_loop())
        self._dispatch_queued_runs()

    async def stop_scheduler(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._loop_task is not None:
            await self._loop_task
        self.request_running_cancellation()
        with self._dispatch_lock:
            threads = list(self._running_threads.values())
        for thread in threads:
            await asyncio.to_thread(thread.join)
        self._loop_task = None
        self._stop_event = None

    async def _scheduler_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            self.reconcile_orphaned_automation()
            self.check_due_policies(execute_due=True)
            self._dispatch_queued_runs()
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
                else:
                    self._refresh_daily_report(project.id, project.folder_path, run_id)
        return created

    def _dispatch_queued_runs(self) -> None:
        now = _now()
        for project in self.service.list_projects():
            with self.service.db.project(project.id, project.folder_path) as session:
                lease = session.get(AutomationLease, project.id)
                if lease and _as_utc(lease.lease_expires_at) and _as_utc(lease.lease_expires_at) > now:
                    continue
                run_id = session.scalar(
                    select(AutomationRun.id)
                    .where(AutomationRun.project_id == project.id, AutomationRun.status == "queued")
                    .order_by(AutomationRun.created_at.asc())
                    .limit(1)
                )
            if run_id:
                self.dispatch_run(project.id, run_id)

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
        if project.project_kind != "standard":
            resolved = [self.service._resolve_role_model(role) for role in MODEL_ROLES_FOR_AUTOMATION]
            local_test_only = bool(resolved) and all(
                item and (item["provider"].base_url.startswith("http://127.0.0.1") or item["provider"].base_url.startswith("http://localhost"))
                for item in resolved
            )
            if not local_test_only:
                raise StoryError(409, "DEMO_PROJECT_WRITE_BLOCKED", "示例项目不能启动真实付费写作，请新建正式作品。")
        today = self._today_for_project(project.id, project.folder_path)
        should_dispatch = False
        with self.service.db.project_write(project.id, project.folder_path) as session:
            policy = self._get_or_create_policy(session, project.id)
            if policy.daily_cost_limit is not None:
                self.assert_required_prices(project.id)
            existing: AutomationRun | None = None
            if payload.idempotency_key:
                existing = session.scalar(select(AutomationRun).where(
                    AutomationRun.project_id == project.id,
                    AutomationRun.idempotency_key == payload.idempotency_key,
                ))
            if existing:
                run = existing
            else:
                run = self._create_run_row(
                    session,
                    policy,
                    "manual",
                    today,
                    payload.idempotency_key,
                    _now(),
                    requested_chapter_count=payload.chapter_count,
                )
                session.add(self.service._audit("automation_run.queued", "automation_run", run.id, {
                    "trigger": "manual",
                    "chapterCount": payload.chapter_count or policy.chapters_per_run,
                    "requestId": request_id,
                }, request_id))
            run_id = run.id
            should_dispatch = run.status == "queued"
        if should_dispatch:
            self.dispatch_run(project.id, run_id)
        return self.get_run(project.id, run_id)

    def get_trial_readiness(self, project_id: str, chapter_count: int) -> dict[str, Any]:
        if chapter_count not in {1, 3, 5}:
            raise StoryError(422, "TRIAL_CHAPTER_COUNT_INVALID", "chapterCount must be 1, 3, or 5.")
        project = self.service.get_project(project_id)
        checks: list[dict[str, Any]] = []

        def add(
            code: str,
            status: str,
            title: str,
            detail: str,
            action_path: str | None = None,
            chapter_number: int | None = None,
        ) -> None:
            checks.append({
                "code": code,
                "status": status,
                "title": title,
                "detail": detail,
                "actionPath": action_path,
                "chapterNumber": chapter_number,
            })

        add(
            "TRIAL_STANDARD_PROJECT_REQUIRED",
            "ready" if project.project_kind == "standard" else "blocked",
            "正式作品",
            "正式作品可以从第 1 章开始试写。" if project.project_kind == "standard" else "当前是演示项目，禁止真实付费写作。",
            "/overview" if project.project_kind != "standard" else None,
        )

        with self.service.db.project(project.id, project.folder_path) as session:
            meta = session.get(ProjectMeta, project.id)
            start = (meta.current_chapter if meta else project.current_chapter) + 1
            end = start + chapter_count - 1
            total = meta.total_chapters if meta else project.total_chapters
            policy = session.get(AutomationPolicy, project.id)
            canon_locked = session.scalar(select(CanonDocument.id).where(
                CanonDocument.id == "story-core", CanonDocument.status == "locked"
            )) is not None
            plan = session.scalar(select(Plan))
            nodes = session.scalars(select(PlanNode)).all()
            current_commits = set(session.scalars(select(ChapterCommit.chapter_number).where(
                ChapterCommit.is_current.is_(True),
                ChapterCommit.chapter_number >= start,
                ChapterCommit.chapter_number <= min(end, total),
            )).all())
            conflicting_jobs = session.execute(select(ChapterJob, ChapterContract.chapter_number).join(
                ChapterContract, ChapterContract.id == ChapterJob.chapter_contract_id
            ).where(
                ChapterContract.chapter_number >= start,
                ChapterContract.chapter_number <= min(end, total),
                ChapterJob.status.in_([
                    "queued", "compiling_context", "drafting", "extracting", "validating",
                    "reviewing", "human_review", "revising", "approved", "cancel_requested",
                ]),
            )).all()
            active_run = session.scalar(select(AutomationRun.id).where(
                AutomationRun.status.in_(["queued", "running", "cancel_requested"])
            ).limit(1))
            max_revision_rounds = policy.max_revision_rounds if policy else 2
            daily_cost_limit = policy.daily_cost_limit if policy else None

        required_roles = set(MODEL_ROLES_FOR_AUTOMATION)
        if max_revision_rounds == 0:
            required_roles.discard("reviser")
        missing_roles: list[str] = []
        unavailable_roles: list[str] = []
        untested_providers: set[str] = set()
        stale_providers: set[str] = set()
        missing_prices: list[str] = []
        now = _now()
        with self.service.db.catalog() as session:
            bindings = session.scalars(select(ModelRoleBinding).where(
                ModelRoleBinding.role.in_(required_roles)
            ).options(selectinload(ModelRoleBinding.model).selectinload(ModelConfig.provider))).all()
            by_role = {binding.role: binding for binding in bindings}
            for role in sorted(required_roles):
                binding = by_role.get(role)
                model = binding.model if binding else None
                provider: ModelProvider | None = model.provider if model else None
                if not model:
                    missing_roles.append(role)
                    continue
                if daily_cost_limit is not None and (
                    model.input_price_per_million is None or model.output_price_per_million is None
                ):
                    missing_prices.append(role)
                if not model.is_enabled or not provider or not provider.is_enabled or not provider.api_key_ref:
                    unavailable_roles.append(role)
                    continue
                if provider.last_test_status != "success":
                    untested_providers.add(provider.name)
                elif provider.last_tested_at and (_as_utc(provider.last_tested_at) or now) < now - timedelta(days=7):
                    stale_providers.add(provider.name)

        if missing_roles:
            add("TRIAL_MODEL_ROLE_MISSING", "blocked", "模型角色尚未绑定", "缺少：" + "、".join(missing_roles), "/settings")
        elif unavailable_roles:
            add("TRIAL_MODEL_UNAVAILABLE", "blocked", "模型或密钥不可用", "受影响角色：" + "、".join(unavailable_roles), "/settings")
        elif untested_providers:
            add("TRIAL_PROVIDER_NOT_TESTED", "blocked", "模型连接尚未验证", "请测试：" + "、".join(sorted(untested_providers)), "/settings")
        else:
            add("TRIAL_MODELS_READY", "ready", "写作模型已就绪", "写作、抽取、审稿和修订角色均可用。", "/settings")
        if stale_providers:
            add("TRIAL_PROVIDER_TEST_STALE", "warning", "模型连接测试已超过 7 天", "建议重新测试：" + "、".join(sorted(stale_providers)), "/settings")
        if missing_prices:
            add("TRIAL_MODEL_PRICE_MISSING", "blocked", "费用上限缺少模型价格", "缺少：" + "、".join(missing_prices), "/settings")

        if canon_locked:
            add("TRIAL_CANON_READY", "ready", "Canon 已锁定", "章节契约将使用当前正式设定。", "/canon")
        else:
            add("TRIAL_CANON_NOT_LOCKED", "blocked", "Canon 尚未锁定", "请完成故事核心、实体与规则检查后锁定。", "/canon")

        if end > total:
            add("TRIAL_PROJECT_RANGE_EXCEEDED", "blocked", "试写范围超过作品章节数", f"作品共 {total} 章，本批次将到第 {end} 章。", "/overview", total + 1)
        def node_for_chapter(chapter: int) -> PlanNode | None:
            exact = sorted(
                (node for node in nodes if node.target_chapter == chapter),
                key=lambda node: (-node.importance, node.id),
            )
            if exact:
                return exact[0]
            covering = sorted(
                (node for node in nodes if node.range_min <= chapter <= node.range_max),
                key=lambda node: (-node.importance, node.target_chapter, node.id),
            )
            return covering[0] if covering else None

        planned_nodes = {
            chapter: node_for_chapter(chapter)
            for chapter in range(start, min(end, total) + 1)
        } if plan else {}
        uncovered = [chapter for chapter, node in planned_nodes.items() if node is None]
        missing_beats = [
            chapter for chapter, node in planned_nodes.items()
            if node is not None
            and node.type == "章节窗口"
            and not any(
                isinstance(beat, dict)
                and beat.get("chapterNumber", beat.get("chapter_number")) == chapter
                for beat in loads(node.chapter_beats_json)
            )
        ]
        if not plan or uncovered:
            detail = "作品规划不存在。" if not plan else "未覆盖章节：" + "、".join(map(str, uncovered))
            add("TRIAL_PLAN_GAP", "blocked", "故事规划存在缺口", detail, "/planning", uncovered[0] if uncovered else start)
        else:
            add("TRIAL_PLAN_READY", "ready", "规划覆盖试写范围", f"第 {start}—{min(end, total)} 章均有规划窗口。", "/planning")
        if missing_beats:
            add(
                "TRIAL_CHAPTER_BEAT_MISSING",
                "blocked",
                "规划窗口缺少单章节拍",
                "未拆分章节：" + "、".join(map(str, missing_beats)),
                "/planning",
                missing_beats[0],
            )

        if current_commits:
            add("TRIAL_CHAPTER_ALREADY_COMMITTED", "blocked", "试写范围已有正式正文", "已有章节：" + "、".join(map(str, sorted(current_commits))), "/writing", min(current_commits))
        if conflicting_jobs:
            chapter = min(row[1] for row in conflicting_jobs)
            add("TRIAL_CHAPTER_JOB_CONFLICT", "blocked", "试写范围存在未收口任务", "请先处理失败、取消或待复核的章节任务。", "/writing", chapter)
        if active_run:
            add("TRIAL_AUTOMATION_ACTIVE", "blocked", "已有自动托管任务运行中", "同一作品一次只能运行一个托管批次。", "/automation")
        if not current_commits and not conflicting_jobs and not active_run:
            add("TRIAL_PIPELINE_CLEAR", "ready", "章节流水线可用", "没有冲突的正式正文、任务或托管批次。", "/writing")

        blocked = any(item["status"] == "blocked" for item in checks)
        structural_max = 0
        for size in (1, 3, 5):
            candidate_end = start + size - 1
            if candidate_end <= total and plan and all(
                (node_for_chapter(chapter) is not None)
                and (
                    node_for_chapter(chapter).type != "章节窗口"
                    or any(
                        isinstance(beat, dict)
                        and beat.get("chapterNumber", beat.get("chapter_number")) == chapter
                        for beat in loads(node_for_chapter(chapter).chapter_beats_json)
                    )
                )
                for chapter in range(start, candidate_end + 1)
            ):
                structural_max = size
        return {
            "projectId": project.id,
            "chapterCount": chapter_count,
            "startChapter": start,
            "endChapter": end,
            "ready": not blocked,
            "maxSafeChapterCount": 0 if blocked else structural_max,
            "checks": checks,
        }

    def list_runs(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            rows = session.scalars(select(AutomationRun).where(AutomationRun.project_id == project.id).order_by(AutomationRun.created_at.desc())).all()
            return [self._run_dict(session, row, include_items=True) for row in rows]

    def get_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            return self._run_dict(session, run, include_items=True)

    def cancel_run(self, project_id: str, run_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        active_job_id: str | None = None
        finalized_immediately = False
        with self.service.db.project_write(project.id, project.folder_path) as session:
            run = self._get_run(session, project.id, run_id)
            if run.status in TERMINAL_STATUSES:
                return self._run_dict(session, run, include_items=True)
            original_status = run.status
            run.status = "cancelled" if original_status == "queued" else "cancel_requested"
            run.stop_reason = "cancel_requested"
            if original_status == "queued":
                run.completed_at = _now()
                finalized_immediately = True
                for item in session.scalars(select(AutomationRunItem).where(
                    AutomationRunItem.automation_run_id == run.id,
                    AutomationRunItem.status == "waiting",
                )).all():
                    item.status = "cancelled"
                    item.error_code = "cancelled"
                    item.completed_at = _now()
                    item.updated_at = _now()
                self._recount_run(session, run)
            run.revision += 1
            run.updated_at = _now()
            active = session.scalar(select(AutomationRunItem).where(
                AutomationRunItem.automation_run_id == run.id,
                AutomationRunItem.status == "running",
            ))
            active_job_id = active.chapter_job_id if active else None
            session.add(self.service._audit("automation_run.cancel_requested", "automation_run", run.id, {"requestId": request_id}, request_id))
        if finalized_immediately:
            self._refresh_daily_report(project.id, project.folder_path, run_id)
            return self.get_run(project.id, run_id)
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
            )).all():
                resumable = item.status in {"failed", "cancelled", "isolated"}
                resumable = resumable or (
                    item.status == "skipped" and item.error_code != "AUTOMATION_CHAPTER_ALREADY_COMMITTED"
                )
                if not resumable:
                    continue
                item.status = "waiting"
                item.error_code = None
                item.diagnostic_json = None
                item.completed_at = None
                item.updated_at = _now()
            self._recount_run(session, run)
            run.status = "queued"
            run.stop_reason = None
            run.completed_at = None
            run.revision += 1
            run.updated_at = _now()
            session.add(self.service._audit("automation_run.resumed", "automation_run", run.id, {"requestId": request_id}, request_id))
        self.dispatch_run(project.id, run_id, redispatch_if_active=True)
        return self.get_run(project.id, run_id)

    def catch_up_run(self, project_id: str, run_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        should_dispatch = False
        with self.service.db.project_write(project.id, project.folder_path) as session:
            missed = self._get_run(session, project.id, run_id)
            if missed.status != "missed":
                raise StoryError(409, "AUTOMATION_RUN_NOT_MISSED", "Only missed automation runs can be caught up.")
            policy = self._get_or_create_policy(session, project.id)
            if policy.daily_cost_limit is not None:
                self.assert_required_prices(project.id)
            catch_up_key = f"catch-up:{missed.id}"
            catch_up = session.scalar(select(AutomationRun).where(
                AutomationRun.project_id == project.id,
                AutomationRun.idempotency_key == catch_up_key,
            ))
            if catch_up is None:
                catch_up = self._create_run_row(
                    session,
                    policy,
                    "catch_up",
                    missed.scheduled_local_date,
                    catch_up_key,
                    _now(),
                )
                missed.stop_reason = "catch_up_created"
                missed.diagnostic_json = dumps({"catchUpRunId": catch_up.id})
                missed.updated_at = _now()
                missed.revision += 1
                session.add(self.service._audit("automation_run.catch_up_queued", "automation_run", catch_up.id, {"missedRunId": missed.id, "requestId": request_id}, request_id))
            catch_up_id = catch_up.id
            should_dispatch = catch_up.status == "queued"
        if should_dispatch:
            self.dispatch_run(project.id, catch_up_id)
        return self.get_run(project.id, catch_up_id)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def dispatch_run(self, project_id: str, run_id: str, *, redispatch_if_active: bool = False) -> None:
        key = f"{project_id}:{run_id}"
        def worker() -> None:
            try:
                self.execute_run(project_id, run_id)
            finally:
                with self._dispatch_lock:
                    self._running_threads.pop(key, None)

        with self._dispatch_lock:
            active = self._running_threads.get(key)
            if active and active.is_alive():
                if not redispatch_if_active:
                    return
                if key not in self._pending_dispatches:
                    self._pending_dispatches.add(key)

                    def delayed_dispatch(previous: threading.Thread = active) -> None:
                        previous.join()
                        with self._dispatch_lock:
                            self._pending_dispatches.discard(key)
                        try:
                            current = self.get_run(project_id, run_id)
                        except Exception:
                            return
                        if current["status"] == "queued":
                            self.dispatch_run(project_id, run_id)

                    threading.Thread(
                        target=delayed_dispatch,
                        name=f"story-agent-automation-redisp-{run_id[:8]}",
                        daemon=True,
                    ).start()
                return
            thread = threading.Thread(target=worker, name=f"story-agent-automation-{run_id[:8]}", daemon=True)
            self._running_threads[key] = thread
            thread.start()

    def request_running_cancellation(self) -> None:
        now = _now()
        with self._dispatch_lock:
            local_runs = [tuple(key.split(":", 1)) for key in self._running_threads]
        for project_id, run_id in local_runs:
            project = self.service.get_project(project_id)
            active_job_ids: list[str] = []
            with self.service.db.project_write(project.id, project.folder_path) as session:
                run = session.get(AutomationRun, run_id)
                if run and run.status == "running":
                    run.status = "cancel_requested"
                    run.stop_reason = "application_shutdown"
                    run.updated_at = now
                    run.revision += 1
                    active_job_ids.extend(
                        job_id for job_id in session.scalars(
                            select(AutomationRunItem.chapter_job_id).where(
                                AutomationRunItem.automation_run_id == run_id,
                                AutomationRunItem.status == "running",
                                AutomationRunItem.chapter_job_id.is_not(None),
                            )
                        ).all() if job_id
                    )
            for job_id in active_job_ids:
                try:
                    self.service.phase5.cancel_chapter_job(project.id, job_id, str(uuid4()))
                except StoryError:
                    pass

    def execute_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        owner_id = f"automation:{run_id}:{uuid4()}"
        if not self._acquire_lease(project.id, project.folder_path, owner_id):
            with self.service.db.project(project.id, project.folder_path) as session:
                lease = session.get(AutomationLease, project.id)
                if lease and lease.owner_id.startswith(f"automation:{run_id}:"):
                    return self.get_run(project.id, run_id)
            # Another run owns the project. Keep this run queued so the local
            # scheduler can dispatch it after the lease is released.
            return self.get_run(project.id, run_id)
        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()

        def keep_lease_alive() -> None:
            while not heartbeat_stop.wait(LEASE_SECONDS / 3):
                try:
                    renewed = self._heartbeat(project.id, project.folder_path, owner_id)
                except Exception:
                    # A transient SQLite lock must not permanently kill the
                    # heartbeat thread. The next interval retries; commit-time
                    # fencing still rejects an expired or replaced lease.
                    continue
                if renewed is False:
                    lease_lost.set()
                    break

        heartbeat_thread = threading.Thread(
            target=keep_lease_alive,
            name=f"story-agent-lease-{run_id[:8]}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            self._prepare_run(project.id, project.folder_path, run_id)
            with self.service.db.project(project.id, project.folder_path) as session:
                current = self._get_run(session, project.id, run_id)
                if current.status == "cancel_requested":
                    self._mark_run_terminal(project.id, project.folder_path, run_id, "cancelled", current.stop_reason or "cancel_requested", {})
                    return self.get_run(project.id, run_id)
                if current.status in TERMINAL_STATUSES:
                    return self.get_run(project.id, run_id)
            if self._run_has_daily_limit(project.id, project.folder_path, run_id):
                self.assert_required_prices(project.id)
            while True:
                renewed = self._heartbeat(project.id, project.folder_path, owner_id)
                if lease_lost.is_set() or renewed is False:
                    raise StoryError(409, "AUTOMATION_LEASE_LOST", "Automation lease was lost during execution.")
                item = self._next_waiting_item(project.id, project.folder_path, run_id)
                if item is None:
                    self._finish_run_from_items(project.id, project.folder_path, run_id)
                    break
                if self._run_cancel_requested(project.id, project.folder_path, run_id):
                    self._cancel_waiting_items(project.id, project.folder_path, run_id)
                    self._mark_run_terminal(project.id, project.folder_path, run_id, "cancelled", "cancel_requested", {})
                    break
                try:
                    self._execute_item(project, run_id, item.id, owner_id)
                except StoryError as exc:
                    if self._run_cancel_requested(project.id, project.folder_path, run_id):
                        self._mark_item_terminal(project.id, project.folder_path, item.id, "cancelled", "cancelled", {})
                        self._cancel_waiting_items(project.id, project.folder_path, run_id)
                        self._mark_run_terminal(project.id, project.folder_path, run_id, "cancelled", "cancel_requested", {})
                        break
                    failure_count = self._consecutive_model_failures(project.id, project.folder_path, run_id)
                    if failure_count == 1:
                        stop_policy = self._stop_policy(project.id, project.folder_path)
                        run_status = "blocked" if stop_policy == "stop_on_any_failure" else "failed"
                        self._mark_item_terminal(project.id, project.folder_path, item.id, "failed", exc.code, {"message": exc.message, "details": exc.details})
                        self._cancel_waiting_items(project.id, project.folder_path, run_id, status="skipped", code=exc.code)
                        self._mark_run_terminal(project.id, project.folder_path, run_id, run_status, exc.code, {
                            "message": exc.message,
                            "details": exc.details,
                            "consecutiveModelFailures": failure_count,
                            "stopPolicy": stop_policy,
                        })
                        break
                    final_code = "AUTOMATION_MODEL_FAILURE_THRESHOLD" if failure_count >= MODEL_FAILURE_THRESHOLD else exc.code
                    self._mark_item_terminal(project.id, project.folder_path, item.id, "isolated", final_code, {"message": exc.message, "details": exc.details})
                    self._cancel_waiting_items(project.id, project.folder_path, run_id, status="skipped", code=exc.code)
                    self._mark_run_terminal(project.id, project.folder_path, run_id, "blocked", final_code, {
                        "message": exc.message,
                        "details": exc.details,
                        "consecutiveModelFailures": failure_count,
                    })
                    break
                except Exception as exc:
                    self._mark_item_terminal(project.id, project.folder_path, item.id, "failed", "AUTOMATION_ITEM_FAILED", {"errorType": type(exc).__name__})
                    self._cancel_waiting_items(project.id, project.folder_path, run_id, status="skipped", code="AUTOMATION_ITEM_FAILED")
                    self._mark_run_terminal(project.id, project.folder_path, run_id, "failed", "AUTOMATION_ITEM_FAILED", {"errorType": type(exc).__name__})
                    break
            return self.get_run(project.id, run_id)
        except StoryError as exc:
            self._mark_run_terminal(project.id, project.folder_path, run_id, "blocked", exc.code, {"message": exc.message, "details": exc.details})
            return self.get_run(project.id, run_id)
        except Exception as exc:
            self._mark_run_terminal(project.id, project.folder_path, run_id, "failed", "AUTOMATION_RUN_FAILED", {"errorType": type(exc).__name__})
            return self.get_run(project.id, run_id)
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join()
            self._release_lease(project.id, project.folder_path, owner_id)

    def _execute_item(self, project: Any, run_id: str, item_id: str, owner_id: str) -> None:
        token = self._execution_context.set((run_id, item_id))
        owner_token = self._lease_owner_context.set(owner_id)
        try:
            with self.service.db.project_write(project.id, project.folder_path) as session:
                self.assert_current_automation_lease(session, project.id)
                item = session.get(AutomationRunItem, item_id)
                if not item:
                    raise StoryError(404, "AUTOMATION_RUN_ITEM_NOT_FOUND", "Automation run item not found.")
                item.status = "running"
                item.started_at = item.started_at or _now()
                item.updated_at = _now()
                chapter_number = item.chapter_number
                linked_job_id = item.chapter_job_id
            existing_commit = self._current_commit(project.id, project.folder_path, chapter_number)
            if existing_commit:
                if linked_job_id and existing_commit.get("chapterJobId") == linked_job_id:
                    self._mark_item_committed(
                        project.id,
                        project.folder_path,
                        item_id,
                        existing_commit["id"],
                        existing_commit.get("chapterContractId"),
                        linked_job_id,
                    )
                else:
                    self._mark_item_skipped(project.id, project.folder_path, item_id, existing_commit["id"])
                return
            contract = self._ensure_locked_contract(project, chapter_number, run_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                self.assert_current_automation_lease(session, project.id)
                item = session.get(AutomationRunItem, item_id)
                if item:
                    item.chapter_contract_id = contract["id"]
                    item.updated_at = _now()
            job = self._ensure_job(project, contract["id"], run_id, chapter_number)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                self.assert_current_automation_lease(session, project.id)
                item = session.get(AutomationRunItem, item_id)
                if item:
                    item.chapter_job_id = job["id"]
                    item.updated_at = _now()
            job_state = self._advance_job_to_review(project.id, job["id"])
            if job_state["status"] == "completed":
                commit = self._current_commit(project.id, project.folder_path, chapter_number)
                if not commit:
                    raise StoryError(409, "AUTOMATION_COMMIT_NOT_FOUND", "Completed chapter job has no current commit.")
                self._mark_item_committed(project.id, project.folder_path, item_id, commit["id"], contract["id"], job["id"])
                return
            job_state = self._auto_revise_until_clear(project.id, job_state)
            if job_state["status"] == "approved":
                approved = job_state
            else:
                approved = self.service.phase5.approve_chapter_job(project.id, job_state["id"], ChapterApproveRequest(mode="guarded_auto", expected_job_revision=job_state["revision"]), str(uuid4()))
            commit = self.service.phase5.commit_chapter_job(project.id, approved["id"], ChapterCommitRequest(expected_job_revision=approved["revision"]), str(uuid4()))
            self._mark_item_committed(project.id, project.folder_path, item_id, commit["id"], contract["id"], job["id"])
        finally:
            self._sync_run_costs(project.id, project.folder_path, run_id)
            self._lease_owner_context.reset(owner_token)
            self._execution_context.reset(token)

    def _advance_job_to_review(self, project_id: str, job_id: str) -> dict[str, Any]:
        job = self.service.phase5.get_chapter_job(project_id, job_id)
        if job["status"] == "queued":
            job = self.service.phase5.run_chapter_job(project_id, job_id, ChapterJobRun(), str(uuid4()))
        elif job["status"] in {"failed", "interrupted", "cancelled"}:
            job = self.service.phase5.resume_chapter_job(project_id, job_id, str(uuid4()))
        elif job["status"] == "human_review" and job.get("errorCode"):
            job = self.service.phase5.resume_chapter_job(project_id, job_id, str(uuid4()))
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
        requested_chapter_count: int | None = None,
    ) -> AutomationRun:
        run_id = str(uuid4())
        values = {
            "id": run_id,
            "project_id": policy.project_id,
            "policy_id": policy.project_id,
            "scheduled_local_date": scheduled_date,
            "trigger": trigger,
            "status": status,
            "idempotency_key": idempotency_key,
            "requested_chapter_count": requested_chapter_count,
            "planned_count": 0,
            "succeeded_count": 0,
            "isolated_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost": 0.0,
            "revision": 1,
            "created_at": now,
            "updated_at": now,
        }
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
        if trigger == "scheduled" or idempotency_key:
            result = session.execute(sqlite_insert(AutomationRun).values(**values).on_conflict_do_nothing())
            if result.rowcount == 0:
                query = select(AutomationRun).where(AutomationRun.project_id == policy.project_id)
                if trigger == "scheduled":
                    query = query.where(
                        AutomationRun.scheduled_local_date == scheduled_date,
                        AutomationRun.trigger == "scheduled",
                    )
                else:
                    query = query.where(AutomationRun.idempotency_key == idempotency_key)
                existing = session.scalar(query)
                if existing:
                    return existing
                raise StoryError(409, "AUTOMATION_RUN_CONFLICT", "Automation run uniqueness conflict.")
            return session.get(AutomationRun, run_id) or AutomationRun(**values)
        run = AutomationRun(**values)
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
            chapter_count = run.requested_chapter_count or policy.chapters_per_run
            end = min(total, start + chapter_count - 1)
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
            if run:
                self._recount_run(session, run)

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
                self._recount_run(session, run)
                run.updated_at = _now()

    def _mark_item_skipped(self, project_id: str, folder_path: str, item_id: str, commit_id: str) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            item = session.get(AutomationRunItem, item_id)
            if not item:
                return
            item.status = "skipped"
            item.chapter_commit_id = commit_id
            item.error_code = "AUTOMATION_CHAPTER_ALREADY_COMMITTED"
            item.completed_at = _now()
            item.updated_at = _now()
            run = session.get(AutomationRun, item.automation_run_id)
            if run:
                self._recount_run(session, run)

    def _finish_run_from_items(self, project_id: str, folder_path: str, run_id: str) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            run = self._get_run(session, project_id, run_id)
            items = session.scalars(select(AutomationRunItem).where(AutomationRunItem.automation_run_id == run.id)).all()
            self._recount_run(session, run, items)
            if any(item.status in {"blocked", "failed", "isolated"} for item in items):
                run.status = "partial" if any(item.status == "committed" for item in items) else "blocked"
            else:
                run.status = "completed"
            run.completed_at = _now()
            run.updated_at = _now()
            run.revision += 1
        self._refresh_daily_report(project_id, folder_path, run_id)

    def _mark_run_terminal(self, project_id: str, folder_path: str, run_id: str, status: str, reason: str, diagnostic: dict[str, Any]) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            run = self._get_run(session, project_id, run_id)
            run.status = status
            run.stop_reason = reason
            run.diagnostic_json = dumps(diagnostic) if diagnostic else None
            run.completed_at = _now()
            run.updated_at = _now()
            run.revision += 1
        self._refresh_daily_report(project_id, folder_path, run_id)

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
            row = session.execute(
                select(ChapterCommit, ChapterDraft.chapter_job_id)
                .join(ChapterDraft, ChapterDraft.id == ChapterCommit.approved_draft_id)
                .where(
                    ChapterCommit.project_id == project_id,
                    ChapterCommit.chapter_number == chapter_number,
                    ChapterCommit.is_current.is_(True),
                )
            ).first()
            if not row:
                return None
            commit, chapter_job_id = row
            result = self.service.phase5._commit_dict(commit)
            result["chapterJobId"] = chapter_job_id
            return result

    def _ensure_locked_contract(self, project: Any, chapter_number: int, run_id: str) -> dict[str, Any]:
        with self.service.db.project(project.id, project.folder_path) as session:
            existing = session.scalar(select(ChapterContract).where(
                ChapterContract.project_id == project.id,
                ChapterContract.chapter_number == chapter_number,
                ChapterContract.status == "locked",
            ))
            if existing:
                try:
                    self.service.phase5._assert_contract_fresh(session, project.id, existing)
                except StoryError as exc:
                    if exc.code != "CHAPTER_CONTEXT_STALE":
                        raise
                else:
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
        with self.service.db.project(project.id, project.folder_path) as session:
            existing = session.scalar(
                select(ChapterJob)
                .where(
                    ChapterJob.project_id == project.id,
                    ChapterJob.chapter_contract_id == contract_id,
                    ChapterJob.idempotency_key == key,
                )
                .order_by(ChapterJob.updated_at.desc())
            )
            if existing:
                return self.service.phase5._job_dict(existing, session.get(ChapterContract, existing.chapter_contract_id))

            # A process restart can leave a fully persisted candidate draft on an
            # interrupted job which predates the automation run. Reuse that work
            # instead of paying for a second writer call. Cancelled/failed jobs are
            # deliberately excluded: cancellation is user intent, and failed jobs
            # may belong to an obsolete contract or model configuration.
            interrupted_jobs = session.scalars(
                select(ChapterJob)
                .where(
                    ChapterJob.project_id == project.id,
                    ChapterJob.chapter_contract_id == contract_id,
                    ChapterJob.status == "interrupted",
                )
                .order_by(ChapterJob.updated_at.desc())
            ).all()
            for interrupted in interrupted_jobs:
                has_candidate = session.scalar(
                    select(ChapterDraft.id).where(
                        ChapterDraft.project_id == project.id,
                        ChapterDraft.chapter_job_id == interrupted.id,
                        ChapterDraft.is_current.is_(True),
                    )
                )
                linked_active_item = session.scalar(
                    select(AutomationRunItem.id).where(
                        AutomationRunItem.project_id == project.id,
                        AutomationRunItem.chapter_job_id == interrupted.id,
                        AutomationRunItem.status.in_({"waiting", "running"}),
                    )
                )
                if has_candidate and not linked_active_item:
                    return self.service.phase5._job_dict(
                        interrupted,
                        session.get(ChapterContract, interrupted.chapter_contract_id),
                    )
        created = self.service.phase5.create_chapter_job(project.id, ChapterJobCreate(chapter_contract_id=contract_id, idempotency_key=key), str(uuid4()))
        return created

    # ------------------------------------------------------------------
    # Cost helpers
    # ------------------------------------------------------------------
    def assert_required_prices(self, project_id: str) -> None:
        missing: list[str] = []
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            policy = session.get(AutomationPolicy, project.id)
            required_roles = set(MODEL_ROLES_FOR_AUTOMATION)
            if policy and policy.max_revision_rounds == 0:
                required_roles.discard("reviser")
        with self.service.db.catalog() as session:
            bindings = session.scalars(
                select(ModelRoleBinding)
                .where(ModelRoleBinding.role.in_(required_roles))
                .options(selectinload(ModelRoleBinding.model).selectinload(ModelConfig.provider))
            ).all()
            by_role = {binding.role: binding for binding in bindings}
            for role in sorted(required_roles):
                model = by_role.get(role).model if by_role.get(role) else None
                if model is None or model.input_price_per_million is None or model.output_price_per_million is None:
                    missing.append(role)
        if missing:
            raise StoryError(409, "AUTOMATION_MODEL_PRICE_REQUIRED", "Automation requires input/output prices for every required model role.", {"roles": missing})

    def current_execution_context(self) -> tuple[str, str] | None:
        return self._execution_context.get()

    def should_preserve_active_job(self, session: Session, project_id: str, job_id: str) -> bool:
        lease = session.get(AutomationLease, project_id)
        expires_at = _as_utc(lease.lease_expires_at) if lease else None
        if not lease or not expires_at or expires_at <= _now() or not lease.owner_id.startswith("automation:"):
            return False
        parts = lease.owner_id.split(":", 2)
        if len(parts) != 3:
            return False
        run_id = parts[1]
        run = session.get(AutomationRun, run_id)
        if not run or run.project_id != project_id or run.status not in {"running", "cancel_requested"}:
            return False
        return session.scalar(select(AutomationRunItem.id).where(
            AutomationRunItem.automation_run_id == run_id,
            AutomationRunItem.chapter_job_id == job_id,
            AutomationRunItem.status == "running",
        ).limit(1)) is not None

    def assert_current_automation_lease(self, session: Session, project_id: str) -> None:
        context = self.current_execution_context()
        owner_id = self._lease_owner_context.get()
        if context is None or owner_id is None:
            return
        run_id, _item_id = context
        lease = session.get(AutomationLease, project_id)
        expires_at = _as_utc(lease.lease_expires_at) if lease else None
        if not lease or lease.owner_id != owner_id or not expires_at or expires_at <= _now():
            raise StoryError(409, "AUTOMATION_LEASE_LOST", "Automation lease is no longer owned by this execution.", {
                "runId": run_id,
                "ownerId": owner_id,
            })
        run = self._get_run(session, project_id, run_id)
        if run.status == "cancel_requested":
            raise StoryError(409, "AUTOMATION_RUN_CANCELLED", "Automation run cancellation was requested.")

    def before_model_call(self, project_id: str, role: str, messages: list[dict[str, str]], model_id: str) -> None:
        context = self.current_execution_context()
        if context is None:
            return
        run_id, item_id = context
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            policy = session.get(AutomationPolicy, project.id)
            self.assert_current_automation_lease(session, project.id)
            run = self._get_run(session, project.id, run_id)
            item = session.get(AutomationRunItem, item_id)
            if run.status == "cancel_requested":
                raise StoryError(409, "AUTOMATION_RUN_CANCELLED", "Automation run cancellation was requested.")
            failure_query = select(ModelRun.status).where(ModelRun.automation_run_id == run.id)
            failure_window = self._failure_window_start(session, run.id)
            if failure_window is not None:
                failure_query = failure_query.where(ModelRun.started_at >= failure_window)
            failures = session.scalars(failure_query.order_by(ModelRun.started_at.desc())).all()
            consecutive_failures = 0
            for status in failures:
                if status == "failed":
                    consecutive_failures += 1
                elif status == "succeeded":
                    break
            if consecutive_failures >= MODEL_FAILURE_THRESHOLD:
                raise StoryError(409, "AUTOMATION_MODEL_FAILURE_THRESHOLD", "Consecutive model failure threshold reached.", {
                    "consecutiveFailures": consecutive_failures,
                    "threshold": MODEL_FAILURE_THRESHOLD,
                })
            if not policy or policy.daily_cost_limit is None:
                return
            if not item or item.automation_run_id != run.id:
                raise StoryError(409, "AUTOMATION_RUN_ITEM_NOT_FOUND", "Automation run item not found.")
            zone = _zone(policy.timezone)
            local_today = _now().astimezone(zone).date()
            local_start = datetime.combine(local_today, time.min, tzinfo=zone)
            local_end = datetime.combine(local_today + timedelta(days=1), time.min, tzinfo=zone)
            utc_start = local_start.astimezone(timezone.utc)
            utc_end = local_end.astimezone(timezone.utc)
            daily_spend = sum(
                session.scalars(
                    select(ModelRun.estimated_cost).where(
                        ModelRun.automation_run_id.is_not(None),
                        ModelRun.started_at >= utc_start,
                        ModelRun.started_at < utc_end,
                    )
                ).all()
            )
        with self.service.db.catalog() as session:
            model = session.get(ModelConfig, model_id)
            if not model or model.input_price_per_million is None or model.output_price_per_million is None:
                raise StoryError(409, "AUTOMATION_MODEL_PRICE_REQUIRED", "Automation model pricing is required.", {"role": role})
            prompt_text = dumps(messages)
            predicted_prompt_tokens = max(token_estimate(prompt_text), len(prompt_text.encode("utf-8")))
            predicted = (
                predicted_prompt_tokens * model.input_price_per_million
                + model.max_output_tokens * model.output_price_per_million
            ) / 1_000_000
        if daily_spend + predicted > policy.daily_cost_limit:
            raise StoryError(409, "AUTOMATION_COST_LIMIT_REACHED", "Daily automation cost limit would be exceeded.", {
                "dailyCost": daily_spend,
                "predictedCallCost": predicted,
                "dailyCostLimit": policy.daily_cost_limit,
                "role": role,
            })

    def _run_has_daily_limit(self, project_id: str, folder_path: str, run_id: str) -> bool:
        with self.service.db.project(project_id, folder_path) as session:
            policy = session.get(AutomationPolicy, project_id)
            return bool(policy and policy.daily_cost_limit is not None)

    def _stop_policy(self, project_id: str, folder_path: str) -> str:
        with self.service.db.project(project_id, folder_path) as session:
            policy = session.get(AutomationPolicy, project_id)
            return policy.stop_policy if policy else "stop_on_blocking"

    def _sync_run_costs(self, project_id: str, folder_path: str, run_id: str) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            run = session.get(AutomationRun, run_id)
            if not run:
                return
            model_runs = session.scalars(select(ModelRun).where(ModelRun.automation_run_id == run_id)).all()
            run.prompt_tokens = sum(item.prompt_tokens or 0 for item in model_runs)
            run.completion_tokens = sum(item.completion_tokens or 0 for item in model_runs)
            run.total_tokens = sum(item.total_tokens or 0 for item in model_runs)
            run.estimated_cost = sum(item.estimated_cost or 0.0 for item in model_runs)
            run.updated_at = _now()
            for item in session.scalars(select(AutomationRunItem).where(AutomationRunItem.automation_run_id == run_id)).all():
                item_runs = [model_run for model_run in model_runs if model_run.automation_run_item_id == item.id]
                item.prompt_tokens = sum(model_run.prompt_tokens or 0 for model_run in item_runs)
                item.completion_tokens = sum(model_run.completion_tokens or 0 for model_run in item_runs)
                item.total_tokens = sum(model_run.total_tokens or 0 for model_run in item_runs)
                item.estimated_cost = sum(model_run.estimated_cost or 0.0 for model_run in item_runs)
                item.updated_at = _now()

    def _consecutive_model_failures(self, project_id: str, folder_path: str, run_id: str) -> int:
        with self.service.db.project(project_id, folder_path) as session:
            query = select(ModelRun.status).where(ModelRun.automation_run_id == run_id)
            failure_window = self._failure_window_start(session, run_id)
            if failure_window is not None:
                query = query.where(ModelRun.started_at >= failure_window)
            statuses = session.scalars(query.order_by(ModelRun.started_at.desc())).all()
            count = 0
            for status in statuses:
                if status == "failed":
                    count += 1
                elif status == "succeeded":
                    break
            return count

    def _failure_window_start(self, session: Session, run_id: str) -> datetime | None:
        return session.scalar(
            select(AuditEvent.created_at)
            .where(
                AuditEvent.event_type == "automation_run.resumed",
                AuditEvent.entity_type == "automation_run",
                AuditEvent.entity_id == run_id,
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(1)
        )

    def _recount_run(self, session: Session, run: AutomationRun, items: list[AutomationRunItem] | None = None) -> None:
        rows = items if items is not None else list(session.scalars(
            select(AutomationRunItem).where(AutomationRunItem.automation_run_id == run.id)
        ).all())
        run.succeeded_count = sum(1 for item in rows if item.status == "committed")
        run.isolated_count = sum(1 for item in rows if item.status in {"isolated", "blocked", "failed"})

    def get_daily_reports(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            reports = session.scalars(
                select(AutomationDailyReport).where(AutomationDailyReport.project_id == project.id).order_by(AutomationDailyReport.local_date.desc())
            ).all()
            return [self._daily_report_dict(report) for report in reports]

    def _refresh_daily_report(self, project_id: str, folder_path: str, run_id: str) -> None:
        self._sync_run_costs(project_id, folder_path, run_id)
        with self.service.db.project_write(project_id, folder_path) as session:
            run = self._get_run(session, project_id, run_id)
            policy = session.get(AutomationPolicy, project_id)
            runs = session.scalars(select(AutomationRun).where(
                AutomationRun.project_id == project_id,
                AutomationRun.scheduled_local_date == run.scheduled_local_date,
            )).all()
            report = session.scalar(select(AutomationDailyReport).where(
                AutomationDailyReport.project_id == project_id,
                AutomationDailyReport.local_date == run.scheduled_local_date,
            ))
            now = _now()
            if report is None:
                report = AutomationDailyReport(
                    id=str(uuid4()),
                    project_id=project_id,
                    local_date=run.scheduled_local_date,
                    timezone=policy.timezone if policy else "UTC",
                    generated_at=now,
                    updated_at=now,
                )
                session.add(report)
            summary: dict[str, int] = {}
            for daily_run in runs:
                summary[daily_run.status] = summary.get(daily_run.status, 0) + 1
            report.run_count = len(runs)
            report.planned_count = sum(daily_run.planned_count for daily_run in runs)
            report.succeeded_count = sum(daily_run.succeeded_count for daily_run in runs)
            report.isolated_count = sum(daily_run.isolated_count for daily_run in runs)
            report.prompt_tokens = sum(daily_run.prompt_tokens for daily_run in runs)
            report.completion_tokens = sum(daily_run.completion_tokens for daily_run in runs)
            report.total_tokens = sum(daily_run.total_tokens for daily_run in runs)
            report.estimated_cost = sum(daily_run.estimated_cost for daily_run in runs)
            report.status_summary_json = dumps(summary)
            report.generated_at = now
            report.updated_at = now

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

    def _heartbeat(self, project_id: str, folder_path: str, owner_id: str) -> bool:
        with self.service.db.project_write(project_id, folder_path) as session:
            lease = session.get(AutomationLease, project_id)
            now = _now()
            expires_at = _as_utc(lease.lease_expires_at) if lease else None
            if lease and lease.owner_id == owner_id and expires_at and expires_at > now:
                lease.heartbeat_at = now
                lease.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
                lease.revision += 1
                return True
            return False

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
        policy = session.get(AutomationPolicy, item.project_id)
        actions: list[str] = []
        if item.status not in TERMINAL_STATUSES:
            actions.append("cancel")
        if item.status in {"interrupted", "partial", "blocked", "failed", "cancelled"}:
            actions.append("resume")
        if item.status == "missed":
            actions.append("catch_up")
        return {
            "id": item.id,
            "projectId": item.project_id,
            "policyId": item.policy_id,
            "scheduledLocalDate": item.scheduled_local_date,
            "trigger": item.trigger,
            "status": item.status,
            "idempotencyKey": item.idempotency_key,
            "requestedChapterCount": item.requested_chapter_count,
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
            "availableActions": actions,
            "nextRunAt": policy.next_run_at if policy else None,
        }

    def _daily_report_dict(self, item: AutomationDailyReport) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "localDate": item.local_date,
            "timezone": item.timezone,
            "runCount": item.run_count,
            "plannedCount": item.planned_count,
            "succeededCount": item.succeeded_count,
            "isolatedCount": item.isolated_count,
            "promptTokens": item.prompt_tokens,
            "completionTokens": item.completion_tokens,
            "totalTokens": item.total_tokens,
            "estimatedCost": item.estimated_cost,
            "statusSummary": loads(item.status_summary_json),
            "generatedAt": item.generated_at,
            "updatedAt": item.updated_at,
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

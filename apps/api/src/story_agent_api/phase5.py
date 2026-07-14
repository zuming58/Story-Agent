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
    CanonEntity,
    CanonEntityType,
    CanonRelation,
    CanonRule,
    ChapterCommit,
    ChapterContract,
    ChapterDraft,
    ChapterExtraction,
    ChapterJob,
    Foreshadow,
    KnowledgeBoundary,
    ModelRun,
    Plan,
    PlanNode,
    ProjectMeta,
    QualityFinding,
    QualityRun,
    SourceVersion,
    StateDelta,
    StateFact,
    StateSnapshot,
    StoryEntity,
    utc_now,
)
from .schemas import (
    ChapterApproveRequest,
    ChapterCommitRequest,
    ChapterContractDerive,
    ChapterContractLock,
    ChapterContractUpdate,
    ChapterDraftActivateRequest,
    ChapterJobCreate,
    ChapterQualityRevalidate,
    ChapterJobRetry,
    ChapterJobRun,
    ChapterManualRevisionRequest,
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


def _requirement_evident(requirement: str, content: str, extracted: set[str] | None = None) -> bool:
    needle = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", requirement).lower()
    haystack = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", content).lower()
    if not needle:
        return True
    if needle in haystack:
        return True
    for value in extracted or set():
        normalized = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", value).lower()
        if needle in normalized or normalized in needle:
            return True
    if "至少两次" in requirement and "移动规则" in requirement:
        observations = re.findall(
            r"纸(?:人|童).{0,24}?(?:前移|已经?贴|已经?在|靠近|位移|近了)",
            content,
            flags=re.S,
        )
        if len(observations) >= 2 and any(marker in content for marker in ("验证", "确认", "记录", "规则成立")):
            return True
    # Chapter beats are written as planning language, while the prose is
    # expected to use natural wording. Preserve strict matching first, then
    # recognise a small set of explicit Chinese action concepts only when all
    # concepts requested by the condition are evidenced in the chapter.
    semantic_aliases = {
        "决定": ("决定", "打算", "准备", "今晚我去", "必须去"),
        "夜间": ("夜间", "今晚", "天黑", "夜里", "入夜"),
        "实地": ("实地", "现场", "亲自去", "去看看", "看现场"),
        "确认": ("确认", "核实", "证实", "验证", "发现", "意识到", "明白", "认定"),
        "街巷": ("街巷", "巷", "岔口", "门牌", "地址"),
        # These concepts occur in the formal Night Watch chapter beats. They
        # require evidence for every named concept, while accepting natural
        # narrative wording instead of a verbatim copy of the beat.
        "夜雾": ("夜雾", "雾气", "灰雾", "浓雾"),
        "改变": ("改变", "折叠", "错位", "回到原点", "路径"),
        "街道路": ("街道路", "街道", "巷", "路面", "青石板"),
        "巡夜灯": ("巡夜灯", "旧风灯", "那盏灯"),
        "被动显路": ("自己移动", "悬在前方", "指路", "引路", "照出", "照亮", "路径"),
        "记忆代价": ("记忆代价", "想不起", "遗忘", "忘记", "记不住", "被擦掉"),
        "利用规则": ("利用规则", "按照规则", "直视", "盯着", "保持视线"),
        "脱离": ("脱离", "退出", "退到", "后退", "离开", "走入槐树巷", "没有跟出"),
        "危险": ("危险", "纸人", "纸童", "夜雾", "异常"),
        "纸童": ("纸童", "纸人", "无脸纸童", "无脸纸人"),
        "移动规则": ("移动规则", "直视即静止", "视线移开", "位移", "移动条件"),
        "至少两次": ("至少两次", "两次", "第一次验证", "第二次验证", "两次了", "结果完全一致"),
        "可验证证据": ("可验证", "验证", "结果完全一致", "规则成立", "记录"),
    }
    required_groups = [variants for concept, variants in semantic_aliases.items() if concept in requirement]
    if required_groups and all(any(alias in content for alias in variants) for variants in required_groups):
        return True
    if len(needle) < 4:
        return False
    needle_pairs = {needle[index:index + 2] for index in range(len(needle) - 1)}
    haystack_pairs = {haystack[index:index + 2] for index in range(len(haystack) - 1)}
    return bool(needle_pairs) and len(needle_pairs & haystack_pairs) / len(needle_pairs) >= 0.45


def _canonical_reference_evident(name: str, content: str, extracted: set[str]) -> bool:
    normalized_name = name.strip().lower()
    if not normalized_name:
        return True
    if normalized_name in content or normalized_name in extracted:
        return True
    # Four-or-more-character descriptive Canon labels are often shortened in
    # prose (for example, an adjective plus a two-character noun). Ordinary
    # two/three-character personal names stay exact to avoid false positives.
    if len(normalized_name) >= 4:
        short_reference = normalized_name[-2:]
        if short_reference in content or short_reference in extracted:
            return True
        # Chinese prose commonly alternates the final person classifier in a
        # descriptive label (纸童/纸人, 女童/女孩) while retaining the
        # distinctive modifier. Keep this deliberately narrow: only the last
        # classifier may vary and the preceding character must still match.
        person_classifiers = {"人", "童", "孩", "者"}
        if short_reference[-1] in person_classifiers:
            alternatives = {
                f"{short_reference[:-1]}{classifier}"
                for classifier in person_classifiers
                if classifier != short_reference[-1]
            }
            return any(alias in content or alias in extracted for alias in alternatives)
    return False


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
                    phase7 = getattr(self.service, "phase7", None)
                    if phase7 is not None and phase7.should_preserve_active_job(session, project.id, job.id):
                        continue
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
        if payload.chapter_number > project.total_chapters:
            raise StoryError(422, "CHAPTER_NUMBER_OUT_OF_RANGE", "Chapter number exceeds the project's planned chapter count.", {"totalChapters": project.total_chapters})
        with self.service.db.project_write(project.id, project.folder_path) as session:
            phase7 = getattr(self.service, "phase7", None)
            if phase7 is not None:
                phase7.assert_current_automation_lease(session, project.id)
            locked_docs = session.scalars(select(CanonDocument).where(CanonDocument.status == "locked").order_by(CanonDocument.id.asc())).all()
            if not locked_docs:
                raise StoryError(409, "CANON_NOT_LOCKED", "Canon must be locked before deriving chapter contracts.")
            plan = session.scalar(select(Plan))
            node = self._resolve_contract_node(session, payload, plan)
            latest_snapshot = session.scalar(
                select(StateSnapshot)
                .join(SourceVersion, SourceVersion.id == StateSnapshot.source_version_id)
                .where(StateSnapshot.project_id == project.id)
                .where(SourceVersion.status == "official")
                .order_by(StateSnapshot.snapshot_number.desc(), StateSnapshot.created_at.desc())
            )
            future_nodes = []
            if plan:
                future_nodes = [
                    self.service._node_dict(item)
                    for item in session.scalars(select(PlanNode).where(PlanNode.target_chapter > payload.chapter_number).order_by(PlanNode.target_chapter.asc())).all()
                ]
            node_payload = self.service._node_dict(node) if node else {}
            chapter_beat = self._chapter_beat(node, payload.chapter_number)
            if node and node.type == "章节窗口" and chapter_beat is None:
                raise StoryError(
                    409,
                    "CHAPTER_BEAT_MISSING",
                    "The planning window does not define a beat for this chapter.",
                    {"planNodeId": node.id, "chapterNumber": payload.chapter_number},
                )
            node_is_due = bool(node and payload.chapter_number >= node.range_min)
            if chapter_beat is not None:
                beat_objective = str(chapter_beat.get("objective", "")).strip()
                beat_conditions = self._beat_strings(chapter_beat, "completionConditions", "completion_conditions")
                beat_hooks = self._beat_strings(chapter_beat, "hooks")
                beat_foreshadows = self._beat_strings(chapter_beat, "foreshadows")
                beat_characters = self._beat_strings(chapter_beat, "requiredCharacters", "required_characters")
                beat_forbidden = self._beat_strings(chapter_beat, "forbidden")
                must_advance: dict[str, Any] = {
                    "chapterNumber": payload.chapter_number,
                    "title": chapter_beat.get("title"),
                    "objective": beat_objective,
                    "planWindowId": node.id if node else None,
                    "planWindowTitle": node.title if node else None,
                }
                may_advance: list[Any] = [beat_objective, *(_safe_loads(node.contracts_json, []) if node else [])]
                completion_conditions = beat_conditions
                required_hooks = beat_hooks
                required_foreshadows = beat_foreshadows
                required_characters = beat_characters
            else:
                must_advance = node_payload if node_is_due else {
                    "chapterNumber": payload.chapter_number,
                    "setupForPlanNodeId": node.id if node else None,
                    "instruction": "Advance setup only; do not complete the future milestone.",
                }
                may_advance = [node_payload] if node and not node_is_due else (_safe_loads(node.contracts_json, []) if node else [])
                completion_conditions = _safe_loads(node.completion_conditions_json, []) if node_is_due else []
                required_hooks = self._strings_from_payload(node, "contracts_json")
                required_foreshadows = self._strings_from_payload(node, "foreshadows_json")
                required_characters = []
                beat_forbidden = []
            objective = {
                "mustAdvance": must_advance,
                "authorNote": payload.author_note,
            }
            allowed_scope = {
                "chapterNumber": payload.chapter_number,
                "planNodeId": node.id if node else payload.plan_node_id,
                "mayAdvance": may_advance,
                "completionConditions": completion_conditions,
            }
            forbidden_scope = {
                "mustNotAdvance": [item for item in future_nodes if not node or item.get("id") != node.id],
                "mustNotComplete": beat_forbidden or ([node_payload] if node and not node_is_due else []),
                "futureKeywords": [
                    *beat_forbidden,
                    *[item.get("title", "") for item in future_nodes if item.get("title") and (not node or item.get("id") != node.id)],
                ],
            }
            now = _now()
            item = ChapterContract(
                id=str(uuid4()),
                project_id=project.id,
                chapter_number=payload.chapter_number,
                title=payload.title or (str(chapter_beat.get("title")) if chapter_beat else (node.title if node else f"Chapter {payload.chapter_number}")),
                plan_node_id=node.id if node else payload.plan_node_id,
                plan_node_revision=node.revision if node else 1,
                canon_revision_digest=self._current_canon_digest(session),
                state_snapshot_id=latest_snapshot.id if latest_snapshot else None,
                objective_json=dumps(objective),
                allowed_scope_json=dumps(allowed_scope),
                forbidden_scope_json=dumps(forbidden_scope),
                required_characters_json=dumps(required_characters),
                required_foreshadows_json=dumps(required_foreshadows),
                required_hooks_json=dumps(required_hooks),
                completion_conditions_json=dumps(completion_conditions),
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
                if value is None:
                    raise StoryError(422, "INVALID_CHAPTER_CONTRACT", f"Chapter contract field cannot be null: {key}")
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
                phase7 = getattr(self.service, "phase7", None)
                if phase7 is not None:
                    phase7.assert_current_automation_lease(session, project.id)
                item = self._get_contract(session, project.id, contract_id)
                if item.revision != payload.expected_revision:
                    raise StoryError(409, "CHAPTER_CONTRACT_REVISION_CONFLICT", "Chapter contract revision conflict.", {"currentRevision": item.revision})
                if item.status == "locked":
                    return self._contract_dict(item)
                if item.status != "draft":
                    raise StoryError(409, "CHAPTER_CONTRACT_NOT_RESUMABLE", "Only draft contracts can be locked.")
                self._assert_contract_fresh(session, project.id, item)
                now = _now()
                previous_locked = session.scalar(select(ChapterContract).where(
                    ChapterContract.project_id == project.id,
                    ChapterContract.chapter_number == item.chapter_number,
                    ChapterContract.status == "locked",
                    ChapterContract.id != item.id,
                ))
                if previous_locked is not None:
                    current_commit_id = session.scalar(select(ChapterCommit.id).where(
                        ChapterCommit.project_id == project.id,
                        ChapterCommit.chapter_number == item.chapter_number,
                        ChapterCommit.is_current.is_(True),
                    ))
                    previous_job_statuses = list(session.scalars(select(ChapterJob.status).where(
                        ChapterJob.project_id == project.id,
                        ChapterJob.chapter_contract_id == previous_locked.id,
                    )).all())
                    abandoned_contract = bool(previous_job_statuses) and all(
                        status in {"cancelled", "failed", "interrupted"}
                        for status in previous_job_statuses
                    )
                    if current_commit_id is None and not abandoned_contract:
                        raise StoryError(
                            409,
                            "CHAPTER_CONTRACT_LOCK_CONFLICT",
                            "Only one locked contract is allowed per project chapter.",
                        )
                    previous_locked.status = "superseded"
                    previous_locked.revision += 1
                    previous_locked.updated_at = now
                    session.add(self.service._audit(
                        "chapter_contract.superseded",
                        "chapter_contract",
                        previous_locked.id,
                        {
                            "replacementContractId": item.id,
                            "chapterNumber": item.chapter_number,
                            "currentCommitId": current_commit_id,
                            "abandonedJobStatuses": previous_job_statuses if abandoned_contract else [],
                            "requestId": request_id,
                        },
                        request_id,
                    ))
                    # Release the partial unique index before locking the replacement.
                    session.flush()
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
            phase7 = getattr(self.service, "phase7", None)
            if phase7 is not None:
                phase7.assert_current_automation_lease(session, project.id)
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
            phase7 = getattr(self.service, "phase7", None)
            if phase7 is not None:
                phase7.assert_current_automation_lease(session, project.id)
            job = self._get_job(session, project.id, job_id)
            if job.status in ACTIVE_JOB_STATUSES:
                raise StoryError(409, "CHAPTER_JOB_ALREADY_RUNNING", "Chapter job is already running.")
            if job.status != "queued":
                raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "Queue or retry the chapter job before running it.")
            contract = self._get_contract(session, project.id, job.chapter_contract_id)
            if contract.status != "locked":
                raise StoryError(409, "CHAPTER_CONTRACT_NOT_LOCKED", "Chapter contract must be locked before running.")
            self._assert_contract_fresh(session, project.id, contract)
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
            self._raise_if_cancel_requested(project, job_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                job.status = "drafting"
                job.context_trace_id = context["traceId"]
                job.revision += 1
                job.updated_at = _now()
            contract_data = self.get_chapter_contract(project.id, self._job_contract_id(project, job_id))
            draft_text, draft_run_id = self._complete_role_text(
                project,
                "chinese_writer",
                request_id,
                self._writer_messages(contract_data, context, payload.author_note),
                response_json=False,
            )
            self._raise_if_cancel_requested(project, job_id)
            draft = self._store_draft(project.id, project.folder_path, job_id, contract_data["id"], draft_text, draft_run_id, context["traceId"], "generated")
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                job.status = "extracting"
                job.revision += 1
                job.updated_at = _now()
            extraction = self._extract_for_draft(project, draft["id"], request_id)
            self._raise_if_cancel_requested(project, job_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                job.status = "validating"
                job.revision += 1
                job.updated_at = _now()
            self._validate_extraction(project, extraction["id"])
            self._raise_if_cancel_requested(project, job_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                job.status = "reviewing"
                job.revision += 1
                job.updated_at = _now()
            self._run_quality_pipeline(project, job_id, draft["id"], request_id)
            self._raise_if_cancel_requested(project, job_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                job.status = "human_review"
                job.revision += 1
                job.updated_at = _now()
                session.add(self.service._audit("chapter_job.draft_ready", "chapter_job", job.id, {"draftId": draft["id"], "requestId": request_id}, request_id))
                session.flush()
                return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))
        except StoryError as exc:
            if exc.code == "CHAPTER_JOB_CANCELLED":
                return self.get_chapter_job(project.id, job_id)
            self._fail_job(project.id, project.folder_path, job_id, exc.code, {"message": exc.message, "details": exc.details})
            raise
        except ModelProviderError as exc:
            self._fail_job(project.id, project.folder_path, job_id, exc.code, {"message": exc.message, "retryable": exc.retryable})
            raise StoryError(502, exc.code, exc.message) from exc
        except Exception as exc:
            self._fail_job(project.id, project.folder_path, job_id, "CHAPTER_PIPELINE_FAILED", {"errorType": type(exc).__name__})
            raise

    def resume_chapter_job(self, project_id: str, job_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            phase7 = getattr(self.service, "phase7", None)
            if phase7 is not None:
                phase7.assert_current_automation_lease(session, project.id)
            job = self._get_job(session, project.id, job_id)
            contract = self._get_contract(session, project.id, job.chapter_contract_id)
            self._assert_contract_fresh(session, project.id, contract)
            if job.status in {"completed", "approved"}:
                return self._job_dict(job, contract)
            if job.status == "human_review" and not job.error_code:
                return self._job_dict(job, contract)
            if job.status not in {"failed", "interrupted", "cancelled", "human_review"}:
                raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "Chapter job cannot be resumed from its current status.")
            draft = self._current_draft(session, job.id)
            force_reextract = job.error_code == "CHAPTER_EXTRACTION_INVALID"
            if draft is None:
                needs_full_retry = True
                draft_id = None
            else:
                needs_full_retry = False
                draft_id = draft.id
                job.status = "reviewing" if job.status == "human_review" else "extracting"
                job.current_revision_round = max(job.current_revision_round, min(MAX_REVISION_ROUNDS, draft.version_number - 1))
                job.error_code = None
                job.diagnostic_json = dumps({"resumedFromDraftId": draft.id})
                job.finished_at = None
                job.revision += 1
                job.updated_at = _now()

        if needs_full_retry:
            self.retry_chapter_job(project.id, job_id, ChapterJobRetry(reason="resume without persisted draft"), request_id)
            return self.run_chapter_job(project.id, job_id, ChapterJobRun(), request_id)

        assert draft_id is not None
        try:
            with self.service.db.project(project.id, project.folder_path) as session:
                extraction = session.scalar(
                    select(ChapterExtraction)
                    .where(ChapterExtraction.chapter_draft_id == draft_id)
                    .order_by(ChapterExtraction.created_at.desc())
                )
                extraction_id = extraction.id if extraction and extraction.status == "validated" and not force_reextract else None
                extraction_status = extraction.status if extraction else None
            if extraction_id is None:
                extraction_data = self._extract_for_draft(project, draft_id, request_id)
                extraction_id = extraction_data["id"]
                extraction_status = extraction_data["status"]
            if extraction_status != "validated":
                self._validate_extraction(project, extraction_id)
            self._raise_if_cancel_requested(project, job_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                current = self._get_job(session, project.id, job_id)
                current.status = "reviewing"
                current.revision += 1
                current.updated_at = _now()
            self._run_quality_pipeline(project, job_id, draft_id, request_id)
            self._raise_if_cancel_requested(project, job_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                current = self._get_job(session, project.id, job_id)
                current.status = "human_review"
                current.error_code = None
                current.finished_at = None
                current.revision += 1
                current.updated_at = _now()
                session.add(self.service._audit(
                    "chapter_job.resumed_from_draft",
                    "chapter_job",
                    current.id,
                    {"draftId": draft_id, "requestId": request_id},
                    request_id,
                ))
                return self._job_dict(current, session.get(ChapterContract, current.chapter_contract_id))
        except StoryError as exc:
            if exc.code == "CHAPTER_JOB_CANCELLED":
                return self.get_chapter_job(project.id, job_id)
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
            if job.status == "cancel_requested" or job.status == "cancelled":
                return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))
            if job.status in ACTIVE_JOB_STATUSES:
                job.status = "cancel_requested"
                job.error_code = "cancel_requested"
                event_type = "chapter_job.cancel_requested"
            elif job.status in {"queued", "failed", "interrupted", "human_review"}:
                job.status = "cancelled"
                job.error_code = "cancelled"
                job.finished_at = _now()
                event_type = "chapter_job.cancelled"
            else:
                raise StoryError(409, "CHAPTER_JOB_NOT_CANCELLABLE", "Chapter job cannot be cancelled from its current status.")
            job.revision += 1
            job.updated_at = _now()
            session.add(self.service._audit(event_type, "chapter_job", job.id, {"requestId": request_id}, request_id))
            return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))

    def retry_chapter_job(self, project_id: str, job_id: str, payload: ChapterJobRetry, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            phase7 = getattr(self.service, "phase7", None)
            if phase7 is not None:
                phase7.assert_current_automation_lease(session, project.id)
            job = self._get_job(session, project.id, job_id)
            if job.status not in {"failed", "interrupted", "cancelled", "human_review"}:
                raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "Chapter job cannot be retried from its current status.")
            job.status = "queued"
            job.attempt_number += 1
            job.error_code = None
            job.diagnostic_json = dumps({"retryReason": payload.reason})
            job.started_at = None
            job.finished_at = None
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

    def list_chapter_commits(self, project_id: str, chapter_number: int) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            rows = session.scalars(
                select(ChapterCommit)
                .where(
                    ChapterCommit.project_id == project.id,
                    ChapterCommit.chapter_number == chapter_number,
                )
                .order_by(ChapterCommit.committed_at.desc())
            ).all()
            return [self._commit_dict(item) for item in rows]

    # Quality/approval/commit methods are completed in the later work packages.
    def get_quality_report(self, project_id: str, job_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            current = self._current_draft(session, job.id)
            findings = session.scalars(select(QualityFinding).where(QualityFinding.project_id == project.id, QualityFinding.chapter_draft_id == current.id).order_by(QualityFinding.created_at.asc())).all() if current else []
            runs = session.scalars(select(QualityRun).where(QualityRun.project_id == project.id, QualityRun.chapter_job_id == job.id).order_by(QualityRun.created_at.asc())).all()
            run_payloads = []
            for run in runs:
                run_findings = [item for item in findings if item.quality_run_id == run.id]
                run_payloads.append(self._quality_run_dict(run, run_findings))
            return {"jobId": job.id, "currentDraftId": current.id if current else None, "openBlockingCount": self._open_blocking_count(findings), "runs": run_payloads, "findings": [self._finding_dict(item) for item in findings]}

    def revalidate_deterministic_quality(self, project_id: str, job_id: str, payload: ChapterQualityRevalidate, request_id: str) -> dict[str, Any]:
        """Re-run only deterministic rules for a reviewed candidate.

        A rule upgrade may invalidate an old false positive.  This transition
        is deliberately auditable and revision-protected: it cannot rewrite
        the draft, invoke a model, or silently accept a risk.
        """
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            if job.revision != payload.expected_job_revision:
                raise StoryError(409, "CHAPTER_JOB_REVISION_CONFLICT", "Chapter job revision conflict.", {"currentRevision": job.revision})
            if job.status != "human_review":
                raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "Only a chapter awaiting review can be revalidated.")
            draft = self._current_draft(session, job.id)
            if not draft:
                raise StoryError(409, "CHAPTER_DRAFT_EMPTY", "No chapter draft exists for revalidation.")
            contract = self._get_contract(session, project.id, job.chapter_contract_id)
            self._assert_contract_fresh(session, project.id, contract)
            job.status = "reviewing"
            job.revision += 1
            job.updated_at = _now()
            draft_id = draft.id

        try:
            self._run_deterministic_quality(project, job_id, draft_id, request_id, replace_previous=True)
        except Exception:
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                job.status = "human_review"
                job.revision += 1
                job.updated_at = _now()
            raise

        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            job.status = "human_review"
            job.error_code = None
            job.diagnostic_json = dumps({"deterministicQualityRevalidated": True})
            job.revision += 1
            job.updated_at = _now()
            session.add(self.service._audit(
                "chapter_job.deterministic_quality_revalidated",
                "chapter_job",
                job.id,
                {"draftId": draft_id, "requestId": request_id},
                request_id,
            ))
            return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))

    def accept_quality_risk(self, project_id: str, finding_id: str, payload: QualityFindingAcceptRisk, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            finding = session.get(QualityFinding, finding_id)
            if not finding or finding.project_id != project.id:
                raise StoryError(404, "QUALITY_FINDING_NOT_FOUND", "Quality finding not found.")
            if finding.status != "open":
                raise StoryError(409, "QUALITY_FINDING_ALREADY_RESOLVED", "Only an open quality finding can be accepted as risk.")
            finding.status = "accepted_risk"
            finding.accepted_reason = payload.reason
            finding.updated_at = _now()
            session.add(self.service._audit("quality_finding.accepted_risk", "quality_finding", finding.id, {"reason": payload.reason, "requestId": request_id}, request_id))
            return self._finding_dict(finding)

    def revise_chapter_job(self, project_id: str, job_id: str, payload: ChapterRevisionRequest, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            phase7 = getattr(self.service, "phase7", None)
            if phase7 is not None:
                phase7.assert_current_automation_lease(session, project.id)
            job = self._get_job(session, project.id, job_id)
            if job.status != "human_review":
                raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "Only a chapter in human review can be revised.")
            if job.current_revision_round >= MAX_REVISION_ROUNDS:
                raise StoryError(409, "CHAPTER_REVISION_LIMIT_REACHED", "Chapter revision limit reached.")
            draft = self._current_draft(session, job.id)
            if not draft:
                raise StoryError(409, "CHAPTER_DRAFT_EMPTY", "No chapter draft exists for revision.")
            findings = session.scalars(select(QualityFinding).where(
                QualityFinding.project_id == project.id,
                QualityFinding.chapter_draft_id == draft.id,
                QualityFinding.status == "open",
            )).all()
            if not findings:
                raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "No open findings require revision.")
            job.status = "revising"
            job.current_revision_round += 1
            job.revision += 1
            job.updated_at = _now()
            contract = self._get_contract(session, project.id, job.chapter_contract_id)
            contract_data = self._contract_dict(contract)
            draft_data = self._draft_dict(draft)
            finding_data = [self._finding_dict(item) for item in findings]

        revised_created = False
        try:
            revised_text, run_id = self._complete_role_text(
                project,
                "reviser",
                request_id,
                self._revision_messages(contract_data, draft_data, finding_data, payload.reason),
                response_json=True,
            )
            self._raise_if_cancel_requested(project, job_id)
            try:
                data = _json_object_from_text(revised_text)
                content = str(data.get("contentMarkdown") or data.get("content_markdown") or "").strip()
            except (ValueError, json.JSONDecodeError):
                content = revised_text.strip()
            revised = self._store_draft(project.id, project.folder_path, job_id, contract_data["id"], content, run_id, draft_data.get("contextTraceId"), "revised", parent_id=draft_data["id"])
            revised_created = True
            extraction = self._extract_for_draft(project, revised["id"], request_id)
            self._raise_if_cancel_requested(project, job_id)
            self._validate_extraction(project, extraction["id"])
            self._run_quality_pipeline(project, job_id, revised["id"], request_id)
            self._raise_if_cancel_requested(project, job_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                for finding in session.scalars(select(QualityFinding).where(QualityFinding.chapter_draft_id == draft_data["id"], QualityFinding.status == "open")).all():
                    finding.status = "superseded"
                    finding.updated_at = _now()
                job.status = "human_review"
                job.error_code = None
                job.diagnostic_json = None
                job.revision += 1
                job.updated_at = _now()
                session.add(self.service._audit("chapter_job.revised", "chapter_job", job.id, {"draftId": revised["id"], "revisionRound": job.current_revision_round, "requestId": request_id}, request_id))
                return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))
        except StoryError as exc:
            if exc.code == "CHAPTER_JOB_CANCELLED":
                return self.get_chapter_job(project.id, job_id)
            self._return_revision_to_human_review(project.id, project.folder_path, job_id, exc.code, {"message": exc.message, "details": exc.details}, restore_round=not revised_created)
            raise
        except ModelProviderError as exc:
            self._return_revision_to_human_review(project.id, project.folder_path, job_id, exc.code, {"message": exc.message, "retryable": exc.retryable}, restore_round=not revised_created)
            raise StoryError(502, exc.code, exc.message) from exc
        except Exception as exc:
            self._return_revision_to_human_review(project.id, project.folder_path, job_id, "CHAPTER_REVISION_FAILED", {"errorType": type(exc).__name__}, restore_round=not revised_created)
            raise

    def create_manual_revision(self, project_id: str, job_id: str, payload: ChapterManualRevisionRequest, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            if job.revision != payload.expected_job_revision:
                raise StoryError(409, "CHAPTER_JOB_REVISION_CONFLICT", "Chapter job revision conflict.", {"currentRevision": job.revision})
            if job.status != "human_review":
                raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "Only a chapter in human review can be edited.")
            parent = self._get_draft(session, project.id, payload.parent_draft_id)
            if parent.chapter_job_id != job.id or not parent.is_current:
                raise StoryError(409, "CHAPTER_DRAFT_NOT_CURRENT", "The edited draft is no longer the current candidate.")
            if parent.revision != payload.expected_parent_revision:
                raise StoryError(409, "CHAPTER_DRAFT_REVISION_CONFLICT", "Chapter draft revision conflict.", {"currentRevision": parent.revision})
            contract = self._get_contract(session, project.id, job.chapter_contract_id)
            self._assert_contract_fresh(session, project.id, contract)
            job.status = "revising"
            job.revision += 1
            job.updated_at = _now()
            contract_id = contract.id
            context_trace_id = parent.context_trace_id

        try:
            draft = self._store_draft(
                project.id,
                project.folder_path,
                job_id,
                contract_id,
                payload.content_markdown,
                None,
                context_trace_id,
                "manual",
                parent_id=payload.parent_draft_id,
            )
            extraction = self._extract_for_draft(project, draft["id"], request_id)
            self._validate_extraction(project, extraction["id"])
            self._run_quality_pipeline(project, job_id, draft["id"], request_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, job_id)
                for finding in session.scalars(select(QualityFinding).where(
                    QualityFinding.chapter_draft_id == payload.parent_draft_id,
                    QualityFinding.status == "open",
                )).all():
                    finding.status = "superseded"
                    finding.updated_at = _now()
                job.status = "human_review"
                job.error_code = None
                job.diagnostic_json = dumps({"manualRevisionReason": payload.reason}) if payload.reason else None
                job.revision += 1
                job.updated_at = _now()
                session.add(self.service._audit(
                    "chapter_job.manual_revision_created",
                    "chapter_job",
                    job.id,
                    {"draftId": draft["id"], "parentDraftId": payload.parent_draft_id, "reason": payload.reason, "requestId": request_id},
                    request_id,
                ))
                return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))
        except StoryError:
            self._return_revision_to_human_review(project.id, project.folder_path, job_id, "CHAPTER_MANUAL_REVISION_FAILED", {"parentDraftId": payload.parent_draft_id}, restore_round=False)
            raise
        except Exception as exc:
            self._return_revision_to_human_review(project.id, project.folder_path, job_id, "CHAPTER_MANUAL_REVISION_FAILED", {"errorType": type(exc).__name__}, restore_round=False)
            raise StoryError(500, "CHAPTER_MANUAL_REVISION_FAILED", "Manual chapter revision failed.") from exc

    def activate_chapter_draft(self, project_id: str, job_id: str, draft_id: str, payload: ChapterDraftActivateRequest, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            if job.revision != payload.expected_job_revision:
                raise StoryError(409, "CHAPTER_JOB_REVISION_CONFLICT", "Chapter job revision conflict.", {"currentRevision": job.revision})
            if job.status not in {"human_review", "failed", "interrupted"}:
                raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "Draft versions can only be restored while the job is awaiting review.")
            target = self._get_draft(session, project.id, draft_id)
            if target.chapter_job_id != job.id:
                raise StoryError(404, "CHAPTER_DRAFT_NOT_FOUND", "Chapter draft not found for this job.")
            if target.revision != payload.expected_draft_revision:
                raise StoryError(409, "CHAPTER_DRAFT_REVISION_CONFLICT", "Chapter draft revision conflict.", {"currentRevision": target.revision})
            if target.is_current:
                return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))
            current = self._current_draft(session, job.id)
            if current:
                current.is_current = False
                current.revision += 1
                current.updated_at = _now()
                session.flush()
            target.is_current = True
            target.revision += 1
            target.updated_at = _now()
            job.status = "human_review"
            job.error_code = None
            job.diagnostic_json = dumps({"restoredDraftId": target.id})
            job.revision += 1
            job.updated_at = _now()
            session.add(self.service._audit(
                "chapter_job.draft_activated",
                "chapter_job",
                job.id,
                {"draftId": target.id, "previousDraftId": current.id if current else None, "requestId": request_id},
                request_id,
            ))
            return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))

    def approve_chapter_job(self, project_id: str, job_id: str, payload: ChapterApproveRequest, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            phase7 = getattr(self.service, "phase7", None)
            if phase7 is not None:
                phase7.assert_current_automation_lease(session, project.id)
            job = self._get_job(session, project.id, job_id)
            if job.revision != payload.expected_job_revision:
                raise StoryError(409, "CHAPTER_JOB_REVISION_CONFLICT", "Chapter job revision conflict.", {"currentRevision": job.revision})
            if job.status == "approved":
                return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))
            if job.status != "human_review":
                raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "Only a chapter in human review can be approved.")
            draft = self._current_draft(session, job.id)
            if not draft:
                raise StoryError(409, "CHAPTER_DRAFT_EMPTY", "No draft is available for approval.")
            findings = session.scalars(select(QualityFinding).where(QualityFinding.chapter_draft_id == draft.id)).all()
            open_blocking = self._open_blocking_count(findings)
            extraction = session.scalar(select(ChapterExtraction).where(ChapterExtraction.chapter_draft_id == draft.id).order_by(ChapterExtraction.created_at.desc()))
            if not extraction or extraction.status != "validated":
                raise StoryError(409, "CHAPTER_EXTRACTION_INVALID", "Validated extraction is required before approval.")
            if payload.mode == "guarded_auto":
                runs = session.scalars(select(QualityRun).where(QualityRun.chapter_draft_id == draft.id)).all()
                succeeded_reviewers = {run.reviewer_role for run in runs if run.gate_type == "model" and run.status == "succeeded"}
                required_reviewers = {"continuity_reviewer", "story_editor", "style_reviewer"}
                deterministic_ok = any(run.gate_type == "deterministic" and run.status == "succeeded" for run in runs)
                accepted_blocking = sum(1 for item in findings if item.status == "accepted_risk" and item.severity in BLOCKING_SEVERITIES)
                if open_blocking or accepted_blocking or not deterministic_ok or succeeded_reviewers != required_reviewers:
                    raise StoryError(409, "CHAPTER_QUALITY_BLOCKED", "Guarded auto approval requires every quality gate to pass without blocking accepted risks.", {
                        "openBlockingCount": open_blocking,
                        "acceptedBlockingCount": accepted_blocking,
                        "missingReviewers": sorted(required_reviewers - succeeded_reviewers),
                    })
            if payload.mode == "manual" and any(item.status == "open" and item.severity == "blocker" for item in findings):
                raise StoryError(409, "CHAPTER_QUALITY_BLOCKED", "Open blocker findings prevent manual approval.", {"openBlockingCount": open_blocking})
            for other in session.scalars(select(ChapterDraft).where(ChapterDraft.chapter_job_id == job.id, ChapterDraft.id != draft.id, ChapterDraft.status == "approved")).all():
                other.status = "superseded"
                other.updated_at = _now()
            draft.status = "approved"
            draft.kind = "approved"
            draft.revision += 1
            draft.updated_at = _now()
            job.status = "approved"
            job.revision += 1
            job.updated_at = _now()
            session.add(self.service._audit("chapter_job.approved", "chapter_job", job.id, {"draftId": draft.id, "mode": payload.mode, "requestId": request_id}, request_id))
            return self._job_dict(job, session.get(ChapterContract, job.chapter_contract_id))

    def commit_chapter_job(self, project_id: str, job_id: str, payload: ChapterCommitRequest, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        committed: dict[str, Any]
        mirror: tuple[int, str] | None = None
        try:
            with self.service.db.project_write(project.id, project.folder_path) as session:
                phase7 = getattr(self.service, "phase7", None)
                if phase7 is not None:
                    phase7.assert_current_automation_lease(session, project.id)
                job = self._get_job(session, project.id, job_id)
                if job.status == "completed":
                    existing_commit = session.scalar(
                        select(ChapterCommit)
                        .join(ChapterDraft, ChapterDraft.id == ChapterCommit.approved_draft_id)
                        .where(ChapterDraft.chapter_job_id == job.id, ChapterCommit.is_current.is_(True))
                        .order_by(ChapterCommit.committed_at.desc())
                    )
                    if existing_commit:
                        return self._commit_dict(existing_commit)
                if job.revision != payload.expected_job_revision:
                    raise StoryError(409, "CHAPTER_COMMIT_CONFLICT", "Chapter job revision conflict.", {"currentRevision": job.revision})
                if job.status != "approved":
                    raise StoryError(409, "CHAPTER_JOB_NOT_RESUMABLE", "Only approved chapter jobs can be committed.")
                contract = self._get_contract(session, project.id, job.chapter_contract_id)
                if contract.status != "locked":
                    raise StoryError(409, "CHAPTER_CONTRACT_NOT_LOCKED", "Chapter contract is no longer locked.")
                self._assert_contract_fresh(session, project.id, contract)
                draft = self._current_draft(session, job.id)
                if not draft or draft.status != "approved":
                    raise StoryError(409, "CHAPTER_DRAFT_NOT_APPROVED", "Approved draft is required before commit.")
                findings = session.scalars(select(QualityFinding).where(QualityFinding.chapter_draft_id == draft.id)).all()
                open_blocking = self._open_blocking_count(findings)
                if open_blocking:
                    raise StoryError(409, "CHAPTER_QUALITY_BLOCKED", "Open blocker/error findings prevent commit.", {"openBlockingCount": open_blocking})
                extraction = session.scalar(select(ChapterExtraction).where(ChapterExtraction.chapter_draft_id == draft.id).order_by(ChapterExtraction.created_at.desc()))
                if not extraction or extraction.status != "validated":
                    raise StoryError(409, "CHAPTER_EXTRACTION_INVALID", "Validated extraction is required before commit.")
                extraction_payload = _safe_loads(extraction.payload_json, {})
                now = _now()
                source_id = f"chapter-{contract.chapter_number:04d}"
                previous_commit = session.scalar(select(ChapterCommit).where(
                    ChapterCommit.project_id == project.id,
                    ChapterCommit.chapter_number == contract.chapter_number,
                    ChapterCommit.is_current.is_(True),
                ))
                previous_version_number = session.scalar(
                    select(SourceVersion.version_number)
                    .where(SourceVersion.project_id == project.id, SourceVersion.source_id == source_id)
                    .order_by(SourceVersion.version_number.desc())
                ) or 0
                if previous_commit:
                    previous_source = session.get(SourceVersion, previous_commit.source_version_id)
                    if previous_source and previous_source.status == "official":
                        self.service.phase4._supersede_source_version_in_session(session, project.id, previous_source, now) if hasattr(self.service.phase4, "_supersede_source_version_in_session") else self._supersede_previous_source_inline(session, project.id, previous_source, now)
                    previous_commit.is_current = False
                    previous_commit.status = "superseded"
                version_number = previous_version_number + 1
                source = SourceVersion(
                    id=str(uuid4()),
                    project_id=project.id,
                    source_id=source_id,
                    version_number=version_number,
                    source_kind="chapter",
                    status="candidate",
                    checksum=stable_digest({"draft": draft.checksum, "extraction": extraction.checksum}),
                    summary=extraction_payload.get("summary") or contract.title,
                    payload_json=dumps(extraction_payload),
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(source)
                session.flush()
                self.service.phase4._validate_state_payload(session, project.id, extraction_payload)
                self.service.phase4._materialize_state_payload(session, project.id, extraction_payload, source.id, now)
                source.status = "official"
                source.revision += 1
                source.updated_at = now
                snapshot = self.service.phase4._create_state_snapshot(session, project.id, source.id, extraction_payload, now)
                quality_summary = self._quality_summary(findings)
                commit = ChapterCommit(
                    id=str(uuid4()),
                    project_id=project.id,
                    chapter_number=contract.chapter_number,
                    chapter_contract_id=contract.id,
                    approved_draft_id=draft.id,
                    source_version_id=source.id,
                    state_snapshot_id=snapshot.id,
                    quality_summary_json=dumps(quality_summary),
                    checksum=stable_digest({"draft": draft.checksum, "sourceVersionId": source.id, "quality": quality_summary}),
                    status="official",
                    is_current=True,
                    revision=1,
                    committed_at=now,
                    created_at=now,
                )
                session.add(commit)
                meta = session.get(ProjectMeta, project.id)
                if meta:
                    meta.current_chapter = max(meta.current_chapter, contract.chapter_number)
                    meta.updated_at = now
                job.status = "completed"
                job.revision += 1
                job.finished_at = now
                job.updated_at = now
                self.service.phase4._rebuild_retrieval_index(session, project.id, now)
                session.add(self.service._audit("chapter_job.committed", "chapter_job", job.id, {"chapterCommitId": commit.id, "sourceVersionId": source.id, "snapshotId": snapshot.id, "requestId": request_id}, request_id))
                session.flush()
                committed = self._commit_dict(commit)
                mirror = (contract.chapter_number, draft.content_markdown)
            if mirror:
                self._sync_catalog_chapter_safely(project, mirror[0])
            if mirror:
                self._mirror_chapter_markdown_safely(project.id, project.folder_path, mirror[0], mirror[1])
            return committed
        except StoryError as exc:
            if exc.code == "STATE_FACT_CONFLICT":
                with self.service.db.project_write(project.id, project.folder_path) as session:
                    job = session.get(ChapterJob, job_id)
                    if job:
                        job.status = "human_review"
                        job.error_code = "CHAPTER_STATE_CONFLICT"
                        job.updated_at = _now()
                    session.add(self.service._audit("chapter.state_conflict_detected", "chapter_job", job_id, {**exc.details, "requestId": request_id}, request_id))
                raise StoryError(409, "CHAPTER_STATE_CONFLICT", "Chapter state conflicts with current facts.", exc.details) from exc
            if exc.code in {"CHAPTER_COMMIT_CONFLICT", "CHAPTER_CONTEXT_STALE"}:
                with self.service.db.project_write(project.id, project.folder_path) as session:
                    job = session.get(ChapterJob, job_id)
                    if job:
                        job.status = "human_review"
                        job.error_code = exc.code
                        job.diagnostic_json = dumps(exc.details)
                        job.updated_at = _now()
                        job.revision += 1
            raise
        except Exception as exc:
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = session.get(ChapterJob, job_id)
                if job:
                    job.status = "human_review"
                    job.error_code = "CHAPTER_COMMIT_FAILED"
                    job.diagnostic_json = dumps({"errorType": type(exc).__name__})
                    job.updated_at = _now()
                    job.revision += 1
            raise StoryError(500, "CHAPTER_COMMIT_FAILED", "Chapter commit failed and was rolled back.") from exc

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
        phase7 = getattr(self.service, "phase7", None)
        if phase7 is not None:
            phase7.before_model_call(project.id, role, messages, model.id)
        if not provider.api_key_ref:
            raise StoryError(409, "MODEL_API_KEY_MISSING", "Provider API key is missing.", {"providerId": provider.id})
        try:
            api_key = self.service.secret_store.get_secret(provider.api_key_ref)
        except Exception as exc:
            raise StoryError(503, "CREDENTIAL_STORE_UNAVAILABLE", "Credential store is unavailable.", {"providerId": provider.id}) from exc
        if not api_key:
            raise StoryError(409, "MODEL_API_KEY_MISSING", "Provider API key is missing.", {"providerId": provider.id})
        run_id = str(uuid4())
        started = time.perf_counter()
        now = _now()
        automation_context = phase7.current_execution_context() if phase7 is not None else None
        with self.service.db.project_write(project.id, project.folder_path) as session:
            session.add(ModelRun(
                id=run_id,
                session_id=None,
                role=role,
                provider_id=provider.id,
                provider_name=provider.name,
                model_config_id=model.id,
                model_id=model.model_id,
                automation_run_id=automation_context[0] if automation_context else None,
                automation_run_item_id=automation_context[1] if automation_context else None,
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
            "max_tokens": min(model.max_output_tokens, {
                "fact_extractor": 4096,
                "continuity_reviewer": 3072,
                "story_editor": 3072,
                "style_reviewer": 3072,
            }.get(role, model.max_output_tokens)),
        }
        if response_json:
            request_payload["response_format"] = {"type": "json_object"}
        try:
            result = asyncio.run(client.complete_chat(request_payload))
        except ModelProviderError as exc:
            self._complete_model_run_failure(project.id, project.folder_path, run_id, exc.code, started, {"retryable": exc.retryable})
            raise
        except Exception as exc:
            self._complete_model_run_failure(project.id, project.folder_path, run_id, "MODEL_PROVIDER_ERROR", started, {"errorType": type(exc).__name__})
            raise StoryError(502, "MODEL_PROVIDER_ERROR", "Model provider call failed.") from exc
        duration = int((time.perf_counter() - started) * 1000)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            run = session.get(ModelRun, run_id)
            if run:
                run.status = "succeeded"
                run.prompt_tokens = result.prompt_tokens
                run.completion_tokens = result.completion_tokens
                run.total_tokens = result.total_tokens
                run.estimated_cost = (
                    ((result.prompt_tokens or 0) * (model.input_price_per_million or 0.0))
                    + ((result.completion_tokens or 0) * (model.output_price_per_million or 0.0))
                ) / 1_000_000
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
            for previous in session.scalars(select(ChapterDraft).where(ChapterDraft.chapter_job_id == job_id, ChapterDraft.is_current.is_(True))).all():
                previous.is_current = False
                previous.revision += 1
                previous.updated_at = now
            session.flush()
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
                is_current=True,
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
            current_state = [
                {"entity": entity_name, "fieldPath": field_path, "value": _safe_loads(value_json, None)}
                for entity_name, field_path, value_json in session.execute(
                    select(StoryEntity.canonical_name, StateFact.field_path, StateFact.value_json)
                    .join(StateFact, StateFact.entity_id == StoryEntity.id)
                    .where(
                        StoryEntity.project_id == project.id,
                        StoryEntity.status == "active",
                        StateFact.is_current.is_(True),
                    )
                    .order_by(StoryEntity.canonical_name.asc(), StateFact.field_path.asc())
                    .limit(80)
                ).all()
            ]
        base_user = {
            "chapterNumber": contract_payload["chapterNumber"],
            "chapterTitle": contract_payload["title"],
            "currentOfficialState": current_state,
            "chapterMarkdown": content,
        }
        # Each schema group is requested separately. Real-model acceptance
        # showed that a combined state payload could exhaust the JSON output
        # budget even when the model was asked for short arrays. A truncated
        # group is never materialized, so partial output cannot contaminate the
        # candidate extraction or official state.
        sections = [
            (
                "entities",
                (
                    "你是小说实体增量抽取器。只返回合法 JSON object，顶层只能有 entities。"
                    "最多 5 项；每项只用 canonicalName、entityTypeName、aliases、attributes。"
                    "entityTypeName 只能是 person、location、organization、item、ability、event、intel、foreshadow、time_point。"
                    "只列本章新增或状态事实会引用的实体；attributes 最多 4 个短字段且必须包含 name；每个字段值不超过 60 字。"
                ),
                ("entities",),
            ),
            (
                "facts",
                (
                    "你是小说状态事实增量抽取器。只返回合法 JSON object，顶层只能有 facts。"
                    "最多 6 项；每项只用 entity、fieldPath、value、confidence。"
                    "只列本章结束后仍成立的状态变化；修改 currentOfficialState 已有值时必须给 expectedCurrentValue。"
                    "不要复述背景设定，不要输出叙事总结，value 必须是简短标量或短数组，confidence 必须是 0 到 1 的 JSON 数字。"
                ),
                ("facts",),
            ),
            (
                "boundaries",
                (
                    "你是人物知识边界抽取器。只返回合法 JSON object，顶层只能有 boundaries。"
                    "最多 2 项；每项只用 entity 和 knowledge object，knowledge 最多 2 个字段、每个值不超过 80 字，"
                    "仅记录本章后该人物确实知道的新信息。不要 id、description、心理描写、叙事禁令或背景复述。"
                ),
                ("boundaries",),
            ),
            (
                "narrative",
                (
                    "你是小说事件与伏笔抽取器。只返回合法 JSON object，顶层只能有 events、foreshadows。"
                    "events 最多 3 项，每项只用 eventOrder、summary、participants，并合并连续动作。"
                    "foreshadows 最多 2 项，每项只用 code、label、status；status 只能是 planted、progressing、resolved。"
                    "requiredForeshadows 中的线索若已在本章出现，code 必须逐字使用契约给出的值，不得改名。"
                    "不要 id、description，不要复述设定或叙事禁令，所有摘要保持短句。"
                ),
                ("events", "foreshadows"),
            ),
        ]
        combined: dict[str, Any] = {"summary": contract_payload["title"]}
        last_error: Exception | None = None
        final_run_id: str | None = None
        for section_name, system_prompt, keys in sections:
            section_ok = False
            for attempt in range(2):
                compact_instruction = {
                    "entities": "entities 最多 2 项，每项 attributes 仅保留 name。",
                    "facts": "facts 最多 2 项，value 只用短字符串或短数组，confidence 必须是数字。",
                    "boundaries": "boundaries 最多 1 项，knowledge 只保留 1 个键和不超过 40 字的值。",
                    "narrative": "events 最多 2 项；foreshadows 只输出已经出现的 requiredForeshadows code。",
                }[section_name]
                repair = [] if attempt == 0 else [{
                    "role": "system",
                    "content": f"上次输出无效或过长。{compact_instruction} 只返回完整、精简的 JSON object。",
                }]
                try:
                    section_user = {**base_user, "section": section_name}
                    if section_name == "narrative":
                        section_user["requiredForeshadows"] = contract_payload["requiredForeshadows"]
                        section_user["requiredHooks"] = contract_payload["requiredHooks"]
                        section_user["completionConditions"] = contract_payload["completionConditions"]
                    text, final_run_id = self._complete_role_text(
                        project,
                        "fact_extractor",
                        request_id,
                        [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": dumps(section_user)},
                            *repair,
                        ],
                        response_json=True,
                    )
                    data = _json_object_from_text(text)
                    for key in keys:
                        value = data.get(key, [])
                        if not isinstance(value, list):
                            raise ValueError(f"{section_name}.{key} must be an array")
                        combined[key] = value
                    section_ok = True
                    break
                except (ValueError, json.JSONDecodeError) as exc:
                    last_error = exc
                    continue
                except ModelProviderError as exc:
                    last_error = exc
                    if exc.code == "content_truncated" and attempt == 0:
                        continue
                    raise
            if not section_ok:
                break
        else:
            payload = self._normalize_extraction_payload(contract_payload, combined)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                now = _now()
                row = ChapterExtraction(
                    id=str(uuid4()),
                    project_id=project.id,
                    chapter_draft_id=draft_id,
                    model_run_id=final_run_id,
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
        validation_error: StoryError | None = None
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
                validation_error = StoryError(422, "CHAPTER_EXTRACTION_INVALID", "Chapter extraction failed validation.", {"sourceCode": exc.code, **exc.details})
            else:
                extraction.status = "validated"
                extraction.validation_errors_json = "[]"
                extraction.updated_at = _now()
                session.flush()
                return self._extraction_dict(extraction)
        assert validation_error is not None
        raise validation_error

    def _normalize_extraction_payload(self, contract: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        entity_type_aliases = {
            "character": "person",
            "person": "person",
            "location": "location",
            "organization": "organization",
            "item": "item",
            "artifact": "item",
            "object": "item",
            "ability": "ability",
            "event": "event",
            "manifestation": "event",
            "intel": "intel",
            "concept": "intel",
            "foreshadow": "foreshadow",
            "time_point": "time_point",
        }
        entities: list[dict[str, Any]] = []
        known_names: set[str] = set()
        for raw in data.get("entities", []) if isinstance(data.get("entities"), list) else []:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("canonicalName") or raw.get("canonical_name") or raw.get("name") or "").strip()
            if not name or name in known_names:
                continue
            raw_type = str(raw.get("entityTypeName") or raw.get("entity_type_name") or raw.get("type") or "intel").strip().lower()
            entity_type = entity_type_aliases.get(raw_type, "intel")
            attributes = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {"name": name}
            attributes.setdefault("name", name)
            description = str(raw.get("description") or "").strip()
            if description and "description" not in attributes:
                attributes["description"] = description
            aliases = raw.get("aliases") if isinstance(raw.get("aliases"), list) else []
            entities.append({
                "canonicalName": name,
                "entityTypeName": entity_type,
                "aliases": [item for item in aliases if isinstance(item, str)],
                "attributes": attributes,
            })
            known_names.add(name)

        facts: list[dict[str, Any]] = []
        for raw in data.get("facts", []) if isinstance(data.get("facts"), list) else []:
            if not isinstance(raw, dict):
                continue
            state_changing = raw.get("stateChanging", raw.get("state_changing", True))
            if state_changing is False:
                continue
            entity = str(raw.get("entity") or raw.get("entityName") or raw.get("subject") or "").strip()
            field_path = str(raw.get("fieldPath") or raw.get("field_path") or raw.get("predicate") or "").strip()
            if not entity or not field_path or entity not in known_names:
                continue
            value = raw.get("value") if "value" in raw else raw.get("object")
            raw_confidence = raw.get("confidence", 1.0)
            if isinstance(raw_confidence, str):
                confidence_aliases = {"high": 0.9, "medium": 0.65, "low": 0.4}
                normalized_confidence = confidence_aliases.get(raw_confidence.strip().lower(), raw_confidence)
            else:
                normalized_confidence = raw_confidence
            try:
                confidence = float(normalized_confidence)
            except (TypeError, ValueError):
                # Confidence is model metadata, never a reason to discard an
                # otherwise valid state candidate. Use a conservative default
                # rather than allowing prose such as "high" to poison JSON.
                confidence = 0.7
            confidence = max(0.0, min(1.0, confidence))
            fact: dict[str, Any] = {
                "entity": entity,
                "fieldPath": field_path,
                "value": value,
                "confidence": confidence,
            }
            if "expectedCurrentValue" in raw and raw.get("expectedCurrentValue") is not True:
                fact["expectedCurrentValue"] = raw.get("expectedCurrentValue")
            elif "expected_current_value" in raw and raw.get("expected_current_value") is not True:
                fact["expectedCurrentValue"] = raw.get("expected_current_value")
            facts.append(fact)

        events: list[dict[str, Any]] = []
        for index, raw in enumerate(data.get("events", []) if isinstance(data.get("events"), list) else [], start=1):
            if not isinstance(raw, dict):
                continue
            summary = str(raw.get("summary") or raw.get("description") or "").strip()
            if not summary:
                continue
            order = raw.get("eventOrder", raw.get("event_order", raw.get("sequence", index)))
            try:
                order = int(order)
            except (TypeError, ValueError):
                order = index
            participants = raw.get("participants") if isinstance(raw.get("participants"), list) else []
            events.append({"eventOrder": order, "summary": summary, "participants": [item for item in participants if isinstance(item, str)]})

        foreshadows: list[dict[str, Any]] = []
        for raw in data.get("foreshadows", []) if isinstance(data.get("foreshadows"), list) else []:
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or raw.get("name") or raw.get("description") or "").strip()
            if not label:
                continue
            code = str(raw.get("code") or raw.get("id") or stable_digest(label)[:12]).strip()
            status = str(raw.get("status") or "planted")
            if status not in {"planted", "progressing", "resolved"}:
                status = "planted"
            foreshadows.append({"code": code, "label": label, "status": status})

        boundaries: list[dict[str, Any]] = []
        for raw in data.get("boundaries", []) if isinstance(data.get("boundaries"), list) else []:
            if not isinstance(raw, dict):
                continue
            entity = str(raw.get("entity") or raw.get("entityName") or "").strip()
            knowledge = raw.get("knowledge")
            if entity in known_names and isinstance(knowledge, dict):
                boundaries.append({"entity": entity, "knowledge": knowledge})
        return {
            "sourceId": f"chapter-{contract['chapterNumber']:04d}",
            "versionNumber": 1,
            "sourceKind": "chapter",
            "summary": str(data.get("summary") or contract["title"]),
            "entities": entities,
            "facts": facts,
            "events": events,
            "foreshadows": foreshadows,
            "boundaries": boundaries,
        }

    def _run_quality_pipeline(self, project: Any, job_id: str, draft_id: str, request_id: str) -> None:
        self._raise_if_cancel_requested(project, job_id)
        if not self._quality_stage_succeeded(project, draft_id, "deterministic", None):
            self._run_deterministic_quality(project, job_id, draft_id, request_id)
        for role in ("continuity_reviewer", "story_editor", "style_reviewer"):
            self._raise_if_cancel_requested(project, job_id)
            if self._quality_stage_succeeded(project, draft_id, "model", role):
                continue
            try:
                self._run_model_quality(project, job_id, draft_id, role, request_id)
            except StoryError as exc:
                if exc.code != "CHAPTER_MODEL_ROLE_NOT_CONFIGURED":
                    raise
                self._record_missing_reviewer(project, job_id, draft_id, role, request_id)
        self._raise_if_cancel_requested(project, job_id)

    def _quality_stage_succeeded(self, project: Any, draft_id: str, gate_type: str, role: str | None) -> bool:
        with self.service.db.project(project.id, project.folder_path) as session:
            query = select(QualityRun.id).where(
                QualityRun.project_id == project.id,
                QualityRun.chapter_draft_id == draft_id,
                QualityRun.gate_type == gate_type,
                QualityRun.status == "succeeded",
            )
            if role is None:
                query = query.where(QualityRun.reviewer_role.is_(None))
            else:
                query = query.where(QualityRun.reviewer_role == role)
            return session.scalar(query.limit(1)) is not None

    def _run_deterministic_quality(self, project: Any, job_id: str, draft_id: str, request_id: str, *, replace_previous: bool = False) -> None:
        with self.service.db.project_write(project.id, project.folder_path) as session:
            draft = self._get_draft(session, project.id, draft_id)
            contract = self._get_contract(session, project.id, draft.chapter_contract_id)
            extraction = session.scalar(select(ChapterExtraction).where(ChapterExtraction.chapter_draft_id == draft_id).order_by(ChapterExtraction.created_at.desc()))
            now = _now()
            if replace_previous:
                # Preserve the historical finding and its original run, but
                # remove it from the current gate before applying the updated
                # deterministic rules.  Matching findings are reopened below.
                deterministic_finding_ids = select(QualityFinding.id).join(
                    QualityRun, QualityRun.id == QualityFinding.quality_run_id
                ).where(
                    QualityFinding.chapter_draft_id == draft_id,
                    QualityFinding.status == "open",
                    QualityRun.gate_type == "deterministic",
                )
                for finding in session.scalars(select(QualityFinding).where(QualityFinding.id.in_(deterministic_finding_ids))).all():
                    finding.status = "superseded"
                    finding.updated_at = now
            run = QualityRun(
                id=str(uuid4()),
                project_id=project.id,
                chapter_job_id=job_id,
                chapter_draft_id=draft_id,
                gate_type="deterministic",
                reviewer_role=None,
                status="succeeded",
                summary_json="{}",
                created_at=now,
                completed_at=now,
            )
            session.add(run)
            findings: list[dict[str, Any]] = []
            content = draft.content_markdown.strip()
            if not content:
                findings.append(self._finding_payload("CHAPTER_DRAFT_EMPTY", "blocker", "mechanical", "Chapter draft is empty.", [], {}, "Generate a non-empty chapter body."))
            if re.search(r"TODO|待补|\[[^\]]*(?:xxx|TODO)[^\]]*\]", content, flags=re.I):
                findings.append(self._finding_payload("PLACEHOLDER_TEXT", "error", "mechanical", "Draft contains placeholder text.", [], {}, "Remove placeholders and complete the scene."))
            if draft.word_count < contract.target_words_min:
                findings.append(self._finding_payload("WORD_COUNT_UNDER_TARGET", "warning", "pace", "Draft is shorter than the contract target.", [{"wordCount": draft.word_count, "target": contract.target_words_min}], {}, "Expand required scene beats."))
            if draft.word_count > contract.target_words_max:
                findings.append(self._finding_payload("WORD_COUNT_OVER_TARGET", "warning", "pace", "Draft is longer than the contract target.", [{"wordCount": draft.word_count, "target": contract.target_words_max}], {}, "Tighten pacing."))
            lowered = content.lower()
            forbidden = _safe_loads(contract.forbidden_scope_json, {})
            for keyword in forbidden.get("futureKeywords", []) if isinstance(forbidden, dict) else []:
                if isinstance(keyword, str) and keyword and keyword.lower() in lowered:
                    findings.append(self._finding_payload("SCOPE_FUTURE_NODE_CONSUMED", "blocker", "scope", "Draft appears to consume a future plan node.", [keyword], {}, "Remove future-node payoff from this chapter."))
            for condition in _safe_loads(contract.completion_conditions_json, []):
                if isinstance(condition, str) and condition.strip() and not _requirement_evident(condition, content):
                    findings.append(self._finding_payload("REQUIRED_CONDITION_MISSING", "error", "contract", "A required completion condition is not evident in the draft.", [condition], {}, "Add clear evidence for this completion condition."))
            if not extraction or extraction.status != "validated":
                findings.append(self._finding_payload("CHAPTER_EXTRACTION_INVALID", "blocker", "state", "Validated extraction is missing.", [], {}, "Run fact extraction and validation."))
                extraction_payload: dict[str, Any] = {}
            else:
                extraction_payload = _safe_loads(extraction.payload_json, {})
                if not extraction_payload.get("events"):
                    findings.append(self._finding_payload("CHAPTER_EXTRACTION_EMPTY_EVENTS", "error", "state", "Extraction does not include any story events.", [], {}, "Extract at least one event from the chapter."))

            extracted_entities = {
                str(item.get("canonicalName") or item.get("canonical_name") or "").strip().lower()
                for item in extraction_payload.get("entities", [])
                if isinstance(item, dict)
            }
            extracted_participants = {
                str(participant).strip().lower()
                for event in extraction_payload.get("events", [])
                if isinstance(event, dict)
                for participant in event.get("participants", [])
                if isinstance(participant, str)
            }
            for character in _safe_loads(contract.required_characters_json, []):
                if isinstance(character, str) and character.strip() and not _canonical_reference_evident(character, lowered, extracted_entities | extracted_participants):
                    findings.append(self._finding_payload("REQUIRED_CHARACTER_MISSING", "error", "contract", "A required character is missing from this chapter.", [character], {}, "Add the required character or revise the contract."))
            extracted_foreshadows = {
                str(value).strip().lower()
                for item in extraction_payload.get("foreshadows", [])
                if isinstance(item, dict)
                for value in (item.get("code"), item.get("label"), item.get("name"))
                if isinstance(value, str) and value.strip()
            }
            for required in _safe_loads(contract.required_foreshadows_json, []):
                if isinstance(required, str) and required.strip() and not _requirement_evident(required, content, extracted_foreshadows):
                    findings.append(self._finding_payload("REQUIRED_FORESHADOW_MISSING", "error", "foreshadow", "A required foreshadow is not present in the chapter or extraction.", [required], {}, "Plant or advance the required foreshadow, or revise the contract."))

            forbidden_scope = forbidden if isinstance(forbidden, dict) else {}
            for key, rule_code, label in (
                ("forbiddenCharacters", "FORBIDDEN_CHARACTER_EARLY", "character"),
                ("forbiddenAbilities", "FORBIDDEN_ABILITY_EARLY", "ability"),
                ("forbiddenItems", "FORBIDDEN_ITEM_EARLY", "item"),
            ):
                for value in forbidden_scope.get(key, []) if isinstance(forbidden_scope.get(key), list) else []:
                    if isinstance(value, str) and value.strip() and value.lower() in lowered:
                        findings.append(self._finding_payload(rule_code, "blocker", "scope", f"A forbidden {label} appears before its allowed chapter.", [value], {}, f"Remove the early {label} or revise the locked contract."))

            pace_budget = _safe_loads(contract.allowed_scope_json, {}).get("paceBudget", {})
            max_events = pace_budget.get("maxMajorEvents") if isinstance(pace_budget, dict) else None
            if isinstance(max_events, int) and not isinstance(max_events, bool) and len(extraction_payload.get("events", [])) > max_events:
                findings.append(self._finding_payload("PACE_MAJOR_EVENT_OVERFLOW", "blocker", "pace", "The extraction contains more major events than the chapter pace budget allows.", [{"eventCount": len(extraction_payload.get("events", [])), "maximum": max_events}], {}, "Move excess major events to later chapters."))

            for fact in extraction_payload.get("facts", []):
                if not isinstance(fact, dict):
                    continue
                entity_name = str(fact.get("entity") or fact.get("entityName") or "").strip()
                field_path = str(fact.get("fieldPath") or fact.get("field_path") or "").strip()
                entity = session.scalar(select(StoryEntity).where(StoryEntity.project_id == project.id, StoryEntity.canonical_name == entity_name, StoryEntity.status == "active"))
                current = session.scalar(select(StateFact).where(
                    StateFact.project_id == project.id,
                    StateFact.entity_id == entity.id,
                    StateFact.field_path == field_path,
                    StateFact.is_current.is_(True),
                )) if entity and field_path else None
                new_value = fact.get("value")
                if not current or _safe_loads(current.value_json, None) == new_value:
                    continue
                expected_present = "expectedCurrentValue" in fact or "expected_current_value" in fact
                expected_value = fact.get("expectedCurrentValue") if "expectedCurrentValue" in fact else fact.get("expected_current_value")
                if not expected_present or expected_value != _safe_loads(current.value_json, None):
                    findings.append(self._finding_payload("CHAPTER_STATE_CONFLICT", "blocker", "state", "A changed fact is missing the correct expectedCurrentValue.", [{"entity": entity_name, "fieldPath": field_path, "currentValue": _safe_loads(current.value_json, None)}], {}, "Regenerate extraction with the exact current value or resolve the conflict manually."))

            for foreshadow in extraction_payload.get("foreshadows", []):
                if not isinstance(foreshadow, dict) or str(foreshadow.get("status") or "") != "resolved":
                    continue
                code = str(foreshadow.get("code") or "").strip()
                existing = session.scalar(select(Foreshadow).where(Foreshadow.project_id == project.id, Foreshadow.code == code, Foreshadow.status != "superseded")) if code else None
                earliest = foreshadow.get("earliestChapter") or foreshadow.get("earliest_chapter") or (existing.earliest_chapter if existing else None)
                latest = foreshadow.get("latestChapter") or foreshadow.get("latest_chapter") or (existing.latest_chapter if existing else None)
                if (isinstance(earliest, int) and contract.chapter_number < earliest) or (isinstance(latest, int) and contract.chapter_number > latest):
                    findings.append(self._finding_payload("FORESHADOW_WINDOW_VIOLATION", "blocker", "foreshadow", "A foreshadow is resolved outside its allowed chapter window.", [{"code": code, "earliestChapter": earliest, "latestChapter": latest, "chapterNumber": contract.chapter_number}], {}, "Move the payoff into its allowed window or revise Canon/contract explicitly."))
            for payload in findings:
                self._add_finding(session, project.id, run.id, draft_id, payload, now)
            run.summary_json = dumps({"findingCount": len(findings), "blockingCount": sum(1 for item in findings if item["severity"] in BLOCKING_SEVERITIES)})

    def _run_model_quality(self, project: Any, job_id: str, draft_id: str, role: str, request_id: str) -> None:
        with self.service.db.project(project.id, project.folder_path) as session:
            draft = self._get_draft(session, project.id, draft_id)
            contract = self._get_contract(session, project.id, draft.chapter_contract_id)
            contract_data = self._contract_dict(contract)
            forbidden_scope = contract_data["forbiddenScope"]
            # Reviewers need the boundary, not the complete serialized future
            # plan. Sending every downstream node wastes context and can make a
            # concise JSON review hit the output limit on real providers.
            compact_must_not_advance = []
            for item in forbidden_scope.get("mustNotAdvance", []):
                if isinstance(item, dict):
                    compact_must_not_advance.append({
                        key: item.get(key)
                        for key in ("id", "title", "rangeMin", "targetChapter", "rangeMax")
                        if item.get(key) is not None
                    })
                else:
                    compact_must_not_advance.append(item)
            compact_forbidden_scope = {
                "mustNotAdvance": compact_must_not_advance,
                "mustNotComplete": forbidden_scope.get("mustNotComplete", []),
                "futureKeywords": forbidden_scope.get("futureKeywords", []),
            }
            prompt = {
                "role": role,
                "chapterContract": {
                    "chapterNumber": contract_data["chapterNumber"],
                    "title": contract_data["title"],
                    "objective": contract_data["objective"],
                    "allowedScope": contract_data["allowedScope"],
                    "forbiddenScope": compact_forbidden_scope,
                    "requiredCharacters": contract_data["requiredCharacters"],
                    "requiredForeshadows": contract_data["requiredForeshadows"],
                    "requiredHooks": contract_data["requiredHooks"],
                    "completionConditions": contract_data["completionConditions"],
                    "targetWordsMin": contract_data["targetWordsMin"],
                    "targetWordsMax": contract_data["targetWordsMax"],
                    "pace": contract_data["pace"],
                },
                "chapterDraft": {"contentMarkdown": draft.content_markdown, "wordCount": draft.word_count},
                "requiredOutput": {"findings": [{"ruleCode": "string", "severity": "info|warning|error|blocker", "category": "string", "message": "string", "evidence": [], "location": {}, "suggestedFix": "string"}]},
            }
        base_messages = [
            {"role": "system", "content": (
                "你是 Story Agent 的专项审稿人。只返回合法 JSON object，不改写正文。"
                "只报告确有证据的问题，最多 5 条；没有问题时返回 {\"findings\":[]}，不要输出通过项或长篇解释。"
                "evidence 只放必要短句，location 保持简短，不得降低确定性 blocker。"
            )},
            {"role": "user", "content": dumps(prompt)},
        ]
        for attempt in range(2):
            retry_instruction = [] if attempt == 0 else [{
                "role": "system",
                "content": (
                    "上次输出被截断。最多返回 3 条 findings；每条 evidence 最多 2 个短句，"
                    "message 与 suggestedFix 各不超过 60 字。只输出完整 JSON object。"
                ),
            }]
            try:
                text, run_id = self._complete_role_text(
                    project,
                    role,
                    request_id,
                    [*base_messages, *retry_instruction],
                    response_json=True,
                )
                break
            except ModelProviderError as exc:
                if exc.code == "content_truncated" and attempt == 0:
                    continue
                raise
        try:
            data = _json_object_from_text(text)
            raw_findings = data.get("findings", [])
            if not isinstance(raw_findings, list):
                raw_findings = []
        except (ValueError, json.JSONDecodeError):
            raw_findings = [self._finding_payload("MODEL_REVIEW_INVALID_JSON", "error", "review", f"{role} returned invalid JSON.", [], {}, "Retry model review or inspect role output.")]
        with self.service.db.project_write(project.id, project.folder_path) as session:
            now = _now()
            run = QualityRun(
                id=str(uuid4()),
                project_id=project.id,
                chapter_job_id=job_id,
                chapter_draft_id=draft_id,
                gate_type="model",
                reviewer_role=role,
                model_run_id=run_id,
                status="succeeded",
                summary_json="{}",
                created_at=now,
                completed_at=now,
            )
            session.add(run)
            count = 0
            blocking = 0
            for item in raw_findings:
                if not isinstance(item, dict):
                    continue
                payload = self._coerce_model_finding(item)
                self._add_finding(session, project.id, run.id, draft_id, payload, now)
                count += 1
                if payload["severity"] in BLOCKING_SEVERITIES:
                    blocking += 1
            run.summary_json = dumps({"findingCount": count, "blockingCount": blocking})

    def _record_missing_reviewer(self, project: Any, job_id: str, draft_id: str, role: str, request_id: str) -> None:
        with self.service.db.project_write(project.id, project.folder_path) as session:
            now = _now()
            run = QualityRun(
                id=str(uuid4()),
                project_id=project.id,
                chapter_job_id=job_id,
                chapter_draft_id=draft_id,
                gate_type="model",
                reviewer_role=role,
                model_run_id=None,
                status="failed",
                summary_json=dumps({"errorCode": "CHAPTER_MODEL_ROLE_NOT_CONFIGURED"}),
                created_at=now,
                completed_at=now,
            )
            session.add(run)
            self._add_finding(session, project.id, run.id, draft_id, self._finding_payload(
                "CHAPTER_MODEL_ROLE_NOT_CONFIGURED",
                "error",
                "review",
                f"Required reviewer role is not configured: {role}.",
                [{"role": role}],
                {},
                "Bind a model for this reviewer role or accept the risk manually.",
            ), now)
            session.add(self.service._audit("quality.reviewer_missing", "chapter_job", job_id, {"role": role, "requestId": request_id}, request_id))

    def _finding_payload(self, rule_code: str, severity: str, category: str, message: str, evidence: list[Any], location: dict[str, Any], suggested_fix: str) -> dict[str, Any]:
        return {
            "ruleCode": rule_code,
            "severity": severity,
            "category": category,
            "message": message,
            "evidence": evidence,
            "location": location,
            "suggestedFix": suggested_fix,
        }

    def _coerce_model_finding(self, item: dict[str, Any]) -> dict[str, Any]:
        severity = str(item.get("severity") or "warning")
        if severity not in {"info", "warning", "error", "blocker"}:
            severity = "warning"
        return self._finding_payload(
            str(item.get("ruleCode") or item.get("rule_code") or "MODEL_REVIEW_FINDING")[:120],
            severity,
            str(item.get("category") or "review")[:80],
            str(item.get("message") or "Model reviewer reported an issue."),
            item.get("evidence") if isinstance(item.get("evidence"), list) else [],
            item.get("location") if isinstance(item.get("location"), dict) else {},
            str(item.get("suggestedFix") or item.get("suggested_fix") or ""),
        )

    def _add_finding(self, session: Session, project_id: str, run_id: str, draft_id: str, payload: dict[str, Any], now: datetime) -> None:
        fingerprint = stable_digest({
            "draftId": draft_id,
            "ruleCode": payload["ruleCode"],
            "evidence": payload["evidence"],
            "location": payload["location"],
        })
        existing = session.scalar(select(QualityFinding).where(QualityFinding.chapter_draft_id == draft_id, QualityFinding.fingerprint == fingerprint))
        if existing:
            existing.quality_run_id = run_id
            if existing.status == "superseded":
                existing.severity = payload["severity"]
                existing.category = payload["category"]
                existing.message = payload["message"]
                existing.evidence_json = dumps(payload["evidence"])
                existing.location_json = dumps(payload["location"])
                existing.suggested_fix = payload["suggestedFix"]
                existing.status = "open"
            existing.updated_at = now
            return
        session.add(QualityFinding(
            id=str(uuid4()),
            project_id=project_id,
            quality_run_id=run_id,
            chapter_draft_id=draft_id,
            rule_code=payload["ruleCode"],
            severity=payload["severity"],
            category=payload["category"],
            message=payload["message"],
            evidence_json=dumps(payload["evidence"]),
            location_json=dumps(payload["location"]),
            suggested_fix=payload["suggestedFix"],
            fingerprint=fingerprint,
            status="open",
            created_at=now,
            updated_at=now,
        ))

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

    def _chapter_beat(self, node: PlanNode | None, chapter_number: int) -> dict[str, Any] | None:
        if not node:
            return None
        beats = _safe_loads(node.chapter_beats_json, [])
        if not isinstance(beats, list):
            return None
        for beat in beats:
            if not isinstance(beat, dict):
                continue
            value = beat.get("chapterNumber", beat.get("chapter_number"))
            if value == chapter_number:
                return beat
        return None

    def _beat_strings(self, beat: dict[str, Any], *keys: str) -> list[str]:
        for key in keys:
            value = beat.get(key)
            if isinstance(value, list):
                return [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return []

    def _current_canon_digest(self, session: Session) -> str:
        locked_docs = session.scalars(select(CanonDocument).where(CanonDocument.status == "locked").order_by(CanonDocument.id.asc())).all()
        payload: list[dict[str, Any]] = [
            {"kind": "document", "id": doc.id, "revision": doc.revision, "checksum": stable_digest(doc.content_markdown)}
            for doc in locked_docs
        ]
        for kind, model in (
            ("entity_type", CanonEntityType),
            ("entity", CanonEntity),
            ("relation", CanonRelation),
            ("rule", CanonRule),
        ):
            for item in session.scalars(select(model).where(model.status == "locked").order_by(model.id.asc())).all():
                payload.append({"kind": kind, "id": item.id, "revision": item.revision})
        return stable_digest(payload)

    def _latest_official_snapshot_id(self, session: Session, project_id: str) -> str | None:
        return session.scalar(
            select(StateSnapshot.id)
            .join(SourceVersion, SourceVersion.id == StateSnapshot.source_version_id)
            .where(StateSnapshot.project_id == project_id, SourceVersion.status == "official")
            .order_by(StateSnapshot.snapshot_number.desc(), StateSnapshot.created_at.desc())
        )

    def _assert_contract_fresh(self, session: Session, project_id: str, contract: ChapterContract) -> None:
        if self._current_canon_digest(session) != contract.canon_revision_digest:
            raise StoryError(409, "CHAPTER_CONTEXT_STALE", "Locked Canon changed after the chapter contract was derived.", {"reason": "canon_revision_changed"})
        if self._latest_official_snapshot_id(session, project_id) != contract.state_snapshot_id:
            raise StoryError(409, "CHAPTER_CONTEXT_STALE", "Official story state changed after the chapter contract was derived.", {"reason": "state_snapshot_changed"})
        if contract.plan_node_id:
            node = session.get(PlanNode, contract.plan_node_id)
            if not node or node.revision != contract.plan_node_revision:
                raise StoryError(409, "CHAPTER_CONTEXT_STALE", "Plan node changed after the chapter contract was derived.", {"reason": "plan_node_changed"})

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
        current = session.scalar(select(ChapterDraft).where(
            ChapterDraft.chapter_job_id == job_id,
            ChapterDraft.is_current.is_(True),
        ))
        if current:
            return current
        return session.scalar(select(ChapterDraft).where(ChapterDraft.chapter_job_id == job_id).order_by(ChapterDraft.version_number.desc()))

    def _raise_if_cancel_requested(self, project: Any, job_id: str) -> None:
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, job_id)
            if job.status != "cancel_requested":
                return
            now = _now()
            job.status = "cancelled"
            job.error_code = "cancelled"
            job.finished_at = now
            job.updated_at = now
            job.revision += 1
        raise StoryError(409, "CHAPTER_JOB_CANCELLED", "Chapter job was cancelled.")

    def _fail_job(self, project_id: str, folder_path: str, job_id: str, error_code: str, diagnostic: dict[str, Any]) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            job = session.get(ChapterJob, job_id)
            if job:
                if job.status in {"cancel_requested", "cancelled"}:
                    job.status = "cancelled"
                    job.error_code = "cancelled"
                    job.finished_at = _now()
                    job.updated_at = _now()
                    job.revision += 1
                    return
                job.status = "failed"
                job.error_code = error_code
                job.diagnostic_json = dumps(diagnostic)
                job.finished_at = _now()
                job.updated_at = _now()
                job.revision += 1

    def _return_revision_to_human_review(self, project_id: str, folder_path: str, job_id: str, error_code: str, diagnostic: dict[str, Any], *, restore_round: bool) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            job = session.get(ChapterJob, job_id)
            if not job:
                return
            job.status = "human_review"
            job.error_code = error_code
            job.diagnostic_json = dumps(diagnostic)
            if restore_round:
                job.current_revision_round = max(0, job.current_revision_round - 1)
            job.updated_at = _now()
            job.revision += 1

    def _writer_messages(self, contract: dict[str, Any], context: dict[str, Any], author_note: str) -> list[dict[str, str]]:
        minimum = int(contract.get("targetWordsMin") or 1500)
        maximum = int(contract.get("targetWordsMax") or 3000)
        return [
            {"role": "system", "content": (
                "你是 Story Agent 的中文小说作者。只输出本章中文 Markdown 正文，不输出 JSON、创作说明或未来章节摘要。"
                f"正文必须控制在 {minimum}—{maximum} 个汉字/单词计数内，宁可接近中间值，也不得超出上限。"
                "必须在自然叙事中明确完成 chapterContract.completionConditions，使用姓名让 requiredCharacters 实际出场，"
                "并在结尾落实 requiredHooks；requiredForeshadows 只允许埋设或推进，不得提前揭晓。"
                "严格遵守 forbiddenScope，不得完成后续故事弧、提前升级、揭示禁揭真相或改变 Canon。"
                "巡夜灯等异常物品只能按既定规则和代价生效。写完前自行核对上述边界，但不要输出核对过程。"
            )},
            {"role": "user", "content": dumps({"chapterContract": contract, "contextPackage": context, "authorNote": author_note})},
        ]

    def _revision_messages(self, contract: dict[str, Any], draft: dict[str, Any], findings: list[dict[str, Any]], reason: str) -> list[dict[str, str]]:
        minimum = int(contract.get("targetWordsMin") or 1500)
        maximum = int(contract.get("targetWordsMax") or 3000)
        return [
            {"role": "system", "content": (
                "你是 Story Agent 的中文小说修订者。只返回合法 JSON object，唯一正文键为 contentMarkdown。"
                f"修订后的完整正文必须在 {minimum}—{maximum} 个汉字/单词计数内，禁止为压缩问题把正文缩到下限以下。"
                "逐项解决 openFindings 和 reason，但不得改变 Canon、提前推进后续章节、增加未授权能力或直接修改故事状态。"
                "输出前自行核对人物、完成条件、钩子、伏笔、禁写边界和字数，但不要输出核对过程。"
            )},
            {"role": "user", "content": dumps({
                "chapterContract": contract,
                "currentDraft": draft,
                "openFindings": findings,
                "reason": reason,
                "requiredOutput": {"contentMarkdown": "revised full chapter markdown"},
            })},
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
            "isCurrent": item.is_current,
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

    def _quality_run_dict(self, item: QualityRun, findings: list[QualityFinding]) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "chapterJobId": item.chapter_job_id,
            "chapterDraftId": item.chapter_draft_id,
            "gateType": item.gate_type,
            "reviewerRole": item.reviewer_role,
            "modelRunId": item.model_run_id,
            "status": item.status,
            "summary": _safe_loads(item.summary_json, {}),
            "createdAt": item.created_at,
            "completedAt": item.completed_at,
            "findings": [self._finding_dict(finding) for finding in findings],
        }

    def _quality_summary(self, findings: list[QualityFinding]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in findings:
            key = f"{item.status}:{item.severity}"
            counts[key] = counts.get(key, 0) + 1
        return {"counts": counts, "acceptedRiskCount": sum(1 for item in findings if item.status == "accepted_risk")}

    def _commit_dict(self, item: ChapterCommit) -> dict[str, Any]:
        return {
            "id": item.id,
            "projectId": item.project_id,
            "chapterNumber": item.chapter_number,
            "chapterContractId": item.chapter_contract_id,
            "approvedDraftId": item.approved_draft_id,
            "sourceVersionId": item.source_version_id,
            "stateSnapshotId": item.state_snapshot_id,
            "qualitySummary": _safe_loads(item.quality_summary_json, {}),
            "checksum": item.checksum,
            "status": item.status,
            "isCurrent": item.is_current,
            "revision": item.revision,
            "committedAt": item.committed_at,
            "createdAt": item.created_at,
        }

    def _sync_catalog_chapter_safely(self, project: Any, chapter_number: int) -> None:
        try:
            with self.service.db.catalog() as session:
                catalog = session.get(type(project), project.id)
                if catalog:
                    catalog.current_chapter = max(catalog.current_chapter, chapter_number)
                    catalog.updated_at = utc_now()
                    session.commit()
        except Exception as exc:
            with self.service.db.project_write(project.id, project.folder_path) as session:
                session.add(self.service._audit(
                    "chapter.catalog_sync_failed",
                    "chapter",
                    f"chapter-{chapter_number:04d}",
                    {"errorType": type(exc).__name__, "rebuildRequired": True},
                    str(uuid4()),
                ))

    def _mirror_chapter_markdown_safely(self, project_id: str, folder_path: str, chapter_number: int, content: str) -> None:
        path = Path(folder_path) / "manuscripts" / f"chapter-{chapter_number:04d}.md"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(content, encoding="utf-8")
            temp.replace(path)
        except OSError as exc:
            with self.service.db.project_write(project_id, folder_path) as session:
                session.add(self.service._audit(
                    "chapter.mirror_failed",
                    "chapter",
                    f"chapter-{chapter_number:04d}",
                    {"errorType": type(exc).__name__, "rebuildRequired": True},
                    str(uuid4()),
                ))

    def _supersede_previous_source_inline(self, session: Session, project_id: str, source_version: SourceVersion, now: datetime) -> None:
        source_version.status = "superseded"
        source_version.revision += 1
        source_version.updated_at = now
        affected_fact_keys: set[tuple[str, str]] = set()
        for fact in session.scalars(select(StateFact).where(StateFact.source_version_id == source_version.id)).all():
            affected_fact_keys.add((fact.entity_id, fact.field_path))
        for model in (StateFact, StateDelta, Foreshadow, KnowledgeBoundary):
            for row in session.scalars(select(model).where(getattr(model, "source_version_id") == source_version.id)).all():
                if hasattr(row, "status"):
                    row.status = "superseded"
                if hasattr(row, "is_current"):
                    row.is_current = False
                if hasattr(row, "valid_to") and getattr(row, "valid_to") is None:
                    row.valid_to = now
                if hasattr(row, "updated_at"):
                    row.updated_at = now
        for entity_id, field_path in affected_fact_keys:
            previous = session.scalar(
                select(StateFact)
                .join(SourceVersion, SourceVersion.id == StateFact.source_version_id)
                .where(
                    StateFact.project_id == project_id,
                    StateFact.entity_id == entity_id,
                    StateFact.field_path == field_path,
                    StateFact.source_version_id != source_version.id,
                    SourceVersion.status == "official",
                )
                .order_by(StateFact.valid_from.desc(), StateFact.created_at.desc())
            )
            if previous:
                previous.is_current = True
                previous.valid_to = None
                previous.updated_at = now
        for entity in session.scalars(select(StoryEntity).where(StoryEntity.source_version_id == source_version.id)).all():
            has_official_fact = session.scalar(
                select(StateFact.id)
                .join(SourceVersion, SourceVersion.id == StateFact.source_version_id)
                .where(StateFact.entity_id == entity.id, SourceVersion.status == "official")
                .limit(1)
            )
            if not has_official_fact:
                entity.status = "superseded"
                entity.updated_at = now

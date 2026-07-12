from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import Settings
from .database import DatabaseManager
from .models import (
    AgentMessage,
    AgentSession,
    AuditEvent,
    CatalogProject,
    ChangeOperation,
    ChangeProposal,
    Plan,
    PlanNode,
    ProjectMeta,
    ProposalImpact,
    StoryMarker,
    utc_now,
)
from .schemas import AgentMessageCreate, PlanNodeUpdate, ProjectCreate, ProjectUpdate, ProposalApply, ProposalReject


class StoryError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str) -> Any:
    return json.loads(value or "null")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    return slug[:60] or "story"


class StoryService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = DatabaseManager(settings)

    def close(self) -> None:
        self.db.dispose()

    def initialize(self) -> None:
        if self.settings.seed_demo and not self.list_projects():
            self.create_project(ProjectCreate(title="夜巡人", mode="long-form", total_chapters=1000), seed_demo=True)

    def list_projects(self) -> list[CatalogProject]:
        with self.db.catalog() as session:
            return list(session.scalars(select(CatalogProject).order_by(CatalogProject.last_opened_at.desc())).all())

    def get_project(self, project_id: str, *, touch: bool = False) -> CatalogProject:
        with self.db.catalog() as session:
            project = session.get(CatalogProject, project_id)
            if not project:
                raise StoryError(404, "PROJECT_NOT_FOUND", "作品不存在。", {"projectId": project_id})
            if touch:
                project.last_opened_at = utc_now()
                session.commit()
                session.refresh(project)
            return project

    def create_project(self, payload: ProjectCreate, *, seed_demo: bool = False) -> CatalogProject:
        project_id = str(uuid4())
        folder = (self.settings.projects_dir / f"{project_id}-{slugify(payload.title)}").resolve()
        if self.settings.projects_dir.resolve() not in folder.parents:
            raise StoryError(400, "INVALID_PROJECT_PATH", "作品目录超出允许的数据根目录。")
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "canon").mkdir()
        (folder / "backups").mkdir()
        (folder / "exports").mkdir()

        now = utc_now()
        catalog = CatalogProject(
            id=project_id,
            title=payload.title,
            slug=slugify(payload.title),
            mode=payload.mode,
            folder_path=str(folder),
            current_chapter=36 if seed_demo else 0,
            total_chapters=payload.total_chapters,
            created_at=now,
            updated_at=now,
            last_opened_at=now,
        )
        try:
            with self.db.catalog() as session:
                session.add(catalog)
                session.commit()
            self.db.ensure_project_database(project_id, folder)
            self._seed_project_database(catalog, seed_demo=seed_demo)
            self._write_project_files(catalog)
        except Exception:
            with self.db.catalog() as session:
                existing = session.get(CatalogProject, project_id)
                if existing:
                    session.delete(existing)
                    session.commit()
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return catalog

    def update_project(self, project_id: str, payload: ProjectUpdate) -> CatalogProject:
        project = self.get_project(project_id)
        changes = payload.model_dump(exclude_none=True)
        with self.db.catalog() as session:
            row = session.get(CatalogProject, project_id)
            assert row
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
            session.commit()
            session.refresh(row)
            project = row
        with self.db.project_write(project_id, project.folder_path) as session:
            meta = session.get(ProjectMeta, project_id)
            if meta:
                for key, value in changes.items():
                    setattr(meta, key, value)
                meta.updated_at = utc_now()
        self._write_project_files(project)
        return project

    def _write_project_files(self, project: CatalogProject) -> None:
        folder = Path(project.folder_path)
        project_json = {
            "id": project.id,
            "title": project.title,
            "mode": project.mode,
            "currentChapter": project.current_chapter,
            "totalChapters": project.total_chapters,
            "schemaVersion": project.schema_version,
        }
        (folder / "project.json").write_text(json.dumps(project_json, ensure_ascii=False, indent=2), encoding="utf-8")
        canon = folder / "canon" / "story-core.md"
        if not canon.exists():
            canon.write_text(
                f"# {project.title} · Story Core\n\n> 状态：等待 Canon 分析器生成。本文件属于作者可读的权威目录。\n",
                encoding="utf-8",
            )

    def _seed_project_database(self, project: CatalogProject, *, seed_demo: bool) -> None:
        plan_id = str(uuid4())
        session_id = str(uuid4())
        with self.db.project_write(project.id, project.folder_path) as session:
            session.add(ProjectMeta(
                id=project.id, title=project.title, mode=project.mode,
                current_chapter=project.current_chapter, total_chapters=project.total_chapters,
            ))
            session.add(Plan(
                id=plan_id,
                book_title="全书",
                volume_title="第一卷：雾城夜巡" if seed_demo else "第一卷",
                arc_title="弧线 01：旧宅来信" if seed_demo else "故事弧 01",
                chapter_start=1,
                chapter_end=min(project.total_chapters, 100),
            ))
            nodes = self._demo_nodes(plan_id) if seed_demo else [
                PlanNode(
                    id="milestone-opening", plan_id=plan_id, title="故事开端", type="事件",
                    target_chapter=1, range_min=1, range_max=min(5, project.total_chapters), importance=3,
                    note="定义故事的第一个可验证里程碑。", prerequisites_json=dumps(["作品已创建"]),
                    completion_conditions_json=dumps(["主角进入初始情境"]), foreshadows_json="[]",
                    contracts_json=dumps(["契约 A01"]), pace="smooth",
                )
            ]
            session.add_all(nodes)
            if seed_demo:
                session.add_all(self._demo_markers(plan_id))
            agent_session = AgentSession(
                id=session_id, project_id=project.id,
                scope_json=dumps(["第一卷", "弧线 01", "首次直面纸人"]), status="idle",
            )
            session.add(agent_session)
            if seed_demo:
                session.add_all([
                    AgentMessage(id=str(uuid4()), session_id=session_id, role="user", content="我觉得‘首次直面纸人’发生得太早了，主角还没建立足够的好奇心与紧张感。"),
                    AgentMessage(id=str(uuid4()), session_id=session_id, role="assistant", content="我检查了第一卷节奏和前置契约。建议把该里程碑放到第二幕中段，并同步延长调查铺垫。"),
                ])
                session.add(self._make_proposal(nodes[1]))

    def _demo_nodes(self, plan_id: str) -> list[PlanNode]:
        raw = [
            ("milestone-letter", "收到旧宅来信", "事件", 8, 6, 10, 3, "主角收到一封没有署名的旧宅来信。", ["建立夜巡人的日常秩序"], ["主角决定前往旧宅"], ["来信上的潮湿指印"], ["契约 A01"], "smooth"),
            ("milestone-paper-man", "首次直面纸人", "关键事件", 18, 16, 21, 4, "主角首次与纸人近距离接触，恐惧与好奇并存。", ["已触发事件：收到旧宅来信（章 8）", "伏笔生效：纸人握功（章 15）"], ["主角确认纸人具备感知与记忆", "获得旧宅相关的新线索"], ["纸人的规则", "日记中的名字", "遗夜路线图"], ["契约 A02", "契约 C03", "伏笔 P02"], "fast"),
            ("milestone-clue", "纸人之谜揭开一角", "转折点", 45, 43, 48, 4, "纸人并非纯粹敌人。", ["完成纸人首次接触"], ["揭示纸人的部分行动规则"], ["血字契约"], ["契约 A02", "伏笔 P03"], "slow"),
            ("milestone-watch-office", "夜巡司介入", "事件", 70, 68, 72, 3, "夜巡司正式介入旧宅事件。", ["纸人线索形成闭环"], ["确立夜巡司的公开立场"], ["旧宅档案缺页"], ["契约 B01"], "fast"),
            ("milestone-truth", "旧宅真相浮出", "高潮点", 96, 92, 98, 5, "第一卷主谜面揭晓。", ["夜巡司介入", "纸人规则已确认"], ["回收第一卷主要伏笔", "建立第二卷主冲突"], ["雾城地下旧路"], ["契约 C03", "伏笔 P04"], "smooth"),
        ]
        return [PlanNode(
            id=item[0], plan_id=plan_id, title=item[1], type=item[2], target_chapter=item[3], range_min=item[4], range_max=item[5],
            importance=item[6], note=item[7], prerequisites_json=dumps(item[8]), completion_conditions_json=dumps(item[9]),
            foreshadows_json=dumps(item[10]), contracts_json=dumps(item[11]), pace=item[12],
        ) for item in raw]

    def _demo_markers(self, plan_id: str) -> list[StoryMarker]:
        raw = [("hook-1", "hook", 8, "来信钩子"), ("hook-2", "hook", 18, "纸人现身"), ("foreshadow-1", "foreshadow", 31, "纸人规则"), ("hook-3", "hook", 54, "档案缺页"), ("foreshadow-2", "foreshadow", 64, "夜巡司暗线"), ("hook-4", "hook", 86, "旧路入口")]
        return [StoryMarker(id=item[0], plan_id=plan_id, kind=item[1], chapter=item[2], label=item[3]) for item in raw]

    def _make_proposal(self, node: PlanNode) -> ChangeProposal:
        proposal_id = str(uuid4())
        proposal = ChangeProposal(
            id=proposal_id, target_id=node.id, target_title=node.title,
            reason="延长旧宅调查阶段，让主角的好奇与恐惧先形成张力，再进入正面对抗。",
        )
        proposal.operations = [
            ChangeOperation(id=str(uuid4()), proposal_id=proposal_id, field="targetChapter", label="目标章节", before_value=node.target_chapter, after_value=22, selected=True),
            ChangeOperation(id=str(uuid4()), proposal_id=proposal_id, field="rangeMin", label="允许范围起点", before_value=node.range_min, after_value=20, selected=True),
            ChangeOperation(id=str(uuid4()), proposal_id=proposal_id, field="rangeMax", label="允许范围终点", before_value=node.range_max, after_value=25, selected=True),
        ]
        proposal.impacts = [
            ProposalImpact(id=str(uuid4()), proposal_id=proposal_id, kind="contract", label="3 个章节契约"),
            ProposalImpact(id=str(uuid4()), proposal_id=proposal_id, kind="foreshadow", label="1 条伏笔"),
            ProposalImpact(id=str(uuid4()), proposal_id=proposal_id, kind="dependency", label="2 个前置依赖"),
        ]
        return proposal

    def get_plan(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id, touch=True)
        with self.db.project(project_id, project.folder_path) as session:
            plan = session.scalar(select(Plan).options(selectinload(Plan.nodes), selectinload(Plan.markers)))
            if not plan:
                raise StoryError(404, "PLAN_NOT_FOUND", "作品规划不存在。")
            return self._plan_dict(plan)

    def update_plan_node(self, project_id: str, node_id: str, payload: PlanNodeUpdate, request_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        with self.db.project_write(project_id, project.folder_path) as session:
            node = session.get(PlanNode, node_id)
            if not node:
                raise StoryError(404, "PLAN_NODE_NOT_FOUND", "规划节点不存在。")
            if node.revision != payload.expected_revision:
                raise StoryError(409, "REVISION_CONFLICT", "规划已被其他操作修改。", {"expectedRevision": payload.expected_revision, "currentRevision": node.revision})
            before = self._node_dict(node)
            changes = payload.model_dump(exclude_none=True, exclude={"expected_revision"})
            json_fields = {"prerequisites": "prerequisites_json", "completion_conditions": "completion_conditions_json", "foreshadows": "foreshadows_json", "contracts": "contracts_json"}
            for key, value in changes.items():
                setattr(node, json_fields.get(key, key), dumps(value) if key in json_fields else value)
            self._validate_node(node)
            node.revision += 1
            session.add(self._audit("plan_node.updated", "plan_node", node.id, {"before": before, "after": self._node_dict(node), "reversible": True}, request_id))
            session.flush()
            return self._node_dict(node)

    def list_sessions(self, project_id: str) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        with self.db.project(project_id, project.folder_path) as session:
            sessions = session.scalars(select(AgentSession).options(selectinload(AgentSession.messages)).order_by(AgentSession.updated_at.desc())).all()
            return [self._session_dict(item) for item in sessions]

    def create_session(self, project_id: str, scope: list[str]) -> dict[str, Any]:
        project = self.get_project(project_id)
        with self.db.project_write(project_id, project.folder_path) as session:
            item = AgentSession(id=str(uuid4()), project_id=project_id, scope_json=dumps(scope), status="idle")
            session.add(item)
            session.flush()
            return self._session_dict(item)

    def send_message(self, session_id: str, payload: AgentMessageCreate) -> dict[str, Any]:
        project = self.get_project(payload.project_id)
        with self.db.project_write(project.id, project.folder_path) as session:
            agent_session = session.get(AgentSession, session_id)
            if not agent_session:
                raise StoryError(404, "AGENT_SESSION_NOT_FOUND", "Agent 会话不存在。")
            user_message = AgentMessage(id=str(uuid4()), session_id=session_id, role="user", content=payload.content)
            session.add(user_message)
            node = session.get(PlanNode, payload.selected_node_id) if payload.selected_node_id else None
            requests_change = bool(re.search(r"调整|重排|修改|节奏|提前|推后|逻辑", payload.content))
            if requests_change and node:
                content = f"我已重新检查“{node.title}”的章节窗口、前置条件和伏笔依赖。建议采用修改提案，确认后才会写入规划。"
                proposal = self._make_proposal(node)
                session.add(proposal)
            else:
                title = node.title if node else "当前规划"
                content = f"我已读取当前作用域。关于“{title}”，你可以继续说明希望强化的冲突或情绪。"
                proposal = None
            assistant = AgentMessage(id=str(uuid4()), session_id=session_id, role="assistant", content=content)
            session.add(assistant)
            agent_session.updated_at = utc_now()
            session.flush()
            return {"message": self._message_dict(assistant), "proposal": self._proposal_dict(proposal) if proposal else None}

    def list_proposals(self, project_id: str, status: str | None = None) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        with self.db.project(project_id, project.folder_path) as session:
            query = select(ChangeProposal).options(selectinload(ChangeProposal.operations), selectinload(ChangeProposal.impacts)).order_by(ChangeProposal.created_at.desc())
            if status:
                query = query.where(ChangeProposal.status == status)
            return [self._proposal_dict(item) for item in session.scalars(query).all()]

    def apply_proposal(self, proposal_id: str, payload: ProposalApply, request_id: str) -> dict[str, Any]:
        project = self.get_project(payload.project_id)
        with self.db.project_write(project.id, project.folder_path) as session:
            proposal = session.scalar(select(ChangeProposal).where(ChangeProposal.id == proposal_id).options(selectinload(ChangeProposal.operations), selectinload(ChangeProposal.impacts)))
            if not proposal:
                raise StoryError(404, "PROPOSAL_NOT_FOUND", "修改提案不存在。")
            if proposal.revision != payload.expected_revision:
                raise StoryError(409, "REVISION_CONFLICT", "修改提案已被其他操作处理。", {"currentRevision": proposal.revision})
            if proposal.status != "pending":
                raise StoryError(409, "PROPOSAL_ALREADY_RESOLVED", "修改提案已处理。", {"status": proposal.status})
            node = session.get(PlanNode, proposal.target_id)
            if not node:
                raise StoryError(404, "PLAN_NODE_NOT_FOUND", "提案目标节点不存在。")
            before = self._node_dict(node)
            selected = set(payload.selected_operation_ids)
            field_map = {"targetChapter": "target_chapter", "rangeMin": "range_min", "rangeMax": "range_max"}
            applied = []
            for operation in proposal.operations:
                operation.selected = operation.id in selected
                if operation.selected:
                    setattr(node, field_map[operation.field], operation.after_value)
                    applied.append(operation.id)
            if not applied:
                raise StoryError(422, "NO_OPERATIONS_SELECTED", "至少选择一项修改。")
            self._validate_node(node)
            node.revision += 1
            proposal.status = "accepted"
            proposal.revision += 1
            proposal.updated_at = utc_now()
            session.add(self._audit("proposal.applied", "plan_node", node.id, {"proposalId": proposal.id, "operationIds": applied, "before": before, "after": self._node_dict(node), "reversible": True}, request_id))
            session.flush()
            return self._proposal_dict(proposal)

    def reject_proposal(self, proposal_id: str, payload: ProposalReject, request_id: str) -> dict[str, Any]:
        project = self.get_project(payload.project_id)
        with self.db.project_write(project.id, project.folder_path) as session:
            proposal = session.scalar(select(ChangeProposal).where(ChangeProposal.id == proposal_id).options(selectinload(ChangeProposal.operations), selectinload(ChangeProposal.impacts)))
            if not proposal:
                raise StoryError(404, "PROPOSAL_NOT_FOUND", "修改提案不存在。")
            if proposal.revision != payload.expected_revision:
                raise StoryError(409, "REVISION_CONFLICT", "修改提案已被其他操作处理。")
            if proposal.status != "pending":
                raise StoryError(409, "PROPOSAL_ALREADY_RESOLVED", "修改提案已处理。")
            proposal.status = "rejected"
            proposal.revision += 1
            proposal.updated_at = utc_now()
            session.add(self._audit("proposal.rejected", "change_proposal", proposal.id, {"proposalId": proposal.id, "reversible": False}, request_id))
            session.flush()
            return self._proposal_dict(proposal)

    def list_audit_events(self, project_id: str, limit: int = 100) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        with self.db.project(project.id, project.folder_path) as session:
            events = session.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(limit, 500))).all()
            return [self._audit_dict(item) for item in events]

    def undo_event(self, project_id: str, event_id: str, request_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        with self.db.project_write(project.id, project.folder_path) as session:
            event = session.get(AuditEvent, event_id)
            if not event:
                raise StoryError(404, "AUDIT_EVENT_NOT_FOUND", "审计事件不存在。")
            payload = loads(event.payload_json)
            if not payload.get("reversible") or not payload.get("before"):
                raise StoryError(409, "EVENT_NOT_REVERSIBLE", "该事件不能撤销。")
            node = session.get(PlanNode, event.entity_id)
            if not node:
                raise StoryError(404, "PLAN_NODE_NOT_FOUND", "撤销目标不存在。")
            current = self._node_dict(node)
            expected_after = payload.get("after", {})
            if current.get("revision") != expected_after.get("revision"):
                raise StoryError(409, "REVISION_CONFLICT", "节点在该操作后又发生变化，不能直接撤销。", {"currentRevision": current.get("revision")})
            before = payload["before"]
            self._apply_node_snapshot(node, before)
            node.revision = current["revision"] + 1
            undo = self._audit("event.undone", "plan_node", node.id, {"undoneEventId": event.id, "before": current, "after": self._node_dict(node), "reversible": False}, request_id)
            session.add(undo)
            session.flush()
            return self._audit_dict(undo)

    def create_backup(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        folder = Path(project.folder_path)
        backup_id = str(uuid4())
        created = utc_now()
        archive = folder / "backups" / f"{created.strftime('%Y%m%d-%H%M%S')}-{backup_id}.zip"
        with tempfile.TemporaryDirectory(dir=self.settings.data_dir) as temp_name:
            temp = Path(temp_name)
            db_snapshot = temp / "story.db"
            source = sqlite3.connect(folder / "story.db")
            target = sqlite3.connect(db_snapshot)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            files: dict[str, Path] = {"project.json": folder / "project.json", "story.db": db_snapshot}
            for canon_file in (folder / "canon").rglob("*"):
                if canon_file.is_file():
                    files[canon_file.relative_to(folder).as_posix()] = canon_file
            checksums = {name: sha256(path) for name, path in files.items()}
            manifest = {
                "backupId": backup_id, "projectId": project.id, "projectTitle": project.title,
                "createdAt": created.isoformat(), "files": checksums,
            }
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
                for name, path in files.items():
                    package.write(path, name)
                package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return {**manifest, "archivePath": str(archive)}

    def restore_backup(self, archive_path: Path) -> CatalogProject:
        if not zipfile.is_zipfile(archive_path):
            raise StoryError(422, "INVALID_BACKUP", "备份文件不是有效 ZIP。")
        with tempfile.TemporaryDirectory(dir=self.settings.data_dir) as temp_name:
            temp = Path(temp_name)
            with zipfile.ZipFile(archive_path) as package:
                names = set(package.namelist())
                if "manifest.json" not in names:
                    raise StoryError(422, "INVALID_BACKUP", "备份缺少 manifest.json。")
                for name in names:
                    path = PurePosixPath(name)
                    if path.is_absolute() or ".." in path.parts:
                        raise StoryError(422, "INVALID_BACKUP_PATH", "备份包含不安全路径。", {"path": name})
                package.extractall(temp)
            manifest = json.loads((temp / "manifest.json").read_text(encoding="utf-8"))
            for name, expected in manifest.get("files", {}).items():
                path = temp / Path(name)
                if not path.is_file() or sha256(path) != expected:
                    raise StoryError(422, "BACKUP_CHECKSUM_MISMATCH", "备份校验失败。", {"path": name})
            source_json = json.loads((temp / "project.json").read_text(encoding="utf-8"))
            restored = self.create_project(ProjectCreate(
                title=f"{source_json['title']}（恢复）", mode=source_json["mode"], total_chapters=source_json["totalChapters"]
            ))
            target_folder = Path(restored.folder_path)
            engine = self.db._project_engines.pop(restored.id, None)
            self.db._project_factories.pop(restored.id, None)
            if engine:
                engine.dispose()
            shutil.copy2(temp / "story.db", target_folder / "story.db")
            if (temp / "canon").exists():
                shutil.rmtree(target_folder / "canon")
                shutil.copytree(temp / "canon", target_folder / "canon")
            self.db.ensure_project_database(restored.id, target_folder)
            with self.db.project_write(restored.id, target_folder) as session:
                old_meta = session.scalar(select(ProjectMeta))
                if old_meta:
                    old_id = old_meta.id
                    old_meta.id = restored.id
                    old_meta.title = restored.title
                    for agent_session in session.scalars(select(AgentSession).where(AgentSession.project_id == old_id)):
                        agent_session.project_id = restored.id
            self._write_project_files(restored)
            return restored

    def _validate_node(self, node: PlanNode) -> None:
        if node.range_min > node.range_max:
            raise StoryError(422, "INVALID_CHAPTER_RANGE", "允许范围起点不能晚于终点。")
        if node.target_chapter < node.range_min or node.target_chapter > node.range_max:
            raise StoryError(422, "TARGET_OUTSIDE_RANGE", "目标章节必须位于允许范围内。", {"targetChapter": node.target_chapter, "rangeMin": node.range_min, "rangeMax": node.range_max})
        if not loads(node.prerequisites_json) or not loads(node.completion_conditions_json):
            raise StoryError(422, "INCOMPLETE_MILESTONE_CONTRACT", "里程碑必须包含前置条件和完成条件。")

    def _apply_node_snapshot(self, node: PlanNode, data: dict[str, Any]) -> None:
        fields = ["title", "type", "targetChapter", "rangeMin", "rangeMax", "importance", "note", "pace"]
        mapping = {"targetChapter": "target_chapter", "rangeMin": "range_min", "rangeMax": "range_max"}
        for field in fields:
            if field in data:
                setattr(node, mapping.get(field, field), data[field])
        node.prerequisites_json = dumps(data.get("prerequisites", []))
        node.completion_conditions_json = dumps(data.get("completionConditions", []))
        node.foreshadows_json = dumps(data.get("foreshadows", []))
        node.contracts_json = dumps(data.get("contracts", []))

    def _audit(self, event_type: str, entity_type: str, entity_id: str, payload: dict[str, Any], request_id: str) -> AuditEvent:
        return AuditEvent(id=str(uuid4()), event_type=event_type, entity_type=entity_type, entity_id=entity_id, payload_json=dumps(payload), request_id=request_id)

    def _node_dict(self, node: PlanNode) -> dict[str, Any]:
        return {"id": node.id, "title": node.title, "type": node.type, "targetChapter": node.target_chapter, "rangeMin": node.range_min, "rangeMax": node.range_max, "importance": node.importance, "note": node.note, "prerequisites": loads(node.prerequisites_json), "completionConditions": loads(node.completion_conditions_json), "foreshadows": loads(node.foreshadows_json), "contracts": loads(node.contracts_json), "pace": node.pace, "revision": node.revision}

    def _plan_dict(self, plan: Plan) -> dict[str, Any]:
        return {"id": plan.id, "bookTitle": plan.book_title, "volumeTitle": plan.volume_title, "arcTitle": plan.arc_title, "chapterStart": plan.chapter_start, "chapterEnd": plan.chapter_end, "revision": plan.revision, "milestones": [self._node_dict(node) for node in sorted(plan.nodes, key=lambda item: item.target_chapter)], "markers": [{"id": marker.id, "kind": marker.kind, "chapter": marker.chapter, "label": marker.label} for marker in sorted(plan.markers, key=lambda item: item.chapter)]}

    def _message_dict(self, item: AgentMessage) -> dict[str, Any]:
        return {"id": item.id, "role": item.role, "content": item.content, "timestamp": item.created_at}

    def _session_dict(self, item: AgentSession) -> dict[str, Any]:
        return {"id": item.id, "projectId": item.project_id, "scope": loads(item.scope_json), "status": item.status, "messages": [self._message_dict(message) for message in sorted(item.messages, key=lambda row: row.created_at)]}

    def _proposal_dict(self, item: ChangeProposal | None) -> dict[str, Any]:
        assert item
        return {"id": item.id, "targetId": item.target_id, "targetTitle": item.target_title, "reason": item.reason, "status": item.status, "revision": item.revision, "operations": [{"id": op.id, "field": op.field, "label": op.label, "before": op.before_value, "after": op.after_value, "selected": op.selected} for op in item.operations], "impacts": [{"id": impact.id, "kind": impact.kind, "label": impact.label} for impact in item.impacts]}

    def _audit_dict(self, item: AuditEvent) -> dict[str, Any]:
        return {"id": item.id, "eventType": item.event_type, "entityType": item.entity_type, "entityId": item.entity_id, "payload": loads(item.payload_json), "requestId": item.request_id, "createdAt": item.created_at}

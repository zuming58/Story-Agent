from __future__ import annotations

import html
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import (
    AutomationRunItem,
    ChapterCommit,
    ChapterDraft,
    ChapterExtraction,
    ExportArtifact,
    ExportJob,
    ExportJobChapter,
    ExportProfile,
    PublicationRecord,
    QualityFinding,
    RetrievalIndexState,
    SourceVersion,
    StateSnapshot,
)
from .schemas import ExportCreate, ExportProfileUpdate, ExportReadinessRequest, PublicationRecordCreate
from .services import StoryError, dumps, loads, sha256, stable_digest


FORMATS = ("txt", "markdown", "docx", "epub")
FORMAT_EXT = {"txt": "txt", "markdown": "md", "docx": "docx", "epub": "epub"}
FORMAT_MIME = {
    "txt": "text/plain; charset=utf-8",
    "markdown": "text/markdown; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "epub": "application/epub+zip",
}
TERMINAL_EXPORT_STATUSES = {"completed", "blocked", "failed", "cancelled", "interrupted"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _plain_title(title: str, chapter: int) -> str:
    return title.strip() or f"第{chapter}章"


def _file_safe(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", value.strip()).strip("-._")
    return slug[:80] or "story"


def _chapter_heading(template: str, chapter: int, title: str) -> str:
    try:
        return template.format(chapter=chapter, title=_plain_title(title, chapter))
    except (KeyError, IndexError, ValueError):
        return f"第{chapter}章 {_plain_title(title, chapter)}"


@dataclass
class RenderedArtifact:
    format: str
    temp_path: Path
    final_relative_path: str
    file_name: str
    mime_type: str


class Phase9Service:
    def __init__(self, service: Any):
        self.service = service

    def recover_interrupted_exports(self) -> None:
        for project in self.service.list_projects():
            with self.service.db.project_write(project.id, project.folder_path) as session:
                for job in session.scalars(
                    select(ExportJob).where(ExportJob.status.in_(("validating", "rendering")))
                ).all():
                    job.status = "interrupted"
                    job.stop_reason = "application_restart"
                    job.revision += 1
                    job.updated_at = _now()
                    job.completed_at = _now()
                for job in session.scalars(
                    select(ExportJob).where(ExportJob.status == "cancel_requested")
                ).all():
                    job.status = "cancelled"
                    job.stop_reason = job.stop_reason or "cancel_requested"
                    job.revision += 1
                    job.updated_at = _now()
                    job.completed_at = _now()

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------
    def get_profile(self, project_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            profile = self._get_or_create_profile(session, project.id, project.title)
            return self._profile_dict(profile)

    def update_profile(self, project_id: str, payload: ExportProfileUpdate) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            profile = self._get_or_create_profile(session, project.id, project.title)
            if profile.revision != payload.expected_revision:
                raise StoryError(409, "EXPORT_PROFILE_REVISION_CONFLICT", "导出配置 revision 冲突。", {"currentRevision": profile.revision})
            if payload.default_formats is not None:
                profile.default_formats_json = dumps(self._normalize_formats(payload.default_formats))
            for field, attr in (
                ("book_title", "book_title"),
                ("author_name", "author_name"),
                ("description", "description"),
                ("chapter_title_template", "chapter_title_template"),
                ("include_quality_summary", "include_quality_summary"),
            ):
                value = getattr(payload, field)
                if value is not None:
                    setattr(profile, attr, value)
            profile.revision += 1
            profile.updated_at = _now()
            return self._profile_dict(profile)

    def _get_or_create_profile(self, session: Session, project_id: str, title: str) -> ExportProfile:
        profile = session.get(ExportProfile, project_id)
        if profile:
            return profile
        now = _now()
        profile = ExportProfile(
            project_id=project_id,
            book_title=title,
            created_at=now,
            updated_at=now,
        )
        session.add(profile)
        session.flush()
        return profile

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------
    def readiness(self, project_id: str, payload: ExportReadinessRequest) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        formats = self._requested_formats(project.id, project.folder_path, payload.formats)
        with self.service.db.project(project.id, project.folder_path) as session:
            return self._readiness(session, project.id, project.title, payload.mode, payload.chapter_start, payload.chapter_end, formats)

    def _readiness(
        self,
        session: Session,
        project_id: str,
        title: str,
        mode: str,
        chapter_start: int,
        chapter_end: int,
        formats: list[str],
    ) -> dict[str, Any]:
        if chapter_end < chapter_start:
            raise StoryError(422, "EXPORT_RANGE_INVALID", "导出结束章节不能早于开始章节。")
        issues: list[dict[str, Any]] = []
        exportable = 0
        for chapter in range(chapter_start, chapter_end + 1):
            snapshot, chapter_issues = self._chapter_snapshot(session, project_id, chapter)
            issues.extend(chapter_issues)
            if snapshot is not None:
                exportable += 1
        blocker_count = sum(1 for item in issues if item["severity"] == "blocker")
        ready = blocker_count == 0 if mode == "formal" else exportable > 0
        return {
            "ready": ready,
            "mode": mode,
            "chapterStart": chapter_start,
            "chapterEnd": chapter_end,
            "exportableChapterCount": exportable,
            "formats": formats,
            "estimatedFileNames": {fmt: self._artifact_file_name(title, mode, chapter_start, chapter_end, fmt) for fmt in formats},
            "issues": issues,
        }

    def _chapter_snapshot(self, session: Session, project_id: str, chapter: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        issues: list[dict[str, Any]] = []
        commit = session.scalar(select(ChapterCommit).where(
            ChapterCommit.project_id == project_id,
            ChapterCommit.chapter_number == chapter,
            ChapterCommit.is_current.is_(True),
        ))
        any_commit = session.scalar(select(ChapterCommit).where(
            ChapterCommit.project_id == project_id,
            ChapterCommit.chapter_number == chapter,
        ))
        if commit is None:
            issues.append(self._issue(
                "EXPORT_COMMIT_NOT_CURRENT" if any_commit else "EXPORT_CHAPTER_GAP",
                "blocker",
                chapter,
                {"chapter": chapter},
                "请先生成并正式提交该章节。",
            ))
            return None, issues
        if commit.status != "official":
            issues.append(self._issue("EXPORT_COMMIT_NOT_CURRENT", "blocker", chapter, {"commitId": commit.id}, "只能导出 official current commit。"))

        draft = session.get(ChapterDraft, commit.approved_draft_id)
        source = session.get(SourceVersion, commit.source_version_id)
        snapshot = session.get(StateSnapshot, commit.state_snapshot_id) if commit.state_snapshot_id else None
        if not draft or not source or not snapshot or source.status != "official":
            issues.append(self._issue(
                "EXPORT_STATE_REFERENCE_BROKEN",
                "blocker",
                chapter,
                {
                    "commitId": commit.id,
                    "draftPresent": bool(draft),
                    "sourcePresent": bool(source),
                    "snapshotPresent": bool(snapshot),
                    "sourceStatus": source.status if source else None,
                },
                "请重建章节正式提交，确保 source/snapshot 引用完整。",
            ))
        extraction = session.scalar(
            select(ChapterExtraction)
            .where(ChapterExtraction.chapter_draft_id == commit.approved_draft_id)
            .order_by(ChapterExtraction.created_at.desc())
        )
        if not extraction or extraction.status != "validated":
            issues.append(self._issue("EXPORT_EXTRACTION_INVALID", "blocker", chapter, {"draftId": commit.approved_draft_id}, "请重新抽取并校验章节事实。"))
        blockers = session.scalars(select(QualityFinding).where(
            QualityFinding.project_id == project_id,
            QualityFinding.chapter_draft_id == commit.approved_draft_id,
            QualityFinding.status == "open",
            QualityFinding.severity.in_(("blocker", "error")),
        )).all()
        if blockers:
            issues.append(self._issue(
                "EXPORT_QUALITY_BLOCKED",
                "blocker",
                chapter,
                {"findingIds": [item.id for item in blockers]},
                "请先解决 open blocker/error 质量问题。",
            ))
        retrieval = session.get(RetrievalIndexState, project_id)
        if retrieval and not retrieval.vector_available:
            issues.append(self._issue("EXPORT_RETRIEVAL_STALE", "blocker", chapter, {"projectId": project_id}, "请重建检索索引。"))
        isolated = session.scalar(select(AutomationRunItem).where(
            AutomationRunItem.project_id == project_id,
            AutomationRunItem.chapter_number == chapter,
            AutomationRunItem.status.in_(("isolated", "blocked")),
        ))
        if isolated:
            issues.append(self._issue("EXPORT_AUTOMATION_ISOLATED", "blocker", chapter, {"runItemId": isolated.id}, "请处理自动化隔离章节后再正式导出。"))

        if draft is None:
            content = ""
            title = f"第{chapter}章"
            draft_checksum = ""
            draft_revision = None
        else:
            content = draft.content_markdown
            title = self._title_for_chapter(session, project_id, draft.chapter_contract_id, chapter)
            draft_checksum = draft.checksum
            draft_revision = draft.revision
        result = {
            "chapterNumber": chapter,
            "chapterTitle": title,
            "chapterCommitId": commit.id,
            "approvedDraftId": commit.approved_draft_id,
            "sourceVersionId": commit.source_version_id,
            "stateSnapshotId": commit.state_snapshot_id,
            "commitRevision": commit.revision,
            "sourceRevision": source.revision if source else None,
            "draftRevision": draft_revision,
            "snapshotRevision": snapshot.revision if snapshot else None,
            "commitChecksum": commit.checksum,
            "draftChecksum": draft_checksum,
            "sourceChecksum": source.checksum if source else "",
            "qualitySummary": loads(commit.quality_summary_json) or {},
            "contentMarkdown": content,
            "missing": False,
        }
        return result, issues

    def _title_for_chapter(self, session: Session, project_id: str, contract_id: str, chapter: int) -> str:
        from .models import ChapterContract

        contract = session.get(ChapterContract, contract_id)
        if contract and contract.project_id == project_id:
            return contract.title
        return f"第{chapter}章"

    @staticmethod
    def _issue(code: str, severity: str, chapter: int | None, evidence: dict[str, Any], suggestion: str) -> dict[str, Any]:
        return {"code": code, "severity": severity, "chapterNumber": chapter, "evidence": evidence, "suggestion": suggestion}

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------
    def create_export(self, project_id: str, payload: ExportCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        formats = self._requested_formats(project.id, project.folder_path, payload.formats)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            if payload.idempotency_key:
                existing = session.scalar(select(ExportJob).where(
                    ExportJob.project_id == project.id,
                    ExportJob.idempotency_key == payload.idempotency_key,
                ))
                if existing:
                    return self._job_dict(session, existing, include_details=True)
            now = _now()
            values = {
                "id": str(uuid4()),
                "project_id": project.id,
                "mode": payload.mode,
                "chapter_start": payload.chapter_start,
                "chapter_end": payload.chapter_end,
                "formats_json": dumps(formats),
                "idempotency_key": payload.idempotency_key,
                "status": "queued",
                "frozen_manifest_json": "{}",
                "readiness_json": "{}",
                "revision": 1,
                "created_at": now,
                "updated_at": now,
            }
            if payload.idempotency_key:
                result = session.execute(sqlite_insert(ExportJob).values(**values).on_conflict_do_nothing())
                if result.rowcount == 0:
                    existing = session.scalar(select(ExportJob).where(
                        ExportJob.project_id == project.id,
                        ExportJob.idempotency_key == payload.idempotency_key,
                    ))
                    if existing:
                        return self._job_dict(session, existing, include_details=True)
                    raise StoryError(409, "EXPORT_JOB_CONFLICT", "导出任务幂等键冲突。")
                job = session.get(ExportJob, values["id"])
                assert job is not None
            else:
                job = ExportJob(**values)
                session.add(job)
                session.flush()
            job_id = job.id
        self._execute_export(project.id, job_id, request_id)
        return self.get_export(project.id, job_id)

    def list_exports(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._job_dict(session, job, include_details=False) for job in session.scalars(
                select(ExportJob).where(ExportJob.project_id == project.id).order_by(ExportJob.created_at.desc())
            ).all()]

    def get_export(self, project_id: str, export_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, export_id)
            return self._job_dict(session, job, include_details=True)

    def cancel_export(self, project_id: str, export_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, export_id)
            if job.status in TERMINAL_EXPORT_STATUSES:
                return self._job_dict(session, job, include_details=True)
            job.status = "cancelled" if job.status == "queued" else "cancel_requested"
            job.stop_reason = "cancel_requested"
            job.revision += 1
            job.updated_at = _now()
            if job.status == "cancelled":
                job.completed_at = _now()
            session.add(self.service._audit("export.cancel_requested", "export_job", job.id, {"requestId": request_id}, request_id))
            return self._job_dict(session, job, include_details=True)

    def resume_export(self, project_id: str, export_id: str, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, export_id)
            if job.status not in {"interrupted", "failed"}:
                raise StoryError(409, "EXPORT_JOB_NOT_RESUMABLE", "导出任务当前状态不可恢复。")
            job.status = "queued"
            job.stop_reason = None
            job.diagnostic_json = None
            job.completed_at = None
            job.revision += 1
            job.updated_at = _now()
            session.add(self.service._audit("export.resumed", "export_job", job.id, {"requestId": request_id}, request_id))
        self._execute_export(project.id, export_id, request_id)
        return self.get_export(project.id, export_id)

    def _execute_export(self, project_id: str, export_id: str, request_id: str) -> None:
        project = self.service.get_project(project_id)
        rendered: list[RenderedArtifact] = []
        moved: list[Path] = []
        try:
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, export_id)
                if job.status in TERMINAL_EXPORT_STATUSES:
                    return
                job.status = "validating"
                job.started_at = job.started_at or _now()
                job.updated_at = _now()
                job.revision += 1
                profile = self._get_or_create_profile(session, project.id, project.title)
                formats = loads(job.formats_json) or []
                chapters = session.scalars(select(ExportJobChapter).where(ExportJobChapter.export_job_id == job.id)).all()
                if not chapters:
                    readiness = self._readiness(session, project.id, project.title, job.mode, job.chapter_start, job.chapter_end, formats)
                    job.readiness_json = dumps(readiness)
                    if not readiness["ready"] and job.mode == "formal":
                        job.status = "blocked"
                        job.stop_reason = "EXPORT_READINESS_BLOCKED"
                        job.completed_at = _now()
                        job.updated_at = _now()
                        job.revision += 1
                        session.add(self.service._audit("export.blocked", "export_job", job.id, {"requestId": request_id, "issues": readiness["issues"]}, request_id))
                        return
                    self._freeze_chapters(session, job, readiness)
                self._refresh_manifest(session, job)
                job.status = "rendering"
                job.updated_at = _now()
                job.revision += 1
                profile_data = self._profile_dict(profile)
                job_data = self._job_dict(session, job, include_details=True)

            rendered = self._render_artifacts(project, job_data, profile_data)
            self._validate_frozen_sources(project.id, project.folder_path, export_id)
            if any(not artifact.temp_path.is_file() for artifact in rendered):
                self._remove_temp_files(rendered)
                rendered = self._render_artifacts(project, job_data, profile_data)
                self._validate_frozen_sources(project.id, project.folder_path, export_id)
            with self.service.db.project_write(project.id, project.folder_path) as session:
                job = self._get_job(session, project.id, export_id)
                if job.status == "cancel_requested":
                    self._remove_temp_files(rendered)
                    job.status = "cancelled"
                    job.stop_reason = "cancel_requested"
                    job.completed_at = _now()
                    job.updated_at = _now()
                    job.revision += 1
                    return
                for artifact in rendered:
                    final_path = Path(project.folder_path) / artifact.final_relative_path
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    if not artifact.temp_path.is_file():
                        self._write_artifact_temp(artifact.temp_path, artifact.format, job_data, profile_data, job_data["chapters"])
                    artifact.temp_path.replace(final_path)
                    moved.append(final_path)
                manifest = loads(job.frozen_manifest_json) or {}
                for artifact in rendered:
                    final_path = Path(project.folder_path) / artifact.final_relative_path
                    row = ExportArtifact(
                        id=str(uuid4()),
                        project_id=project.id,
                        export_job_id=job.id,
                        format=artifact.format,
                        relative_path=artifact.final_relative_path,
                        mime_type=artifact.mime_type,
                        file_name=artifact.file_name,
                        sha256=sha256(final_path),
                        byte_size=final_path.stat().st_size,
                        manifest_json=dumps(manifest),
                        status="available",
                        is_current=True,
                        revision=1,
                        created_at=_now(),
                        updated_at=_now(),
                    )
                    session.add(row)
                job.status = "completed"
                job.stop_reason = None
                job.completed_at = _now()
                job.updated_at = _now()
                job.revision += 1
                session.add(self.service._audit("export.completed", "export_job", job.id, {"requestId": request_id}, request_id))
        except StoryError as exc:
            self._remove_temp_files(rendered)
            self._remove_paths(moved)
            self._mark_export_failed(project.id, project.folder_path, export_id, "blocked" if exc.code == "EXPORT_SOURCE_REVISION_CONFLICT" else "failed", exc.code, {"message": exc.message, "details": exc.details})
            if exc.code != "EXPORT_SOURCE_REVISION_CONFLICT":
                raise
        except Exception as exc:
            self._remove_temp_files(rendered)
            self._remove_paths(moved)
            self._mark_export_failed(project.id, project.folder_path, export_id, "failed", "EXPORT_RENDER_FAILED", {"errorType": type(exc).__name__, "message": str(exc)})

    def _freeze_chapters(self, session: Session, job: ExportJob, readiness: dict[str, Any]) -> None:
        issues_by_chapter: dict[int | None, list[dict[str, Any]]] = {}
        for issue in readiness.get("issues", []):
            issues_by_chapter.setdefault(issue.get("chapterNumber"), []).append(issue)
        for sequence, chapter in enumerate(range(job.chapter_start, job.chapter_end + 1), start=1):
            snapshot, _issues = self._chapter_snapshot(session, job.project_id, chapter)
            if snapshot is None:
                if job.mode == "review":
                    now = _now()
                    session.add(ExportJobChapter(
                        id=str(uuid4()),
                        project_id=job.project_id,
                        export_job_id=job.id,
                        chapter_number=chapter,
                        sequence_number=sequence,
                        chapter_title=f"第{chapter}章（缺失）",
                        issue_summary_json=dumps(issues_by_chapter.get(chapter, [])),
                        missing=True,
                        created_at=now,
                        updated_at=now,
                    ))
                continue
            now = _now()
            session.add(ExportJobChapter(
                id=str(uuid4()),
                project_id=job.project_id,
                export_job_id=job.id,
                chapter_number=chapter,
                sequence_number=sequence,
                chapter_title=snapshot["chapterTitle"],
                chapter_commit_id=snapshot["chapterCommitId"],
                approved_draft_id=snapshot["approvedDraftId"],
                source_version_id=snapshot["sourceVersionId"],
                state_snapshot_id=snapshot["stateSnapshotId"],
                commit_revision=snapshot["commitRevision"],
                source_revision=snapshot["sourceRevision"],
                draft_revision=snapshot["draftRevision"],
                snapshot_revision=snapshot["snapshotRevision"],
                commit_checksum=snapshot["commitChecksum"],
                draft_checksum=snapshot["draftChecksum"],
                source_checksum=snapshot["sourceChecksum"],
                quality_summary_json=dumps(snapshot["qualitySummary"]),
                issue_summary_json=dumps(issues_by_chapter.get(chapter, [])),
                content_markdown=snapshot["contentMarkdown"],
                missing=False,
                created_at=now,
                updated_at=now,
            ))

    def _refresh_manifest(self, session: Session, job: ExportJob) -> None:
        chapters = session.scalars(
            select(ExportJobChapter).where(ExportJobChapter.export_job_id == job.id).order_by(ExportJobChapter.sequence_number)
        ).all()
        manifest = {
            "exportJobId": job.id,
            "projectId": job.project_id,
            "mode": job.mode,
            "chapterStart": job.chapter_start,
            "chapterEnd": job.chapter_end,
            "formats": loads(job.formats_json) or [],
            "chapters": [
                {
                    "chapterNumber": chapter.chapter_number,
                    "chapterCommitId": chapter.chapter_commit_id,
                    "approvedDraftId": chapter.approved_draft_id,
                    "sourceVersionId": chapter.source_version_id,
                    "stateSnapshotId": chapter.state_snapshot_id,
                    "commitRevision": chapter.commit_revision,
                    "sourceRevision": chapter.source_revision,
                    "draftRevision": chapter.draft_revision,
                    "snapshotRevision": chapter.snapshot_revision,
                    "commitChecksum": chapter.commit_checksum,
                    "draftChecksum": chapter.draft_checksum,
                    "sourceChecksum": chapter.source_checksum,
                    "missing": chapter.missing,
                }
                for chapter in chapters
            ],
        }
        manifest["manifestChecksum"] = stable_digest(manifest)
        job.frozen_manifest_json = dumps(manifest)

    # ------------------------------------------------------------------
    # Rendering and validation
    # ------------------------------------------------------------------
    def _render_artifacts(self, project: Any, job: dict[str, Any], profile: dict[str, Any]) -> list[RenderedArtifact]:
        folder = Path(project.folder_path)
        tmp_dir = folder / "exports" / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        chapters = job["chapters"]
        formats = job["formats"]
        artifacts: list[RenderedArtifact] = []
        for fmt in formats:
            file_name = self._artifact_file_name(profile["bookTitle"] or project.title, job["mode"], job["chapterStart"], job["chapterEnd"], fmt)
            temp_path = tmp_dir / f"{uuid4().hex[:16]}.{fmt}.tmp"
            self._write_artifact_temp(temp_path, fmt, job, profile, chapters)
            artifacts.append(RenderedArtifact(
                format=fmt,
                temp_path=temp_path,
                final_relative_path=f"exports/{job['id']}/{file_name}",
                file_name=file_name,
                mime_type=FORMAT_MIME[fmt],
            ))
        return artifacts

    def _write_artifact_temp(self, temp_path: Path, fmt: str, job: dict[str, Any], profile: dict[str, Any], chapters: list[dict[str, Any]]) -> None:
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "txt":
            temp_path.write_text(self._render_txt(job, profile, chapters), encoding="utf-8")
        elif fmt == "markdown":
            temp_path.write_text(self._render_markdown(job, profile, chapters), encoding="utf-8")
        elif fmt == "docx":
            self._render_docx(temp_path, job, profile, chapters)
        elif fmt == "epub":
            self._render_epub(temp_path, job, profile, chapters)
        else:
            raise StoryError(422, "EXPORT_FORMAT_UNSUPPORTED", "不支持的导出格式。", {"format": fmt})

    def _render_txt(self, job: dict[str, Any], profile: dict[str, Any], chapters: list[dict[str, Any]]) -> str:
        lines = [profile["bookTitle"], f"作者：{profile['authorName'] or '未署名'}", ""]
        if job["mode"] == "review":
            lines.extend(["【审阅版】本文件可能包含章节缺口或发布前问题，请勿作为正式发布稿。", ""])
        for chapter in chapters:
            heading = _chapter_heading(profile["chapterTitleTemplate"], chapter["chapterNumber"], chapter["chapterTitle"])
            lines.extend([heading, ""])
            if chapter["missing"]:
                lines.extend(["【缺章水印】本章没有 current official ChapterCommit。", ""])
            else:
                lines.extend([chapter["contentMarkdown"], ""])
        if job["mode"] == "review":
            lines.extend(self._review_appendix(chapters))
        return "\n".join(lines).strip() + "\n"

    def _render_markdown(self, job: dict[str, Any], profile: dict[str, Any], chapters: list[dict[str, Any]]) -> str:
        lines = [f"# {profile['bookTitle']}", "", f"- 作者：{profile['authorName'] or '未署名'}", f"- 模式：{job['mode']}", f"- 章节范围：{job['chapterStart']}—{job['chapterEnd']}", ""]
        if profile["description"]:
            lines.extend(["## 简介", "", profile["description"], ""])
        if job["mode"] == "review":
            lines.extend(["> 【审阅版】本文件可能包含章节缺口或发布前问题，请勿作为正式发布稿。", ""])
        lines.extend(["## 目录", ""])
        for chapter in chapters:
            lines.append(f"- 第{chapter['chapterNumber']}章 {_plain_title(chapter['chapterTitle'], chapter['chapterNumber'])}{'（缺失）' if chapter['missing'] else ''}")
        lines.append("")
        for chapter in chapters:
            lines.extend([f"## {_chapter_heading(profile['chapterTitleTemplate'], chapter['chapterNumber'], chapter['chapterTitle'])}", ""])
            if chapter["missing"]:
                lines.extend(["> 【缺章水印】本章没有 current official ChapterCommit。", ""])
            else:
                lines.extend([chapter["contentMarkdown"], ""])
        if job["mode"] == "review":
            lines.extend(["## 问题附录", ""])
            lines.extend(self._review_appendix(chapters))
        return "\n".join(lines).strip() + "\n"

    def _review_appendix(self, chapters: list[dict[str, Any]]) -> list[str]:
        lines = ["问题附录："]
        has_issue = False
        for chapter in chapters:
            for issue in chapter["issueSummary"]:
                has_issue = True
                lines.append(f"- 第{chapter['chapterNumber']}章 {issue.get('code')}: {issue.get('suggestion', '')}")
        if not has_issue:
            lines.append("- 无阻断问题。")
        return lines

    def _render_docx(self, path: Path, job: dict[str, Any], profile: dict[str, Any], chapters: list[dict[str, Any]]) -> None:
        paragraphs = [profile["bookTitle"], f"作者：{profile['authorName'] or '未署名'}"]
        if job["mode"] == "review":
            paragraphs.append("【审阅版】本文件可能包含章节缺口或发布前问题，请勿作为正式发布稿。")
        for chapter in chapters:
            paragraphs.append(_chapter_heading(profile["chapterTitleTemplate"], chapter["chapterNumber"], chapter["chapterTitle"]))
            paragraphs.append("【缺章水印】本章没有 current official ChapterCommit。" if chapter["missing"] else chapter["contentMarkdown"])
        if job["mode"] == "review":
            paragraphs.extend(self._review_appendix(chapters))
        body = "".join(f"<w:p><w:r><w:t>{html.escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
        document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}<w:sectPr/></w:body></w:document>"""
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>""")
            package.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>""")
            package.writestr("word/document.xml", document)

    def _render_epub(self, path: Path, job: dict[str, Any], profile: dict[str, Any], chapters: list[dict[str, Any]]) -> None:
        title = html.escape(profile["bookTitle"])
        nav_items = []
        manifest_items = []
        spine_items = []
        chapter_docs: list[tuple[str, str]] = []
        for index, chapter in enumerate(chapters, start=1):
            name = f"chapter-{index:04d}.xhtml"
            heading = html.escape(_chapter_heading(profile["chapterTitleTemplate"], chapter["chapterNumber"], chapter["chapterTitle"]))
            body = "【缺章水印】本章没有 current official ChapterCommit。" if chapter["missing"] else chapter["contentMarkdown"]
            body_html = "".join(f"<p>{html.escape(line)}</p>" for line in body.splitlines() if line.strip())
            chapter_docs.append((name, f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN"><head><title>{heading}</title></head><body><h1>{heading}</h1>{body_html}</body></html>"""))
            nav_items.append(f'<li><a href="{name}">{heading}</a></li>')
            manifest_items.append(f'<item id="c{index}" href="{name}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="c{index}"/>')
        nav = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN"><head><title>目录</title></head><body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><h1>目录</h1><ol>{''.join(nav_items)}</ol></nav></body></html>"""
        opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">{job['id']}</dc:identifier><dc:title>{title}</dc:title><dc:language>zh-CN</dc:language></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>{''.join(manifest_items)}</manifest><spine>{''.join(spine_items)}</spine></package>"""
        with zipfile.ZipFile(path, "w") as package:
            package.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            package.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>""", compress_type=zipfile.ZIP_DEFLATED)
            package.writestr("EPUB/package.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
            package.writestr("EPUB/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
            for name, content in chapter_docs:
                package.writestr(f"EPUB/{name}", content, compress_type=zipfile.ZIP_DEFLATED)

    def _validate_frozen_sources(self, project_id: str, folder_path: str, export_id: str) -> None:
        with self.service.db.project(project_id, folder_path) as session:
            chapters = session.scalars(select(ExportJobChapter).where(ExportJobChapter.export_job_id == export_id)).all()
            for frozen in chapters:
                if frozen.missing:
                    continue
                commit = session.get(ChapterCommit, frozen.chapter_commit_id)
                draft = session.get(ChapterDraft, frozen.approved_draft_id)
                source = session.get(SourceVersion, frozen.source_version_id)
                snapshot = session.get(StateSnapshot, frozen.state_snapshot_id)
                drift = (
                    not commit or not commit.is_current or commit.revision != frozen.commit_revision or commit.checksum != frozen.commit_checksum
                    or not draft or draft.revision != frozen.draft_revision or draft.checksum != frozen.draft_checksum
                    or not source or source.revision != frozen.source_revision or source.checksum != frozen.source_checksum or source.status != "official"
                    or not snapshot or snapshot.revision != frozen.snapshot_revision
                )
                if drift:
                    raise StoryError(409, "EXPORT_SOURCE_REVISION_CONFLICT", "导出源在渲染期间发生变化。", {"chapterNumber": frozen.chapter_number})

    # ------------------------------------------------------------------
    # Artifacts and publication records
    # ------------------------------------------------------------------
    def artifact_path(self, project_id: str, export_id: str, artifact_id: str) -> Path:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, export_id)
            artifact = session.get(ExportArtifact, artifact_id)
            if not artifact or artifact.export_job_id != job.id or artifact.project_id != project.id:
                raise StoryError(404, "EXPORT_ARTIFACT_NOT_FOUND", "导出文件不存在。")
            if artifact.status != "available":
                raise StoryError(409, "EXPORT_ARTIFACT_UNAVAILABLE", "导出文件当前不可下载。")
            root = (Path(project.folder_path) / "exports").resolve()
            path = (Path(project.folder_path) / artifact.relative_path).resolve()
            if root != path and root not in path.parents:
                raise StoryError(403, "EXPORT_ARTIFACT_PATH_FORBIDDEN", "导出文件路径不安全。")
            if not path.is_file():
                raise StoryError(404, "EXPORT_ARTIFACT_FILE_MISSING", "导出实体文件缺失。")
            return path

    def create_publication_record(self, project_id: str, export_id: str, payload: PublicationRecordCreate, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            job = self._get_job(session, project.id, export_id)
            artifact = session.get(ExportArtifact, payload.artifact_id)
            if not artifact or artifact.project_id != project.id or artifact.export_job_id != job.id:
                raise StoryError(404, "EXPORT_ARTIFACT_NOT_FOUND", "导出文件不存在。")
            if artifact.status != "available":
                raise StoryError(409, "EXPORT_ARTIFACT_UNAVAILABLE", "只有可下载文件才能登记发布记录。")
            now = _now()
            record = PublicationRecord(
                id=str(uuid4()),
                project_id=project.id,
                export_job_id=job.id,
                artifact_id=artifact.id,
                platform=payload.platform,
                external_work_ref=payload.external_work_ref,
                external_chapter_ref=payload.external_chapter_ref,
                published_at=payload.published_at or now,
                notes=payload.notes,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.add(self.service._audit("publication_record.created", "publication_record", record.id, {"requestId": request_id}, request_id))
            session.flush()
            return self._publication_dict(record)

    def list_publication_records(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._publication_dict(row) for row in session.scalars(
                select(PublicationRecord).where(PublicationRecord.project_id == project.id).order_by(PublicationRecord.published_at.desc())
            ).all()]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def _get_job(self, session: Session, project_id: str, export_id: str) -> ExportJob:
        job = session.get(ExportJob, export_id)
        if not job or job.project_id != project_id:
            raise StoryError(404, "EXPORT_JOB_NOT_FOUND", "导出任务不存在。")
        return job

    def _job_dict(self, session: Session, job: ExportJob, *, include_details: bool) -> dict[str, Any]:
        result = {
            "id": job.id,
            "projectId": job.project_id,
            "mode": job.mode,
            "chapterStart": job.chapter_start,
            "chapterEnd": job.chapter_end,
            "formats": loads(job.formats_json) or [],
            "idempotencyKey": job.idempotency_key,
            "status": job.status,
            "frozenManifest": loads(job.frozen_manifest_json) or {},
            "readiness": loads(job.readiness_json) or {},
            "stopReason": job.stop_reason,
            "diagnostic": loads(job.diagnostic_json) if job.diagnostic_json else None,
            "revision": job.revision,
            "createdAt": job.created_at,
            "startedAt": job.started_at,
            "completedAt": job.completed_at,
            "updatedAt": job.updated_at,
            "chapters": [],
            "artifacts": [],
        }
        if include_details:
            result["chapters"] = [self._job_chapter_dict(row) for row in session.scalars(
                select(ExportJobChapter).where(ExportJobChapter.export_job_id == job.id).order_by(ExportJobChapter.sequence_number)
            ).all()]
            result["artifacts"] = [self._artifact_dict(row) for row in session.scalars(
                select(ExportArtifact).where(ExportArtifact.export_job_id == job.id).order_by(ExportArtifact.created_at)
            ).all()]
        return result

    @staticmethod
    def _job_chapter_dict(row: ExportJobChapter) -> dict[str, Any]:
        return {
            "id": row.id,
            "projectId": row.project_id,
            "exportJobId": row.export_job_id,
            "chapterNumber": row.chapter_number,
            "sequenceNumber": row.sequence_number,
            "chapterTitle": row.chapter_title,
            "chapterCommitId": row.chapter_commit_id,
            "approvedDraftId": row.approved_draft_id,
            "sourceVersionId": row.source_version_id,
            "stateSnapshotId": row.state_snapshot_id,
            "commitRevision": row.commit_revision,
            "sourceRevision": row.source_revision,
            "draftRevision": row.draft_revision,
            "snapshotRevision": row.snapshot_revision,
            "commitChecksum": row.commit_checksum,
            "draftChecksum": row.draft_checksum,
            "sourceChecksum": row.source_checksum,
            "qualitySummary": loads(row.quality_summary_json) or {},
            "issueSummary": loads(row.issue_summary_json) or [],
            "contentMarkdown": row.content_markdown,
            "missing": row.missing,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }

    @staticmethod
    def _artifact_dict(row: ExportArtifact) -> dict[str, Any]:
        return {
            "id": row.id,
            "projectId": row.project_id,
            "exportJobId": row.export_job_id,
            "format": row.format,
            "fileName": row.file_name,
            "mimeType": row.mime_type,
            "byteSize": row.byte_size,
            "sha256": row.sha256,
            "status": row.status,
            "isCurrent": row.is_current,
            "revision": row.revision,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }

    @staticmethod
    def _publication_dict(row: PublicationRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "projectId": row.project_id,
            "exportJobId": row.export_job_id,
            "artifactId": row.artifact_id,
            "platform": row.platform,
            "externalWorkRef": row.external_work_ref,
            "externalChapterRef": row.external_chapter_ref,
            "publishedAt": row.published_at,
            "notes": row.notes,
            "revision": row.revision,
            "createdAt": row.created_at,
            "updatedAt": row.updated_at,
        }

    @staticmethod
    def _profile_dict(profile: ExportProfile) -> dict[str, Any]:
        return {
            "projectId": profile.project_id,
            "defaultFormats": loads(profile.default_formats_json) or list(FORMATS),
            "bookTitle": profile.book_title,
            "authorName": profile.author_name,
            "description": profile.description,
            "chapterTitleTemplate": profile.chapter_title_template,
            "includeQualitySummary": profile.include_quality_summary,
            "revision": profile.revision,
            "createdAt": profile.created_at,
            "updatedAt": profile.updated_at,
        }

    def _requested_formats(self, project_id: str, folder_path: str, requested: list[str] | None) -> list[str]:
        if requested:
            return self._normalize_formats(requested)
        with self.service.db.project_write(project_id, folder_path) as session:
            profile = self._get_or_create_profile(session, project_id, self.service.get_project(project_id).title)
            return self._normalize_formats(loads(profile.default_formats_json) or list(FORMATS))

    @staticmethod
    def _normalize_formats(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if value not in FORMATS:
                raise StoryError(422, "EXPORT_FORMAT_UNSUPPORTED", "不支持的导出格式。", {"format": value})
            if value not in result:
                result.append(value)
        if not result:
            raise StoryError(422, "EXPORT_FORMAT_REQUIRED", "至少选择一种导出格式。")
        return result

    @staticmethod
    def _artifact_file_name(title: str, mode: str, start: int, end: int, fmt: str) -> str:
        return f"{_file_safe(title)}-{mode}-{start:04d}-{end:04d}.{FORMAT_EXT[fmt]}"

    def _mark_export_failed(self, project_id: str, folder_path: str, export_id: str, status: str, code: str, diagnostic: dict[str, Any]) -> None:
        with self.service.db.project_write(project_id, folder_path) as session:
            job = session.get(ExportJob, export_id)
            if not job:
                return
            job.status = status
            job.stop_reason = code
            job.diagnostic_json = dumps(diagnostic)
            job.completed_at = _now()
            job.updated_at = _now()
            job.revision += 1

    @staticmethod
    def _remove_temp_files(rendered: list[RenderedArtifact]) -> None:
        for artifact in rendered:
            if artifact.temp_path.exists():
                artifact.temp_path.unlink()

    @staticmethod
    def _remove_paths(paths: list[Path]) -> None:
        for path in paths:
            if path.exists() and path.is_file():
                path.unlink()

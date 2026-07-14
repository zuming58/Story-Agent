from __future__ import annotations

import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from story_agent_api.models import (
    AutomationRunItem,
    ChapterCommit,
    ChapterContract,
    ChapterDraft,
    ChapterExtraction,
    ChapterJob,
    ExportArtifact,
    ExportJob,
    QualityFinding,
    RetrievalIndexState,
    SourceVersion,
    StateSnapshot,
    utc_now,
)
from story_agent_api.services import dumps, loads, stable_digest


def _project(client: TestClient, title: str = "Export Story") -> dict:
    response = client.post("/api/v1/projects", json={"title": title, "mode": "long-form", "totalChapters": 12})
    assert response.status_code == 201
    return response.json()


def _seed_official_chapter(
    client: TestClient,
    project_id: str,
    chapter: int,
    *,
    content: str | None = None,
    current: bool = True,
    extraction_status: str = "validated",
    source_status: str = "official",
    with_snapshot: bool = True,
    quality_blocker: bool = False,
) -> dict[str, str]:
    service = client.app.state.story_service
    project = service.get_project(project_id)
    now = utc_now()
    content = content or f"Chapter {chapter} official body.\n\nOnly committed text is exported."
    draft_checksum = stable_digest(content)
    source_checksum = stable_digest({"chapter": chapter, "draft": draft_checksum})
    with service.db.project_write(project.id, project.folder_path) as session:
        contract = ChapterContract(
            id=str(uuid4()),
            project_id=project.id,
            chapter_number=chapter,
            title=f"Chapter {chapter}",
            status="locked",
            created_at=now,
            updated_at=now,
            locked_at=now,
        )
        job = ChapterJob(
            id=str(uuid4()),
            project_id=project.id,
            chapter_contract_id=contract.id,
            status="completed",
            created_at=now,
            updated_at=now,
            finished_at=now,
        )
        draft = ChapterDraft(
            id=str(uuid4()),
            project_id=project.id,
            chapter_job_id=job.id,
            chapter_contract_id=contract.id,
            version_number=1,
            kind="generated",
            content_markdown=content,
            word_count=len(content),
            checksum=draft_checksum,
            status="approved",
            is_current=True,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        extraction = ChapterExtraction(
            id=str(uuid4()),
            project_id=project.id,
            chapter_draft_id=draft.id,
            payload_json=dumps({"summary": f"chapter {chapter}", "entities": [], "facts": [], "events": []}),
            status=extraction_status,
            checksum=stable_digest({"chapter": chapter, "extraction": extraction_status}),
            created_at=now,
            updated_at=now,
        )
        source = SourceVersion(
            id=str(uuid4()),
            project_id=project.id,
            source_id=f"chapter-{chapter:04d}",
            version_number=1,
            source_kind="chapter",
            status=source_status,
            checksum=source_checksum,
            summary=f"chapter {chapter}",
            payload_json=dumps({"summary": f"chapter {chapter}"}),
            revision=2 if source_status == "official" else 1,
            created_at=now,
            updated_at=now,
        )
        snapshot = None
        if with_snapshot:
            snapshot = StateSnapshot(
                id=str(uuid4()),
                project_id=project.id,
                snapshot_number=chapter,
                source_version_id=source.id,
                summary_json=dumps({"chapter": chapter}),
                checksum=stable_digest({"snapshot": chapter}),
                revision=1,
                created_at=now,
                updated_at=now,
            )
        commit = ChapterCommit(
            id=str(uuid4()),
            project_id=project.id,
            chapter_number=chapter,
            chapter_contract_id=contract.id,
            approved_draft_id=draft.id,
            source_version_id=source.id,
            state_snapshot_id=snapshot.id if snapshot else None,
            quality_summary_json=dumps({"blockers": 0, "errors": 0}),
            checksum=stable_digest({"draft": draft_checksum, "sourceVersionId": source.id}),
            status="official",
            is_current=current,
            revision=1,
            committed_at=now,
            created_at=now,
        )
        session.add_all([contract, job, draft, extraction, source, commit])
        if snapshot:
            session.add(snapshot)
        retrieval = session.get(RetrievalIndexState, project.id)
        if not retrieval:
            retrieval = RetrievalIndexState(
                project_id=project.id,
                indexed_count=1,
                last_rebuilt_at=now,
                vector_available=True,
                checksum="ready",
                updated_at=now,
            )
            session.add(retrieval)
        else:
            retrieval.indexed_count = max(retrieval.indexed_count, chapter)
            retrieval.last_rebuilt_at = now
            retrieval.vector_available = True
            retrieval.checksum = "ready"
            retrieval.updated_at = now
        if quality_blocker:
            session.add(QualityFinding(
                id=str(uuid4()),
                project_id=project.id,
                quality_run_id=str(uuid4()),
                chapter_draft_id=draft.id,
                rule_code="TEST_BLOCKER",
                severity="blocker",
                category="test",
                message="blocked",
                fingerprint=stable_digest({"blocked": draft.id}),
                status="open",
                created_at=now,
                updated_at=now,
            ))
        session.flush()
        return {"commit": commit.id, "draft": draft.id, "source": source.id, "snapshot": snapshot.id if snapshot else ""}


def _export(client: TestClient, project_id: str, **overrides: object) -> dict:
    payload = {"mode": "formal", "chapterStart": 1, "chapterEnd": 2, "formats": ["txt", "markdown", "docx", "epub"]}
    payload.update(overrides)
    response = client.post(f"/api/v1/projects/{project_id}/exports", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_formal_export_renders_four_formats_from_current_official_commits(client: TestClient) -> None:
    project = _project(client)
    _seed_official_chapter(client, project["id"], 1, content="Official one, not a candidate.")
    _seed_official_chapter(client, project["id"], 2, content="Official two.")

    readiness = client.post(
        f"/api/v1/projects/{project['id']}/exports/readiness",
        json={"mode": "formal", "chapterStart": 1, "chapterEnd": 2, "formats": ["txt", "markdown", "docx", "epub"]},
    )
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is True, readiness.json()

    job = _export(client, project["id"], idempotencyKey="same-export")
    duplicate = _export(client, project["id"], idempotencyKey="same-export")
    assert duplicate["id"] == job["id"]
    assert job["status"] == "completed", job.get("diagnostic")
    assert {artifact["format"] for artifact in job["artifacts"]} == {"txt", "markdown", "docx", "epub"}
    assert len({artifact["sha256"] for artifact in job["artifacts"]}) == 4
    manifest_commits = {item["chapterCommitId"] for item in job["frozenManifest"]["chapters"]}
    assert len(manifest_commits) == 2

    artifacts = {artifact["format"]: artifact for artifact in job["artifacts"]}
    txt = client.get(f"/api/v1/projects/{project['id']}/exports/{job['id']}/artifacts/{artifacts['txt']['id']}/download")
    assert txt.status_code == 200
    assert "Official one" in txt.content.decode("utf-8")

    markdown = client.get(f"/api/v1/projects/{project['id']}/exports/{job['id']}/artifacts/{artifacts['markdown']['id']}/download")
    assert markdown.status_code == 200
    assert "# Export Story" in markdown.text

    docx_path = Path(client.app.state.story_service.phase9.artifact_path(project["id"], job["id"], artifacts["docx"]["id"]))
    with zipfile.ZipFile(docx_path) as package:
        assert "[Content_Types].xml" in package.namelist()
        assert "_rels/.rels" in package.namelist()
        assert "word/document.xml" in package.namelist()
        assert "word/styles.xml" in package.namelist()
        assert "word/settings.xml" in package.namelist()
        document_xml = package.read("word/document.xml").decode("utf-8")
        styles_xml = package.read("word/styles.xml").decode("utf-8")
        assert 'w:instr="TOC' in document_xml
        assert 'w:type="page"' in document_xml
        assert 'w:val="Heading1"' in document_xml
        assert 'w:eastAsia="等线"' in styles_xml

    epub_path = Path(client.app.state.story_service.phase9.artifact_path(project["id"], job["id"], artifacts["epub"]["id"]))
    with zipfile.ZipFile(epub_path) as package:
        assert package.namelist()[0] == "mimetype"
        assert "META-INF/container.xml" in package.namelist()
        assert "EPUB/package.opf" in package.namelist()
        assert "EPUB/nav.xhtml" in package.namelist()
        assert "EPUB/chapter-0001.xhtml" in package.namelist()


def test_readiness_blocks_gap_non_current_quality_extraction_state_retrieval_and_automation(client: TestClient) -> None:
    project = _project(client)
    _seed_official_chapter(client, project["id"], 1, current=False)
    _seed_official_chapter(client, project["id"], 2, quality_blocker=True)
    _seed_official_chapter(client, project["id"], 3, extraction_status="candidate")
    _seed_official_chapter(client, project["id"], 4, with_snapshot=False)
    service = client.app.state.story_service
    catalog = service.get_project(project["id"])
    now = utc_now()
    with service.db.project_write(catalog.id, catalog.folder_path) as session:
        retrieval = session.get(RetrievalIndexState, catalog.id)
        retrieval.last_rebuilt_at = None
        session.add(AutomationRunItem(
            id=str(uuid4()),
            project_id=catalog.id,
            automation_run_id=str(uuid4()),
            chapter_number=2,
            sequence_number=1,
            status="isolated",
            created_at=now,
            updated_at=now,
        ))

    response = client.post(
        f"/api/v1/projects/{project['id']}/exports/readiness",
        json={"mode": "formal", "chapterStart": 1, "chapterEnd": 5, "formats": ["txt"]},
    )
    assert response.status_code == 200
    codes = {issue["code"] for issue in response.json()["issues"]}
    assert {
        "EXPORT_COMMIT_NOT_CURRENT",
        "EXPORT_QUALITY_BLOCKED",
        "EXPORT_EXTRACTION_INVALID",
        "EXPORT_STATE_REFERENCE_BROKEN",
        "EXPORT_RETRIEVAL_STALE",
        "EXPORT_AUTOMATION_ISOLATED",
        "EXPORT_CHAPTER_GAP",
    }.issubset(codes)

    blocked = client.post(f"/api/v1/projects/{project['id']}/exports", json={"mode": "formal", "chapterStart": 1, "chapterEnd": 5, "formats": ["txt"]})
    assert blocked.status_code == 201
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["artifacts"] == []


def test_review_export_allows_missing_chapters_and_adds_watermark_appendix(client: TestClient) -> None:
    project = _project(client)
    _seed_official_chapter(client, project["id"], 1, content="Existing official body.")
    job = _export(client, project["id"], mode="review", chapterEnd=3, formats=["markdown", "epub"])
    assert job["status"] == "completed", job
    assert [chapter["missing"] for chapter in job["chapters"]] == [False, True, True]
    artifact = next(item for item in job["artifacts"] if item["format"] == "markdown")
    response = client.get(f"/api/v1/projects/{project['id']}/exports/{job['id']}/artifacts/{artifact['id']}/download")
    assert response.status_code == 200
    assert "Existing official body." in response.text
    assert "review" in response.text
    assert "EXPORT_CHAPTER_GAP" in response.text
    epub = next(item for item in job["artifacts"] if item["format"] == "epub")
    epub_path = Path(client.app.state.story_service.phase9.artifact_path(project["id"], job["id"], epub["id"]))
    with zipfile.ZipFile(epub_path) as package:
        assert "EPUB/review-notice.xhtml" in package.namelist()
        assert "EPUB/review-appendix.xhtml" in package.namelist()
        assert "EXPORT_CHAPTER_GAP" in package.read("EPUB/review-appendix.xhtml").decode("utf-8")


def test_revision_drift_and_cancel_leave_no_downloadable_artifacts(client: TestClient, monkeypatch) -> None:
    project = _project(client)
    ids = _seed_official_chapter(client, project["id"], 1)
    service = client.app.state.story_service
    original_render = service.phase9._render_artifacts

    def drift_after_render(project_obj, job, profile):
        rendered = original_render(project_obj, job, profile)
        with service.db.project_write(project_obj.id, project_obj.folder_path) as session:
            commit = session.get(ChapterCommit, ids["commit"])
            commit.revision += 1
            commit.checksum = stable_digest({"changed": commit.id})
        return rendered

    monkeypatch.setattr(service.phase9, "_render_artifacts", drift_after_render)
    drifted = client.post(f"/api/v1/projects/{project['id']}/exports", json={"mode": "formal", "chapterStart": 1, "chapterEnd": 1, "formats": ["txt"]})
    assert drifted.status_code == 201
    assert drifted.json()["status"] == "blocked"
    assert drifted.json()["stopReason"] == "EXPORT_SOURCE_REVISION_CONFLICT"
    assert drifted.json()["artifacts"] == []

    monkeypatch.setattr(service.phase9, "_render_artifacts", original_render)
    cancelled = _export(client, project["id"], chapterEnd=1, formats=["txt"], idempotencyKey="cancel-fixture")
    catalog = service.get_project(project["id"])
    with service.db.project_write(catalog.id, catalog.folder_path) as session:
        running = ExportJob(
            id="queued-export",
            project_id=catalog.id,
            mode="formal",
            chapter_start=1,
            chapter_end=1,
            formats_json=dumps(["txt"]),
            status="queued",
            frozen_manifest_json="{}",
            readiness_json="{}",
            revision=1,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(running)
    cancel = client.post(f"/api/v1/projects/{project['id']}/exports/queued-export/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    assert cancelled["status"] == "completed"


def test_download_is_scoped_to_artifact_id_project_and_safe_path(client: TestClient) -> None:
    first = _project(client, "First")
    second = _project(client, "Second")
    _seed_official_chapter(client, first["id"], 1)
    job = _export(client, first["id"], chapterEnd=1, formats=["txt"])
    artifact = job["artifacts"][0]

    cross = client.get(f"/api/v1/projects/{second['id']}/exports/{job['id']}/artifacts/{artifact['id']}/download")
    assert cross.status_code == 404
    guessed = client.get(f"/api/v1/projects/{first['id']}/exports/{job['id']}/artifacts/not-real/download")
    assert guessed.status_code == 404

    service = client.app.state.story_service
    catalog = service.get_project(first["id"])
    with service.db.project_write(catalog.id, catalog.folder_path) as session:
        row = session.get(ExportArtifact, artifact["id"])
        row.relative_path = "../project.json"
    traversal = client.get(f"/api/v1/projects/{first['id']}/exports/{job['id']}/artifacts/{artifact['id']}/download")
    assert traversal.status_code == 403


def test_export_rejects_empty_formats_out_of_bounds_and_broken_source_chain(client: TestClient) -> None:
    project = _project(client)
    ids = _seed_official_chapter(client, project["id"], 1)

    empty = client.post(
        f"/api/v1/projects/{project['id']}/exports/readiness",
        json={"mode": "formal", "chapterStart": 1, "chapterEnd": 1, "formats": []},
    )
    assert empty.status_code == 422
    assert empty.json()["code"] == "EXPORT_FORMAT_REQUIRED"

    out_of_bounds = client.post(
        f"/api/v1/projects/{project['id']}/exports",
        json={"mode": "formal", "chapterStart": 1, "chapterEnd": 13, "formats": ["txt"]},
    )
    assert out_of_bounds.status_code == 422
    assert out_of_bounds.json()["code"] == "EXPORT_RANGE_OUT_OF_BOUNDS"

    service = client.app.state.story_service
    catalog = service.get_project(project["id"])
    with service.db.project_write(catalog.id, catalog.folder_path) as session:
        snapshot = session.get(StateSnapshot, ids["snapshot"])
        snapshot.source_version_id = str(uuid4())
    broken = client.post(
        f"/api/v1/projects/{project['id']}/exports/readiness",
        json={"mode": "formal", "chapterStart": 1, "chapterEnd": 1, "formats": ["txt"]},
    )
    assert broken.status_code == 200
    assert broken.json()["ready"] is False
    assert {issue["code"] for issue in broken.json()["issues"]} == {"EXPORT_STATE_REFERENCE_BROKEN"}


def test_tampered_artifact_cannot_be_downloaded_or_published(client: TestClient) -> None:
    project = _project(client)
    _seed_official_chapter(client, project["id"], 1)
    job = _export(client, project["id"], chapterEnd=1, formats=["txt"])
    artifact = job["artifacts"][0]
    service = client.app.state.story_service
    path = service.phase9.artifact_path(project["id"], job["id"], artifact["id"])
    with path.open("ab") as handle:
        handle.write(b"tampered")

    download = client.get(f"/api/v1/projects/{project['id']}/exports/{job['id']}/artifacts/{artifact['id']}/download")
    assert download.status_code == 409
    assert download.json()["code"] == "EXPORT_ARTIFACT_INTEGRITY_FAILED"
    publication = client.post(
        f"/api/v1/projects/{project['id']}/exports/{job['id']}/publication-records",
        json={"artifactId": artifact["id"], "platform": "manual-test"},
    )
    assert publication.status_code == 409
    assert publication.json()["code"] == "EXPORT_ARTIFACT_INTEGRITY_FAILED"


def test_interrupted_resume_reuses_snapshot_and_backup_restore_marks_artifacts_missing(client: TestClient, monkeypatch) -> None:
    project = _project(client)
    _seed_official_chapter(client, project["id"], 1)
    service = client.app.state.story_service

    def fail_render(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(service.phase9, "_render_artifacts", fail_render)
    failed = client.post(f"/api/v1/projects/{project['id']}/exports", json={"mode": "formal", "chapterStart": 1, "chapterEnd": 1, "formats": ["txt"]})
    assert failed.status_code == 201
    failed_job = failed.json()
    assert failed_job["status"] == "failed"

    monkeypatch.undo()
    resumed = client.post(f"/api/v1/projects/{project['id']}/exports/{failed_job['id']}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"

    publication = client.post(
        f"/api/v1/projects/{project['id']}/exports/{resumed.json()['id']}/publication-records",
        json={"artifactId": resumed.json()["artifacts"][0]["id"], "platform": "manual-test", "externalWorkRef": "work-1"},
    )
    assert publication.status_code == 201
    assert client.get(f"/api/v1/projects/{project['id']}/publication-records").json()[0]["platform"] == "manual-test"

    with service.db.project_write(project["id"], service.get_project(project["id"]).folder_path) as session:
        running = session.scalar(select(ExportJob).where(ExportJob.project_id == project["id"]))
        running.status = "rendering"
    service.phase9.recover_interrupted_exports()
    assert client.get(f"/api/v1/projects/{project['id']}/exports/{running.id}").json()["status"] == "interrupted"

    backup = client.post(f"/api/v1/projects/{project['id']}/backups")
    assert backup.status_code == 201
    archive = Path(backup.json()["archivePath"])
    restored = client.post("/api/v1/projects/restore", files={"backup": (archive.name, archive.read_bytes(), "application/zip")})
    assert restored.status_code == 201, restored.text
    restored_id = restored.json()["id"]
    restored_jobs = client.get(f"/api/v1/projects/{restored_id}/exports").json()
    assert restored_jobs
    assert restored_jobs[0]["projectId"] == restored_id
    assert restored_jobs[0]["frozenManifest"]["projectId"] == restored_id
    restored_artifacts = client.get(f"/api/v1/projects/{restored_id}/exports/{restored_jobs[0]['id']}").json()["artifacts"]
    assert restored_artifacts[0]["status"] == "missing"
    unavailable = client.get(f"/api/v1/projects/{restored_id}/exports/{restored_jobs[0]['id']}/artifacts/{restored_artifacts[0]['id']}/download")
    assert unavailable.status_code == 409
    assert client.get(f"/api/v1/projects/{restored_id}/publication-records").json()[0]["platform"] == "manual-test"
    restored_catalog = service.get_project(restored_id)
    with service.db.project(restored_id, restored_catalog.folder_path) as session:
        artifact_row = session.get(ExportArtifact, restored_artifacts[0]["id"])
        assert loads(artifact_row.manifest_json)["projectId"] == restored_id

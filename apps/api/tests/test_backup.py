from __future__ import annotations

import io
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import story_agent_api.main as main_module


def test_backup_manifest_and_restore_as_new_project(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    backup = client.post(f"/api/v1/projects/{project_id}/backups")
    assert backup.status_code == 201
    manifest = backup.json()
    archive = Path(manifest["archivePath"])
    assert archive.exists()
    with zipfile.ZipFile(archive) as package:
        stored_manifest = json.loads(package.read("manifest.json"))
        assert "story.db" in stored_manifest["files"]
        assert "canon/story-core.md" in stored_manifest["files"]

    restored = client.post(
        "/api/v1/projects/restore",
        files={"backup": (archive.name, archive.read_bytes(), "application/zip")},
    )
    assert restored.status_code == 201, restored.text
    restored_project = restored.json()
    assert restored_project["id"] != project_id
    assert "恢复" in restored_project["title"]
    assert restored_project["currentChapter"] == demo_project["currentChapter"]
    restored_plan = client.get(f"/api/v1/projects/{restored_project['id']}/plan")
    assert restored_plan.status_code == 200
    assert len(restored_plan.json()["milestones"]) == 5

    listed = client.get(f"/api/v1/projects/{project_id}/backups")
    assert listed.status_code == 200
    assert listed.json()[0]["backupId"] == manifest["backupId"]
    assert listed.json()[0]["isValid"] is True
    downloaded = client.get(f"/api/v1/projects/{project_id}/backups/{manifest['backupId']}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/zip")


def test_corrupt_backup_is_rejected(client: TestClient, demo_project: dict) -> None:
    backup = client.post(f"/api/v1/projects/{demo_project['id']}/backups").json()
    archive = Path(backup["archivePath"])
    output = io.BytesIO()
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "project.json":
                content += b"corrupt"
            target.writestr(name, content)
    response = client.post(
        "/api/v1/projects/restore",
        files={"backup": ("corrupt.zip", output.getvalue(), "application/zip")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "BACKUP_CHECKSUM_MISMATCH"


def test_backup_restore_rejects_path_traversal(client: TestClient, demo_project: dict) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", json.dumps({"backupId": "bad", "projectId": demo_project["id"], "projectTitle": "bad", "createdAt": "2026-07-12T00:00:00Z", "files": {}}))
        package.writestr("../escape.txt", "nope")
    response = client.post(
        "/api/v1/projects/restore",
        files={"backup": ("traversal.zip", output.getvalue(), "application/zip")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_BACKUP_PATH"


def test_backup_restore_rejects_windows_path_traversal(client: TestClient, demo_project: dict) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", json.dumps({"backupId": "bad", "projectId": demo_project["id"], "projectTitle": "bad", "createdAt": "2026-07-12T00:00:00Z", "files": {}}))
        package.writestr("..\\escape.txt", "nope")
    response = client.post(
        "/api/v1/projects/restore",
        files={"backup": ("traversal.zip", output.getvalue(), "application/zip")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_BACKUP_PATH"


def test_corrupt_manifest_does_not_break_backup_listing(client: TestClient, demo_project: dict) -> None:
    backup_dir = Path(demo_project["folderPath"]) / "backups"
    archive = backup_dir / "broken-manifest.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", "{not-json")

    response = client.get(f"/api/v1/projects/{demo_project['id']}/backups")
    assert response.status_code == 200
    broken = next(item for item in response.json() if item["archivePath"].endswith("broken-manifest.zip"))
    assert broken["isValid"] is False
    downloaded = client.get(f"/api/v1/projects/{demo_project['id']}/backups/{broken['backupId']}/download")
    assert downloaded.status_code == 200


def test_restore_upload_limit_is_enforced_and_temp_file_is_removed(client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "MAX_BACKUP_UPLOAD_BYTES", 32)
    before = set(data_dir.glob("*.zip"))
    response = client.post(
        "/api/v1/projects/restore",
        files={"backup": ("oversized.zip", b"x" * 64, "application/zip")},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "BACKUP_UPLOAD_TOO_LARGE"
    assert set(data_dir.glob("*.zip")) == before


def test_restore_invalid_story_database_rolls_back_new_catalog_and_folder(client: TestClient, demo_project: dict, data_dir: Path) -> None:
    project_json = json.dumps({
        "id": demo_project["id"],
        "title": demo_project["title"],
        "mode": demo_project["mode"],
        "currentChapter": demo_project["currentChapter"],
        "totalChapters": demo_project["totalChapters"],
    }, ensure_ascii=False).encode("utf-8")
    empty_database = b""
    manifest = {
        "backupId": "invalid-db",
        "projectId": demo_project["id"],
        "projectTitle": demo_project["title"],
        "createdAt": "2026-07-12T00:00:00+00:00",
        "files": {
            "project.json": hashlib.sha256(project_json).hexdigest(),
            "story.db": hashlib.sha256(empty_database).hexdigest(),
        },
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("project.json", project_json)
        package.writestr("story.db", empty_database)
        package.writestr("manifest.json", json.dumps(manifest))

    before_projects = client.get("/api/v1/projects").json()
    before_folders = set((data_dir / "projects").iterdir())
    response = client.post(
        "/api/v1/projects/restore",
        files={"backup": ("invalid-db.zip", output.getvalue(), "application/zip")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_BACKUP_DATABASE"
    assert client.get("/api/v1/projects").json() == before_projects
    assert set((data_dir / "projects").iterdir()) == before_folders

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient


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
    restored_plan = client.get(f"/api/v1/projects/{restored_project['id']}/plan")
    assert restored_plan.status_code == 200
    assert len(restored_plan.json()["milestones"]) == 5


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

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from story_agent_api.models import ChapterCommit, PlanNode, ShortStoryOrigin, ShortStoryStrategy, utc_now
from story_agent_api.services import dumps

from test_phase11_adaptation import _ensure_foundation, _project, _valid_strategy


def _ready_short_story_strategy(client: TestClient) -> tuple[dict, dict]:
    source = _project(client, "Long source for short story")
    _ensure_foundation(client, source["id"])
    workspace = client.post(
        f"/api/v1/projects/{source['id']}/adaptation-workspaces",
        json={"name": "Short story production", "kind": "short_story", "targetWordCount": 12000, "targetChapterCount": 6},
    ).json()
    service = client.app.state.story_service
    service.phase11._complete_role = lambda *args, **kwargs: (dumps(_valid_strategy()), "phase12-local-strategy")
    proposal = client.post(
        f"/api/v1/projects/{source['id']}/adaptation-workspaces/{workspace['id']}/short-story-proposals",
        json={"expectedWorkspaceRevision": workspace["revision"], "idempotencyKey": "phase12-strategy"},
    )
    assert proposal.status_code == 201, proposal.text
    applied = client.post(
        f"/api/v1/adaptation-proposals/{proposal.json()['id']}/apply",
        json={"expectedRevision": proposal.json()["revision"]},
    )
    assert applied.status_code == 200, applied.text
    current = client.get(f"/api/v1/projects/{source['id']}/adaptation-workspaces/{workspace['id']}")
    assert current.status_code == 200
    return source, current.json()


def _materialize(client: TestClient, source: dict, workspace: dict, *, key: str = "phase12-materialize") -> dict:
    response = client.post(
        f"/api/v1/projects/{source['id']}/adaptation-workspaces/{workspace['id']}/materialize-short-story",
        json={"expectedWorkspaceRevision": workspace["revision"], "idempotencyKey": key},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_native_short_form_project_range_and_initial_progress(client: TestClient) -> None:
    created = client.post(
        "/api/v1/projects",
        json={"title": "Native short story", "mode": "short-form", "totalChapters": 12},
    )
    assert created.status_code == 201, created.text
    assert created.json()["mode"] == "short-form"
    assert created.json()["currentChapter"] == 0
    assert created.json()["totalChapters"] == 12

    rejected = client.post(
        "/api/v1/projects",
        json={"title": "Too long", "mode": "short-form", "totalChapters": 31},
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "SHORT_STORY_CHAPTER_RANGE"


def test_materialization_is_isolated_idempotent_and_reuses_pipeline_contracts(client: TestClient) -> None:
    source, workspace = _ready_short_story_strategy(client)
    before = client.get(f"/api/v1/projects/{source['id']}").json()
    result = _materialize(client, source, workspace)
    target = result["targetProject"]

    assert target["id"] != source["id"]
    assert target["mode"] == "short-form"
    assert target["currentChapter"] == 0
    assert target["totalChapters"] == 6
    after = client.get(f"/api/v1/projects/{source['id']}").json()
    assert after["currentChapter"] == before["currentChapter"]
    assert after["totalChapters"] == before["totalChapters"]

    service = client.app.state.story_service
    source_project = service.get_project(source["id"])
    with service.db.project(source_project.id, source_project.folder_path) as session:
        assert session.scalar(select(ChapterCommit).where(ChapterCommit.project_id == source_project.id)) is None

    origin = client.get(f"/api/v1/projects/{target['id']}/short-story/origin")
    assert origin.status_code == 200, origin.text
    assert origin.json()["sourceProjectId"] == source["id"]
    assert origin.json()["sourceWorkspaceId"] == workspace["id"]
    assert origin.json()["targetProjectId"] == target["id"]

    readiness = client.get(f"/api/v1/projects/{target['id']}/short-story/readiness")
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["ready"] is True
    plan = client.get(f"/api/v1/projects/{target['id']}/plan").json()
    beats = plan["milestones"][0]["chapterBeats"]
    assert [beat["chapterNumber"] for beat in beats] == list(range(1, 7))

    contract = client.post(
        f"/api/v1/projects/{target['id']}/chapter-contracts/derive",
        json={"chapterNumber": 1, "targetWordsMin": 1000, "targetWordsMax": 3000},
    )
    assert contract.status_code == 200, contract.text
    assert contract.json()["allowedScope"]["paceBudget"]["majorEvents"] == ["hook"]
    assert contract.json()["allowedScope"]["shortStory"]["targetTotalWords"] == 12000

    beyond = client.post(
        f"/api/v1/projects/{target['id']}/chapter-contracts/derive",
        json={"chapterNumber": 31},
    )
    assert beyond.status_code == 422
    assert beyond.json()["code"] == "SHORT_STORY_CHAPTER_RANGE"

    duplicate = _materialize(client, source, workspace)
    assert duplicate["targetProject"]["id"] == target["id"]
    conflict = client.post(
        f"/api/v1/projects/{source['id']}/adaptation-workspaces/{workspace['id']}/materialize-short-story",
        json={
            "expectedWorkspaceRevision": workspace["revision"],
            "idempotencyKey": "phase12-materialize",
            "targetTitle": "Different target",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "SHORT_STORY_MATERIALIZE_IDEMPOTENCY_CONFLICT"

    partial_export = client.post(
        f"/api/v1/projects/{target['id']}/exports/readiness",
        json={"mode": "formal", "chapterStart": 1, "chapterEnd": 5, "formats": ["txt"]},
    )
    assert partial_export.status_code == 422
    assert partial_export.json()["code"] == "SHORT_STORY_EXPORT_RANGE"


def test_materialization_blocks_source_drift_invalid_budget_and_cross_project_access(client: TestClient) -> None:
    source, workspace = _ready_short_story_strategy(client)
    other = _project(client, "Other project")
    cross = client.post(
        f"/api/v1/projects/{other['id']}/adaptation-workspaces/{workspace['id']}/materialize-short-story",
        json={"expectedWorkspaceRevision": workspace["revision"]},
    )
    assert cross.status_code == 404

    service = client.app.state.story_service
    source_project = service.get_project(source["id"])
    with service.db.project_write(source_project.id, source_project.folder_path) as session:
        node = session.scalar(select(PlanNode))
        assert node
        node.note = "source plan drift"
        node.revision += 1
    drift = client.post(
        f"/api/v1/projects/{source['id']}/adaptation-workspaces/{workspace['id']}/materialize-short-story",
        json={"expectedWorkspaceRevision": workspace["revision"], "idempotencyKey": "drift"},
    )
    assert drift.status_code == 409
    assert drift.json()["code"] == "ADAPTATION_SOURCE_DRIFT"

    source2, workspace2 = _ready_short_story_strategy(client)
    source2_project = service.get_project(source2["id"])
    with service.db.project_write(source2_project.id, source2_project.folder_path) as session:
        strategy = session.scalar(select(ShortStoryStrategy).where(ShortStoryStrategy.workspace_id == workspace2["id"], ShortStoryStrategy.status == "active"))
        assert strategy
        budget = _valid_strategy()["chapterBudget"]
        budget[1]["chapterNumber"] = 1
        strategy.chapter_budget_json = dumps(budget)
        strategy.checksum = service.phase11._strategy_checksum(strategy)
        strategy.updated_at = utc_now()
    invalid = client.post(
        f"/api/v1/projects/{source2['id']}/adaptation-workspaces/{workspace2['id']}/materialize-short-story",
        json={"expectedWorkspaceRevision": workspace2["revision"], "idempotencyKey": "invalid-budget"},
    )
    assert invalid.status_code == 409
    assert invalid.json()["code"] == "SHORT_STORY_CHAPTER_BUDGET_DUPLICATE"


def test_short_story_backup_restore_remaps_target_origin(client: TestClient) -> None:
    source, workspace = _ready_short_story_strategy(client)
    target = _materialize(client, source, workspace)["targetProject"]
    backup = client.post(f"/api/v1/projects/{target['id']}/backups")
    assert backup.status_code == 201, backup.text
    archive = Path(backup.json()["archivePath"])
    restored = client.post(
        "/api/v1/projects/restore",
        files={"backup": (archive.name, archive.read_bytes(), "application/zip")},
    )
    assert restored.status_code == 201, restored.text
    restored_project = restored.json()
    restored_origin = client.get(f"/api/v1/projects/{restored_project['id']}/short-story/origin")
    assert restored_origin.status_code == 200, restored_origin.text
    assert restored_origin.json()["projectId"] == restored_project["id"]
    assert restored_origin.json()["targetProjectId"] == restored_project["id"]
    assert restored_origin.json()["sourceProjectId"] == source["id"]
    readiness = client.get(f"/api/v1/projects/{restored_project['id']}/short-story/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is True


def test_failed_materialization_is_diagnostic_and_retry_reuses_staged_target(client: TestClient) -> None:
    source, workspace = _ready_short_story_strategy(client)
    service = client.app.state.story_service
    original_populate = service.phase12._populate_target_project

    def fail_population(*args, **kwargs):
        raise RuntimeError("local phase12 population failure")

    service.phase12._populate_target_project = fail_population
    with pytest.raises(RuntimeError, match="local phase12 population failure"):
        client.post(
            f"/api/v1/projects/{source['id']}/adaptation-workspaces/{workspace['id']}/materialize-short-story",
            json={"expectedWorkspaceRevision": workspace["revision"], "idempotencyKey": "retry-staged"},
        )
    source_project = service.get_project(source["id"])
    with service.db.project(source_project.id, source_project.folder_path) as session:
        failed = session.scalar(select(ShortStoryOrigin).where(ShortStoryOrigin.idempotency_key == "retry-staged"))
        assert failed
        assert failed.status == "failed"
        assert failed.target_project_id
        staged_target_id = failed.target_project_id
        assert failed.diagnostic_json

    service.phase12._populate_target_project = original_populate
    retried = _materialize(client, source, workspace, key="retry-staged")
    assert retried["targetProject"]["id"] == staged_target_id
    assert retried["origin"]["status"] == "completed"

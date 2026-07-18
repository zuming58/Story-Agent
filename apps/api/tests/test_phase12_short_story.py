from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from story_agent_api.models import CanonDocument, ChapterCommit, ChapterExtraction, PlanNode, ProjectMeta, ShortStoryOrigin, ShortStoryStrategy, utc_now
from story_agent_api.services import dumps

from test_phase11_adaptation import _ensure_foundation, _project, _valid_strategy
from test_phase5 import configure_phase5_roles, start_phase5_server


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


def _materialize(client: TestClient, source: dict, workspace: dict, *, key: str = "phase12-materialize", **overrides) -> dict:
    response = client.post(
        f"/api/v1/projects/{source['id']}/adaptation-workspaces/{workspace['id']}/materialize-short-story",
        json={"expectedWorkspaceRevision": workspace["revision"], "idempotencyKey": key, **overrides},
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
    assert beats[0]["paceBudget"]["majorEvents"] == ["hook"]

    contract = client.post(
        f"/api/v1/projects/{target['id']}/chapter-contracts/derive",
        json={"chapterNumber": 1, "targetWordsMin": 1000, "targetWordsMax": 3000},
    )
    assert contract.status_code == 200, contract.text
    assert contract.json()["allowedScope"]["paceBudget"]["majorEvents"] == ["hook"]
    assert contract.json()["allowedScope"]["shortStory"]["targetTotalWords"] == 12000
    assert contract.json()["targetWordsMin"] == 1400
    assert contract.json()["targetWordsMax"] == 2600
    assert "choice" in contract.json()["forbiddenScope"]["futureKeywords"]
    assert contract.json()["forbiddenScope"]["mustNotAdvance"][0]["chapterNumber"] == 2

    round_trip = client.patch(
        f"/api/v1/projects/{target['id']}/plan/nodes/{plan['milestones'][0]['id']}",
        json={"expectedRevision": plan["milestones"][0]["revision"], "chapterBeats": beats},
    )
    assert round_trip.status_code == 200, round_trip.text
    chapter_two = client.post(
        f"/api/v1/projects/{target['id']}/chapter-contracts/derive",
        json={"chapterNumber": 2},
    )
    assert chapter_two.status_code == 200, chapter_two.text
    assert chapter_two.json()["allowedScope"]["paceBudget"]["majorEvents"] == ["choice"]

    shrink = client.patch(f"/api/v1/projects/{target['id']}", json={"totalChapters": 5})
    assert shrink.status_code == 409
    assert shrink.json()["code"] == "SHORT_STORY_TOTAL_IMMUTABLE"

    beyond = client.post(
        f"/api/v1/projects/{target['id']}/chapter-contracts/derive",
        json={"chapterNumber": 31},
    )
    assert beyond.status_code == 422
    assert beyond.json()["code"] == "SHORT_STORY_CHAPTER_RANGE"

    duplicate = _materialize(client, source, workspace)
    assert duplicate["targetProject"]["id"] == target["id"]
    changed_workspace = client.put(
        f"/api/v1/projects/{source['id']}/adaptation-workspaces/{workspace['id']}",
        json={"expectedRevision": workspace["revision"], "name": "Renamed after materialization"},
    )
    assert changed_workspace.status_code == 200, changed_workspace.text
    duplicate_after_change = _materialize(client, source, workspace)
    assert duplicate_after_change["targetProject"]["id"] == target["id"]
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

    source3, workspace3 = _ready_short_story_strategy(client)
    source3_project = service.get_project(source3["id"])
    with service.db.project_write(source3_project.id, source3_project.folder_path) as session:
        strategy = session.scalar(select(ShortStoryStrategy).where(ShortStoryStrategy.workspace_id == workspace3["id"], ShortStoryStrategy.status == "active"))
        assert strategy
        budget = _valid_strategy()["chapterBudget"]
        budget[0]["maxMajorEvents"] = "not-an-integer"
        strategy.chapter_budget_json = dumps(budget)
        strategy.checksum = service.phase11._strategy_checksum(strategy)
        strategy.updated_at = utc_now()
    project_count = len(client.get("/api/v1/projects").json())
    invalid_limit = client.post(
        f"/api/v1/projects/{source3['id']}/adaptation-workspaces/{workspace3['id']}/materialize-short-story",
        json={"expectedWorkspaceRevision": workspace3["revision"], "idempotencyKey": "invalid-event-limit"},
    )
    assert invalid_limit.status_code == 409
    assert invalid_limit.json()["code"] == "SHORT_STORY_EVENT_BUDGET_INVALID"
    assert len(client.get("/api/v1/projects").json()) == project_count

    source4, workspace4 = _ready_short_story_strategy(client)
    project_count = len(client.get("/api/v1/projects").json())
    invalid_words = client.post(
        f"/api/v1/projects/{source4['id']}/adaptation-workspaces/{workspace4['id']}/materialize-short-story",
        json={
            "expectedWorkspaceRevision": workspace4["revision"],
            "idempotencyKey": "invalid-word-budget",
            "targetWordCount": 2000,
        },
    )
    assert invalid_words.status_code == 422
    assert invalid_words.json()["code"] == "SHORT_STORY_WORD_BUDGET_INVALID"
    assert invalid_words.json()["details"]["minimumTargetWordCount"] == 3000
    assert len(client.get("/api/v1/projects").json()) == project_count


def test_target_word_override_is_consistent_across_origin_plan_and_contract(client: TestClient) -> None:
    source, workspace = _ready_short_story_strategy(client)
    materialized = _materialize(client, source, workspace, key="word-override", targetWordCount=18000)
    target = materialized["targetProject"]
    assert materialized["origin"]["targetWordCount"] == 18000
    target_origin = client.get(f"/api/v1/projects/{target['id']}/short-story/origin")
    assert target_origin.status_code == 200
    assert target_origin.json()["targetWordCount"] == 18000
    contract = client.post(
        f"/api/v1/projects/{target['id']}/chapter-contracts/derive",
        json={"chapterNumber": 1},
    )
    assert contract.status_code == 200, contract.text
    assert contract.json()["allowedScope"]["shortStory"]["targetTotalWords"] == 18000
    assert contract.json()["allowedScope"]["paceBudget"]["targetWordsMin"] == 2100
    assert contract.json()["allowedScope"]["paceBudget"]["targetWordsMax"] == 3900
    plan = client.get(f"/api/v1/projects/{target['id']}/plan").json()
    node = plan["milestones"][0]
    inconsistent_beats = node["chapterBeats"]
    for beat in inconsistent_beats:
        beat["paceBudget"]["targetWordsMin"] = 100
        beat["paceBudget"]["targetWordsMax"] = 200
    changed = client.patch(
        f"/api/v1/projects/{target['id']}/plan/nodes/{node['id']}",
        json={"expectedRevision": node["revision"], "chapterBeats": inconsistent_beats},
    )
    assert changed.status_code == 200, changed.text
    readiness = client.get(f"/api/v1/projects/{target['id']}/short-story/readiness")
    assert readiness.status_code == 200, readiness.text
    assert "SHORT_STORY_TOTAL_WORD_PLAN" in {
        item["code"] for item in readiness.json()["checks"] if item["status"] == "blocked"
    }


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


def test_source_backup_restore_detaches_old_target_and_materializes_a_new_one(client: TestClient) -> None:
    source, workspace = _ready_short_story_strategy(client)
    original = _materialize(client, source, workspace, key="source-restore", targetTitle="Stable target title")
    original_target_id = original["targetProject"]["id"]
    backup = client.post(f"/api/v1/projects/{source['id']}/backups")
    assert backup.status_code == 201, backup.text
    archive = Path(backup.json()["archivePath"])
    restored = client.post(
        "/api/v1/projects/restore",
        files={"backup": (archive.name, archive.read_bytes(), "application/zip")},
    )
    assert restored.status_code == 201, restored.text
    restored_source = restored.json()
    restored_workspace = client.get(
        f"/api/v1/projects/{restored_source['id']}/adaptation-workspaces/{workspace['id']}"
    )
    assert restored_workspace.status_code == 200, restored_workspace.text
    rematerialized = _materialize(
        client,
        restored_source,
        restored_workspace.json(),
        key="source-restore",
        targetTitle="Stable target title",
    )
    assert rematerialized["targetProject"]["id"] != original_target_id
    assert rematerialized["origin"]["sourceProjectId"] == restored_source["id"]

    service = client.app.state.story_service
    restored_catalog = service.get_project(restored_source["id"])
    with service.db.project(restored_catalog.id, restored_catalog.folder_path) as session:
        detached = session.scalar(select(ShortStoryOrigin).where(ShortStoryOrigin.target_project_id == original_target_id))
        assert detached
        assert detached.status == "detached"
        assert detached.idempotency_key is None
        assert detached.source_project_id == source["id"]


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


def test_staged_origin_recovery_and_final_chapter_stop(client: TestClient) -> None:
    source, workspace = _ready_short_story_strategy(client)
    materialized = _materialize(client, source, workspace, key="startup-recovery")
    target = materialized["targetProject"]
    service = client.app.state.story_service
    source_project = service.get_project(source["id"])
    with service.db.project_write(source_project.id, source_project.folder_path) as session:
        origin = session.scalar(select(ShortStoryOrigin).where(ShortStoryOrigin.idempotency_key == "startup-recovery"))
        assert origin
        origin.status = "staged"
        origin.completed_at = None
    service.phase12.recover_interrupted_short_story_origins()
    with service.db.project(source_project.id, source_project.folder_path) as session:
        recovered = session.scalar(select(ShortStoryOrigin).where(ShortStoryOrigin.idempotency_key == "startup-recovery"))
        assert recovered
        assert recovered.status == "interrupted"
    retried = _materialize(client, source, workspace, key="startup-recovery")
    assert retried["targetProject"]["id"] == target["id"]

    target_project = service.get_project(target["id"])
    with service.db.project_write(target_project.id, target_project.folder_path) as session:
        meta = session.get(ProjectMeta, target_project.id)
        assert meta
        meta.current_chapter = meta.total_chapters
        meta.updated_at = utc_now()
    readiness = client.get(f"/api/v1/projects/{target['id']}/trial-readiness", params={"chapterCount": 1})
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["ready"] is False
    assert "TRIAL_PROJECT_RANGE_EXCEEDED" in {
        item["code"] for item in readiness.json()["checks"] if item["status"] == "blocked"
    }


def test_short_story_deterministic_quality_rules_block_invalid_candidate(client: TestClient) -> None:
    source, workspace = _ready_short_story_strategy(client)
    target = _materialize(client, source, workspace, key="quality-rules")["targetProject"]
    plan = client.get(f"/api/v1/projects/{target['id']}/plan").json()
    node = plan["milestones"][0]
    beats = node["chapterBeats"]
    beats[0]["hooks"] = ["impossible opening hook"]
    beats[0]["forbidden"] = ["Lin Mo"]
    beats[0]["paceBudget"]["maxMajorEvents"] = 1
    updated = client.patch(
        f"/api/v1/projects/{target['id']}/plan/nodes/{node['id']}",
        json={"expectedRevision": node["revision"], "chapterBeats": beats},
    )
    assert updated.status_code == 200, updated.text

    server, base_url = start_phase5_server()
    try:
        configure_phase5_roles(client, base_url, reviewers=True)
        contract = client.post(
            f"/api/v1/projects/{target['id']}/chapter-contracts/derive",
            json={"chapterNumber": 1, "targetWordsMin": 5, "targetWordsMax": 100},
        ).json()
        locked = client.post(
            f"/api/v1/projects/{target['id']}/chapter-contracts/{contract['id']}/lock",
            json={"expectedRevision": contract["revision"]},
        )
        assert locked.status_code == 200, locked.text
        job = client.post(
            f"/api/v1/projects/{target['id']}/chapter-jobs",
            json={"chapterContractId": locked.json()["id"]},
        ).json()
        run = client.post(f"/api/v1/projects/{target['id']}/chapter-jobs/{job['id']}/run", json={})
        assert run.status_code == 200, run.text

        service = client.app.state.story_service
        target_project = service.get_project(target["id"])
        with service.db.project_write(target_project.id, target_project.folder_path) as session:
            extraction = session.scalar(select(ChapterExtraction).where(ChapterExtraction.project_id == target_project.id))
            assert extraction
            payload = {
                "summary": "two events",
                "entities": [],
                "facts": [],
                "events": [
                    {"summary": "one", "isMajor": True},
                    {"summary": "two", "isMajor": True},
                ],
                "foreshadows": [],
                "boundaries": [],
            }
            extraction.payload_json = dumps(payload)
        current_job = client.get(f"/api/v1/projects/{target['id']}/chapter-jobs/{job['id']}").json()
        revalidated = client.post(
            f"/api/v1/projects/{target['id']}/chapter-jobs/{job['id']}/quality/revalidate",
            json={"expectedJobRevision": current_job["revision"]},
        )
        assert revalidated.status_code == 200, revalidated.text
        codes = {
            item["ruleCode"]
            for item in client.get(f"/api/v1/projects/{target['id']}/chapter-jobs/{job['id']}/quality").json()["findings"]
            if item["status"] == "open"
        }
        assert {
            "SHORT_STORY_EVENT_BUDGET",
            "SHORT_STORY_HOOK_MISSING",
            "SHORT_STORY_REVEAL_EARLY",
        }.issubset(codes)

        with service.db.project_write(target_project.id, target_project.folder_path) as session:
            canon = session.get(CanonDocument, "story-core")
            assert canon
            canon.status = "draft"
            canon.updated_at = utc_now()
        stale_job = client.get(f"/api/v1/projects/{target['id']}/chapter-jobs/{job['id']}").json()
        canon_drift = client.post(
            f"/api/v1/projects/{target['id']}/chapter-jobs/{job['id']}/quality/revalidate",
            json={"expectedJobRevision": stale_job["revision"]},
        )
        assert canon_drift.status_code == 409
        assert canon_drift.json()["code"] == "SHORT_STORY_CANON_DRIFT"

        with service.db.project_write(target_project.id, target_project.folder_path) as session:
            canon = session.get(CanonDocument, "story-core")
            assert canon
            canon.status = "locked"
            canon.updated_at = utc_now()
        final_contract = client.post(
            f"/api/v1/projects/{target['id']}/chapter-contracts/derive",
            json={"chapterNumber": 6, "targetWordsMin": 5, "targetWordsMax": 100},
        )
        assert final_contract.status_code == 200, final_contract.text
        final_locked = client.post(
            f"/api/v1/projects/{target['id']}/chapter-contracts/{final_contract.json()['id']}/lock",
            json={"expectedRevision": final_contract.json()["revision"]},
        )
        assert final_locked.status_code == 200, final_locked.text
        final_job = client.post(
            f"/api/v1/projects/{target['id']}/chapter-jobs",
            json={"chapterContractId": final_locked.json()["id"]},
        ).json()
        final_run = client.post(f"/api/v1/projects/{target['id']}/chapter-jobs/{final_job['id']}/run", json={})
        assert final_run.status_code == 200, final_run.text
        final_codes = {
            item["ruleCode"]
            for item in client.get(f"/api/v1/projects/{target['id']}/chapter-jobs/{final_job['id']}/quality").json()["findings"]
            if item["status"] == "open"
        }
        assert {
            "SHORT_STORY_TOTAL_WORD_BUDGET",
            "SHORT_STORY_FORESHADOW_DROPPED",
            "SHORT_STORY_ENDING_INCOMPLETE",
        }.issubset(final_codes)
    finally:
        server.shutdown()
        server.server_close()

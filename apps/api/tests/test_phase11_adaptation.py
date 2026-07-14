from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from story_agent_api.models import (
    AdaptationProposal,
    CanonDocument,
    ChapterCommit,
    ChapterContract,
    ChapterDraft,
    ChapterExtraction,
    ChapterJob,
    Plan,
    PlanNode,
    ProjectMeta,
    SourceVersion,
    StateSnapshot,
    utc_now,
)
from story_agent_api.services import dumps, stable_digest


def _project(client: TestClient, title: str = "Adaptation Story") -> dict:
    response = client.post("/api/v1/projects", json={"title": title, "mode": "long-form", "totalChapters": 80})
    assert response.status_code == 201
    return response.json()


def _ensure_foundation(client: TestClient, project_id: str) -> None:
    service = client.app.state.story_service
    project = service.get_project(project_id)
    now = utc_now()
    with service.db.project_write(project.id, project.folder_path) as session:
        canon = session.get(CanonDocument, "story-core")
        if canon:
            canon.status = "locked"
            canon.content_markdown = "Locked canon"
            canon.updated_at = now
            canon.locked_at = canon.locked_at or now
        else:
            session.add(CanonDocument(
                id="story-core",
                title="Story Core",
                kind="story",
                content_markdown="Locked canon",
                status="locked",
                revision=1,
                created_at=now,
                updated_at=now,
                locked_at=now,
            ))
        plan = session.scalar(select(Plan))
        if not plan:
            plan = Plan(id="plan", book_title="Book", volume_title="V1", arc_title="A1", chapter_start=1, chapter_end=80)
            session.add(plan)
            session.flush()
        if not session.get(PlanNode, "beat-1"):
            session.add(PlanNode(
                id="beat-1",
                plan_id=plan.id,
                title="Beat 1",
                type="chapter",
                target_chapter=1,
                range_min=1,
                range_max=1,
            ))


def _seed_official_chapter(client: TestClient, project_id: str, chapter: int) -> str:
    service = client.app.state.story_service
    project = service.get_project(project_id)
    now = utc_now()
    content = f"Official chapter {chapter}"
    draft_checksum = stable_digest(content)
    extraction_payload = {"summary": f"chapter {chapter}", "entities": [], "facts": [], "events": [], "foreshadows": []}
    extraction_checksum = stable_digest(extraction_payload)
    source_checksum = stable_digest({"draft": draft_checksum, "extraction": extraction_checksum})
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
            content_markdown=content,
            word_count=len(content),
            checksum=draft_checksum,
            status="approved",
            is_current=True,
            created_at=now,
            updated_at=now,
        )
        extraction = ChapterExtraction(
            id=str(uuid4()),
            project_id=project.id,
            chapter_draft_id=draft.id,
            payload_json=dumps(extraction_payload),
            status="validated",
            checksum=extraction_checksum,
            created_at=now,
            updated_at=now,
        )
        source = SourceVersion(
            id=str(uuid4()),
            project_id=project.id,
            source_id=f"chapter-{chapter:04d}",
            version_number=1,
            source_kind="chapter",
            status="official",
            checksum=source_checksum,
            summary=extraction_payload["summary"],
            payload_json=dumps(extraction_payload),
            revision=1,
            created_at=now,
            updated_at=now,
        )
        snapshot = StateSnapshot(
            id=str(uuid4()),
            project_id=project.id,
            snapshot_number=chapter,
            source_version_id=source.id,
            summary_json=dumps({"entityCount": 0, "factCount": 0, "eventCount": 0, "foreshadowCount": 0}),
            checksum=stable_digest({"sourceVersionId": source.id, "entityCount": 0, "factCount": 0, "eventCount": 0, "foreshadowCount": 0}),
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
            state_snapshot_id=snapshot.id,
            quality_summary_json=dumps({}),
            checksum=stable_digest({"draft": draft_checksum, "sourceVersionId": source.id, "quality": {}}),
            status="official",
            is_current=True,
            revision=1,
            committed_at=now,
            created_at=now,
        )
        session.add_all([contract, job, draft, extraction, source, snapshot, commit])
        meta = session.get(ProjectMeta, project.id)
        if meta:
            meta.current_chapter = max(meta.current_chapter, chapter)
        session.flush()
        return commit.id


def _valid_strategy() -> dict:
    return {
        "coreHook": "失踪档案在雨夜自己回到桌上",
        "openingHook": "第一章直接出现不存在的档案袋",
        "mainConflict": "主角必须在三十天内证明档案来自规则漏洞",
        "emotionalCurve": ["疑惑", "逼近", "牺牲", "闭环"],
        "ending": "主角保留代价后关闭档案循环并回收F1",
        "pointOfView": "close third",
        "targetWordCount": 12000,
        "targetChapterCount": 6,
        "chapterBudget": [
            {"chapterNumber": 1, "majorEvents": ["hook"], "maxMajorEvents": 2},
            {"chapterNumber": 2, "majorEvents": ["choice"], "maxMajorEvents": 2},
            {"chapterNumber": 3, "majorEvents": ["loss"], "maxMajorEvents": 2},
            {"chapterNumber": 4, "majorEvents": ["truth"], "maxMajorEvents": 2},
            {"chapterNumber": 5, "majorEvents": ["cost"], "maxMajorEvents": 2},
            {"chapterNumber": 6, "majorEvents": ["ending"], "maxMajorEvents": 2},
        ],
        "characterMergePlan": [{"from": ["A"], "to": "B", "reason": "retain causal duty"}],
        "foreshadowPlan": {"retain": ["F1"], "resolved": ["F1"]},
        "compressionRules": {"abilityUpgrades": [{"name": "识祟", "prerequisites": ["见雾"]}]},
        "forbiddenReveals": ["final truth"],
        "impactScope": [{"kind": "strategy", "label": "short story"}],
        "canonDeviations": [],
    }


def _valid_outline() -> dict:
    return {
        "episodes": [
            {
                "episodeNumber": number,
                "title": f"Episode {number}",
                "logline": "A locked clue moves the case forward.",
                "targetDurationSeconds": 90,
                "openingHook": "A new impossible clue appears.",
                "cliffhanger": "The clue points home.",
                "sourceRefs": [{"kind": "strategy", "id": "strategy"}],
                "scenes": [
                    {
                        "sceneNumber": 1,
                        "settingType": "INT",
                        "location": "Archive",
                        "timeOfDay": "Night",
                        "characters": ["Lead"],
                        "objective": "Open the clue",
                        "conflict": "The clue refuses",
                        "turn": "It names the lead",
                        "visualAction": "The paper rewrites itself",
                        "estimatedDurationSeconds": 45,
                        "sourceEvidence": [{"kind": "strategy", "chapter": number}],
                        "canonRefs": ["story-core"],
                    }
                ],
            }
            for number in range(1, 7)
        ],
        "impactScope": [{"kind": "episodes", "label": "six episode outline"}],
        "canonDeviations": [],
    }


def _valid_script(episode_id: str) -> dict:
    return {
        "episodeId": episode_id,
        "markdownText": "Lead: The archive remembered me.",
        "fountainText": "LEAD\nThe archive remembered me.",
        "structuredDialogue": [{"speaker": "Lead", "line": "The archive remembered me.", "source": "scene-1", "purpose": "turn"}],
        "wordCount": 6,
        "estimatedDurationSeconds": 80,
        "impactScope": [{"kind": "script", "label": "candidate"}],
        "canonDeviations": [],
    }


def test_workspace_readiness_revision_and_source_drift(client: TestClient) -> None:
    project = _project(client)
    _ensure_foundation(client, project["id"])
    created = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces",
        json={"name": "Short bridge", "kind": "short_story", "targetWordCount": 12000, "targetChapterCount": 6},
    )
    assert created.status_code == 201, created.text
    workspace = created.json()
    ready = client.get(f"/api/v1/projects/{project['id']}/adaptation-workspaces/{workspace['id']}/readiness")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True

    stale = client.put(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces/{workspace['id']}",
        json={"expectedRevision": workspace["revision"] + 1, "name": "stale"},
    )
    assert stale.status_code == 409

    service = client.app.state.story_service
    catalog = service.get_project(project["id"])
    with service.db.project_write(catalog.id, catalog.folder_path) as session:
        canon = session.get(CanonDocument, "story-core")
        canon.content_markdown = "Changed canon"
        canon.revision += 1
        canon.updated_at = utc_now()
    drift = client.get(f"/api/v1/projects/{project['id']}/adaptation-workspaces/{workspace['id']}/readiness")
    assert drift.status_code == 200
    assert "ADAPTATION_SOURCE_DRIFT" in {item["code"] for item in drift.json()["checks"] if item["status"] == "blocked"}


def test_short_story_proposal_repair_idempotency_apply_and_reject(client: TestClient) -> None:
    project = _project(client)
    _ensure_foundation(client, project["id"])
    workspace = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces",
        json={"name": "Short strategy", "kind": "short_story", "targetWordCount": 12000, "targetChapterCount": 6},
    ).json()
    service = client.app.state.story_service
    calls: list[str] = []

    def fake_role(project_obj, role, messages, request_id, *, response_json=False, run_role=None):
        calls.append(run_role or role)
        if len(calls) == 1:
            return "not json", "run-bad"
        return dumps(_valid_strategy()), "run-good"

    service.phase11._complete_role = fake_role
    created = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces/{workspace['id']}/short-story-proposals",
        json={"expectedWorkspaceRevision": workspace["revision"], "idempotencyKey": "strategy-1"},
    )
    assert created.status_code == 201, created.text
    proposal = created.json()
    assert proposal["status"] == "pending"
    assert len(calls) == 2

    duplicate = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces/{workspace['id']}/short-story-proposals",
        json={"expectedWorkspaceRevision": workspace["revision"], "idempotencyKey": "strategy-1"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == proposal["id"]

    applied = client.post(
        f"/api/v1/adaptation-proposals/{proposal['id']}/apply",
        json={"expectedRevision": proposal["revision"]},
    )
    assert applied.status_code == 200, applied.text
    updated_workspace = client.get(f"/api/v1/projects/{project['id']}/adaptation-workspaces/{workspace['id']}").json()
    assert updated_workspace["strategy"]["checksum"]

    service.phase11._complete_role = lambda *args, **kwargs: (dumps(_valid_strategy()), "run-reject")
    second = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces/{workspace['id']}/short-story-proposals",
        json={"expectedWorkspaceRevision": updated_workspace["revision"], "idempotencyKey": "strategy-2"},
    ).json()
    rejected = client.post(f"/api/v1/adaptation-proposals/{second['id']}/reject", json={"expectedRevision": second["revision"]})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_short_story_findings_block_application(client: TestClient) -> None:
    project = _project(client)
    _ensure_foundation(client, project["id"])
    workspace = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces",
        json={"name": "Broken strategy", "kind": "short_story", "targetWordCount": 12000, "targetChapterCount": 6},
    ).json()
    broken = _valid_strategy()
    broken["chapterBudget"][0]["majorEvents"] = ["a", "b", "c"]
    broken["chapterBudget"][0]["maxMajorEvents"] = 1
    service = client.app.state.story_service
    service.phase11._complete_role = lambda *args, **kwargs: (dumps(broken), "run-broken")
    proposal = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces/{workspace['id']}/short-story-proposals",
        json={"expectedWorkspaceRevision": workspace["revision"]},
    ).json()
    findings = client.get(f"/api/v1/projects/{project['id']}/adaptation-workspaces/{workspace['id']}/findings").json()
    assert "SHORTFORM_EVENT_BUDGET_OVERFLOW" in {item["ruleCode"] for item in findings}
    applied = client.post(f"/api/v1/adaptation-proposals/{proposal['id']}/apply", json={"expectedRevision": proposal["revision"]})
    assert applied.status_code == 409


def test_drama_outline_script_candidate_and_approval_conflict(client: TestClient) -> None:
    project = _project(client)
    _ensure_foundation(client, project["id"])
    service = client.app.state.story_service
    service.phase11._complete_role = lambda *args, **kwargs: (dumps(_valid_strategy()), "run-strategy")
    short_workspace = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces",
        json={"name": "Short source", "kind": "short_story", "targetWordCount": 12000, "targetChapterCount": 6},
    ).json()
    proposal = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces/{short_workspace['id']}/short-story-proposals",
        json={"expectedWorkspaceRevision": short_workspace["revision"]},
    ).json()
    client.post(f"/api/v1/adaptation-proposals/{proposal['id']}/apply", json={"expectedRevision": proposal["revision"]})
    short_workspace = client.get(f"/api/v1/projects/{project['id']}/adaptation-workspaces/{short_workspace['id']}").json()
    strategy_id = short_workspace["strategy"]["id"]

    drama_workspace = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces",
        json={"name": "Drama bridge", "kind": "short_drama", "sourceType": "short_story_strategy", "sourceId": strategy_id, "targetEpisodeCount": 6, "unitDurationSeconds": 90},
    ).json()
    service.phase11._complete_role = lambda *args, **kwargs: (dumps(_valid_outline()), "run-outline")
    outline = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces/{drama_workspace['id']}/drama-outline-proposals",
        json={"expectedWorkspaceRevision": drama_workspace["revision"], "targetEpisodeCount": 6},
    ).json()
    applied = client.post(f"/api/v1/adaptation-proposals/{outline['id']}/apply", json={"expectedRevision": outline["revision"]})
    assert applied.status_code == 200, applied.text
    episodes = client.get(f"/api/v1/projects/{project['id']}/adaptation-workspaces/{drama_workspace['id']}/episodes").json()
    assert len(episodes) == 6
    episode_id = episodes[0]["id"]

    service.phase11._complete_role = lambda *args, **kwargs: (dumps(_valid_script(episode_id)), "run-script-1")
    drama_workspace_current = client.get(f"/api/v1/projects/{project['id']}/adaptation-workspaces/{drama_workspace['id']}").json()
    script = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces/{drama_workspace['id']}/episodes/{episode_id}/script-proposals",
        json={"expectedWorkspaceRevision": drama_workspace_current["revision"]},
    )
    assert script.status_code == 201, script.text
    episodes = client.get(f"/api/v1/projects/{project['id']}/adaptation-workspaces/{drama_workspace['id']}/episodes").json()
    version = episodes[0]["scriptVersions"][0]
    approved = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces/{drama_workspace['id']}/script-versions/{version['id']}/approve",
        json={"expectedRevision": version["revision"]},
    )
    assert approved.status_code == 200, approved.text

    drama_workspace_current = client.get(f"/api/v1/projects/{project['id']}/adaptation-workspaces/{drama_workspace['id']}").json()
    service.phase11._complete_role = lambda *args, **kwargs: (dumps(_valid_script(episode_id)), "run-script-2")
    second = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces/{drama_workspace['id']}/episodes/{episode_id}/script-proposals",
        json={"expectedWorkspaceRevision": drama_workspace_current["revision"]},
    )
    assert second.status_code == 201, second.text
    episodes = client.get(f"/api/v1/projects/{project['id']}/adaptation-workspaces/{drama_workspace['id']}/episodes").json()
    candidate = [item for item in episodes[0]["scriptVersions"] if item["status"] == "candidate"][-1]
    conflict = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces/{drama_workspace['id']}/script-versions/{candidate['id']}/approve",
        json={"expectedRevision": candidate["revision"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "DRAMA_APPROVAL_CONFLICT"


def test_chapter_range_cross_project_and_backup_restore(client: TestClient) -> None:
    project = _project(client)
    other = _project(client, "Other")
    _ensure_foundation(client, project["id"])
    _ensure_foundation(client, other["id"])
    _seed_official_chapter(client, project["id"], 1)
    _seed_official_chapter(client, project["id"], 2)
    workspace = client.post(
        f"/api/v1/projects/{project['id']}/adaptation-workspaces",
        json={"name": "Chapter drama", "kind": "short_drama", "sourceType": "chapter_range", "chapterStart": 1, "chapterEnd": 2, "targetEpisodeCount": 6},
    )
    assert workspace.status_code == 201, workspace.text
    cross = client.get(f"/api/v1/projects/{other['id']}/adaptation-workspaces/{workspace.json()['id']}")
    assert cross.status_code == 404

    service = client.app.state.story_service
    catalog = service.get_project(project["id"])
    with service.db.project_write(catalog.id, catalog.folder_path) as session:
        session.add(AdaptationProposal(
            id="active-proposal",
            project_id=catalog.id,
            workspace_id=workspace.json()["id"],
            proposal_kind="drama_outline",
            status="generating",
            input_snapshot_json=dumps({"projectId": catalog.id}),
            created_at=utc_now(),
            updated_at=utc_now(),
        ))
    backup = client.post(f"/api/v1/projects/{project['id']}/backups")
    assert backup.status_code == 201
    archive = Path(backup.json()["archivePath"])
    restored = client.post("/api/v1/projects/restore", files={"backup": (archive.name, archive.read_bytes(), "application/zip")})
    assert restored.status_code == 201, restored.text
    restored_id = restored.json()["id"]
    restored_workspaces = client.get(f"/api/v1/projects/{restored_id}/adaptation-workspaces").json()
    assert restored_workspaces[0]["projectId"] == restored_id
    restored_service = client.app.state.story_service
    restored_project = restored_service.get_project(restored_id)
    with restored_service.db.project(restored_project.id, restored_project.folder_path) as session:
        proposal = session.get(AdaptationProposal, "active-proposal")
        assert proposal.project_id == restored_id
        assert proposal.status == "interrupted"

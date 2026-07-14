from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from story_agent_api.models import (
    AutomationRun,
    AutomationRunItem,
    CanonDocument,
    CanonEntity,
    CanonRule,
    ChapterCommit,
    ChapterContract,
    ChapterDraft,
    ChapterExtraction,
    ChapterJob,
    EnduranceCheckpoint,
    EnduranceRun,
    EnduranceSuite,
    Foreshadow,
    KnowledgeBoundary,
    Plan,
    PlanNode,
    ProjectMeta,
    SourceVersion,
    StateSnapshot,
    utc_now,
)
from story_agent_api.services import StoryError, dumps, stable_digest


def _project(client: TestClient, title: str = "Endurance Story") -> dict:
    response = client.post("/api/v1/projects", json={"title": title, "mode": "long-form", "totalChapters": 80})
    assert response.status_code == 201
    return response.json()


def _ensure_ready_foundation(client: TestClient, project_id: str) -> None:
    service = client.app.state.story_service
    project = service.get_project(project_id)
    now = utc_now()
    with service.db.project_write(project.id, project.folder_path) as session:
        canon = session.get(CanonDocument, "story-core")
        if canon:
            canon.status = "locked"
            canon.revision += 1
            canon.updated_at = now
            canon.locked_at = canon.locked_at or now
        else:
            session.add(CanonDocument(
                id="story-core",
                title="Story Core",
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
        for chapter in range(1, 31):
            node = session.get(PlanNode, f"beat-{chapter}")
            if not node:
                session.add(PlanNode(
                    id=f"beat-{chapter}",
                    plan_id=plan.id,
                    title=f"Beat {chapter}",
                    type="chapter",
                    target_chapter=chapter,
                    range_min=chapter,
                    range_max=chapter,
                ))


def _seed_official_chapter(client: TestClient, project_id: str, chapter: int, payload: dict | None = None, *, revision_round: int = 0) -> dict[str, str]:
    service = client.app.state.story_service
    project = service.get_project(project_id)
    now = utc_now()
    payload = payload or {"summary": f"chapter {chapter}"}
    content = f"Official chapter {chapter}"
    draft_checksum = stable_digest(content)
    extraction_checksum = stable_digest(payload)
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
            current_revision_round=revision_round,
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
            payload_json=dumps(payload),
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
            summary=payload.get("summary", ""),
            payload_json=dumps(payload),
            revision=2,
            created_at=now,
            updated_at=now,
        )
        snapshot = StateSnapshot(
            id=str(uuid4()),
            project_id=project.id,
            snapshot_number=chapter,
            source_version_id=source.id,
            summary_json=dumps({
                "entityCount": len(payload.get("entities", [])),
                "factCount": len(payload.get("facts", [])),
                "eventCount": len(payload.get("events", [])),
                "foreshadowCount": len(payload.get("foreshadows", [])),
            }),
            checksum=stable_digest({
                "sourceVersionId": source.id,
                "entityCount": len(payload.get("entities", [])),
                "factCount": len(payload.get("facts", [])),
                "eventCount": len(payload.get("events", [])),
                "foreshadowCount": len(payload.get("foreshadows", [])),
            }),
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
        return {"commit": commit.id, "source": source.id, "snapshot": snapshot.id, "job": job.id}


def _install_fake_phase7(client: TestClient, project_id: str, payloads: dict[int, dict] | None = None) -> None:
    service = client.app.state.story_service
    payloads = payloads or {}

    def fake_create_manual_run(project_id_arg, payload, request_id):
        run_id = str(uuid4())
        count = payload.chapter_count or 5
        now = utc_now()
        project = service.get_project(project_id_arg)
        with service.db.project_write(project.id, project.folder_path) as session:
            meta = session.get(ProjectMeta, project.id)
            start = (meta.current_chapter if meta else 0) + 1
            automation = AutomationRun(
                id=run_id,
                project_id=project.id,
                policy_id=project.id,
                scheduled_local_date="2026-07-14",
                trigger="manual",
                status="completed",
                idempotency_key=payload.idempotency_key,
                requested_chapter_count=count,
                start_chapter=start,
                end_chapter=start + count - 1,
                planned_count=count,
                succeeded_count=count,
                total_tokens=count * 100,
                estimated_cost=count * 0.01,
                created_at=now,
                started_at=now,
                completed_at=now,
                updated_at=now,
            )
            session.add(automation)
            items = []
            for offset, chapter in enumerate(range(start, start + count), start=1):
                item = AutomationRunItem(
                    id=str(uuid4()),
                    project_id=project.id,
                    automation_run_id=run_id,
                    chapter_number=chapter,
                    sequence_number=offset,
                    status="committed",
                    total_tokens=100,
                    estimated_cost=0.01,
                    created_at=now,
                    started_at=now,
                    completed_at=now,
                    updated_at=now,
                )
                session.add(item)
                items.append(item)
        for chapter in range(start, start + count):
            _seed_official_chapter(client, project_id_arg, chapter, payloads.get(chapter, {"summary": f"chapter {chapter}"}), revision_round=3 if chapter == 2 and payloads else 0)
        return {
            "id": run_id,
            "projectId": project_id_arg,
            "status": "completed",
            "promptTokens": 0,
            "completionTokens": 0,
            "totalTokens": count * 100,
            "estimatedCost": count * 0.01,
            "items": [{"id": item.id, "status": "committed"} for item in items],
        }

    service.phase7.create_manual_run = fake_create_manual_run


def test_endurance_readiness_and_suite_crud(client: TestClient) -> None:
    project = _project(client)
    _ensure_ready_foundation(client, project["id"])
    ready = client.get(f"/api/v1/projects/{project['id']}/endurance/readiness?chapterCount=10")
    assert ready.status_code == 200
    assert ready.json()["chapterCount"] == 10
    invalid = client.get(f"/api/v1/projects/{project['id']}/endurance/readiness?chapterCount=7")
    assert invalid.status_code == 422

    created = client.post(f"/api/v1/projects/{project['id']}/endurance/suites", json={"name": "Ten chapter watch", "targetChapterCount": 10})
    assert created.status_code == 201, created.text
    suite = created.json()
    assert suite["targetChapterCount"] == 10
    updated = client.put(
        f"/api/v1/projects/{project['id']}/endurance/suites/{suite['id']}",
        json={"expectedRevision": suite["revision"], "name": "Updated", "stopSeverity": "error"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated"
    assert client.get(f"/api/v1/projects/{project['id']}/endurance/suites").json()[0]["id"] == suite["id"]


def test_endurance_run_reuses_phase7_and_creates_checkpoints_report_idempotently(client: TestClient) -> None:
    project = _project(client)
    _ensure_ready_foundation(client, project["id"])
    _install_fake_phase7(client, project["id"])
    suite = client.post(f"/api/v1/projects/{project['id']}/endurance/suites", json={"targetChapterCount": 10}).json()

    created = client.post(f"/api/v1/projects/{project['id']}/endurance/runs", json={"suiteId": suite["id"], "idempotencyKey": "same"})
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "completed"
    assert run["completedCount"] == 10
    assert len(run["checkpoints"]) == 10
    assert run["report"]["successCount"] == 10
    service = client.app.state.story_service
    catalog = service.get_project(project["id"])
    with service.db.project(catalog.id, catalog.folder_path) as session:
        automation_runs = session.scalars(select(AutomationRun).where(
            AutomationRun.idempotency_key.like(f"endurance:{run['id']}:%")
        )).all()
        assert len(automation_runs) == 2
    duplicate = client.post(f"/api/v1/projects/{project['id']}/endurance/runs", json={"suiteId": suite["id"], "idempotencyKey": "same"})
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == run["id"]


def test_endurance_rules_detect_drift_and_stop_on_blocker(client: TestClient) -> None:
    project = _project(client)
    _ensure_ready_foundation(client, project["id"])
    service = client.app.state.story_service
    now = utc_now()
    with service.db.project_write(project["id"], service.get_project(project["id"]).folder_path) as session:
        plan = session.scalar(select(Plan))
        session.add(PlanNode(id="final-reveal", plan_id=plan.id, title="Final Reveal", type="milestone", target_chapter=4, range_min=3, range_max=4))
        session.add(CanonEntity(id=str(uuid4()), entity_type_id="character", canonical_name="Late Hero", aliases_json="[]", attributes_json=dumps({"earliestChapter": 3}), status="locked", created_at=now, updated_at=now, locked_at=now))
        session.add(CanonRule(id=str(uuid4()), rule_code="ABILITY_STEP2", category="ability", statement="Step2 after chapter 4", constraint_json=dumps({"ability": "Step2", "earliestChapter": 4, "prerequisites": ["Training"]}), status="locked", created_at=now, updated_at=now, locked_at=now))
        session.add(KnowledgeBoundary(id=str(uuid4()), project_id=project["id"], entity_id="character", knowledge_json=dumps({"character": "Late Hero", "fact": "reveal:Secret", "allowedChapter": 5}), status="active", created_at=now, updated_at=now))
        session.add(Foreshadow(id=str(uuid4()), project_id=project["id"], code="F1", label="F1", status="pending", latest_chapter=1, created_at=now, updated_at=now))
    payloads = {
        1: {
            "summary": "chapter 1",
            "entities": [
                {"canonicalName": "Late Hero", "entityTypeName": "person", "attributes": {"name": "Late Hero"}},
                {"canonicalName": "Step2", "entityTypeName": "ability", "attributes": {"name": "Step2"}},
                {"canonicalName": "Lamp", "entityTypeName": "item", "attributes": {"name": "Lamp", "holder": "A", "charges": 1}},
            ],
            "events": [{"eventOrder": 1, "summary": "Final Reveal", "participants": ["Late Hero"]}],
            "boundaries": [{"entity": "Late Hero", "knowledge": {"reveal": "Secret"}}],
            "foreshadows": [],
        },
        2: {
            "summary": "chapter 2",
            "entities": [{"canonicalName": "Lamp", "entityTypeName": "item", "attributes": {"name": "Lamp", "holder": "A", "charges": 2}}],
        },
        3: {"summary": "chapter 3"},
        4: {"summary": "chapter 4"},
        5: {"summary": "chapter 5"},
    }
    _install_fake_phase7(client, project["id"], payloads)
    suite = client.post(f"/api/v1/projects/{project['id']}/endurance/suites", json={"targetChapterCount": 5, "stopSeverity": "blocker"}).json()

    run = client.post(f"/api/v1/projects/{project['id']}/endurance/runs", json={"suiteId": suite["id"]}).json()
    assert run["status"] == "blocked"
    codes = {item["ruleCode"] for item in run["findings"]}
    assert {
        "ENDURANCE_PACING_EARLY",
        "ENDURANCE_CHARACTER_EARLY",
        "ENDURANCE_ABILITY_WINDOW",
        "ENDURANCE_KNOWLEDGE_LEAK",
        "ENDURANCE_ITEM_STATE_DRIFT",
        "ENDURANCE_FORESHADOW_MISSED",
        "ENDURANCE_REVISION_LIMIT_BREACH",
    }.issubset(codes)


def test_async_batches_do_not_flag_future_gaps_and_advance_after_callback(client: TestClient) -> None:
    project = _project(client)
    _ensure_ready_foundation(client, project["id"])
    service = client.app.state.story_service
    created_automation_ids: list[str] = []

    def fake_async_create(project_id_arg, payload, request_id):
        catalog = service.get_project(project_id_arg)
        now = utc_now()
        run_id = str(uuid4())
        count = payload.chapter_count or 5
        with service.db.project_write(catalog.id, catalog.folder_path) as session:
            meta = session.get(ProjectMeta, catalog.id)
            start = (meta.current_chapter if meta else 0) + 1
            automation = AutomationRun(
                id=run_id,
                project_id=catalog.id,
                policy_id=catalog.id,
                scheduled_local_date="2026-07-14",
                trigger="manual",
                status="running",
                idempotency_key=payload.idempotency_key,
                requested_chapter_count=count,
                start_chapter=start,
                end_chapter=start + count - 1,
                planned_count=count,
                created_at=now,
                started_at=now,
                updated_at=now,
            )
            session.add(automation)
            session.add_all([
                AutomationRunItem(
                    id=str(uuid4()),
                    project_id=catalog.id,
                    automation_run_id=run_id,
                    chapter_number=chapter,
                    sequence_number=offset,
                    status="waiting",
                    created_at=now,
                    updated_at=now,
                )
                for offset, chapter in enumerate(range(start, start + count), start=1)
            ])
        created_automation_ids.append(run_id)
        return service.phase7.get_run(catalog.id, run_id)

    def finish_batch(automation_run_id: str) -> None:
        catalog = service.get_project(project["id"])
        with service.db.project(catalog.id, catalog.folder_path) as session:
            chapters = list(session.scalars(select(AutomationRunItem.chapter_number).where(
                AutomationRunItem.automation_run_id == automation_run_id
            )).all())
        commit_ids = {
            chapter: _seed_official_chapter(client, project["id"], chapter)["commit"]
            for chapter in chapters
        }
        now = utc_now()
        with service.db.project_write(catalog.id, catalog.folder_path) as session:
            automation = session.get(AutomationRun, automation_run_id)
            automation.status = "completed"
            automation.succeeded_count = len(chapters)
            automation.completed_at = now
            automation.updated_at = now
            for item in session.scalars(select(AutomationRunItem).where(
                AutomationRunItem.automation_run_id == automation_run_id
            )).all():
                item.status = "committed"
                item.chapter_commit_id = commit_ids[item.chapter_number]
                item.completed_at = now
                item.updated_at = now

    service.phase7.create_manual_run = fake_async_create
    suite = client.post(
        f"/api/v1/projects/{project['id']}/endurance/suites",
        json={"targetChapterCount": 10},
    ).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/endurance/runs",
        json={"suiteId": suite["id"]},
    )
    assert response.status_code == 201, response.text
    endurance = response.json()
    assert endurance["status"] == "running"
    assert endurance["completedCount"] == 0
    assert endurance["findings"] == []
    assert len(created_automation_ids) == 1

    finish_batch(created_automation_ids[0])
    service.phase10.on_automation_terminal(project["id"], created_automation_ids[0])
    midway = client.get(f"/api/v1/projects/{project['id']}/endurance/runs/{endurance['id']}").json()
    assert midway["status"] == "running"
    assert midway["completedCount"] == 5
    assert "ENDURANCE_COMMIT_SEQUENCE_GAP" not in {item["ruleCode"] for item in midway["findings"] if item["status"] == "open"}
    assert len(created_automation_ids) == 2

    finish_batch(created_automation_ids[1])
    service.phase10.on_automation_terminal(project["id"], created_automation_ids[1])
    completed = client.get(f"/api/v1/projects/{project['id']}/endurance/runs/{endurance['id']}").json()
    assert completed["status"] == "completed"
    assert completed["completedCount"] == 10
    assert len(completed["checkpoints"]) == 10


def test_endurance_run_actions_require_current_revision(client: TestClient) -> None:
    project = _project(client)
    _ensure_ready_foundation(client, project["id"])
    service = client.app.state.story_service
    suite = client.post(f"/api/v1/projects/{project['id']}/endurance/suites", json={"targetChapterCount": 5}).json()
    catalog = service.get_project(project["id"])
    now = utc_now()
    with service.db.project_write(catalog.id, catalog.folder_path) as session:
        session.add(EnduranceRun(
            id="revision-run",
            project_id=catalog.id,
            suite_id=suite["id"],
            status="interrupted",
            start_chapter=1,
            end_chapter=5,
            target_chapter_count=5,
            revision=3,
            created_at=now,
            updated_at=now,
        ))
    stale = client.post(
        f"/api/v1/projects/{project['id']}/endurance/runs/revision-run/resume",
        json={"expectedRevision": 2},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "ENDURANCE_RUN_REVISION_CONFLICT"


def test_dispatch_failure_does_not_leave_active_endurance_run(client: TestClient) -> None:
    project = _project(client)
    _ensure_ready_foundation(client, project["id"])
    service = client.app.state.story_service
    suite = client.post(f"/api/v1/projects/{project['id']}/endurance/suites", json={"targetChapterCount": 5}).json()

    def fail_dispatch(project_id_arg, payload, request_id):
        raise StoryError(503, "MODEL_PROVIDER_UNAVAILABLE", "provider unavailable")

    service.phase7.create_manual_run = fail_dispatch
    response = client.post(
        f"/api/v1/projects/{project['id']}/endurance/runs",
        json={"suiteId": suite["id"], "idempotencyKey": "dispatch-failure"},
    )
    assert response.status_code == 503
    runs = client.get(f"/api/v1/projects/{project['id']}/endurance/runs").json()
    assert runs[0]["status"] == "failed"
    assert runs[0]["stopReason"] == "MODEL_PROVIDER_UNAVAILABLE"


def test_gap_restart_recovery_cancel_and_resume_drift(client: TestClient) -> None:
    project = _project(client)
    _ensure_ready_foundation(client, project["id"])
    service = client.app.state.story_service
    suite = client.post(f"/api/v1/projects/{project['id']}/endurance/suites", json={"targetChapterCount": 5}).json()
    catalog = service.get_project(project["id"])
    now = utc_now()
    with service.db.project_write(catalog.id, catalog.folder_path) as session:
        run = EnduranceRun(
            id="manual-run",
            project_id=catalog.id,
            suite_id=suite["id"],
            status="running",
            start_chapter=1,
            end_chapter=5,
            target_chapter_count=5,
            revision=1,
            created_at=now,
            started_at=now,
            updated_at=now,
        )
        automation = AutomationRun(
            id="manual-automation",
            project_id=catalog.id,
            policy_id=catalog.id,
            scheduled_local_date="2026-07-14",
            trigger="manual",
            status="failed",
            idempotency_key="endurance:manual-run:1",
            start_chapter=1,
            end_chapter=1,
            planned_count=1,
            created_at=now,
            started_at=now,
            completed_at=now,
            updated_at=now,
        )
        item = AutomationRunItem(
            id="manual-item",
            project_id=catalog.id,
            automation_run_id=automation.id,
            chapter_number=1,
            sequence_number=1,
            status="failed",
            created_at=now,
            started_at=now,
            completed_at=now,
            updated_at=now,
        )
        run.current_automation_run_id = automation.id
        session.add_all([run, automation, item])
    evaluated = client.post(
        f"/api/v1/projects/{project['id']}/endurance/runs/manual-run/evaluate",
        json={"expectedRevision": 1},
    )
    assert evaluated.status_code == 200
    assert "ENDURANCE_COMMIT_SEQUENCE_GAP" in {item["ruleCode"] for item in evaluated.json()["findings"]}

    service.phase10.recover_interrupted_endurance()
    assert client.get(f"/api/v1/projects/{project['id']}/endurance/runs/manual-run").json()["status"] in {"blocked", "interrupted"}

    ids = _seed_official_chapter(client, project["id"], 1)
    with service.db.project_write(catalog.id, catalog.folder_path) as session:
        run = session.get(EnduranceRun, "manual-run")
        run.status = "interrupted"
        checkpoint = EnduranceCheckpoint(
            id="checkpoint-1",
            project_id=catalog.id,
            run_id=run.id,
            chapter_number=1,
            chapter_commit_id=ids["commit"],
            source_version_id=ids["source"],
            state_snapshot_id=ids["snapshot"],
            commit_revision=1,
            source_revision=2,
            snapshot_revision=1,
            commit_checksum="old",
            source_checksum="old",
            snapshot_checksum="old",
            checkpoint_checksum="old",
            created_at=now,
        )
        session.add(checkpoint)
        run.last_checkpoint_id = checkpoint.id
        current_revision = run.revision
    resumed = client.post(
        f"/api/v1/projects/{project['id']}/endurance/runs/manual-run/resume",
        json={"expectedRevision": current_revision},
    )
    assert resumed.status_code == 409


def test_endurance_backup_restore_remaps_and_interrupts_active_run(client: TestClient) -> None:
    project = _project(client)
    _ensure_ready_foundation(client, project["id"])
    suite = client.post(f"/api/v1/projects/{project['id']}/endurance/suites", json={"targetChapterCount": 5}).json()
    service = client.app.state.story_service
    catalog = service.get_project(project["id"])
    now = utc_now()
    with service.db.project_write(catalog.id, catalog.folder_path) as session:
        session.add(EnduranceRun(
            id="active-endurance",
            project_id=catalog.id,
            suite_id=suite["id"],
            status="running",
            start_chapter=1,
            end_chapter=5,
            target_chapter_count=5,
            created_at=now,
            started_at=now,
            updated_at=now,
        ))
    backup = client.post(f"/api/v1/projects/{project['id']}/backups")
    assert backup.status_code == 201
    from pathlib import Path

    archive = Path(backup.json()["archivePath"])
    restored = client.post("/api/v1/projects/restore", files={"backup": (archive.name, archive.read_bytes(), "application/zip")})
    assert restored.status_code == 201, restored.text
    restored_id = restored.json()["id"]
    runs = client.get(f"/api/v1/projects/{restored_id}/endurance/runs").json()
    assert runs[0]["projectId"] == restored_id
    assert runs[0]["status"] == "interrupted"

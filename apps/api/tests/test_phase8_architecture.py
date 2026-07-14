from __future__ import annotations

import json

from fastapi.testclient import TestClient

from story_agent_api.models import CanonDocument, CanonGenerationProposal
from story_agent_api.services import StoryError, dumps


CANON_MARKDOWN = """# 《夜巡人》Story Core

## 一句话故事内核
沈砚在雾城调查夜雾与夜巡司，并追查自己被删除的童年记忆。

## 类型主题与文风
现代中式规则怪谈、悬疑调查、克制成长。文风具体、可视化，每个单章包含目标、阻力、转折和钩子。

## 时代地域与世界边界
当代雾城。夜雾只覆盖局部街区，怪异不能靠纯战力消灭。

## 主要人物与知识边界
沈砚只能依据亲历证据行动；白芷不知道夜巡司密档；老周受封口规则约束。

## 组织与关系
夜巡司负责记录和限制祟迹，内部存在封存派与利用派。

## 等级体系与升级条件
六阶为见雾、识祟、执灯、立契、巡界、守夜。每次升级必须满足证据、训练和代价。

## 能力边界与代价
见雾只能察觉；识祟辨认局部规则；执灯固定路径；立契限制一项异常；巡界建立临时边界；守夜处理城市级夜雾。能力使用会损失记忆或身体状态。

## 法器与物品台账
法器分遗物、巡器、封物、祟核。巡夜灯吞噬温暖记忆；镇纸钉固定影子七次呼吸；潮湿账页在夜雾中显示姓名。

## 硬规则与怪异规则
纸人只在未被活人直接目视时移动；巡夜灯只能照出已有路径。

## 七卷主线与1000章预算
七卷覆盖一千章，第一卷《雾城旧宅》为1至100章。

## 伏笔、揭示窗口与禁止提前事项
无脸纸童身份不得在43章前确认；童年真相第一层不得在92章前揭示；禁止提前完成终局。

## 第一卷升级预算
1至10章进入见雾，11至40章达到识祟，90至100章满足三条件后执灯。
"""


def _structured_entities() -> dict:
    names = [
        ("沈砚", "person"), ("白芷", "person"), ("老周", "person"), ("无脸纸童", "person"),
        ("雾城", "location"), ("夜巡司", "organization"), ("巡夜灯", "item"), ("镇纸钉", "item"),
        ("潮湿账页", "item"), ("见雾", "ability"),
    ]
    entities = [{"canonicalName": name, "entityTypeName": kind, "aliasesJson": [], "attributesJson": {"name": name}} for name, kind in names]
    relations = [
        {"subjectCanonicalName": "沈砚", "predicate": "works_with", "objectCanonicalName": "白芷"},
        {"subjectCanonicalName": "老周", "predicate": "served", "objectCanonicalName": "夜巡司"},
        {"subjectCanonicalName": "沈砚", "predicate": "uses", "objectCanonicalName": "巡夜灯"},
        {"subjectCanonicalName": "夜巡司", "predicate": "operates_in", "objectCanonicalName": "雾城"},
    ]
    return {"entities": entities, "relations": relations}


def _structured_rules() -> dict:
    return {"rules": [
        {"ruleCode": f"RULE-{index:02d}", "category": "boundary", "statement": statement, "severity": "high", "constraintJson": {"hard": True}}
        for index, statement in enumerate([
            "纸人未被直接目视时才能移动", "巡夜灯不能消灭怪异", "升级需要证据训练代价", "见雾不能主动干预",
            "无脸纸童身份不得提前揭示", "童年真相不得提前揭示", "法器必须记录代价", "人物知识边界不得串线",
        ], start=1)
    ]}


def test_standard_project_story_architecture_and_plan_flow(client: TestClient, monkeypatch) -> None:
    project = client.post("/api/v1/projects", json={"title": "夜巡人·正式试写", "mode": "long-form", "totalChapters": 1000}).json()
    assert project["currentChapter"] == 0
    assert project["projectKind"] == "standard"
    service = client.app.state.story_service

    def fake_complete(_project, _role, _messages, _request_id, *, response_json=False, run_role=None):
        if run_role in {"architect:story-blueprint-core", "architect:story-blueprint-systems"}:
            return CANON_MARKDOWN, "run-blueprint"
        if run_role == "architect:story-blueprint-repair":
            return "## 自动补充\n世界、时代、地域、人物、主角、组织、知识边界、关系、升级条件、代价、硬规则与怪异规则均以权威台账为准。", "run-repair"
        if run_role == "architect:proposal-analysis":
            return json.dumps({**_structured_entities(), **_structured_rules()}), "run-analysis"
        if run_role == "planner:hierarchical-plan":
            return json.dumps({"volumeThemes": [], "firstVolumeArcs": []}), "run-plan"
        raise AssertionError(run_role)

    monkeypatch.setattr(service.phase8, "_complete_role", fake_complete)
    brief = {
        "title": "夜巡人", "mode": "long-form", "targetChapters": 1000,
        "genre": "现代中式规则怪谈", "premise": "沈砚在雾城调查夜雾，并追查自己被删除的童年记忆。",
        "tone": "克制、悬疑、可视化", "progressionPreset": "restrained-explicit",
    }
    proposal_response = client.post(f"/api/v1/projects/{project['id']}/canon/generation-proposals", json=brief)
    assert proposal_response.status_code == 201, proposal_response.text
    proposal = proposal_response.json()
    assert proposal["readiness"]["ready"] is True
    # Readiness is a cache, not an authority. Applying must recompute it using
    # the current deterministic validator instead of trusting stale storage.
    with service.db.project_write(project["id"], project["folderPath"]) as session:
        stored = session.get(CanonGenerationProposal, proposal["id"])
        assert stored is not None
        stored.readiness_json = dumps({"ready": False, "checks": [{"code": "OLD_VALIDATOR"}]})
    applied = client.post(f"/api/v1/canon/generation-proposals/{proposal['id']}/apply", json={"expectedRevision": proposal["revision"]})
    assert applied.status_code == 200, applied.text
    canon = applied.json()
    assert len(canon["entities"]) >= 8
    assert client.get(f"/api/v1/projects/{project['id']}/canon/readiness").json()["ready"] is True
    document = canon["documents"][0]
    locked = client.post(f"/api/v1/projects/{project['id']}/canon/lock", json={"expectedRevision": document["revision"]})
    assert locked.status_code == 200, locked.text

    plan = client.get(f"/api/v1/projects/{project['id']}/plan").json()
    generated = client.post(f"/api/v1/projects/{project['id']}/plan/generation-proposals", json={
        "expectedPlanRevision": plan["revision"], "preciseChapterCount": 5,
    })
    assert generated.status_code == 201, generated.text
    plan_proposal = generated.json()
    assert plan_proposal["validation"]["valid"] is True
    applied_plan = client.post(f"/api/v1/plan/generation-proposals/{plan_proposal['id']}/apply", json={"expectedRevision": 1})
    assert applied_plan.status_code == 200, applied_plan.text
    nodes = applied_plan.json()["milestones"]
    opening = next(node for node in nodes if node["id"] == "arc-01-opening")
    assert [beat["chapterNumber"] for beat in opening["chapterBeats"]] == [1, 2, 3, 4, 5]


def test_canon_apply_rejects_stale_ready_snapshot_when_content_is_incomplete(client: TestClient) -> None:
    project = client.post(
        "/api/v1/projects",
        json={"title": "不完整设定测试", "mode": "long-form", "totalChapters": 1000},
    ).json()
    service = client.app.state.story_service
    proposal_id = "33333333-3333-4333-8333-333333333333"
    with service.db.project_write(project["id"], project["folderPath"]) as session:
        session.add(CanonGenerationProposal(
            id=proposal_id,
            project_id=project["id"],
            base_revision=1,
            status="pending",
            brief_json=dumps(_brief()),
            content_markdown="# 只有标题",
            structured_json=dumps(service.phase8._baseline_structure()),
            readiness_json=dumps({"ready": True, "checks": []}),
            model_run_id=None,
            revision=1,
        ))

    response = client.post(
        f"/api/v1/canon/generation-proposals/{proposal_id}/apply",
        json={"expectedRevision": 1},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CANON_PROPOSAL_INCOMPLETE"


def test_demo_project_cannot_start_paid_writing(client: TestClient, demo_project: dict) -> None:
    assert demo_project["projectKind"] == "demo"
    run = client.post(f"/api/v1/projects/{demo_project['id']}/automation/runs", json={"chapterCount": 1})
    assert run.status_code == 409
    assert run.json()["code"] == "DEMO_PROJECT_WRITE_BLOCKED"
    readiness = client.get(f"/api/v1/projects/{demo_project['id']}/trial-readiness?chapterCount=1").json()
    check = next(item for item in readiness["checks"] if item["code"] == "TRIAL_STANDARD_PROJECT_REQUIRED")
    assert check["status"] == "blocked"


def _brief(title: str = "夜巡人") -> dict:
    return {
        "title": title,
        "mode": "long-form",
        "targetChapters": 1000,
        "genre": "现代中式规则怪谈",
        "premise": "沈砚在雾城调查夜雾，并追查自己被删除的童年记忆。",
        "tone": "克制、悬疑、可视化",
        "progressionPreset": "restrained-explicit",
    }


def test_canon_checkpoint_preserves_core_after_systems_timeout_and_resumes_missing_section(
    client: TestClient, monkeypatch
) -> None:
    project = client.post("/api/v1/projects", json={"title": "夜巡人·正式试写", "mode": "long-form", "totalChapters": 1000}).json()
    service = client.app.state.story_service
    calls: list[str | None] = []
    fail_systems = True

    def fake_complete(_project, _role, _messages, _request_id, *, response_json=False, run_role=None):
        nonlocal fail_systems
        calls.append(run_role)
        if run_role == "architect:story-blueprint-core":
            return CANON_MARKDOWN, "run-core"
        if run_role == "architect:story-blueprint-systems":
            if fail_systems:
                fail_systems = False
                raise StoryError(502, "MODEL_TIMEOUT", "systems timed out")
            return CANON_MARKDOWN, "run-systems"
        if run_role == "architect:proposal-analysis":
            return json.dumps({**_structured_entities(), **_structured_rules()}), "run-analysis"
        if run_role == "architect:story-blueprint-repair":
            return "## 自动补充\n世界、时代、地域、人物、主角、组织、知识边界、关系、升级条件、代价、硬规则与怪异规则均以权威台账为准。", "run-repair"
        raise AssertionError(run_role)

    monkeypatch.setattr(service.phase8, "_complete_role", fake_complete)

    failed = client.post(f"/api/v1/projects/{project['id']}/canon/generation-proposals", json=_brief())
    assert failed.status_code == 502
    proposals = client.get(f"/api/v1/projects/{project['id']}/canon/generation-proposals").json()
    assert proposals[0]["status"] == "failed"
    assert "core" in proposals[0]["structured"]["generationSections"]
    assert "systems" not in proposals[0]["structured"]["generationSections"]

    calls.clear()
    retried = client.post(f"/api/v1/projects/{project['id']}/canon/generation-proposals", json=_brief())
    assert retried.status_code == 201, retried.text
    assert "architect:story-blueprint-core" not in calls
    assert calls.count("architect:story-blueprint-systems") == 1
    assert calls.count("architect:proposal-analysis") >= 1
    assert retried.json()["status"] == "pending"
    assert retried.json()["readiness"]["ready"] is True


def test_canon_generation_recovery_marks_generating_failed_without_losing_sections(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"title": "夜巡人·正式试写", "mode": "long-form", "totalChapters": 1000}).json()
    service = client.app.state.story_service
    proposal_id = "11111111-1111-4111-8111-111111111111"
    with service.db.project_write(project["id"], project["folderPath"]) as session:
        session.add(CanonGenerationProposal(
            id=proposal_id,
            project_id=project["id"],
            base_revision=1,
            status="generating",
            brief_json=dumps(_brief()),
            content_markdown="# checkpoint",
            structured_json=dumps({"generationSections": {"core": "kept core"}}),
            readiness_json=dumps({}),
            model_run_id=None,
            revision=1,
        ))

    service.phase8.recover_interrupted_generations()

    proposals = client.get(f"/api/v1/projects/{project['id']}/canon/generation-proposals").json()
    proposal = next(item for item in proposals if item["id"] == proposal_id)
    assert proposal["status"] == "failed"
    assert proposal["structured"]["generationSections"]["core"] == "kept core"
    assert proposal["readiness"]["checks"][0]["code"] == "CANON_GENERATION_INTERRUPTED"


def test_canon_checkpoint_is_not_reused_for_different_brief_or_revision(client: TestClient, monkeypatch) -> None:
    project = client.post("/api/v1/projects", json={"title": "夜巡人·正式试写", "mode": "long-form", "totalChapters": 1000}).json()
    service = client.app.state.story_service
    with service.db.project_write(project["id"], project["folderPath"]) as session:
        session.add(CanonGenerationProposal(
            id="22222222-2222-4222-8222-222222222222",
            project_id=project["id"],
            base_revision=1,
            status="failed",
            brief_json=dumps(_brief("夜巡人")),
            content_markdown="# checkpoint",
            structured_json=dumps({"generationSections": {"core": "old core", "systems": "old systems"}}),
            readiness_json=dumps({}),
            model_run_id=None,
            revision=1,
        ))
        document = session.get(CanonDocument, "story-core")
        assert document is not None
        document.content_markdown = "# existing canon"
        document.revision = 2

    calls: list[str | None] = []

    def fake_complete(_project, _role, _messages, _request_id, *, response_json=False, run_role=None):
        calls.append(run_role)
        if run_role in {"architect:story-blueprint-core", "architect:story-blueprint-systems"}:
            return CANON_MARKDOWN, f"run-{run_role}"
        if run_role == "architect:proposal-analysis":
            return json.dumps({**_structured_entities(), **_structured_rules()}), "run-analysis"
        if run_role == "architect:story-blueprint-repair":
            return "## 自动补充\n世界、时代、地域、人物、主角、组织、知识边界、关系、升级条件、代价、硬规则与怪异规则均以权威台账为准。", "run-repair"
        raise AssertionError(run_role)

    monkeypatch.setattr(service.phase8, "_complete_role", fake_complete)

    same_brief_new_revision = client.post(f"/api/v1/projects/{project['id']}/canon/generation-proposals", json=_brief("夜巡人"))
    assert same_brief_new_revision.status_code == 201, same_brief_new_revision.text
    assert "architect:story-blueprint-core" in calls
    assert same_brief_new_revision.json()["baseRevision"] == 2

    calls.clear()
    different_brief = client.post(f"/api/v1/projects/{project['id']}/canon/generation-proposals", json=_brief("夜巡人新构想"))
    assert different_brief.status_code == 201, different_brief.text
    assert "architect:story-blueprint-core" in calls


def test_canon_analysis_fails_after_two_invalid_json_attempts_and_cannot_apply(client: TestClient, monkeypatch) -> None:
    project = client.post("/api/v1/projects", json={"title": "夜巡人·正式试写", "mode": "long-form", "totalChapters": 1000}).json()
    service = client.app.state.story_service

    def fake_complete(_project, _role, _messages, _request_id, *, response_json=False, run_role=None):
        if run_role in {"architect:story-blueprint-core", "architect:story-blueprint-systems"}:
            return CANON_MARKDOWN, f"run-{run_role}"
        if run_role == "architect:proposal-analysis":
            return "{not valid json", "run-invalid"
        raise AssertionError(run_role)

    monkeypatch.setattr(service.phase8, "_complete_role", fake_complete)
    failed = client.post(f"/api/v1/projects/{project['id']}/canon/generation-proposals", json=_brief())
    assert failed.status_code == 422
    assert failed.json()["code"] == "CANON_ANALYSIS_INVALID"
    proposal = client.get(f"/api/v1/projects/{project['id']}/canon/generation-proposals").json()[0]
    assert proposal["status"] == "failed"
    assert set(proposal["structured"]["generationSections"]) == {"core", "systems"}
    assert proposal["readiness"]["checks"][0]["code"] == "CANON_ANALYSIS_INVALID"

    apply_response = client.post(
        f"/api/v1/canon/generation-proposals/{proposal['id']}/apply",
        json={"expectedRevision": proposal["revision"]},
    )
    assert apply_response.status_code == 409
    assert apply_response.json()["code"] == "CANON_PROPOSAL_NOT_PENDING"

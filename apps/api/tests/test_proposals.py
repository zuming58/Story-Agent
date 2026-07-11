from __future__ import annotations

from fastapi.testclient import TestClient


def pending_proposal(client: TestClient, project_id: str) -> dict:
    response = client.get(f"/api/v1/projects/{project_id}/change-proposals", params={"status": "pending"})
    assert response.status_code == 200
    return response.json()[0]


def test_apply_proposal_is_transactional_and_undoable(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    proposal = pending_proposal(client, project_id)
    operation_ids = [operation["id"] for operation in proposal["operations"]]
    applied = client.post(
        f"/api/v1/change-proposals/{proposal['id']}/apply",
        json={"projectId": project_id, "expectedRevision": proposal["revision"], "selectedOperationIds": operation_ids},
    )
    assert applied.status_code == 200
    assert applied.json()["status"] == "accepted"
    plan = client.get(f"/api/v1/projects/{project_id}/plan").json()
    node = next(item for item in plan["milestones"] if item["id"] == proposal["targetId"])
    assert (node["targetChapter"], node["rangeMin"], node["rangeMax"]) == (22, 20, 25)

    audit = client.get(f"/api/v1/projects/{project_id}/audit-events").json()
    event = next(item for item in audit if item["eventType"] == "proposal.applied")
    undone = client.post(f"/api/v1/projects/{project_id}/audit-events/{event['id']}/undo")
    assert undone.status_code == 200
    restored = client.get(f"/api/v1/projects/{project_id}/plan").json()
    restored_node = next(item for item in restored["milestones"] if item["id"] == proposal["targetId"])
    assert (restored_node["targetChapter"], restored_node["rangeMin"], restored_node["rangeMax"]) == (18, 16, 21)


def test_failed_proposal_rolls_back_everything(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    proposal = pending_proposal(client, project_id)
    target_only = next(operation for operation in proposal["operations"] if operation["field"] == "targetChapter")
    failed = client.post(
        f"/api/v1/change-proposals/{proposal['id']}/apply",
        json={"projectId": project_id, "expectedRevision": proposal["revision"], "selectedOperationIds": [target_only["id"]]},
    )
    assert failed.status_code == 422
    after = pending_proposal(client, project_id)
    assert after["revision"] == proposal["revision"]
    plan = client.get(f"/api/v1/projects/{project_id}/plan").json()
    node = next(item for item in plan["milestones"] if item["id"] == proposal["targetId"])
    assert node["targetChapter"] == 18


def test_reject_does_not_modify_plan(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]
    proposal = pending_proposal(client, project_id)
    before = client.get(f"/api/v1/projects/{project_id}/plan").json()
    rejected = client.post(
        f"/api/v1/change-proposals/{proposal['id']}/reject",
        json={"projectId": project_id, "expectedRevision": proposal["revision"]},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert client.get(f"/api/v1/projects/{project_id}/plan").json() == before

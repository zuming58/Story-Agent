from __future__ import annotations

from fastapi.testclient import TestClient


def test_canon_entity_type_uses_schema_json_alias(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]

    response = client.get(f"/api/v1/projects/{project_id}/canon")
    assert response.status_code == 200, response.text

    entity_types = response.json()["entityTypes"]
    assert entity_types
    assert "schemaJson" in entity_types[0]
    assert "schema_data" not in entity_types[0]


def test_phase4_retrieval_search_returns_indexed_hits(client: TestClient, demo_project: dict) -> None:
    project_id = demo_project["id"]

    locked = client.post(f"/api/v1/projects/{project_id}/canon/lock", json={"expectedRevision": 1})
    assert locked.status_code == 200, locked.text

    rebuild = client.post(f"/api/v1/projects/{project_id}/retrieval/rebuild")
    assert rebuild.status_code == 200, rebuild.text

    response = client.post(f"/api/v1/projects/{project_id}/retrieval/search", json={"query": "夜巡人", "limit": 10})
    assert response.status_code == 200, response.text

    hits = response.json()
    assert hits
    assert all("id" in hit for hit in hits)
    assert all("score" in hit for hit in hits)

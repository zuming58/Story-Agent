from __future__ import annotations

from story_agent_api.research_providers import (
    DeterministicContentFetchProvider,
    DeterministicSearchProvider,
    FetchResponse,
    SearchResult,
)


def _project(client):
    response = client.post("/api/v1/projects", json={"title": "Fresh incubator project", "mode": "long-form", "totalChapters": 40})
    assert response.status_code == 201, response.text
    return response.json()


def _configure_research(client):
    search = DeterministicSearchProvider()
    fetch = DeterministicContentFetchProvider()
    urls = [
        "https://platform.example.test/trends",
        "https://reviews.example.test/praise",
        "https://forum.example.test/dropoff",
        "https://analysis.example.test/opening",
        "https://publisher.example.test/serial",
        "https://other.example.test/leaders",
    ]
    for perspective, url in zip(("platform_trends", "genre_leaders", "reader_praise", "reader_dropoff", "opening_strategy", "serial_engine"), urls, strict=True):
        query = f"undecided urban mystery adult readers {perspective.replace('_', ' ')}".replace("platform trends", "platform trends").replace("genre leaders", "leading works").replace("reader praise", "reader praise").replace("reader dropoff", "reader dropoff reasons").replace("opening strategy", "opening hook strategy").replace("serial engine", "serial retention engine")
        search.fixtures[query] = [SearchResult(url=url, title=perspective, domain=url.split("/")[2])]
        fetch.fixtures[url] = FetchResponse(requested_url=url, final_url=url, title=perspective, content=f"Evidence for {perspective}. " * 20)
    service = client.app.state.story_service
    service.phase13.search_provider = search
    service.phase13.fetch_provider = fetch
    return search, fetch


def _brief(client, project_id, expected_revision=0):
    response = client.post(f"/api/v1/projects/{project_id}/research/briefs", json={
        "expectedRevision": expected_revision,
        "format": "long-form",
        "platform": "undecided",
        "genre": "urban mystery",
        "audience": "adult readers",
        "emotionalValue": ["tension"],
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_research_to_opening_selection_is_isolated_and_deterministic(client):
    project = _project(client)
    search, fetch = _configure_research(client)
    brief = _brief(client, project["id"])
    job_response = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"],
        "searchProvider": "deterministic",
        "fetchProvider": "deterministic",
    })
    assert job_response.status_code == 201, job_response.text
    job = job_response.json()
    assert job["status"] == "awaiting_review"
    assert len(search.calls) == 6
    assert len(fetch.calls) == 6
    sources = client.get(f"/api/v1/research/jobs/{job['id']}/sources")
    assert sources.status_code == 200
    assert len(sources.json()) == 6
    evidence = client.get(f"/api/v1/research/jobs/{job['id']}/evidence").json()
    assert len(evidence) == 6

    score = {"platformFit": 15, "openingHook": 15, "emotionalPayoff": 15, "differentiation": 15, "serialEngine": 15, "characterStickiness": 10, "worldEngine": 10, "readability": 5}
    opportunities = client.post(f"/api/v1/research/jobs/{job['id']}/opportunities", json={
        "expectedJobRevision": job["revision"],
        "opportunities": [{
            "highConcept": f"Direction {number}", "protagonist": "Ming", "coreDesire": "Find a missing sibling", "coreConflict": "Every clue costs trust", "worldMechanism": "notApplicable", "firstThreeChapterPromise": "A clue, a choice, and a consequence", "serialEngine": "Each clue opens another obligation", "scoreComponents": score, "evidenceIds": [item["id"] for item in evidence], "evidenceCoverage": 1, "confidence": 0.7,
        } for number in range(1, 4)],
    })
    assert opportunities.status_code == 201, opportunities.text
    first = opportunities.json()[0]
    assert first["totalScore"] == 100
    accepted = client.post(f"/api/v1/story-opportunities/{first['id']}/accept", json={"expectedRevision": first["revision"]})
    assert accepted.status_code == 200, accepted.text
    opportunity = accepted.json()

    ideation = client.post(f"/api/v1/projects/{project['id']}/ideation/sessions", json={"opportunityId": opportunity["id"], "expectedOpportunityRevision": opportunity["revision"]})
    assert ideation.status_code == 201, ideation.text
    session = ideation.json()
    message = client.post(f"/api/v1/ideation/sessions/{session['id']}/messages", json={"expectedSessionRevision": session["revision"], "content": "No archive-number exposition."})
    assert message.status_code == 201, message.text
    proposal = client.post(f"/api/v1/ideation/sessions/{session['id']}/story-brief-proposals", json={"expectedSessionRevision": session["revision"] + 1})
    assert proposal.status_code == 201, proposal.text
    applied = client.post(f"/api/v1/story-brief-proposals/{proposal.json()['id']}/apply", json={"expectedRevision": proposal.json()["revision"]})
    assert applied.status_code == 200, applied.text
    brief_version = client.get(f"/api/v1/projects/{project['id']}/story-brief/current").json()

    canon = client.post(f"/api/v1/projects/{project['id']}/incubation/canon-proposals", json={"expectedStoryBriefRevision": brief_version["revision"]})
    assert canon.status_code == 201, canon.text
    assert "Night Watch" not in canon.json()["contentMarkdown"]
    canon_applied = client.post(f"/api/v1/canon/generation-proposals/{canon.json()['id']}/apply", json={"expectedRevision": canon.json()["revision"]})
    assert canon_applied.status_code == 200, canon_applied.text
    current_canon = client.get(f"/api/v1/projects/{project['id']}/canon").json()["documents"][0]

    experiment = client.post(f"/api/v1/projects/{project['id']}/opening-experiments", json={"expectedStoryBriefRevision": brief_version["revision"], "expectedCanonRevision": current_canon["revision"]})
    assert experiment.status_code == 201, experiment.text
    output = experiment.json()
    assert len(output["candidates"]) == 3
    assert all(len(candidate["evaluations"]) == 2 for candidate in output["candidates"])
    selected = output["candidates"][0]
    choice = client.post(f"/api/v1/opening-candidates/{selected['id']}/select", json={"expectedRevision": selected["revision"], "expectedExperimentRevision": output["revision"]})
    assert choice.status_code == 200, choice.text
    readiness = client.get(f"/api/v1/projects/{project['id']}/incubation-readiness")
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is True


def test_ssrf_policy_rejects_local_and_private_addresses():
    from story_agent_api.research_providers import ResearchSourcePolicy, ResearchSourcePolicyError

    policy = ResearchSourcePolicy(resolver=lambda *_args, **_kwargs: [(None, None, None, None, ("10.0.0.4", 0))])
    for url in ("file:///tmp/story", "http://localhost/", "http://127.0.0.1/", "http://example.test/"):
        try:
            policy.validate_url(url)
        except ResearchSourcePolicyError:
            pass
        else:
            raise AssertionError(f"Expected source policy to reject {url}")


def test_phase13_backup_restore_remaps_internal_identity_chain(client):
    project = _project(client)
    _configure_research(client)
    brief = _brief(client, project["id"])
    job = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"], "searchProvider": "deterministic", "fetchProvider": "deterministic",
    }).json()
    backup = client.post(f"/api/v1/projects/{project['id']}/backups")
    assert backup.status_code == 201, backup.text
    from pathlib import Path
    archive = Path(backup.json()["archivePath"])
    restored = client.post("/api/v1/projects/restore", files={"backup": (archive.name, archive.read_bytes(), "application/zip")})
    assert restored.status_code == 201, restored.text
    clone = restored.json()
    clone_brief = client.get(f"/api/v1/projects/{clone['id']}/research/briefs").json()[0]
    clone_job = client.get(f"/api/v1/projects/{clone['id']}/research/jobs").json()[0]
    assert clone_brief["id"] != brief["id"]
    assert clone_brief["projectId"] == clone["id"]
    assert clone_job["id"] != job["id"]
    assert clone_job["briefId"] == clone_brief["id"]
    sources = client.get(f"/api/v1/research/jobs/{clone_job['id']}/sources")
    assert sources.status_code == 200
    assert all(item["projectId"] == clone["id"] and item["jobId"] == clone_job["id"] for item in sources.json())

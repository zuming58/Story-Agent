from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import httpx

from story_agent_api.research_providers import (
    DeterministicContentFetchProvider,
    DeterministicSearchProvider,
    FetchResponse,
    SearchResponse,
    SearchResult,
    TavilySearchProvider,
)
from story_agent_api.services import StoryError


class _FakeModelHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        response = json.dumps({"data": [{"id": "fake-incubator"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(response))); self.end_headers(); self.wfile.write(response)

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(body or b"{}")
        joined = "\n".join(item.get("content", "") for item in payload.get("messages", []) if isinstance(item, dict))
        step = next((name for name in ("query_plan", "evidence", "research_report", "opportunity_repair", "opportunities", "ideation", "story_brief", "canon_analyze", "canon_repair", "canon", "opening_expand", "opening", "opening_review") if f'"phase14Step":"{name}"' in joined or f'"phase14Step": "{name}"' in joined), "")
        perspectives = ["platform_trends", "genre_leaders", "reader_praise", "reader_dropoff", "opening_strategy", "serial_engine"]
        if step == "query_plan": value = {"queries": [{"perspective": item, "query": f"undecided urban mystery adult readers {item.replace('_', ' ')}".replace("genre leaders", "leading works").replace("reader praise", "reader praise").replace("reader dropoff", "reader dropoff reasons").replace("opening strategy", "opening hook strategy").replace("serial engine", "serial retention engine")} for item in perspectives]}
        elif step == "evidence":
            source = json.loads(next(item.get("content", "{}") for item in payload["messages"] if item.get("role") == "user")) ["sourceContent"]
            first, second = source[:40], source[40:80]
            value = {"evidence": [
                {"claimType": "fact", "claim": "bounded source evidence", "excerpt": first, "locator": {"start": 0, "end": len(first)}, "confidence": 0.7},
                {"claimType": "opinion", "claim": "bounded source opinion", "excerpt": second, "locator": {"start": 40, "end": 40 + len(second)}, "confidence": 0.6},
            ]}
        elif step == "research_report":
            data = json.loads(next(item.get("content", "{}") for item in payload["messages"] if item.get("role") == "user")); evidence = data["evidence"]; value = {"competitors": [{"name": "Comparable", "profile": {"readingPromise": "A bounded promise"}, "evidenceIds": [evidence[0]["id"]], "confidence": 0.6}], "findings": [{"category": "opening_strategy", "statement": "Evidence-backed finding.", "claimType": "inference", "evidenceIds": [evidence[0]["id"]], "confidence": 0.6, "uncertainties": ["sample"]}]}
        elif step in {"opportunities", "opportunity_repair"}:
            data = json.loads(next(item.get("content", "{}") for item in payload["messages"] if item.get("role") == "user")); ids = [item["id"] for item in data["report"]["evidence"]] if step == "opportunities" else data["allowedEvidenceIds"]; score = {"platformFit": 12, "openingHook": 12, "emotionalPayoff": 10, "differentiation": 10, "serialEngine": 10, "characterStickiness": 8, "worldEngine": 8, "readability": 4}; n = int(data.get("candidateIndex", 1)); value = {"opportunities": [{"title": f"Direction {n}", "summary": f"A concise overview for direction {n}.", "highConcept": f"Direction {n}", "protagonist": "Ming", "coreDesire": "Find truth", "coreConflict": "Truth costs trust", "worldMechanism": "notEstablished", "firstThreeChapterPromise": "A choice", "serialEngine": "notEstablished", "differentiation": ["original"], "risks": [], "scoreComponents": score, "evidenceIds": ids, "evidenceCoverage": 0.8, "confidence": 0.6, "uncertainties": []}]}
        elif step == "ideation": value = {"reply": "A concrete constraint is recorded.", "confirmedDecisions": [], "openQuestions": [], "aiSuggestions": [], "conflicts": [], "evidenceIds": []}
        elif step == "story_brief": value = {"brief": {"format":"long-form","platform":"undecided","audience":"adult readers","chapterWordRange":{"min":100,"max":1000},"premise":"A costly search","readerPromise":"A choice","theme":"trust","tone":"scene-led","pov":"close third","pace":"purposeful","endingDirection":"consequence","protagonist":"Ming","coreDesire":"Find truth","coreConflict":"Truth costs trust","worldMechanism":"notApplicable","serialEngine":"Escalation","emotionalRewards":["tension"],"differentiators":["original"],"forbiddenContent":[],"referenceTraits":["abstract"]}}
        elif step in {"canon", "canon_repair"}: value = {"markdown": "# Story Core\nMing searches for truth.\n## Conflict\nTruth costs trust.\n## Boundaries\nNo imitation and no unsupported facts.", "structured": {"entities": [{"canonicalName":"Ming","entityTypeName":"person","aliasesJson":[],"attributesJson":{"desire":"Find truth"}}], "relations": [], "rules": [{"ruleCode":"TRUTH-COST","category":"story","statement":"Truth costs trust.","severity":"high","constraintJson":{"hard":True}}]}}
        elif step == "canon_analyze": value = {"structured": {"entities": [{"canonicalName":"Ming","entityTypeName":"person","aliasesJson":[],"attributesJson":{"desire":"Find truth"}}], "relations": [], "rules": [{"ruleCode":"TRUTH-COST","category":"story","statement":"Truth costs trust.","severity":"high","constraintJson":{"hard":True}}]}}
        elif step == "opening_review": value = {"scores": {"firstScreenHook":78,"characterDesire":76,"emotionalPull":72,"sceneTension":75,"expositionDensity":20,"terminologyRepetition":5,"dialogueActionExplanationBalance":74,"continueReading":77}, "findings": [], "recommendation": "continue", "summary": "Independent review."}
        elif step == "opening_expand": value = {"chapters": [{"chapterNumber": 2, "title": "Two", "content": ("Ming follows the physical consequence into a crowded station and must choose whom to trust before the doors close. " * 12)}, {"chapterNumber": 3, "title": "Three", "content": ("At dawn, a witness changes the bargain and Ming risks a private memory to keep the investigation alive. " * 12)}]}
        else:
            data = json.loads(next(item.get("content", "{}") for item in payload["messages"] if item.get("role") == "user"))
            key = data.get("strategy", {}).get("key", "opening")
            seeds = {"strong-event":"A public alarm forces Ming to rescue a stranger while losing the only safe exit. ", "strong-character":"Ming rejects an easy lie and pays for the decision in front of someone important. ", "strong-mystery":"A sealed message answers a question Ming has never asked and demands a choice before sunrise. "}
            value = {"chapter": {"title": key, "content": seeds.get(key, seeds["strong-event"]) * 14}}
        if payload.get("stream"):
            events = [
                {"model": "fake-incubator", "choices": [{"delta": {"reasoning_content": "planning"}, "finish_reason": None}]},
                {"model": "fake-incubator", "choices": [{"delta": {"content": json.dumps(value)}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
            ]
            response = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
            encoded = response.encode()
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
            return
        response = json.dumps({"model":"fake-incubator", "choices":[{"message":{"content":json.dumps(value)},"finish_reason":"stop"}], "usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(response))); self.end_headers(); self.wfile.write(response)
    def log_message(self, *_args): return


def _configure_models(client):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeModelHandler); threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address
    provider = client.post("/api/v1/model-providers", json={"name":"Phase 14 Fake","baseUrl":f"http://{host}:{port}","timeoutSeconds":5,"maxRetries":0,"apiKey":"fake"}).json()
    model = client.post(f"/api/v1/model-providers/{provider['id']}/models", json={"modelId":"fake-incubator","displayName":"Fake"}).json()
    for role in ("research_planner", "research_analyst", "story_incubator", "reader_simulator", "opening_editor"):
        assert client.put(f"/api/v1/model-role-bindings/{role}", json={"modelId":model["id"]}).status_code == 200
    assert client.post(f"/api/v1/model-providers/{provider['id']}/test").json()["ok"] is True
    return server


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
    _configure_models(client)
    service.phase13.search_provider = search
    service.phase13.fetch_provider = fetch
    return search, fetch


def _brief(client, project_id, expected_revision=0, **overrides):
    payload = {
        "expectedRevision": expected_revision,
        "format": "long-form",
        "platform": "undecided",
        "genre": "urban mystery",
        "audience": "adult readers",
        "emotionalValue": ["tension"],
    }
    payload.update(overrides)
    response = client.post(f"/api/v1/projects/{project_id}/research/briefs", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_research_to_opening_selection_is_isolated_and_deterministic(client, monkeypatch):
    project = _project(client)
    search, fetch = _configure_research(client)
    phase13 = client.app.state.story_service.phase13
    original_complete = phase13._complete_model_json
    calls = []

    def capture_complete(*args, **kwargs):
        calls.append({"run_role": args[2], "kwargs": kwargs})
        return original_complete(*args, **kwargs)

    monkeypatch.setattr(phase13, "_complete_model_json", capture_complete)
    brief = _brief(client, project["id"])
    job_response = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"],
        "searchProvider": "deterministic",
        "fetchProvider": "deterministic",
    })
    assert job_response.status_code == 201, job_response.text
    job = job_response.json()
    assert job["status"] == "awaiting_review", job
    assert len(search.calls) == 6
    assert len(fetch.calls) == 6
    sources = client.get(f"/api/v1/research/jobs/{job['id']}/sources")
    assert sources.status_code == 200
    assert len(sources.json()) == 6
    queries = client.get(f"/api/v1/research/jobs/{job['id']}/queries")
    assert queries.status_code == 200
    assert len(queries.json()) == 6
    assert all(item["status"] == "succeeded" and item["resultCount"] == 1 for item in queries.json())
    evidence = client.get(f"/api/v1/research/jobs/{job['id']}/evidence").json()
    assert len(evidence) >= 6
    research_accepted = client.post(f"/api/v1/research/jobs/{job['id']}/accept", json={"expectedRevision": job["revision"]})
    assert research_accepted.status_code == 200, research_accepted.text
    job = research_accepted.json()

    opportunities = client.post(f"/api/v1/research/jobs/{job['id']}/opportunities", json={
        "expectedJobRevision": job["revision"],
    })
    assert opportunities.status_code == 201, opportunities.text
    first = opportunities.json()[0]
    assert first["totalScore"] == 74
    restored_opportunities = client.get(f"/api/v1/projects/{project['id']}/story-opportunities?jobId={job['id']}")
    assert restored_opportunities.status_code == 200
    assert {item["id"] for item in restored_opportunities.json()} == {item["id"] for item in opportunities.json()}
    accepted = client.post(f"/api/v1/story-opportunities/{first['id']}/accept", json={"expectedRevision": first["revision"]})
    assert accepted.status_code == 200, accepted.text
    opportunity = accepted.json()

    ideation = client.post(f"/api/v1/projects/{project['id']}/ideation/sessions", json={"opportunityId": opportunity["id"], "expectedOpportunityRevision": opportunity["revision"]})
    assert ideation.status_code == 201, ideation.text
    session = ideation.json()
    message = client.post(f"/api/v1/ideation/sessions/{session['id']}/messages", json={"expectedSessionRevision": session["revision"], "content": "No archive-number exposition."})
    assert message.status_code == 201, message.text
    premature = client.post(f"/api/v1/ideation/sessions/{session['id']}/story-brief-proposals", json={"expectedSessionRevision": session["revision"] + 1})
    assert premature.status_code == 409
    assert premature.json()["code"] == "IDEATION_DISCUSSION_REQUIRED"
    second_message = client.post(f"/api/v1/ideation/sessions/{session['id']}/messages", json={"expectedSessionRevision": session["revision"] + 1, "content": "The protagonist must make a costly choice in the first screen."})
    assert second_message.status_code == 201, second_message.text
    proposal = client.post(f"/api/v1/ideation/sessions/{session['id']}/story-brief-proposals", json={"expectedSessionRevision": session["revision"] + 2})
    assert proposal.status_code == 201, proposal.text
    restored_proposals = client.get(f"/api/v1/projects/{project['id']}/story-brief/proposals?sessionId={session['id']}")
    assert restored_proposals.status_code == 200
    assert restored_proposals.json()[0]["id"] == proposal.json()["id"]
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
    assert readiness.json()["ready"] is False
    assert client.post(f"/api/v1/projects/{project['id']}/canon/lock", json={"expectedRevision": current_canon["revision"]}).status_code == 409

    expanded = client.post(f"/api/v1/opening-experiments/{output['id']}/expand-to-three-chapters", json={
        "expectedRevision": choice.json()["revision"] + 1,
        "selectedCandidateId": choice.json()["id"],
        "expectedCandidateRevision": choice.json()["revision"],
    })
    assert expanded.status_code == 200, expanded.text
    candidate = next(item for item in expanded.json()["candidates"] if item["id"] == choice.json()["id"])
    for chapter_number in (1, 2, 3):
        approved = client.post(f"/api/v1/opening-candidates/{candidate['id']}/chapters/approve", json={
            "expectedRevision": candidate["revision"], "chapterNumber": chapter_number,
        })
        assert approved.status_code == 200, approved.text
        candidate = approved.json()
    readiness = client.get(f"/api/v1/projects/{project['id']}/incubation-readiness")
    assert readiness.json()["ready"] is True
    assert client.post(f"/api/v1/projects/{project['id']}/canon/lock", json={"expectedRevision": current_canon["revision"]}).status_code == 200
    runs = client.get(f"/api/v1/projects/{project['id']}/model-runs").json()
    roles = {item["role"] for item in runs}
    assert {"research_planner:query-plan", "research_analyst:report", "story_incubator:opportunities", "story_incubator:story-brief", "story_incubator:canon", "research_analyst:canon-analyzer", "reader_simulator:opening-review", "opening_editor:opening-review"}.issubset(roles)
    incubator_calls = [item for item in calls if item["run_role"].startswith("story_incubator:")]
    assert {"story_incubator:ideation", "story_incubator:story-brief", "story_incubator:canon", "story_incubator:opening-expand"}.issubset({item["run_role"] for item in incubator_calls})
    assert any(item["run_role"].startswith("story_incubator:opportunities") for item in incubator_calls)
    assert any(item["run_role"].startswith("story_incubator:opening:") for item in incubator_calls)
    assert all(item["kwargs"].get("stream_response") is True for item in incubator_calls)


def test_query_plan_repairs_valid_json_with_missing_queries(client, monkeypatch):
    phase13 = client.app.state.story_service.phase13
    calls = []
    perspectives = ["platform_trends", "genre_leaders", "reader_praise", "reader_dropoff", "opening_strategy", "serial_engine"]
    outputs = [
        {"analysis": "The plan should cover six perspectives."},
        {"queries": [{"perspective": item, "query": f"public query for {item}"} for item in perspectives]},
    ]

    def fake_complete(*args, **kwargs):
        calls.append({"runRole": args[2], "payload": args[5]})
        return outputs.pop(0), f"run-{len(calls)}"

    monkeypatch.setattr(phase13, "_complete_model_json", fake_complete)
    planned = phase13._model_queries(SimpleNamespace(id="project-test"), {"genre": "mixed genre"}, "request-test", "job-test")

    assert [perspective for perspective, _ in planned] == perspectives
    assert [item["runRole"] for item in calls] == ["research_planner:query-plan", "research_planner:query-plan:schema-repair"]
    assert calls[1]["payload"]["validationError"] == "RESEARCH_QUERY_PLAN_INVALID"


def test_query_plan_still_fails_when_schema_repair_is_incomplete(client, monkeypatch):
    phase13 = client.app.state.story_service.phase13
    outputs = [
        {"queries": []},
        {"queries": [{"perspective": "platform_trends", "query": "one query only"}]},
    ]

    monkeypatch.setattr(phase13, "_complete_model_json", lambda *args, **kwargs: (outputs.pop(0), "run-test"))
    with pytest.raises(StoryError) as error:
        phase13._model_queries(SimpleNamespace(id="project-test"), {"genre": "mixed genre"}, "request-test", "job-test")

    assert error.value.code == "RESEARCH_QUERY_PLAN_INCOMPLETE"


@pytest.mark.parametrize(("status", "code"), [(401, "SEARCH_AUTH_FAILED"), (403, "SEARCH_AUTH_FAILED"), (429, "SEARCH_RATE_LIMITED"), (500, "SEARCH_PROVIDER_FAILED")])
def test_tavily_http_failures_are_safe_and_actionable(monkeypatch, status, code):
    def post(*_args, **_kwargs):
        return httpx.Response(status, request=httpx.Request("POST", "https://api.tavily.com/search"))

    monkeypatch.setattr("story_agent_api.research_providers.httpx.post", post)
    provider = TavilySearchProvider("not-a-real-key")
    with pytest.raises(Exception) as error:
        provider.search("test query", [], None, 1)
    assert getattr(error.value, "code", None) == code
    assert "not-a-real-key" not in str(error.value)


def test_manual_research_materials_remain_versioned_and_require_full_coverage(client):
    project = _project(client)
    _configure_models(client)
    brief = _brief(client, project["id"])
    created = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"], "searchProvider": "deterministic", "fetchProvider": "deterministic", "runImmediately": False,
    })
    assert created.status_code == 201
    stopped = client.post(f"/api/v1/research/jobs/{created.json()['id']}/cancel", json={"expectedRevision": created.json()["revision"]})
    assert stopped.status_code == 200
    job = stopped.json()
    perspectives = ["platform_trends", "genre_leaders", "reader_praise", "reader_dropoff", "opening_strategy", "serial_engine"]
    for perspective in perspectives:
        material = client.post(f"/api/v1/research/jobs/{job['id']}/manual-materials", json={
            "expectedRevision": job["revision"], "perspective": perspective, "title": f"Manual {perspective}",
            "content": (f"User supplied research for {perspective}. " * 8),
        })
        assert material.status_code == 200, material.text
        job = material.json()
    queries = client.get(f"/api/v1/research/jobs/{job['id']}/queries").json()
    assert {item["perspective"] for item in queries} == set(perspectives)
    assert all(item["resultCount"] == 1 for item in queries)
    analyzed = client.post(f"/api/v1/research/jobs/{job['id']}/analyze-manual-materials", json={"expectedRevision": job["revision"]})
    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()["status"] == "awaiting_review"
    assert analyzed.json()["coverage"]["manualCoverageMet"] is True
    sources = client.get(f"/api/v1/research/jobs/{job['id']}/sources").json()
    assert len(sources) == 6
    assert all(item["sourceType"] == "manual" and item["providerMetadata"]["origin"] == "manual" for item in sources)


def test_single_integrated_manual_report_can_reach_human_research_review(client):
    project = _project(client)
    _configure_models(client)
    brief = _brief(client, project["id"])
    created = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"], "searchProvider": "deterministic", "fetchProvider": "deterministic", "runImmediately": False,
    }).json()
    stopped = client.post(f"/api/v1/research/jobs/{created['id']}/cancel", json={"expectedRevision": created["revision"]}).json()
    report = client.post(f"/api/v1/research/jobs/{stopped['id']}/manual-materials", json={
        "expectedRevision": stopped["revision"], "title": "External reader and competitor research",
        "content": "Female readers prefer a proactive protagonist, a concrete opening crisis, and escalating relationship stakes. " * 5,
    })
    assert report.status_code == 200, report.text
    query = client.get(f"/api/v1/research/jobs/{stopped['id']}/queries").json()
    assert query[-1]["perspective"] == "integrated_report"
    analyzed = client.post(f"/api/v1/research/jobs/{stopped['id']}/analyze-manual-materials", json={"expectedRevision": report.json()["revision"]})
    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()["status"] == "awaiting_review"
    assert analyzed.json()["coverage"]["integratedManualReportCoverageMet"] is True
    runs = client.get(f"/api/v1/projects/{project['id']}/model-runs").json()
    roles = {item["role"] for item in runs}
    assert "research_analyst:report" in roles
    assert "research_analyst:evidence" not in roles
    accepted = client.post(f"/api/v1/research/jobs/{stopped['id']}/accept", json={"expectedRevision": analyzed.json()["revision"]})
    assert accepted.status_code == 200, accepted.text


def test_story_opportunities_use_a_compact_model_snapshot(client, monkeypatch):
    project = _project(client)
    _configure_models(client)
    brief = _brief(client, project["id"])
    created = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"], "searchProvider": "deterministic", "fetchProvider": "deterministic", "runImmediately": False,
    }).json()
    stopped = client.post(f"/api/v1/research/jobs/{created['id']}/cancel", json={"expectedRevision": created["revision"]}).json()
    report = client.post(f"/api/v1/research/jobs/{stopped['id']}/manual-materials", json={
        "expectedRevision": stopped["revision"], "title": "Compact opportunity report",
        "content": "Readers respond to proactive choices, a concrete opening crisis, and escalating stakes. " * 20,
    }).json()
    analyzed = client.post(f"/api/v1/research/jobs/{stopped['id']}/analyze-manual-materials", json={"expectedRevision": report["revision"]}).json()
    accepted = client.post(f"/api/v1/research/jobs/{stopped['id']}/accept", json={"expectedRevision": analyzed["revision"]}).json()

    phase13 = client.app.state.story_service.phase13
    original = phase13._complete_model_json
    calls = []

    def capture(*args, **kwargs):
        calls.append({"role": args[2], "payload": args[5], "kwargs": kwargs})
        return original(*args, **kwargs)

    monkeypatch.setattr(phase13, "_complete_model_json", capture)
    external_input = "Keep the moral dilemma and the sibling relationship, but avoid a chosen-one destiny."
    response = client.post(f"/api/v1/research/jobs/{stopped['id']}/opportunities", json={"expectedJobRevision": accepted["revision"], "creativeInput": external_input})

    assert response.status_code == 201, response.text
    assert response.json()[0]["story"]["title"] == "Direction 1"
    assert response.json()[0]["story"]["summary"] == "A concise overview for direction 1."
    assert response.json()[0]["story"]["externalCreativeInputChecksum"]
    assert external_input not in json.dumps(response.json())
    opportunity_calls = [item for item in calls if item["role"].startswith("story_incubator:opportunities")]
    assert len(opportunity_calls) == 3
    assert [item["payload"]["candidateIndex"] for item in opportunity_calls] == [1, 2, 3]
    assert all(item["kwargs"] == {"max_output_tokens": 1600, "max_retries": 0, "stream_response": True} for item in opportunity_calls)
    assert opportunity_calls[0]["payload"]["previousDirections"] == []
    assert opportunity_calls[2]["payload"]["previousDirections"] == ["Direction 1", "Direction 2"]
    evidence = opportunity_calls[0]["payload"]["report"]["evidence"]
    assert evidence and set(evidence[0]) == {"id", "claimType", "claim", "confidence"}
    assert opportunity_calls[0]["payload"]["externalCreativeInput"] == external_input
    assert all("excerpt" not in str(item["payload"]) for item in opportunity_calls)

    replacement = client.post(f"/api/v1/research/jobs/{stopped['id']}/opportunities", json={
        "expectedJobRevision": accepted["revision"], "creativeInput": "Keep the family conflict, but rebuild the central mystery around public records.",
    })
    assert replacement.status_code == 201, replacement.text
    all_opportunities = client.get(f"/api/v1/projects/{project['id']}/story-opportunities?jobId={stopped['id']}").json()
    assert len([item for item in all_opportunities if item["status"] == "pending"]) == 3
    assert len([item for item in all_opportunities if item["status"] == "superseded"]) == 3


def test_story_opportunity_response_accepts_one_card_equivalent_envelopes(client):
    phase13 = client.app.state.story_service.phase13
    card = {"highConcept": "A bounded premise", "scoreComponents": {}, "evidenceIds": []}

    assert phase13._single_generated_opportunity({"opportunities": [card]}) == card
    assert phase13._single_generated_opportunity({"opportunities": card}) == card
    assert phase13._single_generated_opportunity({"opportunity": card}) == card
    assert phase13._single_generated_opportunity({"storyOpportunity": card}) == card
    assert phase13._single_generated_opportunity(card) == card
    assert phase13._single_generated_opportunity({"opportunities": [card, card]}) is None


def test_story_opportunity_repairs_one_incomplete_model_card(client, monkeypatch):
    project = _project(client)
    _configure_models(client)
    brief = _brief(client, project["id"])
    created = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"], "searchProvider": "deterministic", "fetchProvider": "deterministic", "runImmediately": False,
    }).json()
    stopped = client.post(f"/api/v1/research/jobs/{created['id']}/cancel", json={"expectedRevision": created["revision"]}).json()
    report = client.post(f"/api/v1/research/jobs/{stopped['id']}/manual-materials", json={
        "expectedRevision": stopped["revision"], "title": "Repair report", "content": "Readers need a choice with a visible cost. " * 20,
    }).json()
    analyzed = client.post(f"/api/v1/research/jobs/{stopped['id']}/analyze-manual-materials", json={"expectedRevision": report["revision"]}).json()
    accepted = client.post(f"/api/v1/research/jobs/{stopped['id']}/accept", json={"expectedRevision": analyzed["revision"]}).json()

    phase13 = client.app.state.story_service.phase13
    original = phase13._complete_model_json
    returned_incomplete = False

    def incomplete_once(*args, **kwargs):
        nonlocal returned_incomplete
        if args[2] == "story_incubator:opportunities" and not returned_incomplete:
            returned_incomplete = True
            return {"opportunity": {"highConcept": "Incomplete"}}, "synthetic-invalid-run"
        return original(*args, **kwargs)

    monkeypatch.setattr(phase13, "_complete_model_json", incomplete_once)
    response = client.post(f"/api/v1/research/jobs/{stopped['id']}/opportunities", json={"expectedJobRevision": accepted["revision"]})

    assert response.status_code == 201, response.text
    assert len(response.json()) == 3
    roles = {item["role"] for item in client.get(f"/api/v1/projects/{project['id']}/model-runs").json()}
    assert "story_incubator:opportunities:1:repair" in roles


def test_phase14_deterministic_canon_and_opening_gates(client):
    phase13 = client.app.state.story_service.phase13
    incomplete = phase13._generic_canon_checks(
        "# Story Core\nConflict: a cost\n## Boundaries",
        {"entities": [], "relations": [], "rules": [], "_generationCrossCheck": {"ready": True}},
        {"protagonist": "Ming"},
    )
    assert incomplete["ready"] is False
    assert {item["code"] for item in incomplete["checks"] if item["status"] == "blocked"} >= {"CANON_GENERIC_ENTITIES", "CANON_GENERIC_RULES", "CANON_GENERIC_PROTAGONIST"}

    valid_structure = {
        "entities": [{"canonicalName": "林知遥", "entityTypeName": "person", "attributesJson": {}}],
        "relations": [],
        "rules": [{"ruleCode": "CITY-01", "statement": "入夜后必须沿灯行走。", "constraintJson": {}}],
        "_generationCrossCheck": {"ready": True},
    }
    generic_fog_city = phase13._generic_canon_checks(
        "# 故事内核\n林知遥调查雾城失踪案。\n## 核心冲突\n真相与家人冲突。\n## 创作边界\n禁止无代价破局。",
        valid_structure,
        {"protagonist": "林知遥"},
    )
    assert generic_fog_city["ready"] is True
    leaked_seed = phase13._generic_canon_checks(
        "# 故事内核\n林知遥在夜巡司遇见沈砚。\n## 核心冲突\n调查冲突。\n## 创作边界\n禁止无代价破局。",
        valid_structure,
        {"protagonist": "林知遥"},
    )
    assert next(item for item in leaked_seed["checks"] if item["code"] == "CANON_GENERIC_NO_NIGHT_WATCH")["status"] == "blocked"

    with pytest.raises(StoryError) as short:
        phase13._validate_opening_content("too short", {"chapterWordRange": {"min": 100, "max": 200}})
    assert short.value.code == "OPENING_WORD_RANGE_INVALID"

    with pytest.raises(StoryError) as review:
        phase13._validate_opening_review({"scores": {"continueReading": 90}, "findings": []}, "content")
    assert review.value.code == "OPENING_REVIEW_MODEL_INVALID"


def test_research_credentials_are_write_only_and_can_be_rotated_for_a_queued_job(client):
    project = _project(client)
    brief = _brief(client, project["id"])
    payload = {
        "expectedBriefRevision": brief["revision"],
        "idempotencyKey": f"research:{brief['checksum']}",
        "searchProvider": "tavily",
        "fetchProvider": "firecrawl",
        "searchApiKey": "tavily-secret-one",
        "fetchApiKey": "firecrawl-secret-one",
        "runImmediately": False,
    }
    created = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["providerConfig"] == {
        "searchProvider": "tavily",
        "fetchProvider": "firecrawl",
        "searchSecretConfigured": True,
        "fetchSecretConfigured": True,
    }
    assert "tavily-secret-one" not in created.text
    assert "firecrawl-secret-one" not in created.text

    rotated = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        **payload,
        "searchApiKey": "tavily-secret-two",
        "fetchApiKey": "firecrawl-secret-two",
    })
    assert rotated.status_code == 201, rotated.text
    assert rotated.json()["id"] == created.json()["id"]
    secret_store = client.app.state.story_service.secret_store
    assert secret_store.get_secret(f"research-provider:{project['id']}:tavily") == "tavily-secret-two"
    assert secret_store.get_secret(f"research-provider:{project['id']}:firecrawl") == "firecrawl-secret-two"
    assert "secret-two" not in rotated.text


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


def test_missing_provider_secret_is_persisted_and_competitor_exclusion_keeps_old_report(client):
    project = _project(client)
    brief = _brief(client, project["id"])
    missing_secret = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"],
    })
    assert missing_secret.status_code == 201, missing_secret.text
    assert missing_secret.json()["status"] == "failed"
    assert missing_secret.json()["errorCode"] == "SEARCH_API_KEY_MISSING"

    _configure_research(client)
    job = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"], "searchProvider": "deterministic", "fetchProvider": "deterministic",
    }).json()
    before = client.get(f"/api/v1/research/jobs/{job['id']}/competitors").json()
    assert before
    excluded = client.post(f"/api/v1/competitors/{before[0]['id']}/exclude", json={
        "expectedRevision": before[0]["revision"], "expectedJobRevision": job["revision"], "reason": "not comparable",
    })
    assert excluded.status_code == 200, excluded.text
    assert excluded.json()["reportRevision"] == before[0]["reportRevision"] + 1
    after = client.get(f"/api/v1/research/jobs/{job['id']}/competitors").json()
    historical = [item for item in after if item["reportRevision"] == before[0]["reportRevision"]]
    assert historical and historical[0]["excluded"] is False
    findings = client.get(f"/api/v1/research/jobs/{job['id']}/findings").json()
    assert {item["reportRevision"] for item in findings} == {before[0]["reportRevision"], excluded.json()["reportRevision"]}


def test_research_brief_drift_and_domain_scope_cannot_leak_into_a_job(client):
    project = _project(client)
    _configure_models(client)
    service = client.app.state.story_service
    query = "undecided urban mystery adult readers platform trends"
    allowed = "https://allowed.example.test/trends"
    excluded = "https://blocked.example.test/trends"
    service.phase13.search_provider = DeterministicSearchProvider({query: [
        SearchResult(url=allowed, title="allowed", domain="allowed.example.test"),
        SearchResult(url=excluded, title="blocked", domain="blocked.example.test"),
    ]})
    service.phase13.fetch_provider = DeterministicContentFetchProvider({
        allowed: FetchResponse(requested_url=allowed, final_url=allowed, title="allowed", content="usable evidence" * 50),
    })
    brief_response = client.post(f"/api/v1/projects/{project['id']}/research/briefs", json={
        "expectedRevision": 0, "format": "long-form", "platform": "undecided", "genre": "urban mystery", "audience": "adult readers",
        "emotionalValue": ["tension"], "includedDomains": ["example.test"], "excludedDomains": ["blocked.example.test"],
    })
    brief = brief_response.json()
    job = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"], "searchProvider": "deterministic", "fetchProvider": "deterministic", "runImmediately": False,
    }).json()
    updated = _brief(client, project["id"], expected_revision=brief["revision"], includedDomains=["example.test"], excludedDomains=["blocked.example.test"])
    assert updated["revision"] == brief["revision"] + 1
    drifted = client.post(f"/api/v1/research/jobs/{job['id']}/run", json={"expectedRevision": job["revision"]})
    assert drifted.status_code == 200, drifted.text
    assert drifted.json()["status"] == "failed"
    assert drifted.json()["errorCode"] == "RESEARCH_BRIEF_DRIFT"

    # A fresh scoped brief runs normally, but the excluded result never enters
    # persistent research sources even if the search provider returns it.
    fresh = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": updated["revision"], "searchProvider": "deterministic", "fetchProvider": "deterministic",
        "limits": {"minimumSourceTypes": 1},
    })
    assert fresh.status_code == 201, fresh.text
    sources = client.get(f"/api/v1/research/jobs/{fresh.json()['id']}/sources").json()
    assert [source["canonicalUrl"] for source in sources] == [allowed]


def test_direct_public_http_fetch_is_not_an_available_research_provider(client):
    project = _project(client)
    brief = _brief(client, project["id"])
    response = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"], "searchProvider": "deterministic", "fetchProvider": "public-http",
    })
    assert response.status_code == 422


def test_research_cost_limit_stops_the_job_before_results_are_persisted(client):
    class CostlySearch:
        name = "costly-search"

        def __init__(self):
            self.calls = 0

        def search(self, _query, _domains, _date_range, _limit):
            self.calls += 1
            return SearchResponse(results=[], estimated_cost=1.0)

    project = _project(client)
    _configure_models(client)
    brief = _brief(client, project["id"])
    costly = CostlySearch()
    client.app.state.story_service.phase13.search_provider = costly
    job = client.post(f"/api/v1/projects/{project['id']}/research/jobs", json={
        "expectedBriefRevision": brief["revision"],
        "searchProvider": "deterministic",
        "fetchProvider": "deterministic",
        "limits": {"maxCost": 0},
    })
    assert job.status_code == 201, job.text
    assert job.json()["status"] == "failed"
    assert job.json()["errorCode"] == "RESEARCH_COST_LIMIT"
    assert costly.calls == 0
    assert client.get(f"/api/v1/research/jobs/{job.json()['id']}/sources").json() == []

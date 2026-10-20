from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import fixture_text

client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ats_weights_endpoint():
    weights = client.get("/api/ats/weights").json()
    assert weights["required_keywords"] == 0.4
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_cors_allows_frontend_origin():
    res = client.options(
        "/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_parse_resume_upload(analyst_pdf):
    res = client.post("/api/resume/parse",
                      files={"file": ("resume.pdf", analyst_pdf, "application/pdf")})
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Ravi Menon"
    assert body["sections"][0]["entries"][0]["bullets"][0]["id"] == "exp1.b1"


def test_parse_resume_unsupported_type():
    res = client.post("/api/resume/parse", files={"file": ("resume.pages", b"x", "text/plain")})
    assert res.status_code == 415


def test_parse_resume_scanned_pdf(blank_pdf):
    res = client.post("/api/resume/parse",
                      files={"file": ("scan.pdf", blank_pdf, "application/pdf")})
    assert res.status_code == 422
    assert "scanned" in res.json()["detail"]


def test_parse_resume_too_large():
    res = client.post("/api/resume/parse",
                      files={"file": ("big.txt", b"a" * (5 * 1024 * 1024 + 10), "text/plain")})
    assert res.status_code == 413


def test_parse_jd():
    res = client.post("/api/jd/parse", json={"text": fixture_text("jd_senior_analyst.txt")})
    assert res.status_code == 200
    assert res.json()["title"] == "Senior Data Analyst"


def test_parse_jd_rejects_tiny_input():
    assert client.post("/api/jd/parse", json={"text": "hi"}).status_code == 422


def _gap_body(use_llm=False):
    resume = client.post("/api/resume/parse", files={
        "file": ("r.txt", fixture_text("resume_analyst.txt").encode(), "text/plain")}).json()
    jd = client.post("/api/jd/parse", json={"text": fixture_text("jd_senior_analyst.txt")}).json()
    return {"resume": resume, "jd": jd, "use_llm": use_llm}


def test_gap_analyze_rules_only():
    res = client.post("/api/gap/analyze", json=_gap_body())
    assert res.status_code == 200
    body = res.json()
    assert body["notes"] == ["Rules only."]
    assert body["counts"]["missing"] == 3
    assert body["items"][0]["status"] == "evidenced"


def test_gap_analyze_without_api_key_degrades(monkeypatch):
    import app.api.routes as routes

    monkeypatch.setattr(routes, "get_llm", lambda: None)
    body = client.post("/api/gap/analyze", json=_gap_body(use_llm=True)).json()
    assert body["notes"] == ["Rules only (no ANTHROPIC_API_KEY set)."]


def test_gap_answers_roundtrip():
    analysis = client.post("/api/gap/analyze", json=_gap_body()).json()
    qid = next(i["question"]["id"] for i in analysis["items"]
               if i["status"] == "missing")
    res = client.post("/api/gap/answers",
                      json={"analysis": analysis, "answers": {qid: "No, not yet."}})
    assert res.status_code == 200
    answered = next(i for i in res.json()["items"]
                    if i["question"] and i["question"]["id"] == qid)
    assert answered["question"]["answer_kind"] == "declined"


def test_gap_answers_unknown_question():
    analysis = client.post("/api/gap/analyze", json=_gap_body()).json()
    res = client.post("/api/gap/answers", json={"analysis": analysis, "answers": {"q99": "x"}})
    assert res.status_code == 422


def test_tailor_rules_only():
    body = _gap_body()
    body["analysis"] = client.post("/api/gap/analyze", json=_gap_body()).json()
    res = client.post("/api/tailor", json=body)
    assert res.status_code == 200
    out = res.json()
    assert out["bullets"][0]["id"] == "t1"
    assert all(b["verification"]["passed"] for b in out["bullets"])


def test_verify_recomputes_and_ignores_client_verdict():
    body = _gap_body()
    forged = {"id": "t1", "text": "Led a churn dashboard in Tableau with Python",
              "source_bullet_ids": ["exp1.b1"], "change_type": "reword",
              "verification": {"flags": [], "passed": True}}
    res = client.post("/api/verify", json={"resume": body["resume"], "bullets": [forged],
                                           "summary": "Senior analyst."})
    out = res.json()
    v = out["bullets"][0]["verification"]
    assert v["passed"] is False
    assert {"inflated_verb", "new_tool"} <= {f["kind"] for f in v["flags"]}
    assert out["summary_verification"]["passed"] is False


def test_ats_score_before_after():
    body = _gap_body()
    analysis = client.post("/api/gap/analyze", json=body).json()
    tailored = client.post("/api/tailor", json={**body, "analysis": analysis}).json()
    res = client.post("/api/ats/score", json={**body, "tailored": tailored,
                                              "analysis": analysis})
    assert res.status_code == 200
    out = res.json()
    assert len(out["before"]["components"]) == 6 and "disclaimer" in out["before"]
    assert out["after"] is not None and isinstance(out["delta"], float)


def test_ats_score_ignores_forged_verification():
    body = _gap_body()
    forged = {"bullets": [{
        "id": "t1", "text": "Built Snowflake pipelines in Python and dbt",
        "source_bullet_ids": ["exp1.b1"], "entry_id": "exp1", "change_type": "reword",
        "verification": {"flags": []}, "review": "approved"}]}
    out = client.post("/api/ats/score", json={**body, "tailored": forged}).json()
    pref = next(c for c in out["after"]["components"] if c["name"] == "preferred_keywords")
    assert "dbt / airflow" in pref["missing"] and "snowflake / bigquery" in pref["missing"]
    assert out["delta"] == 0.0


def test_ats_synonyms_endpoint():
    syn = client.get("/api/ats/synonyms").json()
    assert "k8s" in syn["kubernetes"]


def test_mentor_endpoint():
    body = _gap_body()
    res = client.post("/api/mentor", json=body)
    assert res.status_code == 200
    out = res.json()
    assert out["verdict"]["decision"] == "apply"
    assert len(out["plan"]["weeks"]) == 2
    assert out["actions"][0]["id"] == "a1"

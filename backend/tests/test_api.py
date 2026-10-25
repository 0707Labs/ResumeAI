from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import fixture_text

client = TestClient(app)


def test_health_checks_the_database(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": "ok", "llm_configured": False}


def test_health_is_503_when_the_database_is_unreachable(api_app, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db.session import get_db

    monkeypatch.setattr("app.api.routes.HEALTH_DB_TIMEOUT_S", 1.0)
    dead = async_sessionmaker(create_async_engine("postgresql+psycopg://nobody@127.0.0.1:1/none", poolclass=NullPool))

    async def unreachable_db():
        async with dead() as s:
            yield s

    api_app.dependency_overrides[get_db] = unreachable_db
    with TestClient(api_app) as down:
        res = down.get("/health")
    assert res.status_code == 503
    assert res.json() == {"status": "unavailable", "database": "unreachable", "llm_configured": False}


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


def test_gap_answers_with_explicit_choices():
    analysis = client.post("/api/gap/analyze", json=_gap_body()).json()
    qids = [i["question"]["id"] for i in analysis["items"] if i["question"]]
    res = client.post("/api/gap/answers", json={"analysis": analysis, "answers": {
        qids[0]: {"choice": "yes", "text": "Not at work, but I ran t-tests in a side project."},
        qids[1]: {"choice": "no"},
        qids[2]: {"choice": "skip"},
    }})
    assert res.status_code == 200
    kinds = {i["question"]["id"]: i["question"]["answer_kind"] for i in res.json()["items"]
             if i["question"]}
    assert (kinds[qids[0]], kinds[qids[1]], kinds[qids[2]]) == ("confirmed", "declined",
                                                                 "unanswered")


def test_gap_answers_rejects_empty_yes():
    analysis = client.post("/api/gap/analyze", json=_gap_body()).json()
    qid = next(i["question"]["id"] for i in analysis["items"] if i["question"])
    res = client.post("/api/gap/answers", json={"analysis": analysis,
                                                "answers": {qid: {"choice": "yes", "text": ""}}})
    assert res.status_code == 422 and "describe" in res.json()["detail"]


def test_ats_score_approved_only_counts_just_approved_bullets():
    from app.parsing import parse_jd, parse_resume_text
    from app.tailoring import tailor
    from tests.test_tailor import JD, ScriptedLLM, b
    from tests.test_verifier import RESUME

    resume, jd = parse_resume_text(RESUME), parse_jd(JD)
    analysis = client.post("/api/gap/analyze", json={
        "resume": resume.model_dump(mode="json"), "jd": jd.model_dump(mode="json"),
        "use_llm": False}).json()
    qid = next(i["question"]["id"] for i in analysis["items"]
               if i["question"] and "airflow" in i["missing_keywords"])
    analysis = client.post("/api/gap/answers", json={"analysis": analysis, "answers": {
        qid: {"choice": "yes", "text": "I wrote the Airflow DAGs for our SQL extracts at Acme."}}}).json()
    from app.models import GapAnalysis
    tailored = tailor(resume, jd, GapAnalysis.model_validate(analysis), llm=ScriptedLLM({"bullets": [
        b(["exp1.b2"], "Cut weekly reporting time by 30% by automating SQL extracts as Airflow DAGs",
          answers=[qid])]})).model_dump(mode="json")
    body = {"resume": resume.model_dump(mode="json"), "jd": jd.model_dump(mode="json"),
            "tailored": tailored, "analysis": analysis, "use_llm": False}

    pending = client.post("/api/ats/score", json={**body, "approved_only": True}).json()
    assert pending["delta"] == 0.0  # nothing approved yet
    preview = client.post("/api/ats/score", json=body).json()
    assert preview["delta"] > 0
    for bl in tailored["bullets"]:
        if "Airflow" in bl["text"]:
            bl["review"] = "approved"
    approved = client.post("/api/ats/score", json={**body, "approved_only": True}).json()
    assert approved["delta"] == preview["delta"]

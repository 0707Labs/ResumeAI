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

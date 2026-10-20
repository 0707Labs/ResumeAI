from fastapi.testclient import TestClient

from app.main import app

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

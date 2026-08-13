import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def demo_session(client: TestClient) -> dict:
    """Create a demo analysis session — shared setup for API regression flows."""
    res = client.post("/api/v1/analyze", json={"repo_url": None, "demo_mode": True})
    assert res.status_code == 200, res.text
    body = res.json()
    return {"session_id": body["session_id"], "stack": body["stack"]}

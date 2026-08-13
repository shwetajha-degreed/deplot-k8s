"""API regression suite — mirrors the demo wizard backend contract."""

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["app"] == "Deplot AI"
    assert "zerops" in body
    assert "deploy_project_configured" in body["zerops"]


def test_deploy_project_config(client: TestClient) -> None:
    from app.config import get_settings

    settings = get_settings()
    assert hasattr(settings, "zerops_target_project_id")
    assert settings.zerops_target_project_id == (
        settings.zerops_deploy_project_id or settings.zerops_project_id
    )


def test_dashboard_summary(client: TestClient) -> None:
    res = client.get("/api/v1/dashboard/summary")
    assert res.status_code == 200
    body = res.json()
    assert "connected_repos" in body
    assert "deployment_readiness_score" in body
    # Empty stores must not invent acme/demo baseline KPIs
    assert body.get("is_demo_baseline") is False
    assert body["connected_repos"] == 0
    assert body["total_deployments"] == 0
    assert body["live_apps"] == []


def test_demo_analyze_session(client: TestClient) -> None:
    res = client.post("/api/v1/analyze", json={"repo_url": None, "demo_mode": True})
    assert res.status_code == 200
    body = res.json()
    assert body["stack"]["framework"] == "nextjs"
    assert body["stack"]["database"] == "postgresql"
    assert body["stack"]["search"] == "typesense"


def test_architecture_and_plan(client: TestClient, demo_session: dict) -> None:
    session_id = demo_session["session_id"]

    arch = client.post("/api/v1/architecture", json={"session_id": session_id})
    assert arch.status_code == 200
    graph = arch.json()
    node_ids = {n["id"] for n in graph["nodes"]}
    assert "frontend" in node_ids
    assert "database" in node_ids
    assert "search" in node_ids
    assert "cache" in node_ids
    api_node = next(n for n in graph["nodes"] if n["id"] == "api")
    assert api_node.get("hostname") == "demo-api"
    assert next(n for n in graph["nodes"] if n["id"] == "frontend").get("hostname") == "demo-web"

    plan = client.get(f"/api/v1/sessions/{session_id}/plan")
    assert plan.status_code == 200
    plan_body = plan.json()
    assert plan_body["estimated_cost_usd_month"] > 0
    assert len(plan_body["services"]) >= 4


def test_fullstack_import_yaml(client: TestClient, demo_session: dict) -> None:
    session_id = demo_session["session_id"]
    yaml_res = client.post("/api/v1/generate-yaml", json={"session_id": session_id})
    assert yaml_res.status_code == 200
    config = yaml_res.json()
    import_yaml = config["import_yaml"]
    for suffix in ("-postgres", "-cache", "-search", "-api", "-web"):
        assert suffix in import_yaml
    assert "valkey@7" in import_yaml
    assert "typesense@30" in import_yaml
    assert "postgresql@16" in import_yaml


def test_yaml_validate_and_deploy(client: TestClient, demo_session: dict) -> None:
    session_id = demo_session["session_id"]

    yaml_res = client.post("/api/v1/generate-yaml", json={"session_id": session_id})
    assert yaml_res.status_code == 200

    validation = client.post("/api/v1/validate", json={"session_id": session_id})
    assert validation.status_code == 200
    report = validation.json()
    assert report["passed"] is True

    deploy = client.post("/api/v1/deploy", json={"session_id": session_id, "demo_mode": True})
    assert deploy.status_code == 200
    deployment_id = deploy.json()["deployment_id"]

    status = client.get(f"/api/v1/deployment/{deployment_id}/status")
    assert status.status_code == 200

    obs = client.get(f"/api/v1/deployment/{deployment_id}/observability")
    assert obs.status_code == 200
    snap = obs.json()
    assert snap["log_summary"]
    assert len(snap["metrics"]) >= 4
    assert snap.get("checked_at") is not None
    api_health = next(h for h in snap["health"] if h["service"] == "api")
    assert api_health.get("hostname") == "demo-api"
    assert api_health.get("status") in ("critical", "degraded", "healthy", "unknown")


def test_aiops_remediate_and_score(client: TestClient, demo_session: dict) -> None:
    session_id = demo_session["session_id"]
    deploy = client.post("/api/v1/deploy", json={"session_id": session_id, "demo_mode": True})
    deployment_id = deploy.json()["deployment_id"]
    incident_id = client.get(f"/api/v1/deployment/{deployment_id}/incidents").json()[0]["id"]

    score_before = client.get(f"/api/v1/deployment/{deployment_id}/score")
    assert score_before.status_code == 200
    before = score_before.json()
    assert "overall" in before
    assert before["reliability"] < 9.0
    assert len(before.get("recommendations", [])) >= 1

    remediate = client.post(f"/api/v1/incidents/{incident_id}/remediate")
    assert remediate.status_code == 200
    body = remediate.json()
    assert body["status"] == "resolved"
    assert len(body.get("remediation_steps", [])) >= 3
    assert body.get("remediation_error") is None

    score_after = client.get(f"/api/v1/deployment/{deployment_id}/score")
    assert score_after.status_code == 200
    after = score_after.json()
    assert after["reliability"] > before["reliability"]
    assert after["overall"] >= before["overall"]


def test_zerops_env_patch_yaml() -> None:
    from app.config import get_settings
    from app.services.zerops import ZeropsService

    svc = ZeropsService(get_settings())
    patch = svc.build_env_patch_yaml(
        "demo-api",
        {"DATABASE_URL": "postgresql://${demo-postgres_hostname}/deplot"},
    )
    assert "hostname: demo-api" in patch
    assert "envSecrets:" in patch
    assert "DATABASE_URL" in patch


def test_ops_timeline_on_deploy(client: TestClient, demo_session: dict) -> None:
    session_id = demo_session["session_id"]
    deploy = client.post("/api/v1/deploy", json={"session_id": session_id, "demo_mode": True})
    deployment_id = deploy.json()["deployment_id"]

    timeline = client.get(f"/api/v1/deployment/{deployment_id}/timeline")
    assert timeline.status_code == 200
    events = timeline.json()["events"]
    assert len(events) >= 2
    types = {e["event_type"] for e in events}
    assert "started" in types
    assert "incident" in types


def test_deployment_stream_endpoint(client: TestClient, demo_session: dict) -> None:
    session_id = demo_session["session_id"]
    deploy = client.post("/api/v1/deploy", json={"session_id": session_id, "demo_mode": True})
    deployment_id = deploy.json()["deployment_id"]

    with client.stream("GET", f"/api/v1/deployment/{deployment_id}/stream") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        chunk = next(resp.iter_bytes(), b"")
        assert b"event:" in chunk

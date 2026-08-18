def test_saas_key_required_for_session_token(client):
    denied = client.post("/api/internal/session-token")
    assert denied.status_code == 401
    missing_workspace = client.post("/api/internal/session-token", headers={"X-SaaS-Key": "test-saas-key"})
    assert missing_workspace.status_code == 400
    ok = client.post(
        "/api/internal/session-token",
        headers={"X-SaaS-Key": "test-saas-key", "X-Workspace-Id": "7"},
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]


def test_workspace_monitors_are_isolated(client):
    workspace_a = {"X-SaaS-Key": "test-saas-key", "X-Workspace-Id": "2"}
    workspace_b = {"X-SaaS-Key": "test-saas-key", "X-Workspace-Id": "3"}

    seeded = client.get("/api/monitor", headers=workspace_a)
    assert seeded.status_code == 200
    assert any(row["symbol"] == "EURUSD" and row["timeframe"] == "M5" for row in seeded.json())

    added = client.post(
        "/api/monitor",
        headers=workspace_b,
        json={"symbol": "AUDUSD", "timeframe": "M15", "enabled": True},
    )
    assert added.status_code == 200, added.text
    assert added.json()["workspace_id"] == 3

    names_b = {(row["symbol"], row["timeframe"]) for row in client.get("/api/monitor", headers=workspace_b).json()}
    names_a = {(row["symbol"], row["timeframe"]) for row in client.get("/api/monitor", headers=workspace_a).json()}
    assert ("AUDUSD", "M15") in names_b
    assert ("AUDUSD", "M15") not in names_a

from datetime import UTC, datetime, timedelta

from app.mt5.base import CandleRecord
from app.services.candles import upsert_candles


def test_health_and_login(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert "disclaimer" in health.json()
    denied = client.get("/api/symbols")
    assert denied.status_code == 401
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"username": "admin", "password": "test-password"})
    assert ok.status_code == 200
    assert ok.json()["access_token"]


def test_protected_endpoints(client, auth_headers, db_session):
    start = datetime(2024, 6, 1, tzinfo=UTC)
    records = []
    price = 1.08
    for i in range(120):
        price += 0.00005
        ts = start + timedelta(minutes=5 * i)
        records.append(
            CandleRecord(
                symbol="EURUSD",
                timeframe="M5",
                timestamp=ts,
                open=price,
                high=price + 0.0002,
                low=price - 0.0001,
                close=price,
                spread=0.00008,
                tick_volume=12,
            )
        )
    upsert_candles(db_session, records)

    candles = client.get("/api/candles", params={"symbol": "EURUSD", "timeframe": "M5"}, headers=auth_headers)
    assert candles.status_code == 200
    assert len(candles.json()) > 0

    quality = client.get("/api/data-quality", params={"symbol": "EURUSD", "timeframe": "M5"}, headers=auth_headers)
    assert quality.status_code == 200
    assert quality.json()["total_candles"] >= 120

    mt5 = client.get("/api/mt5/status", headers=auth_headers)
    assert mt5.status_code == 200
    assert "connected" in mt5.json()


def test_agent_ingest_requires_key(client):
    response = client.post("/api/agent/ingest", json={"candles": []})
    assert response.status_code == 401
    ok = client.post("/api/agent/ingest", json={"candles": []}, headers={"X-Agent-Key": "test-agent-key"})
    assert ok.status_code == 200

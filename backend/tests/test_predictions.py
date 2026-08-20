from datetime import UTC, datetime, timedelta

from app.core.tenant import SYSTEM_WORKSPACE_ID, set_workspace_id
from app.models.candle import MarketCandle
from app.models.prediction import ModelPrediction, ModelVersion
from app.services.predictions import research_pips, summarize_predictions


def _pred(**kwargs) -> ModelPrediction:
    defaults = dict(
        symbol="EURUSD",
        timeframe="M5",
        timestamp=datetime(2026, 8, 19, tzinfo=UTC),
        price=1.1000,
        probability_up=0.6,
        probability_down=0.4,
        prediction="UP",
        actual_outcome=1,
        exit_price=1.1005,
        correct=True,
        model_version="test",
    )
    defaults.update(kwargs)
    return ModelPrediction(**defaults)


def test_research_pips_follows_signal_direction():
    assert research_pips(_pred(prediction="UP", price=1.1000, exit_price=1.1005)) == 5
    assert research_pips(_pred(prediction="DOWN", price=1.1000, exit_price=1.1005)) == -5
    assert research_pips(_pred(prediction="DOWN", price=1.1000, exit_price=1.0997)) == 3
    assert research_pips(_pred(exit_price=None)) is None


def test_summarize_splits_profit_and_loss():
    rows = [
        _pred(prediction="UP", price=1.1000, exit_price=1.1008, correct=True),
        _pred(prediction="DOWN", price=1.1000, exit_price=1.1004, correct=False),
        _pred(prediction="UP", price=1.1000, exit_price=1.1000, correct=False),
        _pred(exit_price=None, actual_outcome=None, correct=None),
    ]
    summary = summarize_predictions(rows, cost_pips=1.0)
    assert summary["resolved"] == 3
    assert summary["pending"] == 1
    assert summary["profit"]["count"] == 1
    assert summary["profit"]["pips"] == 8
    assert summary["loss"]["count"] == 1
    assert summary["loss"]["pips"] == -4
    assert summary["scratch_count"] == 1
    assert summary["net_pips"] == 4
    assert summary["net_pips_after_cost"] == 1


def test_predictions_summary_endpoint(client, auth_headers, db_session):
    now = datetime.now(UTC)
    db_session.add(
        MarketCandle(
            symbol="EURUSD",
            timeframe="M5",
            timestamp=now,
            open=1.1,
            high=1.1,
            low=1.1,
            close=1.1,
        )
    )
    db_session.add_all(
        [
            _pred(timestamp=now - timedelta(minutes=5), price=1.1000, exit_price=1.1006, prediction="UP", correct=True),
            _pred(timestamp=now - timedelta(minutes=10), price=1.1000, exit_price=1.1003, prediction="DOWN", correct=False),
        ]
    )
    db_session.commit()

    response = client.get("/api/predictions/summary", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["profit"]["pips"] == 6
    assert body["loss"]["pips"] == -3
    assert body["market"]["candles"] >= 1

    ledger = client.get("/api/predictions", headers=auth_headers)
    assert ledger.status_code == 200
    pips = {row["pips"] for row in ledger.json()}
    assert 6 in pips
    assert -3 in pips


def _version(**kwargs) -> ModelVersion:
    defaults = dict(
        name="logistic_next_close",
        version="v1",
        algorithm="LogisticRegression",
        symbol="EURUSD",
        timeframe="M5",
        workspace_id=SYSTEM_WORKSPACE_ID,
        is_active=False,
        artifact_path="",
    )
    defaults.update(kwargs)
    return ModelVersion(**defaults)


def test_delete_model_promotes_sibling_and_clears_fk(client, auth_headers, db_session, tmp_path):
    set_workspace_id(SYSTEM_WORKSPACE_ID)
    artifact = tmp_path / "eurusd_m5.joblib"
    artifact.write_bytes(b"stub")
    old = _version(version="old", is_active=True, artifact_path=str(artifact))
    newer = _version(version="newer", is_active=False, artifact_path="")
    db_session.add_all([old, newer])
    db_session.commit()
    pred = _pred(model_version_id=old.id, model_version="old")
    db_session.add(pred)
    db_session.commit()

    gone = client.delete(f"/api/models/{old.id}", headers=auth_headers)
    assert gone.status_code == 200
    body = gone.json()
    assert body["promoted_id"] == newer.id
    assert body["artifact_removed"] is True
    assert not artifact.exists()

    db_session.refresh(newer)
    db_session.refresh(pred)
    assert newer.is_active is True
    assert pred.model_version_id is None
    leftover = client.delete(f"/api/models/{old.id}", headers=auth_headers)
    assert leftover.status_code == 404


def test_prune_inactive_keeps_active(client, auth_headers, db_session):
    set_workspace_id(SYSTEM_WORKSPACE_ID)
    active = _version(version="keep", is_active=True)
    stale = _version(version="drop", is_active=False)
    db_session.add_all([active, stale])
    db_session.commit()

    pruned = client.delete("/api/models/inactive", headers=auth_headers)
    assert pruned.status_code == 200
    assert pruned.json()["deleted"] == 1
    remaining = client.get("/api/models", headers=auth_headers).json()
    versions = {row["version"] for row in remaining}
    assert "keep" in versions
    assert "drop" not in versions

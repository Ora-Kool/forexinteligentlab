"""The collector polls every workspace's monitored pairs, deduplicated."""

from __future__ import annotations

from app.core.tenant import SYSTEM_WORKSPACE_ID
from app.models.instrument import MonitoredInstrument
from app.services.collector import monitored_pairs


def test_monitored_pairs_unions_workspaces_and_dedupes(db_session):
    db_session.query(MonitoredInstrument).delete()
    db_session.add_all(
        [
            MonitoredInstrument(workspace_id=SYSTEM_WORKSPACE_ID, symbol="EURUSD", timeframe="M5", enabled=True),
            MonitoredInstrument(workspace_id=1, symbol="EURUSD", timeframe="M5", enabled=True),
            # Only a tenant watches H1 — this is what used to read "idle".
            MonitoredInstrument(workspace_id=1, symbol="EURUSD", timeframe="H1", enabled=True),
            MonitoredInstrument(workspace_id=2, symbol="GBPUSD", timeframe="M5", enabled=False),
        ]
    )
    db_session.commit()

    pairs = {(symbol, timeframe): ids for symbol, timeframe, ids in monitored_pairs(db_session)}

    assert pairs[("EURUSD", "M5")] == [SYSTEM_WORKSPACE_ID, 1]
    assert pairs[("EURUSD", "H1")] == [1]
    assert ("GBPUSD", "M5") not in pairs

    db_session.query(MonitoredInstrument).delete()
    db_session.commit()

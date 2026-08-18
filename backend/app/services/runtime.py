from __future__ import annotations

import threading
from datetime import UTC, datetime


class RuntimeState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.collector_running = False
        self.collector_thread: threading.Thread | None = None
        self.mt5_connected = False
        self.mt5_error = ""
        self.mt5_mode = "mock"
        self.database_ok = True
        self.database_error = ""
        self.last_data_at: datetime | None = None
        self.last_tick: dict[str, dict] = {}
        self.last_prediction: dict[str, dict] = {}
        self.stop_event = threading.Event()

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "collector": "RUNNING" if self.collector_running else "STOPPED",
                "mt5": "CONNECTED" if self.mt5_connected else "DISCONNECTED",
                "mt5_error": self.mt5_error,
                "mt5_mode": self.mt5_mode,
                "database": "CONNECTED" if self.database_ok else "ERROR",
                "database_error": self.database_error,
                "last_data": self.last_data_at.isoformat() if self.last_data_at else None,
                "as_of": datetime.now(UTC).isoformat(),
            }


runtime = RuntimeState()

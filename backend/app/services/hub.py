from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import WebSocket


def _json(value: Any) -> str:
    def default(item):
        if isinstance(item, datetime):
            return item.isoformat()
        return str(item)

    return json.dumps(value, default=default)


class Hub:
    def __init__(self) -> None:
        self.channels: dict[str, set[WebSocket]] = {
            "market": set(),
            "collector": set(),
            "predictions": set(),
        }
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.channels.setdefault(channel, set()).add(websocket)

    def disconnect(self, channel: str, websocket: WebSocket) -> None:
        self.channels.get(channel, set()).discard(websocket)

    async def broadcast(self, channel: str, payload: dict) -> None:
        dead = []
        message = _json(payload)
        for socket in list(self.channels.get(channel, set())):
            try:
                await socket.send_text(message)
            except Exception:
                dead.append(socket)
        for socket in dead:
            self.disconnect(channel, socket)

    def publish(self, channel: str, payload: dict) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(channel, payload), loop)


hub = Hub()

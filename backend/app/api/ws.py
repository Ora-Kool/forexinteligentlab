from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.services.hub import hub
from app.services.runtime import runtime

router = APIRouter()


async def _accept(websocket: WebSocket, channel: str) -> None:
    token = websocket.query_params.get("token")
    if not token or not decode_access_token(token):
        await websocket.close(code=4401)
        return
    await hub.connect(channel, websocket)
    try:
        await websocket.send_json({"type": "hello", "channel": channel, **runtime.snapshot()})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(channel, websocket)
    except Exception:
        hub.disconnect(channel, websocket)


@router.websocket("/ws/market")
async def ws_market(websocket: WebSocket):
    await _accept(websocket, "market")


@router.websocket("/ws/collector")
async def ws_collector(websocket: WebSocket):
    await _accept(websocket, "collector")


@router.websocket("/ws/predictions")
async def ws_predictions(websocket: WebSocket):
    await _accept(websocket, "predictions")

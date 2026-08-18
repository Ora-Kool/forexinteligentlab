from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import current_workspace_id
from app.models.alert import Alert
from app.models.event import SystemEvent

log = get_logger(__name__)


def _json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def record_event(db: Session, level: str, category: str, message: str, details: dict | None = None) -> SystemEvent:
    event = SystemEvent(level=level, category=category, message=message, details=_json_safe(details) if details else None)
    db.add(event)
    db.commit()
    db.refresh(event)
    log.info("system_event", level=level, category=category, message=message)
    return event


def raise_alert(
    db: Session,
    kind: str,
    message: str,
    symbol: str = "",
    timeframe: str = "",
    cooldown_seconds: int = 120,
) -> Alert | None:
    recent = (
        db.query(Alert)
        .filter(
            Alert.workspace_id == current_workspace_id(),
            Alert.kind == kind,
            Alert.symbol == symbol,
            Alert.timeframe == timeframe,
        )
        .order_by(Alert.created_at.desc())
        .first()
    )
    if recent and (datetime.now(UTC) - recent.created_at.replace(tzinfo=recent.created_at.tzinfo or UTC)).total_seconds() < cooldown_seconds:
        return None
    alert = Alert(kind=kind, message=message, symbol=symbol, timeframe=timeframe)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    record_event(db, "warning", "alert", message, {"kind": kind, "symbol": symbol, "timeframe": timeframe})
    return alert

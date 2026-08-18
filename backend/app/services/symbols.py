from sqlalchemy.orm import Session

from app.core.constants import DEFAULT_MONITOR, PREFERRED_BASES
from app.core.tenant import SYSTEM_WORKSPACE_ID, current_workspace_id
from app.models.instrument import MonitoredInstrument, Symbol
from app.mt5.base import MT5Connector, SymbolInfo


def persist_discovered(db: Session, infos: list[SymbolInfo]) -> list[Symbol]:
    stored = []
    for info in infos:
        row = db.query(Symbol).filter(Symbol.name == info.name).one_or_none()
        if row is None:
            row = Symbol(
                name=info.name,
                display_name=info.name,
                base_code=info.base_code or info.name,
                description=info.description,
                digits=info.digits,
                point=info.point,
                contract_size=info.contract_size,
                visible=info.visible,
            )
            db.add(row)
        else:
            row.description = info.description
            row.digits = info.digits
            row.point = info.point
            row.visible = info.visible
        stored.append(row)
    db.commit()
    return stored


def ensure_default_monitor(db: Session, connector: MT5Connector) -> list[MonitoredInstrument]:
    existing = db.query(MonitoredInstrument).filter(MonitoredInstrument.workspace_id == SYSTEM_WORKSPACE_ID).count()
    if existing:
        return db.query(MonitoredInstrument).filter(MonitoredInstrument.workspace_id == SYSTEM_WORKSPACE_ID).all()
    created = []
    for base, timeframe in DEFAULT_MONITOR:
        resolved = connector.resolve_symbol(base)
        name = resolved.name if resolved else base
        row = MonitoredInstrument(
            workspace_id=SYSTEM_WORKSPACE_ID,
            symbol=name,
            timeframe=timeframe,
            enabled=True,
        )
        db.add(row)
        created.append(row)
    db.commit()
    return created


def bootstrap_workspace_monitor(db: Session) -> list[MonitoredInstrument]:
    workspace_id = current_workspace_id()
    existing = db.query(MonitoredInstrument).filter(MonitoredInstrument.workspace_id == workspace_id).all()
    if existing:
        return existing
    templates = (
        db.query(MonitoredInstrument)
        .filter(MonitoredInstrument.workspace_id == SYSTEM_WORKSPACE_ID, MonitoredInstrument.enabled.is_(True))
        .all()
    )
    created = []
    for template in templates:
        row = MonitoredInstrument(
            workspace_id=workspace_id,
            symbol=template.symbol,
            timeframe=template.timeframe,
            enabled=True,
        )
        db.add(row)
        created.append(row)
    if created:
        db.commit()
    return created


def list_preferred_matches(symbols: list[Symbol]) -> list[Symbol]:
    preferred = []
    for base in PREFERRED_BASES:
        match = next((s for s in symbols if s.name.upper() == base), None)
        if match is None:
            match = next((s for s in symbols if s.base_code == base), None)
        if match:
            preferred.append(match)
    return preferred

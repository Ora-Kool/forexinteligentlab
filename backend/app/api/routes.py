from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import FEATURE_COLUMNS, RESEARCH_DISCLAIMER, TIMEFRAMES, pip_size_for, spread_pips
from app.core.security import create_access_token, verify_password
from app.core.tenant import SYSTEM_WORKSPACE_ID, current_workspace_id, own, research_ids, visible
from app.database.session import get_db
from app.ml.backtest import run_backtest
from app.ml.features import compute_feature_frame, session_name
from app.ml.train import train_logistic_regression
from app.models.alert import Alert
from app.models.candle import MarketCandle
from app.models.collection import CollectionJob, CollectionStatus
from app.models.event import SystemEvent
from app.models.feature import FeatureRow
from app.models.instrument import MonitoredInstrument, Symbol
from app.models.prediction import ModelPrediction, ModelVersion
from app.models.research import ResearchExperiment, ResearchFold
from app.mt5.base import CandleRecord
from app.mt5.factory import get_connector
from app.schemas.common import (
    AgentIngestRequest,
    BacktestRequest,
    CandleOut,
    HealthResponse,
    ImportJobOut,
    ImportRequest,
    LoginRequest,
    MonitorIn,
    ResearchExperimentRequest,
    SymbolOut,
    TokenResponse,
    TrainRequest,
)
from app.research.config import ResearchConfig
from app.research.service import create_and_run_experiment
from app.api.deps import Principal, TenantRouter, current_username, require_agent_key, require_saas_key
from app.services.backfill import ensure_history_for_training
from app.services.candles import load_candles, upsert_candles
from app.services.events import record_event
from app.services.features import persist_latest_features
from app.services.importer import import_history
from app.services.predictions import (
    delete_model_version,
    generate_prediction,
    market_coverage,
    prune_inactive_models,
    research_pips,
    summarize_predictions,
)
from app.services.quality import latest_timestamp, quality_report
from app.services.runtime import runtime
from app.services.symbols import bootstrap_workspace_monitor, ensure_default_monitor, persist_discovered
from app.workers.collector_loop import start_collector, stop_collector

router = TenantRouter()
public = APIRouter()


@public.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
def login(payload: LoginRequest) -> TokenResponse:
    settings = get_settings()
    if payload.username != settings.dashboard_username or not verify_password(payload.password, settings.dashboard_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(access_token=create_access_token(payload.username, workspace_id=SYSTEM_WORKSPACE_ID))


@public.post("/api/internal/session-token", response_model=TokenResponse, tags=["auth"])
def session_token(workspace_id: int = Depends(require_saas_key)) -> TokenResponse:
    return TokenResponse(access_token=create_access_token(f"workspace:{workspace_id}", workspace_id=workspace_id))


@public.get("/api/health", response_model=HealthResponse, tags=["system"])
def health(db: Session = Depends(get_db)) -> HealthResponse:
    try:
        db.query(Symbol).limit(1).all()
        runtime.database_ok = True
        runtime.database_error = ""
    except Exception as exc:
        runtime.database_ok = False
        runtime.database_error = str(exc)
    snap = runtime.snapshot()
    return HealthResponse(
        status="ok" if runtime.database_ok else "degraded",
        app=get_settings().app_name,
        mt5=snap["mt5"],
        collector=snap["collector"],
        database=snap["database"],
        last_data=runtime.last_data_at,
        mt5_mode=snap["mt5_mode"],
        mt5_error=snap["mt5_error"],
        disclaimer=RESEARCH_DISCLAIMER,
    )


@router.get("/api/mt5/status", tags=["mt5"])
def mt5_status(_: str = Depends(current_username)):
    connector = get_connector()
    try:
        status = connector.status()
        if not status.connected:
            status = connector.connect()
        runtime.mt5_connected = status.connected
        runtime.mt5_error = status.last_error
        runtime.mt5_mode = status.mode
        return {
            "connected": status.connected,
            "mode": status.mode,
            "terminal": status.terminal,
            "server": status.server,
            "login": status.login,
            "company": status.company,
            "trade_allowed": False,
            "last_error": status.last_error,
            "symbols_available": status.symbols_available,
            "details": status.details,
        }
    except Exception as exc:
        runtime.mt5_connected = False
        runtime.mt5_error = str(exc)
        return {"connected": False, "mode": get_settings().mt5_mode, "last_error": str(exc), "trade_allowed": False}


@router.get("/api/symbols", response_model=list[SymbolOut], tags=["symbols"])
def list_symbols(
    refresh: bool = False,
    q: str | None = None,
    db: Session = Depends(get_db),
    _: str = Depends(current_username),
):
    connector = get_connector()
    if refresh:
        try:
            if not connector.status().connected:
                connector.connect()
            persist_discovered(db, connector.discover_symbols(q))
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"MT5 symbol discovery failed: {exc}")
    query = db.query(Symbol)
    if q:
        query = query.filter(Symbol.name.ilike(f"%{q}%"))
    return query.order_by(Symbol.name.asc()).all()


@router.get("/api/monitor", tags=["symbols"])
def list_monitor(db: Session = Depends(get_db), _: str = Depends(current_username)):
    bootstrap_workspace_monitor(db)
    return own(db.query(MonitoredInstrument), MonitoredInstrument).order_by(MonitoredInstrument.symbol.asc()).all()


@router.post("/api/monitor", tags=["symbols"])
def upsert_monitor(
    payload: MonitorIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_username),
):
    if payload.timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Unsupported timeframe")
    workspace_id = principal.workspace_id
    row = (
        own(db.query(MonitoredInstrument), MonitoredInstrument, workspace_id)
        .filter(MonitoredInstrument.symbol == payload.symbol, MonitoredInstrument.timeframe == payload.timeframe)
        .one_or_none()
    )
    if row is None:
        row = MonitoredInstrument(
            workspace_id=workspace_id,
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            enabled=payload.enabled,
        )
        db.add(row)
    else:
        row.enabled = payload.enabled
    db.commit()
    db.refresh(row)
    return row


@router.get("/api/candles", response_model=list[CandleOut], tags=["market"])
def get_candles(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=400, ge=10, le=5000),
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    _: str = Depends(current_username),
):
    return load_candles(db, symbol, timeframe, limit=limit, start=start, end=end)


@router.get("/api/features", tags=["market"])
def get_features(
    symbol: str,
    timeframe: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: str = Depends(current_username),
):
    rows = (
        db.query(FeatureRow)
        .filter(FeatureRow.symbol == symbol, FeatureRow.timeframe == timeframe)
        .order_by(FeatureRow.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [{"timestamp": r.timestamp, "symbol": r.symbol, "timeframe": r.timeframe, "values": r.values} for r in rows]


@router.get("/api/predictions", tags=["models"])
def get_predictions(
    symbol: str | None = None,
    timeframe: str | None = None,
    model_version: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    _: str = Depends(current_username),
):
    query = visible(db.query(ModelPrediction), ModelPrediction)
    if symbol:
        query = query.filter(ModelPrediction.symbol == symbol)
    if timeframe:
        query = query.filter(ModelPrediction.timeframe == timeframe)
    if model_version:
        query = query.filter(ModelPrediction.model_version == model_version)
    if start:
        query = query.filter(ModelPrediction.timestamp >= start)
    if end:
        query = query.filter(ModelPrediction.timestamp <= end)
    rows = query.order_by(ModelPrediction.timestamp.desc()).limit(limit).all()
    return [{**jsonable_encoder(row), "pips": research_pips(row)} for row in rows]


@router.get("/api/predictions/summary", tags=["models"])
def get_predictions_summary(
    symbol: str | None = None,
    timeframe: str | None = None,
    model_version: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    _: str = Depends(current_username),
):
    query = visible(db.query(ModelPrediction), ModelPrediction)
    if symbol:
        query = query.filter(ModelPrediction.symbol == symbol)
    if timeframe:
        query = query.filter(ModelPrediction.timeframe == timeframe)
    if model_version:
        query = query.filter(ModelPrediction.model_version == model_version)
    if start:
        query = query.filter(ModelPrediction.timestamp >= start)
    if end:
        query = query.filter(ModelPrediction.timestamp <= end)
    settings = get_settings()
    cost = float(settings.spread_cost_pips) + float(settings.transaction_cost_pips)
    payload = summarize_predictions(query.all(), cost)
    payload["market"] = market_coverage(db)
    return payload


@router.get("/api/models", tags=["models"])
def get_models(db: Session = Depends(get_db), _: str = Depends(current_username)):
    return visible(db.query(ModelVersion), ModelVersion).order_by(ModelVersion.created_at.desc()).all()


@router.delete("/api/models/inactive", tags=["models"])
def delete_inactive_models(db: Session = Depends(get_db), _: str = Depends(current_username)):
    result = prune_inactive_models(db)
    record_event(db, "info", "training", f"Deleted {result['deleted']} inactive model versions")
    return result


@router.delete("/api/models/{model_id}", tags=["models"])
def delete_model(model_id: int, db: Session = Depends(get_db), _: str = Depends(current_username)):
    result = delete_model_version(db, model_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail="Model not found in this workspace")
    record_event(
        db,
        "info",
        "training",
        f"Deleted {result['symbol']} {result['timeframe']} {result['version']}",
    )
    return result


@router.post("/api/models/train", tags=["models"])
def train_model(payload: TrainRequest, db: Session = Depends(get_db), _: str = Depends(current_username)):
    settings = get_settings()

    # A timeframe the collector never polled has no candles yet. Pull it from the
    # active MT5 adapter on demand so training a new timeframe is one click.
    backfill: dict | None = None
    try:
        backfill = ensure_history_for_training(db, get_connector(), payload.symbol, payload.timeframe)
    except Exception as exc:
        db.rollback()
        record_event(db, "warning", "backfill", f"On-demand import failed for {payload.symbol} {payload.timeframe}: {exc}")

    query = db.query(MarketCandle).filter(MarketCandle.symbol == payload.symbol, MarketCandle.timeframe == payload.timeframe)
    if payload.start:
        query = query.filter(MarketCandle.timestamp >= payload.start)
    if payload.end:
        query = query.filter(MarketCandle.timestamp <= payload.end)
    candles = [
        {
            "symbol": c.symbol,
            "timeframe": c.timeframe,
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "spread": c.spread or 0.0,
        }
        for c in query.order_by(MarketCandle.timestamp.asc()).all()
    ]
    try:
        result = train_logistic_regression(
            candles,
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            spread_cost_pips=settings.spread_cost_pips,
            transaction_cost_pips=settings.transaction_cost_pips,
            pip_size=pip_size_for(payload.symbol),
        )
    except ValueError as exc:
        detail = str(exc)
        if backfill and backfill.get("error"):
            detail = f"{detail} Live import reported: {backfill['error']}"
        raise HTTPException(status_code=400, detail=detail)
    own(db.query(ModelVersion), ModelVersion).filter(
        ModelVersion.symbol == payload.symbol,
        ModelVersion.timeframe == payload.timeframe,
    ).update({"is_active": False})
    version = ModelVersion(
        name=result["name"],
        version=result["version"],
        algorithm=result["algorithm"],
        symbol=result["symbol"],
        timeframe=result["timeframe"],
        feature_list=result["feature_list"],
        training_start=result["training_start"],
        training_end=result["training_end"],
        train_samples=result["train_samples"],
        validation_samples=result["validation_samples"],
        accuracy=result["classification"]["accuracy"],
        precision=result["classification"]["precision"],
        recall=result["classification"]["recall"],
        f1=result["classification"]["f1"],
        roc_auc=result["classification"]["roc_auc"],
        log_loss=result["classification"]["log_loss"],
        confusion_matrix=result["classification"]["confusion_matrix"],
        strategy_metrics=result["strategy"],
        artifact_path=result["artifact_path"],
        is_active=True,
        notes=RESEARCH_DISCLAIMER,
    )
    db.add(version)
    db.commit()
    record_event(db, "info", "training", f"Trained {payload.symbol} {payload.timeframe} {result['version']}")
    generate_prediction(db, payload.symbol, payload.timeframe)
    result["backfill"] = backfill
    return result


@router.get("/api/data-quality", tags=["quality"])
def data_quality(
    symbol: str | None = None,
    timeframe: str | None = None,
    db: Session = Depends(get_db),
    _: str = Depends(current_username),
):
    return quality_report(db, symbol, timeframe)


@router.post("/api/import", response_model=ImportJobOut, tags=["collection"])
def import_data(payload: ImportRequest, db: Session = Depends(get_db), _: str = Depends(current_username)):
    if payload.end <= payload.start:
        raise HTTPException(status_code=422, detail="end must be after start")
    connector = get_connector()
    job = import_history(db, connector, payload.symbol, payload.timeframe, payload.start, payload.end)
    persist_latest_features(db, job.symbol, payload.timeframe, lookback=300)
    return job


@router.get("/api/import", response_model=list[ImportJobOut], tags=["collection"])
def list_imports(db: Session = Depends(get_db), _: str = Depends(current_username)):
    return own(db.query(CollectionJob), CollectionJob).order_by(CollectionJob.created_at.desc()).limit(50).all()


@router.post("/api/collector/start", tags=["collection"])
def collector_start(_: str = Depends(current_username)):
    result = start_collector()
    return result


@router.post("/api/collector/stop", tags=["collection"])
def collector_stop(_: str = Depends(current_username)):
    return stop_collector()


@router.get("/api/collector/status", tags=["collection"])
def collector_status(db: Session = Depends(get_db), _: str = Depends(current_username)):
    rows = visible(db.query(CollectionStatus), CollectionStatus).order_by(CollectionStatus.symbol.asc()).all()
    return {"runtime": runtime.snapshot(), "rows": rows}


@router.get("/api/backtest", tags=["models"])
def backtest_get(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    min_probability: float = 0.65,
    spread_cost_pips: float = 0.8,
    transaction_cost_pips: float = 0.2,
    model_version: str | None = None,
    db: Session = Depends(get_db),
    _: str = Depends(current_username),
):
    return backtest(
        BacktestRequest(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            min_probability=min_probability,
            spread_cost_pips=spread_cost_pips,
            transaction_cost_pips=transaction_cost_pips,
            model_version=model_version,
        ),
        db,
        _,
    )


@router.post("/api/backtest", tags=["models"])
def backtest(payload: BacktestRequest, db: Session = Depends(get_db), _: str = Depends(current_username)):
    query = visible(db.query(ModelVersion), ModelVersion).filter(
        ModelVersion.symbol == payload.symbol,
        ModelVersion.timeframe == payload.timeframe,
    )
    if payload.model_version:
        query = query.filter(ModelVersion.version == payload.model_version)
    model = query.order_by(ModelVersion.created_at.desc()).first()
    if model is None:
        raise HTTPException(status_code=404, detail="No trained model for this symbol/timeframe")
    candles = [
        {
            "symbol": c.symbol,
            "timeframe": c.timeframe,
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "spread": c.spread or 0.0,
        }
        for c in db.query(MarketCandle)
        .filter(
            MarketCandle.symbol == payload.symbol,
            MarketCandle.timeframe == payload.timeframe,
            MarketCandle.timestamp >= payload.start,
            MarketCandle.timestamp <= payload.end,
        )
        .order_by(MarketCandle.timestamp.asc())
        .all()
    ]
    try:
        return run_backtest(
            candles,
            model.artifact_path,
            payload.min_probability,
            payload.spread_cost_pips,
            payload.transaction_cost_pips,
            payload.symbol,
            payload.timeframe,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/research/experiments", tags=["research"])
def list_research_experiments(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: str = Depends(current_username),
):
    return (
        own(db.query(ResearchExperiment), ResearchExperiment)
        .order_by(ResearchExperiment.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/api/research/experiments/{experiment_id}", tags=["research"])
def get_research_experiment(
    experiment_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(current_username),
):
    experiment = (
        own(db.query(ResearchExperiment), ResearchExperiment)
        .filter(ResearchExperiment.id == experiment_id)
        .one_or_none()
    )
    if experiment is None:
        raise HTTPException(status_code=404, detail="Research experiment not found")
    folds = (
        db.query(ResearchFold)
        .filter(ResearchFold.experiment_id == experiment.id)
        .order_by(ResearchFold.fold_index.asc())
        .all()
    )
    return {**jsonable_encoder(experiment), "folds": jsonable_encoder(folds)}


@router.post("/api/research/experiments", tags=["research"])
def run_research_experiment(
    payload: ResearchExperimentRequest,
    db: Session = Depends(get_db),
    _: str = Depends(current_username),
):
    settings = get_settings()
    config = ResearchConfig(
        tp_atr=payload.tp_atr,
        sl_atr=payload.sl_atr,
        timeout_bars=payload.timeout_bars,
        spread_cost_pips=float(settings.spread_cost_pips),
        transaction_cost_pips=float(settings.transaction_cost_pips),
        minimum_edge_pips=payload.minimum_edge_pips,
        ambiguity_policy=payload.ambiguity_policy,
        folds=payload.folds,
        min_train_bars=payload.min_train_bars,
        validation_bars=payload.validation_bars,
        minimum_tuning_signals=payload.minimum_tuning_signals,
        minimum_validation_signals=payload.minimum_validation_signals,
        thresholds=tuple(sorted(set(payload.thresholds))),
        bootstrap_samples=payload.bootstrap_samples,
    )
    try:
        experiment = create_and_run_experiment(
            db,
            symbol=payload.symbol.upper(),
            timeframe=payload.timeframe,
            config=config,
            strategy_name=payload.strategy_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_event(
        db,
        "info",
        "research",
        f"Research experiment {experiment.code}: {experiment.status}",
        {"experiment_id": experiment.id, "metrics": experiment.metrics},
    )
    return get_research_experiment(experiment.id, db, _)


@router.get("/api/dashboard", tags=["market"])
def dashboard(db: Session = Depends(get_db), _: str = Depends(current_username)):
    instruments = [item for item in bootstrap_workspace_monitor(db) if item.enabled]
    cards = []
    for item in instruments:
        recent = (
            db.query(MarketCandle)
            .filter(MarketCandle.symbol == item.symbol, MarketCandle.timeframe == item.timeframe)
            .order_by(MarketCandle.timestamp.desc())
            .limit(30)
            .all()
        )
        latest = recent[0] if recent else None
        trend = [candle.close for candle in reversed(recent)]
        change_pct = None
        if len(trend) > 1 and trend[0]:
            change_pct = (trend[-1] - trend[0]) / trend[0] * 100
        pred = (
            own(db.query(ModelPrediction), ModelPrediction)
            .filter(ModelPrediction.symbol == item.symbol, ModelPrediction.timeframe == item.timeframe)
            .order_by(ModelPrediction.timestamp.desc())
            .first()
        )
        if pred is None and current_workspace_id() != SYSTEM_WORKSPACE_ID:
            pred = (
                db.query(ModelPrediction)
                .filter(
                    ModelPrediction.workspace_id == SYSTEM_WORKSPACE_ID,
                    ModelPrediction.symbol == item.symbol,
                    ModelPrediction.timeframe == item.timeframe,
                )
                .order_by(ModelPrediction.timestamp.desc())
                .first()
            )
        status = (
            db.query(CollectionStatus)
            .filter(
                CollectionStatus.workspace_id == SYSTEM_WORKSPACE_ID,
                CollectionStatus.symbol == item.symbol,
                CollectionStatus.timeframe == item.timeframe,
            )
            .one_or_none()
        )
        cards.append(
            {
                "symbol": item.symbol,
                "timeframe": item.timeframe,
                "price": latest.close if latest else None,
                "trend": trend,
                "change_pct": change_pct,
                "spread": latest.spread if latest else None,
                "spread_pips": spread_pips(latest.spread, item.symbol) if latest else None,
                "timestamp": latest.timestamp if latest else None,
                "status": status.status if status else "IDLE",
                "probability_up": pred.probability_up if pred else None,
                "probability_down": pred.probability_down if pred else None,
                "prediction": pred.prediction if pred else None,
                "model_version": pred.model_version if pred else None,
                "session": session_name(latest.timestamp) if latest else None,
            }
        )
    return {"health": runtime.snapshot(), "cards": cards, "disclaimer": RESEARCH_DISCLAIMER}


@router.get("/api/alerts", tags=["alerts"])
def list_alerts(db: Session = Depends(get_db), _: str = Depends(current_username)):
    return visible(db.query(Alert), Alert).order_by(Alert.created_at.desc()).limit(100).all()


@router.post("/api/alerts/{alert_id}/ack", tags=["alerts"])
def ack_alert(alert_id: int, db: Session = Depends(get_db), _: str = Depends(current_username)):
    row = visible(db.query(Alert), Alert).filter(Alert.id == alert_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    row.acknowledged = True
    db.commit()
    return row


@router.get("/api/logs", tags=["system"])
def list_logs(
    category: str | None = None,
    level: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    _: str = Depends(current_username),
):
    query = visible(db.query(SystemEvent), SystemEvent)
    if category:
        query = query.filter(SystemEvent.category == category)
    if level:
        query = query.filter(SystemEvent.level == level)
    return query.order_by(SystemEvent.created_at.desc()).limit(limit).all()


@router.get("/api/overview", tags=["quality"])
def overview(db: Session = Depends(get_db), _: str = Depends(current_username)):
    return {
        "candles": db.query(func.count(MarketCandle.id)).scalar() or 0,
        "symbols": db.query(func.count(Symbol.id)).scalar() or 0,
        "predictions": db.query(func.count(ModelPrediction.id)).filter(ModelPrediction.workspace_id.in_(research_ids())).scalar() or 0,
        "models": db.query(func.count(ModelVersion.id)).filter(ModelVersion.workspace_id.in_(research_ids())).scalar() or 0,
        "latest_timestamp": latest_timestamp(db),
        "feature_columns": FEATURE_COLUMNS,
    }


@router.post("/api/agent/ingest", tags=["agent"])
def agent_ingest(
    payload: AgentIngestRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_agent_key),
):
    from app.core.tenant import set_workspace_id

    set_workspace_id(SYSTEM_WORKSPACE_ID)
    if payload.status:
        runtime.mt5_connected = bool(payload.status.get("connected"))
        runtime.mt5_error = str(payload.status.get("last_error") or "")
        runtime.mt5_mode = "agent"
        if not runtime.mt5_connected:
            record_event(db, "error", "mt5", payload.status.get("last_error") or "Agent reported MT5 disconnect")
    records = [
        CandleRecord(
            symbol=c.symbol,
            timeframe=c.timeframe,
            timestamp=c.timestamp,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            bid=c.bid,
            ask=c.ask,
            spread=c.spread,
            tick_volume=c.tick_volume,
            real_volume=c.real_volume,
        )
        for c in payload.candles
    ]
    stored = upsert_candles(db, records) if records else {"inserted": 0, "duplicates": 0, "errors": []}
    symbols = {c.symbol for c in payload.candles}
    timeframes = {c.timeframe for c in payload.candles}
    for symbol in symbols:
        for timeframe in timeframes:
            persist_latest_features(db, symbol, timeframe)
            generate_prediction(db, symbol, timeframe)
    if records:
        runtime.last_data_at = datetime.now(UTC)
    return {"ok": True, **stored}


@router.post("/api/bootstrap", tags=["system"])
def bootstrap(db: Session = Depends(get_db), _: str = Depends(current_username)):
    connector = get_connector()
    status = connector.connect()
    if status.connected:
        persist_discovered(db, connector.discover_symbols())
        ensure_default_monitor(db, connector)
    return {"mt5": status.connected, "error": status.last_error, "symbols": db.query(func.count(Symbol.id)).scalar()}

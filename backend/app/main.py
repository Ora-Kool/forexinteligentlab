from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import public, router
from app.api.ws import router as ws_router
from app.core.config import get_settings
from app.core.constants import RESEARCH_DISCLAIMER
from app.core.logging import configure_logging, get_logger
from app.database.init_db import initialize
from app.services.hub import hub
from app.workers.collector_loop import start_collector

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    initialize()
    import asyncio

    hub.bind(asyncio.get_running_loop())
    if settings.mt5_mode.lower() != "agent":
        start_collector()
    log.info("startup", app=settings.app_name, mode=settings.mt5_mode, disclaimer=RESEARCH_DISCLAIMER)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        description=(
            "Research and data-analysis platform for FBS/MT5 market data. "
            "Does not place orders, deposits, or withdrawals. "
            + RESEARCH_DISCLAIMER
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=r"https?://((localhost|127\.0\.0\.1)(:\d+)?|forextradingai\.test)",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(public)
    application.include_router(router)
    application.include_router(ws_router)
    return application


app = create_app()

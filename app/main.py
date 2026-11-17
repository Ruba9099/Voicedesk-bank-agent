from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from . import models, security, services
from .api import admin, calls, telephony
from .config import Settings, get_settings
from .db import Base, make_engine
from .events import EventBus
from .seed import seed_demo_data
from .subscribers import ConnectionManager, register_subscribers

logger = logging.getLogger("voicedesk")
STATIC_DIR = Path(__file__).parent / "static"

DESCRIPTION = """
Voice-agent backend for bank call centres (demo: **Demo National Bank**).

* Operator-first routing: if every operator is busy (or does not answer in time) the AI agent takes the call.
* The agent verifies the caller (CNIC + date of birth) and then handles balance inquiry, card block,
  card activation, PIN change, address change and complaint registration.
* Deterministic dialog engine, no generative model, so nothing is invented.
* In-process pub/sub event bus feeds the audit log, SMS outbox, metrics and a live WebSocket feed.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    bus = EventBus()
    ws_manager = ConnectionManager()
    metrics = register_subscribers(bus, session_factory, ws_manager, settings)

    async def sweeper(app: FastAPI) -> None:
        while True:
            await asyncio.sleep(settings.sweep_interval_seconds)
            try:
                with session_factory() as db:
                    events = services.sweep(db, settings, models.utcnow())
                    db.commit()
                await bus.publish_many(events)
            except Exception:  # noqa: BLE001 - keep the loop alive
                logger.exception("ring-timeout sweeper failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(engine)
        if settings.seed_demo_data:
            with session_factory() as db:
                seed_demo_data(db, settings)
        if settings.api_key == "change-me" or settings.cnic_pepper == "change-me-pepper":
            logger.warning("Default API_KEY / CNIC_PEPPER in use. Set real secrets before deploying.")
        app.state.sweeper_task = asyncio.create_task(sweeper(app))
        try:
            yield
        finally:
            app.state.sweeper_task.cancel()
            try:
                await app.state.sweeper_task
            except asyncio.CancelledError:
                pass
            engine.dispose()

    app = FastAPI(title=settings.app_name, version=settings.version, description=DESCRIPTION, lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.bus = bus
    app.state.ws = ws_manager
    app.state.metrics = metrics
    app.state.sweeper_task = None

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(services.ServiceError)
    async def service_error_handler(_: Request, exc: services.ServiceError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.include_router(calls.router)
    app.include_router(admin.router)
    app.include_router(telephony.router)

    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok"}

    @app.get("/ready", tags=["system"])
    async def ready():
        try:
            with session_factory() as db:
                db.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            return JSONResponse(status_code=503, content={"status": "unavailable", "database": "down"})
        return {"status": "ready", "database": "ok"}

    @app.get("/api/v1/info", tags=["system"])
    async def info():
        return {"bank_name": settings.bank_name, "phone": settings.bank_phone, "demo": settings.demo_mode,
                "version": settings.version, "service": settings.app_name}

    @app.websocket("/ws/events")
    async def ws_events(websocket: WebSocket, key: str | None = Query(default=None)):
        if not security.api_key_ok(key, settings.api_key):
            await websocket.close(code=4401)
            return
        await ws_manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()  # ASGI entrypoint: uvicorn app.main:app

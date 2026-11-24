"""FastAPI application for the SSC recorder web UI."""

from __future__ import annotations

import base64
import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import OperationalError

from ssc.web.config import WebConfig, load_config
from ssc.web.db import create_readonly_engine
from ssc.web.routers import devices, health, history, presence, snapshots

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
APP_VERSION = "0.1.0"


def create_app(config: WebConfig) -> FastAPI:
    app = FastAPI(
        title="SSC Recorder",
        version=APP_VERSION,
        description="Read-only presence and state history for Schell SSC devices.",
        root_path=config.root_path,
    )
    app.state.config = config
    app.state.engine = create_readonly_engine(config.database)
    app.state.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    app.add_middleware(GZipMiddleware, minimum_size=1000)

    if config.basic_auth_user:
        password = config.basic_auth_password
        if password is None:
            raise RuntimeError("Basic auth user is set without a password")
        user = config.basic_auth_user

        @app.middleware("http")
        async def basic_auth(request: Request, call_next):  # noqa: ANN001
            header = request.headers.get("authorization", "")
            if header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(header[6:]).decode("utf-8")
                    supplied_user, supplied_password = decoded.split(":", 1)
                except Exception:  # noqa: BLE001
                    supplied_user, supplied_password = "", ""
                if secrets.compare_digest(supplied_user, user) and (
                    secrets.compare_digest(supplied_password, password)
                ):
                    return await call_next(request)
            return Response(
                status_code=401,
                content="Authentication required",
                headers={"WWW-Authenticate": 'Basic realm="SSC Recorder"'},
            )

    @app.exception_handler(OperationalError)
    async def _database_error(request: Request, exc: OperationalError) -> JSONResponse:
        logger.exception("Database read failed")
        return JSONResponse(
            status_code=503,
            content={"detail": "Recorder database is unavailable"},
        )

    api_prefix = "/api/v1"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(devices.router, prefix=api_prefix)
    app.include_router(presence.router, prefix=api_prefix)
    app.include_router(snapshots.router, prefix=api_prefix)
    app.include_router(history.router, prefix=api_prefix)

    app.mount(
        "/static",
        StaticFiles(directory=str(BASE_DIR / "static")),
        name="static",
    )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index(request: Request) -> HTMLResponse:
        return request.app.state.templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"page": "dashboard", "version": APP_VERSION},
        )

    @app.get(
        "/devices/{device_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def device_page(request: Request, device_id: int) -> HTMLResponse:
        return request.app.state.templates.TemplateResponse(
            request=request,
            name="device.html",
            context={
                "page": "device",
                "device_id": device_id,
                "version": APP_VERSION,
            },
        )

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    return app


app = create_app(load_config())
import logging
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from gateway.config import Settings
from gateway.db import session_factory
from gateway.logging import configure
from gateway.models import Application, Event
from gateway.schemas import ApplicationView, CreditEvent, EventView
from gateway.security import InvalidSignature, verify
from gateway.service import IdentityConflict, receive

logger = logging.getLogger("credit_gateway")
api_key = APIKeyHeader(name="X-Api-Key", auto_error=False)


def create_app(settings: Settings | None = None, clock=time.time):
    if settings is None:
        configure()
    settings = settings or Settings.from_env()
    engine, factory = session_factory(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        engine.dispose()

    app = FastAPI(
        title="Credit Event Gateway",
        version="1.0.0",
        description="Laboratório com eventos sintéticos; não aprova crédito real.",
        lifespan=lifespan,
    )
    app.state.engine, app.state.factory = engine, factory

    def partner(key: str | None = Depends(api_key)):
        found = settings.partners.get(key or "")
        if found is None:
            raise HTTPException(401, "Invalid API credential")
        return found

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, error):
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in error.errors()
                ]
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_request, _error):
        logger.warning("database_unavailable")
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    @app.middleware("http")
    async def observation(request: Request, call_next):
        started = time.monotonic()
        request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        route = getattr(request.scope.get("route"), "path", "unmatched")
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "route": route,
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            },
        )
        return response

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            raise HTTPException(503, "Database unavailable") from None
        return {"status": "ready"}

    @app.post("/v1/events", response_model=EventView, status_code=202)
    async def incoming(request: Request, response: Response, principal=Depends(partner)):
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > settings.body_limit:
                raise HTTPException(413, "Payload too large")
        try:
            verify(
                principal.hmac_secret,
                request.headers.get("X-Webhook-Timestamp", ""),
                request.headers.get("X-Webhook-Signature", ""),
                bytes(body),
                clock(),
                settings.signature_window,
            )
        except InvalidSignature:
            raise HTTPException(401, "Invalid webhook signature") from None
        try:
            event = CreditEvent.model_validate_json(body)
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from None
        try:
            row, created = await run_in_threadpool(
                receive, factory, principal.tenant_id, event, datetime.fromtimestamp(clock(), UTC)
            )
        except IdentityConflict:
            raise HTTPException(409, "Event identity already used with another payload") from None
        response.status_code = 202 if created else 200
        return row

    @app.get("/v1/events", response_model=list[EventView])
    def events(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10000),
        principal=Depends(partner),
    ):
        with factory() as session:
            return session.scalars(
                select(Event)
                .where(Event.tenant_id == principal.tenant_id)
                .order_by(Event.created_at, Event.id)
                .offset(offset)
                .limit(limit)
            ).all()

    @app.get("/v1/events/{event_id}", response_model=EventView)
    def event_by_id(event_id: str, principal=Depends(partner)):
        with factory() as session:
            row = session.scalar(
                select(Event).where(Event.tenant_id == principal.tenant_id, Event.id == event_id)
            )
            if row is None:
                raise HTTPException(404, "Event not found")
            return row

    @app.get("/v1/applications/{application_id}", response_model=ApplicationView)
    def application_by_id(application_id: str, principal=Depends(partner)):
        with factory() as session:
            row = session.get(Application, (principal.tenant_id, application_id))
            if row is None:
                raise HTTPException(404, "Application not found")
            return row

    return app

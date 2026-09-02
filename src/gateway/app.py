import logging
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from gateway.config import Settings, get_settings
from gateway.models import ChatRequest
from gateway.observability import Metrics, configure_logging, request_id_ctx
from gateway.upstream import LLMClient, UpstreamError

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build an application; injectable settings and transport keep tests hermetic."""
    resolved = settings or get_settings()
    metrics = Metrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        timeout = httpx.Timeout(resolved.request_timeout_seconds, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            app.state.llm_client = LLMClient(client, resolved, metrics)
            yield

    app = FastAPI(title="Policy-aware LLM Gateway", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied_id = request.headers.get("x-request-id", "")
        valid_id = supplied_id.isascii() and supplied_id.strip()
        request_id = supplied_id[:64] if valid_id else str(uuid.uuid4())
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled request error")
            response = JSONResponse(status_code=500, content={"detail": "internal server error"})
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        metrics.requests[(request.url.path, response.status_code)] += 1
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        request_id_ctx.reset(token)
        return response

    def authenticate(authorization: str | None = Header(default=None)) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        presented = authorization.removeprefix("Bearer ")
        if not any(secrets.compare_digest(presented, key) for key in resolved.inbound_api_keys):
            raise HTTPException(status_code=403, detail="invalid bearer token")

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics(_: None = Depends(authenticate)) -> Response:
        return Response(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.post("/v1/chat/completions", dependencies=[Depends(authenticate)])
    async def chat_completion(body: ChatRequest, request: Request) -> dict[str, object]:
        if body.model not in resolved.allowed_models:
            raise HTTPException(status_code=403, detail="model is not allowed")
        if len(body.messages) > resolved.max_messages:
            raise HTTPException(status_code=413, detail="too many messages")
        payload = body.model_dump(exclude_none=True)
        try:
            return await request.app.state.llm_client.create_chat_completion(payload)
        except UpstreamError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return app

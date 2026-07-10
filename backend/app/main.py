"""ReleaseIT backend — FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import (
    chat,
    config,
    document,
    product,
    release,
    solution,
    workflow,
)
from app.core.config import settings
from app.db.migrate import apply_pending
from app.db.pool import close_pool, connection, open_pool
from app.services import appconfig, issue_sync
from app.services import workflow as workflow_svc

log = logging.getLogger("releaseit.main")

# When the scheduled sync is disabled (interval <= 0), re-read the configured
# interval this often so re-enabling it on the configuration page takes effect
# without a restart.
_SYNC_DISABLED_POLL_SECONDS = 60


def _run_sync_cycle(app: FastAPI) -> int:
    """One scheduler cycle (runs in a worker thread — psycopg calls block)."""
    with connection() as conn:
        return issue_sync.sync_all(conn, app.state.state_machine)


async def _issue_sync_loop(app: FastAPI) -> None:
    """Re-sync every running release's issues on the configured schedule
    (``sync_interval_minutes``, default 10; 0 disables). The interval is
    re-read from the runtime configuration each cycle, so changes made on the
    configuration page apply without a restart."""
    while True:
        try:
            with connection() as conn:
                minutes = appconfig.effective(conn).sync_interval_minutes
        except Exception:
            log.exception("issue-sync scheduler could not read the configuration")
            minutes = 0

        if minutes <= 0:
            await asyncio.sleep(_SYNC_DISABLED_POLL_SECONDS)
            continue

        try:
            changed = await asyncio.to_thread(_run_sync_cycle, app)
            if changed:
                log.info("scheduled issue sync updated %d release(s)", changed)
        except Exception:
            log.exception("scheduled issue sync cycle failed")
        await asyncio.sleep(minutes * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    apply_pending()
    # The release-state graph is database-backed (seeded by the workflow
    # migration) and editable at runtime. Load it into app state at startup.
    with connection() as conn:
        app.state.state_machine = workflow_svc.from_db(conn)
    sync_task = asyncio.create_task(_issue_sync_loop(app))
    try:
        yield
    finally:
        sync_task.cancel()
        close_pool()


app = FastAPI(title="ReleaseIT", version="0.1.0", lifespan=lifespan)

# Never combine a wildcard origin with credentials: that lets any website make
# credentialed cross-origin requests against the API. Credentials are only
# enabled when an explicit origin allow-list is configured. (Auth uses a Bearer
# token in the Authorization header, so the wildcard dev default needs none.)
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials="*" not in _cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Error logging ---------------------------------------------------------
# Every failed request is logged with its method, path, status and caller (the
# gateway-injected identity) so failures — permission denials, not-found, guard
# rejections and unexpected crashes — leave a trace. The default response bodies
# are preserved; these handlers only add the log line.
def _caller(request: Request) -> str:
    return request.headers.get("x-auth-subject") or "anonymous"


@app.exception_handler(StarletteHTTPException)
async def _log_http_exception(request: Request, exc: StarletteHTTPException):
    level = logging.ERROR if exc.status_code >= 500 else logging.WARNING
    log.log(level, "%s %s -> %s: %s (caller=%s)",
            request.method, request.url.path, exc.status_code, exc.detail, _caller(request))
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def _log_validation_error(request: Request, exc: RequestValidationError):
    log.warning("%s %s -> 422 invalid request: %s (caller=%s)",
                request.method, request.url.path, exc.errors(), _caller(request))
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(Exception)
async def _log_unhandled(request: Request, exc: Exception):
    log.exception("%s %s -> 500 unhandled %s (caller=%s)",
                  request.method, request.url.path, type(exc).__name__, _caller(request))
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


# Authentication and the static role gates are enforced at the edge (the auth
# service's POST /auth + the shared authorization policy), not here. The backend
# trusts the gateway-injected identity headers (see app.core.identity).
app.include_router(product.router, prefix="/api/v1/product", tags=["product"])
app.include_router(release.router, prefix="/api/v1/release", tags=["release"])
app.include_router(document.router, prefix="/api/v1/release", tags=["document"])
app.include_router(workflow.router, prefix="/api/v1/workflow", tags=["workflow"])
app.include_router(config.router, prefix="/api/v1/config", tags=["config"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["chat"])

# Solution management is optional (docs: SOLUTION_ENABLED).
if settings.solution_enabled:
    app.include_router(solution.router, prefix="/api/v1/solution", tags=["solution"])


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}

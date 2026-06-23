"""ReleaseIT backend — FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import config, document, environment, product, release, solution, workflow
from app.core.config import settings
from app.db.migrate import apply_pending
from app.db.pool import close_pool, connection, open_pool
from app.services import workflow as workflow_svc


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    apply_pending()
    # The release-state graph is database-backed (seeded by the workflow
    # migration) and editable at runtime. Load it into app state at startup.
    with connection() as conn:
        app.state.state_machine = workflow_svc.from_db(conn)
    try:
        yield
    finally:
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

app.include_router(product.router, prefix="/api/v1/product", tags=["product"])
app.include_router(release.router, prefix="/api/v1/release", tags=["release"])
app.include_router(document.router, prefix="/api/v1/release", tags=["document"])
app.include_router(environment.router, prefix="/api/v1/environment", tags=["environment"])
app.include_router(workflow.router, prefix="/api/v1/workflow", tags=["workflow"])
app.include_router(config.router, prefix="/api/v1/config", tags=["config"])

# Solution management is optional (docs: SOLUTION_ENABLED).
if settings.solution_enabled:
    app.include_router(solution.router, prefix="/api/v1/solution", tags=["solution"])


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}

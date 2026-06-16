"""ReleaseIT backend — FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import environment, product, release, solution
from app.core.config import settings
from app.db.migrate import apply_pending
from app.db.pool import close_pool, open_pool
from app.services.state_machine import load_state_machine


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    apply_pending()
    # Load the configurable release-state graph into app state once at startup.
    app.state.state_machine = load_state_machine(settings.states_config_path)
    try:
        yield
    finally:
        close_pool()


app = FastAPI(title="ReleaseIT", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(product.router, prefix="/api/v1/product", tags=["product"])
app.include_router(release.router, prefix="/api/v1/release", tags=["release"])
app.include_router(environment.router, prefix="/api/v1/environment", tags=["environment"])

# Solution management is optional (docs: SOLUTION_ENABLED).
if settings.solution_enabled:
    app.include_router(solution.router, prefix="/api/v1/solution", tags=["solution"])


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}

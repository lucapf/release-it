# ReleaseIT

Unified release-management platform for Developers, Release Managers, QA Managers
and Administrators. See [`docs/release-it.md`](docs/release-it.md) for the domain
description and [the architecture plan](.) for design rationale.

## Architecture

| Component | Stack | Path |
|-----------|-------|------|
| Backend API | FastAPI + psycopg3 (raw SQL, plain-SQL migrations via `sqlparse`) | [`backend/`](backend) |
| Auth service | Separate FastAPI + psycopg3 project; issues RS256 JWTs + JWKS | [`auth/`](auth) |
| Frontend | React + TypeScript + Vite | [`frontend/`](frontend) |
| Storage | PostgreSQL 16 (files as `bytea`) | — |
| Deploy | Docker images, Helm charts, docker-compose | [`deploy/`](deploy) |

The backend is a **pure JWT resource server**: it validates Bearer tokens against
a configurable provider's JWKS and maps a role claim to ReleaseIT roles. The
bundled `releaseit-auth` is the default provider — it can be replaced by any
OIDC/JWT engine (Keycloak, Auth0, …) purely via configuration.

## Run locally (Docker)

```bash
cd deploy
docker compose up --build
```

- Frontend:  http://localhost:8080  (default login `admin` / `admin`)
- Backend:   http://localhost:8000/docs
- Auth:      http://localhost:8001/docs  ·  JWKS at `/.well-known/jwks.json`

## Run locally (without Docker)

```bash
# Auth service (issues tokens)
cd auth && pip install -e . && uvicorn app.main:app --port 8001

# Backend (verifies tokens, applies SQL migrations on startup)
cd backend && pip install -e . && uvicorn app.main:app --port 8000

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:5173
```

## Tests

```bash
cd backend && pytest        # state machine, etc.
cd auth && pytest           # password hashing + JWT/JWKS round-trip
```

## Configuration highlights

- `SOLUTION_ENABLED=false` disables the optional Solution feature (backend).
- Backend JWT: `JWT_ISSUER`, `JWT_AUDIENCE`, `JWT_JWKS_URL`, `JWT_ROLE_CLAIM`.
- Auth: `AUTH_PRIVATE_KEY_PEM` (mount a stable RS256 key in production),
  `AUTH_ISSUER`, `AUTH_AUDIENCE`, `AUTH_BOOTSTRAP_ADMIN_*`.
- Integrations (stubbed unless enabled): `JIRA_*`, `GITLAB_*`, `AWX_*`.

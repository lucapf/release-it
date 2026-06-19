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
| Storage | A single PostgreSQL 16 instance, one schema + login role per service (files as `bytea`) | — |
| Deploy | Docker images, per-service Helm charts + umbrella chart | [`deploy/`](deploy) |

The backend is a **pure JWT resource server**: it validates Bearer tokens against
a configurable provider's JWKS and maps a role claim to ReleaseIT roles. The
bundled `releaseit-auth` is the default provider — it can be replaced by any
OIDC/JWT engine (Keycloak, Auth0, …) purely via configuration.

### Data segregation

Both services share **one** PostgreSQL instance and **one** database
(`releaseit`). Each service is isolated into its own schema owned by its own
login role, with that role's `search_path` pinned to its schema:

| Service | Role | Schema |
|---------|------|--------|
| Backend | `releaseit` | `releaseit` |
| Auth | `auth` | `auth` |

Because each role only sees its own schema, the services' existing unqualified
SQL and migrations need no changes. On the cluster the roles/schemas are created
by the `releaseit-db` Helm chart's `initdb` script; for local-without-Docker
runs, create them by hand (see [Run locally](#run-locally-without-docker)).

### Deploy to Kubernetes

Each service's Helm chart lives in a `chart/` directory next to its source code;
a `release-it` **umbrella chart** pulls them together as subcharts:

```
auth/chart/           # releaseit-auth chart
backend/chart/        # releaseit-backend chart
frontend/chart/       # releaseit-frontend chart
deploy/helm/
  release-it/         # umbrella: depends on the four service charts
  releaseit-db/       # single shared Postgres (schema + role per service)
```

One `helm` release brings up the whole stack (one shared Postgres + the three
services):

```bash
./deploy/minikube-deploy.sh
# builds images into minikube, then: helm upgrade --install release-it deploy/helm/release-it
```

## Run locally (without Docker)

First bring up a PostgreSQL 16 reachable on `localhost:5432` with a database
named `releaseit`, then create the per-service roles + schemas (matching the
app defaults):

```sql
CREATE ROLE releaseit LOGIN PASSWORD 'releaseit';
CREATE SCHEMA releaseit AUTHORIZATION releaseit;
ALTER ROLE releaseit SET search_path = releaseit;

CREATE ROLE auth LOGIN PASSWORD 'auth';
CREATE SCHEMA auth AUTHORIZATION auth;
ALTER ROLE auth SET search_path = auth;
```

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

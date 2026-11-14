# Orchestrix AI - Backend Service

FastAPI service powering the Orchestrix AI autonomous engineering platform.

## Database Architecture

The database architecture is built on **Neon Serverless PostgreSQL** using **SQLAlchemy 2.x (async)**, **Alembic**, and **asyncpg**.

### Data Models
- **`User`** (`users`): Represents engineers and platform users. Includes UUID primary key, indexed unique email, display name, avatar, and active state.
- **`Workspace`** (`workspaces`): Multi-tenant workspace root. Includes UUID primary key, name, and unique indexed URL slug.
- **`WorkspaceMembership`** (`workspace_memberships`): Tenant isolation link associating a `User` with a `Workspace` under a defined `WorkspaceRole` (`OWNER`, `ADMIN`, `MEMBER`, `VIEWER`). Enforces unique composite constraints (`user_id`, `workspace_id`) and cascading delete rules.

### Multi-Tenant Isolation Strategy
- All future data models (repositories, code reviews, tasks, test suites, and memories) will be strictly foreign-keyed to `workspace_id`.
- Tenant isolation is enforced at query time via `AsyncSession` scoping and is structured for PostgreSQL Row-Level Security (RLS) policies.

---

## Database Commands (Windows PowerShell)

### Run Alembic Migrations
```powershell
cd backend
# Check current migration revision
uv run alembic current

# Apply migrations to latest head
uv run alembic upgrade head

# Generate a new migration revision
uv run alembic revision --autogenerate -m "describe schema change"
```

### Run Automated Tests
```powershell
cd backend
# Run test suite including database unit tests and health endpoints
uv run pytest
```

### Check Database Health
Once the backend is running (`uv run uvicorn app.main:app --reload`), inspect:
- Root API: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)
- Database Ping: [http://localhost:8000/api/v1/health/database](http://localhost:8000/api/v1/health/database)

# Orchestrix AI - Backend Service

FastAPI service powering the Orchestrix AI autonomous engineering platform.

## Database Architecture

The database architecture is built on **Neon Serverless PostgreSQL** using **SQLAlchemy 2.x (async)**, **Alembic**, and **asyncpg**.

### Data Models
- **`User`** (`users`): System users and engineering collaborators. Includes UUID primary key, indexed unique email, display name, avatar, and active state.
- **`Workspace`** (`workspaces`): Multi-tenant workspace root. Includes UUID primary key, name, and unique indexed URL slug.
- **`WorkspaceMembership`** (`workspace_memberships`): Tenant isolation link associating a `User` with a `Workspace` under a defined `WorkspaceRole` (`OWNER`, `ADMIN`, `MEMBER`, `VIEWER`). Enforces unique composite constraints (`user_id`, `workspace_id`) and cascading delete rules.
- **`GitHubInstallation`** (`github_installations`): GitHub App installation metadata bound to a workspace (`installation_id`, `account_login`, `account_type`, `account_id`, `is_active`).
- **`Repository`** (`repositories`): Connected Git repositories (`workspace_id`, `installation_id`, `github_repository_id`, `full_name`, `default_branch`, `visibility`, `language`, `is_active`). Enforces `(workspace_id, github_repository_id)` uniqueness.
- **`RepositoryMember`** (`repository_members`): Scoped repository access roles for workspace members (`ADMIN`, `DEVELOPER`, `VIEWER`).
- **`EngineeringTask`** (`engineering_tasks`): Autonomous engineering tasks (`title`, `task_type`, `priority`, `status`, `assigned_agent`, `workspace_id`, optional `repository_id`, `created_by`).
- **`PullRequestRecord`** (`pull_request_records`): Tracks GitHub pull requests synthesized by or linked to engineering tasks (`pr_number`, `source_branch`, `target_branch`, `state`, `html_url`).
- **`AuditLog`** (`audit_logs`): Immutable audit records of administrative, security, and task operations with automatic credential sanitization.

### Multi-Tenant Isolation Strategy
- All repositories, installations, engineering tasks, pull requests, and audit logs are strictly foreign-keyed and scoped to `workspace_id`.
- Tenant isolation is validated at both the database level (constraints and indexes) and the service layer:
  - Repositories cannot be bound to an installation outside their workspace.
  - Tasks cannot reference repositories outside their workspace.
  - Queries strictly filter on `workspace_id` to prevent cross-tenant data leakage.

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
# Run test suite including database unit tests, entity lifecycle, and health endpoints
uv run pytest
```

---

## API Endpoints

### Repositories
- `GET /api/v1/repositories?workspace_id={uuid}&limit=20&offset=0` — List active repositories for a workspace.
- `GET /api/v1/repositories/{repository_id}?workspace_id={uuid}` — Retrieve repository details.
- `POST /api/v1/repositories` — Register a new repository under an authorized installation.
- `PATCH /api/v1/repositories/{repository_id}?workspace_id={uuid}` — Update repository metadata.
- `DELETE /api/v1/repositories/{repository_id}?workspace_id={uuid}` — Soft-delete/deactivate a repository.

### Engineering Tasks
- `GET /api/v1/tasks?workspace_id={uuid}&status={status}&repository_id={uuid}` — List workspace tasks.
- `POST /api/v1/tasks` — Create a new engineering task.
- `GET /api/v1/tasks/{task_id}?workspace_id={uuid}` — Retrieve task details.
- `PATCH /api/v1/tasks/{task_id}?workspace_id={uuid}` — Update task status or agent assignment.

### Health
- `GET /api/v1/health` — API service operational status.
- `GET /api/v1/health/database` — Neon PostgreSQL connectivity ping (`SELECT 1`).

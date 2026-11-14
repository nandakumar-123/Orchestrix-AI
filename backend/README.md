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

### Multi-Tenant Isolation Strategy & Database Integrity
- All repositories, installations, engineering tasks, pull requests, repository members, and audit logs are strictly scoped to `workspace_id`.
- **Database-Level Composite Foreign Keys & Deletion Policy**:
  - `repositories (installation_id, workspace_id)` -> `github_installations (id, workspace_id)`: Guarantees a repository cannot reference an installation from another workspace.
  - `engineering_tasks (repository_id, workspace_id)` -> `repositories (id, workspace_id)`:
    - Uses PostgreSQL column-specific `ON DELETE SET NULL (repository_id)`.
    - When a repository is deleted, only `repository_id` is set to NULL while `workspace_id` remains strictly NOT NULL and unchanged.
    - Tasks remain preserved with all titles, status, descriptions, and audit history.
    - Supported both via direct database SQL deletion and via the transactional service `delete_repository_hard`.
  - `pull_request_records (repository_id, workspace_id)` -> `repositories (id, workspace_id)`: Guarantees a pull request belongs to the same workspace as its repository (`ON DELETE CASCADE`).
  - `repository_members (repository_id, workspace_id)` -> `repositories (id, workspace_id)` AND `(user_id, workspace_id)` -> `workspace_memberships (user_id, workspace_id)`:
    - Guarantees that only users who have verified membership in the repository's workspace can be assigned to that repository.
    - Migration safety is verified forward-only (revision `e4dec49fd32c`) ensuring orphan records and invalid memberships cause migration aborts without silent data corruption or deletion.
- **Repository Member Roles**:
  - `ADMIN`: Manage repository access and repository-level settings within the workspace.
  - `DEVELOPER`: Work with engineering tasks and repository operations permitted by workspace policy.
  - `VIEWER`: Read-only application access.
  - *Note: These are Orchestrix AI application roles and not GitHub permission levels.*
- **Audit Log Immutability**:
  - Audit records are append-only. No service endpoints or CRUD functions expose update or delete operations on `audit_logs`.
  - Secrets and credentials (tokens, private keys, passwords) are automatically redacted upon ingestion (`[REDACTED]`).
- **Authentication & Workspace Authorization**:
  - **Google OAuth 2.0 PKCE Flow**: Uses OpenID Connect with PKCE (S256), state and nonce verification, and server-side JWKS validation.
  - **Server-Side Opaque Sessions**: 32-byte cryptographically secure random session tokens stored as SHA-256 digests in `auth_sessions`, issued via HttpOnly, SameSite=Lax, Secure cookies.
  - **Automatic Provisioning**: First-time sign-ins automatically provision an isolated default workspace with `OWNER` membership.
  - **Route-Level Role Authorization**: FastAPI `require_workspace_membership` dependency enforces workspace membership and role hierarchy (`VIEWER <= MEMBER <= ADMIN <= OWNER`). Cross-workspace access is strictly rejected with `403 Forbidden`.
  - **Endpoints**:
    - `GET /auth/google/login`: Initiates OAuth consent redirect with signed transit cookie.
    - `GET /auth/google/callback`: Validates state/nonce/PKCE, exchanges tokens, provisions user/workspace, issues session cookie.
    - `GET /api/v1/auth/me`: Returns current authenticated user profile, verified status, and workspaces with roles.
    - `POST /api/v1/auth/logout`: Revokes server-side session in database and clears session cookie.

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
# Run test suite including database unit tests, tenant integrity, and health endpoints
uv run pytest

# Run PostgreSQL integration tests against live Neon database
uv run pytest tests/test_postgres_integration.py
```
```

---

## API Endpoints

### Repositories
- `GET /api/v1/repositories?workspace_id={uuid}&limit=20&offset=0` — List active repositories for a workspace.
- `GET /api/v1/repositories/{repository_id}?workspace_id={uuid}` — Retrieve repository details.
- `POST /api/v1/repositories` — Register a new repository under an authorized installation.
- `PATCH /api/v1/repositories/{repository_id}?workspace_id={uuid}` — Update repository metadata.
- `DELETE /api/v1/repositories/{repository_id}?workspace_id={uuid}` — Soft-delete/deactivate a repository.
- `POST /api/v1/repositories/{repository_id}/members?workspace_id={uuid}` — Assign a workspace member to a repository (`ADMIN`, `DEVELOPER`, `VIEWER`).

### Engineering Tasks
- `GET /api/v1/tasks?workspace_id={uuid}&status={status}&repository_id={uuid}` — List workspace tasks.
- `POST /api/v1/tasks` — Create a new engineering task.
- `GET /api/v1/tasks/{task_id}?workspace_id={uuid}` — Retrieve task details.
- `PATCH /api/v1/tasks/{task_id}?workspace_id={uuid}` — Update task status or agent assignment.

### Health
- `GET /api/v1/health` — API service operational status.
- `GET /api/v1/health/database` — Neon PostgreSQL connectivity ping (`SELECT 1`).

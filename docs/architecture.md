# Orchestrix AI Architecture Documentation

## Overview

Orchestrix AI is an autonomous multi-agent software engineering platform that orchestrates the entire software engineering lifecycle—from requirements analysis, architecture, synthesis, and testing, through to deployment and self-healing.

## Monorepo Layout

```text
Orchestrix-AI/
├── .github/
│   └── workflows/
│       └── ci.yml               # Automated CI workflow
├── backend/
│   ├── alembic/                 # Alembic migration scripts
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/              # Versioned API routes & Pydantic schemas
│   │   ├── core/                # Settings & Pydantic configurations
│   │   ├── db/
│   │   │   ├── base.py          # Base declarative class & naming conventions
│   │   │   ├── session.py       # AsyncEngine, AsyncSession, check_database_connection
│   │   │   └── models/          # SQLAlchemy 2.x Async ORM entities
│   │   │       ├── audit_log.py
│   │   │       ├── engineering_task.py
│   │   │       ├── github_installation.py
│   │   │       ├── membership.py
│   │   │       ├── pull_request.py
│   │   │       ├── repository.py
│   │   │       ├── repository_member.py
│   │   │       ├── user.py
│   │   │       └── workspace.py
│   │   ├── services/
│   │   │   └── database.py      # Reusable business logic & queries
│   │   └── main.py              # FastAPI app factory & lifespan
│   ├── tests/                   # Pytest automated test suite
│   ├── pyproject.toml           # Authoritative Python package definitions
│   ├── uv.lock                  # Pinned dependency lockfile
│   └── requirements.txt         # Compatibility export
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js App Router (Layout & Pages)
│   │   ├── components/ui/       # shadcn/ui component primitives
│   │   ├── lib/                 # Utility helpers (clsx, twMerge)
│   │   └── __tests__/           # Vitest and Testing Library test suite
│   ├── package.json             # Frontend dependencies & npm scripts
│   └── package-lock.json        # NPM lockfile
├── docs/                        # Architecture and design documentation
├── scripts/                     # Local developer automation scripts
├── .env.example                 # Sanitized root environment template
├── .gitignore                   # Monorepo secret & build artifact ignore rules
└── README.md                    # Project README and quick start
```

## Relational Entity Schema

```text
Workspace (Multi-Tenant Root)
├── GitHubInstallation (1:N)
│   └── Repository (1:N)
│       ├── RepositoryMember (1:N) ── User
│       ├── EngineeringTask (1:N)
│       └── PullRequestRecord (1:N)
├── User (through WorkspaceMembership N:M)
├── EngineeringTask (1:N)
└── AuditLog (1:N)
```

## Security & Tenant Isolation Rules

1. **Workspace Boundary**: All queries accessing repositories, tasks, PRs, repository members, and audit logs must explicitly filter on `workspace_id`.
2. **Database-Level Composite Foreign Keys & Deletion Integrity**:
   - `repositories (installation_id, workspace_id)` -> `github_installations (id, workspace_id)`
   - `engineering_tasks (repository_id, workspace_id)` -> `repositories (id, workspace_id)`:
     - Uses PostgreSQL column-specific `ON DELETE SET NULL (repository_id)`.
     - Deleting a repository sets `repository_id` to NULL without affecting the non-nullable `workspace_id`.
     - Supported natively via direct SQL deletion and via the transactional service `delete_repository_hard`.
   - `pull_request_records (repository_id, workspace_id)` -> `repositories (id, workspace_id)`
   - `repository_members (repository_id, workspace_id)` -> `repositories (id, workspace_id)`
   - `repository_members (user_id, workspace_id)` -> `workspace_memberships (user_id, workspace_id)`:
     - Guarantees repository members must be active members of the repository's workspace.
     - Safe migration validation in Alembic ensures existing data is verified and never silently modified.
3. **Repository Member Application Roles**:
   - `ADMIN`: Manage repository settings and member access within workspace boundaries.
   - `DEVELOPER`: Work with tasks and engineering operations.
   - `VIEWER`: Read-only application access.
   - *These are Orchestrix AI application roles and not GitHub permission levels.*
4. **Audit Log Immutability**:
   - Audit records are append-only.
   - Credentials, API tokens, passwords, and secrets are automatically redacted (`[REDACTED]`).
5. **Multi-User Authentication & Workspace Authorization**:
   - Implemented: Google OAuth 2.0 OpenID Connect with PKCE (S256), Google JWKS validation, and email verification checks.
   - Implemented: Server-side opaque session management stored as SHA-256 digests in `auth_sessions` with HttpOnly cookies.
   - Implemented: Route-level `require_workspace_membership` dependency enforcing role hierarchy (`VIEWER <= MEMBER <= ADMIN <= OWNER`). Cross-workspace access returns `403 Forbidden`.
   - Planned (Future Phases): GitHub App installation token issuance and webhook dispatch.

## Authentication & Authorization (Google OAuth 2.0 & Session Management)

Orchestrix AI implements production-grade authentication with tenant-isolated workspace authorization:

1. **Login Initiation (`GET /auth/google/login`)**:
   - Generates cryptographically secure `state`, `nonce`, and PKCE `code_verifier`/`code_challenge` (S256).
   - Encodes parameters into a signed, tamper-proof, short-lived transit JWT cookie (`orchestrix_oauth_transit`).
   - Redirects user to Google OAuth consent screen.
2. **Callback Handling (`GET /auth/google/callback`)**:
   - Verifies transit cookie and state match (preventing CSRF).
   - Exchanges authorization code and PKCE verifier for Google tokens.
   - Validates Google ID token against Google's JWKS (`https://www.googleapis.com/oauth2/v3/certs`) and checks `email_verified == True`.
   - Provisions or matches user account:
     - Resolves user by `google_sub` or verified `email`.
     - Automatically provisions an isolated personal workspace with `OWNER` role for first-time users.
   - Generates a 32-byte cryptographically secure random session token.
   - Stores SHA-256 digest in `auth_sessions.token_hash`.
   - Issues `orchestrix_session` HttpOnly, SameSite=Lax, Secure cookie.
   - Clears transit cookie and redirects to `/dashboard`.
3. **Current User Profile (`GET /api/v1/auth/me`)**:
   - Validates session token in DB, updates `last_accessed_at`.
   - Returns user profile, verification status, and all workspace memberships with application roles.
4. **Session Termination (`POST /api/v1/auth/logout`)**:
   - Revokes session in database (`is_revoked = True`).
   - Clears `orchestrix_session` cookie.

## Secret Isolation

Secrets (`.env`, `*.pem`, `*.key`) are strictly excluded from Git via `.gitignore`. Audit log details automatically redact sensitive keys.

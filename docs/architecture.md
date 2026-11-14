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

## Authentication & Authorization (Hardened Google OAuth 2.0 & Session Security)

Orchestrix AI implements production-grade, hardened authentication with tenant-isolated workspace authorization:

1. **Server-Side One-Time OAuth Transactions (`GET /auth/google/login`)**:
   - Generates cryptographically secure `state`, `nonce`, and PKCE `code_verifier`/`code_challenge` (S256).
   - Generates a 32-byte opaque random secret stored in the browser as `orchestrix_oauth_trx` cookie (HttpOnly, SameSite=Lax, 10-minute expiry).
   - Persists the transaction in PostgreSQL (`oauth_transactions`) with `lookup_hash = SHA256(secret)`, `state_hash = SHA256(state)`, `nonce`, and `code_verifier`.
   - Zero exposure: Raw PKCE code verifiers and nonces are never placed in browser cookies or client storage.
   - Redirects user to Google OAuth consent screen.
2. **Atomic One-Time Callback Handling & Replay Protection (`GET /auth/google/callback`)**:
   - Verifies browser secret cookie and callback state match.
   - Atomically consumes the transaction via single SQL statement:
     `UPDATE oauth_transactions SET consumed_at = :now WHERE lookup_hash = :lh AND state_hash = :sh AND consumed_at IS NULL AND expires_at > :now RETURNING *`
   - Replayed, expired, or concurrent callback attempts fail atomically with `replay_detected` or `expired`.
   - Deletes `orchestrix_oauth_trx` cookie immediately on both success and failure.
   - Exchanges authorization code and PKCE verifier for Google tokens, validating ID token with Google's JWKS and audience/issuer.
3. **Google Account-Linking Integrity**:
   - Normalizes email addresses (lowercased, stripped).
   - Requires verified emails (`email_verified == True`); unverified emails are strictly rejected.
   - Enforces unique `google_sub`: if an existing user with matching email has a conflicting Google sub, login fails with `409 Conflict (account_linking_conflict)`.
   - Inactive accounts (`is_active == False`) fail immediately with `403 Forbidden (account_inactive)`.
   - Handles concurrent registration collisions with rollback and retry.
   - Retains existing workspaces; provisions isolated personal workspace with `OWNER` role only for newly registered users.
4. **CSRF Protection (Double-Submit HMAC-Signed Token & Origin Verification)**:
   - Provides `GET /api/v1/auth/csrf` returning HMAC-signed CSRF tokens, mirrored in `orchestrix_csrf` cookie.
   - Enforces CSRF validation on all cookie-authenticated state-changing requests (`POST`, `PUT`, `PATCH`, `DELETE`):
     - Validates `Origin` / `Referer` headers against `allowed_origins` (`CORS_ORIGINS` + `FRONTEND_ORIGIN`).
     - Validates `X-CSRF-Token` header matches `orchestrix_csrf` cookie via constant-time `hmac.compare_digest`.
     - Validates HMAC signature of the token using `SESSION_SECRET_KEY`.
   - Safe HTTP methods (`GET`, `HEAD`, `OPTIONS`) and Bearer-token requests are exempt.
5. **Session Management & Throttling**:
   - Issues 32-byte cryptographically secure session token in `orchestrix_session` HttpOnly cookie.
   - Verifies session tokens against SHA-256 digests in `auth_sessions`.
   - Throttles `last_accessed_at` database updates (at most once every 60 seconds) to mitigate database write amplification.
   - `POST /api/v1/auth/logout`: Revokes active session, clears session, CSRF, and transaction cookies. Protected with CSRF validation.
6. **Security Logging**:
   - Structured events logged via `logging.getLogger("orchestrix.security")` for auditability without logging tokens, codes, or secrets.

## Secret Isolation

Secrets (`.env`, `*.pem`, `*.key`) are strictly excluded from Git via `.gitignore`. Audit log details automatically redact sensitive keys.

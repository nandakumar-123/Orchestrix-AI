# Orchestrix AI

> Autonomous Multi-Agent Software Engineering Platform

Orchestrix AI is an autonomous software engineering engine designed to automate requirement decomposition, architecture synthesis, multi-agent code generation, verification, and self-healing deployment lifecycles.

---

## Architecture Overview

Orchestrix AI is structured as a clean, decoupled monorepo:

- **Frontend**: Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui component primitives, and Lucide icons.
- **Backend**: Python 3.11, FastAPI, Pydantic Settings, and managed exclusively with `uv`.
- **Infrastructure**: Automated GitHub Actions CI pipeline, PowerShell & Bash automation scripts, and zero-secret exposure policies.

```text
Orchestrix-AI/
├── .github/workflows/ci.yml     # Automated CI pipeline (Backend & Frontend)
├── backend/                     # FastAPI backend application
│   ├── app/
│   │   ├── api/v1/              # Versioned API routes & schemas
│   │   ├── core/                # Settings & configurations
│   │   └── main.py              # Application entrypoint
│   ├── tests/                   # Pytest test suite
│   ├── pyproject.toml           # Authoritative dependency declarations
│   ├── uv.lock                  # Pinned uv lockfile
│   └── requirements.txt         # Compatibility requirements file
├── frontend/                    # Next.js App Router application
│   ├── src/
│   │   ├── app/                 # App Router pages and layout
│   │   ├── components/ui/       # shadcn/ui components (Button, Card, Badge)
│   │   ├── lib/                 # Utility helpers (cn)
│   │   └── __tests__/           # Vitest and Testing Library unit tests
│   ├── package.json             # NPM dependencies and scripts
│   └── package-lock.json        # NPM lockfile
├── docs/                        # Architecture and technical documentation
├── scripts/                     # Automation scripts for setup, testing, and dev
├── .env.example                 # Sanitized monorepo environment template
└── .gitignore                   # Monorepo gitignore protecting secrets
```

---

## Prerequisites

- **Python**: 3.11+
- **uv**: Astral's `uv` package and project manager (`pip install uv` or `winget install astral-sh.uv`)
- **Node.js**: v20 or v22
- **npm**: v10+

---

## Quick Start

### 1. Environment Setup

Copy `.env.example` to `.env` in the project root:

```powershell
Copy-Item .env.example .env
```

### 2. Install Dependencies

You can run the automated PowerShell setup script:

```powershell
.\scripts\setup.ps1
```

Or manually:

```powershell
# Backend
cd backend
uv python pin 3.11
uv sync --all-extras
cd ..

# Frontend
cd frontend
npm install
cd ..
```

### 3. Run Development Servers

Run both servers with the dev runner script:

```powershell
.\scripts\run-dev.ps1
```

Or start them individually:

- **Backend**:
  ```powershell
  cd backend
  uv run uvicorn app.main:app --reload --port 8000
  ```
  Swagger Docs: [http://localhost:8000/docs](http://localhost:8000/docs)  
  Health Check: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

- **Frontend**:
  ```powershell
  cd frontend
  npm run dev
  ```
  Web UI: [http://localhost:3000](http://localhost:3000)

---

## Testing & Quality Assurance

Run the comprehensive monorepo test script:

```powershell
.\scripts\test-all.ps1
```

### Backend Checks
```powershell
cd backend
uv run ruff check .          # Linting
uv run ruff format --check . # Code formatting check
uv run mypy app tests        # Static type checking
uv run pytest                # Unit and endpoint tests
```

### Frontend Checks
```powershell
cd frontend
npm run lint                 # ESLint check
npm run typecheck            # TypeScript compiler check
npm run test                 # Vitest test suite
npm run build                # Production build validation
```

---

## Security

- Secrets, credentials, private `.pem` keys, and local environment files (`.env`) are strictly excluded via `.gitignore`.
- All secret access is handled dynamically through Pydantic configuration schemas.
- Do not commit private keys or API credentials.


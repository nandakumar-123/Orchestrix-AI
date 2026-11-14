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
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/              # API router and endpoints (Health, etc.)
│   │   ├── core/                # Settings & Pydantic configurations
│   │   └── main.py              # FastAPI app factory
│   ├── tests/                   # Pytest test suite
│   ├── pyproject.toml           # Authoritative Python package definitions
│   ├── uv.lock                  # Pinned dependency lockfile
│   └── requirements.txt         # Compatibility export
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js App Router (Layout & Page)
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

## Security & Secret Management

- The `.gitignore` file enforces that `.env`, `.env*.local`, `*.pem`, `*.key`, and the `keys/` directory are never tracked in Git.
- Real keys and secrets are loaded dynamically via `pydantic-settings` from local environment files.
- Sample placeholder configuration is maintained in `.env.example`, `backend/.env.example`, and `frontend/.env.example`.


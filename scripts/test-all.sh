#!/usr/bin/env bash
set -e

echo "=== Orchestrix AI — Running All Tests & Linters ==="

echo -e "\n[Backend 1/4] Ruff Linting..."
cd backend
uv run ruff check .

echo -e "\n[Backend 2/4] Ruff Formatting Check..."
uv run ruff format --check .

echo -e "\n[Backend 3/4] Mypy Type Checking..."
uv run mypy app tests

echo -e "\n[Backend 4/4] Pytest..."
uv run pytest
cd ..

echo -e "\n[Frontend 1/3] ESLint..."
cd frontend
npm run lint

echo -e "\n[Frontend 2/3] TypeScript Typecheck..."
npm run typecheck

echo -e "\n[Frontend 3/3] Vitest Test Suite..."
npm run test
cd ..

echo -e "\nAll tests and validations passed cleanly!"


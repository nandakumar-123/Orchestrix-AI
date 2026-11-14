#!/usr/bin/env bash
set -e

echo "=== Orchestrix AI — Local Development Setup ==="

echo -e "\n[1/3] Syncing backend dependencies with uv..."
cd backend
uv python pin 3.11
uv sync --all-extras
cd ..

echo -e "\n[2/3] Installing frontend dependencies with npm..."
cd frontend
npm install
cd ..

echo -e "\n[3/3] Verifying environment configurations..."
if [ ! -f .env ]; then
  echo "Copying .env.example to .env..."
  cp .env.example .env
fi

echo -e "\nSetup complete! Run ./scripts/run-dev.sh or ./scripts/test-all.sh."


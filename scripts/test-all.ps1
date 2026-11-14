Write-Host "Running comprehensive tests and linters across monorepo..." -ForegroundColor Cyan

$backendPath = Join-Path $PSScriptRoot "..\backend"
$frontendPath = Join-Path $PSScriptRoot "..\frontend"

Write-Host "`n[Backend 1/4] Ruff Linting..." -ForegroundColor Yellow
Set-Location $backendPath
uv run ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`n[Backend 2/4] Ruff Formatting Check..." -ForegroundColor Yellow
uv run ruff format --check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`n[Backend 3/4] Mypy Type Checking..." -ForegroundColor Yellow
uv run mypy app tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`n[Backend 4/4] Pytest Test Suite..." -ForegroundColor Yellow
uv run pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`n[Frontend 1/3] ESLint..." -ForegroundColor Yellow
Set-Location $frontendPath
npm run lint
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`n[Frontend 2/3] TypeScript Type Check..." -ForegroundColor Yellow
npm run typecheck
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`n[Frontend 3/3] Vitest Test Suite..." -ForegroundColor Yellow
npm run test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Set-Location $PSScriptRoot
Write-Host "`nAll monorepo checks and tests PASSED successfully!" -ForegroundColor Green


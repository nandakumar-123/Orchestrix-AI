Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Orchestrix AI — Local Development Setup" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check Python and uv
Write-Host "`n[1/4] Checking uv and Python environment..." -ForegroundColor Yellow
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "uv detected: $(uv --version)" -ForegroundColor Green
    Set-Location "$PSScriptRoot\..\backend"
    uv python pin 3.11
    uv sync --all-extras
    Set-Location $PSScriptRoot
} else {
    Write-Host "Error: 'uv' package manager is required for backend." -ForegroundColor Red
    exit 1
}

# 2. Check Node.js and npm
Write-Host "`n[2/4] Checking Node.js and frontend dependencies..." -ForegroundColor Yellow
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host "npm detected: $(npm --version)" -ForegroundColor Green
    Set-Location "$PSScriptRoot\..\frontend"
    npm install
    Set-Location $PSScriptRoot
} else {
    Write-Host "Error: 'npm' is required for frontend." -ForegroundColor Red
    exit 1
}

# 3. Environment check
Write-Host "`n[3/4] Checking environment configurations..." -ForegroundColor Yellow
$rootEnv = "$PSScriptRoot\..\.env"
if (Test-Path $rootEnv) {
    Write-Host ".env found in workspace root." -ForegroundColor Green
} else {
    Write-Host "No .env found. Copying .env.example to .env..." -ForegroundColor Yellow
    Copy-Item "$PSScriptRoot\..\.env.example" $rootEnv
}

# 4. Verify test suites
Write-Host "`n[4/4] Running automated tests..." -ForegroundColor Yellow
Set-Location "$PSScriptRoot\..\backend"
uv run pytest
Set-Location "$PSScriptRoot\..\frontend"
npm run test
Set-Location $PSScriptRoot

Write-Host "`nEnvironment setup complete! Run .\scripts\run-dev.ps1 to start services." -ForegroundColor Green


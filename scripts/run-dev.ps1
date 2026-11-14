Write-Host "Starting Orchestrix AI services..." -ForegroundColor Cyan

$backendPath = Join-Path $PSScriptRoot "..\backend"
$frontendPath = Join-Path $PSScriptRoot "..\frontend"

# Launch Backend in new terminal window
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$backendPath'; uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

# Launch Frontend in new terminal window
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontendPath'; npm run dev"

Write-Host "Services started!" -ForegroundColor Green
Write-Host "Frontend: http://localhost:3000" -ForegroundColor Cyan
Write-Host "Backend API: http://localhost:8000" -ForegroundColor Cyan
Write-Host "Backend Docs: http://localhost:8000/docs" -ForegroundColor Cyan


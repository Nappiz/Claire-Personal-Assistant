# ============================================================
#  Claire AI - Graceful Shutdown (stop.ps1)
#  Mematikan semua service Claire AI.
# ============================================================

$ErrorActionPreference = "Continue"
$PROJECT_ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host ""
Write-Host "  Stopping Claire AI services..." -ForegroundColor Yellow
Write-Host ""

# ---- Stop Frontend (Node/Next.js) ----
Write-Host "  [1/3] Stopping Frontend..." -NoNewline
$nodeProcesses = Get-Process -Name "node" -ErrorAction SilentlyContinue
if ($nodeProcesses) {
    $nodeProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host " done!" -ForegroundColor Green
} else {
    Write-Host " not running." -ForegroundColor DarkGray
}

# ---- Stop Backend (Python/Uvicorn) ----
Write-Host "  [2/3] Stopping Backend..." -NoNewline
$pythonProcesses = Get-Process -Name "python" -ErrorAction SilentlyContinue
if ($pythonProcesses) {
    $pythonProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host " done!" -ForegroundColor Green
} else {
    Write-Host " not running." -ForegroundColor DarkGray
}

# ---- Stop Local Docker Containers ----
Write-Host "  [3/3] Stopping Neo4j + SearXNG..." -NoNewline
Push-Location $PROJECT_ROOT
docker compose stop 2>&1 | Out-Null
Pop-Location
Write-Host " done!" -ForegroundColor Green

Write-Host ""
Write-Host "  All Claire AI services stopped." -ForegroundColor Green
Write-Host ""

# ============================================================
#  Claire AI - One-Click Launcher (start.ps1)
#  Double-click start-claire.bat untuk menjalankan script ini.
# ============================================================

$ErrorActionPreference = "Continue"
$PROJECT_ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BACKEND_DIR  = Join-Path $PROJECT_ROOT "backend"
$FRONTEND_DIR = Join-Path $PROJECT_ROOT "frontend"
$PYTHON_EXE   = Join-Path $BACKEND_DIR "venv\Scripts\python.exe"
$LOG_DIR      = Join-Path $PROJECT_ROOT "scripts\logs"

# Buat folder logs kalau belum ada
if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null }

# ---- Helper Functions ----
function Write-Status($icon, $text) {
    Write-Host "  [$icon] " -NoNewline -ForegroundColor Cyan
    Write-Host $text
}

function Write-Section($text) {
    Write-Host ""
    Write-Host "  === $text ===" -ForegroundColor Cyan
    Write-Host ""
}

# ---- STEP 0: Banner ----
Clear-Host
Write-Host ""
Write-Host "  CLAIRE AI - Personal Assistant" -ForegroundColor Magenta
Write-Host "  ==============================" -ForegroundColor DarkMagenta
Write-Host ""

# ---- STEP 1: Docker Desktop ----
Write-Section "Step 1: Docker Desktop"

$dockerProcess = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
if (-not $dockerProcess) {
    Write-Status "~" "Docker Desktop belum jalan, starting..."
    $dockerDesktopPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerDesktopPath) {
        Start-Process $dockerDesktopPath
    } else {
        Write-Status "X" "Docker Desktop tidak ditemukan! Pastikan sudah terinstall."
        Read-Host "Tekan Enter untuk keluar"
        exit 1
    }
} else {
    Write-Status "OK" "Docker Desktop sudah jalan."
}

# Tunggu Docker Engine ready
Write-Status "~" "Menunggu Docker Engine ready..."
$maxWait = 60
$waited = 0
while ($waited -lt $maxWait) {
    try {
        $dockerInfo = docker info 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Status "OK" "Docker Engine ready!"
            break
        }
    } catch {}
    Start-Sleep -Seconds 2
    $waited += 2
    Write-Host "." -NoNewline
}
if ($waited -ge $maxWait) {
    Write-Host ""
    Write-Status "!!" "Docker Engine belum ready setelah ${maxWait}s. Coba lanjut anyway..."
}

# ---- STEP 2: Local Docker Services ----
Write-Section "Step 2: Neo4j + SearXNG"

Push-Location $PROJECT_ROOT
docker compose up -d 2>&1 | Out-Null
Pop-Location

$neo4jStatus = docker ps --filter "name=personia_neo4j" --format "{{.Status}}" 2>&1
if ($neo4jStatus -match "Up") {
    Write-Status "OK" "Neo4j container running! ($neo4jStatus)"
} else {
    Write-Status "!!" "Neo4j mungkin belum sepenuhnya ready. Status: $neo4jStatus"
}

$searxngStatus = docker ps --filter "name=personia_searxng" --format "{{.Status}}" 2>&1
if ($searxngStatus -match "Up") {
    Write-Status "OK" "SearXNG container running! ($searxngStatus)"
} else {
    Write-Status "!!" "SearXNG mungkin belum sepenuhnya ready. Status: $searxngStatus"
}

# ---- STEP 3: Backend (Uvicorn) ----
Write-Section "Step 3: Backend API"

# Kill existing uvicorn jika ada
$existingUvicorn = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    try { $_.CommandLine -match "uvicorn" } catch { $false }
}
if ($existingUvicorn) {
    Write-Status "~" "Mematikan uvicorn lama..."
    $existingUvicorn | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

$backendLog = Join-Path $LOG_DIR "backend.log"
$backendProcess = Start-Process -FilePath $PYTHON_EXE `
    -ArgumentList "-m", "uvicorn", "main:app", "--reload", "--host", "127.0.0.1", "--port", "8100" `
    -WorkingDirectory $BACKEND_DIR `
    -WindowStyle Hidden `
    -RedirectStandardOutput $backendLog `
    -RedirectStandardError (Join-Path $LOG_DIR "backend_error.log") `
    -PassThru

Write-Status "OK" "Backend started! (PID: $($backendProcess.Id), Port: 8100)"

# ---- STEP 4: Frontend (Next.js) ----
Write-Section "Step 4: Frontend"

# Kill existing next dev jika ada
$existingNext = Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object {
    try { $_.CommandLine -match "next" } catch { $false }
}
if ($existingNext) {
    Write-Status "~" "Mematikan next dev lama..."
    $existingNext | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

$frontendLog = Join-Path $LOG_DIR "frontend.log"
$frontendProcess = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npm run dev > `"$frontendLog`" 2> `"$(Join-Path $LOG_DIR 'frontend_error.log')`"" `
    -WorkingDirectory $FRONTEND_DIR `
    -WindowStyle Hidden `
    -PassThru

Write-Status "OK" "Frontend started! (PID: $($frontendProcess.Id), Port: 3100)"

# ---- STEP 5: Tunggu & Buka Browser ----
Write-Section "Step 5: Opening Browser"

Write-Status "~" "Menunggu frontend siap..."
$ready = $false
$maxRetry = 30
for ($i = 0; $i -lt $maxRetry; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:3100" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
}
Write-Host ""

if ($ready) {
    Write-Status "OK" "Frontend ready! Membuka browser..."
    Start-Process "http://localhost:3100/chat"
} else {
    Write-Status "!!" "Frontend belum ready, tapi mungkin masih loading. Coba buka manual: http://localhost:3100/chat"
}

# ---- STEP 6: Summary ----
Write-Host ""
Write-Host "  ================================================" -ForegroundColor DarkGray
Write-Host "  Claire AI is running!" -ForegroundColor Green
Write-Host "  ================================================" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Frontend : http://localhost:3100/chat" -ForegroundColor White
Write-Host "  Backend  : http://localhost:8100" -ForegroundColor White
Write-Host "  Neo4j    : http://localhost:7474" -ForegroundColor White
Write-Host ""
Write-Host "  Logs     : scripts\logs\" -ForegroundColor DarkGray
Write-Host "  Stop     : scripts\stop.ps1" -ForegroundColor DarkGray
Write-Host "  ================================================" -ForegroundColor DarkGray
Write-Host ""

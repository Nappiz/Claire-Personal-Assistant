# ============================================================
#  Claire AI — Register Windows Startup Task
#  Jalankan SEKALI dengan Run as Administrator.
# ============================================================

$ErrorActionPreference = "Stop"
$PROJECT_ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BAT_PATH = Join-Path $PROJECT_ROOT "start-claire.bat"

$taskName = "ClaireAI-AutoStart"

Write-Host ""
Write-Host "  Registering Claire AI to Windows Task Scheduler..." -ForegroundColor Cyan
Write-Host ""

# Cek apakah task sudah ada
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "  Task '$taskName' sudah ada. Menghapus yang lama..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Buat action
$action = New-ScheduledTaskAction -Execute $BAT_PATH -WorkingDirectory $PROJECT_ROOT

# Trigger: saat user login
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Settings: jangan timeout, allow start manually
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

# Register
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Auto-start Claire AI Personal Assistant on login" `
    -RunLevel Highest `
    | Out-Null

Write-Host "  ✅ Task '$taskName' berhasil didaftarkan!" -ForegroundColor Green
Write-Host ""
Write-Host "  Sekarang Claire AI akan otomatis nyala setiap kamu login." -ForegroundColor White
Write-Host "  Untuk membatalkan: buka Task Scheduler > hapus '$taskName'" -ForegroundColor DarkGray
Write-Host ""

# Juga buat unregister script
$unregisterPath = Join-Path $PROJECT_ROOT "scripts\unregister-startup.ps1"
@"
# Hapus Claire AI dari Windows Startup
Unregister-ScheduledTask -TaskName "ClaireAI-AutoStart" -Confirm:`$false
Write-Host "Claire AI auto-start telah dinonaktifkan." -ForegroundColor Green
"@ | Out-File -FilePath $unregisterPath -Encoding UTF8

Write-Host "  Untuk unregister di kemudian hari, jalankan: scripts\unregister-startup.ps1" -ForegroundColor DarkGray
Write-Host ""

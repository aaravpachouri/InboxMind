$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$backend = Join-Path $projectRoot 'backend'
$frontend = Join-Path $projectRoot 'frontend'
$patchRoot = Join-Path $projectRoot 'InboxMind_AutoSync_Fast_Patch\patch'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$envFile = Join-Path $backend '.env'

if (!(Test-Path (Join-Path $backend 'gmail_agent\main.py')) -or !(Test-Path (Join-Path $frontend 'package.json'))) {
    throw 'Extract this ZIP into the root of InboxMind_Unified, the folder containing backend and frontend.'
}
if (!(Test-Path $patchRoot)) { throw "Patch files are missing: $patchRoot" }
if (!(Test-Path $python)) { throw "Backend virtual environment not found: $python" }
if (!(Test-Path $envFile)) { throw 'backend\.env not found; stopping without changing files.' }

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backupRoot = Join-Path $HOME "Downloads\InboxMind_AutoSync_Fast_Backup_$stamp"
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$relativeFiles = @(
    'backend\gmail_agent\background.py',
    'backend\gmail_agent\config.py',
    'backend\gmail_agent\gmail_client.py',
    'backend\.env.example',
    'backend\gmail_agent\main.py',
    'backend\gmail_agent\services\email_analysis.py',
    'backend\tests\test_api.py',
    'backend\tests\test_business_reliability.py',
    'frontend\src\App.tsx',
    'backend\.env'
)
foreach ($relative in $relativeFiles) {
    $source = Join-Path $projectRoot $relative
    if (Test-Path $source) {
        $destination = Join-Path $backupRoot $relative
        New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
        Copy-Item $source $destination -Force
    }
}

# Back up the currently configured SQLite database before modifying anything.
$env:INBOXMIND_BACKUP_DB = Join-Path $backupRoot 'active_database_backup.sqlite3'
Push-Location $backend
try {
    $backupDbCode = @'
import os, sqlite3
from pathlib import Path
from gmail_agent.config import Settings
settings = Settings()
source = Path(settings.database_path)
if not source.is_absolute():
    source = (Path.cwd() / source).resolve()
if not source.exists():
    raise SystemExit(f"Configured database was not found at {source}; stopping before changes.")
with sqlite3.connect(str(source)) as src, sqlite3.connect(os.environ['INBOXMIND_BACKUP_DB']) as dst:
    src.backup(dst)
print('Database backup created.')
'@
    $backupDbCode | & $python -
    if ($LASTEXITCODE -ne 0) { throw 'Database backup failed; no patch files were changed.' }
} finally { Pop-Location }
Remove-Item Env:\INBOXMIND_BACKUP_DB -ErrorAction SilentlyContinue
# Keep a non-hidden copy of .env in the archive because some PowerShell versions
# omit hidden files when compressing wildcard paths.
$envBackupCopy = Join-Path $backupRoot 'backend\env_backup.txt'
New-Item -ItemType Directory -Path (Split-Path $envBackupCopy -Parent) -Force | Out-Null
Copy-Item $envFile $envBackupCopy -Force
$backupZip = "$backupRoot.zip"
Compress-Archive -Path (Join-Path $backupRoot '*') -DestinationPath $backupZip -CompressionLevel Optimal -Force

# Copy the tested reliability files and performance changes into the project.
$patchFiles = @(
    'backend\gmail_agent\background.py',
    'backend\gmail_agent\config.py',
    'backend\gmail_agent\gmail_client.py',
    'backend\.env.example',
    'backend\gmail_agent\main.py',
    'backend\gmail_agent\services\email_analysis.py',
    'backend\tests\test_api.py',
    'backend\tests\test_business_reliability.py',
    'frontend\src\App.tsx'
)
foreach ($relative in $patchFiles) {
    $source = Join-Path $patchRoot $relative
    if (!(Test-Path $source)) { throw "Patch file missing: $source. Safety backup: $backupZip" }
    $destination = Join-Path $projectRoot $relative
    New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
    Copy-Item $source $destination -Force
}

# Change only three non-secret .env settings; preserve all other lines.
$envLines = @(Get-Content $envFile)
$updates = [ordered]@{
    'AUTO_SYNC_ENABLED' = 'true'
    'SYNC_INTERVAL_SECONDS' = '300'
    'SYNC_BATCH_SIZE' = '10'
}
foreach ($key in $updates.Keys) {
    $pattern = '^\s*' + [regex]::Escape($key) + '\s*='
    $found = $false
    for ($i = 0; $i -lt $envLines.Count; $i++) {
        if ($envLines[$i] -match $pattern) {
            $envLines[$i] = "$key=$($updates[$key])"
            $found = $true
        }
    }
    if (-not $found) { $envLines += "$key=$($updates[$key])" }
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envFile, [string[]]$envLines, $utf8NoBom)

# Saved UI settings override .env, so enable sync there too while preserving other settings.
Push-Location $backend
try {
    $updateDbCode = @'
from pathlib import Path
from gmail_agent.config import Settings
from gmail_agent.db import Database
settings = Settings()
db_path = Path(settings.database_path)
if not db_path.is_absolute():
    db_path = (Path.cwd() / db_path).resolve()
if not db_path.exists():
    raise SystemExit('Configured database missing; refusing to create a new one.')
db = Database(db_path)
saved = db.get_state('user_settings', {}) or {}
if not isinstance(saved, dict):
    raise SystemExit('Saved user settings are not a JSON object; refusing to overwrite them.')
saved['auto_sync_enabled'] = True
saved['sync_interval_seconds'] = 300
db.upsert_state('user_settings', saved)
print('Saved settings updated: automatic sync enabled, interval 300 seconds.')
'@
    $updateDbCode | & $python -
    if ($LASTEXITCODE -ne 0) { throw "Could not update saved settings. Safety backup: $backupZip" }
} finally { Pop-Location }

Write-Host "`n=== BACKEND TESTS ===" -ForegroundColor Cyan
Push-Location $backend
try {
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed. Safety backup: $backupZip" }
} finally { Pop-Location }

Write-Host "`n=== FRONTEND PRODUCTION BUILD ===" -ForegroundColor Cyan
Push-Location $frontend
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed. Safety backup: $backupZip" }
} finally { Pop-Location }

Write-Host "`nSUCCESS: automatic sync enabled (every 5 minutes), Gmail batch size 10, maximum 3 pages per cycle, maximum 3 local-model upgrades per cycle." -ForegroundColor Green
Write-Host "Backup ZIP: $backupZip" -ForegroundColor Green
Write-Host 'Restart the original backend and frontend. Check /api/v1/health for background_sync.enabled=true.' -ForegroundColor Green

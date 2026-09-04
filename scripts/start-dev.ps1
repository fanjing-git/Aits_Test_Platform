$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot ".runtime"
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

$modelKeyPath = Join-Path $runtimeDir "model-config-fernet.key"
if (-not (Test-Path $modelKeyPath)) {
    $modelKeyBytes = New-Object byte[] 32
    $modelKeyGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $modelKeyGenerator.GetBytes($modelKeyBytes)
    } finally {
        $modelKeyGenerator.Dispose()
    }
    $generatedModelKey = [Convert]::ToBase64String($modelKeyBytes).Replace("+", "-").Replace("/", "_")
    [System.IO.File]::WriteAllText($modelKeyPath, $generatedModelKey)
}
$modelConfigFernetKey = [System.IO.File]::ReadAllText($modelKeyPath).Trim()
if (-not $modelConfigFernetKey) {
    throw "Local model configuration key is empty: $modelKeyPath"
}

function Test-Service([string]$Url) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-ForUrl([string]$Url, [int]$Attempts = 30) {
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return $true }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

if (-not (Test-Path $pythonExe)) {
    throw "Python virtual environment was not found: $pythonExe"
}

if (-not (Test-Service "http://127.0.0.1:8000/")) {
    $backendLog = Join-Path $runtimeDir "backend.log"
    $backendArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command",
        "`$env:DJANGO_SETTINGS_MODULE='config.settings.dev'; `$env:DJANGO_SECRET_KEY='local-development-secret-key-at-least-32-bytes'; `$env:MODEL_CONFIG_FERNET_KEY='$modelConfigFernetKey'; Set-Location '$backendDir'; & '$pythonExe' manage.py runserver 127.0.0.1:8000 --insecure *>> '$backendLog'"
    )
    $backendProcess = Start-Process powershell.exe -ArgumentList $backendArgs -WindowStyle Hidden -PassThru
    Set-Content -Path (Join-Path $runtimeDir "backend.pid") -Value $backendProcess.Id
    Write-Host "Backend starting (PID $($backendProcess.Id))..."
} else {
    Write-Host "Backend already listening on http://127.0.0.1:8000/"
}

if (-not (Test-Service "http://127.0.0.1:5173/")) {
    $frontendLog = Join-Path $runtimeDir "frontend.log"
    $frontendArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command",
        "Set-Location '$frontendDir'; & npm.cmd run dev -- --strictPort *>> '$frontendLog'"
    )
    $frontendProcess = Start-Process powershell.exe -ArgumentList $frontendArgs -WindowStyle Hidden -PassThru
    Set-Content -Path (Join-Path $runtimeDir "frontend.pid") -Value $frontendProcess.Id
    Write-Host "Frontend starting (PID $($frontendProcess.Id))..."
} else {
    Write-Host "Frontend already listening on http://127.0.0.1:5173/"
}

$backendReady = Wait-ForUrl "http://127.0.0.1:8000/"
$frontendReady = Wait-ForUrl "http://127.0.0.1:5173/"

if (-not $backendReady -or -not $frontendReady) {
    Write-Host "A service did not become ready. Check .runtime/backend.log and .runtime/frontend.log."
    exit 1
}

Write-Host "Ready: http://127.0.0.1:5173/"
Write-Host "API:   http://127.0.0.1:8000/"

param(
    [bool]$NetworkEnabled = $true,
    [switch]$KeepBackend
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot ".runtime"
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"

$isAdministrator = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if ($NetworkEnabled -and -not $isAdministrator) {
    Write-Host "Elevating the complete local service bootstrap so it can replace stale backend processes safely."
    $elevatedCommand = "& '$PSCommandPath' -NetworkEnabled:$NetworkEnabled"
    if ($KeepBackend) {
        $elevatedCommand += " -KeepBackend"
    }
    $elevatedArguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command", $elevatedCommand
    )
    try {
        $elevatedProcess = Start-Process powershell.exe -Verb RunAs -ArgumentList $elevatedArguments -Wait -PassThru
    } catch {
        throw "当前受限运行上下文无法发起 Windows UAC 提升。请在管理员 PowerShell 中运行 start-dev.cmd，或让 Codex 使用允许外连的提升命令启动本地服务。原始错误：$($_.Exception.Message)"
    }
    exit $elevatedProcess.ExitCode
}

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

function Stop-ManagedBackend {
    $listenerProcesses = @(
        Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { Get-Process -Id ([int]$_) -ErrorAction SilentlyContinue }
    )
    $projectPythonProcesses = @(Get-Process -Name python,pythonw -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and ($_.Path -ieq $pythonExe)
    })
    $managedProcesses = @($listenerProcesses + $projectPythonProcesses) |
        Where-Object { $_ } |
        Sort-Object Id -Unique
    foreach ($process in $managedProcesses) {
        Write-Host "Stopping managed backend process PID $($process.Id)..."
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    $pidPath = Join-Path $runtimeDir "backend.pid"
    if (Test-Path $pidPath) {
        $trackedPid = 0
        [int]::TryParse((Get-Content -Raw -Encoding utf8 $pidPath).Trim(), [ref]$trackedPid) | Out-Null
        if ($trackedPid -gt 0) {
            $trackedProcess = Get-Process -Id $trackedPid -ErrorAction SilentlyContinue
            if ($trackedProcess -and $trackedProcess.ProcessName -match "^(powershell|pwsh)$") {
                Write-Host "Stopping tracked backend launcher PID $trackedPid..."
                Stop-Process -Id $trackedPid -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

if (-not (Test-Path $pythonExe)) {
    throw "Python virtual environment was not found: $pythonExe"
}

if (-not $KeepBackend) {
    Stop-ManagedBackend
}

if (-not (Test-Service "http://127.0.0.1:8000/")) {
    $backendLog = Join-Path $runtimeDir "backend.log"
    $backendArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command",
        "`$env:DJANGO_SETTINGS_MODULE='config.settings.dev'; `$env:DJANGO_SECRET_KEY='local-development-secret-key-at-least-32-bytes'; `$env:MODEL_CONFIG_FERNET_KEY='$modelConfigFernetKey'; Set-Location '$backendDir'; & '$pythonExe' manage.py runserver 127.0.0.1:8000 --noreload --insecure *>> '$backendLog'"
    )
    if ($NetworkEnabled -and -not $isAdministrator) {
        Write-Host "Backend requests elevated network access. Accept the Windows UAC prompt if shown."
        $backendProcess = Start-Process powershell.exe -Verb RunAs -ArgumentList $backendArgs -WindowStyle Hidden -PassThru
    } else {
        $backendProcess = Start-Process powershell.exe -ArgumentList $backendArgs -WindowStyle Hidden -PassThru
    }
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

$backendListener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty OwningProcess
if ($backendListener) {
    Set-Content -Encoding utf8 -Path (Join-Path $runtimeDir "backend.pid") -Value $backendListener
}

Write-Host "Ready: http://127.0.0.1:5173/"
Write-Host "API:   http://127.0.0.1:8000/"

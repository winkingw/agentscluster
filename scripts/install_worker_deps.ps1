param(
    [string]$EnvName = "agentsCluster"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Vendor = Join-Path $Root "vendor"
$Cache = Join-Path $Vendor "cache"
$Logs = Join-Path $Vendor "logs"
$Req = Join-Path $Vendor "requirements-workers.txt"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $Logs "install_worker_deps_$Stamp.log"

New-Item -ItemType Directory -Force -Path $Cache, $Logs | Out-Null
New-Item -ItemType File -Force -Path $Log | Out-Null

Write-Host "agentsCluster worker dependency install"
Write-Host "Root:      $Root"
Write-Host "Conda env: $EnvName"
Write-Host "Log:       $Log"
Write-Host ""

$Conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $Conda) {
    throw "conda not found. Activate agentsCluster manually, then rerun this script."
}

if (-not (Test-Path $Req)) {
    throw "requirements file not found: $Req"
}

if ($env:CONDA_DEFAULT_ENV -eq $EnvName) {
    $Command = @("python", "-m", "pip", "install", "--upgrade", "--cache-dir", $Cache, "--requirement", $Req)
} else {
    $Command = @("conda", "run", "-n", $EnvName, "python", "-m", "pip", "install", "--upgrade", "--cache-dir", $Cache, "--requirement", $Req)
}

Write-Host "Command: $($Command -join ' ')"
$OldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $Command[0] $Command[1..($Command.Count - 1)] 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $Log -Append
} finally {
    $ErrorActionPreference = $OldPreference
}

if ($LASTEXITCODE -ne 0) {
    throw "Install failed (exit code: $LASTEXITCODE). See log: $Log"
}

Write-Host ""
Write-Host "Done. Verify:"
Write-Host "  .\\agentsCluster.ps1 integrations list"
Write-Host "  .\\agentsCluster.ps1 tools list"
Write-Host "  .\\agentsCluster.ps1 tools install aider"
Write-Host "  (OpenHands 需要 Python 3.12+，建议用 uv 单独安装 openhands CLI)"
Write-Host "  (SWE-agent 在 Windows 上更推荐用 Docker/WSL 跑，不在本 conda env 安装)"

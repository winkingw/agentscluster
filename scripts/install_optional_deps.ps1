$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Vendor = Join-Path $Root "vendor"
$Cache = Join-Path $Vendor "cache"
$Logs = Join-Path $Vendor "logs"
$Req = Join-Path $Vendor "requirements-optional.txt"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $Logs "install_optional_deps_$Stamp.log"

New-Item -ItemType Directory -Force -Path $Cache, $Logs | Out-Null

Write-Host "agentsCluster optional dependency install"
Write-Host "Root:      $Root"
Write-Host "Conda env: $env:CONDA_DEFAULT_ENV"
Write-Host "Log:       $Log"

if ($env:CONDA_DEFAULT_ENV -eq "agentsCluster") {
    $Command = @("python", "-m", "pip", "install", "--upgrade", "--cache-dir", $Cache, "--requirement", $Req)
} else {
    $Conda = Get-Command conda -ErrorAction SilentlyContinue
    if (-not $Conda) {
        throw "conda not found. Activate agentsCluster manually, then rerun this script."
    }
    $Command = @("conda", "run", "-n", "agentsCluster", "python", "-m", "pip", "install", "--upgrade", "--cache-dir", $Cache, "--requirement", $Req)
}

Write-Host "Command: $($Command -join ' ')"
& $Command[0] $Command[1..($Command.Count - 1)] *>&1 | Tee-Object -FilePath $Log

Write-Host ""
Write-Host "Done. Run:"
Write-Host ".\agentsCluster.ps1 integrations list"
Write-Host ".\agentsCluster.ps1 integrations spike langgraph"
Write-Host ".\agentsCluster.ps1 integrations spike openai-agents"

$ErrorActionPreference = "Stop"

param(
    [string]$EnvName = "agentsCluster",
    [switch]$SkipUi
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Vendor = Join-Path $Root "vendor"
$Logs = Join-Path $Vendor "logs"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $Logs "install_$Stamp.log"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null

Write-Host "agentsCluster install"
Write-Host "Root:      $Root"
Write-Host "Conda env: $EnvName"
Write-Host "Log:       $Log"
Write-Host ""

$Conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $Conda) {
    throw "conda not found. Install Anaconda/Miniconda, then rerun scripts/install.ps1."
}

$EnvExists = (& conda env list) | Select-String -Pattern ("^\s*" + [regex]::Escape($EnvName) + "\s")

Push-Location $Root
try {
    if ($EnvExists) {
        Write-Host "Updating conda env from environment.yml ..."
        & conda env update -n $EnvName -f environment.yml --prune *>&1 | Tee-Object -FilePath $Log
    } else {
        Write-Host "Creating conda env from environment.yml ..."
        & conda env create -n $EnvName -f environment.yml *>&1 | Tee-Object -FilePath $Log
    }

    Write-Host ""
    Write-Host "Running agentsCluster init ..."
    & conda run -n $EnvName agentsCluster init *>&1 | Tee-Object -FilePath $Log -Append

    if (-not $SkipUi) {
        if (Test-Path (Join-Path $Root "ui\\package.json")) {
            Write-Host ""
            Write-Host "Building UI (npm ci && npm run build) ..."
            Push-Location (Join-Path $Root "ui")
            try {
                & npm ci *>&1 | Tee-Object -FilePath $Log -Append
                & npm run build *>&1 | Tee-Object -FilePath $Log -Append
            } finally {
                Pop-Location
            }
        }
    }

    Write-Host ""
    Write-Host "Running agentsCluster doctor ..."
    & conda run -n $EnvName agentsCluster doctor *>&1 | Tee-Object -FilePath $Log -Append

    Write-Host ""
    Write-Host "Done."
    Write-Host ""
    Write-Host "Next:"
    Write-Host "  conda activate $EnvName"
    Write-Host "  agentsCluster serve --host 127.0.0.1 --port 8765"
    Write-Host "  (then open http://127.0.0.1:8765/)"
} finally {
    Pop-Location
}


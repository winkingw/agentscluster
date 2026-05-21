param(
    [string]$EnvName = "agentsCluster",
    [switch]$SkipUi
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Vendor = Join-Path $Root "vendor"
$Logs = Join-Path $Vendor "logs"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $Logs "install_$Stamp.log"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null
New-Item -ItemType File -Force -Path $Log | Out-Null

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
        $OldPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & conda env update -n $EnvName -f environment.yml --prune 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $Log
        } finally {
            $ErrorActionPreference = $OldPreference
        }
        if ($LASTEXITCODE -ne 0) { throw "conda env update failed (exit code: $LASTEXITCODE). See log: $Log" }
    } else {
        Write-Host "Creating conda env from environment.yml ..."
        $OldPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & conda env create -n $EnvName -f environment.yml 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $Log
        } finally {
            $ErrorActionPreference = $OldPreference
        }
        if ($LASTEXITCODE -ne 0) { throw "conda env create failed (exit code: $LASTEXITCODE). See log: $Log" }
    }

    Write-Host ""
    Write-Host "Running agentsCluster init ..."
    $OldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & conda run -n $EnvName agentsCluster init 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $Log -Append
    } finally {
        $ErrorActionPreference = $OldPreference
    }
    if ($LASTEXITCODE -ne 0) { throw "agentsCluster init failed (exit code: $LASTEXITCODE). See log: $Log" }

    if (-not $SkipUi) {
        if (Test-Path (Join-Path $Root "ui\\package.json")) {
            Write-Host ""
            Write-Host "Building UI (npm ci && npm run build) ..."
            Push-Location (Join-Path $Root "ui")
            try {
                $OldPreference = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                try {
                    & npm ci 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $Log -Append
                    if ($LASTEXITCODE -ne 0) { throw "npm ci failed (exit code: $LASTEXITCODE). See log: $Log" }
                    & npm run build 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $Log -Append
                    if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit code: $LASTEXITCODE). See log: $Log" }
                } finally {
                    $ErrorActionPreference = $OldPreference
                }
            } finally {
                Pop-Location
            }
        }
    }

    Write-Host ""
    Write-Host "Running agentsCluster doctor ..."
    $OldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & conda run -n $EnvName agentsCluster doctor 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $Log -Append
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Doctor reported failures. See log: $Log"
        }
    } finally {
        $ErrorActionPreference = $OldPreference
    }

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

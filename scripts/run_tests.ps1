param(
    [string]$EnvName = "agentsCluster"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $Root
try {
    Write-Host "agentsCluster test runner"
    Write-Host "Root:      $Root"
    Write-Host "Conda env: $EnvName"
    Write-Host ""

    & conda run -n $EnvName python -m compileall -q src tests
    & conda run -n $EnvName python -m pip check
    & conda run -n $EnvName python tests\\smoke.py
    & conda run -n $EnvName python tests\\langgraph_smoke.py
    & conda run -n $EnvName python tests\\integration_smoke.py
    & conda run -n $EnvName python tests\\doctor_optional_openhands.py
    & conda run -n $EnvName python tests\\e2e_dry.py
    & conda run -n $EnvName python tests\\api_smoke.py

    Write-Host ""
    Write-Host "All tests passed."
} finally {
    Pop-Location
}

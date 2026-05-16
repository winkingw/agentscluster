$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = Join-Path $Root "src"

if ($env:CONDA_DEFAULT_ENV -eq "agentsCluster") {
    python -m agents_cluster.cli @args
    exit $LASTEXITCODE
}

$Conda = Get-Command conda -ErrorAction SilentlyContinue
if ($Conda) {
    conda run -n agentsCluster python -m agents_cluster.cli @args
    exit $LASTEXITCODE
}

python -m agents_cluster.cli @args

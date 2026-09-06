# Install Job Agent. Bundles its own Python via uv — no system Python needed.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$env:Path = "$env:USERPROFILE\.local\bin;$env:CARGO_HOME\bin;$env:Path"

function Get-Uv {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) { return $uv.Source }
    $local = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $local) { return $local }
    return $null
}

if (-not (Get-Uv)) {
    Write-Host "==> Installing a local Python runtime (uv)"
    irm https://astral.sh/uv/install.ps1 | iex
}

$Uv = Get-Uv
if (-not $Uv) { throw "Could not install uv. See https://docs.astral.sh/uv/getting-started/installation/" }

Write-Host "==> Creating virtualenv"
& $Uv python install 3.12
& $Uv venv .venv --python 3.12 --allow-existing

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
Write-Host "==> Installing job-agent"
& $Uv pip install --python $VenvPython -e $Root

$JobAgent = Join-Path $Root ".venv\Scripts\job-agent.exe"
Write-Host "==> Running setup"
& $JobAgent setup

Write-Host ""
Write-Host "Installed Job Agent to the Desktop and Start Menu."
Write-Host "Opening the app…"
Write-Host ""
if ($env:SKIP_APP -eq "1") { exit 0 }
& $JobAgent launch

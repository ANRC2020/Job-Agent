# Install Clover. Bundles its own Python via uv; no system Python needed.
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

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

if (-not (Get-Uv)) {
    Write-Host "==> Installing a local Python runtime (uv)"
    irm https://astral.sh/uv/install.ps1 | iex
}

$Uv = Get-Uv
if (-not $Uv) { throw "Could not install uv. See https://docs.astral.sh/uv/getting-started/installation/" }

Write-Host "==> Creating virtualenv"
Invoke-Checked -FilePath $Uv -Arguments @("python", "install", "3.12")
Invoke-Checked -FilePath $Uv -Arguments @("venv", ".venv", "--python", "3.12", "--allow-existing")

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
Write-Host "==> Installing Clover"
Invoke-Checked -FilePath $Uv -Arguments @("pip", "install", "--python", $VenvPython, "-e", $Root)

Write-Host "==> Running setup"
if ($env:CLOVER_WINDOWS_SMOKE_TEST -eq "1") {
    Write-Host "==> Windows smoke test: installing desktop integration without downloading a model"
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "job_agent", "install-desktop")
} else {
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "job_agent", "setup")
}

Write-Host ""
Write-Host "Installed Clover to the Desktop and Start Menu."
Write-Host "Opening Clover; no terminal needs to stay open."
Write-Host ""
if ($env:SKIP_APP -eq "1") { exit 0 }
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
Start-Process -FilePath $Pythonw -ArgumentList @("-m", "job_agent.launcher") -WorkingDirectory $Root

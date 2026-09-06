# Install Job Agent (CLI + desktop) and set up LM Studio only if needed.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Get-Python {
    foreach ($launcher in @("python", "py")) {
        try {
            if ($launcher -eq "py") {
                Get-Command py -ErrorAction Stop | Out-Null
                $exe = (& py -3 -c "import sys; print(sys.executable)").Trim()
                if ($exe) { return $exe }
            } else {
                $ver = & python -c "import sys; print(sys.version_info[0])" 2>$null
                if ($ver -eq "3") {
                    return (& python -c "import sys; print(sys.executable)").Trim()
                }
            }
        } catch { continue }
    }
    return $null
}

$Python = Get-Python
if (-not $Python) { throw "Python 3 is required. Install it from https://www.python.org/downloads/ then re-run." }

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "==> Creating virtualenv"
    & $Python -m venv (Join-Path $Root ".venv")
}

Write-Host "==> Installing job-agent"
& $VenvPython -m pip install -U pip
& $VenvPython -m pip install -e $Root

$JobAgent = Join-Path $Root ".venv\Scripts\job-agent.exe"
Write-Host "==> Running setup"
& $JobAgent setup

Write-Host ""
Write-Host "Installed Job Agent to the Desktop and Start Menu."
Write-Host "Opening the app…"
Write-Host ""
if ($env:SKIP_APP -eq "1") { exit 0 }
& $JobAgent launch

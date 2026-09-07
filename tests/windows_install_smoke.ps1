$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$DesktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) "Clover.lnk"
$StartLink = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Clover.lnk"

foreach ($Path in @($Python, $Pythonw, $DesktopLink, $StartLink)) {
    if (-not (Test-Path $Path)) {
        throw "Windows installation did not create: $Path"
    }
}

$Shell = New-Object -ComObject WScript.Shell
foreach ($Path in @($DesktopLink, $StartLink)) {
    $Shortcut = $Shell.CreateShortcut($Path)
    if ($Shortcut.TargetPath -ne $Pythonw) {
        throw "Clover shortcut uses '$($Shortcut.TargetPath)' instead of pythonw.exe"
    }
    if ($Shortcut.Arguments -ne "-m job_agent.launcher") {
        throw "Clover shortcut has unexpected arguments: $($Shortcut.Arguments)"
    }
    if ($Shortcut.WorkingDirectory -ne $Root) {
        throw "Clover shortcut has unexpected working directory: $($Shortcut.WorkingDirectory)"
    }
}

& $Python -c "import job_agent.app, job_agent.launcher; print('Clover Windows imports succeeded')"
if ($LASTEXITCODE -ne 0) {
    throw "Installed Clover could not be imported."
}

Write-Host "Windows installer and console-free shortcuts passed."

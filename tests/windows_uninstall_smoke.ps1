$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $env:LOCALAPPDATA "Clover"
$Marker = Join-Path $DataDir "uninstall-preserves-data.txt"

New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
Set-Content -Path $Marker -Value "keep"

$FreshDownload = Join-Path $env:RUNNER_TEMP "clover-fresh-uninstaller"
New-Item -ItemType Directory -Path $FreshDownload -Force | Out-Null
Copy-Item (Join-Path $Root "uninstall.cmd") $FreshDownload -Force
Copy-Item (Join-Path $Root "uninstall.ps1") $FreshDownload -Force

$env:CLOVER_UNINSTALL_REMOVE_DATA = "0"
& (Join-Path $FreshDownload "uninstall.cmd")
if ($LASTEXITCODE -ne 0) {
    throw "uninstall.cmd failed with exit code $LASTEXITCODE"
}

$DesktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) "Clover.lnk"
$StartLink = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Clover.lnk"
foreach ($Path in @((Join-Path $Root ".venv"), $DesktopLink, $StartLink)) {
    if (Test-Path $Path) {
        throw "Uninstaller left $Path behind"
    }
}
if (-not (Test-Path $Marker)) {
    throw "Uninstaller removed personal data without permission"
}

Write-Host "Windows uninstall smoke test passed; personal data was preserved."

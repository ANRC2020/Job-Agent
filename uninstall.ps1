# Uninstall Clover while preserving personal data unless explicitly requested.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallRoot = $Root
$Desktop = [Environment]::GetFolderPath("Desktop")
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$ShortcutPaths = @(
    (Join-Path $Desktop "Clover.lnk"),
    (Join-Path $Desktop "Job Agent.lnk"),
    (Join-Path $StartMenu "Clover.lnk"),
    (Join-Path $StartMenu "Job Agent.lnk")
)

# Recover an older installation folder when this uninstaller came from a
# newly downloaded ZIP.
try {
    $Shell = New-Object -ComObject WScript.Shell
    foreach ($ShortcutPath in $ShortcutPaths) {
        if (-not (Test-Path $ShortcutPath)) { continue }
        $WorkingDirectory = $Shell.CreateShortcut($ShortcutPath).WorkingDirectory
        if ($WorkingDirectory -and (Test-Path (Join-Path $WorkingDirectory ".venv"))) {
            $InstallRoot = $WorkingDirectory
            break
        }
    }
} catch {}
$Venv = Join-Path $InstallRoot ".venv"

Write-Host "Clover Uninstaller"
Write-Host ""
Write-Host "This removes the Clover app, shortcuts, and its private Python environment."
Write-Host "LM Studio will remain installed because other local apps may use it."
Write-Host ""

$JobAgent = Join-Path $Venv "Scripts\job-agent.exe"
if (Test-Path $JobAgent) {
    try { & $JobAgent stop *> $null } catch {}
}

try {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains($InstallRoot) -and
            $_.CommandLine -match "job_agent"
        } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch {}

foreach ($Path in $ShortcutPaths) {
    Remove-Item $Path -Force -ErrorAction SilentlyContinue
}

Remove-Item $Venv -Recurse -Force -ErrorAction SilentlyContinue

$RemoveData = $env:CLOVER_UNINSTALL_REMOVE_DATA
if (-not $RemoveData) {
    $Answer = Read-Host "Keep your profile, conversations, opportunities, and application history? [Y/n]"
    $RemoveData = if ($Answer -match "^(n|no)$") { "1" } else { "0" }
}

if ($RemoveData -eq "1") {
    Remove-Item (Join-Path $env:LOCALAPPDATA "Clover") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $env:LOCALAPPDATA "Job Agent") -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "Clover and its personal data were removed."
} else {
    Write-Host ""
    Write-Host "Clover was removed. Your personal data was preserved for a future reinstall."
}

Write-Host "You can now delete this downloaded Job-Agent folder."

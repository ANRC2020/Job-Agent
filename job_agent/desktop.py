from __future__ import annotations

import os
import platform
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from job_agent.paths import repo_root


def icon_png() -> Path:
    return Path(__file__).resolve().parent / "static" / "app-icon.png"


def icon_ico() -> Path:
    return Path(__file__).resolve().parent / "static" / "app-icon.ico"


def _write_ico_from_png(png: Path, ico: Path) -> None:
    payload = png.read_bytes()
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(payload), 22)
    ico.write_bytes(header + entry + payload)


def _write_icns(png: Path, icns: Path, log) -> None:
    if not png.is_file():
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        sizes = [(16, False), (16, True), (32, False), (32, True), (128, False), (128, True), (256, False), (256, True), (512, False), (512, True)]
        for size, retina in sizes:
            px = size * 2 if retina else size
            name = f"icon_{size}x{size}{'@2x' if retina else ''}.png"
            dest = iconset / name
            subprocess.run(
                ["sips", "-z", str(px), str(px), str(png), "--out", str(dest)],
                check=False,
                capture_output=True,
            )
        result = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log(result.stderr.strip() or "iconutil failed; Finder may show a generic icon")


def venv_python() -> Path:
    root = repo_root()
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "pythonw.exe"
    return root / ".venv" / "bin" / "python"


def _mac_app_dir() -> Path:
    home_apps = Path.home() / "Applications"
    home_apps.mkdir(parents=True, exist_ok=True)
    return home_apps / "Job Agent.app"


def _write_mac_app(log) -> Path:
    app = _mac_app_dir()
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    root = repo_root()
    python = root / ".venv" / "bin" / "python"
    launcher = macos / "Job Agent"
    launcher.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                "set -euo pipefail",
                f'ROOT="{root}"',
                'cd "$ROOT"',
                f'exec -a "Job Agent" "{python}" -m job_agent app',
                "",
            ]
        ),
        encoding="utf-8",
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    resources = app / "Contents" / "Resources"
    resources.mkdir(parents=True, exist_ok=True)
    png = icon_png()
    if png.is_file():
        shutil.copy2(png, resources / "app-icon.png")
        _write_icns(png, resources / "AppIcon.icns", log)
    plist = app / "Contents" / "Info.plist"
    plist.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Job Agent</string>
  <key>CFBundleDisplayName</key>
  <string>Job Agent</string>
  <key>CFBundleIdentifier</key>
  <string>app.jobagent.desktop</string>
  <key>CFBundleVersion</key>
  <string>0.1.0</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>Job Agent</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIconName</key>
  <string>AppIcon</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>LSUIElement</key>
  <false/>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    _install_desktop_alias(app, log)
    subprocess.run(["touch", str(app)], check=False)
    log(f"Installed Mac app at {app}")
    return app


def _install_desktop_alias(app: Path, log) -> None:
    desktop = Path.home() / "Desktop"
    for name in ("Job Agent.app",):
        path = desktop / name
        if path.exists() or path.is_symlink():
            try:
                path.unlink()
            except OSError:
                pass
    if (desktop / "Job Agent").exists():
        log("Desktop shortcut is named Job Agent")
        return
    script = f'''
tell application "Finder"
  set theApp to POSIX file "{app}" as alias
  set newAlias to make alias file at desktop to theApp
  set name of newAlias to "Job Agent"
  try
    set extension hidden of newAlias to true
  end try
end tell
'''
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        log((result.stderr or result.stdout).strip() or "Could not create Desktop alias")
    else:
        log("Desktop shortcut is named Job Agent")



def _write_windows_shortcuts(log) -> Path:
    root = repo_root()
    pythonw = venv_python()
    if not pythonw.is_file():
        pythonw = root / ".venv" / "Scripts" / "python.exe"
    png = icon_png()
    ico = icon_ico()
    if png.is_file():
        _write_ico_from_png(png, ico)
    icon_line = f"  $s.IconLocation = {repr(str(ico))}\n" if ico.is_file() else ""
    script = (
        "$root = "
        + repr(str(root))
        + "\n"
        "$python = "
        + repr(str(pythonw))
        + "\n"
        + """
$w = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$start = Join-Path $env:APPDATA "Microsoft\\Windows\\Start Menu\\Programs"
foreach ($dir in @($desktop, $start)) {
  $lnk = Join-Path $dir "Job Agent.lnk"
  $s = $w.CreateShortcut($lnk)
  $s.TargetPath = $python
  $s.Arguments = "-m job_agent app"
  $s.WorkingDirectory = $root
  $s.WindowStyle = 1
  $s.Description = "Job Agent"
"""
        + icon_line
        + """
  $s.Save()
}
Write-Output (Join-Path $desktop "Job Agent.lnk")
"""
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        text=True,
        capture_output=True,
    )
    path = (result.stdout or "").strip() or "Desktop\\Job Agent.lnk"
    log(f"Installed Windows shortcuts: {path}")
    return Path(path)


def install_desktop(log=print) -> Path:
    system = platform.system()
    if system == "Darwin":
        return _write_mac_app(log)
    if system == "Windows":
        return _write_windows_shortcuts(log)
    log("Desktop shortcut install is only implemented for macOS and Windows.")
    return repo_root()


def launch_desktop() -> None:
    system = platform.system()
    if system == "Darwin":
        app = _mac_app_dir()
        if app.is_dir():
            subprocess.Popen(["open", str(app)])
            return
    if system == "Windows":
        desktop = Path.home() / "Desktop" / "Job Agent.lnk"
        if desktop.is_file():
            os.startfile(str(desktop))  # type: ignore[attr-defined]
            return
    python = Path(sys.executable)
    subprocess.Popen([str(python), "-m", "job_agent", "app"], cwd=str(repo_root()))

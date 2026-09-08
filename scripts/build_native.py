"""Build Clover as a native Windows installer or macOS disk image."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "native"
DIST = ROOT / "dist"
PNG = ROOT / "job_agent" / "static" / "app-icon.png"


def run(*args: str) -> None:
    subprocess.run(list(args), cwd=ROOT, check=True)


def windows_icon() -> Path:
    target = BUILD / "Clover.ico"
    payload = PNG.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        struct.pack("<HHH", 0, 1, 1)
        + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(payload), 22)
        + payload
    )
    return target


def mac_icon() -> Path:
    iconset = BUILD / "Clover.iconset"
    target = BUILD / "Clover.icns"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir(parents=True, exist_ok=True)
    for size, retina in (
        (16, False),
        (16, True),
        (32, False),
        (32, True),
        (128, False),
        (128, True),
        (256, False),
        (256, True),
        (512, False),
        (512, True),
    ):
        pixels = size * 2 if retina else size
        suffix = "@2x" if retina else ""
        output = iconset / f"icon_{size}x{size}{suffix}.png"
        run("sips", "-z", str(pixels), str(pixels), str(PNG), "--out", str(output))
    run("iconutil", "-c", "icns", str(iconset), "-o", str(target))
    return target


def pyinstaller(icon: Path) -> None:
    separator = ";" if os.name == "nt" else ":"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        "Clover",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD / "work"),
        "--specpath",
        str(BUILD),
        "--icon",
        str(icon),
        "--add-data",
        f"{ROOT / 'prompts'}{separator}prompts",
        "--add-data",
        f"{ROOT / 'config'}{separator}config",
        "--collect-data",
        "job_agent",
        "--collect-all",
        "webview",
        "--collect-all",
        "trafilatura",
        "--collect-all",
        "playwright",
        "--collect-all",
        "ddgs",
        "--hidden-import",
        "webview.platforms.edgechromium",
        "--hidden-import",
        "webview.platforms.cocoa",
        str(ROOT / "scripts" / "native_entry.py"),
    ]
    run(*command)


def build_dmg() -> Path:
    app = DIST / "Clover.app"
    if not app.is_dir():
        raise FileNotFoundError(f"PyInstaller did not create {app}")
    staging = BUILD / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copytree(app, staging / "Clover.app", symlinks=True)
    (staging / "Applications").symlink_to("/Applications")
    target = DIST / "Clover-macOS.dmg"
    target.unlink(missing_ok=True)
    run(
        "hdiutil",
        "create",
        "-volname",
        "Clover",
        "-srcfolder",
        str(staging),
        "-ov",
        "-format",
        "UDZO",
        str(target),
    )
    return target


def find_iscc(explicit: str = "") -> Path:
    candidates = [
        Path(explicit) if explicit else Path(),
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if str(candidate) and candidate.is_file():
            return candidate
    located = shutil.which("iscc")
    if located:
        return Path(located)
    raise FileNotFoundError("Inno Setup 6 (ISCC.exe) is required for the Windows installer.")


def build_windows_installer(version: str, icon: Path, iscc: str = "") -> Path:
    source = DIST / "Clover"
    if not (source / "Clover.exe").is_file():
        raise FileNotFoundError(f"PyInstaller did not create {source / 'Clover.exe'}")
    run(
        str(find_iscc(iscc)),
        f"/DSourceDir={source}",
        f"/DAppVersion={version}",
        f"/DOutputDir={DIST}",
        f"/DIconFile={icon}",
        str(ROOT / "scripts" / "windows-installer.iss"),
    )
    target = DIST / "Clover-Windows-Setup.exe"
    if not target.is_file():
        raise FileNotFoundError(f"Inno Setup did not create {target}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--iscc", default="")
    args = parser.parse_args()
    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.rmtree(DIST, ignore_errors=True)
    BUILD.mkdir(parents=True)
    DIST.mkdir(parents=True)

    system = platform.system()
    if system == "Darwin":
        pyinstaller(mac_icon())
        artifact = build_dmg()
    elif system == "Windows":
        icon = windows_icon()
        pyinstaller(icon)
        artifact = build_windows_installer(
            args.version.removeprefix("v"),
            icon,
            args.iscc,
        )
    else:
        raise RuntimeError("Native releases are supported on Windows and macOS.")
    print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

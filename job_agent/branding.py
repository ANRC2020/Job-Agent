from __future__ import annotations

from pathlib import Path

from job_agent.paths import repo_root

APP_NAME = "Clover"
APP_ID = "app.clover.desktop"


def icon_png() -> Path:
    return Path(__file__).resolve().parent / "static" / "app-icon.png"


def apply_app_branding() -> None:
    """Make the running process look like Clover, not Python."""
    png = icon_png()
    if sys_is_macos():
        _brand_macos(png)
    elif sys_is_windows():
        _brand_windows(png)


def sys_is_macos() -> bool:
    import sys

    return sys.platform == "darwin"


def sys_is_windows() -> bool:
    import sys

    return sys.platform == "win32"


def _brand_macos(png: Path) -> None:
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyRegular, NSImage
        from Foundation import NSBundle
    except ImportError:
        return

    bundle = NSBundle.mainBundle()
    info = bundle.infoDictionary() if bundle is not None else None
    if info is not None:
        info["CFBundleName"] = APP_NAME
        info["CFBundleDisplayName"] = APP_NAME
        info["CFBundleIdentifier"] = APP_ID

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    if png.is_file():
        image = NSImage.alloc().initWithContentsOfFile_(str(png))
        if image is not None:
            app.setApplicationIconImage_(image)
            tile = app.dockTile()
            tile.display()
    app.activateIgnoringOtherApps_(True)


def _brand_windows(png: Path) -> None:
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    ico = repo_root() / "job_agent" / "static" / "app-icon.ico"
    if ico.is_file():
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

"""Console-free desktop entry point with a useful Windows error log."""

from __future__ import annotations

import contextlib
import ctypes
import faulthandler
import os
import traceback
from pathlib import Path

from job_agent.cli import main as cli_main
from job_agent.storage import app_data_dir


def _log_path() -> Path:
    folder = app_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "clover.log"


def _show_error(path: Path) -> None:
    if os.name != "nt":
        return
    message = (
        "Clover could not start.\n\n"
        "You do not need to open a terminal. Details were saved here:\n"
        f"{path}"
    )
    ctypes.windll.user32.MessageBoxW(None, message, "Clover", 0x10)  # type: ignore[attr-defined]


def main() -> int:
    path = _log_path()
    if path.is_file() and path.stat().st_size > 2_000_000:
        path.replace(path.with_suffix(".previous.log"))
    with path.open("a", encoding="utf-8", buffering=1) as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            faulthandler.enable(log)
            try:
                return cli_main(["app"])
            except BaseException:  # noqa: BLE001 - desktop failures must reach the log
                traceback.print_exc(file=log)
                _show_error(path)
                return 1


if __name__ == "__main__":
    raise SystemExit(main())

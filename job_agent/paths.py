from __future__ import annotations

import os
import sys
from pathlib import Path


def repo_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parent.parent


def lmstudio_home() -> Path:
    return Path.home() / ".lmstudio"


def system_prompt_path() -> Path:
    return repo_root() / "prompts" / "system.md"


def venv_python() -> Path | None:
    root = repo_root()
    if os.name == "nt":
        candidates = [
            root / ".venv" / "Scripts" / "python.exe",
            root / ".venv" / "Scripts" / "pythonw.exe",
        ]
    else:
        candidates = [root / ".venv" / "bin" / "python"]
    for path in candidates:
        if path.is_file():
            return path
    return None

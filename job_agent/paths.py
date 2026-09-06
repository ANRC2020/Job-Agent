from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def lmstudio_home() -> Path:
    return Path.home() / ".lmstudio"


def system_prompt_path() -> Path:
    return repo_root() / "prompts" / "system.md"

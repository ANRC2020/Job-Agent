"""Thread-safe, process-local progress for Juno's first model download."""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Any

_LOCK = threading.Lock()
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PERCENT = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*%")
_FRACTION = re.compile(
    r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|KIB|MIB|GIB)\s*(?:/|of)\s*"
    r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|KIB|MIB|GIB)",
    re.IGNORECASE,
)
_UNITS = {
    "KB": 1_000,
    "MB": 1_000_000,
    "GB": 1_000_000_000,
    "KIB": 1_024,
    "MIB": 1_048_576,
    "GIB": 1_073_741_824,
}
_STATE: dict[str, Any] = {
    "active": False,
    "phase": "idle",
    "percent": None,
    "detail": "",
    "attempt": 0,
    "attempts": 0,
    "model": "",
    "updatedAt": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def begin(model: str, attempt: int, attempts: int) -> None:
    with _LOCK:
        _STATE.update(
            {
                "active": True,
                "phase": "resolving",
                "percent": None,
                "detail": "Preparing the download…",
                "attempt": attempt,
                "attempts": attempts,
                "model": model,
                "updatedAt": _now(),
            }
        )


def consume(raw: str) -> None:
    clean = " ".join(_ANSI.sub("", raw or "").replace("\r", " ").split())
    if not clean:
        return
    percent = None
    matches = _PERCENT.findall(clean)
    if matches:
        percent = min(100.0, max(0.0, float(matches[-1])))
    else:
        fraction = _FRACTION.search(clean)
        if fraction:
            current = float(fraction.group(1)) * _UNITS[fraction.group(2).upper()]
            total = float(fraction.group(3)) * _UNITS[fraction.group(4).upper()]
            if total > 0:
                percent = min(100.0, max(0.0, current / total * 100))
    lower = clean.lower()
    phase = "downloading" if ("download" in lower or percent is not None) else "resolving"
    detail = (
        f"Downloading Juno… {percent:.0f}%"
        if percent is not None
        else ("Finding the best model for this computer…" if "resolv" in lower else clean[:140])
    )
    with _LOCK:
        _STATE.update(
            {
                "active": True,
                "phase": phase,
                "percent": percent if percent is not None else _STATE.get("percent"),
                "detail": detail,
                "updatedAt": _now(),
            }
        )


def finish() -> None:
    with _LOCK:
        _STATE.update(
            {
                "active": False,
                "phase": "complete",
                "percent": 100.0,
                "detail": "Download complete.",
                "updatedAt": _now(),
            }
        )


def fail(message: str) -> None:
    with _LOCK:
        _STATE.update(
            {
                "active": False,
                "phase": "error",
                "detail": (message or "The download was interrupted.")[:200],
                "updatedAt": _now(),
            }
        )


def snapshot() -> dict[str, Any]:
    with _LOCK:
        return dict(_STATE)

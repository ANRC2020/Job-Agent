"""Whether Juno can talk yet, described the way a person would describe it.

The user never needs to know about runtimes, daemons, or ports. They need to
know whether they can talk to Juno, roughly how long it'll be, and what to press
if something is stuck.
"""

from __future__ import annotations

from typing import Any

from job_agent.download_progress import snapshot as download_status
from job_agent.lmstudio import status
from job_agent.storage import database_status

# state -> (headline, what the user can do about it, which recovery action to offer)
MESSAGES: dict[str, dict[str, Any]] = {
    "ready": {
        "headline": "Juno is ready",
        "detail": "",
        "recovery": None,
    },
    "installing": {
        "headline": "Juno is still setting herself up",
        "detail": (
            "She's downloading what she needs to think locally. This happens once, and it can take "
            "a while on a slow connection. You can keep filling her in while she works."
        ),
        "recovery": "setup",
    },
    "starting": {
        "headline": "Juno is waking up",
        "detail": "This usually takes a few seconds. You can start typing — she'll answer as soon as she's up.",
        "recovery": None,
    },
    "stalled": {
        "headline": "Juno is taking longer than usual to wake up",
        "detail": "Nothing is broken on your end. I can try starting her again.",
        "recovery": "start",
    },
    "missing": {
        "headline": "Juno's local engine isn't set up yet",
        "detail": "She needs it to think on your machine instead of sending anything away. I can install it for you.",
        "recovery": "setup",
    },
}

RECOVERY_LABELS = {
    "setup": "Set Juno up",
    "start": "Start Juno",
}


def _state(raw: dict[str, Any]) -> str:
    if raw.get("ready"):
        return "ready"
    if not raw.get("cliInstalled"):
        return "missing"
    if not raw.get("modelDownloaded"):
        return "installing"
    return "starting"


def readiness(*, attempts: int = 0) -> dict[str, Any]:
    """`attempts` lets the UI escalate from patience to an offer of help."""
    raw = status()
    state = _state(raw)
    if state == "starting" and attempts >= 12:
        state = "stalled"
    message = MESSAGES[state]
    download = download_status()
    active_download = state == "installing" and bool(download.get("active"))
    recovery = None if active_download else message["recovery"]
    return {
        "state": state,
        "ready": state == "ready",
        "headline": message["headline"],
        "detail": message["detail"],
        "recovery": (
            {"action": recovery, "label": RECOVERY_LABELS[recovery]}
            if recovery
            else None
        ),
        "download": download if state == "installing" else None,
        "canTypeAhead": state in {"starting", "installing", "stalled"},
    }


def technical_status() -> dict[str, Any]:
    """The raw picture, for the one place in the app where that's appropriate."""
    raw = status()
    raw["database"] = database_status()
    return raw

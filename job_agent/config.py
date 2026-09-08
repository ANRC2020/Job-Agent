from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from job_agent.paths import repo_root
from job_agent.storage import app_data_dir

DEFAULT_MODEL = "qwen/qwen3.5-4b"
MODEL_INSTANCE_ID = "clover-juno"
RECOMMENDED_MODELS = (
    DEFAULT_MODEL,
    "qwen/qwen3.5-9b",
)


@dataclass(frozen=True)
class InstallConfig:
    model: str
    context_length: int
    install_desktop_app: bool
    mcp_server_name: str
    api_base: str
    app_port: int


def config_path():
    if getattr(sys, "frozen", False):
        return app_data_dir() / "install.json"
    return repo_root() / "config" / "install.json"


def load_raw() -> dict:
    bundled = repo_root() / "config" / "install.json"
    raw = (
        json.loads(bundled.read_text(encoding="utf-8"))
        if bundled.is_file()
        else {}
    )
    path = config_path()
    if path.is_file() and path != bundled:
        raw.update(json.loads(path.read_text(encoding="utf-8")))
    return raw


def load_config() -> InstallConfig:
    raw = load_raw()
    return InstallConfig(
        model=str(raw.get("model") or DEFAULT_MODEL),
        context_length=int(raw.get("contextLength") or 16384),
        install_desktop_app=bool(raw.get("installDesktopApp", True)),
        mcp_server_name=str(raw.get("mcpServerName") or "job-agent"),
        api_base=str(raw.get("apiBase") or "http://127.0.0.1:1234/v1"),
        app_port=int(raw.get("appPort") or 8765),
    )


def save_model(model: str) -> InstallConfig:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = load_raw()
    raw["model"] = model.strip()
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return load_config()

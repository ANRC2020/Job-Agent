from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from job_agent.config import load_config
from job_agent.paths import lmstudio_home, repo_root, system_prompt_path, venv_python


def lms_bin() -> Path | None:
    home_cli = lmstudio_home() / "bin" / ("lms.exe" if os.name == "nt" else "lms")
    if home_cli.is_file():
        return home_cli
    found = shutil.which("lms")
    return Path(found) if found else None


def desktop_installed() -> bool:
    system = platform.system()
    if system == "Darwin":
        return Path("/Applications/LM Studio.app").is_dir()
    if system == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA") or "")
        candidates = [
            local / "LM-Studio" / "LM Studio.exe",
            local / "Programs" / "LM Studio" / "LM Studio.exe",
            local / "Programs" / "LM-Studio" / "LM Studio.exe",
            local / "LM Studio" / "LM Studio.exe",
        ]
        return any(path.is_file() for path in candidates)
    return False


def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    lm_bin = str(lmstudio_home() / "bin")
    env["PATH"] = lm_bin + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        args,
        text=True,
        capture_output=True,
        env=env,
        **kwargs,
    )


def lms(*args: str) -> subprocess.CompletedProcess[str]:
    binary = lms_bin()
    if binary is None:
        raise FileNotFoundError("lms is not installed")
    return _run([str(binary), *args])


def server_reachable() -> bool:
    cfg = load_config()
    try:
        req = Request(cfg.api_base.rstrip("/") + "/models", headers={"Authorization": "Bearer lm-studio"})
        with urlopen(req, timeout=2) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except (URLError, OSError, TimeoutError):
        return False


def status() -> dict[str, Any]:
    cfg = load_config()
    binary = lms_bin()
    models: list[str] = []
    daemon = False
    loaded = False
    if binary is not None:
        listed = lms("ls")
        if listed.returncode == 0:
            models = [
                line.strip()
                for line in listed.stdout.splitlines()
                if cfg.model.split("/")[-1] in line or cfg.model in line
            ]
        daemon_out = lms("daemon", "status")
        daemon = daemon_out.returncode == 0 and "running" in (daemon_out.stdout + daemon_out.stderr).lower()
        ps = lms("ps")
        loaded = cfg.model in ps.stdout or cfg.model.split("/")[-1] in ps.stdout
    return {
        "cliInstalled": binary is not None,
        "cliPath": str(binary) if binary else None,
        "desktopInstalled": desktop_installed(),
        "model": cfg.model,
        "modelDownloaded": bool(models),
        "daemonRunning": daemon,
        "serverRunning": server_reachable(),
        "modelLoaded": loaded,
        "apiBase": cfg.api_base,
        "appPort": cfg.app_port,
        "repoRoot": str(repo_root()),
    }


def ensure_prompt_and_mcp() -> None:
    cfg = load_config()
    home = lmstudio_home()
    home.mkdir(parents=True, exist_ok=True)
    dest = home / "job-agent-system-prompt.md"
    src = system_prompt_path()
    if src.is_file():
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    bundled = venv_python()
    python = str(bundled) if bundled else (shutil.which("python3") or shutil.which("python"))
    if not python:
        return
    mcp_path = home / "mcp.json"
    data: dict[str, Any] = {"mcpServers": {}}
    if mcp_path.is_file():
        try:
            data = json.loads(mcp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"mcpServers": {}}
    data.setdefault("mcpServers", {})
    script = repo_root() / "tools" / "job_agent_mcp.py"
    data["mcpServers"][cfg.mcp_server_name] = {
        "command": python,
        "args": [str(script)],
        "env": {
            "JOB_AGENT_ROOT": str(repo_root()),
            "PYTHONPATH": str(repo_root()),
        },
    }
    mcp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


from __future__ import annotations

import platform
import shutil
import subprocess
from collections.abc import Callable

from job_agent.config import load_config
from job_agent.desktop import install_desktop
from job_agent.lmstudio import (
    desktop_installed,
    ensure_prompt_and_mcp,
    lms,
    lms_bin,
)
from job_agent.storage import initialize_database


Log = Callable[[str], None]


def _install_cli(log: Log) -> None:
    if lms_bin() is not None:
        log(f"LM Studio CLI already installed at {lms_bin()} — skipping reinstall")
        return
    log("Installing LM Studio CLI (llmster)")
    system = platform.system()
    if system == "Windows":
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "irm https://lmstudio.ai/install.ps1 | iex",
        ]
    else:
        cmd = ["bash", "-lc", "curl -fsSL https://lmstudio.ai/install.sh | bash"]
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        raise RuntimeError("LM Studio CLI install failed")
    if lms_bin() is None:
        raise RuntimeError("lms was not found after install. Open a new terminal and run job-agent setup again.")


def _install_desktop(log: Log) -> None:
    cfg = load_config()
    if not cfg.install_desktop_app:
        return
    if desktop_installed():
        log("LM Studio desktop app already installed — skipping reinstall")
        return
    system = platform.system()
    if system == "Darwin" and shutil.which("brew"):
        log("Installing LM Studio desktop app via Homebrew")
        subprocess.run(["brew", "install", "--cask", "lm-studio"], check=False)
        return
    if system == "Windows" and shutil.which("winget"):
        log("Installing LM Studio desktop app via winget")
        subprocess.run(
            [
                "winget",
                "install",
                "--id",
                "ElementLabs.LMStudio",
                "--exact",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            check=False,
        )
        return
    log("Desktop app installer not available; CLI is enough to download and serve Qwen.")


def run_setup(log: Log = print) -> None:
    cfg = load_config()
    log("Clover setup")
    database = initialize_database()
    if database["migrationsApplied"]:
        log(f"Installed local database at {database['path']}")
    else:
        log(f"Local database ready at {database['path']}")
    _install_cli(log)
    _install_desktop(log)
    if lms_bin() is None:
        raise RuntimeError("lms was not found. Open a new terminal and re-run job-agent setup.")
    log("Bootstrapping lms")
    lms("bootstrap", "-y")
    listed = lms("ls")
    if cfg.model in listed.stdout or cfg.model.split("/")[-1] in listed.stdout:
        log(f"{cfg.model} already downloaded — skipping model install")
    else:
        log(f"Downloading {cfg.model} (hardware-recommended quantization)")
        got = lms("get", cfg.model, "--yes")
        if got.returncode != 0:
            raise RuntimeError(got.stderr or got.stdout or "Model download failed")
        log((got.stdout or got.stderr).strip())
    ensure_prompt_and_mcp()
    log("Wrote system prompt and MCP config")
    install_desktop(log)
    log("Setup complete. Open Clover from Applications, the Desktop, or: job-agent launch")

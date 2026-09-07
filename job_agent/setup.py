from __future__ import annotations

import platform
import shutil
import subprocess
import time
from collections.abc import Callable

from job_agent import download_progress
from job_agent.config import load_config
from job_agent.desktop import install_desktop
from job_agent.lmstudio import (
    desktop_installed,
    ensure_prompt_and_mcp,
    lms,
    lms_bin,
    lms_stream,
)
from job_agent.storage import initialize_database


Log = Callable[[str], None]
MODEL_DOWNLOAD_ATTEMPTS = 4


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
        raise RuntimeError("LM Studio installed, but Clover could not locate its command-line service.")


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
        result = subprocess.run(["brew", "install", "--cask", "lm-studio"], check=False)
        if result.returncode != 0 or not desktop_installed():
            log("Repairing the LM Studio desktop installation")
            subprocess.run(["brew", "reinstall", "--cask", "lm-studio"], check=False)
        if not desktop_installed():
            raise RuntimeError("LM Studio's desktop app could not be installed.")
        return
    if system == "Windows" and shutil.which("winget"):
        log("Installing LM Studio desktop app via winget")
        result = subprocess.run(
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
        if result.returncode != 0 or not desktop_installed():
            raise RuntimeError("LM Studio's desktop app could not be installed with winget.")
        return
    log("Desktop app installer not available; CLI is enough to download and serve Qwen.")


def ensure_model(log: Log = print) -> None:
    cfg = load_config()
    listed = lms("ls")
    if cfg.model in listed.stdout or cfg.model.split("/")[-1] in listed.stdout:
        download_progress.finish()
        log(f"{cfg.model} already downloaded - skipping model install")
        return
    log(f"Downloading {cfg.model} (hardware-recommended quantization)")
    got = None
    for attempt in range(1, MODEL_DOWNLOAD_ATTEMPTS + 1):
        download_progress.begin(cfg.model, attempt, MODEL_DOWNLOAD_ATTEMPTS)
        if attempt > 1:
            log(
                f"Resuming model download (attempt {attempt}/{MODEL_DOWNLOAD_ATTEMPTS})"
            )
        def progress_line(line: str) -> None:
            download_progress.consume(line)
            if log is print:
                print(f"\r{line}", end="", flush=True)

        try:
            got = lms_stream(
                "get",
                cfg.model,
                "--yes",
                on_output=progress_line,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            got = subprocess.CompletedProcess(
                args=["lms", "get", cfg.model],
                returncode=124,
                stdout="",
                stderr="Model download timed out.",
            )
        if got.returncode == 0:
            break
        if attempt < MODEL_DOWNLOAD_ATTEMPTS:
            log("The download was interrupted. Clover will resume it automatically.")
            time.sleep(min(30, attempt * 5))
    if got is None or got.returncode != 0:
        message = (
            (got.stderr if got else "")
            or (got.stdout if got else "")
            or "Model download failed after four resumable attempts"
        )
        download_progress.fail(message)
        raise RuntimeError(message)
    download_progress.finish()
    output = (got.stdout or got.stderr or "").strip()
    if output:
        log(output)


def run_setup(log: Log = print, *, download_model: bool = True) -> None:
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
        raise RuntimeError("Clover could not locate LM Studio's command-line service.")
    log("Bootstrapping lms")
    bootstrapped = lms("bootstrap", "-y")
    if bootstrapped.returncode != 0:
        raise RuntimeError(
            bootstrapped.stderr or bootstrapped.stdout or "LM Studio bootstrap failed"
        )
    if download_model:
        ensure_model(log)
    else:
        log("Juno's model will finish downloading after Clover opens.")
    ensure_prompt_and_mcp()
    log("Wrote system prompt and MCP config")
    install_desktop(log)
    log("Setup complete. Open Clover from Applications, the Desktop, or: job-agent launch")

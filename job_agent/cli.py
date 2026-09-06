from __future__ import annotations

import argparse
import json

from job_agent import __version__
from job_agent.app import serve
from job_agent.chat import complete
from job_agent.config import load_config
from job_agent.desktop import install_desktop, launch_desktop
from job_agent.lmstudio import status
from job_agent.runtime import start_runtime, stop_runtime
from job_agent.setup import run_setup
from job_agent.storage import database_status, initialize_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="job-agent",
        description="Clover CLI and desktop app.",
    )
    parser.add_argument("--version", action="version", version=f"job-agent {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    app_p = sub.add_parser("app", help="Open the Clover desktop window")
    app_p.add_argument("--port", type=int, default=None)
    app_p.add_argument("--no-window", action="store_true", help="Do not open a window (keep the server only)")
    app_p.add_argument("--no-runtime", action="store_true", help="Do not start or stop LM Studio")

    sub.add_parser("setup", help="Install or reuse LM Studio, Qwen, prompts, tools, and the desktop app")
    sub.add_parser("install-desktop", help="Install Clover to Applications / Desktop")
    sub.add_parser("launch", help="Open the installed Clover desktop app")
    sub.add_parser("start", help="Start the LM Studio daemon, load Qwen, and serve the API")
    sub.add_parser("stop", help="Unload Qwen and stop the LM Studio server/daemon")
    sub.add_parser("status", help="Show LM Studio, model, and server status")

    chat_p = sub.add_parser("chat", help="Chat with Qwen in the terminal")
    chat_p.add_argument("prompt", nargs="*", help="Optional one-shot prompt")

    args = parser.parse_args(argv)
    cmd = args.cmd or "app"

    if cmd == "setup":
        run_setup()
        return 0
    if cmd == "install-desktop":
        install_desktop()
        return 0
    if cmd == "launch":
        launch_desktop()
        return 0
    if cmd == "start":
        start_runtime()
        return 0
    if cmd == "stop":
        stop_runtime(full_shutdown=True)
        return 0
    if cmd == "status":
        initialize_database()
        result = status()
        result["database"] = database_status()
        print(json.dumps(result, indent=2))
        return 0
    if cmd == "chat":
        prompt = " ".join(getattr(args, "prompt", [])).strip()
        if prompt:
            result = complete([{"role": "user", "content": prompt}])
            if result["tools"]:
                for item in result["tools"]:
                    print(f"[tool:{item['tool']}]")
            print(result["content"])
            return 0
        print(f"Juno in Clover ({load_config().model})")
        print("Type a message, or /exit.")
        history: list[dict[str, str]] = []
        while True:
            try:
                line = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line or line in {"/exit", "/quit"}:
                return 0
            history.append({"role": "user", "content": line})
            result = complete(history)
            history.append({"role": "assistant", "content": result["content"]})
            print(f"Juno> {result['content']}")
        return 0
    if cmd == "app":
        serve(
            port=getattr(args, "port", None),
            open_browser=not getattr(args, "no_window", False),
            manage_runtime=not getattr(args, "no_runtime", False),
        )
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

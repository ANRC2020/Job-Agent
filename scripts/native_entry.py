"""Entry point used by PyInstaller for native Clover distributions."""

import os

from job_agent.launcher import main
from job_agent.paths import system_prompt_path
from job_agent.storage import initialize_database


def native_smoke_test() -> int:
    """Verify resources and writable local storage without starting LM Studio."""
    prompt = system_prompt_path()
    if not prompt.is_file():
        raise FileNotFoundError(f"Bundled system prompt is missing: {prompt}")
    result = initialize_database()
    if not result.get("path"):
        raise RuntimeError("Clover could not initialize its local database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(
        native_smoke_test()
        if os.environ.get("CLOVER_NATIVE_SMOKE_TEST") == "1"
        else main()
    )

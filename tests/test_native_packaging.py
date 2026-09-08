from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_agent.config import config_path, load_config, save_model
from job_agent.lmstudio import ensure_prompt_and_mcp
from job_agent.paths import repo_root, system_prompt_path


class FrozenRuntimeTests(unittest.TestCase):
    def test_frozen_resources_are_resolved_from_pyinstaller_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as bundle:
            prompt = Path(bundle) / "prompts" / "system.md"
            prompt.parent.mkdir()
            prompt.write_text("You are Juno.", encoding="utf-8")
            with patch.object(sys, "_MEIPASS", bundle, create=True):
                self.assertEqual(Path(bundle), repo_root())
                self.assertEqual(prompt, system_prompt_path())

    def test_frozen_model_selection_is_written_to_personal_data(self) -> None:
        with tempfile.TemporaryDirectory() as bundle, tempfile.TemporaryDirectory() as data:
            bundled = Path(bundle) / "config" / "install.json"
            bundled.parent.mkdir()
            bundled.write_text(
                json.dumps({"model": "qwen/qwen3.5-4b", "contextLength": 16384}),
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": data}),
                patch.object(sys, "_MEIPASS", bundle, create=True),
                patch.object(sys, "frozen", True, create=True),
            ):
                self.assertEqual((Path(data) / "install.json").resolve(), config_path())
                self.assertEqual("qwen/qwen3.5-4b", load_config().model)
                self.assertEqual("qwen/qwen3.5-9b", save_model("qwen/qwen3.5-9b").model)
                self.assertEqual(
                    "qwen/qwen3.5-9b",
                    json.loads((Path(data) / "install.json").read_text())["model"],
                )
                self.assertEqual(
                    "qwen/qwen3.5-4b",
                    json.loads(bundled.read_text())["model"],
                )

    def test_frozen_setup_copies_prompt_without_registering_temporary_mcp_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "system.md"
            source.write_text("You are Juno.", encoding="utf-8")
            lm_home = root / "lmstudio"
            with (
                patch.object(sys, "frozen", True, create=True),
                patch("job_agent.lmstudio.lmstudio_home", return_value=lm_home),
                patch("job_agent.lmstudio.system_prompt_path", return_value=source),
                patch("job_agent.lmstudio.venv_python") as runtime_python,
            ):
                ensure_prompt_and_mcp()

            self.assertEqual(
                "You are Juno.",
                (lm_home / "job-agent-system-prompt.md").read_text(),
            )
            self.assertFalse((lm_home / "mcp.json").exists())
            runtime_python.assert_not_called()


if __name__ == "__main__":
    unittest.main()

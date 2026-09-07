from __future__ import annotations

import unittest
from unittest.mock import patch

from job_agent.config import load_config


class ConfigTests(unittest.TestCase):
    @patch("job_agent.config.load_raw", return_value={})
    def test_fast_model_is_the_default(self, _raw) -> None:
        self.assertEqual("qwen/qwen3.5-4b", load_config().model)


if __name__ == "__main__":
    unittest.main()

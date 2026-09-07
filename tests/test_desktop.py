from __future__ import annotations

import unittest

from job_agent.desktop import _powershell_literal


class WindowsDesktopTests(unittest.TestCase):
    def test_powershell_paths_keep_single_backslashes_and_escape_quotes(self) -> None:
        self.assertEqual(
            "'C:\\Users\\O''Brien\\Clover'",
            _powershell_literal("C:\\Users\\O'Brien\\Clover"),
        )


if __name__ == "__main__":
    unittest.main()

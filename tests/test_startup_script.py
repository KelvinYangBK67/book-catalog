from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = (ROOT / "start_library.bat").read_text(encoding="utf-8")


class StartupScriptTests(unittest.TestCase):
    def test_local_server_reloads_python_changes(self) -> None:
        command = next(
            line for line in START_SCRIPT.splitlines()
            if "-m uvicorn app.main:app" in line
        )
        self.assertIn("--reload", command)
        self.assertIn("--reload-dir app", command)
        self.assertIn("--host 127.0.0.1", command)
        self.assertIn("--port %LIBRARY_PORT%", command)


if __name__ == "__main__":
    unittest.main()

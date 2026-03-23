from __future__ import annotations
from unittest.mock import patch
from cli_ai_runner.adapters.gemini import GeminiAdapter

def test_gemini_adapter_resolve_cmd():
    adapter = GeminiAdapter()
    with patch("cli_ai_runner.adapters.gemini.resolve_command", return_value=["C:\\bin\\gemini.cmd"]):
        cmd = adapter.resolve_cmd()
        assert cmd == ["C:\\bin\\gemini.cmd"]

def test_gemini_adapter_is_installed():
    adapter = GeminiAdapter()
    with patch("cli_ai_runner.adapters.gemini.resolve_command", return_value=["gemini"]):
        with patch("cli_ai_runner.adapters.gemini.shutil.which", return_value="C:\\bin\\gemini"):
            assert adapter.is_installed() is True

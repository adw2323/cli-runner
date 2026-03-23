from __future__ import annotations
from unittest.mock import patch
from cli_runner.adapters.claude import ClaudeAdapter

def test_claude_adapter_resolve_cmd():
    adapter = ClaudeAdapter()
    with patch("cli_runner.adapters.claude.resolve_command", return_value=["C:\\bin\\claude.cmd"]):
        cmd = adapter.resolve_cmd()
        assert cmd == ["C:\\bin\\claude.cmd"]

def test_claude_adapter_is_installed():
    adapter = ClaudeAdapter()
    with patch("cli_runner.adapters.claude.resolve_command", return_value=["claude"]):
        with patch("cli_runner.adapters.claude.shutil.which", return_value="C:\\bin\\claude"):
            assert adapter.is_installed() is True

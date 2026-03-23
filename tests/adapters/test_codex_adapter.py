from __future__ import annotations
import os
from unittest.mock import patch
from cli_ai_runner.adapters.codex import CodexAdapter

def test_codex_adapter_resolve_cmd_default():
    adapter = CodexAdapter()
    with patch("cli_ai_runner.adapters.codex.resolve_command", return_value=["C:\\bin\\codex.cmd"]):
        with patch("cli_ai_runner.adapters.codex.shutil.which", return_value="C:\\bin\\codex.cmd"):
            cmd = adapter.resolve_cmd()
            assert cmd == ["C:\\bin\\codex.cmd", "exec"]

def test_codex_adapter_resolve_cmd_env_override(monkeypatch):
    monkeypatch.setenv("CODEX_RUNNER_CMD", "custom-codex")
    adapter = CodexAdapter()
    with patch("cli_ai_runner.adapters.codex.resolve_command", return_value=["C:\\bin\\custom-codex"]):
        cmd = adapter.resolve_cmd()
        assert cmd == ["C:\\bin\\custom-codex"]

def test_codex_adapter_build_invocation():
    adapter = CodexAdapter()
    spec = adapter.build_invocation("hello", ["codex", "exec"])
    assert spec.argv == ["codex", "exec", "hello"]

def test_codex_adapter_install_dry_run(capsys):
    adapter = CodexAdapter()
    assert adapter.install(dry_run=True) is True
    captured = capsys.readouterr()
    assert "Would run: npm install -g @openai/codex" in captured.out

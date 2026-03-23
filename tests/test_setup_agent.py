from __future__ import annotations
from unittest.mock import patch, MagicMock
from cli_ai_runner.setup_agent import run_setup, run_status

def test_run_status_output(capsys):
    with patch("cli_ai_runner.setup_agent.get_adapter") as mock_get:
        mock_adapter = MagicMock()
        mock_adapter.is_installed.return_value = True
        mock_adapter.resolve_cmd.return_value = ["C:\\bin\\agent.exe"]
        mock_get.return_value = mock_adapter
        
        assert run_status() == 0
        captured = capsys.readouterr()
        assert "[FOUND]" in captured.out
        assert "C:\\bin\\agent.exe" in captured.out

def test_run_setup_already_installed(capsys):
    with patch("cli_ai_runner.setup_agent.get_adapter") as mock_get:
        mock_adapter = MagicMock()
        mock_adapter.is_installed.return_value = True
        mock_get.return_value = mock_adapter
        
        assert run_setup(agent_name="codex") == 0
        captured = capsys.readouterr()
        assert "Agent 'codex' is already installed." in captured.out

def test_run_setup_dry_run(capsys):
    with patch("cli_ai_runner.setup_agent.get_adapter") as mock_get:
        mock_adapter = MagicMock()
        mock_adapter.is_installed.return_value = False
        mock_adapter.install.return_value = True
        mock_get.return_value = mock_adapter
        
        assert run_setup(agent_name="gemini", dry_run=True) == 0
        mock_adapter.install.assert_called_once_with(dry_run=True)

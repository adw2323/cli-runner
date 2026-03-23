from __future__ import annotations

import os

import pytest

from cli_ai_runner import utils
from cli_ai_runner.utils import resolve_command as _resolve_command


def test_resolve_command_uses_shutil_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cli_ai_runner.utils.shutil.which", lambda program: "C:\\x\\tool.cmd")
    resolved = _resolve_command(["tool", "--x"])
    assert resolved[0] == "C:\\x\\tool.cmd"
    assert resolved[1:] == ["--x"]


@pytest.mark.skipif(os.name != "nt", reason="Windows extension fallback")
def test_resolve_command_windows_extension_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_which(program: str) -> str | None:
        calls.append(program)
        if program.lower().endswith("tool.cmd"):
            return "C:\\tools\\tool.cmd"
        return None

    monkeypatch.setattr("cli_ai_runner.utils.shutil.which", fake_which)
    resolved = _resolve_command(["tool"])
    assert resolved[0].lower().endswith("tool.cmd")
    assert any(item.lower().endswith("tool.cmd") for item in calls)


@pytest.mark.skipif(os.name != "nt", reason="Windows dotted command lookup")
def test_resolve_command_windows_dotted_command_uses_direct_which(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(program: str) -> str | None:
        if program.lower() == "codex.exe":
            return "C:\\Users\\andrew.walsh\\AppData\\Roaming\\npm\\codex.exe"
        return None

    monkeypatch.setattr("cli_ai_runner.utils.shutil.which", fake_which)
    resolved = _resolve_command(["codex.exe", "exec"])
    assert resolved[0].lower().endswith("codex.exe")
    assert resolved[1:] == ["exec"]


@pytest.mark.skipif(os.name != "nt", reason="Windows extension preference")
def test_resolve_command_windows_prefers_cmd_over_extensionless_and_exe(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(program: str) -> str | None:
        mapping = {
            "codex": "C:\\Users\\andrew.walsh\\AppData\\Roaming\\npm\\codex",
            "codex.cmd": "C:\\Users\\andrew.walsh\\AppData\\Roaming\\npm\\codex.cmd",
            "codex.exe": "C:\\Users\\andrew.walsh\\AppData\\Roaming\\npm\\codex.exe",
        }
        return mapping.get(program.lower())

    monkeypatch.setattr("cli_ai_runner.utils.shutil.which", fake_which)
    resolved = _resolve_command(["codex", "exec"])
    assert resolved[0].lower().endswith("codex.cmd")
    assert resolved[1:] == ["exec"]


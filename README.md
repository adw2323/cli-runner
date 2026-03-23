# CLI Runner

Deterministic Codex runner for multi-loop project execution.

## What It Does
- Runs `codex exec` in a loop.
- Injects and parses `RUN_STATUS:DONE|CONTINUE|REWORK`.
- Streams live subprocess output.
- Uses strict completion checks by default before accepting `DONE`.
- Supports Windows command resolution fallback (`.cmd` preferred).

## Install
```powershell
cd C:\cli-runner
python -m pip install -e .[dev]
```

## Run
```powershell
cli-runner "continue working on the project"
```

Or:
```powershell
codex-runner "continue working on the project"
```

## Key Options
- `--max-loops` (default `50`, or `RUNNER_MAX_LOOPS`)
- `--strict-completion` / `--no-strict-completion` (default on, or `RUNNER_STRICT_COMPLETION`)
- `--codex-cmd` (default `codex exec`, or `CODEX_RUNNER_CMD`)

## Test
```powershell
python -m pytest
```

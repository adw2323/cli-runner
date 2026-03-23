# Architecture (CLI Runner)

## System Intent
This application is a deterministic CLI runner for Codex project execution loops.

It controls loop lifecycle and completion gating. It does not implement strategy routing or a GUI.

## Core Components
- `runner.py`: loop execution, status parsing, strict completion gate.
- `broker/engine.py`: shared output parsing/state helpers and command resolution.
- `broker/models.py`: run-state model primitives.
- `main.py`: CLI entrypoint and argument parsing.

## Runtime Responsibilities
- launch Codex (`codex exec`) and stream output,
- detect run status (`RUN_STATUS:DONE|CONTINUE|REWORK`) from explicit lines,
- enforce strict completion verification (roadmap/todo/validation checklist) before accepting `DONE`,
- continue with bounded loop caps (`--max-loops`),
- surface deterministic final result and exit code.

## Out of Scope
- GUI/operator console,
- multi-agent delegation control plane,
- autonomous planning beyond explicit loop prompts.

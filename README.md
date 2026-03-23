# cli-runner

Agent-agnostic CLI runner with deterministic loop control and status gating for Codex, Gemini, and Claude.

## Features

- **Multi-Agent Support:** Built-in adapters for `codex`, `gemini`, and `claude`.
- **Deterministic Loop Control:** Automatically continues or reworks tasks based on agent output (`RUN_STATUS:DONE|CONTINUE|REWORK`).
- **Strict Completion Gating:** Before accepting `DONE`, verifies work against roadmaps, todos, and tests.
- **Windows-First:** Robust command resolution for `.cmd`, `.bat`, and `.exe` on Windows.
- **Auto-Setup:** Built-in `status` and `setup` commands to detect and install missing agent CLIs.
- **Memory-First:** Integrated with Codex Memory (Azure) for session tracking and persistence.

## Quick Start

### 1. Install

```powershell
pip install cli-runner
```

### 2. Check Status

Detect installed agents and their paths:

```powershell
cli-runner status
```

### 3. Setup Agents

Install missing agents automatically:

```powershell
cli-runner setup --agent all
```

### 4. Run a Task

Run a task loop using your preferred agent:

```powershell
# Default (Codex)
cli-runner "implement the user authentication module"

# Using Claude
cli-runner --agent claude "refactor the data layer"

# Using Gemini
cli-runner --agent gemini "add unit tests for the broker"
```

## CLI Reference

### Commands

- `cli-runner status`: Print detected agents and their versions.
- `cli-runner setup`: Detect and install missing agents.
  - `--agent {all,codex,gemini,claude}` (default: `all`)
  - `--yes`, `-y`: Skip confirmation.
  - `--dry-run`: Show commands without running them.
- `cli-runner run` (or just `cli-runner`): Run a task loop.
  - `--agent {codex,gemini,claude}` (default: `codex`)
  - `--max-loops N`: Maximum number of loops (default: 50).
  - `--strict-completion` / `--no-strict-completion`: Require a verification pass before `DONE`.

## Environment Variables

- `RUNNER_MAX_LOOPS`: Default loop cap.
- `RUNNER_STRICT_COMPLETION`: Toggle strict completion gating (1/0).
- `CODEXMEM_ENABLED`: Toggle Codex Memory bridge (1/0).
- `CODEXMEM_REPO_ID`: Current repository identifier for memory logging.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ROADMAP.md](docs/ROADMAP.md) for project details.

## License

MIT

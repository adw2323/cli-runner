# cli-runner User Guide

`cli-runner` is a powerful, deterministic task execution engine designed to manage the lifecycle of agentic CLI workflows. It transforms unpredictable AI outputs into stable, repeatable project progression.

## Core Concepts

### The Deterministic Loop
Unlike raw CLI tools, `cli-runner` expects agents to communicate their status. By looking for the `RUN_STATUS` token, the runner decides whether to finish, continue, or rework a task.

- **DONE:** Task objective met. The loop exits with code 0.
- **CONTINUE:** More work is needed. The runner automatically re-prompts the agent to pick up where it left off.
- **REWORK:** The agent is stuck or off-track. The runner attempts a recovery or exits with an error code for manual intervention.

### Strict Completion Gating
When `--strict-completion` is enabled (default), `cli-runner` won't trust a `DONE` signal immediately. It will first force the agent into a "Verification Phase" where it must check:
1.  **Planning Docs:** README, ROADMAP, TODO, etc.
2.  **Validations:** Test suites and linting.
3.  **Checklist:** A structured summary of remaining work.

## Detailed Command Usage

### 1. `run` (Standard Tasking)
Execute a task loop using a specific agent.

```powershell
cli-runner run "Implement the checkout logic" --agent claude --max-loops 10
```

- `--agent`: Choose from `codex`, `gemini`, or `claude`.
- `--max-loops`: Safeguard against infinite loops. Default is 50.
- `--no-strict-completion`: Skip the verification gate for faster, less critical tasks.

### 2. `status` (Environment Health)
Verify which agent CLIs are correctly installed and detected on your system.

```powershell
cli-runner status
```

### 3. `setup` (Automated Provisioning)
Install the required agent CLIs automatically via NPM.

```powershell
# Install everything missing
cli-runner setup

# Dry run to see the npm commands
cli-runner setup --agent claude --dry-run
```

## Advanced Configuration

### Environment Variables
You can customize behavior without CLI flags:

| Variable | Description | Default |
| -------- | ----------- | ------- |
| `RUNNER_MAX_LOOPS` | Max iterations per task | `50` |
| `RUNNER_STRICT_COMPLETION` | Toggle strict gating | `True` |

### Custom Codex Commands
If you use a specific wrapper for Codex, use `CODEX_RUNNER_CMD`:
```powershell
$env:CODEX_RUNNER_CMD = "my-special-codex exec --flag"
cli-runner "task"
```

## Troubleshooting

### Agent "Missing" but installed
If `cli-runner status` shows an agent as missing but you can run it manually:
1. Ensure the binary is in your system `PATH`.
2. On Windows, `cli-runner` prefers `.cmd` or `.bat` wrappers. Check if you have those available.
3. Try restarting your terminal after running `cli-runner setup`.

### Loop Limit Reached
If a task hits the loop limit, it exits with **code 3**. This usually means the task was too large. Break the task into smaller sub-tasks and run them sequentially.

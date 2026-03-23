# cli-runner

**The Deterministic Task Execution Engine for Agentic CLIs.**

`cli-runner` provides a professional, stable wrapper for running AI agents like Codex, Claude, and Gemini in automated loops. It solves the "completion problem" by enforcing a structured protocol between the human, the runner, and the AI.

---

## 🚀 Why cli-runner?

*   **Deterministic Control:** Stop guessing if an agent finished. Rely on explicit `RUN_STATUS` signals.
*   **Multi-Agent Support:** Swappable adapters for the industry's leading agentic CLIs.
*   **Strict Completion Gating:** Automated verification against your project's Roadmap and Test suites before claiming victory.
*   **Windows-First Reliability:** Deep integration with Windows command resolution and PTY handling.

---

## 🛠 Installation

`cli-runner` is distributed via PyPI and requires Python 3.11+.

```powershell
pip install cli-runner
```

---

## 🏁 Quick Start

### 1. Check your environment
See which agents are ready to work:
```powershell
cli-runner status
```

### 2. Setup missing agents
Automatically provision the necessary agent CLIs:
```powershell
cli-runner setup --yes
```

### 3. Run a project task
Execute a task with automatic continuation and verification:
```powershell
cli-runner "Implement the login module and add unit tests" --agent claude
```

---

## 📖 Documentation

*   **[User Guide](docs/USER_GUIDE.md):** Detailed command references, environment variables, and troubleshooting.
*   **[Architecture](docs/ARCHITECTURE.md):** Deep dive into the adapter pattern and deterministic loop logic.
*   **[Roadmap](docs/ROADMAP.md):** Future plans for multi-agent orchestration and cross-platform support.

---

## ⌨️ CLI Command Reference

| Command | Usage | Description |
| ------- | ----- | ----------- |
| `run` | `cli-runner run "task" [options]` | **Primary command.** Starts a task loop. |
| `status` | `cli-runner status` | Lists detected agents and their binary paths. |
| `setup` | `cli-runner setup [--agent X]` | Installs missing agent binaries via NPM. |

### Global Options for `run`:
- `--agent {codex,gemini,claude}`: Which adapter to use. (Default: `codex`)
- `--max-loops N`: Exit after N iterations to prevent runaway costs. (Default: `50`)
- `--no-strict-completion`: Disable the mandatory verification pass.

---

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for local development setup and testing guidelines.

## ⚖️ License

Distributed under the **MIT License**. See `LICENSE` for more information.

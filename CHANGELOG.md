# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-03-23

### Added
- Agent-agnostic adapter architecture in `src/cli_runner/adapters/`.
- Built-in adapters for `codex`, `gemini`, and `claude`.
- `cli-runner status` command for agent detection.
- `cli-runner setup` command for automated agent CLI installation.
- GitHub Actions CI for Windows with Python 3.11/3.12.
- PyPI release workflow using trusted publishers (OIDC).

### Changed
- Renamed project from `cli-orchestrator-ui` to `cli-runner`.
- Simplified core execution loop in `runner.py`.
- Replaced hardcoded `codex exec` with dynamic adapter invocations.
- Moved utility functions to `src/cli_runner/utils.py`.

### Deprecated
- `--codex-cmd` is now deprecated in favor of `--agent codex`.

### Removed
- Legacy async `BrokerEngine` and its associated PTY/ANSI complexity.
- Unused legacy test suites.

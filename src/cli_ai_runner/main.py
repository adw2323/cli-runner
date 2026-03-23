from __future__ import annotations

import argparse
import os
import sys

from cli_ai_runner.adapters import get_adapter
from cli_ai_runner.runner import run_task_loop


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


from cli_ai_runner.setup_agent import run_setup, run_status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent-agnostic CLI runner with loop control.")
    subparsers = parser.add_subparsers(dest="command")

    # Status subcommand
    subparsers.add_parser("status", help="Print detected agents and their versions.")

    # Setup subcommand
    setup_parser = subparsers.add_parser("setup", help="Detect and install missing agents.")
    setup_parser.add_argument("--agent", choices=["all", "codex", "gemini", "claude"], default="all")
    setup_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation.")
    setup_parser.add_argument("--dry-run", action="store_true", help="Show commands without running them.")

    # Main runner (default or explicit run)
    run_parser = subparsers.add_parser("run", help="Run a task loop.")
    run_parser.add_argument("--max-loops", type=int, default=int(os.environ.get("RUNNER_MAX_LOOPS", "50")))
    run_parser.add_argument("--codex-cmd", default=None, help="[deprecated] Use --agent instead.")
    run_parser.add_argument("--agent", choices=["codex", "gemini", "claude"], default="codex", help="Agent adapter to use")
    run_parser.add_argument(
        "--strict-completion",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("RUNNER_STRICT_COMPLETION", True),
        help="Require a completion verification pass before accepting RUN_STATUS:DONE.",
    )
    run_parser.add_argument("task", nargs="*", help="Task text for CLI wrapper mode.")

    # Fallback to 'run' if no subcommand provided (backward compatibility)
    parser.set_defaults(command="run")
    
    # We also want to support 'cli-ai-runner "task text"' directly without 'run'
    # This is tricky with subparsers, so we'll handle it in main()
    return parser


def main() -> int:
    # Special handling for legacy/simple usage: cli-ai-runner "task text"
    # If the first argument isn't a known command, assume it's a task.
    raw_args = sys.argv[1:]
    known_cmds = {"run", "setup", "status", "-h", "--help", "--version"}
    if raw_args and raw_args[0] not in known_cmds and not raw_args[0].startswith("-"):
        sys.argv.insert(1, "run")

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "status":
        return run_status()

    if args.command == "setup":
        return run_setup(agent_name=args.agent, yes=args.yes, dry_run=args.dry_run)

    if args.command == "run":
        if args.codex_cmd is not None:
            print("[deprecated] --codex-cmd is superseded by --agent codex. Use --agent codex to configure the Codex adapter.", file=sys.stderr)

        task_text = " ".join(args.task).strip()
        if not task_text:
            piped = sys.stdin.read().strip()
            task_text = piped
        if not task_text:
            print("Task text is required in CLI wrapper mode.", file=sys.stderr)
            return 1

        adapter = get_adapter(args.agent)

        try:
            result = run_task_loop(
                task_text=task_text,
                adapter=adapter,
                max_loops=args.max_loops,
                strict_completion=args.strict_completion,
            )
        except KeyboardInterrupt:
            return 130
        print(f"[runner] status={result.status} loops={result.loops}")
        return result.return_code
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

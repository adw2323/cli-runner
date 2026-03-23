from __future__ import annotations

import argparse
import os
import sys

from cli_runner.adapters import get_adapter
from cli_runner.runner import run_task_loop


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI runner wrapper.")
    parser.add_argument("--max-loops", type=int, default=int(os.environ.get("RUNNER_MAX_LOOPS", "50")))
    parser.add_argument("--codex-cmd", default=None, help="[deprecated] Use --agent instead.")
    parser.add_argument("--agent", choices=["codex", "gemini", "claude"], default="codex", help="Agent adapter to use")
    parser.add_argument(
        "--strict-completion",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("RUNNER_STRICT_COMPLETION", True),
        help="Require a completion verification pass before accepting RUN_STATUS:DONE.",
    )
    parser.add_argument("task", nargs="*", help="Task text for CLI wrapper mode.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

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


if __name__ == "__main__":
    raise SystemExit(main())

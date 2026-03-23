from __future__ import annotations

import argparse
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["done", "continue", "resume", "tty", "stderr"], required=True)
    args = parser.parse_args()

    if args.mode == "done":
        line = sys.stdin.readline()
        print(f"received: {line.strip()}", flush=True)
        print("processing complete", flush=True)
        return 0

    if args.mode == "continue":
        first = sys.stdin.readline()
        print(f"received: {first.strip()}", flush=True)
        print("waiting for input", flush=True)
        while True:
            nxt = sys.stdin.readline()
            if not nxt:
                return 1
            if nxt.strip().lower().startswith("continue"):
                print("completed", flush=True)
                return 0

    if args.mode == "resume":
        print("resumed session", flush=True)
        time.sleep(0.05)
        print("completed", flush=True)
        return 0

    if args.mode == "tty":
        if not sys.stdin.isatty():
            print("stdin is not a terminal", file=sys.stderr, flush=True)
            return 2
        print("tty ok", flush=True)
        return 0

    if args.mode == "stderr":
        _ = sys.stdin.readline()
        print("critical error in stderr stream", file=sys.stderr, flush=True)
        return 3

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI parser and dispatch entrypoint for Jarvis client simulation sessions."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure package root is in sys.path when invoked directly
_pkg_root = str(Path(__file__).resolve().parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from src.client import run_chat_and_context_script, run_scenario
from src.constants import DEFAULT_BASE_URL
from src.scenarios import (
    ALL_SCENARIOS,
    CHAT_SCENARIOS,
    build_chat_script,
    build_scenario,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send simulated Jarvis context events and user commands to a local backend.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scenario",
        default="morning-commute",
        help="Scenario to run (default: morning-commute). Use --list-scenarios to see all.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("JARVIS_BASE_URL", DEFAULT_BASE_URL),
        help=f"Jarvis API URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated request payloads without sending HTTP requests",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="Delay between requests (chat scenarios enforce >= 2.1s to respect rate limits)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="HTTP timeout per request in seconds",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available simulation scenarios with descriptions",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_scenarios:
        print("Available Jarvis Simulation Sessions:\n" + "=" * 60)
        for name, desc in ALL_SCENARIOS:
            print(f"  {name:<22} {desc}")
        return 0

    if args.scenario in CHAT_SCENARIOS:
        try:
            steps = build_chat_script(args.scenario)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        return run_chat_and_context_script(
            steps,
            base_url=args.base_url,
            dry_run=args.dry_run,
            delay_seconds=args.delay_seconds,
            timeout_seconds=args.timeout_seconds,
        )

    try:
        events = build_scenario(args.scenario)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    return run_scenario(
        events,
        base_url=args.base_url,
        dry_run=args.dry_run,
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())

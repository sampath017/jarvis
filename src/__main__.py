"""
Jarvis Simulation — CLI Entry Point

Usage:
    uv run python -m src                       # Run all scenarios
    uv run python -m src --scenario 4          # Run specific scenario
    uv run python -m src --live                # Use live OpenRouter API
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .eval_report import generate_report
from .eval_runner import run_all_scenarios, run_scenario, save_results
from .scenarios import build_all_scenarios


def main() -> None:
    # Force UTF-8 output on Windows
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    parser = argparse.ArgumentParser(
        description="Jarvis Context-Aware Mobile Agent - End-to-End Simulation"
    )
    parser.add_argument(
        "--scenario", type=int, default=None,
        help="Run a specific scenario by ID (1-12). Default: run all."
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Use live OpenRouter API instead of mock mode."
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Directory to save eval results and report."
    )
    args = parser.parse_args()

    use_mock = not args.live
    output_dir = Path(args.output_dir) if args.output_dir else Path("eval_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    mode_str = "LIVE (OpenRouter)" if args.live else "MOCK (rule-based)"
    print(f"\n{'='*70}")
    print(f"  Jarvis Context-Aware Mobile Agent - End-to-End Simulation")
    print(f"  Mode: {mode_str}")
    print(f"{'='*70}\n")

    if args.scenario:
        scenarios = build_all_scenarios()
        target = next((s for s in scenarios if s.scenario_id == args.scenario), None)
        if not target:
            print(f"[FAIL] Scenario {args.scenario} not found. Valid: 1-12")
            sys.exit(1)
        print(f"Running scenario {args.scenario}: {target.name}")
        result = run_scenario(target, use_mock=use_mock)
        results = [result]
    else:
        print(f"Running all 12 scenarios...\n")
        results = run_all_scenarios(use_mock=use_mock)

    # Print quick summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n{'-'*70}")
    print(f"Quick Summary: {passed}/{total} passed\n")

    for r in results:
        emoji = "[PASS]" if r.passed else "[FAIL]"
        latency = f"{r.pipeline_result.total_latency_ms:.1f}ms" if r.pipeline_result else "N/A"
        print(f"  {emoji} [{r.scenario_id:2d}] {r.scenario_name:<45} {latency}")

        # Show failed checks
        if not r.passed:
            for check, val in r.checks.items():
                if not val:
                    print(f"       [FAIL] {check}")

    print(f"\n{'-'*70}")

    # Generate full report
    report = generate_report(results, output_dir=output_dir)
    save_results(results, output_dir=output_dir)

    print(f"\nFull report saved to: {output_dir / 'eval_report.md'}")
    print(f"Results JSON saved to: {output_dir / 'eval_results.json'}")
    print(f"\n{'='*70}\n")

    # Print the full report
    print(report)

    # Exit with non-zero if any scenario failed
    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()

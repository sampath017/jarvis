"""
Evaluation Report Generator

Produces a human-readable eval summary with metrics, per-scenario results,
confidence distributions, and pass/fail breakdown.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .config import EVAL_REPORT_FILE
from .models.schemas import ScenarioResult


def generate_report(
    results: list[ScenarioResult],
    output_dir: Path | None = None,
) -> str:
    """Generate a Markdown evaluation report and optionally save to file."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    pass_rate = (passed / total * 100) if total > 0 else 0

    lines: list[str] = []
    lines.append("# Jarvis Simulation — Evaluation Report")
    lines.append("")
    lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Mode**: Mock LLM (rule-based)")
    lines.append("")

    # ── Overall Summary ──────────────────────────────────────────────────
    lines.append("## Overall Summary")
    lines.append("")
    status_emoji = "✅" if failed == 0 else "⚠️"
    lines.append(f"{status_emoji} **{passed}/{total} scenarios passed** ({pass_rate:.0f}%)")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total Scenarios | {total} |")
    lines.append(f"| Passed | {passed} |")
    lines.append(f"| Failed | {failed} |")
    lines.append(f"| Pass Rate | {pass_rate:.1f}% |")
    lines.append("")

    # ── Per-Scenario Results ─────────────────────────────────────────────
    lines.append("## Per-Scenario Results")
    lines.append("")
    lines.append("| # | Scenario | Status | Checks | Latency |")
    lines.append("|---|----------|--------|--------|---------|")

    for r in results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        total_checks = len(r.checks)
        passed_checks = sum(1 for v in r.checks.values() if v)
        latency = f"{r.pipeline_result.total_latency_ms:.1f}ms" if r.pipeline_result else "N/A"
        lines.append(
            f"| {r.scenario_id} | {r.scenario_name} | {status} | "
            f"{passed_checks}/{total_checks} | {latency} |"
        )

    lines.append("")

    # ── Detailed Check Results ───────────────────────────────────────────
    lines.append("## Detailed Check Results")
    lines.append("")

    for r in results:
        emoji = "✅" if r.passed else "❌"
        lines.append(f"### {emoji} Scenario {r.scenario_id}: {r.scenario_name}")
        lines.append("")

        if r.checks:
            for check_name, check_passed in r.checks.items():
                check_emoji = "✅" if check_passed else "❌"
                lines.append(f"- {check_emoji} {check_name}")
        else:
            lines.append("- No checks defined")

        # Show classification details if available
        if r.pipeline_result and r.pipeline_result.classification:
            cls = r.pipeline_result.classification
            lines.append(f"- 📊 Classification: **{cls.vehicle_class.value}** "
                         f"(confidence: {cls.confidence:.4f}, match: {cls.is_match})")

        # Show Tier 1 details
        if r.pipeline_result and r.pipeline_result.tier1_invoked:
            t1 = r.pipeline_result.tier1_response
            if t1:
                lines.append(f"- 🧠 Tier 1: {t1.recommended_action.value} "
                             f"(confidence: {t1.confidence:.2f}, "
                             f"latency: {t1.latency_ms:.1f}ms)")

        # Show Tier 2 details
        if r.pipeline_result and r.pipeline_result.tier2_invoked:
            t2 = r.pipeline_result.tier2_response
            if t2:
                lines.append(f"- 🤖 Tier 2: {len(t2.function_calls)} function call(s), "
                             f"all valid: {t2.all_calls_valid}")
                for fc in t2.function_calls:
                    valid_emoji = "✅" if fc.is_valid else "❌"
                    lines.append(f"  - {valid_emoji} `{fc.function_name}` "
                                 f"→ {fc.entity.value}.{fc.operation.value}")
                    if not fc.is_valid:
                        lines.append(f"    - Error: {fc.validation_error}")

        lines.append("")

    # ── Metrics Summary ──────────────────────────────────────────────────
    lines.append("## Metrics Summary")
    lines.append("")

    # Collect aggregate metrics
    confidences: list[float] = []
    latencies: list[float] = []
    tier1_invocations = 0
    tier2_invocations = 0
    total_function_calls = 0
    valid_function_calls = 0
    rejected_function_calls = 0
    total_audit_entries = 0

    for r in results:
        pr = r.pipeline_result
        if pr:
            latencies.append(pr.total_latency_ms)
            total_audit_entries += len(pr.audit_entries)
            if pr.classification:
                confidences.append(pr.classification.confidence)
            if pr.tier1_invoked:
                tier1_invocations += 1
            if pr.tier2_invoked:
                tier2_invocations += 1
            if pr.tier2_response:
                for fc in pr.tier2_response.function_calls:
                    total_function_calls += 1
                    if fc.is_valid:
                        valid_function_calls += 1
                    else:
                        rejected_function_calls += 1

    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")

    if confidences:
        avg_conf = sum(confidences) / len(confidences)
        min_conf = min(confidences)
        max_conf = max(confidences)
        lines.append(f"| Avg Classification Confidence | {avg_conf:.4f} |")
        lines.append(f"| Min Classification Confidence | {min_conf:.4f} |")
        lines.append(f"| Max Classification Confidence | {max_conf:.4f} |")

    if latencies:
        avg_lat = sum(latencies) / len(latencies)
        max_lat = max(latencies)
        lines.append(f"| Avg Pipeline Latency | {avg_lat:.1f}ms |")
        lines.append(f"| Max Pipeline Latency | {max_lat:.1f}ms |")

    lines.append(f"| Tier 1 Invocations | {tier1_invocations} |")
    lines.append(f"| Tier 2 Invocations | {tier2_invocations} |")
    lines.append(f"| Total Function Calls | {total_function_calls} |")
    lines.append(f"| Valid Function Calls | {valid_function_calls} |")
    lines.append(f"| Rejected Function Calls | {rejected_function_calls} |")
    lines.append(f"| Total Audit Entries | {total_audit_entries} |")
    lines.append("")

    # ── BRD Success Criteria Mapping ─────────────────────────────────────
    lines.append("## BRD Success Criteria Validation")
    lines.append("")

    criteria = [
        ("Reliably detect IN_VEHICLE activity", _check_criteria_1(results)),
        ("Capture bounded IMU burst", _check_criteria_2(results)),
        ("Distinguish Hunter 350 from non-matching vehicles", _check_criteria_3(results)),
        ("Maintain session across stop-shop-return", _check_criteria_4(results)),
        ("Resolve ambiguous context via Tier 1", _check_criteria_5(results)),
        ("Interpret user commands via Tier 2", _check_criteria_6(results)),
        ("Generate only valid, allow-listed function calls", _check_criteria_7(results)),
        ("Audit log completeness", _check_criteria_8(results)),
    ]

    lines.append("| # | Criterion | Status |")
    lines.append("|---|-----------|--------|")
    for i, (name, met) in enumerate(criteria, 1):
        emoji = "✅" if met else "❌"
        lines.append(f"| {i} | {name} | {emoji} |")

    lines.append("")

    report = "\n".join(lines)

    # Save to file if output_dir specified
    if output_dir:
        path = output_dir / EVAL_REPORT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(report)

    return report


# ── BRD Success Criteria Checks ──────────────────────────────────────────────

def _check_criteria_1(results: list[ScenarioResult]) -> bool:
    """Reliably detect the start of an IN_VEHICLE activity."""
    s1 = next((r for r in results if r.scenario_id == 1), None)
    return s1.passed if s1 else False


def _check_criteria_2(results: list[ScenarioResult]) -> bool:
    """Capture a bounded IMU burst without continuous sensor monitoring."""
    s1 = next((r for r in results if r.scenario_id == 1), None)
    s12 = next((r for r in results if r.scenario_id == 12), None)
    # S1 should capture IMU, S12 (walking) should NOT
    return (s1.passed if s1 else False) and (s12.passed if s12 else False)


def _check_criteria_3(results: list[ScenarioResult]) -> bool:
    """Distinguish Hunter 350 from non-matching vehicle contexts."""
    s1 = next((r for r in results if r.scenario_id == 1), None)
    s2 = next((r for r in results if r.scenario_id == 2), None)
    s3 = next((r for r in results if r.scenario_id == 3), None)
    return all(r.passed for r in [s1, s2, s3] if r is not None)


def _check_criteria_4(results: list[ScenarioResult]) -> bool:
    """Maintain a single session across a stop-shop-return journey."""
    s4 = next((r for r in results if r.scenario_id == 4), None)
    s5 = next((r for r in results if r.scenario_id == 5), None)
    return all(r.passed for r in [s4, s5] if r is not None)


def _check_criteria_5(results: list[ScenarioResult]) -> bool:
    """Resolve ambiguous physical context using Tier 1."""
    s6 = next((r for r in results if r.scenario_id == 6), None)
    s7 = next((r for r in results if r.scenario_id == 7), None)
    return all(r.passed for r in [s6, s7] if r is not None)


def _check_criteria_6(results: list[ScenarioResult]) -> bool:
    """Interpret user commands using resolved context through Tier 2."""
    s8 = next((r for r in results if r.scenario_id == 8), None)
    s9 = next((r for r in results if r.scenario_id == 9), None)
    return all(r.passed for r in [s8, s9] if r is not None)


def _check_criteria_7(results: list[ScenarioResult]) -> bool:
    """Generate only valid, allow-listed backend function calls."""
    s10 = next((r for r in results if r.scenario_id == 10), None)
    return s10.passed if s10 else False


def _check_criteria_8(results: list[ScenarioResult]) -> bool:
    """Provide observable logs for all decisions."""
    # Check that every scenario has audit entries
    for r in results:
        if r.pipeline_result and len(r.pipeline_result.audit_entries) == 0:
            return False
    return True

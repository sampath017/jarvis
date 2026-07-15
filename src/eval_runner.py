"""
Evaluation Harness

Runs all 12 scenarios through the pipeline, collects metrics,
and validates against expected outcomes.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import EVAL_RESULTS_FILE
from .models.enums import SessionStatus
from .models.schemas import PipelineResult, ScenarioExpectation, ScenarioResult
from .pipeline import JarvisPipeline
from .scenarios import Scenario, ScenarioStep, build_all_scenarios


def run_all_scenarios(use_mock: bool = True) -> list[ScenarioResult]:
    """Run all scenarios and return results."""
    scenarios = build_all_scenarios()
    results: list[ScenarioResult] = []

    for scenario in scenarios:
        result = run_scenario(scenario, use_mock=use_mock)
        results.append(result)

    return results


def run_scenario(
    scenario: Scenario,
    use_mock: bool = True,
    scenario_filter: int | None = None,
) -> ScenarioResult:
    """Run a single scenario through the pipeline."""
    if scenario_filter is not None and scenario.scenario_id != scenario_filter:
        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            scenario_name=scenario.name,
            passed=True,
            details={"skipped": "Filtered out"},
        )

    pipeline = JarvisPipeline(use_mock_llm=use_mock)
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}
    last_result: PipelineResult | None = None

    for step in scenario.steps:
        result = pipeline.process_event(
            vehicle_type=step.vehicle_type,
            activity=step.activity,
            gps=step.gps,
            nearby_pois=step.nearby_pois,
            user_command=step.user_command,
            imu_seed=step.imu_seed,
            skip_imu=step.skip_imu,
        )
        last_result = result

        # Validate step expectations
        step_checks = _validate_step(step, result, pipeline)
        for key, val in step_checks.items():
            check_key = f"{step.name} → {key}"
            checks[check_key] = val
            if not val:
                details[check_key] = f"FAILED"

    passed = all(checks.values()) if checks else True

    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        scenario_name=scenario.name,
        passed=passed,
        checks=checks,
        details=details,
        pipeline_result=last_result,
    )


def _validate_step(
    step: ScenarioStep,
    result: PipelineResult,
    pipeline: JarvisPipeline,
) -> dict[str, bool]:
    """Validate a pipeline result against step expectations."""
    exp = step.expectation
    checks: dict[str, bool] = {}

    # Vehicle classification check
    if exp.expected_vehicle is not None:
        if result.classification:
            checks["vehicle_class"] = (
                result.classification.vehicle_class == exp.expected_vehicle
            )
        else:
            checks["vehicle_class"] = False

    # Is-match check
    if exp.expected_is_match is not None:
        if result.classification:
            checks["is_match"] = result.classification.is_match == exp.expected_is_match
        else:
            # If no classification happened and we expected no match, that's OK
            checks["is_match"] = not exp.expected_is_match

    # Session status check
    if exp.expected_session_status is not None:
        session = pipeline.session_manager.active_session
        # Also check completed/expired sessions
        if session is None:
            # Look through all sessions for the expected status
            all_sessions = pipeline.session_manager.all_sessions
            if all_sessions:
                latest = all_sessions[-1]
                checks["session_status"] = latest.status == exp.expected_session_status
            else:
                checks["session_status"] = False
        else:
            checks["session_status"] = session.status == exp.expected_session_status

    # Tier 1 invocation check
    if exp.expected_tier1_invoked is not None:
        checks["tier1_invoked"] = result.tier1_invoked == exp.expected_tier1_invoked

    # Tier 2 invocation check
    if exp.expected_tier2_invoked is not None:
        checks["tier2_invoked"] = result.tier2_invoked == exp.expected_tier2_invoked

    # Function call validity check
    if exp.expected_function_valid is not None and result.tier2_response:
        if result.tier2_response.function_calls:
            all_valid = all(c.is_valid for c in result.tier2_response.function_calls)
            checks["function_valid"] = all_valid == exp.expected_function_valid
        else:
            checks["function_valid"] = not exp.expected_function_valid

    # CRUD entity check
    if exp.expected_crud_entity is not None and result.tier2_response:
        if result.tier2_response.function_calls:
            entities = [c.entity for c in result.tier2_response.function_calls]
            checks["crud_entity"] = exp.expected_crud_entity in entities
        else:
            checks["crud_entity"] = False

    # Minimum confidence check
    if exp.min_confidence is not None and result.classification:
        checks["min_confidence"] = result.classification.confidence >= exp.min_confidence

    return checks


def save_results(results: list[ScenarioResult], output_dir: Path | None = None) -> Path:
    """Save evaluation results to JSON."""
    path = (output_dir / EVAL_RESULTS_FILE) if output_dir else Path(EVAL_RESULTS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": datetime.now().isoformat(),
        "total_scenarios": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "scenarios": [
            {
                "id": r.scenario_id,
                "name": r.scenario_name,
                "passed": r.passed,
                "checks": r.checks,
                "details": r.details,
                "latency_ms": r.pipeline_result.total_latency_ms if r.pipeline_result else 0,
            }
            for r in results
        ],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return path

"""Run Android UI/native, backend, real embedding and scripted agent checks."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "tests" / "coding_agent_artifacts"
OUTPUT = ARTIFACTS / "harness"
EMBEDDING_PYTHON = ROOT / "backend" / "models" / "embedding" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def embedding_url(value):
    """Require an explicit HTTPS origin for remote inference; allow local HTTP."""
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path not in {"", "/"}
            or parsed.scheme not in {"http", "https"}
            or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
        raise argparse.ArgumentTypeError("Use an HTTPS origin or a loopback HTTP origin")
    return value.rstrip("/")


def percentile(values, fraction):
    if not values:
        return None
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3)


def junit_cases(path):
    result = []
    for case in ET.parse(path).getroot().iter("testcase"):
        status = "passed"
        for tag in ("failure", "error", "skipped"):
            if case.find(tag) is not None:
                status = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                break
        result.append({"name": case.get("name"), "class": case.get("classname"),
                       "status": status, "call_ms": round(float(case.get("time", 0)) * 1000, 3),
                       "metrics": {p.get("name"): p.get("value")
                                   for p in case.findall("./properties/property")}})
    return result


def flutter_cases(path):
    starts = {}
    result = []
    finished = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):  # Flutter also emits device-debug event arrays.
            continue
        if event.get("type") == "testStart":
            starts[event["test"]["id"]] = (event["test"], event.get("time", 0))
        elif event.get("type") == "testDone" and not event.get("hidden", False):
            test, start = starts.get(event["testID"], ({}, 0))
            result.append({"name": test.get("name", str(event["testID"])),
                           "status": "skipped" if event.get("skipped") else
                           "passed" if event.get("result") == "success" else "failed",
                           "call_ms": max(0, event.get("time", 0) - start)})
        elif event.get("type") == "done":
            finished = True
    if not finished:
        raise ValueError("Flutter machine report did not finish")
    return result


def execute(command, cwd, env, log, timeout, append=False):
    started = time.perf_counter()
    try:
        with log.open("a" if append else "w", encoding="utf-8") as stream:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Stop inference descendants before an optional service fallback
                # starts, including Windows venv launcher child processes.
                tree_stopped = True
                if os.name == "nt":
                    stopped = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    tree_stopped = stopped.returncode == 0
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if process.poll() is None:
                    process.kill()
                process.wait()
                error = "Suite timed out" if tree_stopped else "Suite timed out; process-tree cleanup could not be confirmed"
                return {"exit_code": -1, "error": error,
                        "wall_seconds": round(time.perf_counter() - started, 3)}
    except OSError as exc:
        return {"exit_code": -1, "error": str(exc), "wall_seconds": 0}
    return {"exit_code": code, "wall_seconds": round(time.perf_counter() - started, 3)}


def summarize(process, cases):
    counts = dict(Counter(case["status"] for case in cases))
    return {**process, "passed": process["exit_code"] == 0 and bool(cases)
            and all(c["status"] in {"passed", "skipped"} for c in cases)
            and counts.get("passed", 0) > 0,
            "counts": counts, "cases": cases}


def embedding_metrics(cases):
    """Aggregate only measured, labeled retrieval cases, with model provenance."""
    health = next((case["metrics"] for case in cases
                   if case.get("metrics", {}).get("model")), {})
    queries = [case["metrics"] for case in cases
               if "expected_rank" in case.get("metrics", {})]
    return {"model": health.get("model"), "revision": health.get("revision"),
            "dimensions": health.get("dimensions"), "retrieval": {
                "queries_measured": len(queries),
                "recall_at_1": sum(float(q["recall_at_1"]) for q in queries) / len(queries) if queries else None,
                "mean_reciprocal_rank": sum(float(q["reciprocal_rank"]) for q in queries) / len(queries) if queries else None,
                "sources": [{"path": q["source"], "sha256": q["source_sha256"]} for q in queries],
            }, "limitations": "Retrieval scores apply only to the checked-in repository corpus. "
                "They do not measure general LLM accuracy or phone performance."}


def test_environment(python, suite, embedding_origin=None):
    env = dict(os.environ)
    env.update(ENVIRONMENT="testing", PYTHONUTF8="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", JARVIS_ENABLE_TRACING="false",
               LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false",
               OPENROUTER_API_KEY="offline-harness", GOOGLE_PLACES_API_KEY="",
               JARVIS_TEST_PYTHON=python)
    env.pop("JARVIS_STORAGE_MODE", None)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "tests"), str(ROOT / "backend"), env.get("PYTHONPATH", "")])
    # Isolate defaults used by graph/API fixtures from the developer's local DB.
    runtime = OUTPUT / f"{suite}-runtime.db"
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(runtime) + suffix)
        if not path.resolve().is_relative_to(OUTPUT.resolve()):
            raise ValueError("Runtime database escaped the artifact directory")
        path.unlink(missing_ok=True)
    env["JARVIS_LOCAL_DB_PATH"] = str(runtime)
    if suite == "embedding":
        if embedding_origin:
            env["JARVIS_TEST_EMBEDDING_URL"] = embedding_origin
        else:
            env.pop("JARVIS_TEST_EMBEDDING_URL", None)
            env.pop("JARVIS_TEST_EMBEDDING_TOKEN", None)
            env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
            env.setdefault("HF_HOME", str(ROOT / "backend/models/huggingface"))
            media_bin = ARTIFACTS / "embedding/ffmpeg/bin"
            if media_bin.is_dir():
                env["PATH"] = str(media_bin) + os.pathsep + env.get("PATH", "")
    return env


def pytest_run(python, suite, nodes, timeout, append=False, embedding_origin=None):
    xml = OUTPUT / f"{suite}.xml"
    xml.unlink(missing_ok=True)  # Never parse an earlier successful run after a failure.
    fixture_dir = ARTIFACTS / "tests" / "fixtures" / "harness" / suite
    if not fixture_dir.resolve().is_relative_to(ARTIFACTS.resolve()):
        raise ValueError("Pytest fixture directory escaped the archive")
    fixture_dir.parent.mkdir(parents=True, exist_ok=True)
    # Real inference uses the selected service; other Python suites stay offline.
    plugins = [] if suite == "embedding" else ["-p", "harness.offline", "-p", "pytest_asyncio.plugin"]
    command = [python, "-m", "pytest", "-c", str(ROOT / "pytest.ini"), "-q", *plugins,
               "-m", "not live",
               "-o", "junit_family=legacy", "-o", "junit_duration_report=call",
               f"--junitxml={xml}", f"--basetemp={fixture_dir}", *nodes]
    env = test_environment(python, suite, embedding_origin)
    log = OUTPUT / f"{suite}.log"
    if suite == "embedding" and not embedding_origin:
        preflight = execute([python, str(ROOT / "tests/harness/check_embedding_runtime.py")],
                            ROOT, env, log, timeout)
        if preflight["exit_code"] != 0:
            return {**summarize(preflight, []), "mode": "real-model-inference", "runtime": "local",
                    "python": python, "endpoint": None,
                    "error": preflight.get("error", "Local embedding preflight failed; see embedding.log and embedding/README.md.")}
    process = execute(command, ROOT, env, log, timeout, append)
    try:
        cases = junit_cases(xml) if xml.exists() else []
    except (ET.ParseError, ValueError) as exc:
        process["error"] = f"Invalid test report: {exc}"
        process["exit_code"] = -1
        cases = []
    result = summarize(process, cases)
    if suite == "embedding":
        result["mode"] = "real-model-inference"
        result["runtime"] = "service" if embedding_origin else "local"
        result["python"] = python
        result["endpoint"] = embedding_origin
        result["inference"] = embedding_metrics(cases)
    return result


def embedding_tests(python, timeout, local_python=EMBEDDING_PYTHON,
                    origin=None, fallback_origin=None):
    """Prefer local weights; fall back only for explicit infrastructure failures."""
    if origin:
        return pytest_run(python, "embedding", ["tests/embedding"], timeout,
                          embedding_origin=origin)
    if Path(local_python).is_file():
        local = pytest_run(str(local_python), "embedding", ["tests/embedding"], timeout)
    else:
        local = {"passed": False, "exit_code": 77, "counts": {}, "cases": [],
                 "mode": "real-model-inference", "runtime": "local", "python": str(local_python),
                 "endpoint": None, "error": "Local embedding Python is missing. Prepare embedding/.venv "
                     "using embedding/README.md or pass --embedding-python."}
        (OUTPUT / "embedding.xml").unlink(missing_ok=True)
        (OUTPUT / "embedding.log").write_text(local["error"], encoding="utf-8")
    # Startup failures use exit 77. A deadline can indicate insufficient local
    # resources. Ordinary test failures never trigger a passing remote rerun.
    unavailable = local["exit_code"] == 77 or local.get("error") == "Suite timed out"
    if local["passed"] or not fallback_origin or not unavailable:
        return local
    print("Local embedding runtime unavailable; trying the explicitly selected service...", flush=True)
    for extension in ("log", "xml"):
        path = OUTPUT / f"embedding.{extension}"
        if path.exists():
            shutil.copyfile(path, OUTPUT / f"embedding-local.{extension}")
    service = pytest_run(python, "embedding", ["tests/embedding"], timeout,
                         embedding_origin=fallback_origin)
    return {**service, "fallback_used": True, "attempts": [local, service]}


def agent_benchmark(python, repeats, timeout):
    definitions = json.loads((ROOT / "tests" / "harness" / "agent_cases.json").read_text())
    runs = []
    for index in range(repeats):
        print(f"Agent workflow benchmark {index + 1}/{repeats}...", flush=True)
        runs.append(pytest_run(python, "agent", [c["node"] for c in definitions],
                               timeout, append=index > 0))
    groups = defaultdict(list)
    for run in runs:
        for case in run["cases"]:
            groups[(case["class"], case["name"])].append(case)
    scenarios = []
    for (class_name, name), cases in sorted(groups.items()):
        samples = [c["call_ms"] for c in cases]
        definition = next((d for d in definitions
                           if Path(d["node"].split("::")[0]).stem == class_name.split(".")[-1]
                           and d["node"].split("::")[1] == name.split("[")[0]), None)
        scenarios.append({"id": definition["id"] if definition else name,
                          "name": name, "purpose": definition["purpose"] if definition else "",
                          "runs": len(cases), "passed_runs": sum(c["status"] == "passed" for c in cases),
                          "p50_test_call_ms": percentile(samples, .5),
                          "p95_test_call_ms": percentile(samples, .95),
                          "metrics": [c["metrics"] for c in cases if c["metrics"]]})
    return {"passed": all(r["passed"] for r in runs) and bool(scenarios),
            "mode": "offline-scripted-provider", "repeats": repeats,
            "scenario_definitions": len(definitions), "counts": dict(Counter(
                c["status"] for r in runs for c in r["cases"])), "scenarios": scenarios,
            "runs": runs,
            "limitations": "Measures workflow regressions and local test-call timing. "
                "Does not measure live model accuracy, provider latency, token cost, phone frame rate or billed RecordStore reads."}


def android_tests(python, timeout):
    import shutil
    env = test_environment(python, 'android')
    studio_java = Path('C:/Program Files/Android/Android Studio/jbr')
    if not env.get('JAVA_HOME') and studio_java.exists():
        env['JAVA_HOME'] = str(studio_java)
    gradle = ROOT / 'mobile' / 'android' / ('gradlew.bat' if os.name == 'nt' else 'gradlew')
    process = execute([str(gradle), ':app:testDebugUnitTest', '--console=plain'],
                      gradle.parent, env, OUTPUT / 'android.log', timeout)
    cases = []
    reports = OUTPUT / 'android-results'
    reports.mkdir(exist_ok=True)
    for old in reports.glob('*.xml'):
        old.unlink()
    if process['exit_code'] == 0:
        for path in (ROOT / 'mobile/build/app/test-results/testDebugUnitTest').glob('*.xml'):
            shutil.copyfile(path, reports / path.name)
            cases.extend(junit_cases(path))
    return summarize(process, cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("all", "backend", "ui", "agent", "embedding", "android", "harness"), default="all")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--flutter", default=shutil.which("flutter"))
    parser.add_argument("--embedding-url", type=embedding_url,
                        default=os.environ.get("JARVIS_TEST_EMBEDDING_URL"),
                        help="Use this service instead of local model inference")
    parser.add_argument("--embedding-python", default=str(EMBEDDING_PYTHON),
                        help="Local inference Python (default: embedding/.venv)")
    parser.add_argument("--embedding-fallback-url", type=embedding_url,
                        help="Try this service only if local startup is unavailable or times out")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20 or args.timeout < 1:
        parser.error("Use 1–20 repeats and a positive timeout")
    if args.embedding_url and args.embedding_fallback_url:
        parser.error("Choose --embedding-url or --embedding-fallback-url, not both")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    venv = ROOT / "backend" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python = str(venv) if venv.exists() else sys.executable
    suites = ("backend", "embedding", "ui", "agent", "harness", "android") if args.suite == "all" else (args.suite,)
    report = {"schema_version": 1, "started_at_utc": datetime.now(timezone.utc).isoformat(), "suites": {}}
    for suite in suites:
        print(f"Running {suite}...", flush=True)
        if suite == "embedding":
            result = embedding_tests(python, args.timeout, args.embedding_python,
                                     args.embedding_url, args.embedding_fallback_url)
        elif suite in {"backend", "harness"}:
            result = pytest_run(python, suite, [f"tests/{suite}"], args.timeout)
        elif suite == 'android':
            result = android_tests(python, args.timeout)
        elif suite == "ui":
            if not args.flutter:
                result = {"passed": False, "error": "Flutter not found; supply --flutter"}
            else:
                log = OUTPUT / "ui.log"
                process = execute([args.flutter, "test", "--machine", "--no-pub", str(ROOT / 'tests/android/ui')],
                                  ROOT / "mobile", test_environment(python, suite), log, args.timeout)
                try:
                    cases = flutter_cases(log) if log.exists() else []
                except ValueError as exc:
                    process["error"] = str(exc)
                    process["exit_code"] = -1
                    cases = []
                result = summarize(process, cases)
                result["mode"] = "flutter-widget-and-service-tests"
        else:
            result = agent_benchmark(python, args.repeats, args.timeout)
        report["suites"][suite] = result
        (OUTPUT / f"{suite}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        report["passed"] = all(r["passed"] for r in report["suites"].values())
        (OUTPUT / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"{suite}: {'PASS' if result['passed'] else 'FAIL'} {result.get('counts', {})}", flush=True)
    print(f"Report: {OUTPUT / 'latest.json'}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Check real inference selection and aggregation without making provider calls."""
import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import run

TEMP_ROOT = run.ARTIFACTS / "tests/fixtures/harness/embedding-config"


class EmbeddingConfigurationTests(unittest.TestCase):
    def test_origins_exclude_credentials_paths_and_insecure_remote_hosts(self):
        for origin in ("http://127.0.0.1:8080", "http://localhost:8080/", "https://private.run.app"):
            self.assertEqual(run.embedding_url(origin), origin.rstrip("/"))
        for origin in ("http://private.run.app", "https://user:secret@private.run.app",
                       "https://private.run.app?token=secret", "https://private.run.app/embed", "not-a-url"):
            with self.subTest(origin=origin), self.assertRaises(argparse.ArgumentTypeError):
                run.embedding_url(origin)

    def test_only_embedding_suite_uses_real_service_instead_of_offline_plugin(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder, patch.object(run, "OUTPUT", Path(folder)):
            def execute(command, cwd, env, log, timeout, append):
                xml = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml="))
                Path(xml).write_text('<testsuite><testcase name="checked"/></testsuite>')
                return {"exit_code": 0}

            with patch.object(run, "execute", side_effect=execute) as process:
                result = run.pytest_run("python", "embedding", ["tests/embedding"], 10,
                                        embedding_origin="https://private.run.app")
                command, _, env, *_ = process.call_args.args
                self.assertNotIn("harness.offline", command)
                self.assertEqual(env["JARVIS_TEST_EMBEDDING_URL"], "https://private.run.app")
                self.assertEqual(result["mode"], "real-model-inference")
                self.assertTrue(result["passed"])
                run.pytest_run("python", "backend", ["tests/backend"], 10)
                self.assertIn("harness.offline", process.call_args.args[0])

    def test_missing_measurements_cannot_become_perfect_retrieval(self):
        empty = run.embedding_metrics([])
        self.assertEqual(empty["retrieval"]["queries_measured"], 0)
        self.assertIsNone(empty["retrieval"]["recall_at_1"])
        measured = run.embedding_metrics([
            {"metrics": {"model": "production", "revision": "pinned", "dimensions": "768"}},
            {"metrics": {"expected_rank": "1", "recall_at_1": "1", "reciprocal_rank": "1",
                         "source": "first.md", "source_sha256": "first"}},
            {"metrics": {"expected_rank": "2", "recall_at_1": "0", "reciprocal_rank": "0.5",
                         "source": "second.md", "source_sha256": "second"}},
        ])
        self.assertEqual(measured["retrieval"]["recall_at_1"], .5)
        self.assertEqual(measured["retrieval"]["mean_reciprocal_rank"], .75)
        self.assertEqual(measured["revision"], "pinned")

    def test_local_environment_excludes_service_and_disables_weight_downloads(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder, patch.object(run, "OUTPUT", Path(folder)):
            with patch.dict(run.os.environ, {"JARVIS_TEST_EMBEDDING_URL": "https://old.run.app",
                                            "JARVIS_TEST_EMBEDDING_TOKEN": "test-token"}):
                run.os.environ.pop("HF_HOME", None)
                env = run.test_environment("local-python", "embedding")
        self.assertNotIn("JARVIS_TEST_EMBEDDING_URL", env)
        self.assertNotIn("JARVIS_TEST_EMBEDDING_TOKEN", env)
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertEqual(env["TRANSFORMERS_OFFLINE"], "1")
        self.assertEqual(env["HF_HOME"], str(run.ROOT / "backend/models/huggingface"))

    def test_local_success_never_contacts_fallback(self):
        with patch.object(run.Path, "is_file", return_value=True), patch.object(run, "pytest_run") as execute:
            execute.return_value = {"passed": True, "exit_code": 0, "runtime": "local"}
            result = run.embedding_tests("backend-python", 10, "local-python", fallback_origin="https://service.run.app")
        self.assertEqual(result["runtime"], "local")
        execute.assert_called_once_with("local-python", "embedding", ["tests/embedding"], 10)

    def test_missing_environment_requires_explicit_fallback(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder, patch.object(run, "OUTPUT", Path(folder)):
            with patch.object(run.Path, "is_file", return_value=False), patch.object(run, "pytest_run") as execute:
                (Path(folder) / "embedding.xml").write_text("old success")
                result = run.embedding_tests("backend-python", 10, "missing-python")
            self.assertFalse((Path(folder) / "embedding.xml").exists())
            self.assertIn("missing", (Path(folder) / "embedding.log").read_text())
        self.assertFalse(result["passed"])
        self.assertEqual(result["exit_code"], 77)
        execute.assert_not_called()

    def test_fallback_preserves_local_failure_and_uses_service_python(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        for failure in ({"passed": False, "exit_code": 77},
                        {"passed": False, "exit_code": -1, "error": "Suite timed out"}):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
                with patch.object(run, "OUTPUT", Path(folder)), patch.object(run.Path, "is_file", return_value=True):
                    (Path(folder) / "embedding.log").write_text("local failure")
                    with patch.object(run, "pytest_run", side_effect=[failure, {"passed": True, "runtime": "service"}]) as execute:
                        result = run.embedding_tests("backend-python", 10, "local-python",
                                                     fallback_origin="https://service.run.app")
                    self.assertEqual((Path(folder) / "embedding-local.log").read_text(), "local failure")
            self.assertTrue(result["passed"])
            self.assertTrue(result["fallback_used"])
            self.assertEqual(result["attempts"][0], failure)
            self.assertEqual(execute.call_args.args[0], "backend-python")
            self.assertEqual(execute.call_args.kwargs["embedding_origin"], "https://service.run.app")

    def test_assertion_or_cleanup_failures_do_not_trigger_service_fallback(self):
        for failure in ({"passed": False, "exit_code": 1},
                        {"passed": False, "exit_code": -1,
                         "error": "Suite timed out; process-tree cleanup could not be confirmed"}):
            with self.subTest(failure=failure), patch.object(run.Path, "is_file", return_value=True):
                with patch.object(run, "pytest_run", return_value=failure) as execute:
                    result = run.embedding_tests("backend-python", 10, "local-python", fallback_origin="https://service.run.app")
            self.assertFalse(result["passed"])
            self.assertEqual(execute.call_count, 1)

    def test_dependency_preflight_failure_does_not_invoke_pytest(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder, patch.object(run, "OUTPUT", Path(folder)):
            with patch.object(run, "execute", return_value={"exit_code": 77}) as execute:
                result = run.pytest_run("local-python", "embedding", ["tests/embedding"], 10)
        self.assertFalse(result["passed"])
        self.assertEqual(result["exit_code"], 77)
        self.assertEqual(execute.call_count, 1)
        self.assertTrue(execute.call_args.args[0][1].endswith("check_embedding_runtime.py"))

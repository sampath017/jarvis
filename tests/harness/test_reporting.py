"""Ensure failures and incomplete reports cannot appear as successful harness runs."""
import json
from pathlib import Path
import tempfile
import unittest

from harness.run import flutter_cases, junit_cases, summarize

TEMP_ROOT = Path(__file__).resolve().parents[1] / 'coding_agent_artifacts/tests/fixtures/harness/reporting'


class ReportingTests(unittest.TestCase):
    def setUp(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    def test_junit_preserves_failures_skips_and_measured_properties(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
            path = Path(folder) / 'report.xml'
            path.write_text('''<testsuites><testsuite>
                <testcase name="save" classname="agent" time="0.02">
                  <properties><property name="model_calls" value="2"/></properties>
                </testcase>
                <testcase name="broken"><failure message="wrong answer"/></testcase>
                <testcase name="unavailable"><error message="setup failed"/></testcase>
                <testcase name="optional"><skipped/></testcase>
                </testsuite></testsuites>''')
            cases = junit_cases(path)
        self.assertEqual([c['status'] for c in cases], ['passed', 'failed', 'error', 'skipped'])
        self.assertEqual(cases[0]['metrics'], {'model_calls': '2'})
        self.assertEqual(cases[0]['call_ms'], 20)
        self.assertFalse(summarize({'exit_code': 0}, cases)['passed'])

    def test_nonzero_exit_and_empty_or_skipped_suites_fail(self):
        self.assertFalse(summarize({'exit_code': 1}, [{'status': 'passed'}])['passed'])
        self.assertFalse(summarize({'exit_code': 0}, [])['passed'])
        self.assertFalse(summarize({'exit_code': 0}, [{'status': 'skipped'}])['passed'])

    def test_flutter_ignores_hidden_loading_tests_and_retains_failures(self):
        events = [
            [{'event': 'test.startedProcess', 'params': {'vmServiceUri': None}}],
            {'type': 'testStart', 'test': {'id': 1, 'name': 'widget'}, 'time': 5},
            {'type': 'testDone', 'testID': 99, 'hidden': True, 'result': 'success'},
            {'type': 'testDone', 'testID': 1, 'hidden': False, 'result': 'failure', 'time': 25},
            {'type': 'done', 'success': False},
        ]
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
            path = Path(folder) / 'ui.log'
            path.write_text('\n'.join(json.dumps(e) for e in events))
            cases = flutter_cases(path)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]['call_ms'], 20)
        self.assertFalse(summarize({'exit_code': 1}, cases)['passed'])

    def test_interrupted_flutter_log_is_not_a_success(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
            path = Path(folder) / 'ui.log'
            path.write_text(json.dumps({'type': 'testDone', 'testID': 1, 'result': 'success'}))
            with self.assertRaisesRegex(ValueError, 'did not finish'):
                flutter_cases(path)


if __name__ == '__main__':
    unittest.main()

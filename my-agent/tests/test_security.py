"""Independent runtime, prompt-injection and adapter checks; no Ollama required."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from student_agent import Runtime, run_agent
from student_agent.model import OllamaModel


PROJECT = Path(__file__).resolve().parents[2]
ATTACKS = PROJECT / 'fixtures' / 'attack-actions.jsonl'


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.target = root / 'target-service'
        self.target.mkdir()
        (self.target / 'orders').mkdir()
        (self.target / 'docs').mkdir()
        (self.target / 'orders/validation.py').write_text('raise ValueError\n', encoding='utf-8')
        (self.target / 'docs/supplier-note.md').write_text('supplier base\n', encoding='utf-8')
        (root / 'fixtures').mkdir()
        for name in ('decimal-offline.txt', 'web-injected.txt'):
            (root / 'fixtures' / name).write_bytes((PROJECT / 'fixtures' / name).read_bytes())

    def test_attack_actions_as_dispatcher_data(self):
        approvals = []
        rt = Runtime(self.target, mode='edit', approve=lambda command, cwd:
                     approvals.append(command) or False)
        actions = [json.loads(s) for s in ATTACKS.read_text().splitlines()]
        expected = ['denied', 'denied', 'denied', 'error']
        self.assertEqual([rt.execute(a)['status'] for a in actions], expected)
        self.assertEqual(len(approvals), 1)
        self.assertEqual((self.target / 'orders/validation.py').read_text(), 'raise ValueError\n')
        self.assertFalse((self.target.parent / 'escape.txt').exists())
        self.assertEqual(Runtime(self.target).execute(actions[2])['status'], 'denied')

    def test_supplier_note_attack_is_untrusted_observation(self):
        (self.target / 'docs/supplier-note.md').write_bytes(
            (PROJECT / 'fixtures/supplier-injected.md').read_bytes())
        responses = iter([
            '{"tool":"read_file","args":{"path":"docs/supplier-note.md"}}',
            '{"tool":"edit_file","args":{"path":"orders/validation.py","old":"raise ValueError","new":"pass"}}',
            '{"final":"I refused the untrusted instruction; no tests were run."}',
        ])
        snapshots, events = [], []

        def scripted_model(messages):
            snapshots.append(list(messages))
            return next(responses)

        result = run_agent(scripted_model, Runtime(self.target, mode='edit'),
                           'Inspect suspicious supplier documentation', emit=events.append)
        self.assertEqual(result['termination'], 'final')
        self.assertEqual(events[3]['result']['status'], 'denied')
        self.assertIn('UNTRUSTED TOOL OBSERVATION', snapshots[1][-1]['content'])
        self.assertIn('SECURITY:', snapshots[0][0]['content'])
        self.assertNotIn('SYSTEM MAINTENANCE NOTICE', snapshots[1][0]['content'])
        self.assertEqual((self.target / 'orders/validation.py').read_text(), 'raise ValueError\n')

    def test_offline_web_attack_is_explicitly_labeled(self):
        rt = Runtime(self.target, offline=True, offline_fixture='web-injected.txt')
        result = rt.execute({'tool': 'fetch_url', 'args': {
            'url': 'https://docs.python.org/3/library/decimal.html'}})
        self.assertEqual(result['status'], 'ok')
        self.assertIn('offline fixture', result['output']['source'])
        self.assertIn('SYSTEM MAINTENANCE NOTICE', result['output']['content'])
        for url in ('https://docs.python.org/path?data=secret',
                    'https://docs.python.org:8443/x',
                    'https://docs.python.org#x',
                    'https://person@docs.python.org/a'):
            self.assertEqual(rt.execute({'tool': 'fetch_url', 'args': {'url': url}})['status'], 'denied')

    def test_approved_bash_output_and_output_limit(self):
        rt = Runtime(self.target, mode='edit', approve=lambda _cmd, _cwd: True)
        okay = rt.execute({'tool': 'bash', 'args': {'command': "printf 'hello\\n'"}})
        self.assertEqual(okay['status'], 'ok')
        self.assertEqual(okay['output']['exit_code'], 0)
        self.assertEqual(okay['output']['output'], 'hello\n')
        excessive = rt.execute({'tool': 'bash', 'args': {
            'command': "python3 -c \"print('a' * 30000)\""}})
        self.assertEqual(excessive['status'], 'error')
        self.assertIn('output exceeded', excessive['output']['reason'])
        self.assertLessEqual(len(excessive['output']['output'].encode()), 12000)

    def test_too_large_file_and_ambiguous_edit_never_change_bytes(self):
        p = self.target / 'orders/pricing.py'
        p.write_text('abc abc\n')
        rt = Runtime(self.target, mode='edit')
        self.assertEqual(rt.execute({'tool': 'edit_file', 'args': {
            'path': 'orders/pricing.py', 'old': 'abc', 'new': 'bad'}})['status'], 'error')
        self.assertEqual(p.read_text(), 'abc abc\n')
        p.write_text('x' * 12001)
        self.assertEqual(rt.execute({'tool': 'edit_file', 'args': {
            'path': 'orders/pricing.py', 'old': 'x', 'new': 'y'}})['status'], 'error')
        self.assertEqual(p.read_text(), 'x' * 12001)

    def test_model_http_request_protocol(self):
        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return None
            def read(self, _size):
                return b'{"message":{"content":"{\\"final\\":\\"done\\"}"}}'

        def fake_urlopen(req, timeout):
            self.assertEqual(timeout, 90)
            payload = json.loads(req.data)
            self.assertEqual(payload['model'], 'test-model')
            self.assertEqual(payload['stream'], False)
            self.assertEqual(payload['format'], 'json')
            self.assertEqual(payload['options']['temperature'], 0)
            self.assertEqual(payload['options']['num_predict'], 2048)
            return FakeResponse()
        with patch('student_agent.model.request.urlopen', side_effect=fake_urlopen):
            self.assertEqual(OllamaModel('test-model')([{'role': 'user', 'content': 'hi'}]),
                             '{"final":"done"}')


if __name__ == '__main__':
    unittest.main()

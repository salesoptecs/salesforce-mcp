"""Offline regression tests: never connect to Salesforce or install dependencies."""
import asyncio
import copy
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[3] / 'static/downloads/salesforce_mcp_server.py'
if not SOURCE.exists():
    SOURCE = Path(__file__).resolve().parents[3] / 'salesforce_mcp_server.py'
spec = importlib.util.spec_from_file_location('salesforce_runtime', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
IDS = ['001000000000000AAA', '001000000000001AAA']


class FakeObject:
    def __init__(self):
        self.rows = {rid: {'Name': 'Example', 'Industry': 'Old',
                          'LastModifiedDate': '2026-09-06T10:00:00.000Z'} for rid in IDS}
        self.writes = []
        self.failure = None
        self.read_failure = False

    def describe(self):
        return {'fields': [{'name': 'Industry', 'updateable': True, 'nillable': False, 'length': 30}]}

    def get(self, rid):
        if self.read_failure:
            raise TimeoutError()
        return copy.deepcopy(self.rows[rid])

    def update(self, rid, data, headers):
        self.writes.append((rid, data, headers))
        if self.failure:
            raise self.failure
        self.rows[rid].update(data)
        return 204


class FakeSF:
    sf_instance = 'example.my.salesforce.com'
    def __init__(self):
        self.Account = FakeObject()


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'SF_USERNAME': 'test@example.com',
            'SF_UPDATE_POLICY': '{"Account":["Industry"]}', 'SF_STATE_DIR': self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.mode = patch.object(m, 'READONLY', False)
        self.mode.start()
        self.addCleanup(self.mode.stop)
        self.sf = FakeSF()
        self.store = m.ChangeStore()
        self.addCleanup(self.store.db.close)

    def prepare(self, count=1):
        return m.prepare_updates(self.sf, self.store, 'Account',
            [{'record_id': rid, 'data': {'Industry': 'New'}} for rid in IDS[:count]])

    def execute(self, plan):
        return m.execute_reviewed(self.sf, self.store, plan, plan['digest'])

    def test_prepare_never_writes_and_contains_diff(self):
        p = self.prepare()
        self.assertEqual(p['payload']['rows'][0]['before'], {'Industry': 'Old'})
        self.assertEqual(p['payload']['rows'][0]['after'], {'Industry': 'New'})
        self.assertEqual(self.sf.Account.writes, [])

    def test_no_direct_write_or_approval_tools(self):
        names = {t.name for t in asyncio.run(m.list_tools())}
        self.assertFalse(names & m.WRITE_TOOLS)
        self.assertFalse(any('approve' in n or 'execute' in n for n in names))
        for name in m.WRITE_TOOLS:
            self.assertIn('disabled', asyncio.run(m.call_tool(name, {}))[0].text)

    def test_validation(self):
        invalid = [[], [{'record_id': 'bad', 'data': {'Industry': 'New'}}],
            [{'record_id': IDS[0], 'data': {'Industry': None}}],
            [{'record_id': IDS[0], 'data': {'Industry': 'Old'}}],
            [{'record_id': IDS[0], 'data': {'Name': 'New'}}],
            [{'record_id': IDS[0], 'data': {'Industry': 'x' * 31}}],
            [{'record_id': IDS[0], 'data': {'Industry': 'New'}}] * 2,
            [{'record_id': IDS[0], 'data': {'Industry': 'New'}}] * 201]
        for updates in invalid:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                m.prepare_updates(self.sf, self.store, 'Account', updates)
        self.assertEqual(self.sf.Account.writes, [])

    def test_policy_closed_by_default(self):
        with patch.dict(os.environ, {'SF_UPDATE_POLICY': '{}'}), self.assertRaises(ValueError):
            self.prepare()

    def test_success_conditional_header_and_no_replay(self):
        p = self.prepare()
        self.assertEqual(self.execute(p)['status'], 'completed')
        self.assertEqual(self.sf.Account.writes[0][2],
                         {'If-Unmodified-Since': 'Sun, 06 Sep 2026 10:00:00 GMT'})
        with self.assertRaises(ValueError):
            self.execute(p)
        self.assertEqual(len(self.sf.Account.writes), 1)

    def test_readonly_digest_identity_expiry_and_policy_guards(self):
        p = self.prepare()
        with patch.object(m, 'READONLY', True), self.assertRaises(ValueError):
            self.execute(p)
        with self.assertRaises(ValueError):
            m.execute_reviewed(self.sf, self.store, p, 'wrong')
        with patch.dict(os.environ, {'SF_USERNAME': 'other@example.com'}), self.assertRaises(ValueError):
            self.execute(p)
        with patch.object(m.time, 'time', return_value=p['payload']['expires_at']+1), self.assertRaises(ValueError):
            self.execute(p)
        with patch.dict(os.environ, {'SF_UPDATE_POLICY': '{}'}), self.assertRaises(ValueError):
            self.execute(p)
        self.assertEqual(self.sf.Account.writes, [])

    def test_stale_record_conflict(self):
        p = self.prepare()
        self.sf.Account.rows[IDS[0]]['Industry'] = 'Changed elsewhere'
        self.assertEqual(self.execute(p)['outcomes'][0]['status'], 'conflict')
        self.assertEqual(self.sf.Account.writes, [])

    def test_conditional_conflict(self):
        p = self.prepare()
        error = RuntimeError()
        error.status = 412
        self.sf.Account.failure = error
        self.assertEqual(self.execute(p)['outcomes'][0]['status'], 'conflict')

    def test_uncertain_write_not_retried_and_pending_resumes(self):
        p = self.prepare(2)
        self.sf.Account.failure = TimeoutError()
        first = self.execute(p)
        self.assertEqual(first['status'], 'paused')
        self.assertEqual([r['status'] for r in first['outcomes']], ['unknown', 'pending'])
        self.sf.Account.failure = None
        second = self.execute(p)
        self.assertEqual([r['status'] for r in second['outcomes']], ['unknown', 'succeeded'])
        self.assertEqual([w[0] for w in self.sf.Account.writes], IDS)

    def test_read_failure_can_resume(self):
        p = self.prepare()
        self.sf.Account.read_failure = True
        self.assertEqual(self.execute(p)['outcomes'][0]['status'], 'pending')
        self.sf.Account.read_failure = False
        self.assertEqual(self.execute(p)['status'], 'completed')

    def test_crashed_or_concurrent_job_is_not_replayed(self):
        p = self.prepare()
        self.store.record(p['plan_id'], [{'record_id': IDS[0], 'status': 'inflight'}], 'executing')
        with self.assertRaises(ValueError):
            self.execute(p)
        self.assertEqual(self.sf.Account.writes, [])

    def test_payload_corruption_detected(self):
        p = self.prepare()
        self.store.db.execute('UPDATE plans SET payload=? WHERE id=?', ('{}', p['plan_id']))
        self.store.db.commit()
        with self.assertRaises(ValueError):
            self.store.load(p['plan_id'])

    def test_default_readonly_and_typo_fail_closed(self):
        for value in (None, '', 'treu', '1'):
            with self.subTest(value=value), patch.dict(os.environ):
                if value is None:
                    os.environ.pop('SF_READONLY', None)
                else:
                    os.environ['SF_READONLY'] = value
                fresh = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(fresh)
                self.assertTrue(fresh.READONLY)

    def test_piped_approval_refused_before_salesforce_connection(self):
        p = self.prepare()
        with patch.object(m.sys, 'stdin', io.StringIO('APPLY '+p['digest'])), \
             patch.object(m.sys, 'stdout', io.StringIO()), \
             patch.object(m, 'get_sf') as connection, self.assertRaises(ValueError):
            m.review_cli(SimpleNamespace(command='review', plan_id=p['plan_id']))
        connection.assert_not_called()

    def test_report_omits_field_values(self):
        p = self.prepare()
        output = io.StringIO()
        with patch.object(m.sys, 'stdout', output):
            m.review_cli(SimpleNamespace(command='report', plan_id=p['plan_id']))
        self.assertIn(IDS[0]+',pending', output.getvalue())
        self.assertNotIn('Industry', output.getvalue())

    def test_upstream_errors_do_not_echo_sensitive_payloads(self):
        self.assertNotIn('secret', m.safe_error(ValueError('secret')))
        self.assertEqual(m.safe_error(m.ProposalError('Safe validation')), 'Safe validation')


if __name__ == '__main__':
    unittest.main()

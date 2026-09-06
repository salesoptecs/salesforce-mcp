"""Read-only diagnostics with synthetic Salesforce responses; no live API calls."""
import asyncio
import copy
import unittest
from unittest.mock import patch
from test_workflow import m, IDS

FLOW = '301000000000000AAA'
META = {'start':{'object':'Account', 'recordTriggerType':'Update', 'triggerType':'RecordAfterSave',
                 'filters':[{'field':'Industry', 'operator':'EqualTo', 'value':{'stringValue':'Tech'}}],
                 'connector':{'targetReference':'ChooseOwner'}},
        'decisions':[{'name':'ChooseOwner','rules':[{'name':'Enterprise',
            'conditions':[{'leftValueReference':'$Record.Industry','operator':'EqualTo','rightValue':{'stringValue':'Tech'}}],
            'connector':{'targetReference':'AssignOwner'}}]}],
        'assignments':[{'name':'AssignOwner','assignmentItems':[{'assignToReference':'$Record.OwnerId',
            'operator':'Assign','value':{'stringValue':'005000000000000AAA'}}]}],
        'subflows':[{'name':'Notify','flowName':'NotifyOwner'}],
        'actionCalls':[{'name':'Routing','actionType':'apex','actionName':'RoutingAction'}]}


class DiagnosticSF:
    def __init__(self):
        self.calls = []
        self.meta = copy.deepcopy(META)
        self.missing = False
        self.history_denied = False
        self.more = False
        self.Account = self

    def describe(self):
        return {'fields':[{'name':f} for f in ('Id','OwnerId','Industry','LastModifiedDate','LastModifiedById')]}

    def toolingexecute(self, action, method, params):
        self.calls.append((action, method, params['q']))
        assert action == 'query' and method == 'GET'
        q = params['q']
        if 'FROM ApexTrigger' in q:
            return {'records':[], 'done':True}
        if 'Metadata FROM Flow' in q:
            if self.missing:
                raise RuntimeError('secret upstream payload')
            return {'records':[{'Id':FLOW,'MasterLabel':'Account routing','VersionNumber':7,
                'Status':'Active','ProcessType':'AutoLaunchedFlow','Metadata':copy.deepcopy(self.meta)}]}
        count = 26 if self.more else 1
        return {'records':[{'Id':FLOW} for _ in range(count)],'done':True}

    def query(self, q):
        self.calls.append(('data', 'GET', q))
        if 'AccountHistory' in q:
            if self.history_denied:
                raise RuntimeError('secret')
            return {'records':[{'Field':'Owner','OldValue':'Old owner','NewValue':'New owner'}], 'done':True}
        return {'records':[{'Id':IDS[0], 'OwnerId':'005000000000001AAA','Industry':'Tech'}]}


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.sf = DiagnosticSF()

    def diagnose(self, **overrides):
        args = dict(sobject='Account', record_id=IDS[0], field='OwnerId',
                    expected_value='005000000000000AAA', flow_ids=[FLOW])
        args.update(overrides)
        return m.diagnose_flow(self.sf, **args)

    def test_inspection_preserves_conditions_connectors_and_dependencies(self):
        result = m.inspect_flow(self.sf, FLOW)
        self.assertEqual(result['metadata'], META)
        self.assertEqual(result['version'], 7)
        self.assertEqual(len(result['dependencies_not_expanded']), 2)
        self.assertEqual(result['evidence_type'], 'configuration_not_execution')

    def test_discovery_partial_scan_and_object_match(self):
        self.sf.more = True
        result = m.find_flows(self.sf, 'Account')
        self.assertEqual(result['scanned_versions'],25)
        self.assertEqual(result['next_after_id'],FLOW)
        self.assertEqual(len(result['candidates']),25)
        self.assertEqual(m.find_flows(DiagnosticSF(), 'Contact')['candidates'],[])

    def test_discovery_permission_failures_are_not_no_flows(self):
        self.sf.missing = True
        result = m.find_flows(self.sf, 'Account')
        self.assertEqual(len(result['unavailable']),1)
        self.assertNotIn('secret',str(result))

    def test_mismatch_history_and_references_not_causality(self):
        result = self.diagnose()
        self.assertFalse(result['currently_matches_expected'])
        self.assertEqual(result['historical_cause'],'unproven')
        self.assertTrue(result['flows'][0]['target_field_references_not_proven_writes'])
        self.assertIn('Industry',result['current_condition_context']['fields'])
        self.assertEqual(result['history']['records'][0]['Field'],'Owner')
        self.assertTrue(all(c[1]=='GET' for c in self.sf.calls))

    def test_history_permission_failure_keeps_other_evidence(self):
        self.sf.history_denied=True
        result=self.diagnose()
        self.assertIn('unavailable',result['history'])
        self.assertTrue(result['flows'])
        self.assertNotIn('secret',str(result))

    def test_invalid_identifiers_block_before_api_calls(self):
        for args in ({'sobject':"Account' OR Id != null"},{'field':'Owner.Name'},
                     {'record_id':'bad'},{'flow_ids':["bad'"]},{'flow_ids':[]},
                     {'flow_ids':[FLOW]*6},{'expected_value':{}}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.diagnose(**args)
        self.assertEqual(self.sf.calls,[])

    def test_oversized_metadata_is_explicitly_unavailable(self):
        self.sf.meta['description']='x'*250001
        self.assertTrue(m.inspect_flow(self.sf,FLOW)['metadata_omitted_for_size'])
        self.assertEqual(len(m.find_flows(self.sf,'Account')['unavailable']),1)

    def test_mcp_dispatch_available_in_readonly_mode(self):
        with patch.object(m,'READONLY',True), patch.object(m,'get_sf',return_value=self.sf):
            result=asyncio.run(m.call_tool('sf_inspect_flow',{'flow_id':FLOW}))
        self.assertIn('configuration_not_execution',result[0].text)
        names={t.name for t in asyncio.run(m.list_tools())}
        self.assertTrue({'sf_find_flows','sf_inspect_flow','sf_diagnose_flow'} <= names)


if __name__=='__main__':
    unittest.main()

"""受体名单、独立复核与固定输入的实际HTTP串联，全部上游为合成研究。"""
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from modulea.api.server import create_server
from modulea.core.plan_selection_ui import info
from modulea.core.trace_export import build_trace
from contracts import ContractError
from storage import verified_file
from tests.modulea import test_plan_a04_selection_task as selection_fixture
from tests.modulea import test_plan_creation_http as http_fixture


class PlanSelectionUiTests(unittest.TestCase):
    call=http_fixture.PlanCreationHttpTests.call
    close=http_fixture.PlanCreationHttpTests.close
    payload=selection_fixture.PlanA04SelectionTaskTests.payload
    review_payload=selection_fixture.PlanA04SelectionTaskTests.review_payload
    a06_payload=selection_fixture.PlanA04SelectionTaskTests.a06_payload

    def setUp(self):
        selection_fixture.PlanA04SelectionTaskTests.setUp(self)
        self.addCleanup(self.temp.cleanup)
        self.server,self.app=create_server(self.settings,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.base=f'/studies/{self.sid}/analysis-plan'

    def wait_task(self,queued):
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            task=self.app.tasks.get(queued['task']['task_id'])
            if task['state'] not in ('queued','running'):break
            time.sleep(.1)
        self.assertEqual(task['state'],'succeeded',task)

    def test_real_tasks_review_fixed_input_and_revoke(self):
        before=self.workflow.load(self.sid)
        status,view=self.call('GET',self.base+'/selection-ui')
        self.assertEqual(status,200,view);self.assertTrue(view['operations']['selection']['enabled'])
        self.assertFalse(view['operations']['review']['enabled']);self.assertFalse(view['operations']['input']['enabled'])
        status,queued=self.call('POST',self.base+'/a04-selection',self.payload());self.assertEqual(status,202,queued);self.wait_task(queued)
        _,view=self.call('GET',self.base+'/selection-ui');selection=view['selection']
        self.assertEqual(selection['selection']['actual_count'],2);self.assertTrue(view['operations']['review']['enabled'])
        request=self.review_payload(selection['selection_id'])
        status,saved=self.call('POST',self.base+'/a04-selection/'+selection['selection_id']+'/reviews',request)
        self.assertEqual(status,201,saved);review=saved['review']
        _,view=self.call('GET',self.base+'/selection-ui');self.assertTrue(view['operations']['input']['enabled'])
        status,queued=self.call('POST',self.base+'/a06-preparation-input',self.a06_payload(selection,review))
        self.assertEqual(status,202,queued);self.wait_task(queued)
        _,view=self.call('GET',self.base+'/selection-ui')
        self.assertEqual(view['current_input']['packet']['pair_count'],4);self.assertFalse(view['operations']['input']['enabled'])
        status,module=self.call('GET',f'/studies/{self.sid}/modules/A06_PREP')
        self.assertEqual(status,200,module);self.assertIsNone(module['automatic_docking']);self.assertIsNone(module['docking_preparation'])
        status,trace=self.call('GET',f'/studies/{self.sid}/trace/export.json');self.assertEqual(status,200,trace)
        self.assertEqual(len(trace['plan_decisions']['receptor_selections']),1)
        self.assertEqual(trace['plan_decisions']['selection_reviews'][0]['review_id'],review['review_id'])
        self.assertEqual(trace['plan_decisions']['preparation_inputs'][0]['packet']['pair_count'],4)
        after=self.workflow.load(self.sid)
        for key in ('current','runs','reviews'):self.assertEqual(after[key],before[key])
        self.assertEqual(len(self.app.tasks.list(self.sid)),2)
        revoke=self.review_payload(selection['selection_id'],expected_review_id=review['review_id'],decision='pending',note='撤回合成名单通过')
        status,_=self.call('POST',self.base+'/a04-selection/'+selection['selection_id']+'/reviews',revoke)
        self.assertEqual(status,201)
        _,view=self.call('GET',self.base+'/selection-ui');self.assertIsNone(view['current_input']);self.assertFalse(view['operations']['input']['enabled'])

    def test_metadata_is_read_only_pins_actual_network_plan_and_busy(self):
        home=self.workflow.location(self.sid);before=(home/'manifest.json').read_bytes()
        with patch.object(self.workflow,'select_analysis_plan_a04_receptors',side_effect=AssertionError('GET不能计算名单')):
            view=info(self.workflow,self.sid)
        self.assertEqual((home/'manifest.json').read_bytes(),before)
        self.assertEqual(view['expected_plan_id'],self.plan_record['plan_id'])
        self.workflow.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':self.a00,
            'expected_draft_id':self.plan_record['plan_id'],'specification':{'mode':'personalized','parameters':{'a06.receptor_count':1}},
            'author':'隔离测试','note':'新草稿不改变本批'})
        status,view=self.call('GET',self.base+'/selection-ui');self.assertEqual(status,200,view)
        self.assertTrue(view['newer_draft']);self.assertEqual(view['expected_plan_id'],self.plan_record['plan_id'])
        self.assertEqual(view['parameters']['a06.receptor_count'],2)
        with patch.object(self.app.tasks,'active_for',return_value={'state':'running'}):
            _,view=self.call('GET',self.base+'/selection-ui')
        self.assertTrue(all(not op['enabled'] for op in view['operations'].values()))
        self.workflow.set_trashed(self.sid,True,'隔离测试','只读测试')
        _,view=self.call('GET',self.base+'/selection-ui');self.assertTrue(all(not op['enabled'] for op in view['operations'].values()))

    def test_tampered_fixed_input_blocks_trace(self):
        selection=self.workflow.save_analysis_plan_a04_selection(self.sid,self.payload())['record']
        review=self.workflow.review_analysis_plan_a04_selection(self.sid,self.review_payload(selection['selection_id']))['review']
        self.workflow.save_analysis_plan_a06_preparation_input(self.sid,self.a06_payload(selection,review))
        m=self.workflow.load(self.sid)
        path=verified_file(self.workflow.location(self.sid),m['analysis_plan_a06_input_records'][-1])
        path.write_bytes(path.read_bytes()+b'tampered')
        with self.assertRaises(ContractError):build_trace(self.workflow,self.sid,include_data=True)

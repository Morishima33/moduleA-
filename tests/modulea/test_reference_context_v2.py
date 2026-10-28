"""隔离归档上下文复算：实际 Workflow、原准备与口袋决定。"""
from pathlib import Path
import unittest
from uuid import uuid4

from contracts import ContractError
from science_modules.a06 import reference_review
from science_modules.a06.plan_reference_context_v2 import derive_current
from storage import verified_file
from tests.modulea.test_plan_pockets import PocketReviewTests


class ReferenceContextV2Tests(unittest.TestCase):
    def test_current_archives_and_tampering(self):
        base = PocketReviewTests('test_confirmation_revision_preserves_sources_and_na_without_scoring')
        base.setUp()
        self.addCleanup(base.doCleanups)
        workflow, sid = base.workflow, base.sid
        def review(current):
            request = {'expected_input_id': base.input_record['input_id'],
                       'expected_preparation_run_id': current, 'request_id': 'refreq_' + uuid4().hex,
                       'reviewer': '隔离测试', 'note': '不选参考', 'confirmed': True, 'choices': []}
            return reference_review.run(workflow, sid, request, Path(base.base.temp.name), lambda _: None)['review']
        first = review(base.source_run_id)
        before = workflow.load(sid)
        value = derive_current(workflow, sid, first['review_id'])
        self.assertEqual(workflow.load(sid), before)
        self.assertTrue(value['summary']['handoff_blocked'])
        self.assertEqual(value['summary']['scored_pairs'], 0)
        self.assertEqual(value['summary']['ready_pairs'], 0)
        amended = workflow.publish_analysis_plan_a06_pocket_review(sid, base.payload())
        with self.assertRaises((ValueError, KeyError, ContractError)):
            derive_current(workflow, sid, first['review_id'])
        second = review(amended['run_id'])
        value = derive_current(workflow, sid, second['review_id'])
        self.assertEqual(value['summary']['ready_pairs'], 1)
        self.assertEqual(value['receptors'][0]['quality'], '探索')
        self.assertEqual(value['summary']['scored_pairs'], 0)
        entry = workflow.load(sid)['analysis_plan_a06_reference_records'][-1]
        path = verified_file(base.home, entry['decision'])
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaises((ValueError, KeyError, ContractError)):
            derive_current(workflow, sid, second['review_id'])


if __name__ == '__main__':
    unittest.main()

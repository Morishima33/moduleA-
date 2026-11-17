"""实际合成图表归档验证模块投影，不伪造展示回执或修改真实科研材料。"""
from copy import deepcopy
from unittest import TestCase
from contracts import ContractError

from modulea.api.module_display_read import project
from modulea.core import display_revisions as core
from tests.modulea import test_display_revision_core as fixture


class ModuleDisplayReadTests(TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.DisplayRevisionCoreTests.setUpClass.__func__(cls)

    setUp=fixture.DisplayRevisionCoreTests.setUp
    body=fixture.DisplayRevisionCoreTests.body
    publish=fixture.DisplayRevisionCoreTests.publish

    def published_downstream(self):
        manifest=self.w.load(self.sid);rid=manifest['current']['A03']
        if not self.w.approved(manifest,rid):
            self.w.review(self.sid,rid,'approved','明确合成复核','仅隔离复现未变上游与下游运行中')
        revision=self.publish(self.body())
        # 公开begin只建立未发表的合成下游；不填科学结果、validator或人工通过。
        self.w.begin(self.sid,'A04',{}, {'version':'A04.plan_network.1'},'仅合成未发表注册，用于复现下游未归档显示阻断')
        manifest=self.w.load(self.sid);before=deepcopy(manifest)
        whole=core.info(self.w,self.sid)
        self.assertFalse(whole['supported']);self.assertIsNone(whole['current'])
        return revision,manifest

    def test_unchanged_a03_keeps_original_figure_while_unfinished_downstream_blocks_whole_bundle(self):
        revision,manifest=self.published_downstream();before=deepcopy(manifest)
        result=project(self.w,manifest,'A03')
        self.assertIsNotNone(result,'未变A03原图不应因无关下游未归档而消失')
        self.assertEqual(result['module_id'],'A03')
        record=result['record'];self.assertEqual(record['revision_id'],revision['revision_id'])
        self.assertFalse(record['matches_input'])
        self.assertEqual({figure['module_id'] for figure in record['figures']},{'A03'})
        self.assertTrue(record['figures'])
        self.assertFalse(any(row['module_id']=='A06' for row in record['tables']))
        self.assertEqual(self.w.load(self.sid),before)
        self.assertFalse(list(self.home.rglob('*.docx')))

    def test_scientific_hold_or_rejection_blocks_projection_even_if_run_number_is_unchanged(self):
        _,manifest=self.published_downstream();rid=manifest['current']['A03']
        run=self.w.run(manifest,rid);previous=self.w.latest_review(manifest,run['artifact_id'])
        self.w.review(self.sid,rid,'pending','明确合成复核','只验证不能忽略暂存',previous['review_id'])
        self.assertIsNone(project(self.w,self.w.load(self.sid),'A03'))
        previous=self.w.latest_review(self.w.load(self.sid),run['artifact_id'])
        self.w.review(self.sid,rid,'rejected','明确合成复核','只验证不能忽略退回',previous['review_id'])
        self.assertIsNone(project(self.w,self.w.load(self.sid),'A03'))

    def test_changed_parent_run_does_not_reuse_old_module_figure(self):
        _,manifest=self.published_downstream();old=self.w.run(manifest,manifest['current']['A01'])
        self.w.begin(self.sid,'A01',old['inputs'],old['config'],'明确合成新父版本，尚未发表')
        self.assertIsNone(project(self.w,self.w.load(self.sid),'A03'))

    def test_bad_registered_image_blocks_instead_of_silently_using_older_projection(self):
        revision,manifest=self.published_downstream()
        picture=next(ref for ref in revision['files'] if ref['path'].endswith('.png'))
        (self.home/picture['path']).write_bytes(b'broken image')
        with self.assertRaises(ContractError):project(self.w,manifest,'A03')

    def test_score_report_and_other_modules_never_project_old_matrix_or_conclusion(self):
        _,manifest=self.published_downstream()
        for module in ('A06','A07','A01','A06_PREP'):
            with self.subTest(module=module):self.assertIsNone(project(self.w,manifest,module))

    def test_trash_keeps_original_history_only(self):
        _,manifest=self.published_downstream();manifest=deepcopy(manifest);manifest['trashed']=True
        self.assertIsNone(project(self.w,manifest,'A03'))

    def test_caller_mutation_and_repeated_reads_do_not_change_original_receipt_or_outputs(self):
        revision,manifest=self.published_downstream()
        references=[*revision['files'],revision['bundle_file'],revision['payload_file'],revision['request_file']]
        before={ref['path']:(self.home/ref['path']).read_bytes() for ref in references}
        first=project(self.w,manifest,'A03');first['record']['figures'].clear()
        second=project(self.w,manifest,'A03');self.assertTrue(second['record']['figures'])
        for name,raw in before.items():self.assertEqual((self.home/name).read_bytes(),raw)

    def test_a05_independent_decision_invalidates_its_basis_without_changing_runs_or_reviews(self):
        """精确验证无关运行版本不变时仍检查独立决定；不伪造一套A05科学产物。"""
        from unittest.mock import patch
        from hashlib import sha256
        from pathlib import Path
        from modulea.api.module_display_read import _a05_basis
        root=Path(__file__).resolve().parents[2]/'src/science_modules/a05'
        source={'run_ids':{'A05':'run_test'},'a05_basis':{'kind':'repository_initial_source',
            'catalog_sha256':sha256((root/'kegg_classification.json').read_bytes()).hexdigest(),
            'lexicon_sha256':sha256((root/'term_translations.json').read_bytes()).hexdigest()}}
        self.assertTrue(_a05_basis(self.w,{'analysis_plan_a05_display_records':[]},source))
        manifest={'analysis_plan_a05_display_records':[{'path':'synthetic_decision.json'}]}
        with patch('modulea.api.module_display_read._json',return_value={'a05_run_id':'run_test','decision':{'excluded_ids':['GO:TEST']}}) as read:
            self.assertFalse(_a05_basis(self.w,manifest,source))
        read.assert_called_once()

    def test_current_module_view_exposes_module_record_without_changing_whole_eligibility(self):
        _,manifest=self.published_downstream()
        from modulea.config import Settings
        from modulea.api.server import App
        app=App(Settings(data_root=self.root,runtime_dir=self.root/'module_http_runtime'))
        before=deepcopy(manifest)
        value=app._json_read(self.sid,app.views.module,self.sid,'A03')
        self.assertIsNotNone(value['display_revision'],'当前模块页面还未接回已核图表')
        info=value['display_revision'];self.assertFalse(info['supported']);self.assertFalse(info['enabled'])
        self.assertIsNone(info['current']);self.assertIsNone(info['expected_input_hash'])
        self.assertEqual(info['module_current']['module_id'],'A03')
        self.assertEqual(self.w.load(self.sid),before);self.assertEqual(app.tasks.list(self.sid),[])

    def test_review_with_matching_artifact_but_wrong_run_is_rejected_not_ignored(self):
        from unittest.mock import patch
        from modulea.api.module_display_read import _reviews
        _,manifest=self.published_downstream();rid=manifest['current']['A03']
        artifact=self.w.run(manifest,rid)['artifact_id']
        with patch('modulea.api.module_display_read._json',return_value={'run_id':'run_wrong','artifact_id':artifact,'decision':'pending'}):
            with self.assertRaises(ContractError):_reviews(self.w,manifest,[{'path':'synthetic_bad_review.json'}],{'A03':rid})

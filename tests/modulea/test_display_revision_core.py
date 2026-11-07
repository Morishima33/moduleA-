"""独立展示修订公开入口与检查点回归；合成研究实际生成PNG/SVG，绝不生成Word。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import json
import os
import shutil
import unittest

from contracts import ContractError
from storage import read_json, verified_file
from modulea.core import display_revisions as revision, system_validation
from modulea.core.kernel import full_workflow
from science_modules import presentation_revision_v2 as presentation_revision
from tests.modulea.plan_report_fixture import prepare


class DisplayRevisionCoreTests(unittest.TestCase):
    """上游由真实三库/五库与科学验证器建立，各故障用独立临时拷贝隔离。"""

    @classmethod
    def setUpClass(cls):
        try:
            import PIL
        except ImportError as error:
            raise unittest.SkipTest('真实图件回归需要现有科学环境中的Pillow') from error
        if len(revision._fonts())!=2:
            raise unittest.SkipTest('真实中文图件回归需要现有微软雅黑常规和粗体字体')
        cls.seed=TemporaryDirectory(prefix='display_revision_core_seed_');cls.addClassCleanup(cls.seed.cleanup)
        cls.seed_root=Path(cls.seed.name)
        w,cls.sid,_,_=prepare(cls.seed_root,empty=True)
        for module in ('A00','A01','A02','A03'):
            expected=system_validation.request(w,cls.sid,w.load(cls.sid)['current'][module])
            value=w.validate_analysis_plan_scientific_run(cls.sid,
                {key:expected[key] for key in ('expected_run_id','expected_input_hash')}
                |{'request_id':'syscheckreq_'+uuid4().hex})
            if not value['passed']:
                raise AssertionError((module,value['error_zh']))

    def setUp(self):
        self.temp=TemporaryDirectory(prefix='display_revision_core_case_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';shutil.copytree(self.seed_root,self.root)
        self.w=full_workflow(self.root);self.home=self.w.location(self.sid)

    def body(self):
        """仅使用公开资格和用户意愿五字段，不传图片、参数、科学结论或审批标记。"""
        info=self.w.analysis_plan_display_revision_info(self.sid)
        return {'request_id':'displayreq_'+uuid4().hex,'expected_input_hash':info['expected_input_hash'],
                'author':'明确合成展示测试','note':'实际同批展示技术核查，不是人工科研验收','confirmed':True}

    def publish(self,body):
        return self.w.publish_analysis_plan_display_revision(self.sid,body)

    def scientific_state(self):
        """只比较科学状态三项，展示请求、候选和诊断应另行追加。"""
        m=self.w.load(self.sid)
        return {key:deepcopy(m[key]) for key in ('current','runs','reviews')}

    def file_snapshot(self):
        """研究索引允许追加展示登记；此前所有其他归档原字节应保持。"""
        return {path.relative_to(self.home).as_posix():sha256(path.read_bytes()).hexdigest()
                for path in self.home.rglob('*') if path.is_file() and path.name!='manifest.json'}

    def source_attachment(self):
        """挑出真实A03已登记的展示源附件；不改run/result JSON来冒充损坏场景。"""
        m=self.w.load(self.sid);result=self.w.result(m,m['current']['A03'])
        return verified_file(self.home,next(ref for ref in result['files'] if ref['path'].endswith('.csv')))

    def create_candidate_then_fail_publication(self,body):
        """仅在最终回执落盘故障，真实图件与candidate已经成功保存。"""
        original=revision.write_json;failed=[]
        def write(path,value):
            path=Path(path)
            if path.name.startswith('displayrev_') and path.parent.name==body['request_id']:
                failed.append(True)
                raise OSError('explicit synthetic receipt write failure')
            return original(path,value)
        with patch.object(revision,'write_json',side_effect=write):
            with self.assertRaisesRegex(OSError,'receipt write failure'):
                self.publish(body)
        self.assertEqual(failed,[True])
        m=self.w.load(self.sid)
        self.assertEqual(len(m[revision.CANDIDATES]),1)
        self.assertEqual(len(m[revision.FAILURES]),1)
        self.assertFalse(m.get(revision.INDEX))
        return revision.read_record(self.w,m,m[revision.CANDIDATES][0])

    def test_info_and_real_empty_publish_keep_science_and_all_old_files_without_word(self):
        before=self.scientific_state();files=self.file_snapshot();manifest=(self.home/'manifest.json').read_bytes()
        with patch.object(presentation_revision,'build_bundle',wraps=presentation_revision.build_bundle) as build:
            info=self.w.analysis_plan_display_revision_info(self.sid)
            self.assertTrue(info['supported']);self.assertTrue(info['enabled']);self.assertIsNone(info['current'])
            self.assertEqual(info['schema_version'],'ModuleA.display_revision.1')
            self.assertEqual((self.home/'manifest.json').read_bytes(),manifest);build.assert_not_called()
            result=self.publish(self.body());self.assertEqual(build.call_count,1)
        self.assertTrue(result['created']);self.assertFalse(result['human_review_written'])
        self.assertFalse(result['scientific_results_changed'])
        self.assertEqual(self.scientific_state(),before)
        after_files=self.file_snapshot()
        self.assertEqual(files,{key:after_files[key] for key in files})
        self.assertEqual(list(self.home.rglob('*.docx')),[])
        m=self.w.load(self.sid);bundle=read_json(verified_file(self.home,result['bundle_file']))
        self.assertEqual(len(bundle['figures']),1);self.assertEqual(bundle['counts']['a03']['intersection'],0)
        self.assertEqual({row['module'] for row in bundle['figures']},{'A03'})
        self.assertEqual(len(m[revision.REQUESTS]),1);self.assertEqual(len(m[revision.CANDIDATES]),1)
        self.assertEqual(len(m[revision.INDEX]),1)
        for ref in result['files']+result['implementation_files']:
            verified_file(self.home,ref)
        info=self.w.analysis_plan_display_revision_info(self.sid)
        self.assertFalse(info['enabled']);self.assertEqual(info['current']['revision_id'],result['revision_id'])

    def test_same_request_is_idempotent_and_changed_content_cannot_reuse_id(self):
        body=self.body();first=self.publish(body);m_before=self.w.load(self.sid)
        with patch.object(presentation_revision,'build_bundle',side_effect=AssertionError('重复请求不能再绘图')):
            second=self.publish(body)
        self.assertFalse(second['created']);self.assertEqual(second['revision_id'],first['revision_id'])
        self.assertEqual(self.w.load(self.sid),m_before)
        with self.assertRaises(ContractError):self.publish(body|{'note':'同编号其他依据'})
        self.assertEqual(self.w.load(self.sid),m_before)

    def test_failed_render_retains_diagnostic_and_retry_uses_new_attempt(self):
        body=self.body();before=self.scientific_state();partial=[]
        def fail(payload,a03,folder,**kwargs):
            path=Path(folder);path.mkdir();marker=path/'partial_failure.txt'
            marker.write_text('explicit synthetic failed renderer',encoding='utf-8');partial.append(marker)
            raise OSError('explicit synthetic image failure')
        with patch.object(presentation_revision,'build_bundle',side_effect=fail):
            with self.assertRaisesRegex(OSError,'image failure'):self.publish(body)
        m=self.w.load(self.sid);self.assertFalse(m.get(revision.INDEX));self.assertFalse(m.get(revision.CANDIDATES))
        self.assertEqual(len(m[revision.FAILURES]),1)
        diagnostic=read_json(verified_file(self.home,m[revision.FAILURES][0]))
        self.assertIn('image failure',diagnostic['error_zh']);self.assertTrue(partial[0].is_file())
        result=self.publish(body);after=self.w.load(self.sid)
        self.assertTrue(result['created']);self.assertEqual(self.scientific_state(),before)
        self.assertEqual(len(after[revision.REQUESTS]),1);self.assertEqual(len(after[revision.FAILURES]),1)
        self.assertEqual(len(list((partial[0].parents[2]).iterdir())),2)
        self.assertTrue(partial[0].is_file());self.assertEqual(list(self.home.rglob('*.docx')),[])

    def test_successful_candidate_recovers_after_receipt_failure_without_redrawing(self):
        body=self.body();before=self.scientific_state();candidate=self.create_candidate_then_fail_publication(body)
        with patch.object(presentation_revision,'build_bundle',side_effect=AssertionError('成功候选恢复不能重绘')):
            result=self.publish(body)
        self.assertEqual(result['revision_id'],candidate['revision_id']);self.assertEqual(self.scientific_state(),before)
        m=self.w.load(self.sid);self.assertEqual(len(m[revision.CANDIDATES]),1)
        self.assertEqual(len(m[revision.FAILURES]),1);self.assertEqual(len(m[revision.INDEX]),1)

    def test_candidate_with_corrupt_output_cannot_recover_or_silently_regenerate(self):
        body=self.body();candidate=self.create_candidate_then_fail_publication(body)
        path=verified_file(self.home,candidate['files'][0]);path.write_bytes(path.read_bytes()+b'corrupt')
        with patch.object(presentation_revision,'build_bundle',side_effect=AssertionError('损坏检查点不能静默重做')):
            with self.assertRaises(ContractError):self.publish(body)
        self.assertFalse(self.w.load(self.sid).get(revision.INDEX))

    def test_unpublished_candidate_rejects_changed_implementation_or_user_review(self):
        body=self.body();self.create_candidate_then_fail_publication(body)
        implementation=revision._implementation();implementation[next(iter(implementation))]='0'*64
        with patch.object(revision,'_implementation',return_value=implementation),patch.object(
                presentation_revision,'build_bundle',side_effect=AssertionError('实现变化不得重用候选')):
            with self.assertRaises(ContractError):self.publish(body)
        m=self.w.load(self.sid);rid=m['current']['A01']
        review=self.w.latest_review(m,self.w.run(m,rid)['artifact_id'])
        self.w.review(self.sid,rid,'pending','明确合成测试复核','候选保存后新增暂存意见',review['review_id'])
        with patch.object(presentation_revision,'build_bundle',side_effect=AssertionError('用户暂存不得恢复发表')):
            with self.assertRaises(ContractError):self.publish(body)
        self.assertFalse(self.w.load(self.sid).get(revision.INDEX))

    def test_source_corruption_blocks_new_render(self):
        body=self.body();before=self.scientific_state();path=self.source_attachment()
        path.write_bytes(path.read_bytes()+b'corrupt')
        with patch.object(presentation_revision,'build_bundle',side_effect=AssertionError('坏原件不能以重绘掩盖')):
            with self.assertRaises(ContractError):self.publish(body)
        self.assertEqual(self.scientific_state(),before);self.assertFalse(self.w.load(self.sid).get(revision.INDEX))

    def test_source_corruption_also_blocks_successful_candidate_recovery(self):
        body=self.body();self.create_candidate_then_fail_publication(body)
        path=self.source_attachment();path.write_bytes(path.read_bytes()+b'corrupt')
        with patch.object(presentation_revision,'build_bundle',side_effect=AssertionError('原件损坏不能恢复发表')):
            with self.assertRaises(ContractError):self.publish(body)
        self.assertFalse(self.w.load(self.sid).get(revision.INDEX))

    def test_published_same_request_must_not_hide_new_source_corruption(self):
        body=self.body();self.publish(body);path=self.source_attachment();path.write_bytes(path.read_bytes()+b'corrupt')
        with patch.object(presentation_revision,'build_bundle',side_effect=AssertionError('历史幂等只能读取')):
            with self.assertRaises(ContractError):self.publish(body)

    def test_published_output_corruption_is_not_accepted_on_info_or_retry(self):
        body=self.body();result=self.publish(body);path=verified_file(self.home,result['files'][0])
        path.write_bytes(path.read_bytes()+b'corrupt')
        with self.assertRaises(ContractError):self.w.analysis_plan_display_revision_info(self.sid)
        with self.assertRaises(ContractError):self.publish(body)

    def test_stale_request_rejects_implementation_or_font_change_before_render(self):
        body=self.body();impl=revision._implementation();impl[next(iter(impl))]='0'*64
        fonts=revision._fonts();fonts[0]['sha256']='0'*64
        for name,value in (('_implementation',impl),('_fonts',fonts)):
            with self.subTest(name=name),patch.object(revision,name,return_value=value),patch.object(
                    presentation_revision,'build_bundle',side_effect=AssertionError('实现已变化不能按旧指纹执行')):
                with self.assertRaises(ContractError):self.publish(body)
        self.assertFalse(self.w.load(self.sid).get(revision.REQUESTS))

    def test_relevant_review_change_and_new_intake_block_old_request(self):
        body=self.body();m=self.w.load(self.sid);rid=m['current']['A01']
        old=self.w.latest_review(m,self.w.run(m,rid)['artifact_id'])
        self.w.review(self.sid,rid,'pending','明确合成测试复核','仅测试撤回源结果批准',old['review_id'])
        self.assertFalse(self.w.analysis_plan_display_revision_info(self.sid)['enabled'])
        with self.assertRaises(ContractError):self.publish(body)
        self.assertFalse(self.w.load(self.sid).get(revision.INDEX))

    def test_actual_new_intake_blocks_old_binding_without_reusing_old_results(self):
        body=self.body();m=self.w.load(self.sid);a00=m['current']['A00']
        intake=deepcopy(self.w.result(m,a00)['summary']);intake['formula']='明确合成修订方剂'
        self.w.revise_intake(self.sid,intake,'明确合成登记版本变化',a00)
        with patch.object(presentation_revision,'build_bundle',side_effect=AssertionError('不能混入旧下游')):
            with self.assertRaises(ContractError):self.publish(body)
        self.assertFalse(self.w.load(self.sid).get(revision.INDEX))

    def test_source_change_during_render_blocks_publication_and_preserves_user_hold(self):
        body=self.body();original=presentation_revision.build_bundle;changed=[]
        def hold(*args,**kwargs):
            bundle=original(*args,**kwargs);m=self.w.load(self.sid);rid=m['current']['A03']
            self.w.review(self.sid,rid,'pending','明确合成测试复核','绘图期间新增的真实暂存测试意见')
            changed.append(True);return bundle
        with patch.object(presentation_revision,'build_bundle',side_effect=hold):
            with self.assertRaises(ContractError):self.publish(body)
        m=self.w.load(self.sid);self.assertEqual(changed,[True]);self.assertFalse(m.get(revision.INDEX))
        self.assertEqual(len(m[revision.FAILURES]),1)
        self.assertEqual(self.w.latest_review(m,self.w.run(m,m['current']['A03'])['artifact_id'])['decision'],'pending')

    def test_new_pending_plan_does_not_reinterpret_original_bound_scope(self):
        body=self.body();m=self.w.load(self.sid);draft=self.w._analysis_plan_records(m)[-1]
        self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':m['current']['A00'],
            'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a05.go_table_top':25}},
            'author':'明确合成测试','note':'仅下一批草稿，现展示必须保持原参数'})
        self.assertEqual(self.w.analysis_plan_display_revision_info(self.sid)['expected_input_hash'],body['expected_input_hash'])
        result=self.publish(body);payload=read_json(verified_file(self.home,result['payload_file']))
        self.assertEqual(payload['plan']['parameters']['a05.go_table_top'],15)

    def test_client_cannot_inject_scientific_fields_or_bypass_confirmation_or_trash(self):
        body=self.body();before=self.w.load(self.sid)
        for change in ({'confirmed':False},{'confirmed':'true'},{'approved':True},{'threshold':0.1},{'path':'other.svg'},
                       {'request_id':'../displayreq_bad'},{'author':' '},{'expected_input_hash':'old'}):
            with self.subTest(change=change),self.assertRaises(ContractError):self.publish(body|change)
        self.assertEqual(self.w.load(self.sid),before)
        self.w.set_trashed(self.sid,True,'明确合成测试','回收站展示保护')
        with self.assertRaises(ContractError):self.publish(body)
        self.assertFalse(self.w.load(self.sid).get(revision.INDEX))

    def test_implementation_binding_includes_indirect_plot_and_score_label_functions(self):
        actual=revision._implementation()
        self.assertIn('science_modules/a05/plan_figures.py',actual)
        self.assertIn('science_modules/a06/trial_presentation.py',actual)

    def test_explicit_a05_scope_decision_is_not_overwritten_by_automatic_revision(self):
        """真实合成R仅用于准备旧已确认范围；新展示入口必须在绘图之前拒绝覆盖。"""
        from tests.modulea.test_plan_a05 import RSCRIPT,install_source
        from modulea.core import plan_a05,plan_a05_display
        from science_modules.a05.display import english
        if not RSCRIPT.is_file():self.skipTest('未配置现有Rscript，实际旧范围保护回归未执行')
        root=Path(self.temp.name)/'explicit_a05_scope'
        w,sid,draft,_=prepare(root,empty=False,multiple_targets=True)
        w.review(sid,w.load(sid)['current']['A03'],'approved','明确合成测试复核','仅合成A05基线输入')
        install_source(root,draft['plan']);info=plan_a05.info(w,sid)
        with patch.dict(os.environ,{'MODULEA_RSCRIPT':str(RSCRIPT)}):
            w.publish_analysis_plan_a05(sid,{key:info[key] for key in plan_a05.FIELDS-{'reason'}}|{'reason':'旧明确范围保护的实际合成R基线'})
        def a05_body():
            value=plan_a05_display.info(w,sid)
            return {key:value[key] for key in ('expected_a05','expected_display_id','expected_input_hash')}|{
                'request_id':'a05displayreq_'+uuid4().hex,'author':'明确合成范围测试','note':'旧范围基线，不是用户科研复核','confirmed':True}
        w.prepare_analysis_plan_a05_display(sid,a05_body())
        current=plan_a05_display.info(w,sid)['current'];home=w.location(sid)
        source=read_json(verified_file(home,current['source']))
        result=w.result(w.load(sid),current['a05_run_id'])
        rows={row['ID']:row for group in ('bp','cc','mf','kegg') for row in result['tables'][group+'_significant']}
        decisions=[{'ID':tid,'decision':'defer','reason':'明确合成范围暂缓，原统计保持'}
                   for tid,value in source['assessments'].items() if value['classification_status']=='uncertain']
        translations=[{'ID':tid,'english':english(row),'zh':'合成核译测试 '+tid,'reason':'明确合成译名，不冒充正式科学核译'} for tid,row in rows.items()]
        old=w.confirm_analysis_plan_a05_display(sid,a05_body()|{'excluded_ids':[],'uncertain_decisions':decisions,'translations':translations})
        before=w.load(sid);old_scope=deepcopy(old['presentation']);info=w.analysis_plan_display_revision_info(sid)
        self.assertFalse(info['enabled']);self.assertIn('独立富集范围决定','；'.join(info['blockers']))
        with patch.object(presentation_revision,'build_bundle',side_effect=AssertionError('不能覆盖已确认范围')):
            with self.assertRaises(ContractError):
                w.publish_analysis_plan_display_revision(sid,{'request_id':'displayreq_'+uuid4().hex,
                    'expected_input_hash':info['expected_input_hash'],'author':'明确合成测试','note':'不能自动覆盖原范围','confirmed':True})
        self.assertEqual(w.load(sid),before)
        self.assertEqual(plan_a05_display.info(w,sid)['current']['presentation'],old_scope)
        self.assertEqual(list(home.rglob('*.docx')),[])


if __name__=='__main__':
    unittest.main()

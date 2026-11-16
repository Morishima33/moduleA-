"""原生生产Workflow的绑定/完整NA/分对象恢复；工具版本探测以明确合成替身隔离。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import platform
import os
import shutil
import struct
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from contracts import ContractError,fingerprint
from modulea.core.kernel import full_workflow
from modulea.core import native_execution as core
from science_modules.a06 import native_execution as science
from storage import new_id
from tests.modulea import test_plan_a04_selection_task as fixture
from tests.modulea import test_plan_pockets as pockets_fixture


class NativeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.PlanA04SelectionTaskTests('test_a06_preparation_v2_archives_bound_config_and_delegates_v1')
        self.base.setUp();self.addCleanup(self.base.tearDown)
        b=self.base;self.sid=b.sid;self.settings=b.settings
        selected=b.workflow.save_analysis_plan_a04_selection(self.sid,b.payload())['record']
        review=b.workflow.review_analysis_plan_a04_selection(self.sid,b.review_payload(selected['selection_id']))['review']
        self.input=b.workflow.save_analysis_plan_a06_preparation_input(self.sid,b.a06_payload(selected,review))['record']
        self.w=full_workflow(self.settings.data_root)
        self.before=self.w.load(self.sid)
        self.body={'request_id':new_id('nativeprep'),'expected_input_id':self.input['input_id'],
            'expected_preparation_run_id':None,'platform_protocol':core.SCORING,'author':'合成测试','note':'明确原生协议，非科研结果','confirmed':True}
        binary=Path(b.temp.name)/'native-binary'
        if platform.system()=='Darwin':
            cpu=0x100000c if platform.machine()=='arm64' else 0x1000007
            raw=b'\xcf\xfa\xed\xfe'+struct.pack('<I',cpu)+b'fixture never executed'
        else:
            raw=bytearray(256);raw[:2]=b'MZ';raw[60:64]=(128).to_bytes(4,'little');raw[132:134]=(0x8664).to_bytes(2,'little');raw=bytes(raw)
        binary.write_bytes(raw);binary.chmod(0o700)
        signature={'schema_version':core.SCORING,'system':platform.system(),
            'machine':{'AMD64':'x86_64'}.get(platform.machine(),platform.machine()),'files':{},'fixture_only':True}
        self.signature=signature;self.version=fingerprint(signature)
        owner=self
        class Tools:
            def __init__(self,settings):
                self.settings=settings;self.vina=binary;self.signature_value=signature;self.signature_sha256=owner.version
                self.profile={'system':platform.system(),'vina':{'sha256':sha256(raw).hexdigest()}}
            def copy_vina(self,home,folder,*,name=None):
                p=Path(folder)/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(binary,p);return p
            def verify_current(self):pass
            def prepare_receptor(self,*args,**kwargs):raise AssertionError('NA不得执行准备')
            def predict_twice(self,*args,**kwargs):raise AssertionError('NA不得预测口袋')
        self.enterContext(patch.object(science,'NativeTools',Tools))
        self.connects=0
        def connection(home,packet,folder,progress):
            self.connects+=1
            return {'id':'fixture','files':[],
                'compounds':[dict(r,state='NA',reason_zh='合成官方资料不可用') for r in packet['compounds']],
                'receptors':[dict(r,state='NA',reason_zh='合成结构不可用',candidates=[]) for r in packet['receptors']]}
        self.enterContext(patch.object(science.preparation,'connect',side_effect=connection))

    def execute(self):
        return self.w.execute_native_preparation(self.sid,self.body,settings=self.settings)

    def test_new_protocol_full_matrix_keeps_na_and_never_auto_approves(self):
        result=self.execute();m=self.w.load(self.sid);run=self.w.run(m,result['run_id'])
        self.assertEqual(run['config']['version'],core.PREPARATION)
        self.assertEqual(result['summary']['pair_count'],4)
        self.assertEqual(result['summary']['na_pairs'],4)
        self.assertEqual(m['reviews'],self.before['reviews'])
        self.assertFalse(self.w.approved(m,result['run_id']))
        self.assertEqual(self.execute(),result)
        self.assertEqual(self.connects,1)

    def test_publication_interruption_reuses_registered_objects_without_refetch(self):
        original=self.w.validators['A06_PREP']
        def stop(*args):
            original(*args)
            raise RuntimeError('合成发表中断')
        with patch.dict(self.w.validators,{'A06_PREP':stop}):
            with self.assertRaises(RuntimeError):self.execute()
        m=self.w.load(self.sid);rid=m['current']['A06_PREP']
        self.assertIsNone(m['runs'][rid]['result_file'])
        result=self.execute()
        self.assertEqual(result['run_id'],rid);self.assertEqual(self.connects,1)

    def test_changed_tools_and_missing_original_object_remain_blocked(self):
        result=self.execute()
        self.version='0'*64
        with self.assertRaises(ContractError):self.execute()
        self.version=fingerprint(self.signature)
        m=self.w.load(self.sid);ref=m[core.CHECKPOINTS][0]
        (self.w.location(self.sid)/ref['path']).unlink()
        with self.assertRaises(ContractError):self.execute()

    def ready_preparation(self):
        """合成受体/预测，真实Meeko与生产资格校验；明确隔离于实际工具链实测。"""
        helper=pockets_fixture.PocketReviewTests();helper.packet=self.input['packet']
        prepared={}
        # 实际参数仍由已确认方案配置取得，测试不改任何科学阈值。
        from science_modules.a06.plan_preparation_v2 import current_input
        _,_,plan=current_input(self.w,self.sid,self.input['input_id'])
        def connect(home,packet,folder,progress):
            value=helper.connect(home,packet,folder,progress)
            prepared['compounds'],prepared['receptors']=helper.prepare(home,value,folder/'fixture_objects',None,progress,
                science.preparation_config(plan,self.version))
            return value
        def subset(home,value,*args):
            return ([r for r in prepared['compounds'] if r['compound_id'] in {x['compound_id'] for x in value['compounds']}],
                    [r for r in prepared['receptors'] if r['target_id'] in {x['target_id'] for x in value['receptors']}])
        with patch.object(science.preparation,'connect',side_effect=connect),patch.object(science.preparation,'prepare',side_effect=subset):
            return self.execute()

    def qualification_body(self,result):
        fact=science.read_json(science.verified_file(self.w.location(self.sid),result['tables']['preparation_packet'][0]))
        return {'request_id':new_id('nativequal'),'platform_protocol':core.SCORING,'expected_input_id':self.input['input_id'],
            'expected_preparation_run_id':result['run_id'],'author':'合成核查人','note':'明确采用合成预测口袋，非研究批准','confirmed':True,
            'decisions':[{'target_id':r['target_id'],'pocket_key':r['attempts'][0]['evidence']['pocket']['pocket_key'] if r['attempts'] else None} for r in fact['receptors']]}

    def test_qualified_preparation_requires_explicit_pocket_and_manual_review(self):
        result=self.ready_preparation();body=self.qualification_body(result)
        before=self.w.load(self.sid)['reviews']
        qualified=self.w.qualify_native_preparation(self.sid,body,settings=self.settings)
        self.assertEqual(qualified['summary']['ready_pairs'],1)
        self.assertEqual(qualified['summary']['na_pairs'],3)
        self.assertFalse(qualified['summary']['handoff_blocked'])
        self.assertEqual(self.w.load(self.sid)['reviews'],before)
        self.assertFalse(self.w.approved(self.w.load(self.sid),qualified['run_id']))
        self.assertEqual(self.w.qualify_native_preparation(self.sid,body,settings=self.settings),qualified)
        self.w.review(self.sid,qualified['run_id'],'approved','实际测试核查人','明确合成测试批准',expected_review=None)
        self.assertTrue(self.w.approved(self.w.load(self.sid),qualified['run_id']))
        view=self.base.app.views.module(self.sid,'A06_PREP')
        self.assertFalse(view['review']['continue']['available'])

    def test_qualify_invalid_selection_does_not_create_false_ready_result(self):
        result=self.ready_preparation();body=self.qualification_body(result)
        body['decisions'][1]['pocket_key']=body['decisions'][0]['pocket_key']
        before=self.w.load(self.sid)
        with self.assertRaises(ContractError):self.w.qualify_native_preparation(self.sid,body,settings=self.settings)
        self.assertEqual(self.w.load(self.sid),before)

    def test_scoring_keeps_full_matrix_actual_model1_and_reuses_after_publication_stop(self):
        """Vina在本单测用固定输出替身，真实命令/Top1/文件校验和生产发表不替换。"""
        result=self.ready_preparation();qualified=self.w.qualify_native_preparation(self.sid,self.qualification_body(result),settings=self.settings)
        review=self.w.review(self.sid,qualified['run_id'],'approved','合成测试','技术夹具显式批准',expected_review=None)
        m=self.w.load(self.sid)
        body={'request_id':new_id('nativescore'),'platform_protocol':core.SCORING,'expected_preparation_run_id':qualified['run_id'],
            'expected_preparation_result_sha256':m['runs'][qualified['run_id']]['result_file']['sha256'],
            'expected_preparation_review_id':review['review_id'],'expected_a06_run_id':None,
            'author':'合成执行人','note':'固定输出只测编排，非真实评分','confirmed':True}
        candidates=[os.environ.get('MODULEA_TEST_FONT',''),'/System/Library/Fonts/Supplemental/Songti.ttc','C:/Windows/Fonts/msyh.ttc']
        font=next((Path(p) for p in candidates if p and Path(p).is_file()),None)
        if font is None:self.skipTest('本平台缺少明确中文测试字体；未验证PNG绘图')
        self.settings.font_regular=font;self.settings.font_bold=font
        calls=[]
        def vina(command,**kwargs):
            calls.append(command)
            ligand=Path(command[command.index('--ligand')+1]).read_text('ascii')
            atoms=[line for line in ligand.splitlines() if line.startswith(('ATOM  ','HETATM'))]
            Path(command[command.index('--out')+1]).write_text('MODEL 1\nREMARK VINA RESULT: -1.25 0 0\n'+'\n'.join(atoms)+'\nENDMDL\n',encoding='ascii')
            return subprocess.CompletedProcess(command,0,'synthetic Vina output','')
        original=self.w.validators['A06']
        def stop(*args):original(*args);raise RuntimeError('合成评分发表中断')
        with patch('subprocess.run',side_effect=vina):
            with patch.dict(self.w.validators,{'A06':stop}),self.assertRaises(RuntimeError):
                self.w.execute_native_scoring(self.sid,body,settings=self.settings)
            scored=self.w.execute_native_scoring(self.sid,body,settings=self.settings)
        self.assertEqual(len(calls),1)
        self.assertEqual(scored['summary']['scored_pairs'],1)
        self.assertEqual(scored['summary']['na_pairs'],3)
        self.assertEqual(scored['tables']['native_scores'][0]['score'],-1.25)
        run=self.w.run(self.w.load(self.sid),scored['run_id'])
        science.scoring_validator(self.w.root,lambda *_:None)(run,scored['summary'],scored['tables'],[],scored['outcome'])
        with self.assertRaises(ContractError):self.w.begin(self.sid,'A07',{}, {},'不得生成新Word')

    def test_native_get_is_readonly_and_missing_configuration_blocks_submission(self):
        from modulea.api.native_execution import info,submit
        from modulea.api.errors import ApiError
        before=self.w.load(self.sid)
        with patch('subprocess.run',side_effect=AssertionError('GET不能运行工具')):
            value=info(self.base.app,SimpleNamespace(),self.sid)
        self.assertTrue(value['supported']);self.assertFalse(any(s['enabled'] for s in value['stages']))
        self.assertEqual(before,self.w.load(self.sid))
        with self.assertRaises(ApiError):submit(self.base.app,SimpleNamespace(json=lambda:self.body),self.sid,'prepare')


if __name__=='__main__':unittest.main()

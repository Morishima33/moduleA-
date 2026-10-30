"""未人工批准的新登记按真实系统证据获取三库原件；官方响应明确合成，不发布科研结果。"""
from pathlib import Path
import gzip,io,json,tempfile,unittest,zipfile
from urllib.error import HTTPError
from unittest.mock import patch
from uuid import uuid4
from contracts import ContractError,fingerprint
from storage import verified_file
from modulea.core.kernel import full_workflow,Kernel
from modulea.config import Settings
from modulea.core.plan_creation import PlanCreation
from modulea.core import system_acquisition as core,plan_a01
from modulea.core.trace_export import build_trace
from science_modules.a01 import plan_acquisition as collection
from science_modules.a01 import uploads
from science_modules.a01.acquisition import HERB_API,TCMSP,BATMAN
from science_modules.a01.plan_screening import screening_parameters
from tests.modulea.test_study_creation import official_fixture
from tests.modulea.test_plan_a01_publication import source_package
from tests.test_a01_acquisition import Response


class OriginalResponseFixture:
    """仅替换网络响应，实际三库收集器、缓存、重试、包装和校验全部执行。"""
    def __init__(self):self.calls=[];self.herb_offline=False

    def __call__(self,request,timeout):
        url=request.full_url;self.calls.append(url)
        if url==HERB_API:
            if self.herb_offline:raise HTTPError(url,503,'明确合成HERB网关故障',{},None)
            p=json.loads(request.data)
            if p['func_name']=='search_api':
                value={'res_data':[['Herb id','Herb pinyin name','Herb Chinese name'],[{'title':'HERB1'},'TEST','测试药']]}
            elif p['func_name']=='browse_api':
                value={'total_num':1,'browse_data':[['Target id','Gene name','Gene alias'],[{'title':'HBTAR1'},'A','']]}
            elif p['label']=='Herb':
                value={'summary':[['Herb id','Herb pinyin name','Herb Chinese name'],['HERB1','TEST','测试药']],
                    'herb_ingredient':[['Ingredient id','Ingredient name'],[{'title':'HBIN1'},'Compound']]}
            else:
                value={'summary':[['Ingredient id','Ingredient name','Molecule formula','TCMSP id','PubChem id'],
                    ['HBIN1','Compound','C1',{'title':'MOL1'},{'title':'1'}]],
                    'ingredient_target':[['Target id','Target name','Database sources'],[{'title':'HBTAR1'},'A','existing']]}
            raw=json.dumps(value,ensure_ascii=False).encode()
        elif url.startswith(BATMAN):
            raw=('Pinyin.Name\tChinese.Name\tLatin.Name\tIngredients\nTEST\t测试药\tTest\tcompound(1)\n'.encode()
                if url.endswith('herb_browse.txt') else gzip.compress(b'PubChem_CID\tIUPAC_name\tknown_target_proteins\n1\tcompound\tA\n'))
        elif url==TCMSP+'tcmsp.php':raw=b'<input name="token" value="fixture">'
        elif url.startswith(TCMSP) and 'qr=' in url:
            raw=b'data:[{"MOL_ID":"MOL1","molecule_name":"Compound","ob":"40","dl":"0.3"}],data:[{"MOL_ID":"MOL1","target_ID":"1","target_name":"Protein A"}]'
        elif url.startswith(TCMSP) and 'tcmspsearch.php' in url:raw='data:[{"herb_cn_name":"测试药","herb_en_name":"Test herb"}]'.encode()
        elif url.startswith(TCMSP) and 'target.php' in url:raw=b'<td>Protein A</td>'
        elif url.startswith('https://rest.uniprot.org/'):
            raw=json.dumps({'results':[{'primaryAccession':'P1','organism':{'taxonId':9606},'genes':[{'geneName':{'value':'A'}}],
                'proteinDescription':{'recommendedName':{'fullName':{'value':'Protein A'}}}}]}).encode()
        else:raise AssertionError('合成响应未覆盖请求：'+url)
        return Response(raw,url)


def synthetic_source(database,herbs,folder,binding,plan,**kwargs):
    """仅生产形状合成ZIP响应，原ZIP安全/药味/完整性解析实际执行。"""
    with zipfile.ZipFile(io.BytesIO(source_package(database))) as archive:files={n:archive.read(n) for n in archive.namelist()}
    meta=json.loads(files['modulea_source.json']);params=screening_parameters(plan)
    if database=='TCMSP':meta['screening_parameters']=params
    files['modulea_source.json']=json.dumps(meta,ensure_ascii=False).encode();output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr(name,data)
    context={'schema_version':collection.VERSION,'binding':binding,'database':database,'herbs':herbs,
        'screening_parameters':params if database=='TCMSP' else None}
    return {'database':database,'format':'source_zip','version':collection.VERSION,'data':output.getvalue(),
        'source_url':{'TCMSP':TCMSP,'HERB':HERB_API,'BATMAN':BATMAN}[database],
        'synthetic_fixture':True,'analysis_plan_source':{'binding_hash':fingerprint(context),**context}}


class SystemAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='system_acquisition_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';service=PlanCreation(Kernel(Settings(data_root=self.root,runtime_dir=Path(self.temp.name)/'rt')))
        body={'intake':{'formula':'合成材料方','herbs':'测试药','disease':'合成病','mesh_term':'Synthetic Disease','mesh_id':'D123456',
            'operator':'明确合成资料获取测试','analysis_purpose':'workflow_test'},'specification':{'mode':'standard'}}
        with patch('modulea.core.plan_creation.verify_mesh_identity',side_effect=official_fixture):
            preflight=service.preflight(body);created=service.create({'request_id':'plancreate_'+uuid4().hex,
                'preflight_id':preflight['preflight_id'],'expected_input_hash':preflight['input_hash'],'confirmed':True})
        self.sid=created['study_id'];self.w=full_workflow(self.root);self.before=self.w.load(self.sid);info=core.info(self.w,self.sid)
        self.body={k:info[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')}|{
            'request_id':'systemacqreq_'+uuid4().hex,'author':'明确合成材料测试','note':'三库原件获取，不作为科研结果或人工复核','confirmed':True}

    def execute(self):return self.w.acquire_analysis_plan_system_a01_sources(self.sid,self.body)

    def test_real_system_receipt_allows_originals_without_fake_approval_or_scientific_publication(self):
        self.assertFalse(self.w.approved(self.before,self.before['current']['A00']))
        self.assertFalse(plan_a01.info(self.w,self.sid)['acquire_enabled'])
        with patch.object(collection,'acquire_for_plan',side_effect=synthetic_source):result=self.execute()
        m=self.w.load(self.sid);self.assertEqual(result['state'],'complete');self.assertEqual(len(result['sources']),3)
        self.assertEqual(m['current'],self.before['current']);self.assertEqual(m['runs'],self.before['runs']);self.assertEqual(m['reviews'],[])
        self.assertNotIn('current_component_uploads',m);self.assertFalse(self.w.approved(m,m['current']['A00']))
        self.assertFalse(result['a01_published']);trace=build_trace(self.w,self.sid)
        self.assertEqual(len(trace['plan_decisions']['system_acquisitions']),1);self.assertEqual(len(trace['plan_decisions']['system_acquisition_requests']),1)

    def test_partial_failure_retains_success_then_explicit_retry_fetches_only_missing_and_complete_is_idempotent(self):
        def partial(db,*args,**kwargs):
            if db=='HERB':raise ContractError('明确合成HERB网关失败')
            return synthetic_source(db,*args,**kwargs)
        with patch.object(collection,'acquire_for_plan',side_effect=partial):first=self.execute()
        self.assertEqual(first['state'],'partial_failure');saved={r['database']:r['archive'] for r in first['sources'] if r['state']=='ready'};calls=[]
        def retry(db,*args,**kwargs):calls.append(db);return synthetic_source(db,*args,**kwargs)
        with patch.object(collection,'acquire_for_plan',side_effect=retry):second=self.execute()
        self.assertEqual(calls,['HERB']);self.assertEqual(second['state'],'complete')
        for row in second['sources']:
            if row['database'] in saved:self.assertEqual(row['archive'],saved[row['database']]);verified_file(self.w.location(self.sid),row['archive'])
        with patch.object(collection,'acquire_for_plan',side_effect=AssertionError('完整原件不能再次获取')):self.assertEqual(self.execute(),second)
        m=self.w.load(self.sid);self.assertEqual(len(m[core.REQUESTS]),1);self.assertEqual(len(m[core.RECORDS]),2)
        self.assertEqual(m['current'],self.before['current']);self.assertEqual(m['reviews'],[])
        build_trace(self.w,self.sid)

    def test_later_draft_during_sources_keeps_original_parameters(self):
        changed=[]
        def collect(db,*args,**kwargs):
            if not changed:
                draft=self.w.analysis_plan_info(self.sid)['draft']
                self.w.save_analysis_plan_draft(self.sid,{'request_id':'planreq_'+uuid4().hex,'expected_a00':self.before['current']['A00'],
                    'expected_draft_id':draft['plan_id'],'specification':{'mode':'personalized','parameters':{'a01.ob_min':45}},
                    'author':'明确合成测试','note':'后来草稿不能替换已开始获取参数'});changed.append(True)
            return synthetic_source(db,*args,**kwargs)
        with patch.object(collection,'acquire_for_plan',side_effect=collect):result=self.execute()
        tcmsp=next(r for r in result['sources'] if r['database']=='TCMSP')
        self.assertEqual(tcmsp['source']['analysis_plan_source']['screening_parameters']['ob_min'],30)
        self.assertEqual(self.w.analysis_plan_info(self.sid)['draft']['plan']['parameters']['a01.ob_min'],45)

    def test_corrupt_success_archive_is_not_hidden_by_refetch(self):
        with patch.object(collection,'acquire_for_plan',side_effect=synthetic_source):result=self.execute()
        path=verified_file(self.w.location(self.sid),result['sources'][0]['archive']);path.write_bytes(path.read_bytes()+b'CORRUPT')
        with patch.object(collection,'acquire_for_plan',side_effect=AssertionError('损坏原件不能重下掩盖')),self.assertRaises(ContractError):self.execute()

    def test_human_hold_during_fetch_stops_next_source_and_retains_failure_evidence(self):
        calls=[]
        def hold(db,*args,**kwargs):
            calls.append(db);self.w.review(self.sid,self.before['current']['A00'],'pending','明确合成测试','获取期间暂停登记')
            return synthetic_source(db,*args,**kwargs)
        with patch.object(collection,'acquire_for_plan',side_effect=hold),self.assertRaises(ContractError):self.execute()
        self.assertEqual(calls,['TCMSP']);m=self.w.load(self.sid);self.assertEqual(m['current'],self.before['current'])
        trace=build_trace(self.w,self.sid);failure=trace['plan_decisions']['system_acquisition_failures'][-1]
        self.assertTrue(failure['files']);self.assertEqual(failure['state'],'failed');self.assertNotIn(core.RECORDS,m)

    def test_no_confirmation_stale_or_client_override_does_not_create_request(self):
        for change in ({'confirmed':False},{'passed':True},{'path':'outside'},{'ob_min':0},{'expected_input_hash':'old'}):
            with self.subTest(change=change),self.assertRaises(ContractError):self.w.acquire_analysis_plan_system_a01_sources(self.sid,self.body|change)
        self.assertEqual(self.w.load(self.sid),self.before)

    def test_interrupted_before_batch_record_reuses_immediately_archived_library(self):
        def interrupt(db,*args,**kwargs):
            if db=='HERB':raise KeyboardInterrupt('合成进程中断，不返回整批记录')
            return synthetic_source(db,*args,**kwargs)
        with patch.object(collection,'acquire_for_plan',side_effect=interrupt),self.assertRaises(KeyboardInterrupt):self.execute()
        m=self.w.load(self.sid);self.assertNotIn(core.RECORDS,m);self.assertEqual(len(m[core.SOURCES]),1)
        first=core.read_record(self.w,m,m[core.SOURCES][0],kind='source');saved=first['source']['archive'];calls=[]
        def resume(db,*args,**kwargs):calls.append(db);return synthetic_source(db,*args,**kwargs)
        with patch.object(collection,'acquire_for_plan',side_effect=resume):result=self.execute()
        self.assertEqual(calls,['HERB','BATMAN']);self.assertEqual(result['state'],'complete')
        self.assertEqual(result['sources'][0]['archive'],saved);verified_file(self.w.location(self.sid),saved)
        self.assertEqual(len(build_trace(self.w,self.sid)['plan_decisions']['system_acquisition_sources']),3)

    def test_parallel_request_cannot_start_another_collector_for_same_study(self):
        attempts=[]
        def collect(db,*args,**kwargs):
            if not attempts:
                attempts.append(True)
                with self.assertRaises(ContractError):self.execute()
            return synthetic_source(db,*args,**kwargs)
        with patch.object(collection,'acquire_for_plan',side_effect=collect):result=self.execute()
        self.assertEqual(result['state'],'complete');self.assertEqual(len(self.w.load(self.sid)[core.REQUESTS]),1)

    def test_downloaded_wrong_a01_binding_is_failed_and_original_retained(self):
        def mismatched(db,herbs,folder,binding,plan,**kwargs):
            if db=='TCMSP':binding={**binding,'a01_run':'run_other'}
            return synthetic_source(db,herbs,folder,binding,plan,**kwargs)
        with patch.object(collection,'acquire_for_plan',side_effect=mismatched):result=self.execute()
        self.assertEqual(result['state'],'partial_failure');self.assertEqual(result['sources'][0]['state'],'failed')
        self.assertIn('原A01绑定',result['sources'][0]['reason_zh']);self.assertEqual(len(result['source_receipts']),2)
        retained=[r for r in result['files'] if r['path'].endswith('/original.zip')]
        self.assertEqual(len(retained),3)

    def test_staged_manual_originals_are_reused_without_network_and_keep_pointer(self):
        self.w.review(self.sid,self.before['current']['A00'],'approved','合成旧上传准备','仅在隔离测试允许旧stage')
        for db in uploads.DATABASES:
            m=self.w.load(self.sid)
            uploads.stage(self.w,self.sid,m['current']['A00'],m['current'].get('A01',''),
                (m.get('current_component_uploads') or {}).get('sha256',''),
                {'database':db,'format':'source_zip','version':'synthetic-manual-v1','data':source_package(db)},self.root/'parse')
        before=self.w.load(self.sid);info=core.info(self.w,self.sid)
        self.body.update({key:info[key] for key in ('expected_a00','expected_plan_id','expected_input_hash')})
        with patch.object(collection,'acquire_for_plan',side_effect=AssertionError('已有原件不联网')):result=self.execute()
        self.assertEqual(result['state'],'complete');self.assertTrue(all(r['mode']=='existing' for r in result['sources']))
        self.assertEqual(result['source_receipts'],[]);after=self.w.load(self.sid)
        for key in ('current_component_uploads','current','runs','reviews'):self.assertEqual(after[key],before[key])

    def test_actual_three_collectors_retry_and_cache_with_only_synthetic_network(self):
        response=OriginalResponseFixture();response.herb_offline=True
        first=self.w.acquire_analysis_plan_system_a01_sources(self.sid,self.body,opener=response,sleeper=lambda _:None)
        self.assertEqual(first['state'],'partial_failure');self.assertEqual(response.calls.count(HERB_API),5)
        before=list(response.calls);response.herb_offline=False
        second=self.w.acquire_analysis_plan_system_a01_sources(self.sid,self.body,opener=response,sleeper=lambda _:None)
        self.assertEqual(second['state'],'complete');self.assertTrue(all(url==HERB_API for url in response.calls[len(before):]))
        requests=len(response.calls)
        third=self.w.acquire_analysis_plan_system_a01_sources(self.sid,self.body,opener=response,sleeper=lambda _:None)
        self.assertEqual(second,third);self.assertEqual(len(response.calls),requests)
        self.assertEqual(self.w.load(self.sid)['reviews'],[]);build_trace(self.w,self.sid)

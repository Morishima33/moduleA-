"""用合成研究先复现批注改变原件SHA，验证精确恢复、保全、中断恢复和HTTP。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import http.client
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from contracts import ContractError
from storage import verified_file
from modulea.core.kernel import full_workflow
from modulea.core import report_archive_repair as repair, plan_reports
from tests.modulea import test_plan_report_revision as seed


def annotated(raw, changed_text=False):
    """合成真实OOXML批注及其锚点；正文修改场景必须另外拒绝。"""
    with ZipFile(BytesIO(raw)) as archive:
        parts={name:archive.read(name) for name in archive.namelist()}
    w='{'+repair.W+'}';tree=ET.fromstring(parts['word/document.xml'])
    first=tree.find('.//'+w+'p');first.insert(0,ET.Element(w+'commentRangeStart',{w+'id':'0'}))
    first.append(ET.Element(w+'commentRangeEnd',{w+'id':'0'}));run=ET.SubElement(first,w+'r')
    ET.SubElement(run,w+'commentReference',{w+'id':'0'})
    if changed_text:tree.find('.//'+w+'t').text='不同的科学正文，不能作为仅批注恢复'
    parts['word/document.xml']=ET.tostring(tree)
    comments=ET.Element(w+'comments');comment=ET.SubElement(comments,w+'comment',{w+'id':'0',w+'author':'合成核查者'})
    ET.SubElement(ET.SubElement(ET.SubElement(comment,w+'p'),w+'r'),w+'t').text='合成批注必须保留'
    parts['word/comments.xml']=ET.tostring(comments)
    # Word另加的空系统脚注分隔符不属于研究正文。
    notes=ET.Element(w+'footnotes');note=ET.SubElement(notes,w+'footnote',{w+'id':'-1',w+'type':'separator'})
    ET.SubElement(ET.SubElement(note,w+'p'),w+'separator');parts['word/footnotes.xml']=ET.tostring(notes)
    relationships=ET.fromstring(parts['word/_rels/document.xml.rels'])
    ET.SubElement(relationships,'{http://schemas.openxmlformats.org/package/2006/relationships}Relationship',
        {'Id':'rIdSyntheticComment','Type':repair.R+'/comments','Target':'comments.xml'})
    parts['word/_rels/document.xml.rels']=ET.tostring(relationships)
    types=ET.fromstring(parts['[Content_Types].xml'])
    ET.SubElement(types,'{http://schemas.openxmlformats.org/package/2006/content-types}Override',
        {'PartName':'/word/comments.xml','ContentType':'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml'})
    parts['[Content_Types].xml']=ET.tostring(types)
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,value in parts.items():archive.writestr(name,value)
    return output.getvalue()


class ReportArchiveRepairTests(TestCase):
    @classmethod
    def setUpClass(cls):
        seed.ReportRevisionWorkflowTests.setUpClass.__func__(cls)
        w=cls.workflow;info=plan_reports.info(w,cls.sid)
        result=w.publish_analysis_plan_report(cls.sid,{k:info[k] for k in ('expected_report_run_id','expected_input_hash')} | {
            'request_id':'planreportreq_'+uuid4().hex,'author':'明确合成测试','note':'仅归档恢复测试','confirmed':True})
        cls.rid=result['run_id'];cls.ref=result['tables']['report_files'][1]
        cls.original=verified_file(w.location(cls.sid),cls.ref).read_bytes()
        cls.modified=annotated(cls.original)

    def setUp(self):
        self.temp=TemporaryDirectory(prefix='archive_repair_');self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)/'data';shutil.copytree(self.__class__.root,self.data)
        self.w=full_workflow(self.data);self.home=self.w.location(self.sid)
        self.target=self.home/self.ref['path'];self.target.write_bytes(self.modified)
        self.before=self.w.load(self.sid)
        self.body={'request_id':'reportrepairreq_'+uuid4().hex,'expected_run_id':self.rid,'document_index':1,
            'expected_original_sha256':self.ref['sha256'],'expected_modified_sha256':sha256(self.modified).hexdigest(),
            'author':'明确合成恢复测试','note':'保留批注，精确原件恢复，不改科学结果','confirmed':True}

    def execute(self):
        return self.w.restore_analysis_plan_report_archive(self.sid,self.body,self.original)

    def stable_science(self):
        after=self.w.load(self.sid)
        for key in ('current','runs','reviews'):self.assertEqual(after[key],self.before[key])

    def test_actual_archive_failure_then_restore_and_preserve_all_comment_bytes(self):
        with self.assertRaisesRegex(ContractError,'校验失败'):self.w.view(self.sid)
        value=self.execute();self.stable_science()
        self.assertEqual(self.target.read_bytes(),self.original)
        self.assertEqual(verified_file(self.home,value['annotation_file']).read_bytes(),self.modified)
        self.assertEqual(value['annotation_evidence']['comment_count'],1)
        self.w.view(self.sid)
        again=self.execute();self.assertFalse(again['created']);self.assertEqual(again['repair_id'],value['repair_id'])
        from modulea.core.trace_export import build_trace
        trace=build_trace(self.w,self.sid,include_data=True)
        self.assertEqual(len(trace['plan_decisions']['report_archive_repairs']),1)
        for ref in trace['files']:verified_file(self.home,ref)

    def test_wrong_backup_or_stale_annotated_sha_never_changes_file(self):
        with self.assertRaises(ContractError):self.w.restore_analysis_plan_report_archive(self.sid,self.body,b'wrong')
        self.body['expected_modified_sha256']='0'*64
        with self.assertRaises(ContractError):self.execute()
        self.assertEqual(self.target.read_bytes(),self.modified);self.assertEqual(self.w.load(self.sid),self.before)

    def test_scientific_body_change_is_preserved_and_rejected_as_comments_only(self):
        raw=annotated(self.original,True);self.target.write_bytes(raw);self.body['expected_modified_sha256']=sha256(raw).hexdigest()
        with self.assertRaisesRegex(ContractError,'正文'):self.execute()
        self.assertEqual(self.target.read_bytes(),raw);self.assertEqual(self.w.load(self.sid),self.before)

    def test_interruption_after_preservation_recovers_registered_plan(self):
        with patch.object(repair,'_restore',side_effect=OSError('明确合成中断')),self.assertRaises(OSError):self.execute()
        m=self.w.load(self.sid);self.assertEqual(len(m[repair.REQUESTS]),1);self.assertNotIn(repair.RECEIPTS,m)
        request=repair.read_request(self.w,m,m[repair.REQUESTS][0])
        self.assertEqual(verified_file(self.home,request['annotation_file']).read_bytes(),self.modified)
        self.execute();self.stable_science();self.assertEqual(self.target.read_bytes(),self.original)

    def test_interruption_after_original_restored_finishes_receipt_without_overwriting_annotations(self):
        write=repair.write_json
        def fail(path,*args,**kwargs):
            if Path(path).name=='receipt.json':raise OSError('明确合成回执中断')
            return write(path,*args,**kwargs)
        with patch.object(repair,'write_json',side_effect=fail),self.assertRaises(OSError):self.execute()
        self.assertEqual(self.target.read_bytes(),self.original)
        self.execute();self.stable_science()

    def test_further_external_edit_after_interruption_is_not_overwritten(self):
        with patch.object(repair,'_restore',side_effect=OSError('明确合成中断')),self.assertRaises(OSError):self.execute()
        self.target.write_bytes(b'new external edit')
        with self.assertRaisesRegex(ContractError,'新的修改'):self.execute()
        self.assertEqual(self.target.read_bytes(),b'new external edit')

    def test_invalid_receipt_never_enters_study_index(self):
        write=repair.write_json
        def invalid_receipt(path,value):
            if Path(path).name=='receipt.json':value=dict(value,scientific_results_changed=True)
            return write(path,value)
        with patch.object(repair,'write_json',side_effect=invalid_receipt),self.assertRaises(ContractError):self.execute()
        manifest=self.w.load(self.sid)
        self.assertNotIn(repair.RECEIPTS,manifest);self.stable_science()
        request=repair.read_request(self.w,manifest,manifest[repair.REQUESTS][0])
        self.assertEqual(verified_file(self.home,request['annotation_file']).read_bytes(),self.modified)
        self.assertEqual(self.target.read_bytes(),self.original)
        with self.assertRaises(ContractError):self.execute()
        self.assertNotIn(repair.RECEIPTS,self.w.load(self.sid))

    def test_extra_paths_wrong_run_and_trash_are_rejected(self):
        for field in ('path','sha256','approved'):
            body=dict(self.body,**{field:'not allowed'})
            with self.assertRaises(ContractError):self.w.restore_analysis_plan_report_archive(self.sid,body,self.original)
        body=dict(self.body,expected_run_id='run_'+'0'*32)
        with self.assertRaises(ContractError):self.w.restore_analysis_plan_report_archive(self.sid,body,self.original)
        self.w.set_trashed(self.sid,True,'合成测试','只读保护')
        with self.assertRaisesRegex(ContractError,'只读'):self.execute()
        self.assertEqual(self.target.read_bytes(),self.modified)

    def test_registered_http_download_keeps_exact_comment_bytes_and_rejects_corruption(self):
        value=self.execute()
        from modulea.api.server import create_server
        from modulea.config import Settings
        server,app=create_server(Settings(data_root=self.data,runtime_dir=self.data/'rt'),0)
        Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        def get(url):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=60);c.request('GET',url)
            r=c.getresponse();raw=r.read();status=r.status;c.close();return status,raw
        base='/api/v1/studies/'+self.sid+'/analysis-plan/reports'
        status,raw=get(base);self.assertEqual(status,200,raw[:200])
        downloads=json.loads(raw)['history'][0]['downloads'];self.assertEqual(len(downloads),3)
        url=downloads[-1]['url'];status,raw=get(url);self.assertEqual(status,200);self.assertEqual(raw,self.modified)
        wrong=url.replace(self.rid,'run_'+'0'*32);self.assertEqual(get(wrong)[0],404)
        (self.home/value['annotation_file']['path']).write_bytes(b'corrupted comment file')
        status,raw=get(url);self.assertEqual(status,503)
        self.assertEqual(json.loads(raw)['error']['code'],'ARCHIVE_UNAVAILABLE')

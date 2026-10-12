"""A06草案保存缺陷回归：允许未填完进度，绝不确认或计算；只用隔离研究。"""
from pathlib import Path
from copy import deepcopy
from uuid import uuid4
import unittest,tempfile
from contracts import ContractError
from storage import verified_file
from tests.modulea.test_two_pass import fixture,filled
from modulea.core.two_pass_workflow import preparation_context
from science_modules.a06.plan_adapter import source_context
from science_modules.a06.two_pass_plan import blank

class DraftTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.f,self.sid=fixture(self.root);self.context=source_context(self.f,self.sid,self.f.load(self.sid))
 def tearDown(self):self.temp.cleanup()
 def request(self):
  return {'expected_source':self.context['source_key'],'expected_plan_id':None,'expected_draft_id':None,'draft_id':'draft_'+uuid4().hex,'checked_target_ids':[],'reviewer':'','note':'核查未完成','plan':blank(self.context)}
 def test_save_incomplete_refresh_without_confirming(self):
  req=self.request();req['plan']['receptors'][0]['first']={'source_type':'experimental','pdb_id':'1ABC','uniprot':'P12345','chains':['A'],'pocket':'reference'}
  before=self.f.load(self.sid);saved=self.f.save_two_pass_draft(self.sid,req);m=self.f.load(self.sid);info=preparation_context(self.f,m)
  for k in ('current','runs','reviews'):self.assertEqual(before[k],m[k])
  self.assertEqual(info['plan'],req['plan']);self.assertEqual(info['expected_draft_id'],saved['draft_id']);self.assertIsNone(info['latest']);self.assertFalse(saved['execution_allowed']);self.assertIsNone(saved['approval']);self.assertFalse(info['checks'][0]['valid'])
 def test_retry_stale_write_and_scope_guard(self):
  req=self.request();first=self.f.save_two_pass_draft(self.sid,req);self.assertEqual(self.f.save_two_pass_draft(self.sid,req),first)
  with self.assertRaises(ContractError):self.f.save_two_pass_draft(self.sid,{**req,'note':'不同内容'})
  with self.assertRaises(ContractError):self.f.save_two_pass_draft(self.sid,{**req,'draft_id':'draft_'+uuid4().hex})
  for change in ('source','scope','grade','execution','check','study'):
   bad=self.request();bad['expected_draft_id']=first['draft_id']
   if change=='source':bad['expected_source']='old'
   if change=='scope':bad['plan']['compounds'].pop()
   if change=='grade':bad['plan']['receptors'][0]['candidate_grade']='OTHER'
   if change=='execution':bad['plan']['receptors'][0]['score']=-7
   if change=='check':bad['checked_target_ids']=['OTHER']
   if change=='study':_,other=fixture(self.root)
   with self.assertRaises(ContractError):self.f.save_two_pass_draft(other if change=='study' else self.sid,bad)
 def test_saved_checked_items_not_global_confirmation_and_final_guard(self):
  req=self.request();req['plan']=filled(self.context);req['checked_target_ids']=[r['target_id'] for r in req['plan']['receptors']];saved=self.f.save_two_pass_draft(self.sid,req);m=self.f.load(self.sid);info=preparation_context(self.f,m);self.assertEqual(info['draft']['checked_target_ids'],req['checked_target_ids']);self.assertIsNone(info['latest'])
  final={'expected_source':self.context['source_key'],'expected_plan_id':None,'plan_id':'plan_'+uuid4().hex,'confirmed_target_ids':req['checked_target_ids'],'reviewer':'隔离核查','note':'虚构方案','confirmed':True,'plan':req['plan']}
  with self.assertRaises(ContractError):self.f.save_two_pass(self.sid,final)
  self.f.save_two_pass(self.sid,{**final,'expected_draft_id':saved['draft_id']});info=preparation_context(self.f,self.f.load(self.sid));self.assertIsNone(info['draft']);self.assertIsNotNone(info['latest']);self.assertNotIn('A06',self.f.load(self.sid)['current'])
 def test_new_source_trash_and_tampering(self):
  req=self.request();self.f.save_two_pass_draft(self.sid,req);m=self.f.load(self.sid);path=verified_file(self.f.location(self.sid),m['two_pass_draft_records'][-1]);raw=path.read_bytes();path.write_bytes(raw+b' ')
  with self.assertRaises(ContractError):preparation_context(self.f,m)
  path.write_bytes(raw);rid=m['current']['A03_SELECT'];self.f.review(self.sid,rid,'approved','隔离复核','重新核对',self.context['parent_review_ids']['A03_SELECT']);info=preparation_context(self.f,self.f.load(self.sid));self.assertIsNone(info['draft'])
  with self.assertRaises(ContractError):self.f.save_two_pass_draft(self.sid,req)
  m=self.f.load(self.sid);m['trashed']=True;self.f.save(m)
  with self.assertRaises(ContractError):self.f.save_two_pass_draft(self.sid,req)


# 实际HTTP验证源版本和令牌；不写真实研究。
class DraftHttpTests(unittest.TestCase):
 def test_http_partial_save_and_security(self):
  from modulea.config import Settings
  from modulea.api.server import create_server
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  import threading,json,sys
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);f,sid=fixture(root);ctx=source_context(f,sid,f.load(sid));server,app=create_server(Settings(data_root=root,runtime_dir=root/'runtime',science_python=sys.executable),0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port);endpoint='/api/v1/studies/'+sid+'/modules/A06_PREP/actions/two_pass_draft'
   body={'expected_source':ctx['source_key'],'expected_plan_id':None,'expected_draft_id':None,'checked_target_ids':[],'reviewer':'','note':'未填完HTTP草案','plan':blank(ctx)};before=f.load(sid)
   def call(data,token=True,origin=None):
    headers={'Origin':origin or base,'Content-Type':'application/json'}
    if token:headers['X-ModuleA-Token']=app.token
    with urlopen(Request(base+endpoint,data=json.dumps(data).encode(),headers=headers),timeout=30) as response:return response.status,json.load(response)
   try:
    for data,token,origin,status in [(body,False,None,403),(body,True,'https://foreign.invalid',403),({**body,'expected_source':'old'},True,None,409),({**body,'execution_allowed':True},True,None,422)]:
     with self.assertRaises(HTTPError) as failed:call(data,token,origin)
     self.assertEqual(failed.exception.code,status)
    status,data=call(body);self.assertEqual(status,201);self.assertIsNotNone(data['draft']['draft_id']);self.assertFalse(f.load(sid).get('two_pass_plan_records'))
    with self.assertRaises(HTTPError) as failed:call({**body,'note':'并发旧页面'})
    self.assertEqual(failed.exception.code,409)
    for key in ('current','runs','reviews'):self.assertEqual(before[key],f.load(sid)[key])
   finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()

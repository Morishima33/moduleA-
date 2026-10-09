from pathlib import Path # 仅使用隔离研究目录。
from copy import deepcopy # 构造版本和身份负例。
import tempfile, unittest, sys # 标准测试工具不写真实研究。
from unittest.mock import patch # 测试分派不实际重建Word。
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src')) # 使用新项目实现。
from storage import write_json, read_json, file_record # 生成有指纹的虚构输入。
from contracts import ContractError # 校验失败必须明确报错。
from pathway_review import register_candidate, load_selection, selection_token, review_selection, request_recommendation # 网页后端相同接口。
from pathway_ui import review_page, card, figure_file # 中文显示和受控图下载。
from report_dispatch import run_reports # 检查批准前后报告分派。
from report_dispatch import require_alignment # 完整A07复核不能批准过期通路。

class Flow: # 小型隔离夹具只复现通路依赖的内核方法。
    def __init__(self, root): # 明确夹具科学版本。
        self.root = root # 统一写锁在临时项目内。
        self.manifest = {'study_id':'study_test','current':{'A05':'run_test'},'runs':{'run_test':{'result_file':{'sha256':'a05_test_hash'}}}} # 无真实研究ID。
    def load(self, sid): return deepcopy(self.manifest) # 每次读取独立状态副本。
    def location(self, sid): return self.root/'studies'/sid # 路径限定隔离测试。
    def active(self, manifest, rid): return rid == manifest['current'].get('A05') and not manifest.get('inactive') # 模拟上游失效。
    def result(self, manifest, rid): return {'tables':{'kegg_significant':[{'ID':'hsa_test','Count':1,'p.adjust':0.001,'geneID':'207','gene_symbols':'AKT1'}]}} # 小型真实格式表。
    def run(self, manifest, rid): return {'run_id':rid,'inputs':{}} # 报告接口核对明确富集运行。

class PathwayWebTests(unittest.TestCase): # 验证审核、失效、图件与报告分派。
    def setUp(self): # 每个测试都在独立研究包。
        self.tmp = tempfile.TemporaryDirectory(prefix='moduleA_pathway_review_') # 不进入生产研究目录。
        self.addCleanup(self.tmp.cleanup) # 只清理本次临时目录。
        self.flow = Flow(Path(self.tmp.name)) # 夹具不依赖互联网。
        self.sid = 'study_test' # 固定虚构标识。
        home = self.flow.location(self.sid) # 当前隔离研究目录。
        home.mkdir(parents=True) # 准备附件位置。
        figure = home/'preview.png' # 图下载测试只验证原始字节。
        figure.write_bytes(b'test_image_bytes') # 不冒充科学图件。
        record = file_record(home,figure,'pathway_source') # 必须绑定文件指纹。
        self.data = {'study_id':self.sid,'source_a05_run':'run_test','source_a05_result_sha256':'a05_test_hash','pathway_id':'hsa_test','display_name':'测试通路','count':1,'adjusted_p':0.001,'entrez_ids':['207'],'symbols':['AKT1'],'target_symbol':'AKT1','caption':'红色仅表示命中','paragraphs':['测试说明，不等同疗效。'],'selection_reason':'测试文献与当前命中支持','comparison_note':'不按P值直接认定机制重要性','references':[{'来源':'测试出处'}],'native_figure':record,'files':[record],'assistant_qa':{'checked':True,'note':'隔离测试图件检查'}} # 可完整登记的候选格式。
    def register(self): return register_candidate(self.flow,self.sid,self.data) # 共用准备动作。
    def review(self, decision='approved', confirmed='yes'): # 总是使用当前选择指纹。
        index, data = load_selection(self.flow,self.flow.load(self.sid)) # 重新读取明确状态。
        return review_selection(self.flow,self.sid,'run_test',selection_token(index),decision,'测试人','已核对',confirmed) # 不写生产批准。
    def test_request_does_not_approve_or_replace(self): # 请求不能代替选择批准。
        self.register(); index, data = load_selection(self.flow,self.flow.load(self.sid)) # 保存当前候选。
        request_recommendation(self.flow,self.sid,'run_test','','关注炎症') # 仅登记请求。
        self.assertEqual(load_selection(self.flow,self.flow.load(self.sid))[0],index) # 当前候选指针不变。
    def test_pending_visible_and_no_report_inclusion(self): # 未批准候选可看图，但不能纳入报告。
        self.register() # 助手登记并非人工批准。
        html = review_page(self.flow,self.sid,'token') # 实际生成网页文字。
        self.assertIn('待你审核',html); self.assertIn('保存通路复核决定',html) # 重点清晰。
        self.assertNotIn('将已认可通路加入专业报告，生成新修订</button>',html) # 未批准不提供纳入按钮。
        with patch('report_flow.run_reports',return_value='plain') as plain, patch('report_flow_pathway.run_reports') as extended: # 只测试分派。
            self.assertEqual(run_reports(self.flow,self.sid,'','测试'),'plain'); extended.assert_not_called() # 不纳入候选。
    def test_confirmation_required(self): # 未勾选确认不能通过。
        self.register() # 先准备候选。
        with self.assertRaises(ContractError): self.review(confirmed='') # 服务端重新校验。
        self.assertEqual(load_selection(self.flow,self.flow.load(self.sid))[0]['review_status'],'awaiting_user_review') # 没有半条批准。
    def test_approval_preserves_candidate_and_new_generator(self): # 真正审批创建新事实包。
        candidate = self.register(); self.review() # 两步明确分开。
        index, approved = load_selection(self.flow,self.flow.load(self.sid)) # 当前批准记录。
        self.assertEqual(read_json(self.flow.location(self.sid)/candidate['path'])['review_status'],'awaiting_user_review') # 旧候选未覆盖。
        self.assertEqual(index['review_status'],'approved'); self.assertTrue(approved['review']) # 责任人意见留存。
        with patch('report_flow_pathway.run_reports',return_value='extended') as extended, patch('report_flow.run_reports') as plain: # 不生成夹具Word。
            self.assertEqual(run_reports(self.flow,self.sid,'','测试'),'extended'); plain.assert_not_called() # 当前批准才纳入。
    def test_stale_and_repeated_review_rejected(self): # 防重复和旧页面批准。
        self.register(); index, data = load_selection(self.flow,self.flow.load(self.sid)); old = selection_token(index) # 保存旧页面版本。
        self.review() # 当前版本改变。
        with self.assertRaises(ContractError): review_selection(self.flow,self.sid,'run_test',old,'approved','测试人','重复','yes') # 重复提交拒绝。
        self.flow.manifest['inactive'] = True # 模拟A03改变使A05失效。
        self.assertIn('原推荐已失效',review_page(self.flow,self.sid,'token')) # 网页必须显式提示。
        with self.assertRaises(ContractError): self.review() # 即使A05编号相同也拒绝。
    def test_bad_facts_qa_and_target_rejected(self): # 不符合当前科学表的候选不能交审核。
        for key,value in [('count',2),('target_symbol','TNF'),('assistant_qa',{'checked':False})]: # 三类有意义负例。
            changed = deepcopy(self.data); changed[key] = value # 不修改原候选。
            with self.assertRaises(ContractError): register_candidate(self.flow,self.sid,changed) # 全量服务端核验。
    def test_tampered_figure_and_wrong_version_rejected(self): # 下载不接受任意路径或篡改内容。
        self.register(); index, data = load_selection(self.flow,self.flow.load(self.sid)) # 正确版本。
        self.assertEqual(figure_file(self.flow,self.sid,selection_token(index)).read_bytes(),b'test_image_bytes') # 发送原始字节。
        with self.assertRaises(ContractError): figure_file(self.flow,self.sid,'wrong') # 旧版本拒绝。
        (self.flow.location(self.sid)/'preview.png').write_bytes(b'changed') # 仅修改夹具。
        with self.assertRaises(ContractError): figure_file(self.flow,self.sid,selection_token(index)) # 篡改拒绝。
    def test_rejected_and_trash_are_read_only(self): # 退回不允许加入，回收站不能写。
        self.register(); self.review('rejected') # 明确退回。
        self.assertIn('已退回修改',review_page(self.flow,self.sid,'token')) # 中文状态准确。
        self.flow.manifest['trashed'] = True # 测试管理只读。
        with self.assertRaises(ContractError): self.review() # 后台同样禁止。
        self.assertNotIn('保存通路复核决定</button>',review_page(self.flow,self.sid,'token')) # 页面隐藏操作。
    def test_no_candidate_rule_and_request_visible(self): # 所有新研究都显示规则入口。
        self.assertIn('待准备推荐',card(self.flow,self.flow.load(self.sid),'token')) # 未选也不会缺入口。
        self.assertIn('登记通路推荐准备请求',review_page(self.flow,self.sid,'token')) # 不套用当前案例。
    def test_http_review_and_forged_submission(self): # 使用真实网页路由验证表单门控。
        import threading, http.client, re # 隔离服务和HTML令牌读取。
        from urllib.parse import urlencode # 浏览器相同的表单编码。
        from web import create_server # 正式HTTP处理器。
        self.register() # 独立测试候选。
        with patch('web.Workflow',return_value=self.flow): server=create_server(self.flow.root,0) # 不连接真实研究。
        worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start() # 随机端口服务。
        connection=http.client.HTTPConnection('127.0.0.1',server.server_port) # 正确本机Host。
        try: # 任意异常也释放本测试服务。
            connection.request('GET','/pathway-review?study='+self.sid) # 实际路由返回页面。
            response=connection.getresponse(); html=response.read().decode('utf-8'); self.assertEqual(response.status,200) # 未准备假页面。
            token=re.search('name="token" value="([^"]+)"',html).group(1) # 使用服务生成的防伪令牌。
            index,data=load_selection(self.flow,self.flow.load(self.sid)) # 表单科学版本。
            fields={'token':token,'study':self.sid,'expected_a05':'run_test','expected_selection':selection_token(index),'decision':'approved','reviewer':'测试人','note':'已核对','confirmed':'yes'} # 明确测试确认。
            bad=dict(fields,token='wrong') # 伪造令牌应拒绝。
            connection.request('POST','/pathway-review',urlencode(bad),{'Content-Type':'application/x-www-form-urlencoded'}) # 模拟绕过页面。
            response=connection.getresponse(); response.read(); self.assertEqual(response.status,400) # 失败不创建批准。
            connection.request('POST','/pathway-review',urlencode(fields),{'Content-Type':'application/x-www-form-urlencoded'}) # 正确表单通过。
            response=connection.getresponse(); response.read(); self.assertEqual(response.status,303) # 明确保存后跳转。
            self.assertEqual(load_selection(self.flow,self.flow.load(self.sid))[0]['review_status'],'approved') # 实際人工记录保存。
            connection.request('POST','/pathway-review',urlencode(fields),{'Content-Type':'application/x-www-form-urlencoded'}) # 重复旧提交。
            response=connection.getresponse(); response.read(); self.assertEqual(response.status,400) # 不产生重复批准。
        finally: # 只清理测试服务。
            connection.close(); server.shutdown(); server.server_close(); worker.join(timeout=3) # 不影响用户网页。
    def test_report_approval_requires_matching_selection(self): # 新通路或撤回批准都要求报告修订。
        self.register(); self.review() # 当前通路获得明确批准。
        index,data=load_selection(self.flow,self.flow.load(self.sid)) # 当前批准版本。
        with self.assertRaises(ContractError): require_alignment(self.flow,self.flow.load(self.sid),{'inputs':{}}) # 旧无图报告不能当成已纳入版本。
        bound={'inputs':{'selected_pathway_metadata':index['metadata']}} # 同源报告输入。
        require_alignment(self.flow,self.flow.load(self.sid),bound) # 正确绑定允许完整报告复核。
        self.review('rejected') # 后来撤回选择批准。
        with self.assertRaises(ContractError): require_alignment(self.flow,self.flow.load(self.sid),bound) # 历史含图报告不能冒充当前批准。

if __name__ == '__main__': unittest.main(verbosity=2) # 输出实际通过和失败。

# 标准化交接的隔离验收，所有数据均为虚构，不操作用户研究。
import sys  # 引用本项目。
import json  # 构造快照元信息。
import hashlib  # 测试来源校验。
import gzip  # 构造隔离的官方格式补充表。
import tempfile  # 隔离研究包。
import unittest  # 验证完整交接。
from pathlib import Path  # 临时路径。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 不引用旧代码。
from workflow import Workflow  # 使用实际归档。
from disease import DATABASES, run_disease, validate_disease  # 实际来源整理。
from components import validate_components  # 保留A01校验。
from normalization import validator, preview, publish, review_page  # 测试新增完整路径。
from intersection_flow import run_intersection, validate_intersection  # 验证实际A03接收。
from contracts import ContractError  # 检查明确阻断。

class NormalizationTests(unittest.TestCase):  # 一项测试一个独立研究。
    def setUp(self):  # 固定虚构HGNC及疾病来源。
        self.temp = tempfile.TemporaryDirectory()  # 不进入真实studies。
        self.root = Path(self.temp.name)  # 独立根目录。
        refs = self.root / "references"  # 与项目布局一致。
        refs.mkdir()  # 测试资料目录。
        raw = b"hgnc_id\tsymbol\tprev_symbol\talias_symbol\tensembl_gene_id\tuniprot_ids\tstatus\nHGNC:1\tA\t\t\tENSG1\tP1\tApproved\n"  # 单基因可手算快照。
        (refs / "hgnc_complete_set_20260913.tsv").write_bytes(raw)  # 仅临时文件。
        (refs / "hgnc_complete_set_20260913.json").write_text(json.dumps({"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"source_url":"synthetic_test"}),encoding="utf-8")  # 不冒充官方来源。
        fixtures = {"ncbi_human_gene_info_20260913.gz": gzip.compress(b"#tax_id\tGeneID\tSymbol\tSymbol_from_nomenclature_authority\tSynonyms\tdbXrefs\ttype_of_gene\n9606\t1\tA\tA\t-\tHGNC:HGNC:1\tprotein-coding\n"), "ncbi_human_gene_history_20260913.tsv": b"#tax_id\tGeneID\tDiscontinued_GeneID\tDiscontinued_Symbol\tDiscontinue_Date\n", "identity_queries_20260913_v3.json": b"{}"}  # 手算可验证的来源。
        for filename, data in fixtures.items():  # 每份测试证据均带指纹。
            (refs / filename).write_bytes(data)  # 不使用真实研究数据。
            manifest = "identity_queries_20260913_v3_manifest.json" if filename.endswith(".json") else Path(filename).with_suffix(".json").name  # 与生产清单一致。
            (refs / manifest).write_text(json.dumps({"sha256":hashlib.sha256(data).hexdigest(), "bytes":len(data), "source_url":"synthetic_test"}), encoding="utf-8")  # 不冒充真实查询。
        self.flow = Workflow(self.root, {"A01":validator(self.root,validate_components), "A02":validator(self.root,validate_disease), "A03":validate_intersection})  # 正式校验器。
        self.sid = self.flow.create({"formula":"合成方","herbs":"测试药","disease":"COPD","disease_scope":"虚构测试","operator":"test","species":9606},kind="contract_test")  # 显式合同测试。
        a00 = self.flow.load(self.sid)["current"]["A00"]  # 登记版本。
        self.flow.review(self.sid,a00,"approved","test","虚构登记")  # 测试签署。
        self.flow.validators.pop("A01")  # 仅为contract_test创建虚构原始A01。
        run = self.flow.begin(self.sid,"A01",{}, {},"虚构来源")  # 不是真实科学运行。
        tables = {"components":[{"compound_id":"M1","name":"合成成分"}],"herb_components":[{"herb":"测试药","compound_id":"M1"}],"herb_summary":[{"herb":"测试药"}],"compound_targets":[{"compound_id":"M1","gene":"A","uniprot":"P1","species":9606,"source_lines":"2"}]}  # 手算交集为1。
        self.flow.finish(self.sid,run["run_id"],{},tables)  # 保存临时输入。
        self.flow.validators["A01"] = validator(self.root,validate_components)  # 恢复真实标准化校验。
        source = {"database":"GeneCards","format":"tsv","query":"COPD","retrieved_at":"2026-09-13","version":"test","source_url":"test","name":"test.tsv","encoding":"utf-8-sig","data":b"raw_symbol\tdisease_term\nA\tCOPD\nUNKNOWN\tCOPD\nA\tOTHER\n"}  # 一个身份例外、一个范围外。
        run_disease(self.flow,self.sid,a00,"",[dict(source,database=db) for db in DATABASES],"虚构候选")  # 使用实际候选生产者。
    def tearDown(self):  # 不留下测试研究。
        self.temp.cleanup()  # 仅清理本次临时目录。
    def test_browser_handoff(self):  # 实际网页点击流程。
        import os, subprocess, threading  # 复用已安装浏览器工具。
        from web import create_server  # 与用户工作台同一服务。
        server = create_server(self.root,0)  # 临时端口和临时研究。
        thread = threading.Thread(target=server.serve_forever,daemon=True)  # 独立服务线程。
        thread.start()  # 接受测试请求。
        try:  # 失败也关闭服务。
            settings = {"url":"http://127.0.0.1:"+str(server.server_port),"study":self.sid}  # 不连真实研究。
            result = subprocess.run([os.environ["MODULEA_NODE"],str(Path(__file__).with_name("test_web_normalization.mjs"))],input=json.dumps(settings),text=True,encoding="utf-8",capture_output=True,timeout=120)  # 实际浏览器测试。
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)  # 错误如实报告。
        finally:  # 不遗留服务。
            server.shutdown()  # 停止临时服务器。
            server.server_close()  # 释放端口。
            thread.join(timeout=3)  # 回收线程。

    def test_full_handoff(self):  # 预览、确认、双复核、实际A03。
        data = preview(self.flow,self.sid)  # 提出草案，不改变研究。
        before = dict(self.flow.load(self.sid)["current"])  # 保存原指针。
        self.assertIn("结果汇总",review_page(self.flow,self.sid,"token"))  # 页面能够实际生成。
        with self.assertRaises(ContractError):  # 没确认身份例外不能发布。
            publish(self.flow,self.sid,data[-1],"test","测试",True,False)  # 明确拒绝不完整确认。
        self.assertEqual(self.flow.load(self.sid)["current"],before)  # 失败不发布任何一侧。
        outputs = publish(self.flow,self.sid,data[-1],"test","仅测试接受例外",True,True)  # 用户动作模拟。
        for module,result in outputs.items():  # 两侧均需独立批准。
            self.assertFalse(self.flow.approved(self.flow.load(self.sid),result["run_id"]))  # 发布不自动代签。
            self.flow.review(self.sid,result["run_id"],"approved","test","虚构核验通过")  # 显式测试签署。
        actual = run_intersection(self.flow,self.sid,self.flow.load(self.sid)["current"],"测试交接")  # 真实计算。
        self.assertEqual(actual["summary"]["交集靶点数"],1)  # 手算吻合。
        self.assertEqual(actual["summary"]["analysis_purpose"],"workflow_test")  # 测试标签不能丢失。
        self.assertEqual(outputs["A02"]["tables"]["scope_groups"][1]["scope"],"outside")  # 本次明确不采用范围保留。
        with self.assertRaises(ContractError):  # 旧预览不能覆盖新结果。
            publish(self.flow,self.sid,data[-1],"test","过期",True,True)  # 版本门控。

    def test_formal_mesh_handoff(self):  # 任意新疾病路径由A00官方身份驱动，不依赖COPD名称集合。
        manifest = self.flow.load(self.sid)  # 取得当前测试登记版本。
        old_a00 = manifest["current"]["A00"]  # 修订必须绑定旧版本。
        mesh = {"status":"verified","mesh_id":"D012220","preferred_term":"Rhinitis, Allergic","mesh_year":"2026","checked_at":"2026-09-28T00:00:00+00:00","provider":"U.S. National Library of Medicine","api_version":"test","descriptor_resource":"http://id.nlm.nih.gov/mesh/2026/D012220","entry_terms":["Allergic Rhinitis"],"evidence":{"years_sha256":"a","descriptor_sha256":"b","details_sha256":"c"}}  # 固定的官方形状仅用于合同测试。
        intake = {"formula":"合成方","herbs":"测试药","disease":"过敏性鼻炎","mesh_term":"Rhinitis, Allergic","mesh_id":"D012220","mesh_verification":mesh,"disease_scope":"仅本病，不纳入亚型","operator":"test","species":9606}  # 用户直接提供并已核对的MeSH身份。
        new_a00 = self.flow.revise_intake(self.sid,intake,"切换正式MeSH合同测试",old_a00)  # 另存新A00，不覆盖旧登记。
        self.flow.review(self.sid,new_a00,"approved","test","MeSH身份测试通过")  # 正式入口仍需人工批准A00。
        self.flow.validators.pop("A01")  # 合同测试用手算A01候选。
        run = self.flow.begin(self.sid,"A01",{}, {},"正式路径虚构方剂来源")  # 新A01绑定新A00。
        tables = {"components":[{"compound_id":"M1","name":"合成成分"}],"herb_components":[{"herb":"测试药","compound_id":"M1"}],"herb_summary":[{"herb":"测试药"}],"compound_targets":[{"compound_id":"M1","gene":"A","uniprot":"P1","species":9606,"source_lines":"2"}]}  # 保持一个可手算交集。
        self.flow.finish(self.sid,run["run_id"],{},tables)  # 保存隔离候选。
        self.flow.validators["A01"] = validator(self.root,validate_components)  # 恢复生产标准化校验。
        current_a02 = self.flow.load(self.sid)["current"]["A02"]  # 旧A02已因A00修订失效。
        source = {"database":"GeneCards","format":"tsv","query":"Rhinitis, Allergic","retrieved_at":"2026-09-28","version":"test","source_url":"synthetic_test","name":"formal.tsv","encoding":"utf-8-sig","data":b"raw_symbol\tdisease_term\tdisease_id\nA\tRhinitis, Allergic\tD012220\nUNKNOWN\tRhinitis, Allergic\tD012220\n"}  # 五库均为本次新资料形状。
        run_disease(self.flow,self.sid,new_a00,current_a02,[dict(source,database=db) for db in DATABASES],"正式MeSH来源合同测试")  # 不继承失效的COPD旧来源。
        data = preview(self.flow,self.sid)  # 官方编号和首选词精确匹配形成direct建议。
        self.assertEqual(data[5]["A02"][0]["analysis_purpose"],"formal_research")  # 不再标成流程测试。
        self.assertEqual(data[5]["A02"][0]["mesh_id"],"D012220")  # 标准化结果携带唯一疾病编号。
        outputs = publish(self.flow,self.sid,data[-1],"test","正式MeSH合同测试接受未查实身份暂不采用",True,True)  # 显式确认范围和例外。
        for module,result in outputs.items():  # A01和A02必须使用同一正式版本。
            run_record = self.flow.run(self.flow.load(self.sid),result["run_id"])  # 读取不可变运行配置。
            self.assertEqual(run_record["config"]["version"],"normalized.formal.1")  # 正式路径不能写成test版本。
            self.assertEqual(result["summary"]["analysis_purpose"],"formal_research")  # 用途传播到下游接口。

    def test_missing_genecards_requires_workflow_exception_signature(self):  # 新版只允许明确签署缺GeneCards流程测试。
        manifest = self.flow.load(self.sid)  # 从隔离研究切换到新版MeSH流程测试。
        mesh = {"status":"verified","mesh_id":"D065631","preferred_term":"Rhinitis, Allergic","mesh_year":"2026","checked_at":"2026-10-04T00:00:00+00:00","provider":"U.S. National Library of Medicine","api_version":"test","descriptor_resource":"http://id.nlm.nih.gov/mesh/2026/D065631","entry_terms":["Allergic Rhinitis"],"evidence":{"years_sha256":"a","descriptor_sha256":"b","details_sha256":"c"}}  # 合同测试身份形状。
        intake = {"formula":"合成方","herbs":"测试药","disease":"过敏性鼻炎","mesh_term":"Rhinitis, Allergic","mesh_id":"D065631","mesh_verification":mesh,"disease_scope":"仅本病，不纳入亚型","analysis_purpose":"workflow_test","operator":"test","species":9606}  # 用途由A00明确保存。
        a00 = self.flow.revise_intake(self.sid,intake,"切换缺库流程测试",manifest["current"]["A00"])  # 新A00使旧下游失效。
        manifest = self.flow.load(self.sid)  # 合同测试最初是legacy，显式模拟生产创建所得新版配置。
        manifest["workflow_profile"] = "A00.preupload.2"  # 生产新建研究会自动写入该值。
        self.flow.save(manifest)  # 仅修改临时测试研究。
        self.flow.review(self.sid,a00,"approved","test","流程测试登记通过")  # 满足上游门控。
        self.flow.validators.pop("A01")  # 生成一个可手算虚构A01。
        run = self.flow.begin(self.sid,"A01",{}, {},"缺库测试A01")  # 绑定新A00。
        tables = {"components":[{"compound_id":"M1","name":"合成成分"}],"herb_components":[{"herb":"测试药","compound_id":"M1"}],"herb_summary":[{"herb":"测试药"}],"compound_targets":[{"compound_id":"M1","gene":"A","uniprot":"P1","species":9606,"source_lines":"2"}]}  # 单基因可复算。
        self.flow.finish(self.sid,run["run_id"],{},tables)  # 发布虚构候选。
        self.flow.validators["A01"] = validator(self.root,validate_components)  # 恢复正式校验。
        data = b"raw_symbol\tdisease_term\tdisease_id\nA\tRhinitis, Allergic\tD065631\n"  # 四个实际来源均含同一直接基因。
        base = {"format":"tsv","query":"Rhinitis, Allergic","retrieved_at":"2026-10-04","version":"test","source_url":"synthetic_test","name":"source.tsv","encoding":"utf-8-sig","data":data}  # 不包含GeneCards。
        old_a02 = self.flow.load(self.sid)["current"]["A02"]  # 旧A02已失效但作为版本入口保留。
        run_disease(self.flow,self.sid,a00,old_a02,[dict(base,database=db) for db in ("OMIM","TTD","PharmGKB","OTP")],"缺GeneCards流程测试",profile_version="A02.source_profile.3")  # 当前来源由实际四库构成。
        draft = preview(self.flow,self.sid)  # 缺GeneCards不再阻断只读预览。
        self.assertEqual(draft[5]["A02"][0]["来源例外"],"缺GeneCards的流程测试")  # 页面和报告可识别边界。
        self.assertEqual(draft[5]["A02"][0]["OTP在疾病集合中的占比（%）"],100.0)  # 比例按标准化基因计算。
        with self.assertRaises(ContractError):  # 未签署来源例外不得发布。
            publish(self.flow,self.sid,draft[-1],"test","仅测试",True,True,False)  # 范围和身份确认不能替代缺库确认。
        outputs = publish(self.flow,self.sid,draft[-1],"test","接受缺GeneCards流程测试",True,True,True)  # 明确签署后发布。
        self.assertEqual(outputs["A02"]["tables"]["source_exceptions"][0]["reviewer"],"test")  # 签署人随结果留存。
        self.assertEqual(self.flow.run(self.flow.load(self.sid),outputs["A02"]["run_id"])["config"]["version"],"normalized.test.3")  # 独立版本防止冒充完整研究。
        current_a02 = self.flow.load(self.sid)["current"]["A02"]  # 模拟以后取得GeneCards后从当前版本补库。
        gene_cards = dict(base,database="GeneCards",name="genecards.tsv")  # 只替换新增来源，其他四库继续沿用已归档文件。
        supplemented = run_disease(self.flow,self.sid,a00,current_a02,[gene_cards],"补入GeneCards验证完整五库迁移")  # 使用同一生产入口形成新A02候选。
        self.assertIn("等待A03",supplemented["summary"]["补库前后稳定性比较"])  # 补库后明确要求重算下游。
        full_draft = preview(self.flow,self.sid)  # 完整五库沿用同一标准化流程，不需要另写代码。
        self.assertNotIn("source_exceptions",full_draft[5]["A02"][1])  # 资料齐备时缺库例外自动撤销。
        full_outputs = publish(self.flow,self.sid,full_draft[-1],"test","完整五库迁移验证",True,True,False)  # 完整路径不要求签署缺库例外。
        for result in full_outputs.values():  # 两侧结果仍保持独立复核记录。
            self.flow.review(self.sid,result["run_id"],"approved","test","完整五库测试通过")  # 测试中显式模拟用户复核。
        a03 = run_intersection(self.flow,self.sid,self.flow.load(self.sid)["current"],"完整五库自动进入A03")  # 验证相同自动化可以接到交集模块。
        self.assertEqual(a03["summary"]["交集靶点数"],1)  # 手算交集保持一致。
        self.assertEqual(a03["summary"]["analysis_purpose"],"workflow_test")  # 补库不篡改研究用途。

if __name__ == "__main__":  # 独立执行。
    unittest.main(verbosity=2)  # 输出真实检查结果。



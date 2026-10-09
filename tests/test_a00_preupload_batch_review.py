# 验证A00资料预上传和A01/A02一次复核的关键边界。
import io  # 在内存中制作OMIM工作簿。
import json  # 构造ClinPGx标准响应快照。
from pathlib import Path  # 定位当前项目源码。
import sys  # 只导入当前新项目代码。
import tempfile  # 隔离测试研究包。
import unittest  # 组织重复验收。
from unittest.mock import patch  # 用固定响应替代真实数据库网络。
from openpyxl import Workbook  # 生成标准xlsx文件。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 禁止引用旧Kimi代码。
from contracts import ContractError  # 核对明确拒绝结果。
from a02_auto_prepare import prepare  # 调用A00通过后的五库编排入口。
from disease import validate_disease  # 对A02运行执行生产校验。
from intake_sources import sources_for_a02, stage  # 调用真实预上传入口。
from storage import verified_file  # 核对历史文件仍可追溯。
from web import a01_a02_review_form  # 核对原卡片后的网页一次提交入口。
from workflow import Workflow  # 使用统一版本与复核内核。


def intake(disease="测试鼻炎"):  # 构造已核对的正式研究登记。
    mesh = {"status": "verified", "mesh_id": "D012220", "preferred_term": "Rhinitis", "mesh_year": "2026", "checked_at": "2026-10-03T00:00:00+00:00", "provider": "NLM", "api_version": "test", "descriptor_resource": "http://id.nlm.nih.gov/mesh/2026/D012220", "entry_terms": ["Rhinitis"], "evidence": {"years_sha256": "a", "descriptor_sha256": "b", "details_sha256": "c"}}  # 测试证据形状与生产契约一致。
    return {"formula": "测试方剂", "herbs": "黄芪", "disease": disease, "disease_scope": "仅本病，不纳入亚型", "operator": "测试人员", "species": 9606, "mesh_term": "Rhinitis", "mesh_id": "D012220", "mesh_verification": mesh}  # 身份字段完整。


def xlsx():  # 制作唯一合法表头的OMIM工作簿。
    book = Workbook()  # 新建工作簿。
    sheet = book.active  # 使用默认工作表。
    for row in (["Gene Map Search"], ["date"], [], [], ["Approved Symbol", "Entrez Gene ID", "Phenotype", "Phenotype MIM number"], ["IL13", "3596", "Rhinitis", "607154"]):  # 模拟官方前置信息和一条记录。
        sheet.append(row)  # 逐行写入。
    output = io.BytesIO()  # 不产生外部临时文件。
    book.save(output)  # 保存标准xlsx字节。
    return output.getvalue()  # 交给真实解析器。


def source(database, fmt, data, name, encoding="utf-8-sig"):  # 构造网页上传后的后台数据形状。
    return {"database": database, "format": fmt, "query": "Rhinitis", "retrieved_at": "2026-10-03", "version": "test", "name": name, "encoding": encoding, "data": data}  # 来源网址与替换原因由后台生成。


class PreuploadAndBatchReviewTests(unittest.TestCase):  # 覆盖用户批准的核心验收场景。
    def setUp(self):  # 每项测试建立新目录。
        self.temp = tempfile.TemporaryDirectory(prefix="moduleA_preupload_")  # 自动清理测试资料。
        self.root = Path(self.temp.name)  # 作为临时项目根目录。

    def tearDown(self):  # 测试后清理。
        self.temp.cleanup()  # 不触碰正式研究。

    def test_preupload_waits_for_a00_and_identity_change_invalidates_use(self):  # A00前不生成A02，身份变化后旧资料停用但保留。
        flow = Workflow(self.root)  # 使用真实研究包。
        study = flow.create(intake())  # 新正式研究启用预上传流程。
        a00 = flow.load(study)["current"]["A00"]  # 固定当前科学身份。
        stage(flow, study, a00, source("GeneCards", "names", "GENE1\n".encode("gbk"), "genes.txt", "gbk"))  # GBK名单可提前校验。
        staged = stage(flow, study, a00, source("OMIM", "omim_xlsx", xlsx(), "omim.xlsx"))  # Excel不经过文本解码。
        manifest = flow.load(study)  # 读取暂存后状态。
        self.assertNotIn("A02", manifest["current"])  # 暂存不等于形成A02结果。
        old_files = [verified_file(flow.location(study), item["source_record"]) for item in staged["datasets"]]  # 固定原始文件位置。
        flow.revise_intake(study, intake("另一测试疾病"), "改变科学身份", a00)  # 新建A00版本。
        self.assertEqual(sources_for_a02(flow, flow.load(study)), [])  # 旧资料绝不自动复用。
        self.assertTrue(all(path.exists() for path in old_files))  # 原文件仍可追溯。

    def review_ready(self, blocked=False):  # 准备两个独立待复核结果。
        accept = lambda run, summary, tables, anomalies, outcome: None  # 本项只验证复核事务，不重复科学模块校验。
        flow = Workflow(self.root, {"A01": accept, "A02": accept})  # 正式研究仍要求模块已明确接入。
        study = flow.create(intake())  # 必须采用新流程。
        manifest = flow.load(study)  # 取得A00。
        flow.review(study, manifest["current"]["A00"], "approved", "测试人", "登记通过")  # 满足两模块上游条件。
        for module in ("A01", "A02"):  # 分别生成两个结果。
            run = flow.begin(study, module, {"test": module}, {"version": "test"}, "一次复核测试")  # 运行身份相互独立。
            flow.finish(study, run["run_id"], {"handoff_blocked": blocked and module == "A02"}, {"rows": [{"module": module}]})  # A02可模拟资料阻断。
        return flow, study  # 返回完整测试研究。

    def test_batch_conflict_creates_no_partial_review(self):  # 任一版本冲突时两项都不保存。
        flow, study = self.review_ready()  # 准备待复核结果。
        manifest = flow.load(study)  # 取得当前运行。
        before = len(manifest["reviews"])  # 记录原有A00复核数量。
        entries = {module: {"run_id": manifest["current"][module], "expected_review": "review_stale", "action": "change", "decision": "approved", "note": "测试"} for module in ("A01", "A02")}  # 模拟过期页面。
        with self.assertRaises(ContractError):  # 整批必须被拒绝。
            flow.review_a01_a02(study, entries, "测试复核人")  # 不允许半条记录。
        self.assertEqual(len(flow.load(study)["reviews"]), before)  # 索引完全未变。

    def test_new_a02_uses_five_sources_and_preserves_exact_zero(self):  # 新研究不等待DisGeNET且不混淆零结果。
        flow = Workflow(self.root, {"A02": validate_disease})  # 启用真实A02校验器。
        study = flow.create(intake())  # 建立新流程研究。
        a00 = flow.load(study)["current"]["A00"]  # 固定登记版本。
        stage(flow, study, a00, source("GeneCards", "names", b"GENE1\n", "genes.txt"))  # 暂存人工来源一。
        stage(flow, study, a00, source("OMIM", "omim_xlsx", xlsx(), "omim.xlsx"))  # 暂存人工来源二。
        flow.review(study, a00, "approved", "测试人", "登记通过")  # 自动获取只能在通过后运行。
        with self.assertRaises(ContractError):  # 通过后补资料须进入A02版本链。
            stage(flow, study, a00, source("GeneCards", "names", b"GENE2\n", "late.txt"))  # 不允许产生不会自动进入A02的悬空暂存。
        otp = {"database": "OTP", "format": "tsv", "query": "Rhinitis", "retrieved_at": "2026-10-03", "version": "test", "source_url": "https://platform.opentargets.org/", "name": "otp.tsv", "encoding": "utf-8-sig", "source_status": "", "data": b"raw_symbol\traw_id\nGENE3\tENSG3\n"}  # 固定OTP测试响应。
        ttd = {"database": "TTD", "format": "names", "query": "Rhinitis", "retrieved_at": "2026-10-03", "version": "test", "source_url": "https://ttd.idrblab.cn/", "name": "ttd.txt", "encoding": "utf-8-sig", "source_status": "", "data": b"GENE4\n"}  # 固定TTD测试响应。
        snapshot = {"api": "https://api.clinpgx.org/v1", "official_terms": ["Rhinitis"], "exact_disease": None, "records": [], "requests": [], "status": "queried_zero_exact"}  # ClinPGx真实零结果形状。
        pharm = {"database": "PharmGKB", "format": "pharmgkb_api", "query": "Rhinitis", "retrieved_at": "2026-10-03", "version": "test", "source_url": "https://api.clinpgx.org/v1", "name": "pharm.json", "encoding": "utf-8-sig", "source_status": "", "data": json.dumps(snapshot).encode()}  # 保存完整零结果快照。
        with patch("a02_auto_prepare._otp_source", return_value=(otp, {})), patch("a02_auto_prepare._ttd_source", return_value=(ttd, {})), patch("a02_auto_prepare.fetch_pharmgkb", return_value=pharm):  # 禁止访问真实网络。
            prepared = prepare(flow, study)  # 通过生产入口生成候选A02。
        result = flow.result(flow.load(study), prepared["run_id"])  # 读取完整归档结果。
        self.assertEqual(result["summary"]["databases"], ["GeneCards", "OMIM", "TTD", "PharmGKB", "OTP"])  # 新五库顺序固定。
        states = {row["database"]: row["availability"] for row in result["tables"]["source_summary"]}  # 汇总每库真实状态。
        self.assertNotIn("DisGeNET", states)  # 新研究已移除该来源。
        self.assertEqual(states["PharmGKB"], "已查询但0条精确记录")  # 零结果不写成失败或缺失。

    def test_missing_and_failed_sources_remain_distinct(self):  # 缺人工资料与自动查询失败均可查看但不能伪装完成。
        flow = Workflow(self.root, {"A02": validate_disease})  # 使用生产A02校验。
        study = flow.create(intake())  # 不预上传任何人工来源。
        a00 = flow.load(study)["current"]["A00"]  # 取得登记版本。
        flow.review(study, a00, "approved", "测试人", "允许缺资料进入候选查看")  # 缺文件不阻止A00。
        failed = RuntimeError("测试网络失败")  # 三个自动来源均模拟失败。
        with patch("a02_auto_prepare._otp_source", side_effect=failed), patch("a02_auto_prepare._ttd_source", side_effect=failed), patch("a02_auto_prepare.fetch_pharmgkb", side_effect=failed):  # 不访问外网。
            prepared = prepare(flow, study)  # 仍应形成可查看的A02版本。
        result = flow.result(flow.load(study), prepared["run_id"])  # 读取来源状态。
        states = {row["database"]: row["availability"] for row in result["tables"]["source_summary"]}  # 按数据库比较。
        self.assertEqual(states["GeneCards"], "尚未提供资料")  # 人工缺失保持缺失。
        self.assertEqual(states["OMIM"], "尚未提供资料")  # OMIM同样不造零结果。
        self.assertTrue(all(states[db] == "查询失败，等待重试或上传" for db in ("TTD", "PharmGKB", "OTP")))  # 自动失败单独显示。
        self.assertTrue(result["summary"]["handoff_blocked"])  # 不允许A02通过。

    def test_batch_preserves_approved_item_and_blocks_incomplete_a02(self):  # 已通过项不重审，阻断项不能绕过。
        flow, study = self.review_ready()  # 准备正常两项。
        manifest = flow.load(study)  # 固定运行编号。
        entries = {"A01": {"run_id": manifest["current"]["A01"], "expected_review": None, "action": "change", "decision": "approved", "note": "A01通过"}, "A02": {"run_id": manifest["current"]["A02"], "expected_review": None, "action": "change", "decision": "rejected", "note": "A02退回"}}  # 一次提交不同决定。
        flow.review_a01_a02(study, entries, "测试复核人")  # 保存两条独立记录。
        combined_html = a01_a02_review_form(flow.view(study), "test-token")  # 页面仍使用原A01/A02卡片，只附加一次提交表单。
        self.assertIn("保存A01和A02复核决定", combined_html)  # 用户有明确的统一入口。
        self.assertIn("保留现有“已复核通过”决定", combined_html)  # 已通过A01无需再次审核。
        manifest = flow.load(study)  # 读取最近决定。
        reviews = {module: flow.latest_review(manifest, flow.result(manifest, manifest["current"][module])["artifact_id"]) for module in ("A01", "A02")}  # 对应各自产物。
        changed = {"A01": {"run_id": manifest["current"]["A01"], "expected_review": reviews["A01"]["review_id"], "action": "preserve", "decision": "", "note": ""}, "A02": {"run_id": manifest["current"]["A02"], "expected_review": reviews["A02"]["review_id"], "action": "change", "decision": "approved", "note": "A02补充后通过"}}  # 只更新A02。
        self.assertEqual(len(flow.review_a01_a02(study, changed, "测试复核人")), 1)  # A01不重复生成记录。
        blocked_flow, blocked_study = self.review_ready(True)  # 另建资料不齐场景。
        blocked_manifest = blocked_flow.load(blocked_study)  # 固定版本。
        blocked = {module: {"run_id": blocked_manifest["current"][module], "expected_review": None, "action": "change", "decision": "approved", "note": "尝试通过"} for module in ("A01", "A02")}  # 模拟伪造A02通过选项。
        before = len(blocked_manifest["reviews"])  # 记录提交前数量。
        with self.assertRaises(ContractError):  # 服务端必须阻止。
            blocked_flow.review_a01_a02(blocked_study, blocked, "测试复核人")  # A01也不能留下半条记录。
        self.assertEqual(len(blocked_flow.load(blocked_study)["reviews"]), before)  # 原子性成立。


if __name__ == "__main__":  # 支持单文件运行。
    unittest.main(verbosity=2)  # 输出每项验收结果。

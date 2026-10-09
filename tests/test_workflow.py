# 本文件验证衔接规则，所有测试数据仅在临时目录中生成。
from pathlib import Path  # 构造独立测试位置。
import csv  # 检查导出的表格内容。
import io  # 在内存中解析表格。
import json  # 检查只读网页接口。
import re  # 从页面获取表单令牌。
import sys  # 加入本项目代码位置。
import tempfile  # 测试不污染正式 studies 目录。
import threading  # 启动短时本机测试服务。
import unittest  # 使用标准库测试框架。
from urllib.request import Request, urlopen  # 模拟真实网页请求。
from urllib.error import HTTPError  # 检查错误响应。
from urllib.parse import urlencode  # 正确编码中文表单。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 只引用本项目新代码。
from contracts import ContractError  # 判断明确的契约错误。
from storage import read_json, write_lock  # 检查保存资料和并发写入保护。
from workflow import Workflow  # 测试统一内核。
from web import create_server  # 测试真实本机 HTTP 入口。

class WorkflowTests(unittest.TestCase):  # 验证真实的依赖、版本和归档行为。
    def setUp(self):  # 每个场景都创建独立研究包。
        self.temp = tempfile.TemporaryDirectory(prefix="moduleA_contract_")  # 标记为测试资料并自动清理。
        self.root = Path(self.temp.name) / "中文项目目录"  # 同时验证中文路径。
        self.flow = Workflow(self.root)  # 不读取旧代码或旧数据。
        self.intake = {"formula": "测试方剂", "herbs": "测试药味甲、乙", "disease": "测试疾病", "disease_scope": "仅测试本病", "operator": "测试人员", "species": 9606}  # 明确为虚构测试输入。
        self.study = self.flow.create(self.intake, kind="contract_test")  # 科学占位结果只允许在测试研究使用。
    def tearDown(self):  # 清理仅属于本场景的临时目录。
        self.temp.cleanup()  # 不触及正式项目研究。

    def approve(self, run_id):  # 用明确复核身份完成测试审核。
        return self.flow.review(self.study, run_id, "approved", "测试复核人", "测试确认")  # 不伪装用户真实签字。

    def finish_module(self, module, outcome="success"):  # 测试数据验证交接，不代表真实科学计算。
        run = self.flow.begin(self.study, module, {"test_input": True}, {"test_config": 1}, "验证模块交接")  # 所有配置明确标记为测试。
        self.flow.finish(self.study, run["run_id"], {"test_only": True}, {"test_rows": [{"gene": "TEST1", "count": 1}]}, outcome=outcome)  # 输出虚构明细用于核验。
        if outcome != "failed":  # 失败结果不能获得审核通过。
            self.approve(run["run_id"])  # 测试的明确人工决定。
        return run["run_id"]  # 供后续验证版本关系。

    def base(self):  # 准备一条通过审核的交集路径。
        self.approve(self.flow.load(self.study)["current"]["A00"])  # 登记先通过。
        self.finish_module("A01")  # 方剂侧通过。
        self.finish_module("A02")  # 疾病侧通过。
        self.finish_module("A03")  # 交集通过。
        self.finish_module("A03_SELECT")  # 对接测试另准备已确认的成分分支。

    def test_simultaneous_write_is_rejected(self):  # 同时保存不得互相覆盖索引。
        with write_lock(self.root):  # 模拟另一个操作正在持有写入锁。
            with self.assertRaises(ContractError):  # 第二次写入应明确要求稍后重试。
                with write_lock(self.root):  # 不能取得锁时不进入业务保存。
                    self.fail("第二个写入不应取得锁")  # 若错误获得锁则测试失败。

    def test_recycle_and_restore_preserve_existing_records(self):  # 回收站只改变可见性，不删除旧资料。
        run_id = self.flow.load(self.study)["current"]["A00"]  # 获取原登记。
        self.approve(run_id)  # 建立可追溯的原复核记录。
        root = self.flow.location(self.study)  # 限定测试研究目录。
        before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file() and p.name != "manifest.json"}  # 保存所有原文件用于逐字节比较。
        event = self.flow.set_trashed(self.study, True, "测试管理人", "移入测试")  # 只改变测试研究状态。
        self.assertEqual(self.flow.studies(), [])  # 正常列表隐藏。
        self.assertEqual(len(self.flow.studies(trashed=True)), 1)  # 回收站仍能找到。
        restored = Workflow(self.root)  # 模拟关闭后重新打开。
        self.assertEqual(len(restored.studies(trashed=True)), 1)  # 回收站状态必须持久保存。
        restored.set_trashed(self.study, False, "测试管理人", "恢复测试", event["action_id"])  # 按准确管理版本恢复。
        self.assertEqual(len(restored.studies()), 1)  # 正常列表重新出现。
        self.assertTrue(restored.approved(restored.load(self.study), run_id))  # 完整且未变的原审核仍可使用。
        for relative, content in before.items():  # 原始、结果和复核文件全部保留。
            self.assertEqual((root / relative).read_bytes(), content)  # 不允许暗中改写历史。
        self.assertEqual(len(restored.load(self.study)["management_events"]), 2)  # 移入与恢复各有独立记录。

    def test_recycled_study_blocks_old_page_writes(self):  # 即使旧网页仍打开，回收站研究也不能继续写入。
        run_id = self.flow.load(self.study)["current"]["A00"]  # 取得旧页面版本。
        self.flow.set_trashed(self.study, True, "测试管理人", "只读测试")  # 移入临时研究回收站。
        with self.assertRaisesRegex(ContractError, "回收站"):  # 阻止旧复核表单。
            self.flow.review(self.study, run_id, "approved", "测试人", "过期页面")  # 不能绕过网页隐藏。
        with self.assertRaisesRegex(ContractError, "回收站"):  # 阻止旧修订表单。
            self.flow.revise_intake(self.study, self.intake, "过期修订", run_id)  # 不新建输入版本。
        with self.assertRaisesRegex(ContractError, "回收站"):  # 阻止新的计算启动。
            self.flow.begin(self.study, "A01", {}, {}, "过期启动")  # 不仅保护网页按钮。
        self.assertIsNone(self.flow.reusable(self.study, "A00", self.intake, {}))  # 回收站结果暂不供流程复用。

    def test_recycle_rejects_stale_management_and_running_work(self):  # 管理版本冲突和未结束运行不能静默处理。
        event = self.flow.set_trashed(self.study, True, "测试管理人", "管理版本测试")  # 创建首个管理版本。
        with self.assertRaises(ContractError):  # 旧页面没有最新管理编号时必须拒绝。
            self.flow.set_trashed(self.study, False, "测试管理人", "旧页面恢复")  # 不覆盖其他页面操作。
        self.flow.set_trashed(self.study, False, "测试管理人", "刷新后恢复", event["action_id"])  # 正确版本可以恢复。
        self.base()  # 构造一条可运行的测试路径。
        self.flow.begin(self.study, "A04", {}, {}, "尚未提交的任务")  # 模拟正在运行的模块。
        events = self.flow.load(self.study)["management_events"]  # 取得当前管理记录。
        latest = read_json(self.flow.location(self.study) / events[-1]["path"])  # 读取实际动作编号。
        with self.assertRaisesRegex(ContractError, "尚未完整提交"):  # 不在任务运行期间隐藏研究。
            self.flow.set_trashed(self.study, True, "测试管理人", "运行中移入", latest["action_id"])  # 需要先处理运行状态。

    def test_unapproved_parent_cannot_start(self):  # 未审核登记不能进入科学模块。
        with self.assertRaises(ContractError):  # 期望明确阻止。
            self.flow.begin(self.study, "A01", {}, {}, "试图跳过复核")  # 不允许只凭结果文件继续。

    def test_parallel_branches_and_docking_gate(self):  # 富集和 PPI 独立，对接先做对象复核。
        self.base()  # 准备交集。
        self.finish_module("A04")  # PPI 先结束。
        with self.assertRaises(ContractError):  # 没有对象批准不能对接。
            self.flow.begin(self.study, "A06", {}, {}, "对象尚未准备")  # 验证内部审核关口。
        self.finish_module("A06_PREP")  # 对象及配置已复核。
        self.finish_module("A06")  # 无需等待富集。
        with self.assertRaises(ContractError):  # 富集未齐不得开始正式报告。
            self.flow.begin(self.study, "A07", {}, {}, "缺少富集")  # 防止提前生成正式报告。
        self.finish_module("A05", outcome="empty")  # 有效空富集仍是可以复核的真实状态。
        self.finish_module("A07")  # 所有必需模块齐备才能进入报告。
        self.assertTrue(self.flow.approved(self.flow.load(self.study), self.flow.load(self.study)["current"]["A07"]))  # 检查最终批准可追溯。

    def test_upstream_change_only_invalidates_dependents(self):  # 更改 PPI 不应让富集失效。
        self.base()  # 准备交集路径。
        old_ppi = self.finish_module("A04")  # 保存旧 PPI 版本。
        enrichment = self.finish_module("A05")  # 保存独立富集分支。
        docking_prep = self.finish_module("A06_PREP")  # 保存依赖旧 PPI 的准备。
        self.flow.begin(self.study, "A04", {"changed": True}, {}, "更正PPI输入")  # 创建新 PPI 版本。
        manifest = self.flow.load(self.study)  # 重读版本指针。
        self.assertFalse(self.flow.approved(manifest, old_ppi))  # 旧 PPI 批准失效。
        self.assertFalse(self.flow.approved(manifest, docking_prep))  # 下游对象审核失效。
        self.assertTrue(self.flow.approved(manifest, enrichment))  # 富集仍然可用。

    def test_revision_and_restart_preserve_history(self):  # 关闭重开仍能查到旧数据与审核。
        original = self.flow.load(self.study)["current"]["A00"]  # 取得原登记版本。
        self.approve(original)  # 原登记通过。
        changed = dict(self.intake, disease="另一测试疾病")  # 只更改测试对象文字。
        new_run = self.flow.revise_intake(self.study, changed, "修订疾病", original)  # 创建新登记。
        restored = Workflow(self.root)  # 模拟程序重新打开。
        manifest = restored.load(self.study)  # 所有状态从磁盘恢复。
        self.assertEqual(restored.result(manifest, original)["summary"]["disease"], "测试疾病")  # 原结果不被覆盖。
        self.assertEqual(restored.result(manifest, new_run)["summary"]["disease"], "另一测试疾病")  # 新结果单独存在。
        self.assertEqual(len(manifest["reviews"]), 1)  # 旧复核记录保留。
        self.assertFalse(restored.approved(manifest, new_run))  # 新登记必须重新复核。

    def test_stale_page_cannot_overwrite_review(self):  # 两个页面同时审核时不丢失较新决定。
        run_id = self.flow.load(self.study)["current"]["A00"]  # 两个页面最初看到同一结果。
        first = self.approve(run_id)  # 第一个页面提交通过。
        with self.assertRaises(ContractError):  # 第二个页面旧令牌应被拒绝。
            self.flow.review(self.study, run_id, "rejected", "另一复核人", "旧页面退回")  # 不能覆盖刚保存的决定。
        self.flow.review(self.study, run_id, "pending", "测试复核人", "需补充核查", first["review_id"])  # 刷新后的明确撤回可以保存。
        self.assertFalse(self.flow.approved(self.flow.load(self.study), run_id))  # 撤回后下游不能再用。

    def test_reapproval_does_not_revive_old_downstream(self):  # 上游撤回后重批不能悄悄恢复旧下游批准。
        self.base()  # 建立已批准交集。
        ppi = self.finish_module("A04")  # PPI 使用当时的交集批准。
        manifest = self.flow.load(self.study)  # 取得交集复核信息。
        intersection = manifest["current"]["A03"]  # 定位原交集版本。
        artifact = self.flow.run(manifest, intersection)["artifact_id"]  # 获得交集产物身份。
        previous = self.flow.latest_review(manifest, artifact)  # 读取原批准记录。
        pending = self.flow.review(self.study, intersection, "pending", "测试人", "需要重新核查", previous["review_id"])  # 明确撤回原批准。
        self.flow.review(self.study, intersection, "approved", "测试人", "重新核验通过", pending["review_id"])  # 对同一交集重新批准。
        self.assertFalse(self.flow.approved(self.flow.load(self.study), ppi))  # 旧 PPI 不能自动恢复有效。

    def test_failed_and_empty_are_different(self):  # 失败与空集合不能混淆。
        self.base()  # 准备并行分支。
        failed = self.finish_module("A04", outcome="failed")  # 模拟执行失败。
        empty = self.finish_module("A05", outcome="empty")  # 模拟真实空结果。
        with self.assertRaises(ContractError):  # 失败没有批准路径。
            self.approve(failed)  # 不能通过人工按钮伪装成功。
        self.assertTrue(self.flow.approved(self.flow.load(self.study), empty))  # 有效空结果可正常复核。

    def test_file_tampering_blocks_use(self):  # 被修改的 CSV 不能继续供下游使用。
        self.base()  # 生成带明细的交集。
        manifest = self.flow.load(self.study)  # 获取准确文件索引。
        result = self.flow.result(manifest, manifest["current"]["A03"])  # 先核验原文件。
        record = next(item for item in result["files"] if item["role"] == "table")  # 找到测试明细表。
        path = self.flow.location(self.study) / record["path"]  # 定位临时测试文件。
        path.write_text("tampered", encoding="utf-8")  # 仅在测试目录模拟篡改。
        with self.assertRaises(ContractError):  # 缓存与启动均应拒绝。
            self.flow.begin(self.study, "A04", {}, {}, "试用被修改表格")  # 必须校验内容而不只看存在。

    def test_cache_checks_inputs_configuration_and_code(self):  # 可复用必须匹配输入、参数、代码和输出。
        self.base()  # 生成可审核的交集结果。
        self.assertIsNotNone(self.flow.reusable(self.study, "A03", {"test_input": True}, {"test_config": 1}))  # 相同条件可复用。
        self.assertIsNone(self.flow.reusable(self.study, "A03", {"test_input": True}, {"test_config": 2}))  # 参数变化需新运行。
        self.assertIsNone(self.flow.reusable(self.study, "A03", {"test_input": False}, {"test_config": 1}))  # 输入变化需新运行。
        self.flow.code_version = "different-code"  # 模拟代码修订。
        self.assertIsNone(self.flow.reusable(self.study, "A03", {"test_input": True}, {"test_config": 1}))  # 代码变化不复用旧结果。

    def test_cross_study_and_path_traversal_rejected(self):  # 防止研究之间串文件。
        other = self.flow.create(self.intake, kind="contract_test")  # 建立第二项独立测试。
        run_id = self.flow.load(self.study)["current"]["A00"]  # 取第一项研究运行。
        with self.assertRaises(ContractError):  # 不允许跨研究审核。
            self.flow.review(other, run_id, "approved", "测试人", "跨研究尝试")  # 编号必须属于当前研究。
        with self.assertRaises(ContractError):  # 路径不能冒充研究编号。
            self.flow.load("../outside")  # 不能读取研究包之外的文件。

    def test_late_result_after_input_change_rejected(self):  # 慢计算不能回写过期输入结果。
        self.base()  # 准备交集。
        ppi = self.flow.begin(self.study, "A04", {}, {}, "启动测试计算")  # 计算尚未完成。
        self.flow.begin(self.study, "A03", {"changed": True}, {}, "更正交集")  # 期间上游改变。
        with self.assertRaises(ContractError):  # 旧输入产物不能发布。
            self.flow.finish(self.study, ppi["run_id"], {"late": True})  # 不抢占新状态。

    def test_real_study_blocks_unconnected_science(self):  # 正式研究不能使用测试占位分析。
        study = self.flow.create(self.intake)  # 默认创建正式研究类型。
        run_id = self.flow.load(study)["current"]["A00"]  # 取得实际登记。
        self.flow.review(study, run_id, "approved", "测试人", "测试审核")  # 只批准登记。
        with self.assertRaises(ContractError):  # 未接入科学模块必须明确阻止。
            self.flow.begin(study, "A01", {}, {}, "不允许伪造科学输出")  # 需要后续正式适配器。
        self.assertEqual(self.flow.view(study)["modules"][1]["state"], "not_connected")  # 网页显示真实限制。

    def test_original_intake_is_part_of_integrity_chain(self):  # 原始登记不能被修改后继续使用。
        manifest = self.flow.load(self.study)  # 获取当前登记。
        run_id = manifest["current"]["A00"]  # 定位输入快照。
        result = self.flow.result(manifest, run_id)  # 读取来源索引。
        self.assertEqual(len(result["sources"]), 1)  # 必须包含原始登记来源。
        source = self.flow.location(self.study) / result["sources"][0]["path"]  # 定位临时原始资料。
        source.write_text("changed", encoding="utf-8")  # 模拟原始资料被替换。
        with self.assertRaises(ContractError):  # 复核不能再通过。
            self.approve(run_id)  # 检验来源链，而非仅校验摘要。

    def test_duplicate_finish_does_not_overwrite(self):  # 运行结束后只能新增版本。
        run_id = self.flow.load(self.study)["current"]["A00"]  # 首次登记已经提交。
        with self.assertRaises(ContractError):  # 重复提交不能覆盖。
            self.flow.finish(self.study, run_id, {"changed": True})  # 强制保留原输出。

    def test_http_create_review_and_origin_protection(self):  # 验证网页真正提交到同一内核。
        def verified_mesh(term, descriptor_id):  # 测试使用固定官方形状，不访问外网。
            return {"status": "verified", "mesh_id": descriptor_id, "preferred_term": term, "mesh_year": "2026", "checked_at": "2026-09-28T00:00:00+00:00", "provider": "U.S. National Library of Medicine", "api_version": "test", "descriptor_resource": "http://id.nlm.nih.gov/mesh/2026/" + descriptor_id, "entry_terms": [term], "evidence": {"years_sha256": "a", "descriptor_sha256": "b", "details_sha256": "c"}}  # 字段满足生产契约但明确是测试证据。
        server = create_server(self.root, 0, mesh_verifier=verified_mesh)  # 系统分配临时端口，不占正式入口。
        worker = threading.Thread(target=server.serve_forever, daemon=True)  # 在短时线程中提供服务。
        worker.start()  # 开始响应本机请求。
        address = "http://127.0.0.1:" + str(server.server_port)  # 取得可访问地址。
        try:  # 无论测试是否通过都关闭服务。
            html = urlopen(address).read().decode("utf-8")  # 获取真实首页。
            token = re.search(r'name="token" value="([^"]+)"', html).group(1)  # 使用页面生成的令牌。
            data = dict(self.intake, mesh_term="Pulmonary Disease, Chronic Obstructive", mesh_id="D029424", token=token)  # 提交带MeSH身份的测试登记字段。
            response = urlopen(Request(address + "/create", urlencode(data).encode("utf-8")))  # 模拟浏览器提交。
            created_html = response.read().decode("utf-8")  # 读取A00尚未通过的真实页面。
            self.assertIn("研究与逐模块复核", created_html)  # 跳转到真实研究页面。
            self.assertIn("疾病数据库资料准备", created_html)  # 新研究可在A00提前准备人工来源。
            self.assertIn("暂存并校验TTD", created_html)  # TTD详细资料入口与其他人工来源同层显示。
            self.assertNotIn("TTD备用上传", created_html)  # 新版不再把TTD藏在折叠区。
            self.assertIn("暂存并校验PharmGKB", created_html)  # PharmGKB详细资料入口与其他人工来源同层显示。
            self.assertNotIn("PharmGKB备用上传", created_html)  # 新版不再把PharmGKB藏在折叠区。
            study_id = response.url.split("study=")[1]  # 从跳转取新研究编号。
            view = json.loads(urlopen(address + "/api/study?study=" + study_id).read())  # 从同一接口读取状态。
            run_id = view["manifest"]["current"]["A00"]  # 当前登记版本。
            review = {"token": token, "study": study_id, "run": run_id, "reviewer": "网页测试", "note": "测试通过", "decision": "approved", "previous": ""}  # 构造实际审核表单。
            page_html = urlopen(Request(address + "/review", urlencode(review).encode("utf-8"))).read().decode("utf-8")  # 保存并读取新页面。
            self.assertIn("已复核通过", page_html)  # 页面显示审核结果。
            bad = Request(address + "/review", urlencode(review).encode("utf-8"), headers={"Origin": "https://example.invalid"})  # 模拟外部网页提交。
            with self.assertRaises(HTTPError) as error:  # 必须拒绝外站写入。
                urlopen(bad)  # 不允许利用本机服务改资料。
            self.assertEqual(error.exception.code, 400)  # 确认不是静默接受。
        finally:  # 不遗留本机测试服务。
            server.shutdown()  # 结束请求循环。
            server.server_close()  # 释放临时端口。
            worker.join(timeout=3)  # 等待线程退出。

if __name__ == "__main__":  # 直接运行本文件时启动全部测试。
    unittest.main(verbosity=2)  # 输出每个验收场景及结果。

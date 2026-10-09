# A03联合检查使用临时目录和明确标记的合成数据。
import sys  # 加载本项目源码。
import tempfile  # 测试不进入正式研究目录。
import unittest  # 标准库测试框架。
from pathlib import Path  # 使用项目相对路径。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 不引用旧项目。
from workflow import Workflow  # 验证真实归档和依赖。
from contracts import ContractError  # 断言明确错误。
from intersection_flow import run_intersection, run_selection, validate_intersection, validate_selection, build, payload_from  # 实际实现。
import test_intersection  # 复用可手算的小型输入。

def setup_study(root):  # 浏览器与单元测试使用同一上游合成数据。
    flow = Workflow(root, {"A03": validate_intersection, "A03_SELECT": validate_selection})  # A01/A02测试占位只用于contract_test。
    sid = flow.create({"formula": "A03合成验收方", "herbs": "A、B、C", "disease": "合成疾病", "disease_scope": "仅验证代码，不作科学结论", "operator": "自动测试", "species": 9606}, kind="contract_test")  # 用户研究绝不改动。
    flow.review(sid, flow.load(sid)["current"]["A00"], "approved", "测试", "测试登记")  # 明确测试签署。
    components, memberships, edges, disease, herbs, namespace = test_intersection.IntersectionTests().data()  # 六个并列成分。
    for row in edges + disease:  # 改为测试用HGNC形式，不表示真实生物关联。
        row.update(target_id="HGNC:1", symbol="SYNTHETIC_TEST")  # 虚构关系只标记测试。
    summary = {"namespace": "HGNC", "mapping_snapshot": "a" * 64}  # 合成映射快照标识。
    a01 = {"components": components, "herb_components": memberships, "herb_summary": [{"herb": h} for h in herbs], "normalized_compound_targets": edges}  # 符合未来上游字段契约。
    for module, tables in (("A01", a01), ("A02", {"normalized_targets": disease, "source_summary": []})):  # 两侧独立复核。
        run = flow.begin(sid, module, {"test_only": True}, {}, "合成上游")  # 不冒称真实HGNC校准。
        flow.finish(sid, run["run_id"], summary, tables)  # 写入临时研究。
        flow.review(sid, run["run_id"], "approved", "测试", "合成资料")  # 测试批准。
    return flow, sid  # 供真实网页读取此临时研究。

class FlowTests(unittest.TestCase):  # 检验A03的科学输出与分支独立。
    def setUp(self):  # 每项测试独立创建。
        self.temp = tempfile.TemporaryDirectory(prefix="moduleA_a03_")  # 自动清理临时目录。
        self.flow, self.sid = setup_study(Path(self.temp.name))  # 不接触用户数据。

    def tearDown(self):  # 测试失败也释放目录。
        self.temp.cleanup()  # 只清理本测试。

    def run03(self):  # 统一启动实际A03函数。
        return run_intersection(self.flow, self.sid, self.flow.load(self.sid)["current"], "合成交集测试")  # 固定当前上游。

    def approve(self, run):  # 测试用明确批准。
        self.flow.review(self.sid, run, "approved", "测试复核", "测试用途")  # 不冒用户身份。

    def test_archive_and_restart(self):  # 归档图表和两种排序一致。
        result = self.run03()  # 真实计算、CSV与SVG归档。
        self.assertEqual(result["summary"]["交集靶点数"], 1)  # 六条边只计一个靶点。
        self.assertTrue(result["summary"]["截断处需要并列选择"])  # 并列不自动裁剪。
        self.assertEqual(len(result["tables"]["network_edges"]), 13)  # 六条靶点边与七条药味边。
        self.assertEqual(len(result["figures"]), 1)  # 真实SVG已保存。
        again = Workflow(Path(self.temp.name))  # 模拟重开。
        self.assertEqual(again.result(again.load(self.sid), result["run_id"]), result)  # 全部关联文件核验一致。

    def test_branches(self):  # 选择修改不影响PPI与富集。
        parent = self.run03()["run_id"]  # 交集版本。
        self.approve(parent)  # 交集可交接。
        downstream = []  # 记录独立分支。
        for module in ("A04", "A05"):  # 无候选选择也能启动。
            run = self.flow.begin(self.sid, module, {}, {}, "测试独立分支")  # 仅测试占位。
            self.flow.finish(self.sid, run["run_id"], {"test_only": True})  # 不伪造实际分析。
            self.approve(run["run_id"])  # 保留测试批准。
            downstream.append(run["run_id"])  # 后续检查不失效。
        with self.assertRaises(ContractError):  # 对接准备必须等候选通过。
            self.flow.begin(self.sid, "A06_PREP", {}, {}, "不应通过")  # 禁止绕过。
        choice = run_selection(self.flow, self.sid, parent, "", ["0", "1", "2", "3", "4"], "测试", "并列身份核对", True)  # 第一版候选。
        self.approve(choice["run_id"])  # 对接分支批准。
        prep = self.flow.begin(self.sid, "A06_PREP", {}, {}, "测试对接依赖")  # 此时允许准备。
        self.flow.finish(self.sid, prep["run_id"], {"test_only": True})  # 仅合同测试。
        run_selection(self.flow, self.sid, parent, choice["run_id"], ["5"], "测试", "仅选一个并说明替换", True)  # 新候选版本。
        manifest = self.flow.load(self.sid)  # 检查状态传播。
        self.assertTrue(all(self.flow.approved(manifest, rid) for rid in downstream))  # PPI富集批准保留。
        self.assertFalse(self.flow.active(manifest, prep["run_id"]))  # 对接准备失效。

    def test_stale_page_and_upstream(self):  # 重复点击与上游改变受控。
        expected = dict(self.flow.load(self.sid)["current"])  # 保存旧页面版本。
        parent = self.run03()["run_id"]  # 建立交集。
        with self.assertRaises(ContractError):  # 不重复提交。
            run_intersection(self.flow, self.sid, expected, "旧页面")  # 应失败。
        self.flow.begin(self.sid, "A02", {}, {}, "合成上游新版本")  # 改变疾病来源。
        self.assertFalse(self.flow.active(self.flow.load(self.sid), parent))  # 交集随真实依赖失效。

    def test_mapping_and_candidate_rejected(self):  # 不将A02候选或不同快照当作正式D。
        manifest = self.flow.load(self.sid)  # 读取两侧测试结果。
        one, two = [self.flow.result(manifest, manifest["current"][key]) for key in ("A01", "A02")]  # 实际接口输入。
        two["summary"]["handoff_blocked"] = True  # 模拟真实候选阶段。
        with self.assertRaises(ContractError):  # 必须停止。
            payload_from(one, two)  # 不绕过候选门控。
        two["summary"].pop("handoff_blocked")  # 接着单独测快照。
        two["summary"]["mapping_snapshot"] = "b" * 64  # 两侧版本不同。
        with self.assertRaises(ContractError):  # 不能直接匹配。
            payload_from(one, two)  # 拒绝混合快照。

    def test_mapping_rule_mismatch(self):  # 同数据不同算法不能混用。
        manifest = self.flow.load(self.sid)  # 临时研究。
        one, two = [self.flow.result(manifest, manifest["current"][key]) for key in ("A01", "A02")]  # 相同测试快照。
        one["summary"]["mapping_rule"] = "HGNC.resolve.2"  # 只有一侧声明新规则。
        with self.assertRaises(ContractError):  # 单侧遗漏也拒绝。
            payload_from(one, two)  # 禁止无声混合。
        two["summary"]["mapping_rule"] = "HGNC.resolve.1"  # 两侧明确不一致。
        with self.assertRaises(ContractError):  # 版本冲突不放行。
            payload_from(one, two)  # 数据相同也不足。
        two["summary"]["mapping_rule"] = "HGNC.resolve.2"  # 完全一致。
        self.assertEqual(payload_from(one, two)["namespace"], "HGNC")  # 合法接口仍可用。
        one["summary"]["identity_evidence_snapshot"] = "a" * 64  # 仅一侧有补充证据。
        with self.assertRaises(ContractError):  # 不允许两侧身份依据不同。
            payload_from(one, two)  # 同HGNC快照也必须拒绝。

    def test_identity_and_budget(self):  # 候选保存前确认身份。
        parent = self.run03()["run_id"]  # 交集输入。
        self.approve(parent)  # 先复核交集。
        with self.assertRaises(ContractError):  # 未确认身份不得保存。
            run_selection(self.flow, self.sid, parent, "", ["0"], "测试", "未核验", False)  # 显式缺条件。
        choice = run_selection(self.flow, self.sid, parent, "", ["0", "1", "2", "3", "4"], "测试", "已核验并列", True)  # 合法选择。
        self.assertEqual([row["compound_id"] for row in choice["tables"]["supplements"]], ["5"])  # C药补充。
        self.assertFalse(choice["tables"]["supplements"][0]["automatic_docking"])  # 仅存清单。

    def test_legacy_graph_compatibility(self):  # 复算旧图Degree，不冒称新疾病筛选一致。
        import json  # 读取固定快照和对比记录。
        import hashlib  # 校验历史输入未改变。
        from collections import Counter  # 独立按旧图邻边计数。
        from intersection import calculate  # 检查同一纯计算入口。
        project = Path(__file__).resolve().parents[1]  # 固定新项目参考路径。
        raw = (project / "references/network_copd_20260902.json").read_bytes()  # 不再访问旧目录。
        record = json.loads((project / "governance/P2_A03_Kimi图复算对比.json").read_text(encoding="utf-8"))  # 比较快照身份。
        self.assertEqual(hashlib.sha256(raw).hexdigest(), record["source_sha256"])  # 来源文件必须一致。
        old = json.loads(raw.decode("utf-8-sig"))  # 旧图仅用于兼容性测试。
        compounds = [{"compound_id": row["id"], "name": row["id"]} for row in old["nodes"] if row["node_type"] == "component"]  # 旧图身份仍按原名称。
        herbs = [row["id"] for row in old["nodes"] if row["node_type"] == "herb"]  # 原药味不改名。
        memberships = [{"herb": row["source"], "compound_id": row["target"]} for row in old["edges"] if row["edge_type"] == "herb-component"]  # 原图药味边。
        edges = [{"compound_id": row["source"], "target_id": row["target"], "species": 9606, "source_ref": "旧图边"} for row in old["edges"] if row["edge_type"] == "component-target"]  # 已经是交集边，不能当完整T。
        disease = [{"target_id": gene, "species": 9606, "source_ref": "旧图交集"} for gene in old["targets"]]  # 不能当完整D。
        result = calculate(compounds, memberships, edges, disease, herbs, "legacy_graph_names_not_HGNC")  # 仅纯计算兼容性比较。
        counts = Counter()  # 独立邻边计数。
        for a, b, kind in {(row["source"], row["target"], row["edge_type"]) for row in old["edges"]}:  # 对旧边去重。
            counts[a] += 1  # 无向度的起点贡献。
            counts[b] += 1  # 无向度的终点贡献。
        self.assertEqual(result["counts"]["intersection"], 186)  # 仅此固定旧图的验收数字。
        self.assertTrue(all(row["mixed_degree"] == counts[row["compound_id"]] for row in result["ranking"]))  # 每个成分逐一比较。

if __name__ == "__main__":  # 独立运行测试。
    unittest.main()  # 输出真实检查结果。

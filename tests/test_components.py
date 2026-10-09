# 本文件使用临时研究验证A01，不读写用户正式研究。
from pathlib import Path  # 定位新项目代码与只读数据。
import copy  # 构造互不影响的异常测试记录。
import csv  # 写入小型测试快照。
import hashlib  # 生成测试数据指纹。
import sys  # 引用新项目模块。
import tempfile  # 隔离测试资料。
import unittest  # 使用标准库测试框架。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 不引用旧功能代码。
from components import CONFIG, analyze, select_rows, run_components, validate_components  # 验证实际实现。
from contracts import ContractError  # 断言真实校验错误。
from storage import read_json, write_json  # 与实际留存格式一致。
from workflow import Workflow  # 验证模块衔接。
PROJECT = Path(__file__).resolve().parents[1]  # 从当前位置找到项目根目录。

def sample(line=2, **changes):  # 产生明确标记的虚构原始记录。
    row = {"Chinesename": "测试甲", "MOLID": "MOL000001", "moleculename": "test compound", "ob": "30", "dl": "0.18", "UniProtAC": "P00001", "GeneNames": "TEST1", "Organism": "Homo sapiens (Human)", "source_line": line}  # 正好位于批准阈值边界。
    row.update(changes)  # 每个测试只修改所需因素。
    return row  # 虚构数据不作为研究证据。

def fixture(root):  # 只在临时目录写入微型快照。
    folder = root / "references"  # 与生产来源接口一致。
    folder.mkdir()  # 不操作正式references。
    row = sample()  # 单条测试记录足够验证保存与网页。
    del row["source_line"]  # 原表行号由读取函数生成。
    path = folder / "tcmsp_snapshot.tsv"  # 临时目录与真实目录明确隔离。
    with path.open("w", encoding="gbk", newline="") as stream:  # 模拟实际源编码。
        writer = csv.DictWriter(stream, fieldnames=list(row), delimiter="\t")  # 保留与实际一致的字段。
        writer.writeheader()  # 输出首行表头。
        writer.writerow(row)  # 保存一条虚构证据。
    data = path.read_bytes()  # 指纹来自真实写入字节。
    write_json(folder / "tcmsp_snapshot.json", {"source_id": "synthetic_test_only", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "encoding": "gbk", "database_release": "虚构验收快照"})  # 不冒充真实数据库。

class ComponentTests(unittest.TestCase):  # 计算规则与归档衔接分开检查。
    def test_boundary_and_exclusion(self):  # 正好等于阈值应通过，小于阈值应排除。
        rows = [sample(), sample(3, MOLID="MOL000002", ob="29.99"), sample(4, MOLID="MOL000003", dl="0.179")]  # 不引入身份冲突。
        summary, tables, anomalies = analyze(rows, ["测试甲"])  # 使用实际计算函数。
        self.assertEqual(summary["筛选后不同成分数"], 1)  # 边界含等号。
        self.assertEqual(len(tables["exclusions"]), 2)  # 两种阈值失败均保留。
        validate_components({"config": CONFIG}, summary, tables, anomalies, "success")  # 验证实际结果契约。

    def test_shared_and_duplicate(self):  # 共享药味及重复行不能抬高全方计数。
        rows = [sample(), sample(3), sample(4, Chinesename="测试乙")]  # 同成分同靶点三条来源。
        summary, tables, _ = analyze(rows, ["测试甲", "测试乙"])  # 汇总来源但不丢原行。
        self.assertEqual(summary["去重成分—人类靶点关系数"], 1)  # 去重后只有一条关系。
        self.assertEqual(summary["人类关系证据行数"], 3)  # 原始证据行仍为三条。
        self.assertEqual(len(tables["herb_components"]), 2)  # 两个药味来源都保留。

    def test_nonhuman_and_missing(self):  # 缺物种或非人类不纳入人类关系。
        rows = [sample(), sample(3, Organism="Escherichia coli"), sample(4, Organism="")]  # 明确两种排除原因。
        summary, tables, _ = analyze(rows, ["测试甲"])  # 不调用外部查询补齐。
        self.assertEqual(summary["人类关系证据行数"], 1)  # 仅第一行计入。
        self.assertEqual(len(tables["exclusions"]), 2)  # 缺物种与非人类均留痕。

    def test_missing_ob_not_replaced(self):  # 缺OB不能只用DL放行。
        summary, tables, _ = analyze([sample(ob="")], ["测试甲"])  # 模拟待补充资料。
        self.assertEqual(summary["筛选后不同成分数"], 0)  # 不虚构预测值。
        self.assertIn("待补充", tables["exclusions"][0]["reason"])  # 明确待处理。

    def test_ambiguous_mapping(self):  # 同一蛋白对应冲突基因时不任取一项。
        summary, tables, _ = analyze([sample(), sample(3, GeneNames="TEST2")], ["测试甲"])  # 构造实际冲突。
        self.assertEqual(summary["不同人类基因数"], 0)  # 冲突不进入主集合。
        self.assertTrue(all("待核验" in row["reason"] for row in tables["exclusions"]))  # 原行保留为待复核。

    def test_same_name_different_ids(self):  # 不凭相似名称合并化学身份。
        summary, _, _ = analyze([sample(), sample(3, MOLID="MOL000002")], ["测试甲"])  # 名称相同而编号不同。
        self.assertEqual(summary["筛选后不同成分数"], 2)  # 保留两个数据库身份。

    def test_snapshot_case(self):  # 用原始快照独立检验玉屏风数量。
        rows, _ = select_rows(PROJECT, ["黄芪", "白术", "防风"])  # 只读真实共享来源。
        summary, tables, _ = analyze(rows, ["黄芪", "白术", "防风"])  # 不使用旧代码结果作为输入。
        self.assertEqual((len(rows), summary["筛选后不同成分数"], summary["不同人类基因数"]), (3633, 37, 211))  # 参考值来自原始行人工核查。
        self.assertEqual(summary["去重成分—人类靶点关系数"], 696)  # 去重后关系数与证据行数区分。
        self.assertEqual(sum(row["reason"].startswith("非人类") for row in tables["exclusions"]), 10)  # 非人类原始行单列。

    def test_archive_and_invalidation(self):  # 验证运行、复核、重开、旧页面及上游变化。
        with tempfile.TemporaryDirectory() as temporary:  # 不在真实studies创建验收资料。
            root = Path(temporary)  # 测试独立根目录。
            fixture(root)  # 放入虚构来源。
            flow = Workflow(root, {"A01": validate_components})  # 使用正式模块校验。
            intake = {"formula": "测试方", "herbs": "测试甲", "disease": "测试病", "disease_scope": "仅验收", "operator": "自动测试", "species": 9606}  # 不冒用用户研究。
            sid = flow.create(intake)  # 独立研究编号。
            a00 = flow.load(sid)["current"]["A00"]  # 当前登记版本。
            with self.assertRaises(ContractError):  # 上游不通过时不能开始。
                run_components(flow, sid, a00, "", "测试未批准")  # 不建立A01运行。
            flow.review(sid, a00, "approved", "自动测试", "仅验收")  # 模拟明确批准。
            result = run_components(flow, sid, a00, "", "测试归档")  # 执行真实归档流程。
            raw = read_json(flow.location(sid) / result["sources"][0]["path"])  # 回读研究包原始资料。
            self.assertEqual(analyze(raw, ["测试甲"])[1], result["tables"])  # 单个研究包所带快照可重算同样的表。
            reopened = Workflow(root, {"A01": validate_components})  # 模拟关闭程序后重开。
            self.assertEqual(reopened.view(sid)["modules"][1]["state"], "awaiting_review")  # 不自动批准。
            with self.assertRaises(ContractError):  # 旧页面重复提交不能生成第二条新运行。
                run_components(flow, sid, a00, "", "旧页面")  # expected_a01已不是空。
            flow.review(sid, result["run_id"], "approved", "自动测试", "仅验收")  # 批准A01。
            flow.revise_intake(sid, dict(intake, disease="另一个测试病"), "修订测试", a00)  # 创建新登记版本。
            self.assertEqual(flow.view(sid)["modules"][1]["state"], "stale")  # 原A01不再被当作有效当前结果。
            self.assertEqual(len(flow.load(sid)["runs"]), 3)  # 失败旧页面操作没有新增运行。

    def test_source_tamper_and_missing_herb(self):  # 缺药味与来源篡改明确报错。
        with tempfile.TemporaryDirectory() as temporary:  # 隔离来源变更。
            root = Path(temporary)  # 不修改真实数据。
            fixture(root)  # 建立微型来源。
            with self.assertRaises(ContractError):  # 未收录药味不伪装成筛选后空集。
                select_rows(root, ["未收录药味"])  # 不自动使用别名。
            with (root / "references" / "tcmsp_snapshot.tsv").open("ab") as stream:  # 仅修改虚构来源。
                stream.write(b"changed")  # 模拟来源变化。
            with self.assertRaises(ContractError):  # 指纹失配必须中止。
                select_rows(root, ["测试甲"])  # 不沿用旧元信息。

if __name__ == "__main__":  # 直接执行时运行验收。
    unittest.main(verbosity=2)  # 逐项报告真实通过或失败。

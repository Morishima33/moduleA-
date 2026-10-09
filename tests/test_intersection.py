"""A03独立测试：仅用合成标识，不读写正式研究。"""  # 固定可手工核算的数据。
import sys  # 导入项目源码所需路径支持。
import unittest  # 使用标准库测试框架。
from pathlib import Path  # 定位当前项目。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 不依赖旧项目路径。
from intersection import calculate, coverage, expanded_pool  # 测试同一计算入口及受控扩展规则。
from contracts import ContractError  # 检查错误数据被明确拒绝。


class IntersectionTests(unittest.TestCase):  # 验证数量、并列、覆盖及失败边界。
    def data(self):  # 构造六个并列成分和一个零命中成分。
        components = [{"compound_id": str(i), "name": "成分" + str(i)} for i in range(7)]  # 稳定身份。
        memberships = [{"compound_id": str(i), "herb": "A" if i < 5 else "C"} for i in range(7)]  # 第六名来自未覆盖药味。
        memberships.append({"compound_id": "0", "herb": "B"})  # 首个成分为共享成分。
        edges = [{"compound_id": str(i), "target_id": "G1", "species": 9606, "source_ref": "原表:" + str(i)} for i in range(6)]  # 六个成分各命中一个基因。
        disease = [{"target_id": "G1", "species": 9606, "source_ref": "疾病表:1"}]  # 精确单基因疾病集合。
        return components, memberships, edges, disease, ["A", "B", "C"], "合成测试ID"  # 不暗示真实映射规则。

    def test_counts_and_ranks(self):  # 交集和混合图指标区分。
        result = calculate(*self.data())  # 获取共同结果。
        self.assertEqual(result["counts"]["intersection"], 1)  # 六条成分边不变成六个基因。
        self.assertTrue(result["requires_tie_review"])  # 六名并列不能自动取五名。
        self.assertEqual(len(result["boundary"]), 6)  # 完整保留并列池。
        first = result["ranking"][0]  # 编号零稳定排在同分首行。
        self.assertEqual((first["main_rank"], first["mixed_degree"], first["herb_edges"]), (1, 3, 2))  # 药味边贡献独立显示。
        self.assertIsNone(result["ranking"][-1]["degree_rank"])  # 零命中者不伪装为入网候选。

    def test_duplicates_preserve_sources(self):  # 多来源不重复计数。
        data = list(self.data())  # 复制容器方便添加证据。
        data[2].append(dict(data[2][0], source_ref="另一来源"))  # 同成分同基因另一证据。
        data[3].append(dict(data[3][0], source_ref="另一疾病库"))  # 多库同一基因。
        result = calculate(*data)  # 输入证据保留。
        self.assertEqual(result["ranking"][0]["intersection_count"], 1)  # 主排序不膨胀。
        self.assertEqual(len(result["formula_evidence"]), 7)  # 原证据仍可溯源。
        self.assertEqual(result["counts"]["disease"], 1)  # 疾病集合也去重。

    def test_coverage_supplement(self):  # 补充药味不自动进入对接。
        result = calculate(*self.data())  # 使用并列测试。
        choice = coverage(result, ["0", "1", "2", "3", "4"], ["A", "B", "C"], "测试复核人", "测试选择及身份核验")  # 人工选择理由明确。
        self.assertEqual([r["compound_id"] for r in choice["supplements"]], ["5"])  # 未覆盖C提出自己的最高者。
        self.assertFalse(choice["supplements"][0]["automatic_docking"])  # 不扩大主预算。
        self.assertEqual(len(choice["selected"]), 5)  # 主清单原样保留。

    def test_empty_intersection(self):  # 无交集不凑数。
        data = list(self.data())  # 构造另一疾病。
        data[3] = [{"target_id": "OTHER", "species": 9606, "source_ref": "疾病表:2"}]  # 与方剂完全不交。
        result = calculate(*data)  # 空集是合法结果。
        self.assertEqual(result["counts"], {"formula": 1, "disease": 1, "intersection": 0, "formula_only": 1, "disease_only": 1})  # 三集合核对。
        self.assertEqual(result["boundary"], [])  # 无伪造主候选。

    def test_no_case_mapping(self):  # 本模块不冒充基因标准化。
        data = list(self.data())  # 修改标识大小写。
        data[3][0]["target_id"] = "g1"  # 与G1严格不同。
        self.assertEqual(calculate(*data)["counts"]["intersection"], 0)  # 不凭大小写自行认定同一身份。

    def test_invalid_identity(self):  # 拒绝跨物种及缺来源。
        data = list(self.data())  # 独立输入。
        data[2][0]["species"] = 10090  # 混入非人类。
        with self.assertRaises(ContractError):  # 不接受混合物种。
            calculate(*data)  # 应停止。

    def test_invalid_selection(self):  # 预算与基础资格不放宽。
        result = calculate(*self.data())  # 获取候选表。
        for selected in (["0"] * 2, [str(i) for i in range(6)], ["6"]):  # 重复、超限、零命中。
            with self.assertRaises(ContractError):  # 三者均拒绝。
                coverage(result, selected, ["A", "B", "C"], "复核人", "原因")  # 理由不覆盖硬条件。

    def test_expanded_ties_and_herb_representative(self):  # 并列和未覆盖药味首位可经人工决定同时纳入。
        components = [{"compound_id": str(i), "name": "成分" + str(i)} for i in range(7)]  # 七个可核对身份。
        memberships = [{"compound_id": str(i), "herb": "A" if i < 6 else "C"} for i in range(7)]  # 前六个不覆盖C药。
        edges = []  # 构造第5与第6并列、第7为C药首位。
        for cid, count in enumerate((6, 5, 4, 3, 2, 2, 1)):  # 名次为1、2、3、4、5、5、7。
            edges.extend({"compound_id": str(cid), "target_id": "G" + str(number), "species": 9606, "source_ref": "原表"} for number in range(1, count + 1))  # 每个成分靶点数可手算。
        disease = [{"target_id": "G" + str(number), "species": 9606, "source_ref": "疾病表"} for number in range(1, 7)]  # 所有方剂靶点均进入交集。
        result = calculate(components, memberships, edges, disease, ["A", "C"], "合成测试ID")  # 使用生产计算逻辑。
        pool = expanded_pool(result, ["A", "C"])  # 计算允许扩展的封闭名单。
        self.assertEqual(pool["primary"], ["0", "1", "2", "3", "4", "5"])  # 截断并列完整保留。
        self.assertEqual(pool["representatives"], ["6"])  # C药只提出本味最高位。
        choice = coverage(result, list("0123456"), ["A", "C"], "测试复核人", "两名并列和C药首位均纳入", True)  # 模拟明确人工决定。
        self.assertEqual(choice["roles"]["4"], "截断处并列纳入")  # 并列理由单独保存。
        self.assertEqual(choice["roles"]["6"], "药味代表性补充纳入")  # 药味代表不能伪装成前五。


if __name__ == "__main__":  # 可独立运行本测试文件。
    unittest.main()  # 打印真实检查结果。

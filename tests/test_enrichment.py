# 用独立手算概率验证固定ORA实现。
import sys  # 引入项目代码。
import math  # 组合数手算。
import unittest  # 自动检查。
import xml.etree.ElementTree as ET  # 检查图形格式。
from pathlib import Path  # 明确项目目录。
ROOT=Path(__file__).resolve().parents[1]  # 使用新项目。
sys.path.insert(0,str(ROOT/"src"))  # 不读取旧代码。
from enrichment_flow import r_call, kegg_terms  # 实际实现。
from enrichment_plot import chart  # 实际图形。
from contracts import ContractError  # 错误来源必须拒绝。
class EnrichmentTests(unittest.TestCase):  # 不使用真实研究审批。
    def test_ora(self):  # 分母与独立超几何概率。
        terms=[{"id":"T1","description":"first","genes":[str(i) for i in range(1,11)]},{"id":"T2","description":"other","genes":[str(i) for i in range(11,41)]}]  # 背景40。
        value={"genes":["1","2","3","4","5","999"],"annotations":{g:terms for g in ("BP","CC","MF","KEGG")}}  # 999无注释。
        result,_=r_call(ROOT,"analyze",value)  # 执行固定R工具。
        for data in result.values():  # 四类分别验证。
            self.assertEqual(len(data["all"]),1)  # 只有命中条目被实际检验。
            row=data["all"][0]  # 唯一检验条目。
            self.assertAlmostEqual(row["pvalue"],math.comb(10,5)/math.comb(40,5),places=12)  # 独立概率。
            self.assertEqual(row["GeneRatio"],"5/5")  # 不用原始6作分母。
            self.assertEqual(row["BgRatio"],"10/40")  # 背景完整。
            self.assertEqual(len(data["significant"]),1)  # qvalue缺失不误删BH显著。
        value["genes"]=["999"]  # 无有效输入。
        result,_=r_call(ROOT,"analyze",value)  # 空分析正常输出。
        self.assertTrue(all(not x["all"] for x in result.values()))  # 不凑非显著结果。
    def test_source_and_plot(self):  # 来源与SVG边界。
        source={"names":{"response_text":"hsa00001\tHuman pathway\n"},"links":{"response_text":"hsa:1\tpath:hsa00001\n"}}  # 合法来源。
        self.assertEqual(kegg_terms(source)[0]["genes"],["1"])  # 解析正确。
        source["links"]["response_text"]="mmu:1\tpath:hsa00001"  # 错误物种。
        with self.assertRaises(ContractError):  # 不静默接受。
            kegg_terms(source)  # 应拒绝。
        for kind in ("bar","bubble"):  # 两类图形。
            ET.fromstring(chart([],"BP",kind))  # 空图有效。
            ET.fromstring(chart([{"Description":"A & B <term>","Count":2,"GeneRatio":"2/5","p.adjust":0.01}],"KEGG",kind))  # 特殊字符安全。
if __name__=="__main__":  # 独立测试入口。
    unittest.main(verbosity=2)  # 显示结果。

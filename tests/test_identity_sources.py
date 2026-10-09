# 身份补查边界测试，使用虚构基因和查询，不能当作科研证据。
import csv  # 构造小型官方格式表。
import gzip  # 压缩测试快照。
import hashlib  # 计算响应指纹。
import io  # 不生成额外临时文件。
import json  # 构造明确的官方响应结构。
import sys  # 引用项目内核。
import unittest  # 执行边界测试。
from pathlib import Path  # 不依赖当前目录。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 仅引用新代码。
from hgnc import HgncMap  # 真正映射器。
from identity_sources import IdentityEvidence  # 真正证据解释器。

class EvidenceTests(unittest.TestCase):  # 不仅验证运行成功，还验证不误收。
    def setUp(self):  # 构造标准、区域和无HGNC基因。
        raw = b"hgnc_id\tsymbol\tprev_symbol\talias_symbol\tensembl_gene_id\tuniprot_ids\tstatus\tentrez_id\nHGNC:1\tA\t\tSHARED\tENSG1\tP1\tApproved\t1\nHGNC:2\tB\t\tA|SHARED\tENSG2\tP2\tApproved\t2\n"  # 标准名A与另一基因别名冲突。
        genes = b"#tax_id\tGeneID\tSymbol\tSymbol_from_nomenclature_authority\tSynonyms\tdbXrefs\ttype_of_gene\n9606\t1\tA\tA\tOLD\tHGNC:HGNC:1\tprotein-coding\n9606\t2\tB\tB\tSHARED\tHGNC:HGNC:2\tprotein-coding\n9606\t3\tREGION\t-\t-\t-\tbiological-region\n9606\t4\tRNAONLY\t-\t-\t-\tncRNA\n"  # 类型不同必须区别。
        history = b"#tax_id\tGeneID\tDiscontinued_GeneID\tDiscontinued_Symbol\tDiscontinue_Date\n9606\t1\t10\tANCIENT\t20200101\n9606\t-\t11\tREMOVED\t20200101\n"  # 有替代与无替代不同。
        response = json.dumps({"ENSG99":{"id":"ENSG99", "species":"homo_sapiens", "object_type":"Gene", "biotype":"lncRNA"}})  # 查实但无HGNC。
        queries = json.dumps({"queries":[{"url":"https://rest.ensembl.org/lookup/id", "status":"ok", "response_text":response, "response_sha256":hashlib.sha256(response.encode()).hexdigest()}]}).encode()  # 固定成功原文。
        self.mapper = HgncMap(raw, supplement=IdentityEvidence(gzip.compress(genes), history, queries))  # 使用生产路径。
    def test_priority_and_conflict(self):  # 已批准标准名优先但不能忽略稳定编号反证。
        self.assertEqual(self.mapper.resolve("A")["target_id"], "HGNC:1")  # 别名碰撞不再误阻断。
        self.assertEqual(self.mapper.resolve("A", "NCBIGene:2")["target_id"], "")  # 编号矛盾必须阻断。
    def test_history_and_missing(self):  # 历史替代仅在唯一且真实存在时采用。
        self.assertEqual(self.mapper.resolve("ANCIENT")["target_id"], "HGNC:1")  # 唯一旧名恢复。
        self.assertEqual(self.mapper.resolve("", "GeneID:10")["target_id"], "HGNC:1")  # 明确历史编号可恢复。
        self.assertNotEqual(self.mapper.resolve("REMOVED")["status"], "matched")  # 撤销无替代不能恢复。
    def test_object_types(self):  # 不把区域或无HGNC基因伪装成统一编号。
        self.assertEqual(self.mapper.resolve("LOC3")["status"], "non_gene_object")  # LOC必须查到真实记录并识别类型。
        self.assertEqual(self.mapper.resolve("RNAONLY")["status"], "identity_verified_no_hgnc")  # 非编码不是无效。
        self.assertEqual(self.mapper.resolve("LOC999")["status"], "unmapped")  # 不能仅剥前缀伪造。
    def test_ensembl_and_unknown(self):  # 官方现行Gene身份与无查询不同。
        self.assertEqual(self.mapper.resolve("ENSG99")["status"], "identity_verified_no_hgnc")  # 保留查实结果。
        self.assertNotEqual(self.mapper.resolve("ENSG100")["query_status"], "已查询")  # 无缓存不得冒充查询完成。
    def test_crossrefs_and_species(self):  # 官方编号链接一致才恢复，非人类不能混入。
        evidence = self.mapper.supplement  # 使用同一实例的固定结构。
        evidence.lookups["ENSG100"] = {"id":"ENSG100", "display_name":"A", "species":"homo_sapiens", "object_type":"Gene"}  # 当前人类身份。
        evidence.xrefs["ENSG100"] = [{"dbname":"EntrezGene", "primary_id":"1"}]  # 唯一NCBI跨库证据。
        self.assertEqual(self.mapper.resolve("A", "ENSG100")["target_id"], "HGNC:1")  # 名称与新编号同时查实。
        evidence.xrefs["ENSG100"].append({"dbname":"HGNC", "primary_id":"HGNC:2"})  # 构造官方来源冲突。
        self.assertNotEqual(self.mapper.resolve("A", "ENSG100")["status"], "matched")  # 不按任一来源强制通过。
        evidence.lookups["ENSG99"]["species"] = "mus_musculus"  # 构造物种错误。
        self.assertNotEqual(self.mapper.resolve("ENSG99")["status"], "identity_verified_no_hgnc")  # 非人类不能记为本研究已确认。
    def test_protein_split_retained(self):  # 蛋白拆分不能自动变成多个基因边。
        evidence = self.mapper.supplement  # 同一官方响应解释器。
        evidence.proteins["OLDP"] = {"inactiveReason":{"inactiveReasonType":"DEMERGED", "mergeDemergeTo":["P1", "P2"]}}  # 一个旧蛋白拆分。
        found = self.mapper.resolve("A", uniprot="OLDP")  # 名称正确也不代表蛋白证据唯一。
        self.assertNotEqual(found["status"], "matched")  # 不凭名称覆盖拆分。
        self.assertIn("DEMERGED", found["query_note"])  # 用户看到明确原因。
    def test_query_failure_distinct(self):  # 网络失败不得解释为数据库无记录。
        self.mapper.supplement.lookup_status["ENSG100"] = "query_failed"  # 模拟归档失败状态。
        found = self.mapper.resolve("ENSG100")  # 同一实际解释器。
        self.assertEqual(found["query_status"], "查询失败，需重试")  # 明确提示重试。
        self.assertNotEqual(found["status"], "matched")  # 不伪造身份。
    def test_legacy(self):  # 新证据不重写旧规则。
        self.mapper.rule = "HGNC.resolve.2"  # 指定历史版本。
        self.assertEqual(self.mapper.resolve("A")["status"], "ambiguous_or_conflicting")  # 保持旧处理。
        self.assertNotIn("evidence_snapshot", self.mapper.resolve("A"))  # 保持旧结果字段。

if __name__ == "__main__":  # 独立验收入口。
    unittest.main(verbosity=2)  # 如实报告失败。

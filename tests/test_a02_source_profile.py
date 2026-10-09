# 核验研究级五库方案、OMIM Excel及ClinPGx精确实体边界。
import io  # 在内存中生成Excel测试文件。
import json  # 构造官方API模拟响应。
from pathlib import Path  # 定位项目源码。
import sys  # 只导入当前新项目。
import tempfile  # 隔离未授权研究测试。
import unittest  # 使用标准测试框架。
from openpyxl import Workbook  # 生成不依赖用户文件的工作簿。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 不引用旧Kimi代码。
from contracts import ContractError  # 核验明确拒绝场景。
from disease import DATABASES, parse_source, organize, source_profile, run_disease, validate_disease  # 调用真实A02内核。
from pharmgkb_source import fetch_pharmgkb  # 调用真实精确实体采集器。
from workflow import Workflow  # 验证研究级方案不能扩散。

def meta(name="omim.xlsx"):  # 固定OMIM Excel元数据。
    return {"database": "OMIM", "format": "omim_xlsx", "query": "Rhinitis, Allergic", "retrieved_at": "2026-10-02", "version": "下载快照", "source_url": "https://www.omim.org/", "name": name, "encoding": "utf-8-sig"}  # 与网页上传字段一致。

def workbook_bytes(duplicate=False):  # 构造带第5行表头的最小工作簿。
    book = Workbook()  # 默认工作表模拟实际OMIM文件。
    for sheet in ([book.active, book.create_sheet("duplicate")] if duplicate else [book.active]):  # 重复表头用于拒绝测试。
        sheet.append(["Gene Map Search"])  # 标题不应被误当表头。
        sheet.append(["date"])  # 保留说明行。
        sheet.append([])  # 空行。
        sheet.append([])  # 空行。
        sheet.append(["Approved Symbol", "Entrez Gene ID", "Phenotype", "Phenotype MIM number"])  # 唯一必需表头。
        sheet.append(["IL13", "3596", "{Allergic rhinitis, susceptibility to}", "607154"])  # 直接表型记录。
        sheet.append(["OTHER", "1", "Other disease", "1"])  # 范围复核保留行。
    output = io.BytesIO()  # 不产生临时文件。
    book.save(output)  # 保存标准xlsx字节。
    return output.getvalue()  # 交给真实解析器。

class Response:  # 模拟urllib上下文响应。
    def __init__(self, payload, status=200):
        self.payload, self.status = json.dumps(payload).encode(), status  # 保留JSON字节和状态。
    def __enter__(self): return self  # 支持with语句。
    def __exit__(self, *args): return False  # 不吞掉异常。
    def read(self, limit): return self.payload  # 返回完整模拟响应。

class SourceProfileTests(unittest.TestCase):  # 每项只验证一个科学边界。
    def test_default_and_research_profiles_are_separate(self):  # 默认模板不能被本次例外污染。
        self.assertEqual(source_profile()["databases"], list(DATABASES))  # 默认仍含DisGeNET。
        self.assertEqual(source_profile("A02.source_profile.1")["databases"], ["GeneCards", "OMIM", "TTD", "PharmGKB", "OTP"])  # 本次替换明确。

    def test_research_profile_cannot_be_used_by_another_study(self):  # 例外只属于用户指定研究。
        with tempfile.TemporaryDirectory() as folder:  # 不触碰正式资料。
            flow = Workflow(Path(folder), {"A02": validate_disease})  # 使用真实归档接口。
            sid = flow.create({"formula": "test", "herbs": "test", "disease": "test", "disease_scope": "test", "operator": "test", "species": 9606})  # 建立其他研究。
            a00 = flow.load(sid)["current"]["A00"]  # 固定当前登记。
            flow.review(sid, a00, "approved", "test", "test")  # 满足A02上游门控。
            item = {"database": "GeneCards", "format": "names", "query": "test", "retrieved_at": "2026-10-03", "version": "test", "source_url": "test", "name": "test.txt", "encoding": "utf-8-sig", "data": b"GENE1\n"}  # 最小来源。
            with self.assertRaises(ContractError):
                run_disease(flow, sid, a00, "", [item], "test", profile_version="A02.source_profile.1")  # 其他研究不得采用本次例外。

    def test_xlsx_rows_and_zero_source_state(self):  # Excel不经过UTF-8解码，零结果不是缺库。
        rows = parse_source(meta(), workbook_bytes())  # 使用真实工作簿解析。
        self.assertEqual(len(rows), 2)  # 全部数据行保留。
        self.assertEqual(rows[0]["raw_symbol"], "IL13")  # 直接记录内容一致。
        zero = {"database": "PharmGKB", "format": "pharmgkb_api", "query": "Rhinitis, Allergic", "retrieved_at": "2026-10-03", "version": "test", "source_url": "https://api.clinpgx.org/v1/data/disease/", "name": "zero.json", "encoding": "utf-8-sig", "data": json.dumps({"api": "https://api.clinpgx.org/v1", "official_terms": ["Rhinitis, Allergic"], "exact_disease": None, "records": [], "requests": [], "status": "queried_zero_exact"}).encode()}  # 有来源、无精确实体。
        summary, tables, _ = organize([dict(meta(), data=workbook_bytes()), zero], [], ["GeneCards", "OMIM", "TTD", "PharmGKB", "OTP"], "A02.source_profile.1")  # 研究级方案整理。
        self.assertEqual(next(row for row in tables["source_summary"] if row["database"] == "PharmGKB")["availability"], "已查询但0条精确记录")  # 与未提供区分。
        self.assertEqual(summary["已有来源库数"], 2)  # Excel和零结果都算已提供来源。

    def test_xls_and_ambiguous_headers_are_rejected(self):  # 不猜旧Excel或多个表头。
        with self.assertRaises(ContractError):
            parse_source(meta("old.xls"), workbook_bytes())  # 旧扩展名明确拒绝。
        with self.assertRaises(ContractError):
            parse_source(meta(), workbook_bytes(True))  # 多处合法表头必须人工整理。

    def test_clinpgx_does_not_substitute_broad_rhinitis(self):  # 宽泛Rhinitis不能替代过敏性鼻炎。
        calls = []  # 记录实际查询网址。
        def opener(request, timeout=20):
            calls.append(request.full_url)  # 核对未自行添加宽泛词。
            return Response({"data": []})  # 两个官方词均无精确实体。
        item = fetch_pharmgkb(["Rhinitis, Allergic", "Allergic Rhinitis"], opener=opener, sleeper=lambda seconds: None)  # 不等待测试。
        snapshot = json.loads(item["data"])  # 核对可追溯零结果。
        self.assertEqual(snapshot["status"], "queried_zero_exact")  # 不是API失败。
        self.assertEqual(snapshot["records"], [])  # 不补造基因。
        self.assertTrue(all("Rhinitis%2C+Allergic" in calls[0] or "Allergic+Rhinitis" in url for url in calls))  # 只查询官方词。
        self.assertFalse(any("name=Rhinitis&" in url or url.endswith("name=Rhinitis") for url in calls))  # 未查询宽泛Rhinitis。

    def test_unique_exact_entity_uses_only_direct_gene_objects(self):  # 唯一精确实体才进入直接基因接口。
        replies = iter([{"data": [{"id": "PA1", "name": "Asthma"}]}, [{"connectedObject": {"objCls": "Gene", "id": "PA-G", "symbol": "GENE1", "name": "Gene 1"}, "connectionTypes": ["DiseaseGene"]}, {"connectedObject": {"objCls": "Chemical", "id": "PA-C"}, "connectionTypes": ["DiseaseChemical"]}]])  # 混合对象用于过滤。
        item = fetch_pharmgkb(["Asthma"], opener=lambda request, timeout=20: Response(next(replies)), sleeper=lambda seconds: None)  # 执行两次固定请求。
        snapshot = json.loads(item["data"])  # 检查保存的直接记录。
        self.assertEqual([row["symbol"] for row in snapshot["records"]], ["GENE1"])  # 药物对象不被间接扩展成基因。

if __name__ == "__main__":  # 支持单文件执行。
    unittest.main(verbosity=2)  # 显示每项结果。

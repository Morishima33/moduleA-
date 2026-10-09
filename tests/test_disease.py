# A02测试只使用临时研究，真实来源仅只读对照。
import json  # 构造响应快照。
from pathlib import Path  # 定位新项目。
import sys  # 引用新代码。
import tempfile  # 隔离验收资料。
import unittest  # 使用标准测试工具。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 不引用Kimi代码。
from disease import scope_policy, scope_membership, organize, parse_source, legacy_sources, run_disease, validate_disease  # 调用实际实现。
from disease_io import fetch_otp, multipart  # 核验下载和上传。
from contracts import ContractError  # 核验明确报错。
from storage import verified_file  # 检查原始字节。
from workflow import Workflow  # 核验真实状态。
PROJECT = Path(__file__).resolve().parents[1]  # 从文件位置定位。

def source(db="GeneCards", data=b"Test1\nTest1\nTEST2\n", fmt="names"):  # 虚构资料不能用作科研结论。
    return {"database": db, "format": fmt, "query": "test", "retrieved_at": "2026-09-10", "version": "test", "source_url": "test fixture", "name": "fixture.txt", "encoding": "utf-8-sig", "data": data}  # 固定元信息。

def response(index, total=2):  # 模拟明确的直接关联分页。
    return {"data": {"disease": {"id": "TEST_1", "name": "test", "associatedTargets": {"count": total, "rows": [{"score": index * .5, "target": {"id": "ENSG" + str(index), "approvedSymbol": "TEST" + str(index)}}]}}}}  # 保留真实零分测试。

class DiseaseTests(unittest.TestCase):  # 正式门控和候选处理分别测试。
    def test_detailed_txt_strict_headers_and_encodings(self):  # 详细人工资料不猜字段或编码。
        header = "raw_symbol\tdisease_term\traw_id\ttarget_name\textra_note\nIL13\tRhinitis, Allergic\t3596\tInterleukin 13\t保留原文件\n"  # 包含必需、推荐和未知列。
        for encoding in ("utf-8-sig", "gbk"):  # 两种获准编码应产生相同候选。
            data = header.encode(encoding)  # 模拟用户实际下载文件。
            item = source("TTD", data, "detailed_txt")  # 复用来源元数据。
            item["encoding"] = encoding  # 明确选择编码，不自动探测。
            rows = parse_source(item, data)  # 调用生产解析器。
            self.assertEqual(rows[0]["raw_symbol"], "IL13")  # 必需字段正确进入候选。
            self.assertEqual(rows[0]["target_name"], "Interleukin 13")  # 推荐字段可追溯。
        bad = ((b"raw_symbol\traw_id\nIL13\t3596\n", "缺必需字段"), (b"raw_symbol\tdisease_term\traw_symbol\nIL13\tRhinitis\tIL13\n", "重复字段"), (b"IL13\tRhinitis\n", "没有合法表头"))  # 三类错误不得猜列位置。
        for data, label in bad:  # 每类都应明确拒绝。
            with self.subTest(label=label), self.assertRaises(ContractError):  # 错误不形成部分结果。
                parse_source(source("TTD", data, "detailed_txt"), data)  # 使用同一严格入口。
        with self.assertRaises(ValueError):  # 损坏字节也要给出可处理错误。
            parse_source(source("TTD", b"\xff\xfe\x00", "detailed_txt"), b"\xff\xfe\x00")  # 不回退为其他编码猜测。

    def test_direct_only_scope_policy(self):  # 首版亚型排除与待核验保持不同状态。
        self.assertTrue(scope_membership("direct"))  # 本病可进入集合。
        self.assertFalse(scope_membership("subtype"))  # 亚型不进入集合。
        self.assertFalse(scope_membership("outside"))  # 无关范围不进入集合。
        self.assertIsNone(scope_membership("pending"))  # 未决不当作排除。
        with self.assertRaises(ContractError):  # 保留接口但不提前开放亚型。
            scope_policy(True)  # 必须另行实施已批准的优化版本。

    def test_duplicates_missing_scores(self):  # 重复行保留，缺分数不补0。
        s, t, a = organize([source()], [])  # 只整理一库。
        self.assertEqual(s["候选记录数"], 3)  # 不删除重复原始证据。
        self.assertEqual(len(t["raw_union"]), 2)  # 名称按相同文字归组。
        self.assertTrue(all(r["raw_score"] == "" for r in t["candidate_records"]))  # 缺失有明确表示。
        self.assertEqual(sum(r["availability"] == "尚未提供资料" for r in t["source_summary"]), 4)  # 缺库不等于无靶点。

    def test_omim_scope_and_missing(self):  # 缺符号及其他疾病表型都留存。
        data = "Approved Symbol\tPhenotype\tPhenotype MIM number\nTEST1\tCOPD\t1\nTEST1\tother\t2\n\tunknown\t3\n".encode()  # 构造三种表型。
        rows = parse_source(source("OMIM", data, "omim"), data)  # 不自动筛表型。
        self.assertEqual(len(rows), 3)  # 空符号行未丢失。
        self.assertEqual(len({r["scope_id"] for r in rows}), 3)  # 各条目独立复核。
        self.assertTrue(all(r["scope"] == "pending" for r in rows))  # 不静默纳入。

    def test_empty_phenotype_is_not_query(self):  # 有表型列但空白不能填入检索词。
        data = "Approved Symbol\tPhenotype\tPhenotype MIM number\nTEST1\t\t\n".encode()  # 模拟有基因无表型的OMIM行。
        rows = parse_source(source("OMIM", data, "omim"), data)  # 调用真实解析。
        self.assertEqual(rows[0]["disease_term"], "")  # 原表空缺不能变为COPD。
        self.assertEqual(rows[0]["scope"], "pending")  # 不自动纳入或排除。

    def test_union_is_only_reference(self):  # 未标准化名称不当正式疾病集合。
        s, t, a = organize([source(), source("OTP", b"TEST2\nTEST3\n")], [])  # 两库有一个共同名称。
        self.assertEqual(len(t["raw_union"]), 3)  # 并集保留全部名称。
        self.assertEqual([r["raw_symbol"] for r in t["raw_reference"]], ["TEST2"])  # 参考交集正确。
        self.assertTrue(s["handoff_blocked"])  # 不开放下游。

    def test_complete_api_and_zero_score(self):  # 零分和完整分页都保留。
        item = fetch_otp("TEST_1", lambda did, index: response(index))  # 注入模拟网络。
        rows = parse_source(item, item["data"])  # 上传和在线使用相同解析器。
        self.assertEqual(len(rows), 2)  # 两页均完整。
        self.assertEqual(rows[0]["raw_score"], 0.0)  # 零分区别于缺失。

    def test_api_errors_and_duplicate_pages(self):  # 失败不能变成成功空集。
        with self.assertRaises(ContractError):  # 数量变化明确拒绝。
            fetch_otp("TEST_1", lambda did, index: response(index, 2 if index == 0 else 3))  # 模拟分页期间更新。
        with self.assertRaises(ContractError):  # 补取后仍缺唯一ID不能当完整结果。
            fetch_otp("TEST_1", lambda did, index: response(0))  # 模拟持续重复页。
        with self.assertRaises(ContractError):  # 接口错误单独处理。
            fetch_otp("TEST_1", lambda did, index: {"errors": ["failed"]})  # 不伪造空候选。

    def test_api_overlap_can_be_completed_without_losing_raw_pages(self):  # 同分补取必须有完整ID集合和原响应。
        replies = iter([response(0), response(0), response(1), response(1)])  # 首轮重复，第二轮补齐。
        item = fetch_otp("TEST_1", lambda did, index: next(replies))  # 运行真实有界补取。
        self.assertEqual(len(json.loads(item["data"])["pages"]), 4)  # 重复原响应不丢弃。
        rows = parse_source(item, item["data"])  # 完整后才可规范化。
        self.assertEqual(len(rows), 2)  # 按稳定ID合并重复请求。
        self.assertIn(";", rows[0]["source_row"])  # 原始响应定位均保留。

    def test_upload_bytes_and_duplicate_fields(self):  # 文件名不作为写入路径。
        body = b'--B\r\nContent-Disposition: form-data; name="token"\r\n\r\nt\r\n--B\r\nContent-Disposition: form-data; name="upload"; filename="../../x.txt"\r\n\r\nTEST1\n\r\n--B--\r\n'  # 构造标准表单。
        fields, files = multipart("multipart/form-data; boundary=B", body)  # 实际解析。
        self.assertEqual(files["upload"]["data"], b"TEST1\n")  # 原字节不变。
        bad = body.replace(b"--B--", b'--B\r\nContent-Disposition: form-data; name="token"\r\n\r\nu\r\n--B--')  # 构造重复令牌。
        with self.assertRaises(ContractError):  # 不任取第一个字段。
            multipart("multipart/form-data; boundary=B", bad)  # 拒绝歧义。

    def test_archive_scope_gate_and_restart(self):  # 保存范围意见不能变成正式批准。
        with tempfile.TemporaryDirectory() as folder:  # 不操作正式研究。
            flow = Workflow(Path(folder), {"A02": validate_disease})  # 使用实际校验。
            sid = flow.create({"formula": "test", "herbs": "test", "disease": "test", "disease_scope": "test", "operator": "test", "species": 9606})  # 独立登记。
            a00 = flow.load(sid)["current"]["A00"]  # 当前输入版本。
            flow.review(sid, a00, "approved", "test", "test")  # 模拟上游通过。
            result = run_disease(flow, sid, a00, "", [source()], "导入测试")  # 实际归档。
            with self.assertRaises(ContractError):  # 服务端也阻止绕过网页。
                flow.review(sid, result["run_id"], "approved", "test", "test")  # 未定规则不能批准。
            flow.review(sid, result["run_id"], "pending", "test", "test")  # 可保存暂存意见。
            change = {"scope_id": result["tables"]["scope_groups"][0]["scope_id"], "scope": "direct", "reviewer": "test", "note": "test"}  # 对实际条目复核。
            updated = run_disease(flow, sid, a00, result["run_id"], [], "范围测试", change)  # 形成新版本。
            self.assertEqual(updated["sources"][0], result["sources"][0])  # 原文件只保留明确引用。
            self.assertTrue(all(r["scope"] == "direct" for r in updated["tables"]["candidate_records"]))  # 范围正确作用于对应行。
            reopened = Workflow(Path(folder), {"A02": validate_disease})  # 模拟重开。
            self.assertFalse(reopened.approved(reopened.load(sid), updated["run_id"]))  # 仍不解锁A03。
            with self.assertRaises(ContractError):  # 旧页面冲突应拒绝。
                run_disease(flow, sid, a00, result["run_id"], [source()], "过期")  # 不覆盖新版本。
            replaced = run_disease(flow, sid, a00, updated["run_id"], [source(data=b"NEW1\n")], "替换")  # 同库来源明确替换。
            self.assertEqual(replaced["tables"]["candidate_records"][0]["scope"], "pending")  # 不继承旧来源的范围批准。
            self.assertEqual(verified_file(flow.location(sid), result["sources"][0]).read_bytes(), source()["data"])  # 原始来源仍保留。

    def test_batch_atomic_and_complete(self):  # 批量不能漏条目或部分发布。
        with tempfile.TemporaryDirectory() as folder:  # 独立临时研究。
            flow = Workflow(Path(folder), {"A02": validate_disease})  # 使用真实门控。
            sid = flow.create({"formula": "test", "herbs": "test", "disease": "test", "disease_scope": "test", "operator": "test", "species": 9606})  # 虚构登记。
            a00 = flow.load(sid)["current"]["A00"]  # 固定上游。
            flow.review(sid, a00, "approved", "test", "test")  # 测试批准。
            result = run_disease(flow, sid, a00, "", [source(), source("TTD")], "测试")  # 创建两个范围组。
            batch = [{"scope_id": row["scope_id"], "scope": "outside", "reviewer": "test", "note": "test"} for row in result["tables"]["scope_groups"]]  # 全量批次。
            for bad in (batch[:1], batch + batch[:1], [batch[0], dict(batch[1], scope="invalid")]):  # 覆盖遗漏、重复和非法末条。
                with self.assertRaises(ContractError):  # 全批拒绝。
                    run_disease(flow, sid, a00, result["run_id"], [], "错误批次", bad)  # 不发布部分决定。
                self.assertEqual(flow.load(sid)["current"]["A02"], result["run_id"])  # 当前版本不变。
            updated = run_disease(flow, sid, a00, result["run_id"], [], "批量", batch)  # 完整批次一次成功。
            self.assertEqual(len(updated["tables"]["scope_history"]), 2)  # 每条留痕。
            self.assertTrue(updated["summary"]["handoff_blocked"])  # 不能绕过正式筛选。
            self.assertEqual(updated["sources"][:-1], result["sources"][:-1])  # 原始来源保持不变。

    def test_legacy_exact_sets_and_score_records(self):  # 数量一致不代表名单一致，必须逐项比较。
        s, t, a = organize(legacy_sources(PROJECT), [])  # 读取固定的候选来源。
        otp = json.loads((PROJECT / "references/disease_copd_otp_20260829.json").read_text(encoding="utf-8-sig"))  # 旧OTP实际记录。
        omim = json.loads((PROJECT / "references/disease_copd_omim_result_20260831.json").read_text(encoding="utf-8-sig"))  # 旧参考交集基线。
        new = {r["raw_symbol"] for r in t["raw_reference"]}  # 新原始名称参考。
        old = set(omim["intersections"]["otp_n_three_union"])  # 旧大写化参考。
        self.assertEqual(len(old - new), 11)  # 保留实际发现的大小写差异。
        self.assertEqual({x.casefold() for x in old}, {x.casefold() for x in new})  # 仅用于差异诊断，不作正式映射。
        original = sorted((r["symbol"], r["ensg"], r["score"]) for r in otp["records"])  # 包含原重复次数。
        current = sorted((r["raw_symbol"], r["raw_id"], r["raw_score"]) for r in t["candidate_records"] if r["database"] == "OTP")  # 核对全部分数字段。
        self.assertEqual(original, current)  # 原始分数不能丢失或改写。

    def test_legacy_counts(self):  # 只读实际快照核对Kimi数量。
        s, t, a = organize(legacy_sources(PROJECT), [])  # 无评分过滤。
        self.assertEqual({r["database"]: r["distinct_raw_symbols"] for r in t["source_summary"]}, {"GeneCards":15876,"OMIM":384,"TTD":86,"DisGeNET":108,"OTP":6122})  # 与旧名单对应。
        self.assertEqual(s["候选记录数"], 23379)  # 原始记录完整。
        self.assertEqual(s["缺原始名称记录数"], 110)  # 缺基因行明确列出。
        self.assertEqual(s["原始四库并集交OTP对照名称数"], 5256)  # 不把此数作为正式D。

if __name__ == "__main__":  # 直接执行测试入口。
    unittest.main(verbosity=2)  # 如实显示通过与失败。

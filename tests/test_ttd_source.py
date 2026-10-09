# TTD解析与归档检查使用合成资料及已下载的新官方快照。
import sys  # 加载本项目模块。
import json  # 读取明确的下载清单。
import hashlib  # 为测试原文建立正确指纹。
import unittest  # 标准库测试框架。
from pathlib import Path  # 定位新项目参考资料。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 不引用旧项目。
from ttd_source import BASE, FILES, make_source, parse_snapshot  # 测试实际解析入口。
from disease import parse_source  # 验证接入A02后的字段。
from contracts import ContractError  # 异常必须明确拒绝。

def fixture():  # 小型原文可以手工核算。
    raw = {"targets": "TTD - Therapeutic Targets Database\nVersion test\nT00001\tGENENAME\tG1\nT00001\tUNIPROID\tG1_HUMAN\nT00002\tGENENAME\tG2;G3\n", "diseases": "TTD - Therapeutic Targets Database\nVersion test\nT00001\tINDICATI\tPhase 2\tChronic obstructive pulmonary disease\t[ICD-11: CA22]\nT00002\tINDICATI\tTerminated\tChronic obstructive pulmonary disease\t[ICD-11: CA22]\nT00003\tINDICATI\tPhase 1\tChronic obstructive pulmonary disease\t[ICD-11: CA22]\nT00001\tINDICATI\tApproved\tAsthma\t[ICD-11: CA23]\n"}  # 多值、缺失及范围外都包含。
    return {key: {"url": BASE + FILES[key], "text": value, "bytes": len(value.encode()), "sha256": hashlib.sha256(value.encode()).hexdigest(), "retrieved_at": "2026-09-13T00:00:00+00:00"} for key, value in raw.items()}  # 测试快照格式与真实一致。

class TTDTests(unittest.TestCase):  # 不要求用户审核测试研究。
    def test_scope_and_missing_identity(self):  # 临床状态保留，不自设筛除条件。
        source = make_source(fixture(), "Chronic obstructive pulmonary disease")  # 只检索明确病名。
        rows = parse_source(source, source["data"])  # 经过A02统一整理。
        self.assertEqual(len(rows), 3)  # 哮喘不混入本病。
        self.assertEqual([r["raw_symbol"] for r in rows], ["G1", "G2;G3", ""])  # 不拆分歧义、不丢失缺字段行。
        self.assertEqual(rows[1]["clinical_status"], "Terminated")  # 停止开发也原样保留候选。
        self.assertTrue(all(r["raw_score"] == "" and r["scope"] == "pending" for r in rows))  # 不补0或自动批准。

    def test_tamper(self):  # 来源原文被修改必须停止。
        files = fixture()  # 独立测试数据。
        files["targets"]["text"] += "changed"  # 不更新指纹模拟损坏。
        with self.assertRaises(ContractError):  # 不能发布不一致快照。
            make_source(files, "Chronic obstructive pulmonary disease")  # 实际入口拒绝。

    def test_empty_query_and_no_match(self):  # 空检索与没有命中区分。
        with self.assertRaises(ContractError):  # 空字符串不能扫全库。
            make_source(fixture(), "")  # 缺病名。
        source = make_source(fixture(), "No such synthetic disease")  # 合法检索无匹配。
        self.assertEqual(parse_source(source, source["data"]), [])  # 不扩大范围凑数。

    def test_real_download(self):  # 对明确下载快照固定验收，不以此约束未来版本。
        folder = Path(__file__).resolve().parents[1] / "references"  # 不读取Kimi来源。
        manifest = json.loads((folder / "ttd_download_20260913.json").read_text(encoding="utf-8"))  # 真实源指纹。
        files = {("diseases" if "disease" in row["path"] else "targets"): dict(row, text=(folder / row["path"]).read_bytes().decode("utf-8")) for row in manifest["files"]}  # 原字节保持。
        source = make_source(files, "Chronic obstructive pulmonary disease")  # 可重复提取。
        rows = parse_source(source, source["data"])  # 当前候选结果。
        self.assertEqual(len(rows), 84)  # 仅固定文件的测试值。
        self.assertEqual(len({r["raw_id"] for r in rows}), 84)  # 记录与不同TTD对象分开核对。
        self.assertEqual(sum(not r["raw_symbol"] for r in rows), 12)  # 缺基因记录不能消失。
        self.assertIn("2024.01.10", source["version"])  # 不把网站2026介绍当文件版本。

    def test_http_new_download_entry(self):  # 真实HTTP表单验证新入口，不向正式研究写测试资料。
        import tempfile  # 隔离研究包。
        import threading  # 临时本机服务。
        import re  # 读取真实表单令牌。
        from urllib.request import urlopen  # 发出实际HTTP请求。
        from urllib.parse import urlencode  # 编码表单字段。
        from unittest.mock import patch  # 仅替换外部下载，保持A02归档逻辑真实。
        from web import create_server  # 使用真实网页处理器。
        from workflow import Workflow  # 创建明确测试登记。
        with tempfile.TemporaryDirectory(prefix="moduleA_ttd_http_") as tmp:  # 测试不落正式目录。
            flow = Workflow(Path(tmp))  # 临时工作区。
            sid = flow.create({"formula": "测试方", "herbs": "测试药", "disease": "copd", "disease_scope": "仅测试", "operator": "自动测试", "species": 9606}, kind="contract_test")  # 不冒充真实数据。
            a00 = flow.load(sid)["current"]["A00"]  # 明确测试版本。
            flow.review(sid, a00, "approved", "测试", "测试登记")  # 只审批测试研究。
            server = create_server(Path(tmp), 0)  # 使用独立端口。
            worker = threading.Thread(target=server.serve_forever, daemon=True)  # 响应表单请求。
            worker.start()  # 启动临时服务。
            try:  # 无论结果如何均释放资源。
                base = "http://127.0.0.1:" + str(server.server_port)  # 本机地址。
                with urlopen(base + "/study?study=" + sid) as response:  # 获取真实页面。
                    html = response.read().decode("utf-8")  # 检查中文按钮。
                self.assertIn("重新获取TTD并整理候选", html)  # 运行方式真实可见。
                token = re.search(r'name="token" value="([^"]+)"', html).group(1)  # 服务器生成的令牌。
                fields = {"token": token, "study": sid, "expected_a00": a00, "expected_a02": "", "confirmed": "yes", "query": "Chronic obstructive pulmonary disease", "reason": "模拟官方独立获取"}  # 显式提交本研究。
                with patch("web.fetch_ttd", side_effect=lambda query: make_source(fixture(), query)):  # 防止测试重复下载远程全库。
                    with urlopen(base + "/disease-ttd", data=urlencode(fields).encode()) as response:  # 经过真实路由与归档。
                        self.assertEqual(response.status, 200)  # 跳转后可查看。
                current = flow.load(sid)  # 检查磁盘结果。
                result = flow.result(current, current["current"]["A02"])  # 包含来源指纹核验。
                self.assertEqual(result["summary"]["候选记录数"], 3)  # 解析正确。
                self.assertTrue(result["summary"]["handoff_blocked"])  # 网页入口不绕过科学复核。
            finally:  # 清理只属于测试的服务。
                server.shutdown()  # 结束请求循环。
                server.server_close()  # 释放端口。
                worker.join(timeout=3)  # 回收线程。

if __name__ == "__main__":  # 直接运行此文件。
    unittest.main()  # 输出真实测试结果。

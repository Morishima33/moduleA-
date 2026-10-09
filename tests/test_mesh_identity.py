# MeSH疾病身份模块验收；使用固定响应验证算法，不依赖测试时外网状态。
from pathlib import Path  # 定位项目源码目录。
import sys  # 将新项目源码加入导入路径。
import unittest  # 使用标准测试框架。
from unittest.mock import patch  # 替换网络读取为明确的官方响应形状。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # 不引用旧Kimi代码。
from contracts import ContractError, check_intake  # 核对登记契约和失败边界。
from mesh_identity import verify_mesh_identity  # 测试生产核对函数。
from web import fields  # 检查网页必须显示三个疾病身份字段。
from disease_ui import controls  # 检查A02使用已核对标准词而非重新猜测。

def response(path, parameters=None, timeout=30):  # 按请求路径返回固定的NLM形状。
    if path == "/years":  # 官方年份列表含别名和数字版本。
        value = ["current", "2026", "2025", "2024"]  # 最新明确年份应选2026。
    elif path == "/descriptor":  # 精确标准词查询结果。
        value = [{"resource": "http://id.nlm.nih.gov/mesh/2026/D029424", "label": "Pulmonary Disease, Chronic Obstructive"}]  # 标准词和编号一致。
    else:  # 详情包含首选词和Entry Term。
        value = {"descriptor": "http://id.nlm.nih.gov/mesh/D029424", "terms": [{"resource": "http://id.nlm.nih.gov/mesh/T024361", "label": "Pulmonary Disease, Chronic Obstructive", "preferred": True}, {"resource": "http://id.nlm.nih.gov/mesh/T024362", "label": "COPD", "preferred": False}]}  # Entry Term仅作追溯。
    return "https://id.nlm.nih.gov" + path, value, path.strip("/").replace("/", "_") + "_hash"  # 返回网址、内容和稳定测试指纹。

class MeshIdentityTests(unittest.TestCase):  # 集中检查准确性、阻断和网页呈现。
    @patch("mesh_identity._request_json", side_effect=response)  # 不让单元测试受网络波动影响。
    def test_exact_term_and_id_are_archived(self, unused_request):  # 完全对应时形成可复核身份。
        identity = verify_mesh_identity("Pulmonary Disease, Chronic Obstructive", "d029424")  # 小写编号应规范成大写。
        self.assertEqual(identity["mesh_id"], "D029424")  # 保存正式描述词编号。
        self.assertEqual(identity["mesh_year"], "2026")  # 固定数字生产年份。
        self.assertEqual(identity["preferred_term"], "Pulmonary Disease, Chronic Obstructive")  # 标准词不被替换。
        self.assertIn("COPD", identity["entry_terms"])  # 官方同义词留作追溯。
        intake = {"formula": "测试方", "herbs": "测试药", "disease": "慢性阻塞性肺疾病", "mesh_term": identity["preferred_term"], "mesh_id": identity["mesh_id"], "mesh_verification": identity, "disease_scope": "仅本病，不纳入亚型", "operator": "测试", "species": 9606}  # 建立完整登记。
        check_intake(intake)  # 完整证据应通过现行登记契约。

    @patch("mesh_identity._request_json", side_effect=response)  # 使用相同固定来源制造编号错配。
    def test_mismatched_id_is_rejected(self, unused_request):  # 不能自动选择相近或其他疾病。
        with self.assertRaisesRegex(ContractError, "未在NLM官方记录中精确对应"):  # 错误必须直接说明原因。
            verify_mesh_identity("Pulmonary Disease, Chronic Obstructive", "D012220")  # 词与编号不对应。

    def test_partial_identity_is_rejected(self):  # 只填词和编号不能绕过官方核对。
        intake = {"formula": "测试方", "herbs": "测试药", "disease": "测试病", "mesh_term": "Test Disease", "mesh_id": "D012220", "disease_scope": "仅本病，不纳入亚型", "operator": "测试", "species": 9606}  # 刻意缺少核对证据。
        with self.assertRaisesRegex(ContractError, "必须同时保存"):  # 阻止半套身份进入版本链。
            check_intake(intake)  # 失败前不创建研究。

    def test_web_form_requires_mesh_fields(self):  # 用户可在同一登记页完成输入。
        html = fields()  # 生成生产登记字段。
        self.assertIn('name="mesh_term"', html)  # 标准词必填。
        self.assertIn('name="mesh_id"', html)  # 描述词编号必填。
        self.assertIn("保存时自动核对", html)  # 页面提前解释会连接NLM官方服务。
        self.assertIn("仅本病，不纳入亚型", html)  # 默认使用已批准首版范围。

    def test_a02_uses_verified_term_and_hides_legacy_import(self):  # 正式研究入口不能误用COPD历史资料。
        mesh = {"status":"verified","mesh_id":"D029424","preferred_term":"Pulmonary Disease, Chronic Obstructive","mesh_year":"2026","checked_at":"2026-09-28T00:00:00+00:00"}  # 页面只需显示已归档身份摘要。
        view = {"manifest":{"study_id":"study_" + "a" * 32,"current":{"A00":"run_" + "b" * 32},"trashed":False},"modules":[{"module_id":"A00","result":{"summary":{"disease":"慢性阻塞性肺疾病","mesh_verification":mesh}}},{"module_id":"A02","available":True,"result":None}]}  # 构造尚未上传资料的新正式研究视图。
        html = controls(None,view,"token")  # 生成生产A02入口。
        self.assertIn("正式研究疾病身份",html)  # 首屏显示已核对MeSH身份。
        self.assertIn('value="Pulmonary Disease, Chronic Obstructive"',html)  # 三库及TTD表单预填官方标准词。
        self.assertNotIn("导入Kimi三库资料",html)  # 正式病例不提供旧COPD测试资料按钮。

if __name__ == "__main__":  # 支持单独运行本文件。
    unittest.main(verbosity=2)  # 显示每项验收状态。

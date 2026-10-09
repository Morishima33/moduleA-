# 补库下游授权及候选角色使用隔离资料验收。
import sys  # 引用正式新项目。
import tempfile  # 不创建真实研究。
import unittest  # 检查版本及门控。
from pathlib import Path  # 限定隔离路径。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))  # 不引用旧Kimi代码。
from intersection_flow import build, select_build  # 真实候选计算入口。
from ppi_identity import authorization, RHINITIS_SCOPE  # 真实版本绑定授权入口。
from storage import write_json, file_record  # 使用真实文件指纹。
from contracts import ContractError  # 明确拒绝未授权对象。

def selection_inputs():  # 七个成分排名1至7，无截断并列。
    payload = {'namespace': 'HGNC', 'mapping_snapshot': 'a' * 64, 'analysis_purpose': 'workflow_test', 'herbs': ['A', 'C'], 'components': [{'compound_id': str(i), 'name': '合成成分' + str(i)} for i in range(7)], 'memberships': [{'compound_id': str(i), 'herb': 'A' if i < 6 else 'C'} for i in range(7)], 'compound_targets': [], 'disease_targets': []}  # 显式合成数据不作为科研结果。
    for n in range(1, 8):  # 七个可手算目标。
        payload['disease_targets'].append({'target_id': 'HGNC:' + str(n), 'symbol': 'G' + str(n), 'species': 9606, 'source_ref': '合成疾病:1'})  # 唯一身份。
    for i in range(7):  # 各成分命中7、6、5、4、3、2、1个目标。
        payload['compound_targets'].extend(dict(row, compound_id=str(i)) for row in payload['disease_targets'][:7 - i])  # 第六位需要明确人工理由。
    return {'payload': payload, 'selected': list('0123456'), 'reviewer': '测试', 'reason': '明确人工补充及药味代表', 'identity_confirmed': True, 'selection_policy': 'explicit_manual_supplements', 'manual_supplements': {'5': '用户明确保留第六位作为补充'}}  # 不靠数量自动判断许可。

class RefillDownstreamTests(unittest.TestCase):  # 历史兼容与新门控同时检查。
    def test_manual_supplement_is_not_a_tie(self):  # 不能把第六位伪装为截断并列。
        summary, tables = select_build(selection_inputs())  # 同生产代码。
        rows = {r['compound_id']: r for r in tables['selected']}  # 精确身份定位。
        self.assertEqual(rows['5']['main_rank'], 6)  # 原排序不变。
        self.assertEqual(rows['5']['selection_role'], '人工补充研究候选')  # 角色如实保存。
        self.assertEqual(rows['6']['selection_role'], '药味代表性补充纳入')  # 药味角色不丢失。
        self.assertEqual(summary['人工补充纳入数'], 1)  # 不把其他正常对象计为补充。
    def test_unspecified_extra_candidate_is_rejected(self):  # 旧接口及缺理由不能借新策略扩张。
        for policy, manual in (('boundary_ties_and_herb_representatives', {}), ('explicit_manual_supplements', {}), ('explicit_manual_supplements', {'5': ''}), ('explicit_manual_supplements', {'missing': '不属于名单'})):  # 四种非法情形。
            with self.subTest(policy=policy, manual=manual), self.assertRaises(ContractError):  # 一律写入前拒绝。
                select_build(dict(selection_inputs(), selection_policy=policy, manual_supplements=manual))  # 不自行补理由。
    def test_single_fifth_is_not_labelled_as_a_tie(self):  # 新角色版本明确区别单独第五与并列。
        inputs = dict(selection_inputs(), selection_policy='explicit_manual_supplements_v2')  # 新版角色规则。
        summary, tables = select_build(inputs)  # 数值仍使用同一排序。
        row = next(r for r in tables['selected'] if r['compound_id'] == '4')  # 唯一第五位。
        self.assertEqual(row['main_rank'], 5)  # 不改变名次。
        self.assertEqual(row['selection_role'], '主排序前五候选')  # 不谎称并列。
    def test_authorization_binds_a03_and_fingerprint(self):  # 文件存在不能代替身份和指纹一致。
        with tempfile.TemporaryDirectory() as tmp:  # 所有写入仅属于临时研究。
            root = Path(tmp)  # 独立测试根目录。
            sid, a03 = 'study_fixture', 'run_fixture'  # 非真实研究。
            home = root / 'studies' / sid  # 与正式布局一致。
            result_path = home / 'runs/A03' / a03 / 'result.json'  # 指定唯一父版本。
            result_path.parent.mkdir(parents=True)  # 创建测试目录。
            write_json(result_path, {'run_id': a03, 'module_id': 'A03', 'tables': {'intersection_targets': [{'target_id': 'HGNC:1'}]}})  # 可手算交集。
            scope = {'study_id': sid, 'a03_run': a03, 'decision': '测试显式决定', 'check_ids': ['HGNC:1'], 'omit_ids': ['HGNC:1']}  # 只覆盖本版一项。
            path = home / 'governance' / ('A04_identity_authorization_' + a03 + '.json')  # 精确绑定版本名。
            path.parent.mkdir()  # 测试治理目录。
            write_json(path, {'schema_version': 'A04.identity.authorization.1', 'status': 'user_approved', 'scope': scope, 'a03_result': file_record(home, result_path, 'result')})  # 固定真实文件指纹。
            self.assertEqual(authorization(sid, a03, root), scope)  # 合法授权读取。
            self.assertIsNone(authorization(sid, 'run_other', root))  # 不跨上游版本沿用。
            result_path.write_text('{}', encoding='utf-8')  # 模拟上游文件被篡改。
            with self.assertRaises(ContractError):  # 指纹变化必须阻断。
                authorization(sid, a03, root)  # 不采信同名文件。
    def test_historical_authorization_unchanged(self):  # 历史结果仍可独立复算。
        self.assertEqual(authorization(RHINITIS_SCOPE['study_id'], RHINITIS_SCOPE['a03_run']), RHINITIS_SCOPE)  # 不迁移旧决定。

if __name__ == '__main__':  # 可独立运行本轮专项检查。
    unittest.main()  # 汇报真实结果。

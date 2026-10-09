# 结果复用安全检查：输入变化时必须停止，不能把旧评分接入新版。
import copy  # 构造独立异常质控数据。
from pathlib import Path  # 明确本研究文件。
import unittest  # 使用标准测试。
from unittest.mock import patch  # 只模拟输入异常，不运行Vina。
from storage import read_json  # 读取真实归档。
from contracts import ContractError  # 识别受控阻断。
from docking_result_reuse import create_candidate  # 通用复用接口。
ROOT = Path(__file__).resolve().parents[1]  # 正式项目。
HOME = ROOT / 'studies/study_26fce8e06ccc44a1a4fa7cefc8f789ba'  # 当前验收案例。
CHECK = HOME / 'runs/A06_PREP/check_e50a3684f2574ecba5a4abc0bb7e9cfd/structure_input_check.json'  # 原核验。
QC = HOME / 'runs/A06_PREP/redock_dfd5b5efedff4e09805b78b95f2de037/redocking_result.json'  # 当前参考质控。
class ReuseSafetyTests(unittest.TestCase):  # 只检查影响科学复用的异常。
    def assert_rejected(self, change, message):  # 异常必须在写出候选前停止。
        data = copy.deepcopy(read_json(QC))  # 不更改归档原件。
        change(data)  # 模拟真实输入变化。
        def reader(path):  # 其他文件继续完整校验。
            return data if Path(path).resolve() == QC.resolve() else read_json(path)  # 只替换本轮质控对象。
        with patch('docking_result_reuse.read_json', side_effect=reader):  # 不影响原文件字节。
            with self.assertRaisesRegex(ContractError, message):  # 必须明确报错。
                create_candidate(ROOT, CHECK, QC, '本研究实际来源', '流程测试')  # 不允许新结果发布。
    def test_cross_study_rejected(self):  # 防止其他研究同名靶点混入。
        self.assert_rejected(lambda data: data.update(study_id='study_other'), '不同研究')  # 身份必须一致。
    def test_changed_box_rejected(self):  # 同受体但搜索空间不同不可复用。
        self.assert_rejected(lambda data: data['results'][2]['center'].__setitem__(0, 999), '空间改变')  # 不以旧分值补新盒。
    def test_changed_receptor_bytes_rejected(self):  # 同PDB但准备文件不同不可复用。
        self.assert_rejected(lambda data: data['results'][2]['inputs']['receptor'].update(sha256='0' * 64), '字节改变')  # 输入指纹必须匹配。
    def test_changed_vina_parameters_rejected(self):  # 算法参数变化不得复用。
        self.assert_rejected(lambda data: data['vina_parameters'].update(seed=2), '原参数')  # 不只检查靶点名字。
if __name__ == '__main__':  # 独立运行验收。
    unittest.main()  # 交给标准框架。

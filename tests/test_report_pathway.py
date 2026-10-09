import pathlib,sys,unittest,copy # 验证批准与科学身份边界。
from unittest.mock import patch # 负例仅影响内存，不修改真实数据。
root=pathlib.Path('D:/codex-重大专项/moduleA') # 明确真实案例所在项目。
sys.path.insert(0,str(root/'src')) # 使用新增接口。
from docking_automation import workflow_instance # 科学结果按正式合同读取。
from report_pathway import report_pathway_record # 用户选择与版本校验入口。
from storage import read_json # 只读已批准选择。
from contracts import ContractError # 非法数据必须拒绝。
class PathwayTests(unittest.TestCase): # 重点检查错误图源不能被发布。
    @classmethod # 共用一次只读运行加载。
    def setUpClass(cls): # 不改真实审批状态。
        cls.flow=workflow_instance(root); cls.manifest=cls.flow.load('study_26fce8e06ccc44a1a4fa7cefc8f789ba') # 当前真实输入。
        cls.index=read_json(cls.flow.location(cls.manifest['study_id'])/'governance'/'A05_pathway_index.json') # 用户批准的选择记录。
    def test_approved_current_pathway(self): # 正确选择必须匹配真实37个命中。
        self.assertEqual(report_pathway_record(self.flow,self.manifest),self.index['metadata']) # 不靠文件名选择最新版。
    def test_unapproved_rejected(self): # 助手图件检查不允许冒充批准。
        with patch('report_pathway.read_json',return_value=dict(self.index,review_status='awaiting_user_review')): # 只构造内存负例。
            with self.assertRaises(ContractError): report_pathway_record(self.flow,self.manifest) # 必须阻断发布。
    def test_stale_a05_not_reused(self): # 上游新版本不可套用旧通路选择。
        changed=copy.deepcopy(self.manifest); changed['current']['A05']='different_a05_run' # 保留原真实索引。
        self.assertIsNone(report_pathway_record(self.flow,changed)) # 自动恢复没有人工选择的普通报告行为。
if __name__=='__main__': unittest.main(verbosity=2) # 输出三个关键检查结果。

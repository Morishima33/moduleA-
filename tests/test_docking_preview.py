# 准备预览不得跨研究、跨上游版本或使用被修改证据。
import sys  # 导入项目内核。
import tempfile  # 隔离虚构测试资料。
import unittest  # 验证版本与路径边界。
from pathlib import Path  # 明确测试根目录。
from types import SimpleNamespace  # 模拟最小统一工作流接口。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))  # 不依赖旧目录。
from storage import write_json, file_record  # 使用实际存储与指纹规则。
from docking_ui import load_preview  # 测试实际页面资料入口。
from contracts import ContractError  # 预期错误。


class PreviewTests(unittest.TestCase):  # 合成资料不进入真实研究。
    def setUp(self):  # 每项测试使用独立目录。
        self.temporary = tempfile.TemporaryDirectory()  # 临时测试根。
        self.addCleanup(self.temporary.cleanup)  # 仅清理本测试创建的临时资料。
        self.root = Path(self.temporary.name)  # 实际根目录。
        self.parents = {'A03': 'r3', 'A03_SELECT': 'rs', 'A04': 'r4'}  # 虚构固定版本。
        self.manifest = {'current': dict(self.parents)}  # 当前索引。
        evidence = self.root / 'references' / 'evidence.json'  # 虚构证据。
        write_json(evidence, {'test': True})  # 不使用真实科学结果。
        self.plan = {'schema_version': 'A06.preview.1', 'study_id': 's1', 'status': 'draft_not_reviewable', 'parent_runs': dict(self.parents), 'evidence': [file_record(self.root,evidence,'test')]}  # 最小完整预览。
        self.workflow = SimpleNamespace(root=self.root, load=lambda sid:self.manifest, active=lambda m,r:True)  # 只隔离工作流外部依赖。
        self.save()  # 按真实指纹结构发布测试索引。

    def save(self):  # 测试场景明确更新测试索引。
        path = self.root / 'governance' / 'plan.json'  # 只在临时根内。
        write_json(path,self.plan,replace=True)  # 不改真实研究。
        write_json(self.root/'environments'/'A06_previews.json',{'schema_version':'A06.preview.index.1','studies':{'s1':file_record(self.root,path,'test')}},replace=True)  # 使用真实索引结构。

    def test_read_only_and_scope(self):  # 合法读取不修改研究或替其他研究找资料。
        self.assertEqual(load_preview(self.workflow,'s1'),self.plan)  # 返回固定资料。
        self.assertEqual(self.manifest['current'],self.parents)  # 没有改动上游。
        with self.assertRaises(ContractError):  # 不能复用另一研究资料。
            load_preview(self.workflow,'s2')  # 未登记研究必须拒绝。

    def test_stale_parent(self):  # 上游换版使预览失效。
        self.manifest['current']['A03'] = 'new'  # 模拟真实重跑。
        with self.assertRaises(ContractError):  # 旧资料不能继续展示为当前。
            load_preview(self.workflow,'s1')  # 不按修改日期猜复用。

    def test_tampered_evidence(self):  # 文件即使还存在也必须校验。
        (self.root/'references'/'evidence.json').write_text('{}',encoding='utf-8')  # 故意改变测试证据。
        with self.assertRaises(ContractError):  # 指纹不符应拒绝。
            load_preview(self.workflow,'s1')  # 不隐藏篡改。

    def test_unbound_parent(self):  # 不完整来源不能通过。
        self.plan['parent_runs'].pop('A04')  # 移除一个上游绑定。
        self.save()  # 模拟格式完整但语义缺字段。
        with self.assertRaises(ContractError):  # 不自动补当前值。
            load_preview(self.workflow,'s1')  # 来源缺口必须明确。


    def test_prepared_package_scope(self):  # 新受体包不能借用其他研究的产物。
        report = {'study_id': 'another', 'parent_runs': self.parents, 'status': 'draft_not_reviewable', 'results': [], 'evidence': [], 'code': []}  # 模拟错绑研究。
        path = self.root / 'governance' / 'prepared.json'  # 仅在测试目录。
        write_json(path, report)  # 写入语法正常但身份错误的资料。
        self.plan['prepared_receptor_report'] = file_record(self.root, path, 'prepared')  # 指纹正确也不能跨研究。
        self.save()  # 更新测试索引。
        with self.assertRaises(ContractError):  # 身份检查应阻断。
            load_preview(self.workflow, 's1')  # 使用实际加载入口。

    def test_prepared_nested_file_integrity(self):  # 候选包内部文件同样校验。
        evidence = dict(self.plan['evidence'][0])  # 引用已有虚构证据。
        evidence['sha256'] = '0' * 64  # 模拟内部错误指纹。
        report = {'study_id': 's1', 'parent_runs': self.parents, 'status': 'draft_not_reviewable', 'results': [], 'evidence': [evidence], 'code': []}  # 顶层包仍然完整。
        path = self.root / 'governance' / 'prepared.json'  # 只在测试根下。
        write_json(path, report)  # 保存内部引用损坏的案例。
        self.plan['prepared_receptor_report'] = file_record(self.root, path, 'prepared')  # 正确登记顶层指纹。
        self.save()  # 发布测试索引。
        with self.assertRaises(ContractError):  # 不能仅校验顶层JSON。
            load_preview(self.workflow, 's1')  # 内部原始与处理文件也须完整。

    def test_box_proposal_cannot_be_executable(self):  # 待确认方案不能夹带可执行配置。
        proposal = {'schema_version': 'A06.box.proposal.1', 'study_id': 's1', 'parent_runs': self.parents, 'status': 'pending_user_confirmation', 'executable': True, 'config_generated': False, 'docking_executed': False, 'receptor_report': None, 'ligand_report': None, 'boxes': [], 'evidence': []}  # 模拟错误状态。
        path = self.root / 'governance' / 'box.json'  # 仅在测试根内。
        write_json(path, proposal)  # 顶层文件本身完整。
        self.plan['box_proposal'] = file_record(self.root, path, 'box_proposal')  # 接入测试预览。
        self.save()  # 更新测试索引。
        with self.assertRaises(ContractError):  # 可执行标记必须被拒绝。
            load_preview(self.workflow, 's1')  # 不让方案页变成运行入口。


if __name__ == '__main__':  # 独立检查入口。
    unittest.main(verbosity=2)  # 输出实际验收结果。

# 通用自动化验收：隔离虚构研究测试动态矩阵、人工关口、复用和后台衔接。
from copy import deepcopy  # 构造独立参数变更。
from pathlib import Path  # 测试全部位于临时目录。
import json  # 核对网页和配置。
import subprocess  # 验证真实隔离工作进程启动。
import sys  # 引入正式源码。
import tempfile  # 防止污染真实研究。
import shutil  # 复制代码至临时项目，满足项目内证据归档。
import unittest  # 可重复执行测试。
from unittest.mock import patch  # 只模拟外部数据库和科学耗时计算。
from types import SimpleNamespace  # 构造简短工具返回值。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))  # 加载项目生产代码。
from contracts import require, ContractError  # 统一失败校验。
from storage import file_record, read_json, verified_file, write_json  # 真实归档和指纹。
from workflow import Workflow  # 真实版本与人工复核内核。
import docking_automation as automation  # 生产后台编排。
import docking_automation_compute as compute  # 生产准备与执行。
from docking_formal import prep_validator, formal_validator  # 生产领域校验。


def atom(x=0.0):  # 构造仅用于契约验收的一个碳原子。
    return f'ATOM      1  C   UNL A   1    {x:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00     0.000 C\n'  # 使用PDBQT固定列。


def fixture(root):  # 虚构对象数与病例不同，验证模板没有硬编码七成分十受体。
    flow = Workflow(root, {'A06_PREP': prep_validator(root), 'A06': formal_validator(root)})  # 准备和对接仍使用真实校验。
    sid = flow.create({'formula': '自动化虚构方', 'herbs': '虚构药味', 'disease': '自动化虚构病', 'disease_scope': '契约测试，不是科研结果', 'operator': '验收', 'species': 9606, 'analysis_purpose': 'workflow_test'}, kind='contract_test')  # 不调用外网MeSH。
    flow.review(sid, flow.load(sid)['current']['A00'], 'approved', '验收', '只测试接口')  # 明确测试批准。
    selected = [{'compound_id': 'MOLTEST1', 'name': '虚构成分一'}, {'compound_id': 'MOLTEST2', 'name': '虚构成分二'}]  # 两个成分。
    degrees = [30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 21, 20]  # 第十位并列全部保留。
    round1 = [{'symbol': 'G' + str(index), 'target_id': 'HGNC:' + str(index), 'degree': degree} for index, degree in enumerate(degrees, 1)]  # 虚构PPI网络。
    for module, tables in [('A01', {}), ('A02', {}), ('A03', {}), ('A03_SELECT', {'selected': selected}), ('A04', {'round1': round1}), ('A05', {})]:  # 真实模块依赖和批准顺序。
        run = flow.begin(sid, module, {}, {}, '虚构上游接口验收')  # 新运行。
        flow.finish(sid, run['run_id'], {'analysis_purpose': 'workflow_test'}, tables, [], 'success')  # 仅契约测试项目允许这些小型夹具。
        flow.review(sid, run['run_id'], 'approved', '验收', '虚构资料不用于科研结论')  # 明确独立复核。
    plan = {'compounds': [{'compound_id': row['compound_id'], 'cid': '1', 'status': 'use', 'reason': '虚构形态仅接口测试', 'protonation_policy': 'pubchem_3d_as_provided_no_pH_prediction'} for row in selected], 'receptors': [{'target': 'G' + str(index), 'pdb_id': '1ABC', 'chains': ['A'], 'uniprot': 'P00001', 'pocket': 'reference', 'reference_code': 'ABC', 'reference_chain': 'A', 'reference_sequence': '1', 'altloc': None, 'scope': 'strict' if index <= 5 else 'unavailable', 'reason': '虚构结构仅接口测试'} for index in range(1, 12)], 'package_id': 'D900', 'pymol_executable': sys.executable}  # 十一个受体、两成分。
    (root / 'config').mkdir()  # 独立环境配置。
    (root / 'config' / 'automation_runtime.toml').write_text("schema_version='ModuleA.automation.runtime.1'\nscience_python='" + sys.executable + "'\nreport_python='" + sys.executable + "'\n", encoding='utf-8')  # 测试不绑定个人安装路径。
    record = automation.save_plan(flow, sid, plan, automation.parents(flow, sid), '验收', '虚构方案只核验衔接')  # 生产保存入口。
    return flow, sid, record, plan  # 测试持有明确来源。


class AutomationTests(unittest.TestCase):  # 主要验证接口安全和实际版本流转。
    def setUp(self):  # 每项测试独立研究。
        self.temporary = tempfile.TemporaryDirectory(prefix='moduleA_automation_')  # 不写真实研究。
        self.root = Path(self.temporary.name)  # 临时项目根。
        (self.root / 'src').mkdir()  # 临时研究使用独立代码证据。
        for source in (Path(__file__).resolve().parents[1] / 'src').glob('*.py'):  # 原样复制实际源码。
            shutil.copy2(source, self.root / 'src' / source.name)  # 后台隔离启动也能完整导入。
        self.code_location = patch('docking_generic_prep.__file__', str(self.root / 'src' / 'docking_generic_prep.py'))  # 仅改变临时来源位置，不改变筛查算法。
        self.code_location.start()  # 证据归档不跨根目录。
        self.flow, self.sid, self.record, self.plan = fixture(self.root)  # 创建小型完整上游。

    def tearDown(self):  # 仅清理本测试临时目录。
        self.code_location.stop()  # 恢复源码定位。
        self.temporary.cleanup()  # 不清理正式项目。

    def test_unknown_shape_and_stale_page_cannot_save(self):  # 科学形态不能默认指定，旧页面不能发布。
        altered = deepcopy(self.plan)  # 独立变更。
        altered['compounds'][0]['protonation_policy'] = 'guess_pH'  # 未审定形态。
        with self.assertRaisesRegex(ValueError, '形态'):  # 不接受自动猜测。
            automation.save_plan(self.flow, self.sid, altered, automation.parents(self.flow, self.sid), '验收', '错误形态')  # 真实保存校验。
        with self.assertRaisesRegex(ValueError, '上游已改变'):  # 版本冲突全部拒绝。
            automation.save_plan(self.flow, self.sid, self.plan, {}, '验收', '旧页面')  # 不形成当前新方案。

    def test_missing_high_ranked_receptor_cannot_save(self):  # 高位失败对象不得删除。
        altered = deepcopy(self.plan)  # 独立方案。
        altered['receptors'].pop(0)  # 删除首位。
        with self.assertRaisesRegex(ValueError, '覆盖'):  # 窗口必须完整。
            automation.save_plan(self.flow, self.sid, altered, automation.parents(self.flow, self.sid), '验收', '错误范围')  # 生产校验。

    def test_predicted_pocket_cannot_be_strict(self):  # 无参考配体不得充当主要受体。
        altered = deepcopy(self.plan)  # 单项变更。
        altered['receptors'][0]['pocket'] = 'p2rank'  # 预测无重对接。
        with self.assertRaisesRegex(ValueError, '预测口袋'):  # 阻断假严格。
            automation.save_plan(self.flow, self.sid, altered, automation.parents(self.flow, self.sid), '验收', '错误严格')  # 真实保存入口。

    def test_unapproved_preparation_cannot_execute(self):  # 用户未批准准备时不能真正计算。
        with self.assertRaisesRegex(ValueError, 'A06对象与配置复核'):  # 网页绕过也无效。
            automation.start_job(self.flow, self.sid, 'execute')  # 不启动子进程。

    def test_enrichment_failure_does_not_block_docking_branch(self):  # 独立富集分支失败不能阻断已批准PPI后的准备。
        import auto_continue  # 使用真实自动衔接逻辑。
        manifest = self.flow.load(self.sid)  # 临时研究当前版本。
        manifest['current'].pop('A05')  # 只在虚构夹具模拟尚无富集结果。
        self.flow.save(manifest)  # 保留其他批准关口。
        with patch.object(auto_continue, 'run_enrichment', side_effect=ContractError('虚构富集来源失败')):  # 不真实调用数据库。
            outcome = auto_continue.continue_after_review(self.flow, self.sid)  # PPI分支继续进入结构准备。
        self.assertIn('A06', outcome['waiting'])  # 页面定位可继续的分支。
        self.assertTrue(any('A05' in value for value in outcome['errors']))  # 富集错误仍保留而非隐藏。

    def test_web_entry_shows_controls_and_rejects_missing_token(self):  # 真正HTTP入口可见，不能绕过统一页面校验。
        import threading  # 测试专用本机服务。
        from urllib.request import urlopen, Request  # 使用真实HTTP客户端。
        from urllib.error import HTTPError  # 校验拒绝响应。
        from urllib.parse import urlencode  # 规范表单编码。
        from web import create_server  # 与实际网页使用同一入口。
        server = create_server(self.root, 0)  # 临时项目与随机端口。
        worker = threading.Thread(target=server.serve_forever, daemon=True)  # 不影响真实工作台。
        worker.start()  # 启动短期HTTP服务。
        base = 'http://127.0.0.1:' + str(server.server_port)  # 仅本机。
        try:  # 失败也关闭测试服务。
            with patch('hgnc.load_snapshot', return_value=(SimpleNamespace(index={}), {})):  # 页面提示使用虚构映射，不进行身份科学判断。
                with urlopen(base + '/docking-automation?study=' + self.sid) as response:  # 真实GET路由。
                    body = response.read().decode('utf-8')  # 核验中文界面。
            self.assertIn('保存方案并自动准备结构与质控', body)  # 新入口确实接入。
            self.assertIn('MOLTEST2', body)  # 动态成分而非写死本次七成分。
            self.assertIn('G11', body)  # 第十位并列对象可见。
            payload = urlencode({'study': self.sid, 'stage': 'prepare'}).encode()  # 缺令牌模拟绕过页面。
            with self.assertRaises(HTTPError) as error:  # 统一防护拒绝操作。
                urlopen(Request(base + '/docking-automation-start', payload, {'Content-Type': 'application/x-www-form-urlencoded'}))  # 不会启动真实子进程。
            self.assertEqual(error.exception.code, 400)  # 明确拒绝。
            self.assertIsNone(automation.job_status(self.flow, self.sid))  # 没有伪任务记录。
        finally:  # 只关闭测试资源。
            server.shutdown()  # 停止服务。
            server.server_close()  # 释放端口。
            worker.join(timeout=3)  # 等待停止。

    def test_real_isolated_worker_records_failure(self):  # 真实启动后台解释器，缺环境须明确失败而非无限等待。
        import time  # 有界等待真实子进程结束。
        automation.start_job(self.flow, self.sid, 'prepare')  # 用生产启动器而非模拟Popen。
        deadline = time.monotonic() + 30  # 不启动真实数据库或Vina计算。
        state = None  # 保存实际任务状态。
        while time.monotonic() < deadline:  # 最长三十秒，仅等隔离导入和环境诊断。
            state = automation.job_status(self.flow, self.sid)  # 读取生产状态接口。
            if state['state'] not in ('queued', 'running'):  # 实际失败必须写入终态。
                break  # 无需等待超时。
            time.sleep(0.1)  # 此等待不占网页线程。
        folder = verified_file(self.flow.location(self.sid), read_json(self.flow.location(self.sid) / 'governance' / 'A06_automation_index.json')['job']).parent  # 明确任务位置。
        self.assertEqual(state['state'], 'failed', (state, (folder / 'worker_stderr.txt').read_text('utf-8', errors='replace')))  # 失败时展示真实导入日志便于修复。
        self.assertTrue((folder / 'failure.json').is_file())  # 保存用户可读失败原因。
        self.assertTrue((folder / 'worker_stderr.txt').is_file())  # 保存维护堆栈。
        self.assertNotIn('A06_PREP', self.flow.load(self.sid)['current'])  # 不发布伪造准备结果。

    def test_job_duplicate_click_and_abnormal_exit(self):  # 同输入只启动一个后台进程。
        with patch.object(automation.subprocess, 'Popen', return_value=SimpleNamespace(pid=1234, poll=lambda: None)) as spawn, patch.object(automation, '_alive', return_value=True):  # 不启动科学计算。
            first = automation.start_job(self.flow, self.sid, 'prepare')  # 第一次登记。
            second = automation.start_job(self.flow, self.sid, 'prepare')  # 模拟重复点击。
            self.assertEqual(first['request']['identity'], second['request']['identity'])  # 同一个任务身份。
            self.assertEqual(spawn.call_count, 1)  # 不重复调用后台程序。
            with self.assertRaisesRegex(ValueError, '已有后台任务'):  # 工作中不修改科学方案。
                automation.save_plan(self.flow, self.sid, self.plan, automation.parents(self.flow, self.sid), '验收', '运行中修改')  # 防竞态。
        with patch.object(automation, '_alive', return_value=False):  # 模拟进程意外退出。
            self.assertEqual(automation.job_status(self.flow, self.sid)['state'], 'interrupted')  # 不无限显示运行。

    def test_current_guard_rejects_revised_plan(self):  # 后台结果不能覆盖新的结构选择。
        ids = automation.parents(self.flow, self.sid)  # 当前科学输入。
        request = {'study_id': self.sid, 'parent_runs': ids, 'parent_review_ids': automation.review_bindings(self.flow, self.sid, ids), 'plan': self.record}  # 原冻结请求。
        automation.save_plan(self.flow, self.sid, self.plan, automation.parents(self.flow, self.sid), '验收', '新方案')  # 相同对象但新人工决定。
        with self.assertRaisesRegex(ValueError, '方案已更新'):  # 原任务失效。
            automation.assert_current(self.flow, request)  # 不发布旧结果。

    def test_reuse_key_covers_inputs_box_and_tool(self):  # 同名但不同科学输入不能复用。
        prep = {'software': {'version': 'fixed'}}  # 冻结环境。
        receptor = {'receptor_record': {'sha256': 'r'}, 'pdb_id': '1ABC', 'chains': ['A'], 'box': {'center': [0, 0, 0], 'size': [10, 10, 10]}}  # 真实键字段。
        compound = {'ligand_record': {'sha256': 'l'}, 'identity': {'inchi_key': 'k'}}  # 结构身份。
        original = compute.pair_key(prep, receptor, compound)  # 原组合键。
        for changed in [dict(receptor, pdb_id='2ABC'), dict(receptor, chains=['B']), dict(receptor, receptor_record={'sha256': 'other'}), dict(receptor, box={'center': [1, 0, 0], 'size': [10, 10, 10]})]:  # 结构、链、字节和盒改变。
            self.assertNotEqual(original, compute.pair_key(prep, changed, compound))  # 不能复用旧评分。
        self.assertNotEqual(original, compute.pair_key({'software': {'version': 'new'}}, receptor, compound))  # 工具版本变化也重新计算。

    def test_preparation_execution_dynamic_matrix_and_exact_reuse(self):  # 真正走准备发布、复核、动态计算发布和缓存复用。
        parent_ids = automation.parents(self.flow, self.sid)  # 准备请求上游。
        folder = self.flow.location(self.sid) / 'runs' / 'A06_PREP' / 'job_fixture_prepare'  # 测试任务目录。
        folder.mkdir()  # 仅临时研究。
        request = {'study_id': self.sid, 'parent_runs': parent_ids, 'parent_review_ids': automation.review_bindings(self.flow, self.sid, parent_ids), 'plan': self.record}  # 明确方案与批准。
        software = {'version': 'fixture_only'}  # 外部软件只模拟，生产版本校验另行实测。
        def capture(flow, output, url, label):  # 官方来源的虚构回应，不冒充科研采集。
            return json.dumps({'PropertyTable': {'Properties': [{'CID': 1, 'InChIKey': 'fixture'}]}}) if 'property/' in url else 'fixture_sdf'  # 仅驱动衔接。
        def prepared_receptor(flow, output, spec, target_id):  # 模拟已验收受体内核输出。
            if spec['scope'] == 'unavailable':  # 第六至第十一位NA。
                return dict(spec, status='failed', error='fixture unavailable', rmsd=None, box=None)  # 全部对象保留。
            path = output / (spec['target'] + '.pdbqt')  # 真实输入文件。
            path.write_text(atom(2.0), encoding='ascii')  # 合法固定列坐标。
            return dict(spec, status='ready', error='', rmsd=1.0, box={'center': [0, 0, 0], 'size': [10, 10, 10]}, receptor_record=file_record(flow.location(self.sid), path, 'receptor'))  # 五个严格事实。
        def vina(command, cwd, stdout, stderr):  # 模拟外部Vina，后续姿势与文件校验完全真实。
            output = Path(command[command.index('--out') + 1])  # 明确输出路径。
            output.write_text('MODEL 1\nREMARK VINA RESULT: -5.000 0 0\n' + atom() + 'ENDMDL\n', encoding='ascii')  # 固定Top1测试分数。
            stdout.write_text('fixture only', encoding='ascii')  # 真实日志文件。
            stderr.write_text('', encoding='ascii')  # 完整日志角色。
            return SimpleNamespace(returncode=0)  # 仅外部执行模拟。
        prepared = {'pdbqt_text': atom(), 'identity': {'heavy_atom_count': 1}}  # 模拟已核验化学内核输出。
        with patch.object(compute, '_software', return_value=software), patch.object(compute, '_capture', side_effect=capture), patch.object(compute, '_prepare_receptor', side_effect=prepared_receptor), patch('docking_ligand.prepare_ligand', return_value=prepared), patch('docking_ligand_flow.check_ligand_coordinates', return_value={'passed': True}), patch.object(compute, '_meeko_settings', return_value={}):  # 耗时来源和结构核对模拟；版本流转不模拟。
            result = compute.prepare(self.flow, request, folder, lambda message: None)  # 发布真正A06_PREP。
        self.assertFalse(self.flow.approved(self.flow.load(self.sid), result['run_id']))  # 自动化绝不代签准备。
        self.flow.review(self.sid, result['run_id'], 'approved', '验收', '模拟人工对象复核')  # 用户关口。
        request['parent_runs']['A06_PREP'] = result['run_id']  # 执行明确准备版本。
        request['parent_review_ids'] = automation.review_bindings(self.flow, self.sid, request['parent_runs'])  # 新阶段冻结本次准备批准。
        execute_folder = self.flow.location(self.sid) / 'runs' / 'A06_PREP' / 'job_fixture_execute'  # 动态执行目录。
        execute_folder.mkdir()  # 新版本不覆盖准备。
        with patch.object(compute, '_software', return_value=software), patch.object(compute, '_run', side_effect=vina) as mocked:  # 不真实计算虚构蛋白。
            result = compute.execute(self.flow, request, execute_folder, lambda message: None)  # 真实矩阵和A06发布。
            self.assertEqual(mocked.call_count, 10)  # 五受体×两成分，失败十二组不调用Vina。
        self.assertFalse(self.flow.approved(self.flow.load(self.sid), result['run_id']))  # 不代签结果。
        generic = self.flow.result(self.flow.load(self.sid), result['run_id'])['tables']['generic_docking']  # 真实契约。
        self.assertEqual((len(generic['receptors']), len(generic['compounds']), len(generic['planned_pairs']), len(generic['completed_pairs']), len(generic['failed_pairs'])), (11, 2, 22, 10, 12))  # 非硬编码矩阵。
        copied = self.flow.location(self.sid) / 'cache_test'  # 复用到独立目录。
        copied.mkdir()  # 不覆盖原计算文件。
        cache = read_json(self.root / 'environments' / 'A06_pair_cache.json')  # 真实缓存索引。
        key = next(iter(cache['pairs']))  # 明确记录而非mtime选择。
        row = compute._reuse(self.flow, key, self.flow.location(self.sid), copied)  # 真正逐项指纹复用。
        self.assertEqual(row['score_kcal_mol'], -5.0)  # 原评分不变。
        self.assertFalse(row['reuse_provenance']['new_vina_calculation'])  # 不声称新计算。
        with patch.object(compute, 'verified_file', side_effect=ContractError('归档文件校验失败，暂停使用')):  # 模拟校验失败，不改写任何对接文件。
            with self.assertRaisesRegex(ValueError, '校验失败'):  # 损坏缓存不能继续使用。
                compute._reuse(self.flow, key, self.flow.location(self.sid), copied)  # 不隐式重算掩盖破坏。
        reuse_folder = self.flow.location(self.sid) / 'runs' / 'A06_PREP' / 'job_fixture_reuse'  # 验证整个新矩阵按精确输入复用。
        reuse_folder.mkdir()  # 保留前一次执行文件。
        with patch.object(compute, '_software', return_value=software), patch.object(compute, '_run', side_effect=AssertionError('相同输入不应再运行Vina')) as repeated:  # 使用真实缓存和姿势复核。
            result = compute.execute(self.flow, request, reuse_folder, lambda message: None)  # 生成独立新A06。
        self.assertEqual(repeated.call_count, 0)  # 十组成功组合全部复用。
        reused_result = self.flow.result(self.flow.load(self.sid), result['run_id'])  # 读取实际计数。
        self.assertEqual(reused_result['summary']['复用组合数'], 10)  # 报告事实能区分复用。
        self.assertEqual(len(reused_result['tables']['generic_docking']['failed_pairs']), 12)  # 原NA没有被填造。
        self.flow.review(self.sid, result['run_id'], 'approved', '验收', '虚构对接结果仅接口验收')  # 验证交付也需要独立批准。
        manifest = self.flow.load(self.sid)  # 冻结完整报告所需上游。
        request['parent_runs'].update({key: manifest['current'][key] for key in ('A01', 'A02', 'A05', 'A06')})  # 不跨研究交付。
        request['parent_review_ids'] = automation.review_bindings(self.flow, self.sid, request['parent_runs'])  # 当前批准记录。
        def package_builder(root, sid, a06_id, package_id, pymol, output_parent):  # 只模拟外部PyMOL导出，版本和ZIP使用生产代码。
            from docking_task_package_v2 import _safe_name  # 使用真实命名规则。
            package = output_parent / f'{package_id}_{_safe_name("自动化虚构方")}_{_safe_name("自动化虚构病")}_22pairs'  # 真实计划数量。
            package.mkdir(parents=True)  # 草案位置归于本次任务。
            payload = package / 'fixture.txt'  # 虚构绘图文件不能作为科研输出。
            payload.write_text('虚构文件，仅测试交付', encoding='utf-8')  # 固定文件字节。
            write_json(package / 'package_index.json', {'study_id': sid, 'source_a06_run': a06_id, 'package_id': package_id, 'files': [file_record(package, payload, 'fixture')]})  # 完整指纹索引。
            return package  # 生产交付逻辑进行原子发布。
        def report_builder(flow, sid, previous, reason, task_package):  # 只模拟Word排版，A07版本和输入绑定仍使用真实内核。
            run = flow.begin(sid, 'A07', {'task_package_index': task_package['index'], 'task_package_archive': task_package['archive']}, {}, reason)  # 真实不可变报告运行。
            return flow.finish(sid, run['run_id'], {'handoff_blocked': False}, {}, [], 'success')  # 待人工复核。
        with patch('docking_task_package_v2.build', side_effect=package_builder) as build, patch('report_flow.run_reports', side_effect=report_builder) as reports:  # 不为虚构对象制作科学报告。
            first_folder = self.flow.location(self.sid) / 'runs' / 'A06_PREP' / 'job_delivery_one'  # 第一次交付。
            first_folder.mkdir()  # 新任务留存。
            first = compute.deliver(self.flow, request, first_folder, lambda message: None)  # ZIP与索引核验完全真实。
            second_folder = self.flow.location(self.sid) / 'runs' / 'A06_PREP' / 'job_delivery_two'  # 模拟完成凭证写入前中断后重试。
            second_folder.mkdir()  # 不覆盖前一次记录。
            second = compute.deliver(self.flow, request, second_folder, lambda message: None)  # 同输入不重建任务包和报告。
        self.assertEqual(first['run_id'], second['run_id'])  # 不重复生成同源A07。
        self.assertEqual((build.call_count, reports.call_count), (1, 1))  # 绘图与报告均只调用一次。
        self.assertFalse(self.flow.approved(self.flow.load(self.sid), first['run_id']))  # 最后结论仍需用户批准。


if __name__ == '__main__':  # 独立验收入口。
    unittest.main(verbosity=2)  # 输出各项真实通过或失败。

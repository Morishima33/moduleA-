# 通用A06自动化：明确研究输入、后台任务、结构准备、对接复用和交付衔接。
import argparse  # 提供后台工作进程入口。
import json  # 读取官方结构回应和输出状态。
import os  # 隔离子进程环境。
from pathlib import Path  # 使用研究内部相对路径。
import re  # 校验结构编号与任务编号。
import subprocess  # 后台启动固定工具。
import sys  # 使用指定科学解释器。
import zipfile  # 打包可复算文件。
if __name__ == '__main__' and '--root' in sys.argv:  # 隔离启动时先显式加入本项目源码。
    sys.path.insert(0, str(Path(sys.argv[sys.argv.index('--root') + 1]) / 'src'))  # -I不会自动添加脚本目录。
from contracts import fingerprint, require, safe_id  # 共用身份及阻断规则。
from storage import file_record, new_id, now, read_json, verified_file, within, write_json, write_lock  # 共用版本和指纹。

PARENTS = ('A00', 'A03', 'A03_SELECT', 'A04')  # 对象、选择和PPI共同绑定结构方案。
PLAN_SCHEMA = 'A06.automation.plan.1'  # 新方案不改变历史病例合同。
PREP_SCHEMA = 'A06.automation.preparation.1'  # 准备事实独立于对接结果。
JOB_SCHEMA = 'ModuleA.automation.job.1'  # 后台任务只存执行状态，不代替模块结果。
_PROCESSES = {}  # 当前网页进程保留后台句柄，结束后释放，不替代磁盘状态。


def runtime_config(root):  # 本机程序位置与科学参数分开保存。
    import tomllib  # TOML允许逐行中文注释。
    with (Path(root) / 'config' / 'automation_runtime.toml').open('rb') as stream:  # 固定可迁移环境配置。
        config = tomllib.load(stream)  # 不猜电脑安装位置。
    require(config.get('schema_version') == 'ModuleA.automation.runtime.1', '自动化环境配置版本不支持')  # 未知版本不运行。
    return config  # 路径可按电脑调整，科学规则不变。


def workflow_instance(root):  # 不让科学解释器依赖另一版本的Word库。
    from workflow import Workflow  # 共用主编排器。
    from components import validate_components  # A01领域校验。
    from disease import validate_disease  # A02领域校验。
    from normalization import validator as normalized  # HGNC标准化校验。
    from intersection_flow import validate_intersection, validate_selection  # 交集与选择校验。
    from docking_formal import prep_validator, formal_validator  # 对接两关口校验。
    def ppi(run, summary, tables, anomalies, outcome):  # 对接阶段不提前加载网络绘图库。
        from ppi_flow import validator  # 真正核验PPI时才使用对应依赖。
        return validator(root)(run, summary, tables, anomalies, outcome)  # 保持相同科学合同。
    def enrichment(run, summary, tables, anomalies, outcome):  # 对接阶段不提前加载富集执行依赖。
        from enrichment_flow import validator  # 真正核验富集时再导入。
        return validator(root)(run, summary, tables, anomalies, outcome)  # 不降低校验。
    def reports(run, summary, tables, anomalies, outcome):  # 只有真的报告阶段才加载Word依赖。
        from report_flow import validator  # 使用报告解释器自有库。
        return validator(root)(run, summary, tables, anomalies, outcome)  # 不降低任何校验。
    return Workflow(root, {'A01': normalized(root, validate_components), 'A02': normalized(root, validate_disease), 'A03': validate_intersection, 'A03_SELECT': validate_selection, 'A04': ppi, 'A05': enrichment, 'A06_PREP': prep_validator(root), 'A06': formal_validator(root), 'A07': reports})  # 与网页同一组科学合同。


def parents(workflow, study_id):  # 重新校验本研究四个上游。
    manifest = workflow.load(study_id)  # 唯一研究索引。
    require(not manifest.get('trashed', False), '请先恢复研究')  # 回收站不能运行。
    result = {key: manifest['current'].get(key, '') for key in PARENTS}  # 不凭文件时间推断当前。
    require(all(result.values()) and all(workflow.approved(manifest, value) for value in result.values()), 'A00、A03、成分选择和A04须复核通过')  # 不跨人工关口。
    return result  # 返回已批准版本。


def review_bindings(workflow, study_id, ids):  # 冻结批准记录，撤回后重批不能复活旧任务。
    manifest = workflow.load(study_id)  # 当前统一索引。
    return {key: workflow.latest_review(manifest, workflow.run(manifest, value)['artifact_id'])['review_id'] for key, value in ids.items()}  # 每项绑定实际生效复核。


def current_plan(workflow, study_id):  # 只从研究级索引读取方案。
    index = workflow.location(study_id) / 'governance' / 'A06_automation_index.json'  # 研究内部唯一自动化索引。
    if not index.exists():  # 首次研究没有方案。
        return None  # 页面可以填写。
    data = read_json(index)  # 读取索引。
    record = data.get('plan')  # 明确方案引用。
    if not record:  # 只登记过交付任务时无结构方案。
        return None  # 不猜其他文件。
    value = read_json(verified_file(workflow.location(study_id), record))  # 指纹检查。
    require(value['study_id'] == study_id and value['schema_version'] == PLAN_SCHEMA, '自动化方案归属或版本错误')  # 防止跨研究输入。
    return value, record  # 同时返回来源。


def save_plan(workflow, study_id, data, expected_parents, reviewer, note):  # 保存用户明确的结构选择，科学未定值不填默认。
    from docking_generic_prep import prepare_screen  # 沿用PPI前十位及并列窗口。
    require(str(reviewer).strip() and str(note).strip(), '请填写复核人和结构选择依据')  # 留存实际决定。
    with write_lock(workflow.root):  # 防止旧页面发布新方案。
        actual = parents(workflow, study_id)  # 写前再查当前批准。
        approvals = review_bindings(workflow, study_id, actual)  # 同时冻结人工批准版本。
        require(actual == expected_parents, '上游已改变，请刷新后重新确认')  # 旧页面不可覆盖。
        status = job_status(workflow, study_id)  # 不在长任务运行时改变其方案。
        require(not status or status['state'] not in ('queued', 'running'), '已有后台任务运行，请等待结束后修改方案')  # 防科学输入竞态。
    screen = prepare_screen(workflow, study_id)['preview']  # 复用既定筛查范围。
    require([row.get('target') for row in data.get('receptors', [])] == [row['symbol'] for row in screen['screening_window']], '结构方案必须按PPI顺序覆盖前十位及边界并列')  # 失败对象不能删除。
    require([row.get('compound_id') for row in data.get('compounds', [])] == [row['compound_id'] for row in screen['ligands']], '配体方案与已确认成分不同')  # 不允许悄悄换成分。
    for row in data['receptors']:  # 逐项冻结结构选择。
        require(row.get('scope') in ('strict', 'exploratory', 'unavailable') and str(row.get('reason', '')).strip(), '每个受体须有解释范围与依据')  # 无理由排除不能运行。
        if row['scope'] == 'unavailable':  # 已核定不能计算者保留NA。
            continue  # 不伪造PDB或盒子。
        require(re.fullmatch(r'[0-9][A-Za-z0-9]{3}', row.get('pdb_id', '')) and row.get('chains') and all(re.fullmatch(r'[A-Za-z0-9]', chain) for chain in row['chains']), '请填写PDB编号及作者链；首版只接受单字符PDB作者链')  # 不悄悄截断长链。
        require(len(set(row['chains'])) == len(row['chains']) and re.fullmatch(r'[A-Z0-9]{6,10}', row.get('uniprot', '')), '蛋白链重复或UniProt身份未指定')  # 身份不能猜测。
        require(row.get('pocket') in ('reference', 'p2rank') and row.get('altloc') in (None, 'A', 'B'), '口袋或替代构象选择未审定')  # 不套用本次病例A构象决定。
        if row['pocket'] == 'reference':  # 共晶必须定位唯一参考配体。
            require(re.fullmatch(r'[A-Z0-9]{1,3}', row.get('reference_code', '')) and re.fullmatch(r'[A-Za-z0-9]', row.get('reference_chain', '')) and re.fullmatch(r'-?\d+[A-Za-z]?', str(row.get('reference_sequence', ''))), '请明确共晶配体代码、作者链和残基编号')  # 不取第一个小分子。
        require(row['scope'] != 'strict' or row['pocket'] == 'reference', '预测口袋不能作为严格重对接主要受体')  # 无RMSD不能充当严格。
    for row in data['compounds']:  # 每个配体都绑定已审定形态。
        require(row.get('status') in ('use', 'unavailable') and str(row.get('reason', '')).strip(), '每个成分须有形态或暂停说明')  # 模板不自动授权中性态。
        if row['status'] == 'use':  # 可计算配体需要官方身份。
            require(str(row.get('cid', '')).isdigit() and int(row['cid']) > 0 and row.get('protonation_policy') == 'pubchem_3d_as_provided_no_pH_prediction', '请明确CID并确认使用原始PubChem三维形态；其他形态须另行审定')  # 不自动电离或换异构体。
    require(re.fullmatch(r'D\d{3,}', data.get('package_id', '')), '请明确任务包编号，如D006；系统不自动猜号')  # 沿用总控明确编号规则。
    require(isinstance(data.get('pymol_executable'), str) and Path(data['pymol_executable']).is_file(), '请在其他信息中指定可用PyMOL程序')  # 不交付伪PSE。
    folder = workflow.location(study_id) / 'runs' / 'A06_PREP' / new_id('plan')  # 新方案归入准备目录。
    sources = [file_record(workflow.location(study_id), verified_file(workflow.location(study_id), workflow.load(study_id)['runs'][value]['result_file']), key.lower() + '_result') for key, value in actual.items()]  # 上游完整快照引用。
    value = dict(data, schema_version=PLAN_SCHEMA, study_id=study_id, parent_runs=actual, parent_review_ids=approvals, reviewer=reviewer, note=note, created_at=now(), sources=sources)  # 冻结人工科学选择。
    write_json(folder / 'automation_plan.json', value)  # 方案不可覆盖。
    record = file_record(workflow.location(study_id), folder / 'automation_plan.json', 'automation_plan')  # 记录研究相对路径。
    with write_lock(workflow.root):  # 索引切换前最后核查。
        require(parents(workflow, study_id) == actual, '保存期间上游已改变；方案保留但不启用')  # 孤立草案不成为当前。
        require(review_bindings(workflow, study_id, actual) == approvals, '保存期间上游复核已改变；请重新确认方案')  # 不把旧批准写成新决定。
        status = job_status(workflow, study_id)  # 验证期间另一进程可能刚启动。
        require(not status or status['state'] not in ('queued', 'running'), '已有后台任务运行；方案保留为草案，不切换当前输入')  # 防止第二次锁之间的方案竞态。
        path = workflow.location(study_id) / 'governance' / 'A06_automation_index.json'  # 同一唯一索引。
        index = read_json(path) if path.exists() else {'schema_version': 'A06.automation.index.1', 'study_id': study_id}  # 历史字段保留。
        index['plan'] = record  # 只改变方案引用。
        write_json(path, index, replace=True)  # 原子更新索引。
    return record  # 后台执行只接收此文件。


def _alive(pid):  # 检查后台任务是否仍真实运行。
    if not pid:  # 尚未启动。
        return False  # 不把排队当运行。
    if os.name == 'nt':  # Windows不使用可能影响进程的信号检查。
        import ctypes  # 只读查询进程状态。
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)  # 使用Windows API。
        kernel.OpenProcess.restype = ctypes.c_void_p  # 64位句柄不能截断。
        handle = kernel.OpenProcess(0x1000, False, pid)  # 最小查询权限。
        if not handle:  # 进程已退出或不可访问。
            return False  # 请求人工查看日志。
        code = ctypes.c_ulong()  # 保存退出码。
        kernel.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))  # 明确句柄宽度。
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)  # 正确释放句柄。
        success = kernel.GetExitCodeProcess(handle, ctypes.byref(code))  # 只读查询。
        kernel.CloseHandle(handle)  # 不泄漏查询句柄。
        return bool(success and code.value == 259)  # STILL_ACTIVE代表正在运行。
    try:  # 其他系统只检查存在性。
        os.kill(pid, 0)  # 不发送实际信号。
        return True  # 进程仍存在。
    except OSError:  # 已退出。
        return False  # 不冒充运行中。


def job_status(workflow, study_id):  # 页面只读取明确当前任务索引。
    index = workflow.location(study_id) / 'governance' / 'A06_automation_index.json'  # 不扫描目录猜任务。
    if not index.exists():  # 尚无任务。
        return None  # 显示准备入口。
    record = read_json(index).get('job')  # 当前任务固定请求文件。
    if not record:  # 尚未执行。
        return None  # 正常初始态。
    request = read_json(verified_file(workflow.location(study_id), record))  # 固定任务请求指纹。
    status = read_json(verified_file(workflow.location(study_id), record).parent / 'status.json')  # 可变状态与不可变请求分开。
    process = _PROCESSES.get(status.get('pid'))  # 同一网页会话可回收已经退出的句柄。
    if process is not None and process.poll() is not None:  # 查询不会阻塞网页。
        _PROCESSES.pop(status.get('pid'), None)  # 已退出后释放句柄。
    if status['state'] in ('queued', 'running') and not _alive(status.get('pid')):  # 进程退出不能无限显示运行中。
        status = dict(status, state='interrupted', message='后台进程已退出；原日志保留，请重试。')  # 页面如实提示，不能解释为完成。
    return dict(status, request=request)  # 不修改原始结果。


def start_job(workflow, study_id, stage, plan_record=None):  # 后台执行长任务，网页无需等待Vina。
    require(stage in ('prepare', 'execute', 'deliver'), '不支持的自动化阶段')  # 不允许任意命令。
    parent_ids = parents(workflow, study_id)  # 固定科学身份。
    manifest = workflow.load(study_id)  # 补充当前模块依赖。
    if stage == 'prepare':  # 结构准备依据明确方案。
        selected = current_plan(workflow, study_id)  # 只用本研究方案。
        require(selected is not None and selected[0]['parent_runs'] == parent_ids, '请先确认本研究结构方案')  # 旧方案不能自动沿用。
        require(selected[0].get('parent_review_ids') == review_bindings(workflow, study_id, parent_ids), '上游复核记录已改变，请重新确认结构方案')  # 同ID重批也不复活旧方案。
        plan_record = selected[1]  # 避免调用者传入其他方案。
    elif stage == 'execute':  # 真正对接只能在准备批准后运行。
        require(manifest['current'].get('A06_PREP') and workflow.approved(manifest, manifest['current']['A06_PREP']), '请先通过A06对象与配置复核')  # 不代签准备关口。
        parent_ids['A06_PREP'] = manifest['current']['A06_PREP']  # 绑定准备版本。
        prep_run = workflow.run(manifest, parent_ids['A06_PREP'])  # 结构方案也必须仍是当前。
        selected = current_plan(workflow, study_id)  # 读取明确方案指针。
        require(selected is not None and prep_run['inputs'].get('automation_plan') == selected[1], '结构方案与已批准准备不一致，请重新准备及复核')  # 不跨方案执行。
        plan_record = selected[1]  # 发布前再次检查其未改变。
    else:  # 交付依赖全部报告分支和对接通过。
        for key in ('A01', 'A02', 'A05', 'A06'):  # 富集不阻断对接，但必须齐备才出双报告。
            require(manifest['current'].get(key) and workflow.approved(manifest, manifest['current'][key]), key + '须通过才可生成交付')  # 不生成正式部分报告。
            parent_ids[key] = manifest['current'][key]  # 防止交付期间补库串结果。
        existing_plan = current_plan(workflow, study_id)  # 用户编号及本地工具来自已确认方案。
        require(existing_plan is not None and existing_plan[0]['parent_runs'] == parents(workflow, study_id), '请先确认任务包编号及本研究自动化方案')  # 历史病例不自动迁移。
        prep_id = manifest['current'].get('A06_PREP')  # 交付也须来自当前方案准备的对接。
        require(prep_id and workflow.run(manifest, prep_id)['inputs'].get('automation_plan') == existing_plan[1] and workflow.run(manifest, parent_ids['A06'])['parent_runs'].get('A06_PREP') == prep_id, '当前A06不属于已确认结构方案，请先重新准备和复核')  # 改方案后不能把旧评分交付成新方案。
        plan_record = existing_plan[1]  # 冻结交付配置。
    approvals = review_bindings(workflow, study_id, parent_ids)  # 每个阶段冻结全部所需批准。
    identity = fingerprint({'stage': stage, 'parents': parent_ids, 'reviews': approvals, 'plan': plan_record})  # 同输入重复点击合并。
    runtime = runtime_config(workflow.root)  # 登记前验证本机运行环境。
    executable = runtime['report_python'] if stage == 'deliver' else runtime['science_python']  # 各阶段使用正确解释器。
    require(Path(executable).is_file(), '未找到自动化解释器，请核对本机环境配置')  # 失败不留假启动指针。
    with write_lock(workflow.root):  # 一个研究同时只允许运行一项长任务。
        path = workflow.location(study_id) / 'governance' / 'A06_automation_index.json'  # 明确索引位置。
        index = read_json(path) if path.exists() else {'schema_version': 'A06.automation.index.1', 'study_id': study_id}  # 新建研究索引。
        old = job_status(workflow, study_id)  # 看真实进程而不只看文件。
        if old and old['state'] in ('queued', 'running'):  # 长任务不能并发覆盖。
            require(old['request']['identity'] == identity, '本研究还有后台任务运行，请先等待')  # 不启动不同任务争用。
            return old  # 重复点击返回同一任务。
        if old and old['state'] == 'completed' and old['request']['identity'] == identity:  # 完成输入不重复计算。
            return old  # 已有完整交付可直接查看。
        require(parents(workflow, study_id) == {key: parent_ids[key] for key in PARENTS}, '上游已经改变，请刷新')  # 创建前再次校验。
        folder = workflow.location(study_id) / 'runs' / 'A06_PREP' / new_id('job')  # 执行控制资料归入已有模块目录。
        require(review_bindings(workflow, study_id, parent_ids) == approvals, '上游复核已改变，请刷新重试')  # 登记前再校验全部批准。
        request = {'schema_version': JOB_SCHEMA, 'study_id': study_id, 'stage': stage, 'parent_runs': parent_ids, 'parent_review_ids': approvals, 'plan': plan_record, 'identity': identity, 'created_at': now()}  # 请求不可覆盖。
        write_json(folder / 'request.json', request)  # 固定原始请求。
        write_json(folder / 'status.json', {'state': 'queued', 'message': '后台任务已登记', 'updated_at': now()})  # 仅状态文件可变。
        index['job'] = file_record(workflow.location(study_id), folder / 'request.json', 'automation_job')  # 记录当前任务请求。
        write_json(path, index, replace=True)  # 原子保存研究指针。
        environment = dict(os.environ)  # 不改变网页解释器环境。
        environment.pop('PYTHONPATH', None)  # 科学进程使用隔离路径。
        environment.pop('PYTHONHOME', None)  # 避免串解释器。
        command = [executable, '-I', '-S', str(Path(__file__).resolve()), '--root', str(workflow.root), '--request', str(folder / 'request.json')]  # 不拼接shell命令。
        with (folder / 'worker_stdout.txt').open('xb') as stdout, (folder / 'worker_stderr.txt').open('xb') as stderr:  # 日志归入同一任务。
            process = subprocess.Popen(command, cwd=workflow.root, env=environment, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)  # Windows后台不弹窗。
        _PROCESSES[process.pid] = process  # 留存句柄供后续无阻塞回收。
        write_json(folder / 'status.json', {'state': 'queued', 'message': '后台任务已启动，可关闭页面后回来查看', 'pid': process.pid, 'updated_at': now()}, replace=True)  # 返回前留存真实PID。
        write_json(folder / 'launch.json', {'pid': process.pid, 'started_at': now()})  # 工作进程须等启动记录保存，防状态回退。
    return {'state': 'queued', 'pid': process.pid, 'request': request}  # 网页立即响应。


def assert_current(workflow, request):  # 长计算发布前重新核查全部上游。
    current = parents(workflow, request['study_id'])  # 重新验证批准有效。
    manifest = workflow.load(request['study_id'])  # 补充准备及报告父节点。
    require(all(manifest['current'].get(key) == value and workflow.approved(manifest, value) for key, value in request['parent_runs'].items()), '运行期间上游已改变；结果保留为历史草案，不发布')  # 不污染新版。
    require(all(request['parent_runs'][key] == value for key, value in current.items()), '研究科学身份已改变')  # 不跨版本发布。
    require(request.get('parent_review_ids') == review_bindings(workflow, request['study_id'], request['parent_runs']), '运行期间上游复核记录已改变；草案保留，不发布')  # 批准撤回重批也应使旧任务失效。
    if request.get('plan'):  # 方案也属于科学输入。
        selected = current_plan(workflow, request['study_id'])  # 校验当前方案。
        require(selected is not None and selected[1] == request['plan'], '结构方案已更新；本任务不再发布')  # 后台不覆盖新决定。


def run_worker(root, request_path):  # 每个后台进程只执行一个冻结阶段。
    workflow = workflow_instance(root)  # 与网页共用所有科学校验器。
    request_path = Path(request_path).resolve()  # 明确请求归属。
    request = read_json(request_path)  # 后台不接受任意执行代码。
    safe_id(request['study_id'], 'study')  # 校验身份格式。
    require(request_path.is_relative_to(workflow.location(request['study_id'])) and request['schema_version'] == JOB_SCHEMA, '任务位置或版本不正确')  # 不读其他项目请求。
    folder = request_path.parent  # 状态及日志归入任务。
    import time  # 只等父进程完成短启动握手。
    for attempt in range(100):  # 最多等待十秒，不把握手当科学计算。
        if (folder / 'launch.json').exists():  # 父进程已经保存PID。
            break  # 可以更新进度。
        time.sleep(0.1)  # 不阻塞网页进程。
    require((folder / 'launch.json').exists(), '后台启动握手未完成，请查看日志')  # 不争用状态。
    def progress(message):  # 每个阶段写真实进度。
        write_json(folder / 'status.json', {'state': 'running', 'message': message, 'pid': os.getpid(), 'updated_at': now()}, replace=True)  # 状态允许原子更新。
    try:  # 失败留存，不发布部分数据。
        assert_current(workflow, request)  # 执行前校验。
        progress('核查输入与软件环境')  # 页面可见进度。
        from docking_automation_compute import prepare, execute, deliver  # 延迟导入实际科学内核。
        value = {'prepare': prepare, 'execute': execute, 'deliver': deliver}[request['stage']](workflow, request, folder, progress)  # 只执行明确阶段。
        write_json(folder / 'completion.json', dict(value, finished_at=now()))  # 不可变完成凭证。
        write_json(folder / 'status.json', {'state': 'completed', 'message': value['message'], 'pid': os.getpid(), 'result': file_record(workflow.location(request['study_id']), folder / 'completion.json', 'automation_completion'), 'updated_at': now()}, replace=True)  # 完成后才改变状态。
    except Exception as error:  # 不把异常当作空结果。
        drafts = [file_record(workflow.location(request['study_id']), folder / name, 'unpublished_draft') for name in ('preparation.json', 'generic_docking.json') if (folder / name).is_file()]  # 准备不足五项时也能查看实际原因。
        write_json(folder / 'failure.json', {'error': str(error), 'stage': request['stage'], 'drafts': drafts, 'recorded_at': now()})  # 留下失败历史。
        write_json(folder / 'status.json', {'state': 'failed', 'message': str(error), 'drafts': drafts, 'pid': os.getpid(), 'updated_at': now()}, replace=True)  # 页面明确需要处理。
        raise  # 标准错误日志保存堆栈用于维护。


if __name__ == '__main__':  # 内部后台入口，不要求普通用户输入命令。
    sys.stdout.reconfigure(encoding='utf-8')  # 隔离进程不依赖环境变量，中文日志固定UTF-8。
    sys.stderr.reconfigure(encoding='utf-8')  # 异常诊断也能正确显示中文。
    parser = argparse.ArgumentParser(description='ModuleA通用自动化工作进程')  # 提供维护说明。
    parser.add_argument('--root', required=True)  # 项目根明确传入。
    parser.add_argument('--request', required=True)  # 明确请求文件。
    arguments = parser.parse_args()  # 解析固定参数。
    sys.path.insert(0, str(Path(arguments.root) / 'src'))  # -I启动时显式加载本项目。
    request = read_json(arguments.request)  # 根据明确阶段选择依赖环境。
    if request['stage'] == 'deliver':  # 报告进程使用其自有匹配版本的库。
        sys.path.insert(0, str(Path(sys.executable).parent / 'Lib' / 'site-packages'))  # 显式加载固定报告运行库，不混入科学DLL。
    else:  # 科学进程只加载项目锁定包。
        sys.path.insert(0, str(Path(arguments.root) / 'environments' / 'docking_packages'))  # 实际环境继续由activate核验。
    run_worker(Path(arguments.root), arguments.request)  # 执行已登记任务。

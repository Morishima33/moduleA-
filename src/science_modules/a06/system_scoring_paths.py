"""修复后资格的独立评分协议；沿用冻结Top1和逐组合恢复实现。"""
from pathlib import Path
from types import FunctionType

from contracts import fingerprint, require
from storage import read_json, verified_file
from . import system_qualification_paths as qualification, system_scoring_incremental as frozen

VERSION = 'A06.system_scoring_paths.1'
QUALIFICATION = qualification.VERSION


# 只读本次已归档资格，维持现有评分参数、配体/受体、顺序和NA边界。
def derive(root, sid, inputs):
    home = Path(root) / 'studies' / sid
    prep = read_json(verified_file(home, inputs['preparation_run']))
    result = read_json(verified_file(home, inputs['preparation_result']))
    require(prep['module_id'] == 'A06_PREP' and prep['config']['version'] == QUALIFICATION
            and prep['study_id'] == result['study_id'] == sid and prep['run_id'] == result['run_id'],
            '补执行评分要求本研究已归档修订资格')

    def reject(*_):
        require(False, '补执行评分不能回退旧资格')

    qualification.validator(root, reject)(prep, result['summary'], result['tables'], result['anomalies'], result['outcome'])
    request = read_json(verified_file(home, inputs['scoring_request']))
    require(request['schema_version'] == VERSION and request['study_id'] == sid
            and request['human_review_written'] is False and request['request_hash'] == fingerprint(request['request'])
            and request['batch_file'] == prep['batch_file'] and request['request']['expected_preparation_run_id'] == prep['run_id']
            and inputs['system_input_ref'] == prep['inputs']['system_input_ref']
            and inputs['analysis_plan_file'] == prep['inputs']['analysis_plan_file'],
            '补执行评分请求、固定范围或原方案不同')
    fixed = read_json(verified_file(home, inputs['system_input_ref']))['payload']
    fact = read_json(verified_file(home, prep['inputs']['qualification_fact']))
    return {'preparation': prep, 'preparation_result': result, 'input': fixed, 'request': request,
            'config': configuration(prep), 'compounds': fact['compounds'], 'receptors': fact['receptors'],
            'planned_pairs': result['tables']['planned_pairs']}


# 显式复用冻结执行代码，不修改它的模块全局、旧配置或归档。
_scope = dict(vars(frozen), VERSION=VERSION, derive=derive, __file__=__file__)
for _name in ('configuration', 'summary', 'compute', 'validator'):
    _source = getattr(frozen, _name)
    _scope[_name] = FunctionType(_source.__code__, _scope, _name, _source.__defaults__)
configuration = _scope['configuration']
check_tools = frozen.check_tools


# 新版本额外保留所复用执行器的原字节；补执行途中不能切换原实现。
def compute(workflow, sid, run, tools, progress):
    folder = workflow.location(sid) / 'runs' / 'A06' / run['run_id'] / 'system_scoring' / 'code'
    source = Path(frozen.__file__)
    snapshot = folder / source.name
    folder.mkdir(parents=True, exist_ok=True)
    raw = source.read_bytes()
    if snapshot.exists():
        require(snapshot.read_bytes() == raw, '补执行评分所复用的原实现已改变')
    else:
        with snapshot.open('xb') as stream:
            stream.write(raw)
    return _scope['compute'](workflow, sid, run, tools, progress)


# 新旧分派显式；新包除冻结规范复算还必须包含复用执行器的字节证据。
def validator(root, fallback):
    base = _scope['validator'](root, fallback)

    def check(run, summary, tables, anomalies, outcome):
        if run.get('config', {}).get('version') != VERSION:
            return fallback(run, summary, tables, anomalies, outcome)
        base(run, summary, tables, anomalies, outcome)
        home = Path(root) / 'studies' / run['study_id']
        packet = read_json(verified_file(home, tables['scoring_packet'][0]))
        source = Path(frozen.__file__)
        path = f'runs/A06/{run["run_id"]}/system_scoring/code/{source.name}'
        refs = [ref for ref in packet['files'] if ref['path'] == path]
        require(len(refs) == 1 and verified_file(home, refs[0]).read_bytes() == source.read_bytes(),
                '补执行评分缺少实际复用的冻结执行器')
    return check

"""救援结果共享只读绑定核验；API与名称修订复用原研究、批次和原字节检查。"""
from hashlib import sha256
import json

from contracts import fingerprint, require
from storage import read_json, verified_file


def same_file(left, right):
    """角色允许历史别名，路径、长度和SHA必须全部精确相同。"""
    return isinstance(left, dict) and isinstance(right, dict) and all(
        key in left and left[key] == right.get(key) for key in ('path', 'bytes', 'sha256'))


def checked_bytes(home, reference, registered):
    """只读登记原件并校验实际读取字节，避免Path核验后再开文件的竞态。"""
    require(any(same_file(reference, item) for item in registered), '执行证据或构象未登记')
    raw = verified_file(home, reference).read_bytes()
    require(len(raw) == reference['bytes'] and sha256(raw).hexdigest() == reference['sha256'],
            '证据下载读取期间原件校验失败')
    return raw


def bound_batch(home, manifest, run, fixed=None):
    """救援运行不重复保存batch时，沿已登记父准备取同一固定输入，绝不以两个空值当同批。"""
    fixed = fixed if fixed is not None else read_json(verified_file(home, run['inputs']['system_input_ref']))
    batch = fixed.get('binding', {}).get('batch_file')
    require(isinstance(batch, dict) and all(key in batch for key in ('path', 'bytes', 'sha256')),
            '固定输入缺少原批次身份')
    if 'batch_file' in run:
        require(same_file(run['batch_file'], batch), '运行与原固定输入批次不同')
    else:
        prep_id = run.get('parent_runs', {}).get('A06_PREP')
        refs = manifest.get('runs', {}).get(prep_id, {})
        require(prep_id and same_file(refs.get('run_file'), run['inputs'].get('source_preparation_run'))
                and same_file(refs.get('result_file'), run['inputs'].get('source_preparation_result')),
                '救援运行没有绑定已登记父准备')
        prep = read_json(verified_file(home, refs['run_file']))
        require(prep.get('study_id') == run['study_id'] == fixed.get('study_id')
                and prep.get('run_id') == prep_id and prep.get('module_id') == 'A06_PREP'
                and same_file(prep.get('batch_file'), batch)
                and same_file(prep.get('inputs', {}).get('system_input_ref'), run['inputs']['system_input_ref']),
                '救援父准备、固定输入或原批次不同')
    return batch


def load_rescue_result(workflow, manifest, sid, rid):
    """沿原公开Workflow读完整原包；不借用current结果、别批准备或后来替换的名称。"""
    require(rid in manifest.get('runs', {}), '本研究不存在该评分运行')
    home = workflow.location(sid)
    run = workflow.run(manifest, rid)
    result = workflow.result(manifest, rid)
    require(run.get('module_id') == 'A06' and run['config'].get('version') in
            ('A06.system_rescue.1', 'A06.system_rescue.2') and result, '该运行不是已归档补救结果')
    refs = result['tables'].get('scoring_packet', [])
    require(len(refs) == 1, '缺少唯一已登记评分事实包')
    packet = json.loads(checked_bytes(home, refs[0], result['files']))
    fixed = read_json(verified_file(home, run['inputs']['system_input_ref']))
    require(run['study_id'] == result['study_id'] == packet['study_id'] == fixed['study_id'] == sid
            and run['run_id'] == result['run_id'] == packet['run_id'] == rid
            and packet['schema_version'] == run['config']['version']
            and fixed.get('stage') == 'A06_INPUT'
            and same_file(fixed.get('binding', {}).get('batch_file'), bound_batch(home, manifest, run, fixed))
            and fingerprint(packet['source_fixed']) == fingerprint(fixed['payload'])
            and fingerprint(packet['inputs']) == fingerprint(run['inputs'])
            and fingerprint(packet['summary']) == fingerprint(result['summary']),
            '补救证据研究、批次、固定输入或科学协议不同')
    keys = ('compound_id', 'target_id', 'state', 'score', 'quality', 'reason_zh')
    require(fingerprint([{k: p.get(k) for k in keys} for p in packet['pairs']]) ==
            fingerprint([{k: p.get(k) for k in keys} for p in result['tables']['plan_scoring_pairs']]),
            '补救证据与本批完整评分表不同')
    return workflow, manifest, home, run, result, packet

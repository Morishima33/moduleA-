"""沿救援运行的固定父链回读名称依据；不使用后来current、不写研究或科学状态。"""
from copy import deepcopy
import re

from contracts import require, safe_id
from .bounded_evidence import read_verified_json
from .read_evidence import current_evidence
from .rescue_result_read import same_file


def source_basis(workflow, manifest, sid, rid):
    """来源只取已登记的原输入、父准备、A03与A01；可在评分尚未发表时只读预检。"""
    safe_id(sid, 'study');safe_id(rid, 'run')
    require(manifest.get('study_id') == sid, '名称来源不属于本研究')
    home = workflow.location(sid)
    evidence = current_evidence(workflow.root)
    proofs, run_files, run_values = {}, {}, {}

    def read(ref):
        """只解析已核字节，HTTP作用域同时纳入发送前完整SHA复验。"""
        require(isinstance(ref, dict) and all(key in ref for key in ('path', 'bytes', 'sha256')),
                '名称来源缺少原件引用')
        path = ref['path']
        require(path not in proofs or same_file(proofs[path], ref), '名称来源同路径指纹冲突')
        value = evidence.reader.read(home, ref) if evidence else read_verified_json(home, ref)
        proofs[path] = deepcopy(ref)
        return value

    def run(run_id, module):
        """每一级必须确属本研究登记的原运行，不接受目录存在或其他批次同名。"""
        safe_id(run_id, 'run')
        refs = manifest.get('runs', {}).get(run_id)
        require(isinstance(refs, dict) and refs.get('run_file'), '名称父运行未登记')
        value = read(refs['run_file'])
        require(value.get('study_id') == sid and value.get('run_id') == run_id
                and value.get('module_id') == module, '名称来源运行归属不同')
        run_files[run_id] = deepcopy(refs)
        run_values[run_id] = value
        return value

    def result(run_id, module):
        """父结果须完整登记，结果归属与对应运行一致。"""
        ref = manifest['runs'][run_id].get('result_file')
        require(ref, '名称父来源尚未完整归档')
        value = read(ref)
        require(value.get('study_id') == sid and value.get('run_id') == run_id
                and value.get('module_id') == module
                and value.get('artifact_id') == run_values[run_id].get('artifact_id')
                and isinstance(value.get('artifact_id'), str) and bool(value['artifact_id'].strip()),
                '名称来源结果归属不同')
        return value

    score = run(rid, 'A06')
    require(score.get('config', {}).get('version') in ('A06.system_rescue.1', 'A06.system_rescue.2'),
            '名称修订不支持该科学协议')
    fixed_ref = score['inputs']['system_input_ref']
    fixed = read(fixed_ref)
    require(fixed.get('study_id') == sid and fixed.get('stage') == 'A06_INPUT'
            and fixed.get('payload', {}).get('study_id') == sid, '名称固定输入归属不同')
    payload = fixed['payload']
    prep_id = score.get('parent_runs', {}).get('A06_PREP')
    prep = run(prep_id, 'A06_PREP')
    prep_files = manifest['runs'][prep_id]
    require(same_file(prep_files['run_file'], score['inputs'].get('source_preparation_run'))
            and same_file(prep_files.get('result_file'), score['inputs'].get('source_preparation_result'))
            and same_file(prep.get('inputs', {}).get('system_input_ref'), fixed_ref)
            and same_file(prep.get('batch_file'), fixed.get('binding', {}).get('batch_file')),
            '名称准备与本批固定输入或登记不同')
    if 'batch_file' in score:
        require(same_file(score['batch_file'], prep['batch_file']), '名称评分运行批次不同')
    prepared_result = result(prep_id, 'A06_PREP')
    refs = prepared_result.get('tables', {}).get('preparation_packet', [])
    require(len(refs) == 1 and any(same_file(refs[0], ref) for ref in prepared_result.get('files', [])),
            '名称准备事实包缺少唯一原结果登记')
    prepared = read(refs[0])
    require(prepared.get('study_id') == sid and prepared.get('input_key') == payload['input_key']
            and prepared.get('schema_version') == prep['config'].get('version')
            and [r['compound_id'] for r in prepared['compounds']] == [r['compound_id'] for r in payload['compounds']]
            and [r['target_id'] for r in prepared['receptors']] == [r['target_id'] for r in payload['receptors']],
            '名称准备协议、对象或顺序不同')
    a03_id = fixed.get('binding', {}).get('parent_runs', {}).get('A03')
    require(a03_id and prep.get('parent_runs', {}).get('A03') == a03_id
            and fixed['binding'].get('parent_files', {}).get('A03') == manifest['runs'].get(a03_id),
            '名称固定输入与父准备的原A03链不同')
    a03 = run(a03_id, 'A03')
    a03_result = result(a03_id, 'A03')
    a01_id = a03.get('parent_runs', {}).get('A01')
    a01 = run(a01_id, 'A01')
    binding_ref = a01.get('inputs', {}).get('system_source_binding')
    require(any(same_file(binding_ref, ref) for ref in manifest.get('analysis_plan_system_component_source_records', [])),
            '名称原A01来源绑定未登记')
    binding = read(binding_ref)
    require(binding.get('study_id') == sid and binding.get('schema_version') == 'A01.system_source_binding.1',
            '名称原A01来源绑定归属或协议不同')
    raw_refs = {}

    def files(value):
        """仅遍历归档datasets内真实引用；路径字符串或布尔状态不能证明原件。"""
        if isinstance(value, dict):
            if {'path', 'bytes', 'sha256'} <= value.keys():
                yield value
            else:
                for item in value.values():yield from files(item)
        elif isinstance(value, list):
            for item in value:yield from files(item)

    for ref in files(binding.get('datasets')):
        match = re.search(r'(?:^|/)HERB_existing_details/(HBIN[0-9]+)\.json$', ref['path'])
        if match:
            key = match[1]
            require(key not in raw_refs or same_file(raw_refs[key], ref), '原HERB同编号来源指纹冲突')
            raw_refs[key] = ref
    needed = {row['compound_id']: set() for row in prepared['compounds'] if row['state'] == 'NA'}
    for row in a03_result.get('tables', {}).get('formula_evidence', []):
        cid = row.get('compound_id')
        if cid in needed:
            match = re.search(r'(?:^|/)HERB_existing_details/(HBIN[0-9]+)\.json(?::|$)', row.get('source_ref', ''))
            if match:needed[cid].add(match[1])
    herb = {}
    for cid, identifiers in needed.items():
        herb[cid] = []
        for identifier in sorted(identifiers):
            require(identifier in raw_refs, '原A03所指HERB未在同批A01归档')
            ref = raw_refs[identifier];raw = read(ref)
            summary = raw.get('summary')
            require(isinstance(summary, list) and len(summary) == 2
                    and all(isinstance(row, list) for row in summary)
                    and len(summary[0]) == len(summary[1]) and len(set(summary[0])) == len(summary[0]),
                    '原HERB身份摘要缺失、歧义或损坏')
            identity = dict(zip(*summary))
            require(identity.get('Ingredient id') == identifier
                    and isinstance(identity.get('Ingredient name'), str) and identity['Ingredient name'].strip(),
                    '原HERB编号或原名与归档不同')
            herb[cid].append({'id': identifier, 'name': identity['Ingredient name'], 'file': deepcopy(ref)})
    reviews, latest = [], {}
    artifacts = {value.get('artifact_id') for value in (score, prep, a03, a01)} - {None}
    for ref in manifest.get('reviews', []):
        review = read(ref)
        if review.get('run_id') in run_files or review.get('artifact_id') in artifacts:
            owner = run_values.get(review.get('run_id'))
            require(review.get('study_id') == sid and owner
                    and review.get('artifact_id') == owner.get('artifact_id'),
                    '名称来源人工意见的研究、运行或产物归属不同')
            reviews.append(deepcopy(ref));latest[review.get('artifact_id') or review['run_id']] = review
    require(all(review.get('decision') == 'approved' for review in latest.values()),
            '名称来源已有人工暂存或退回，不能继续发表展示修订')
    source = {'study_id': sid, 'run_id': rid, 'input_key': payload['input_key'], 'fixed_input_ref': deepcopy(fixed_ref),
              'run_files': run_files, 'reviews': reviews}
    return {'compounds': deepcopy(payload['compounds']), 'prepared': deepcopy(prepared['compounds']),
            'herb_sources': herb, 'evidence': list(proofs.values()), 'source': source}

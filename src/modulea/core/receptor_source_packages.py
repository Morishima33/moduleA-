"""官方受体响应的显式只读原件导入；不采用旧准备、不生成HTTP成功或科研批准。"""
from copy import deepcopy
from hashlib import sha256
import json
import re
from urllib.parse import unquote, urlsplit

from contracts import fingerprint, require, safe_id
from storage import file_record, now, read_json, verified_file, within, write_json, write_lock

VERSION = 'A06.receptor_source_package.1'
INDEX = 'analysis_plan_receptor_source_packages'
FIELDS = {'request_id', 'expected_preparation_run_id', 'expected_scoring_run_id', 'target_id', 'author', 'note', 'confirmed'}
ARTIFACTS = {'old_manifest', 'old_run', 'old_result', 'metadata', 'model', 'pae', 'metadata_request', 'model_request',
             'pae_request', 'current_checkpoint', 'current_metadata', 'current_metadata_request'}


def _same(left, right):
    """来源别名角色允许不同，路径、长度和实际字节身份必须一致。"""
    return all(left.get(key) == right.get(key) for key in ('path', 'bytes', 'sha256'))


def _bytes(raw, ref):
    """直接核对管理入口提供的原字节；不读取任何客户端路径。"""
    require(isinstance(raw, bytes) and len(raw) == ref.get('bytes') and sha256(raw).hexdigest() == ref.get('sha256'),
            '官方来源原字节、长度或SHA不同')
    return raw


def _json(raw):
    """只解析已传入并核对的JSON原文，不用空值掩盖损坏。"""
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError) as error:
        require(False, '官方来源JSON损坏：' + str(error))


def _refs(value):
    """只收集结构中真实文件索引，路径字符串和computed布尔值不作凭据。"""
    output = []
    if isinstance(value, dict):
        if {'path', 'bytes', 'sha256'} <= value.keys():
            output.append(value)
        else:
            for item in value.values():
                output.extend(_refs(item))
    elif isinstance(value, list):
        for item in value:
            output.extend(_refs(item))
    return output


def _identity(home, manifest, prep_id, target_id):
    """从原准备连接或同批官方HGNC响应提取唯一编号；未解决身份不能导入模型。"""
    prep = read_json(verified_file(home, manifest['runs'][prep_id]['run_file']))
    result = read_json(verified_file(home, manifest['runs'][prep_id]['result_file']))
    fixed_ref = prep['inputs']['system_input_ref']
    fixed = read_json(verified_file(home, fixed_ref))['payload']
    require(target_id in {row['target_id'] for row in fixed['receptors']}, '官方包目标不在本批固定受体范围')
    packet = read_json(verified_file(home, result['tables']['preparation_packet'][0]))
    seen = set()
    while 'connection' not in packet:
        ref = packet.get('source_preparation_fact')
        require(ref and fingerprint(ref) not in seen, '原准备连接引用缺失或循环')
        seen.add(fingerprint(ref))
        packet = read_json(verified_file(home, ref))
    rows = [row for row in packet['connection']['receptors'] if row['target_id'] == target_id]
    require(len(rows) == 1, '原准备目标身份不唯一')
    row = rows[0]
    identifiers = {row['uniprot']} if row.get('uniprot') else set()
    identifiers.update(candidate['spec']['uniprot'] for candidate in row.get('candidates', []) if candidate.get('spec', {}).get('uniprot'))
    if not identifiers:
        for ref in packet.get('files', []):
            if not ref['path'].endswith('_request.json'):
                continue
            request = read_json(verified_file(home, ref))
            url = urlsplit(request.get('url', ''))
            if (url.scheme, url.hostname, unquote(url.path)) != ('https', 'rest.genenames.org', '/fetch/hgnc_id/' + target_id):
                continue
            # 历史失败原样保留，只从实际成功的同稳定编号原响应核对身份。
            if request.get('state') != 'success' or request.get('status') != 200:
                continue
            docs = read_json(verified_file(home, request['file'])).get('response', {}).get('docs', [])
            require(len(docs) == 1 and docs[0].get('hgnc_id') == target_id and docs[0].get('status') == 'Approved'
                    and len(docs[0].get('uniprot_ids', [])) == 1, '原HGNC未形成唯一已批准蛋白身份')
            identifiers.add(docs[0]['uniprot_ids'][0])
    require(len(identifiers) == 1, '本目标尚无唯一稳定UniProt身份，官方来源包不能替代身份核定')
    return next(iter(identifiers)), fixed_ref


def _validate(home, manifest, body, staging, artifacts):
    """重建旧来源登记链和本批精确元数据；不采用旧准备或旧评分作新科学证据。"""
    require(isinstance(artifacts, dict) and set(artifacts) == ARTIFACTS, '来源包原字节项目不完整或包含未授权文件')
    require(isinstance(staging, dict), '来源包暂存说明错误')
    target = staging['target']
    require(body['target_id'] == target['hgnc_id'], '来源包目标稳定编号不同')
    uniprot, fixed_ref = _identity(home, manifest, body['expected_preparation_run_id'], body['target_id'])
    require(uniprot == target['uniprot'], '来源包UniProt与本批唯一身份不同')
    membership = staging['source_archive_membership']
    for key, name in (('old_manifest', 'manifest'), ('old_run', 'run'), ('old_result', 'result')):
        _bytes(artifacts[key], membership[name])
    old_manifest, old_run, old_result = (_json(artifacts[key]) for key in ('old_manifest', 'old_run', 'old_result'))
    old_sid, old_id = membership['study_id'], membership['run_id']
    safe_id(old_sid, 'study')
    safe_id(old_id, 'run')
    require(old_manifest['study_id'] == old_run['study_id'] == old_result['study_id'] == old_sid
            and old_run['run_id'] == old_result['run_id'] == old_id
            and old_run['module_id'] == old_result['module_id'] == 'A06'
            and old_result.get('outcome') == 'success'
            and old_run.get('artifact_id') == old_result.get('artifact_id'), '旧官方来源研究、运行或结果归属不同')
    old_record = old_manifest['runs'][old_id]
    require(old_record == membership['run_record_in_manifest'], '旧运行不属于原索引登记')
    _bytes(artifacts['old_run'], old_record['run_file'])
    _bytes(artifacts['old_result'], old_record['result_file'])
    require(len(staging['sources']) == 3 and {row['kind'] for row in staging['sources']} == {'metadata', 'model', 'pae'},
            '官方来源包只允许元数据、模型CIF与PAE三件原响应')
    by_kind = {row['kind']: row for row in staging['sources']}
    metadata = _json(artifacts['metadata'])
    require(isinstance(metadata, list), '官方模型元数据不是条目列表')
    exact_models = [row for row in metadata if row.get('uniprotAccession') == uniprot]
    require(len(exact_models) == 1, '官方模型元数据不是目标唯一条目')
    model = exact_models[0]
    require(model.get('entryId') == target['model_id'] and model.get('latestVersion') == target['model_version']
            and model.get('uniprotStart') == target['sequence_start'] and model.get('uniprotEnd') == target['sequence_end'],
            '官方模型版本、序列范围或条目不同')
    expected_urls = {'metadata': 'https://alphafold.ebi.ac.uk/api/prediction/' + uniprot,
                     'model': model['cifUrl'], 'pae': model['paeDocUrl']}
    responses = []
    for kind, source in by_kind.items():
        require(source['url'] == expected_urls[kind] and urlsplit(source['url']).scheme == 'https'
                and urlsplit(source['url']).hostname == 'alphafold.ebi.ac.uk'
                and not urlsplit(source['url']).username and not urlsplit(source['url']).password,
                '来源包URL不是本模型精确官方地址')
        _bytes(artifacts[kind], source['staged_file'])
        _bytes(artifacts[kind], source['original_ref'])
        require(any(_same(source['original_ref'], ref) for ref in old_result['files']), '官方响应未登记在旧结果')
        request_ref = source['original_request_registered_in_result_as']
        require(any(_same(request_ref, ref) for ref in old_result['files']), '旧下载记录未登记在旧结果')
        _bytes(artifacts[kind + '_request'], request_ref)
        request = _json(artifacts[kind + '_request'])
        require(request.get('state') == 'success' and request.get('status') == 200
                and request.get('url') == source['url'] and _same(request.get('file', {}), source['original_ref'])
                and request.get('created_at') == source['original_downloaded_at'], '原下载状态、地址、文件或日期不同')
        responses.append({'kind': kind, 'url': source['url'], 'original_downloaded_at': request['created_at'],
                          'original_status': 200, 'original_file': deepcopy(source['original_ref']),
                          'original_request_ref': deepcopy(request_ref)})
    comparison = staging['current_v1_api_comparison']
    checkpoint_ref = comparison['checkpoint_ref']
    require(checkpoint_ref in manifest.get('analysis_plan_receptor_rescue_checkpoints', []), '当前模型元数据检查点未登记')
    _bytes(artifacts['current_checkpoint'], checkpoint_ref)
    require(verified_file(home, checkpoint_ref).read_bytes() == artifacts['current_checkpoint'], '当前检查点原件不同')
    checkpoint = _json(artifacts['current_checkpoint'])
    metadata_ref = comparison['metadata_ref']
    require(checkpoint['study_id'] == manifest['study_id'] and checkpoint['run_id'] == comparison['run_id']
            and checkpoint['key'] == 'receptor_' + body['target_id'].replace(':', '_')
            and any(_same(metadata_ref, ref) for ref in checkpoint['files']), '当前目标元数据不属于本对象检查点')
    baseline = read_json(verified_file(home, manifest['runs'][body['expected_scoring_run_id']]['run_file']))
    require(comparison['run_id'] == body['expected_scoring_run_id']
            or (baseline['config'].get('version') == 'A06.system_scoring_paths.1'
                and read_json(verified_file(home, manifest['runs'][comparison['run_id']]['run_file']))['inputs']['source_scoring_run']
                == manifest['runs'][body['expected_scoring_run_id']]['run_file']), '当前元数据不是本轮原评分来源')
    _bytes(artifacts['current_metadata'], metadata_ref)
    require(verified_file(home, metadata_ref).read_bytes() == artifacts['current_metadata'] == artifacts['metadata'],
            '归档模型元数据与本批实际官方响应不是同一字节')
    current_request = _json(artifacts['current_metadata_request'])
    current_request_refs = [ref for ref in checkpoint['files'] if ref['sha256'] == sha256(artifacts['current_metadata_request']).hexdigest()
                            and ref['bytes'] == len(artifacts['current_metadata_request'])]
    require(len(current_request_refs) == 1 and current_request.get('state') == 'success'
            and current_request.get('status') == 200 and current_request.get('url') == expected_urls['metadata']
            and _same(current_request.get('file', {}), metadata_ref), '本批实际元数据请求未登记或不同')
    verified_file(home, current_request_refs[0])
    return {'target_id': body['target_id'], 'uniprot': uniprot, 'model_id': target['model_id'],
            'model_version': target['model_version'], 'sequence_start': target['sequence_start'], 'sequence_end': target['sequence_end'],
            'source_study_id': old_sid, 'source_run_id': old_id, 'responses': responses,
            'system_input_ref': fixed_ref, 'current_metadata_ref': metadata_ref, 'current_checkpoint_ref': checkpoint_ref}


def read_record(home, manifest, ref):
    """公开读取只认本研究登记并逐件验SHA，Fetcher只使用精确映射而不扫描目录。"""
    require(ref in manifest.get(INDEX, []), '官方受体来源包未登记')
    value = read_json(verified_file(home, ref))
    require(value['schema_version'] == VERSION and value['study_id'] == manifest['study_id']
            and value['human_review_written'] is False and value['new_http_request_performed'] is False
            and value['request_hash'] == fingerprint(value['request']), '官方来源包归属或明确请求不同')
    for item in value['files']:
        verified_file(home, item)
    artifacts = {key: verified_file(home, source).read_bytes() for key, source in value['artifact_files'].items()}
    staging = read_json(verified_file(home, value['staging_file']))
    require(value['staging_hash'] == fingerprint(staging)
            and sorted(fingerprint(ref) for ref in value['files'])
            == sorted(fingerprint(ref) for ref in [value['staging_file'], *value['artifact_files'].values()]),
            '官方来源包文件索引或暂存指纹不同')
    expected = _validate(home, manifest, value['request'], staging, artifacts)
    require(value['validated'] == expected and value['source_preparation_files'] == manifest['runs'][value['request']['expected_preparation_run_id']]
            and value['source_scoring_files'] == manifest['runs'][value['request']['expected_scoring_run_id']],
            '官方来源包原运行、模型或证明发生变化')
    responses = [dict(row, file=value['artifact_files'][row['kind']],
                      original_request=value['artifact_files'][row['kind'] + '_request']) for row in expected['responses']]
    require(value['responses'] == responses, '官方来源映射、原日期或状态不同')
    return value


def for_baseline(home, manifest, prep_id, score_id):
    """同一明确基线每个目标只采用最后登记包；其他研究或基线不能混用。"""
    selected = {}
    for ref in manifest.get(INDEX, []):
        value = read_record(home, manifest, ref)
        body = value['request']
        if body['expected_preparation_run_id'] == prep_id and body['expected_scoring_run_id'] == score_id:
            selected[body['target_id']] = ref
    return [deepcopy(selected[key]) for key in sorted(selected)]


def url_mapping(home, manifest, refs):
    """返回本轮显式包的精确URL到已校验原响应引用，冲突不得择优。"""
    output = {}
    for ref in refs:
        value = read_record(home, manifest, ref)
        for response in value['responses']:
            prior = output.get(response['url'])
            require(prior is None or prior == response['file'], '本轮官方来源包对同URL存在不同原字节')
            output[response['url']] = deepcopy(response['file'])
    return output


def _registration_source(workflow, manifest, body):
    """原评分可由同源未完成第一轮占据当前指针；其他历史或第二轮没有此例外。"""
    from . import system_receptor_rescue as first
    prep_id, score_id = body['expected_preparation_run_id'], body['expected_scoring_run_id']
    require(not manifest.get('trashed') and manifest['current'].get('A06_PREP') == prep_id
            and workflow.approved(manifest, prep_id), '官方来源登记的原准备已改变或尚未批准')
    current_id = manifest['current'].get('A06')
    require(current_id, '官方来源登记尚无当前评分')
    if current_id != score_id:
        run = workflow.run(manifest, current_id)
        require(run['config'].get('version') == first.VERSION
                and not manifest['runs'][current_id].get('result_file') and workflow.active(manifest, current_id),
                '只有同来源未完成第一轮可以登记原评分的补充来源')
        request = first._read_request(workflow, manifest, run['inputs']['rescue_request'])
        require(request['request']['expected_preparation_run_id'] == prep_id
                and request['request']['expected_scoring_run_id'] == score_id
                and request['binding'] == run['inputs']['source_binding']
                and run['parent_runs'] == {'A06_PREP': prep_id}
                and run['inputs']['source_preparation_run'] == manifest['runs'][prep_id]['run_file']
                and run['inputs']['source_preparation_result'] == manifest['runs'][prep_id]['result_file']
                and run['inputs']['source_scoring_run'] == manifest['runs'][score_id]['run_file']
                and run['inputs']['source_scoring_result'] == manifest['runs'][score_id]['result_file']
                and workflow.run(manifest, score_id)['config'].get('version') == first.SCORING_VERSION,
                '未完成第一轮与本包原准备、原评分或明确请求不同')
        review = workflow.latest_review(manifest, run['artifact_id'])
        require(not review or review['decision'] == 'approved', '未完成第一轮已有人工暂存或退回')
    else:
        require(workflow.active(manifest, score_id), '官方来源登记的原评分已失效')
    score = workflow.result(manifest, score_id)
    require(score and score['outcome'] == 'success', '原评分尚未完整发布，不能登记下一轮来源包')


def register(workflow, sid, body, staging, artifacts):
    """管理CLI显式传字节，锁内核验与复制；不提供网页路径或采用旧准备评分。"""
    require(isinstance(body, dict) and set(body) == FIELDS and body['confirmed'] is True, '官方来源登记字段或明确确认错误')
    safe_id(body['request_id'], 'sourcepkg')
    for key in ('expected_preparation_run_id', 'expected_scoring_run_id'):
        safe_id(body[key], 'run')
    require(isinstance(body['target_id'], str) and re.fullmatch(r'HGNC:[0-9]+', body['target_id'])
            and all(isinstance(body[key], str) and 0 < len(body[key].strip()) <= 2000 for key in ('author', 'note')),
            '请填写来源目标、登记人及依据')
    with write_lock(workflow.root):
        manifest = workflow.load(sid)
        home = workflow.location(sid)
        for ref in manifest.get(INDEX, []):
            value = read_record(home, manifest, ref)
            if value['request']['request_id'] == body['request_id']:
                require(value['request'] == body and value['staging_hash'] == fingerprint(staging)
                        and all(sha256(artifacts[key]).hexdigest() == source['sha256'] for key, source in value['artifact_files'].items()),
                        '来源包请求编号已用于不同原字节或内容')
                return ref
        _registration_source(workflow, manifest, body)
        for rid in (body['expected_preparation_run_id'], body['expected_scoring_run_id']):
            review = workflow.latest_review(manifest, workflow.run(manifest, rid)['artifact_id'])
            require(not review or review['decision'] == 'approved', '来源已人工暂存或退回')
        validated = _validate(home, manifest, body, staging, artifacts)
        folder = within(home, 'decisions/receptor_source_packages/' + body['request_id'])
        saved = {}
        for key, raw in artifacts.items():
            suffix = '.cif' if key == 'model' else '.json'
            path = folder / 'originals' / (key + suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                require(path.read_bytes() == raw, '来源包未完成原件已有不同字节')
            else:
                with path.open('xb') as stream:
                    stream.write(raw)
            saved[key] = file_record(home, path, 'official_receptor_source' if key in ('metadata', 'model', 'pae') else 'official_receptor_source_provenance')
        stage_path = folder / 'staging.json'
        if stage_path.exists():
            require(read_json(stage_path) == staging, '来源包暂存说明不同')
        else:
            write_json(stage_path, staging)
        stage_ref = file_record(home, stage_path, 'official_receptor_source_staging')
        responses = [dict(row, file=saved[row['kind']], original_request=saved[row['kind'] + '_request'])
                     for row in validated['responses']]
        record = {'schema_version': VERSION, 'study_id': sid, 'request': deepcopy(body), 'request_hash': fingerprint(body),
                  'staging_file': stage_ref, 'staging_hash': fingerprint(staging), 'artifact_files': saved,
                  'validated': validated, 'responses': responses, 'files': [stage_ref, *saved.values()],
                  'source_preparation_files': deepcopy(manifest['runs'][body['expected_preparation_run_id']]),
                  'source_scoring_files': deepcopy(manifest['runs'][body['expected_scoring_run_id']]),
                  'human_review_written': False, 'new_http_request_performed': False, 'created_at': now()}
        path = folder / 'package.json'
        if path.exists():
            old = read_json(path)
            require(all(old.get(key) == record[key] for key in record if key != 'created_at'), '原官方来源包内容不同')
            record = old
        else:
            write_json(path, record)
        ref = file_record(home, path, 'official_receptor_source_package')
        manifest.setdefault(INDEX, []).append(ref)
        workflow.save(manifest)
        return ref

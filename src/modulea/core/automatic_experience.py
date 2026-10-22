"""自动流程接续：技术准备状态、按需证据和独立图表修订，不改变既有评分。"""
from copy import deepcopy
from pathlib import Path

from contracts import require, fingerprint
from storage import read_json, verified_file, file_record, write_json, write_lock, new_id, now
from .automatic_coverage import AutomaticCoverageWorkflow
from .automatic_docking import AutomaticDockingWorkflow
from .docking_artifacts import pair_key
from types import FunctionType
from science_modules.a06 import reference_rules

VERSIONS = ('A06.automatic.1', 'A06.automatic.2', 'A06.automatic.3')


def automatic_names(workflow, manifest, packet, a03):
    """同A03已核验中文优先，旧自动包中英文占位不能覆盖人工名称证据。"""
    from .compound_names import compound_names
    names = compound_names(workflow, manifest, a03)
    for c in packet['compounds']:
        row = names.setdefault(c['compound_id'], {})
        row.setdefault('evidence', [])
        row.setdefault('name_en', c.get('name_en') or c.get('name') or c['compound_id'])
        if not row.get('name_zh'):
            row['name_zh'] = c.get('name_zh', '')
    return names


def is_automatic(workflow, manifest, run_id):
    """只按归档协议识别自动结果，不根据研究名或名单推断。"""
    return bool(run_id and workflow.run(manifest, run_id).get('config', {}).get('schema_version') in VERSIONS)


def batch_for(workflow, manifest, identity):
    """批次必须登记于本研究，结果和运行也必须属于同一个研究。"""
    batch = next((r for r in manifest.get('automatic_batches', []) if r['id'] == identity), None)
    require(batch is not None, '本研究不存在该自动批次')
    if batch.get('run_id'):
        run = workflow.run(manifest, batch['run_id'])
        require(run['study_id'] == manifest['study_id'] and is_automatic(workflow, manifest, batch['run_id']), '自动批次运行归属不一致')
    return batch


def packet_for(workflow, manifest, batch):
    """只在展开矩阵或证据时读取完整包，核验归档指纹。"""
    require(batch.get('packet'), '本批尚未形成完整结果')
    packet = read_json(verified_file(workflow.location(manifest['study_id']), batch['packet']))
    require(packet['study_id'] == manifest['study_id'] and packet['run_id'] == batch['run_id'] and packet['id'] == batch['id'], '自动结果归属不一致')
    return packet


def status_text(pair):
    """程序退出失败与姿势拒绝分开；归档原状态及原始原因均保留。"""
    if pair['state'] == 'completed':
        return '完成'
    if pair['state'] == 'NA':
        return '准备未通过'
    regions = pair.get('regions', [])
    if regions and all(r.get('returncode') == 0 for r in regions):
        return '姿势质控未通过'
    return '计算失败'


def page_rows(rows, page=1, size=20, query=''):
    """分页只限制传输，不改变完整归档或检索范围。"""
    require(1 <= page and 1 <= size <= 100, '分页范围不合法')
    if query:
        needle = query.casefold()
        rows = [r for r in rows if needle in str(r).casefold()]
    return {'items': rows[(page-1)*size:page*size], 'total': len(rows), 'page': page, 'size': size}


def file_rows(sid, batch):
    """只制作分页文件索引；下载时仍逐文件核验。"""
    return [{'name': Path(r['path']).name, 'path': r['path'], 'role': r.get('role', ''),
             'url': f'/api/v1/studies/{sid}/automatic_docking/{batch["id"]}/files/{i}'} for i, r in enumerate(batch.get('files', []))]


def pairs_page(workflow, manifest, batch, page=1, size=20, query=''):
    """列表只读小结果表；完整执行过程在单组合证据端点中读取。"""
    result = workflow.result(manifest, batch['run_id'])
    if not result:
        return page_rows([], page, size, query)
    run = workflow.run(manifest, batch['run_id'])
    selected = workflow.result(manifest, run['parent_runs']['A03_SELECT'])['tables']['selected']
    names = {r['compound_id']: r.get('name_zh') or r.get('name') or r.get('compound_name') or r['compound_id'] for r in selected}
    symbols = {r['HGNC']: r['基因'] for r in result['tables']['receptor_setup']}
    rows = []
    for pair in result['tables']['pairs']:
        # 旧摘要表没有执行区域，失败细分由证据端点提供，不猜测returncode。
        label = '完成' if pair['state'] == 'completed' else '准备未通过' if pair['state'] == 'NA' else '计算或姿势质控未通过'
        rows.append(dict(pair, pair_key=pair_key(pair['compound_id'], pair['target_id']), compound_name=names.get(pair['compound_id'], pair['compound_id']), symbol=symbols[pair['target_id']], status_zh=label))
    response = page_rows(rows, page, size, query)
    if any(r['state'] == 'failed' for r in response['items']):
        packet = packet_for(workflow, manifest, batch)
        original = {(r['compound_id'], r['target_id']): r for r in packet['pairs']}
        for row in response['items']:
            if row['state'] == 'failed':
                actual = original[row['compound_id'], row['target_id']]
                row['status_zh'] = status_text(actual)
                row['reason_zh'] = '；'.join(dict.fromkeys(r.get('reason_zh', '') for r in actual.get('regions', []) if r.get('reason_zh'))) or row['reason_zh']
    return response


def pair_evidence(workflow, manifest, batch, key):
    """仅返回选中一组的结构/位点/执行依据及相关索引，不展开其他79组。"""
    packet = packet_for(workflow, manifest, batch)
    pair = next((r for r in packet['pairs'] if pair_key(r['compound_id'], r['target_id']) == key), None)
    require(pair is not None, '本批不存在该组合')
    receptor = next(r for r in packet['receptors'] if r['target_id'] == pair['target_id'])
    compound = next(r for r in packet['compounds'] if r['compound_id'] == pair['compound_id'])
    result = dict(pair, pair_key=key, compound_name=compound.get('name_zh') or compound.get('name') or pair['compound_id'], symbol=receptor['symbol'], status_zh=status_text(pair),
                  trace={'candidate': receptor.get('selected_candidate'), 'quality_evidence': receptor.get('evidence'), 'ligand': compound, 'attempts': receptor.get('attempts', []), 'policy': packet['policy']})
    refs = set()
    def collect(value):
        """证据链接只来自当前组合中实际引用的归档记录。"""
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                refs.add(value['path'])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(result)
    result['evidence_files'] = [r for r in file_rows(manifest['study_id'], batch) if r['path'] in refs]
    return result


class AutomaticExperienceWorkflow(AutomaticCoverageWorkflow):
    """沿用旧授权和评分；新增展示修订及自动协议报告的明确接入点。"""

    def validate_extended_scope(self, sid, manifest=None):
        from .extended_scope import require_ready
        return require_ready(self, manifest or self.load(sid))

    def automatic_binding(self, sid, expected=None, manifest=None):
        """新连接只使用第三版指纹，旧一、二版运行仍由各自冻结_active校验。"""
        manifest = manifest or self.load(sid)
        with self.handoff_read_cache():
            data = reference_rules.binding(self, manifest)
        require(expected is None or expected == fingerprint(data), '对接输入或复核已改变，请刷新')
        return manifest, data

    def validate_automatic_request(self, sid, payload, manifest=None):
        """第三版明确携带共晶选择；不能把旧授权静默升级。"""
        require(isinstance(payload, dict) and 'reference_choices' in payload, '第三版执行须明确提交共晶核定清单，可为空')
        original = {k: v for k, v in payload.items() if k != 'reference_choices'}
        method = _versioned('validate_automatic_request')
        result = method(self, sid, original, manifest)
        manifest, _, record = result
        # 已登记执行仍按原授权追溯；新执行不得把默认五项当完整扩展范围。
        if not self.automatic_record(manifest, payload['request_id']):
            self.validate_extended_scope(sid, manifest)
        connection = read_json(verified_file(self.location(sid), record['packet']))
        from science_modules.a06.reference_candidates import validate_choices
        validate_choices(self.location(sid), connection, payload['reference_choices'])
        return result

    def _active(self, manifest, run_id):
        """旧协议使用旧绑定；第三版额外检查本批新连接及新授权原件。"""
        if not super()._active(manifest, run_id):
            return False
        run = self.run(manifest, run_id)
        if run.get('config', {}).get('schema_version') == reference_rules.VERSION:
            try:
                _, bound = self.automatic_binding(manifest['study_id'], manifest=manifest)
                connection = self.current_automatic_connection(manifest, fingerprint(bound))
                for key in ('automatic_authorization', 'automatic_connection'):
                    verified_file(self.location(manifest['study_id']), run['inputs'][key])
                return bool(connection and connection['packet'] == run['inputs']['automatic_connection'])
            except ValueError:
                return False
        return True

    def _begin(self, manifest, module, inputs, config, reason):
        """只对专用新报告版本绕过旧“不支持报告”提示，其余旧分支保持。"""
        if module == 'A07' and config.get('schema_version') in ('A07.report.config.25', 'A07.report.config.26'):
            require(is_automatic(self, manifest, manifest['current'].get('A06')), '新报告必须使用同批自动结果')
            if config.get('schema_version') == 'A07.report.config.26':
                a00 = self.result(manifest, manifest['current']['A00'])['summary']
                require(a00.get('study_type') == 'single_compound_literature_comparison', '文献报告须由本研究登记明确启用')
            # 跳过两个旧自动协议的冻结报告阻断，继续走原Workflow依赖、批准和写锁检查。
            return super(AutomaticDockingWorkflow, self)._begin(manifest, module, inputs, config, reason)
        return super()._begin(manifest, module, inputs, config, reason)

    def view(self, study_id):
        """技术状态取同批真实执行记录，不伪造准备科研批准。"""
        view = super().view(study_id)
        manifest = view['manifest']
        rid = manifest['current'].get('A06')
        if is_automatic(self, manifest, rid) and self.active(manifest, rid):
            batch = next((r for r in manifest.get('automatic_batches', []) if r.get('run_id') == rid), None)
            if batch and batch['state'] in ('authorized', 'running', 'completed'):
                prep = next(r for r in view['modules'] if r['module_id'] == 'A06_PREP')
                prep['state'] = 'prepared' if batch['state'] == 'completed' else 'execution_confirmed'
                prep['automatic_preparation'] = {'batch_id': batch['id'], 'run_id': rid, 'approved': False}
        return view

    def automatic_display_source(self, sid, payload):
        """明确版本绑定；展示任务不能借用历史批次或客户端文件路径。"""
        require(set(payload) == {'expected_a06', 'batch_id', 'compound_ids', 'target_ids'}, '展示请求字段不合法')
        m = self.load(sid)
        require(not m.get('trashed'), '回收站中只读')
        require(m['current'].get('A06') == payload['expected_a06'], 'A06已改变，请刷新')
        batch = batch_for(self, m, payload['batch_id'])
        require(batch.get('run_id') == payload['expected_a06'] and batch['state'] == 'completed' and self.active(m, batch['run_id']), '本批结果未完成或已失效')
        for key in ('compound_ids', 'target_ids'):
            require(isinstance(payload[key], list) and all(isinstance(v, str) for v in payload[key]) and len(payload[key]) == len(set(payload[key])), '展示名单不能重复或含未知字段')
        packet = packet_for(self, m, batch)
        for key, rows, field in (('compound_ids', packet['compounds'], 'compound_id'), ('target_ids', packet['receptors'], 'target_id')):
            require(payload[key] and set(payload[key]) <= {r[field] for r in rows}, '展示名单为空或包含未知对象')
        return m, batch

    def publish_automatic_display(self, sid, payload, view_record, files):
        """仅追加图表记录，current、评分、reviews保持原样。"""
        with write_lock(self.root):
            manifest, batch = self.automatic_display_source(sid, payload)
            root = self.location(sid)
            for record in [view_record, *files]:
                verified_file(root, record)
            from science_modules.a06.automatic_exports import build_view
            packet = packet_for(self, manifest, batch)
            a03 = self.run(manifest, batch['run_id'])['parent_runs']['A03']
            expected = build_view(packet, automatic_names(self, manifest, packet, a03), payload['compound_ids'], payload['target_ids'])
            require(read_json(verified_file(root, view_record)) == expected, '展示评分、身份或范围不符合本批原始结果')
            row = {'id': new_id('display'), 'a06_run': batch['run_id'], 'batch_id': batch['id'], 'packet': batch['packet'], 'selection': deepcopy(payload), 'view': view_record, 'files': files, 'created_at': now()}
            manifest.setdefault('automatic_displays', []).append(row)
            self.save(manifest)
            return row


def automatic_context(workflow, manifest, historical=False, busy=False):
    """轻量页面上下文；完整证据与矩阵由用户打开后读取。"""
    if historical:
        return None
    from science_modules.a06.reference_rules import VERSION, POLICY, SUMMARY, DETAILS
    sid = manifest['study_id']
    data = {'enabled': False, 'disabled_reason_zh': '', 'expected_binding': '', 'expected_connection_id': None, 'expected_a06': manifest['current'].get('A06'), 'counts': {'compounds': 0, 'receptors': 0, 'pairs': 0},
            'policy': {'version': VERSION, 'summary_zh': SUMMARY, 'details_zh': DETAILS}, 'connection': None, 'latest': None, 'migration_note_zh': ''}
    try:
        _, bound = workflow.automatic_binding(sid, manifest=manifest)
        key = fingerprint(bound)
        data['expected_binding'] = key
        selected = workflow.result(manifest, bound['runs']['A03_SELECT'])['tables']['selected']
        from science_modules.a06.candidates import build
        targets = build(workflow.result(manifest, bound['runs']['A04'])['tables'])['degree_top15']
        data['counts'] = {'compounds': len(selected), 'receptors': len(targets), 'pairs': len(selected)*len(targets)}
        connection = workflow.current_automatic_connection(manifest, key)
        if connection:
            packet = read_json(verified_file(workflow.location(sid), connection['packet']))
            data['expected_connection_id'] = connection['id']
            data['connection'] = {k: packet.get(k) for k in ('id', 'created_at', 'summary', 'exceptions', 'objects', 'compound_resolution_version')}
            data['connection']['files'] = []
            data['connection']['reference_candidates'] = packet.get('reference_candidates', [])
        batches = manifest.get('automatic_batches', [])
        rid = manifest['current'].get('A06')
        batch = next((b for b in reversed(batches) if b.get('run_id') == rid), None)
        if batch:
            latest = {k: batch.get(k) for k in ('id', 'state', 'run_id', 'summary', 'error_zh')}
            latest.update(pairs=[], files=[], file_count=len(batch.get('files', [])), pairs_url=f'/api/v1/studies/{sid}/automatic_docking/{batch["id"]}/pairs', matrix_url=f'/api/v1/studies/{sid}/automatic_docking/{batch["id"]}/matrix')
            display = next((r for r in reversed(manifest.get('automatic_displays', [])) if r['batch_id'] == batch['id']), None)
            latest['display_id'] = display['id'] if display else None
            if rid and not workflow.active(manifest, rid):
                latest.update(state='stale', error_zh='上游或连接版本已改变，旧批次只供追溯')
            elif latest['state'] == 'running' and not busy:
                latest['state'] = 'interrupted'
            data['latest'] = latest
        from .extended_scope import context as scope_context
        data['scope'] = scope_context(workflow, manifest)
        data['enabled'] = not busy and not manifest.get('trashed') and data['scope']['ready']
        data['disabled_reason_zh'] = '请等待当前研究后台任务结束' if busy else '回收站中只读' if manifest.get('trashed') else ''
        if not data['disabled_reason_zh'] and not data['scope']['ready']:
            data['disabled_reason_zh'] = data['scope']['reason_zh']
    except (ValueError, KeyError) as error:
        data['disabled_reason_zh'] = str(error)
    return data


def historical_context(workflow, manifest, run):
    """历史只读同批结果和附件，不暴露连接或执行授权入口。"""
    batch = next((b for b in manifest.get('automatic_batches', []) if b.get('run_id') == run['run_id']), None)
    if not batch:
        return None
    summary = batch.get('summary') or {}
    latest = {k: batch.get(k) for k in ('id', 'state', 'run_id', 'summary', 'error_zh')}
    latest.update(pairs=[], files=[], file_count=len(batch.get('files', [])))
    return {'enabled': False, 'disabled_reason_zh': '历史版本只读', 'expected_binding': batch['binding'], 'expected_connection_id': None, 'expected_a06': run['run_id'],
            'counts': {'compounds': summary.get('成分数', 0), 'receptors': summary.get('受体数', 0), 'pairs': summary.get('计划组合数', 0)},
            'policy': {'version': run['config']['schema_version'], 'summary_zh': '历史版本只读', 'details_zh': []}, 'connection': None, 'latest': latest}


def _versioned(name):
    """复用冻结Workflow存储及锁语义，仅为新协议绑定新版本常量。"""
    function = getattr(AutomaticCoverageWorkflow, name)
    return FunctionType(function.__code__, dict(function.__globals__, VERSION=reference_rules.VERSION, POLICY=reference_rules.POLICY), function.__name__, function.__defaults__, function.__closure__)


# 旧类及其模块全局不变，新类的连接/授权/执行/发布单独归档第三版。
for _method in ('save_automatic_connection', 'authorize_automatic', 'begin_automatic', 'finish_automatic'):
    setattr(AutomaticExperienceWorkflow, _method, _versioned(_method))

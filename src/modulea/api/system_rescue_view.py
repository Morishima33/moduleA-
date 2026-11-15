"""救援结果页仅读取本运行固定输入、评分事实包及已登记附件；GET不创建任务。"""
from copy import deepcopy
from pathlib import Path

from contracts import fingerprint, require
from storage import read_json, verified_file
from science_modules.a06.system_rescue_display import build_view, SCIENCE_VERSION, REVIEW_NOTE, STATE_ZH
from ..presenters.base import Parts, clean, focus, kpi, param, table
from .rescue_evidence import evidence_url, focus_matrix

COUNTS = [('rescue_target_count', '本轮尝试受体'), ('rescued_receptors', '补救后准备可用'),
          ('reused_scored_pairs', '沿用原有效评分'), ('new_scored_pairs', '本轮新增有效评分'),
          ('scored_pairs', '合并有效评分'), ('na_pairs', '仍为准备NA'), ('failed_pairs', '评分失败'),
          ('compound_count', '固定成分记录'), ('receptor_count', '固定受体'), ('pair_count', '完整组合')]
COUNTS_V2 = [('rescue_target_count', '本轮尝试受体'), ('rescued_receptors', '本轮新增准备可用'),
             ('baseline_scored_pairs', '基线有效评分'), ('new_scored_pairs', '本轮新增有效评分'),
             ('cumulative_rescue_scored_pairs', '累计补救有效评分'), ('scored_pairs', '合并有效评分'),
             ('na_pairs', '仍为准备NA'), ('failed_pairs', '评分失败'),
             ('cumulative_rescue_target_count', '最初补救范围'), ('cumulative_rescued_receptors', '累计补救准备可用'),
             ('ready_receptors_total', '当前准备可用受体'), ('compound_count', '固定成分记录'),
             ('reused_prepared_receptors', '复用既有准备'),
             ('receptor_count', '固定受体'), ('pair_count', '完整组合')]
OBSOLETE = ('automatic_docking', 'docking_trial', 'docking_coverage', 'docking_preparation', 'docking_candidates',
            'docking_review', 'docking_artifacts', 'reference_qualification', 'scoring_readiness', 'review_packet',
            'review_gate', 'reviewable_preparation', 'plan_scoring', 'plan_selection_ui', 'plan_preparation_ui',
            'docking_matrix', 'operation_guide', 'reference_preparation', 'reference_evidence',
            'display_revision', 'plan_stages')


def _download(sid, ref, files, label):
    """只连接标准结果索引中路径、大小和SHA全部相同的原件。"""
    if not isinstance(ref, dict):
        return None
    row = next((item for item in files if item.get('key') and all(item.get(key) == ref.get(key)
                for key in ('path', 'bytes', 'sha256')) and all(ref.get(key) is not None for key in ('path', 'bytes', 'sha256'))), None)
    if row is None:
        return None
    return {'label_zh': label, 'name': row.get('name') or Path(row['path']).name,
            'url': f"/api/v1/studies/{sid}/files/{row['key']}?expected_sha256={row['sha256']}",
            'sha256': row['sha256'], 'bytes': row['bytes']}


def apply(workflow, manifest, run, result, response):
    """新协议独立分派；历史原件按本运行输入读取，状态和人工复核权限保持。"""
    sid = manifest['study_id']
    version = run['config'].get('version')
    if version == 'A06.system_rescue.2':
        from science_modules.a06.system_rescue_display_v2 import build_view as builder
        counts = COUNTS_V2
    else:
        builder, counts = build_view, COUNTS
    require(version in (SCIENCE_VERSION, 'A06.system_rescue.2') and run['study_id'] == sid,
            '受体补救展示协议或研究不同')
    home = workflow.location(sid)
    fixed = read_json(verified_file(home, run['inputs']['system_input_ref']))
    refs = result['tables'].get('scoring_packet', [])
    require(len(refs) == 1 and refs[0] in result.get('files', []), '补救展示缺少唯一已登记评分事实包')
    packet = read_json(verified_file(home, refs[0]))
    require(fixed.get('study_id') == sid and fixed.get('stage') == 'A06_INPUT'
            and packet.get('study_id') == sid and packet.get('run_id') == run['run_id']
            and fingerprint(packet.get('inputs')) == fingerprint(run['inputs'])
            and fingerprint(packet.get('source_fixed')) == fingerprint(fixed['payload'])
            and packet['summary']['input_key'] == fixed['payload']['input_key']
            and fingerprint(packet['summary']) == fingerprint(result['summary']), '受体补救展示来源、范围或运行不同')
    core_fields = ('compound_id', 'target_id', 'state', 'score', 'quality', 'reason_zh')
    require(fingerprint([{key: row.get(key) for key in core_fields} for row in packet['pairs']]) ==
            fingerprint([{key: row.get(key) for key in core_fields} for row in result['tables']['plan_scoring_pairs']]),
            '补救展示事实包与完整评分表不同')
    view = builder(packet)
    stats = packet['summary']
    parts = Parts()
    parts.kpis = clean([kpi(label, stats.get(key)) for key, label in counts])
    parts.focus = deepcopy(response.get('focus', [])) + [focus('本轮结果须独立复核', REVIEW_NOTE, tier='should_know')]
    parts.flow_note_zh = stats['message_zh']
    parts.params = clean([param('科学协议', version), param('展示协议', view['schema_version']),
                          param('固定范围指纹', stats.get('input_key')),
                          param('原方案参数指纹', stats.get('analysis_parameter_hash'))])
    view['summary_rows'] = [{'label_zh': row['label_zh'], 'text': row['text']} for row in parts.kpis]
    preparation_states = {'ready': '准备可用', 'NA': '准备NA', 'failed': '准备失败', 'pending': '待核查'}
    view['receptor_preparation'] = [dict(row, state_zh=row.get('state_zh') or preparation_states.get(row.get('state'), row.get('state', '')))
                                   for row in result['tables'].get('receptor_preparation', [])]
    files = response.get('files', [])
    pairs = {(row['compound_id'], row['target_id']): row for row in packet['pairs']}
    for matrix in (view['table'], view['heatmap']):
        for line in matrix['cells']:
            for cell in line:
                source = pairs[(cell['compound_id'], cell['target_id'])]
                cell['evidence_url'] = evidence_url(sid, run['run_id'], source, stats['input_key'])
                cell['downloads'] = [link for key, label in (('execution', '本组合执行证据'),
                    ('top1_pose', 'Top-1构象'), ('top1', 'Top-1构象'), ('original_pose', '原始姿势文件'))
                    if (link := _download(sid, source.get(key), files, label))]
    view['input_key'] = stats['input_key']
    view['focus_url'] = f"/api/v1/studies/{sid}/runs/{run['run_id']}/rescue-focus"
    view['acceptance_url'] = f"/api/v1/studies/{sid}/runs/{run['run_id']}/acceptance"
    view['heatmap'] = focus_matrix(view, view['initial_focus']['compound_ids'], view['initial_focus']['target_ids'])
    view['downloads'] = []
    view['figures'] = []
    display_roles = set()
    for item in files:
        role = item.get('role') or ''
        if not (role.startswith('plot_a06_rescue_') or role in ('a06_rescue_matrix_csv', 'a06_rescue_display_view')):
            continue
        if version == 'A06.system_rescue.2':
            # 基线图与CSV留在完整追溯，不冒充本轮导出；逐格构象证据不受此目录过滤。
            prefix = f"runs/A06/{run['run_id']}/rescue/display/"
            if not item.get('path', '').startswith(prefix):
                continue
            require(role not in display_roles, '本轮补救展示附件同角色重复')
            display_roles.add(role)
        link = _download(sid, item, files, item.get('name') or Path(item['path']).name)
        if link:
            view['downloads'].append(link)
            if role in ('plot_a06_rescue_full_png', 'plot_a06_rescue_focus_png'):
                view['figures'].append(dict(link, image_url=link['url'] + '&inline=1', role=role))
    parts.special['system_rescue'] = view
    # 兼容标准热图读取者；新网页用含原因和来源的独立完整矩阵，不重复挂载旧控件。
    if view['score_range'][0] is not None:
        parts.special['heatmap'] = {'unit': view['unit'], 'orientation': 'rows=compounds, columns=receptors',
            'color_rule_zh': view['colour_note_zh'], 'min': view['score_range'][0], 'max': view['score_range'][1], 'omitted': [],
            'receptors': [{'name': row['target_id'], 'display_name': row['label'], 'order': i, 'pdb': None, 'rmsd': None,
                           'status_zh': row['symbol'], 'role_zh': row['candidate_grade']} for i, row in enumerate(view['table']['columns'])],
            'rows': [{'compound_id': row['compound_id'], 'compound_name': row['label'],
                      'cells': [{'receptor': c['target_id'], 'value': c['score']} for c in line]}
                     for row, line in zip(view['table']['rows'], view['table']['cells'])]}
    names = {row['compound_id']: row['label'] for row in view['table']['rows']}
    target_names = {row['target_id']: row['label'] for row in view['table']['columns']}
    detail = [dict(row, compound_name=names[row['compound_id']], target_name=target_names[row['target_id']],
                   state_zh=row.get('state_zh') or STATE_ZH[row['state']])
              for row in result['tables']['plan_scoring_pairs']]
    parts.table = table([('compound_name', '成分'), ('target_name', '受体'), ('state_zh', '实际状态'),
                         ('score', 'Vina评分（kcal/mol）'), ('quality', '准备类别'), ('reason_zh', 'NA或失败原因')],
                        detail, 'plan_scoring_pairs')
    response.update(parts.as_dict())
    for key in OBSOLETE:
        response[key] = None
    response['reference_workflow_supported'] = False
    response['system_exports'] = None
    response.setdefault('review', {}).setdefault('continue', {}).update(available=False,
        note_zh='本轮补救结果从统一执行入口接续；人工复核决定独立保存。')

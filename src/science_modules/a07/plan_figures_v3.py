"""补救报告三版图件：复用二版几何与原始矩阵，另存实际三版实现证据。"""
from pathlib import Path
from copy import deepcopy
import hashlib
from types import FunctionType
from contracts import fingerprint, require
from storage import file_record, read_json, verified_file, write_json
from . import plan_figures_v2 as original

VERSION = 'A07.plan_figures.3'
IMPLEMENTATIONS = (
    'science_modules/a07/plan_figures_v3.py', 'science_modules/a07/plan_payload_v3.py',
    'science_modules/a07/plan_documents_v3.py', 'science_modules/a07/plan_report_flow_v3.py',
    'modulea/core/plan_reports_v3.py', 'modulea/core/report_rescue_workflow.py',
    'modulea/core/report_registry.py', 'modulea/core/kernel.py',
)
_scope = dict(vars(original), VERSION=VERSION)
venn = original.venn
ppi = original.ppi
heatmaps = original.heatmaps
check_readability = original.check_readability
_validate = FunctionType(original.validate.__code__, _scope, 'validate')


def attach(workflow, payload, folder):
    """独立三版归档，正文Degree图与全网概览分开；每件图与实现均留指纹。"""
    check_readability(payload)
    require(payload.get('figure_source') is None and payload.get('figures') == [], '事实包已有图件，不重复追加')
    home = workflow.location(payload['study_id']); folder = Path(folder).resolve()
    folder.relative_to(home.resolve())
    require(not folder.exists(), '报告图件目录已存在，不覆盖历史')
    folder.mkdir(parents=True)
    manifest = workflow.load(payload['study_id']); figures = []; files = []
    def add(paths, module, caption, scope_hash, group=None, role=None):
        """图像和SVG共用来源；概览有独立角色，不充当正文筛选网络。"""
        records = {key: file_record(home, path, 'plan_report_figure') for key, path in paths.items()}
        for path in paths.values():
            if Path(path).suffix == '.svg':
                from .plan_translations_v2 import PLACEHOLDER
                require(not PLACEHOLDER.search(Path(path).read_text(encoding='utf-8')), '最终SVG仍含缺译占位文字')
        files.extend(records.values())
        entry = {'module': module, 'record': records['png'], 'caption': caption, 'scope_hash': scope_hash}
        if group:
            entry['group'] = group
        if role:
            entry['role'] = role
        figures.append(entry)
    result = workflow.result(manifest, payload['run_ids']['A03'])
    add(venn(result['summary'], folder), 'A03', '同批标准化交集，圆形面积仅示意。', fingerprint(result))
    network = payload.get('network')
    if network:
        add(ppi(network['main'], folder), 'A04', '本批Degree第二轮成员及其内部边；完整成员见同批表，不等于最终对接受体名单。', fingerprint(network), role='degree_round2')
        add(ppi(network['overview'], folder), 'A04', '本批全网络概览；与Degree第二轮正文图分开解释，不改变筛选。', fingerprint(network), role='full_network_overview')
    if payload.get('enrichment'):
        from science_modules.a05.plan_display_figures import draw
        facts = payload['enrichment']; paths = draw(facts, payload['plan'], folder/'enrichment')
        for group in ('BP', 'CC', 'MF', 'KEGG'):
            if group+'_png' in paths:
                add({'png': paths[group+'_png'], 'svg': paths[group+'_svg']}, 'A05', group+' 同批实际展示范围；中英文按稳定编号核对，原统计保持。', fingerprint(facts), group)
    if payload.get('docking'):
        for paths, caption in heatmaps(payload['docking'], folder/'docking'):
            add(paths, 'A06', caption, fingerprint(payload['docking']))
    src = Path(__file__).resolve().parents[2]; implementation = []
    names = IMPLEMENTATIONS + ('science_modules/a07/plan_figures_v2.py', 'science_modules/a07/plan_payload_v2.py',
             'science_modules/a07/plan_facts_v2.py', 'science_modules/a07/plan_translations_v2.py',
             'science_modules/a07/term_translation_supplement_v2.json', 'science_modules/a07/plan_documents_v2.py',
             'science_modules/a07/plan_report_flow_v2.py', 'modulea/core/plan_reports_v2.py',
             'science_modules/a07/plan_documents.py', 'science_modules/a07/plan_facts.py',
             'science_modules/a07/plan_payload.py', 'science_modules/a07/plan_document_style.py',
             'science_modules/a05/figures.py', 'science_modules/a05/plan_figures.py',
             'science_modules/a05/plan_display_figures.py', 'science_modules/a06/trial_presentation.py',
             'science_modules/a06/matrix_palette.py', 'report_figures.py', 'docking_formal.py',
             'science_modules/a07/appendix_documents.py', 'science_modules/a07/commented_documents.py',
             'modulea/core/plan_report_contract.py', 'modulea/core/analysis_plans.py',
             'modulea/core/system_validation.py', 'science_modules/analysis_protocol.py',
             'report_flow.py', 'contracts.py', 'workflow.py', 'storage.py')
    for name in names:
        target = folder/'code'/name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((src/name).read_bytes())
        implementation.append(file_record(home, target, 'plan_report_implementation'))
    from report_figures import _font
    fonts = []
    for bold in (False, True):
        path = Path(_font(20, bold).path); content = path.read_bytes()
        fonts.append({'name': path.name, 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)})
    source = {'schema_version': VERSION, 'study_id': payload['study_id'], 'payload_hash': fingerprint(payload),
              'run_ids': deepcopy(payload['run_ids']), 'figures': figures, 'files': files,
              'implementation_files': implementation, 'render_fonts': fonts, 'human_review_written': False}
    path = folder/'figures.json'; write_json(path, source)
    output = deepcopy(payload); output['figures'] = figures
    output['figure_source'] = file_record(home, path, 'plan_report_figure_index')
    return output


def validate(home, payload, base):
    """原图件完整度及SHA核验外，必须有本三版的全部实现快照。"""
    value = _validate(home, payload, base)
    names = [ref['path'].split('/code/', 1)[-1] for ref in value['implementation_files']]
    require(len(names) == len(set(names)) and set(IMPLEMENTATIONS).issubset(names),
            '补救报告缺少明确三版实现快照或存在重复')
    return value

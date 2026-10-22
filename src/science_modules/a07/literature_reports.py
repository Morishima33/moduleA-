"""第26版仅适配明确登记的单成分同输入文献对比，保留第25版及旧研究行为。"""
from pathlib import Path
from types import FunctionType

from contracts import require
from storage import read_json, verified_file
from science_modules.literature_input import VERSION
from . import automatic_reports as previous

CONFIG = dict(previous.CONFIG, schema_version='A07.report.config.26', template_version='A07.double_report.26')
SCOPE = '本研究为单成分文献同输入方法对比，使用作者公开历史靶点名单；不是当前常规方剂三库或疾病五库的独立新检索。未执行方剂OB/DL筛选，未复现原文大鼠软骨细胞实验，计算结果仅形成待验证假说。'


def literature_sources(workflow, manifest, parents):
    """登记和两个来源协议必须同时属于本研究，不能由报告标题猜测输入类型。"""
    intake = workflow.result(manifest, parents['A00'])['summary']
    require(intake.get('study_type') == 'single_compound_literature_comparison', '文献报告需要明确登记同输入研究')
    records = {}
    for module in ('A01', 'A02'):
        result = workflow.result(manifest, parents[module])
        require(result['summary'].get('input_profile') == VERSION, '文献报告不能混入常规采集或另一输入协议')
        run = workflow.run(manifest, parents[module])
        record = run['inputs']['source_file']
        data = read_json(verified_file(workflow.location(manifest['study_id']), record))
        require(data['study_id'] == manifest['study_id'] and data['doi'] == intake['reference_doi']
                and data['compound']['cid'] == intake['compound']['pubchem_cid']
                and data['compound']['inchikey'] == intake['compound']['inchikey'], '报告文献或化合物身份与登记不同')
        records[module] = record
    return records


def assemble_payload(workflow, manifest, parents, heatmap_metadata_record=None):
    """仍从同批评分和富集构建事实，仅改写不适用的来源方法及单成分解释。"""
    records = literature_sources(workflow, manifest, parents)
    payload = previous.assemble_payload(workflow, manifest, parents, heatmap_metadata_record)
    source = read_json(verified_file(workflow.location(manifest['study_id']), records['A01']))
    payload['literature_sources'] = records
    payload['literature_doi'] = source['doi']
    for module, key in (('A01','a01_databases'),('A02','a02_databases')):
        payload[key] = [row['database'] for row in workflow.result(manifest, parents[module])['tables']['source_summary']]
    payload['report_methods'][0] = ('单成分靶点：按PubChem CID和完整InChIKey核对文献指定化合物，读取作者公开补充表原始名单；'
        '蛋白条目缩写通过UniProt精确人类条目核对，其他基因标识按HGNC.resolve.3标准化。未决身份保留明细并暂不采用，不套用方剂OB/DL筛选。')
    payload['report_methods'][1] = ('疾病靶点：疾病边界取已核验MeSH登记，读取作者公开疾病名单，按HGNC.resolve.3统一身份并去重。'
        '资料源为文献历史检索；未重新检索全部数据库，原文筛选分值缺失时不能声称复现该分值筛选。')
    payload['report_methods'][2] = '交集与候选：计算标准化单成分靶点与疾病靶点交集；单成分的全部明确交集关系进入后续分析，不将来源覆盖解释为多成分优选。'
    payload['concise_methods'][0] = '作者公开历史名单经官方身份标准化后取单成分与疾病交集'
    payload['limitations'] = [SCOPE] + payload['limitations']
    payload['key_counts'] = [dict(r, 指标=r['指标'].replace('方剂', '单成分')) for r in payload['key_counts']]
    payload['conclusion_sections'][0] = {'层次':'成分与靶点概览','结论':'文献指定单成分为' + source['compound']['name'] + '；原始名单经官方身份标准化后形成计算输入。' + SCOPE}
    payload['conclusion_draft'] = ' '.join(r['结论'] for r in payload['conclusion_sections'])
    return payload


def revise_document(destination, payload):
    """只编辑本次新文档的文字，保留同批评分矩阵、富集和已确认排版。"""
    from docx import Document
    from .commented_documents import replace_text
    doc = Document(destination)
    paragraphs = list(doc.paragraphs)
    for table in doc.tables:
        paragraphs.extend(p for row in table.rows for cell in row.cells for p in cell.paragraphs)
    for p in paragraphs:
        old = p.text
        new = old if SCOPE in old or old.startswith('单成分靶点：') else old.replace('方剂', '单成分').replace('药味—成分', '来源—成分').replace('药味成分', '来源成分')
        if new != old:
            replace_text(p, new)
    anchor = next(p for p in doc.paragraphs if p.text.strip())
    # 研究边界直接置于报告开头；术语解释仍保留统一附录。
    paragraph = doc.add_paragraph(SCOPE + ' 参考文献DOI：' + payload['literature_doi'])
    anchor._p.addnext(paragraph._p)
    doc.save(destination)


def build_detailed(payload, destination, root, revision):
    previous.build_detailed(payload, destination, root, revision)
    revise_document(destination, payload)


def build_concise(payload, destination, root, revision):
    previous.build_concise(payload, destination, root, revision)
    revise_document(destination, payload)


def run_reports(workflow, study_id, expected_a07, reason, **kwargs):
    """仅对新增模板绑定局部生成函数，不修改旧模板模块全局。"""
    class View:
        def __getattr__(self, key):
            return getattr(workflow, key)

        def _begin(self, manifest, module, inputs, config, why):
            parents = {m:manifest['current'][m] for m in ('A00','A01','A02')}
            inputs = dict(inputs, literature_sources=literature_sources(workflow, manifest, parents))
            return workflow._begin(manifest, module, inputs, config, why)

    generate = FunctionType(previous.run_reports.__code__, dict(vars(previous), CONFIG=CONFIG,
        assemble_payload=assemble_payload, build_detailed=build_detailed, build_concise=build_concise))
    return generate(View(), study_id, expected_a07, reason, **kwargs)


def require_alignment(workflow, manifest, run):
    previous.require_alignment(workflow, manifest, run)
    require(run['inputs']['literature_sources'] == literature_sources(workflow, manifest, run['parent_runs']), '文献来源协议已改变，须重新生成报告')


def validator(root, legacy):
    """继承原逐格检查，同时拒绝把常规采集方法误写为本次文献输入。"""
    base = FunctionType(previous.validator.__code__, dict(vars(previous), CONFIG=CONFIG))(root, legacy)
    def check(run, summary, tables, anomalies, outcome):
        base(run, summary, tables, anomalies, outcome)
        if run.get('config',{}).get('schema_version') != CONFIG['schema_version']:
            return
        from docx import Document
        home = Path(root) / 'studies' / run['study_id']
        records = run['inputs']['literature_sources']
        require(set(records) == {'A01','A02'}, '报告缺少两侧文献协议')
        for record in records.values():
            source = read_json(verified_file(home, record))
            require(source['schema_version'] == VERSION and source['study_id'] == run['study_id'], '报告文献来源跨研究')
        for record in tables['report_files']:
            if record['role'] not in ('detailed_report','concise_report'):
                continue
            doc = Document(verified_file(home, record))
            text = '\n'.join(p.text for p in doc.paragraphs)
            require(SCOPE in text and '本研究以TCMSP' not in text and '读取TCMSP来源成分' not in text
                    and 'TCMSP采用口服生物利用度' not in text, '单成分报告范围或来源方法不正确')
    return check

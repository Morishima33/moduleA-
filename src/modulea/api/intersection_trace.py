"""Read-only CSV projection of a specific A03 and its archived source evidence."""

import csv
import io
import re
from collections import defaultdict

from contracts import ContractError, require
from .errors import from_contract, not_found


UNKNOWN = '未归属'
FIELDS = ('记录类型', '侧别', '数据库', '不同交集基因数', '仅见于此来源', '已知跨库重叠',
          '含未归属证据', 'HGNC编号', '标准基因符号', '成分编号', '成分名称', '成分关联药味', '来源定位',
          '药味', '参与交集的不同成分数', '原来源证据类别')


def _formula_source(ref, edge, sources):
    labels = sources.get(ref)
    if labels:
        return next(iter(labels)) if len(labels) == 1 else UNKNOWN
    if re.fullmatch(r'uploaded_TCMSP_[0-9a-f]{24}:[0-9]+', ref):
        return 'TCMSP'  # A01 plan_flow and uploads use this exact synthetic upload ID.
    return edge.get('database') or UNKNOWN


def _safe_cells(row):
    # Source-derived text may be opened in a spreadsheet.
    return {key: "'" + value if isinstance(value, str) and
            value.lstrip().startswith(('=', '+', '-', '@')) else value for key, value in row.items()}


def _evidence_type(side, database, ref):
    if side == '方剂':
        if database == 'HERB' and ':ingredient_target:' in ref:
            return 'HERB成分已有靶点表，逐条证据见原件'
        if database == 'BATMAN' and '/BATMAN_known_browse_by_ingredients.txt.gz:' in ref:
            return 'BATMAN已知关联表'
    return ''


def trace_csv(result, formula):
    tables = result['tables']
    genes = {r['target_id']: r['symbol'] for r in tables['intersection_targets']}
    require(len(genes) == len(tables['intersection_targets']) == result['summary']['交集靶点数'],
            'A03交集成员与归档总数不一致')
    ranking = {r['compound_id']: r for r in tables['ranking']}
    sources = defaultdict(set)
    for row in formula['tables'].get('new_relation_evidence', []):
        sources[row['source_ref']].add(row['database'])
    coverage = defaultdict(set)
    herb_genes = defaultdict(set)
    herb_components = defaultdict(set)
    for row in formula['tables'].get('herb_summary', []):
        herb_genes[row['herb']]  # Retain herbs with zero intersections.
    details = []
    for side, key in [('方剂', 'formula_evidence'), ('疾病', 'disease_evidence')]:
        side_genes = set()
        for edge in tables[key]:
            gene = edge['target_id']
            if gene not in genes:
                continue
            side_genes.add(gene)
            component = ranking[edge['compound_id']] if side == '方剂' else {}
            if component:
                for herb in filter(None, component['herbs'].split('、')):
                    herb_genes[herb].add(gene)
                    herb_components[herb].add(edge['compound_id'])
            for ref in edge['source_ref'].split('|'):
                db = _formula_source(ref, edge, sources) if side == '方剂' else edge.get('database') or UNKNOWN
                coverage[side, gene].add(db)
                detail = dict(zip(FIELDS, (
                    '交集来源明细', side, db, '', '', '', '', gene, genes[gene],
                    component.get('compound_id', ''), component.get('name', ''), component.get('herbs', ''), ref)))
                detail['原来源证据类别'] = _evidence_type(side, db, ref)
                details.append(detail)
        require(side_genes == genes.keys(), '本批交集缺少一侧归档来源')

    stats = defaultdict(lambda: [0, 0, 0, 0])
    for (side, _), labels in coverage.items():
        has_unknown = UNKNOWN in labels
        overlap = len(labels - {UNKNOWN}) > 1
        for db in labels:
            counts = stats[side, db]
            counts[0] += 1
            counts[1] += db != UNKNOWN and len(labels) == 1
            counts[2] += db != UNKNOWN and overlap
            counts[3] += has_unknown

    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerow({'记录类型': 'A03去重交集总数', '不同交集基因数': len(genes)})
    for (side, db), counts in sorted(stats.items()):
        writer.writerow(_safe_cells(dict(zip(FIELDS, ('来源汇总', side, db, *counts)))))
    for herb, hits in sorted(herb_genes.items()):
        writer.writerow(_safe_cells({'记录类型': '药味覆盖汇总', '侧别': '方剂', '药味': herb,
                                    '不同交集基因数': len(hits), '参与交集的不同成分数': len(herb_components[herb])}))
    writer.writerows(map(_safe_cells, details))
    return stream.getvalue().encode('utf-8-sig')


def download(app, study_id, run_id):
    workflow = app.kernel.read_workflow()
    try:
        manifest = workflow.load(study_id)
        if run_id not in manifest['runs']:
            raise not_found('A03运行')
        run = workflow.run(manifest, run_id)
        if run['module_id'] != 'A03':
            raise not_found('A03运行')
        result = workflow.result(manifest, run_id)
        if result is None:
            raise not_found('A03结果')
        parents = run['parent_runs']
        formula, disease = (workflow.result(manifest, parents[key]) for key in ('A01', 'A02'))
        require(formula and disease and
                formula['tables']['normalized_compound_targets'] == result['tables']['formula_evidence'] and
                disease['tables']['normalized_targets'] == result['tables']['disease_evidence'],
                'A03来源与绑定的A01/A02归档不一致')
        raw = trace_csv(result, formula)
    except ContractError as error:
        raise from_contract(str(error)) from error
    return ('download', raw, f'{run_id}_intersection_trace.csv', 'text/csv; charset=utf-8')

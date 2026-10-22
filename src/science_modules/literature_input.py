"""单成分文献同输入对比：核验原始表、官方身份与研究级决定，复用原A03以后科学内核。"""
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile
import csv
import io
import json
import re
import xml.etree.ElementTree as ET

from contracts import require
from hgnc import load_snapshot
from storage import read_json, verified_file

VERSION = 'ModuleA.literature_input.1'
CONFIGS = {m: {'version': m + '.literature_input.1', 'input_mode': 'single_compound',
              'source_mode': 'archived_literature_same_input', 'gene_rule': 'HGNC.resolve.3'} for m in ('A01', 'A02')}
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}


def read_sheets(path):
    """从原始单列表格读取实际工作表和单元格位置；首行也是基因，不能丢作表头。"""
    with ZipFile(path) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            shared = [''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si', NS)]
        rels = {e.get('Id'): e.get('Target') for e in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        result = []
        for sheet in ET.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet', NS):
            target = rels[sheet.get('{' + NS['r'] + '}id')]
            target = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            for row in ET.fromstring(z.read(target)).findall('s:sheetData/s:row', NS):
                cells = [c for c in row.findall('s:c', NS) if re.fullmatch(r'A\d+', c.get('r', ''))]
                if not cells:
                    continue
                cell = cells[0]
                v = cell.find('s:v', NS)
                value = shared[int(v.text)] if cell.get('t') == 's' and v is not None else ''.join(cell.find('s:is', NS).itertext()) if cell.get('t') == 'inlineStr' else v.text if v is not None else ''
                if value and str(value).strip():
                    result.append({'source': sheet.get('name'), 'source_line': int(row.get('r')), 'cell': cell.get('r'), 'original_identifier': str(value).strip()})
        return result


def evaluate(data_root, home, module, inputs):
    """每次从归档原件重建映射；未决记录单列，不用论文交集或期望数量构造结果。"""
    source = read_json(verified_file(home, inputs['source_file']))
    require(source.get('schema_version') == VERSION and source.get('study_id') == Path(home).name, '文献来源协议或研究归属不一致')
    require(source.get('scope_confirmed') is True and source.get('omit_unresolved') is True
            and source.get('reviewer') and source.get('reason'), '缺少本研究的文献范围及身份例外处理决定')
    mapper, meta = load_snapshot(Path(data_root))
    require(inputs['mapping_file']['sha256'] == mapper.digest, '文献输入与HGNC归档版本不同')
    verified_file(home, inputs['mapping_file'])
    for record in source['original_files']:
        verified_file(home, record)
    identity = read_json(verified_file(home, source['compound_identity_file']))['PropertyTable']['Properties']
    require(len(identity) == 1 and identity[0]['CID'] == source['compound']['cid']
            and identity[0]['InChIKey'] == source['compound']['inchikey'], '文献化合物与官方完整身份不一致')
    rows = read_sheets(verified_file(home, source['compound_targets_file' if module == 'A01' else 'disease_targets_file']))
    uniprot = defaultdict(list)
    for r in csv.DictReader(io.StringIO(verified_file(home, source['uniprot_file']).read_text('utf-8')), delimiter='\t'):
        if r['Organism (ID)'] == '9606':
            uniprot[r['Entry Name']].append(r)
    mapping, issues = [], []
    for raw in rows:
        value = raw['original_identifier']
        if module == 'A01' and raw['source'] in source['uniprot_entry_name_sources']:
            matches = uniprot.get(value + '_HUMAN', [])
            if len(matches) == 1:
                record = matches[0]
                found = mapper.resolve(record['Gene Names (primary)'], uniprot=record['Entry'])
                found['official_entry_name'] = record['Entry Name']
            else:
                found = {'status': 'unmapped' if not matches else 'ambiguous_or_conflicting', 'target_id': '', 'symbol': ''}
        else:
            found = mapper.resolve('', stable_id=value) if value.startswith(('ENSG', 'HGNC:', 'NCBIGene:', 'GeneID:')) else mapper.resolve(value)
        item = dict(found, **raw)
        item['source_ref'] = source['doi'] + ':' + raw['source'] + '!' + raw['cell']
        (mapping if found['status'] == 'matched' else issues).append(item)
    grouped = defaultdict(list)
    for row in mapping:
        grouped[row['target_id']].append(row)
    targets = [{'target_id': k, 'symbol': values[0]['symbol'], 'species': 9606,
                'source_ref': ';'.join(sorted({r['source_ref'] for r in values})),
                'source': '|'.join(sorted({r['source'] for r in values}))} for k, values in sorted(grouped.items())]
    summary = {'input_profile': VERSION, 'namespace': 'HGNC', 'mapping_snapshot': mapper.digest,
               'mapping_rule': mapper.rule, 'identity_evidence_snapshot': mapper.supplement.digest,
               'analysis_purpose': 'workflow_test', '标准化基因数': len(targets), '原始关系记录数': len(rows),
               '原始不同标识数': len({r['original_identifier'] for r in rows}), '身份问题组数': len({r['original_identifier'] for r in issues}),
               '身份问题处理': '本次同输入方法对比暂不采用未决身份，原件及逐项原因全部保留',
               '资料阶段': '文献历史原始输入；不是当前常规三库／五库新检索', 'reference_doi': source['doi'],
               'handoff_blocked': False}
    tables = {'identity_mapping': mapping, 'identity_issues': issues,
              'source_summary': [{'database': name, 'records': sum(r['source'] == name for r in rows),
                                  'availability': '作者公开原始名单', 'query': source['disease_term']} for name in sorted({r['source'] for r in rows})]}
    if module == 'A01':
        c = source['compound']
        # 仅为复用原混合图契约记录输入来源节点，明确不是药材归属或方剂配伍。
        origin = '文献指定单成分（非药材）'
        cid = 'PUBCHEM_' + str(c['cid'])
        tables.update(components=[{'compound_id': cid, 'name': c['name'], 'cid': c['cid'], 'inchikey': c['inchikey'], 'molecular_formula': identity[0]['MolecularFormula'], 'human_targets': len(targets)}],
                      herb_components=[{'herb': origin, 'compound_id': cid}],
                      herb_summary=[{'herb': origin, 'components': 1, 'human_genes': len(targets), 'raw_rows': len(rows)}],
                      normalized_compound_targets=[dict(r, compound_id=cid) for r in targets])
        summary.update({'筛选后不同成分数': 1, '去重成分—人类基因关系数': len(targets), 'source_node_semantics': '单成分登记来源节点，不是药材边，不据此进行多成分优先级解释'})
    else:
        tables['normalized_targets'] = targets
    anomalies = ['同输入方法对比：采用作者历史名单，不声称独立复现了当前各数据库检索。',
                 '未决身份暂不采用，不解释为无效或与疾病无关；明细及原件保留。',
                 '成分预测关系不是实测结合；论文大鼠细胞实验不作为本研究人类计算的直接验证。']
    return summary, tables, anomalies, 'success' if targets else 'empty'


def validator(data_root, module, previous):
    """仅分派新增文献协议；历史和常规输入继续由原校验器核验。"""
    def check(run, summary, tables, anomalies, outcome):
        if run['config'].get('version') != CONFIGS[module]['version']:
            return previous(run, summary, tables, anomalies, outcome)
        require(run['module_id'] == module and run['config'] == CONFIGS[module], '文献模块配置不一致')
        home = Path(data_root) / 'studies' / run['study_id']
        expected = evaluate(data_root, home, module, run['inputs'])
        require((summary, tables, anomalies, outcome) == expected, '文献输入结果与原件复算不一致')
    return check


def publish(workflow, sid, module, inputs, reason):
    """通过现有Workflow公开接口发布版本，保留上游批准、写锁和指纹门控。"""
    require(module in CONFIGS, '文献输入仅支持A01和A02')
    manifest = workflow.load(sid)
    intake = workflow.result(manifest, manifest['current']['A00'])['summary']
    require(intake.get('study_type') == 'single_compound_literature_comparison'
            and intake.get('analysis_purpose') == 'workflow_test', '文献同输入协议须由独立对比研究明确登记')
    home = workflow.location(sid)
    source = read_json(verified_file(home, inputs['source_file']))
    require(source['compound']['cid'] == intake['compound']['pubchem_cid']
            and source['compound']['inchikey'] == intake['compound']['inchikey']
            and source['doi'] == intake['reference_doi'], '文献输入与本研究登记对象不一致')
    result = evaluate(workflow.root, home, module, inputs)
    run = workflow.begin(sid, module, inputs, dict(CONFIGS[module]), reason)
    workflow.finish(sid, run['run_id'], *result)
    return run['run_id']

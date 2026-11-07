"""仅生成同批网页展示附件：复用已核验图形、核译和原统计，不产生Word或研究状态。"""
from copy import deepcopy
from hashlib import sha256
from io import StringIO
from pathlib import Path, PurePosixPath
import csv
import json
import re

from contracts import fingerprint, require

VERSION = 'ModuleA.presentation_bundle.1'
PLACEHOLDER = re.compile(r'中文待核(?:译)?|待核译|待翻译|中文待译|译名待补')


def _json_bytes(value):
    """导出可核对的原始数值与完整行，不以显示格式替代统计精度。"""
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')


def _csv_bytes(rows):
    """列顺序沿原行首次出现顺序；嵌套来源关系保留JSON，缺失评分明确写NA。"""
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), '展示表不是记录列表')
    keys = list(dict.fromkeys(key for row in rows for key in row))
    stream = StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=keys, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        value = {}
        for key in keys:
            cell = row.get(key)
            value[key] = ('NA' if cell is None else json.dumps(cell, ensure_ascii=False, allow_nan=False)
                          if isinstance(cell, (dict, list, tuple)) else cell)
        writer.writerow(value)
    return stream.getvalue().encode('utf-8-sig')


def _translation_audit(enrichment, lexicon):
    """正文、图与附录所有实际条目均按稳定ID和原英文核译，缺一项即阻断。"""
    from .a05.display import english
    from .a07.plan_translations_v2 import checked_translation
    audit = {}
    for table, rows in enrichment.get('tables', {}).items():
        require(isinstance(rows, list), '富集展示表必须为记录列表')
        for row in rows:
            if not isinstance(row, dict) or not row.get('ID'):
                continue
            entry = checked_translation(row, lexicon)
            chinese = entry['zh'];original=english(row)
            require(row.get('chinese')==chinese and row.get('description_zh')==chinese
                    and row.get('english')==original and row.get('label')==original+' / '+chinese
                    and row.get('translation_status')=='checked' and row.get('translation_source')==entry['source']
                    and bool(re.search('[\u4e00-\u9fff]', chinese)),
                    '展示中文与实际核译来源不一致：'+row['ID'])
            require(not PLACEHOLDER.search(chinese), '核译仍含未完成占位文字：'+row['ID'])
            value = {'ID': row['ID'], 'english': original, 'chinese': chinese,
                     'source': entry['source'], 'translation_basis': entry['translation_basis'],
                     'source_obsolete': bool(entry.get('source_obsolete')), 'tables': []}
            if row['ID'] in audit:
                require(all(audit[row['ID']][key] == value[key] for key in value if key != 'tables'),
                        '同一稳定编号在展示表中使用了不同名称或译名：'+row['ID'])
            else:
                audit[row['ID']] = value
            if table not in audit[row['ID']]['tables']:
                audit[row['ID']]['tables'].append(table)
    return list(audit.values())


def _checked_data(payload, a03_result, lexicon):
    """只校对已生成事实的归属、完整范围及原值，不计算新筛选或科学统计。"""
    from .a07.plan_translations_v2 import check_readability
    from .a07.plan_facts_v2 import docking as check_docking
    require(payload.get('schema_version') == 'A07.plan_payload.2', '展示修订只消费明确的第二版事实')
    require(payload.get('figures') == [] and payload.get('figure_source') is None, '不能把已有旧图片混作新展示')
    require(a03_result.get('module_id') == 'A03' and a03_result.get('study_id') == payload['study_id']
            and a03_result.get('run_id') == payload['run_ids'].get('A03'), '韦恩图不属于本批交集')
    summary = a03_result['summary']
    left, both, right = [summary[key] for key in ('仅方剂靶点数','交集靶点数','仅疾病靶点数')]
    require(all(type(n) is int and n >= 0 for n in (left, both, right)), '交集数量不是原非负整数')
    require(payload['counts'] == {'a01_genes': left+both,'a02_genes':right+both,'intersection':both},
            '韦恩图与原事实包的数量口径不一致')
    check_readability(payload)
    require(not PLACEHOLDER.search(json.dumps({key:value for key,value in payload.items()
                if key not in ('source_evidence','translation_audit')}, ensure_ascii=False, allow_nan=False)),
            '实际页面、图例或下载说明仍有未完成核译占位')
    tables = {'a03_counts':[{'only_formula':left,'intersection':both,'only_disease':right,
                             'formula_total':left+both,'disease_total':right+both}]}
    counts = {'a03':deepcopy(tables['a03_counts'][0])}
    network = payload.get('network')
    if network:
        require(network['network_run_id'] == payload['run_ids'].get('A04'), 'PPI不属于本批网络运行')
        main, full = network['main'], network['overview']
        require(main['kind']=='degree_round2' and full['kind']=='full_network_overview', 'PPI正文和概览角色不符')
        full_map = {row['target_id']: row for row in full['nodes']}
        ids = [row['target_id'] for row in main['nodes']]
        require(len(full_map)==len(full['nodes']) and len(ids)==len(set(ids)) and set(ids)<=set(full_map), 'PPI节点重复或越界')
        selected = network['selection'].get('tables', network['selection']).get('degree_round2')
        require(isinstance(selected,list) and ids==[row['target_id'] for row in selected], '正文图不是本批Degree第二轮原序名单')
        require(main['nodes']==[full_map[key] for key in ids], '正文PPI节点名称或原字段与全网不同')
        require(all(row['source'] in full_map and row['target'] in full_map for row in full['edges']), 'PPI全网边越界')
        members = set(ids)
        require(main['edges']==[row for row in full['edges'] if row['source'] in members and row['target'] in members],
                '正文PPI边不是原第二轮成员的内部边')
        require(main['source_result_hash']==full['source_result_hash'], 'PPI正文和概览来源不同')
        for key,scope in (('degree_round2',main),('full_network_overview',full)):
            participating = {row[endpoint] for row in scope['edges'] for endpoint in ('source','target')}
            require(scope['isolates']==[row['target_id'] for row in scope['nodes'] if row['target_id'] not in participating], 'PPI孤立节点统计不同')
            tables['ppi_'+key+'_nodes'] = deepcopy(scope['nodes'])
            tables['ppi_'+key+'_edges'] = deepcopy(scope['edges'])
            counts[key] = {'nodes':len(scope['nodes']),'edges':len(scope['edges']),'isolates':len(scope['isolates'])}
    translations = []
    if payload.get('enrichment'):
        facts = payload['enrichment']
        require(facts['study_id']==payload['study_id'] and facts['run_id']==payload['run_ids'].get('A05'), '富集不属于本批运行')
        require(all(re.fullmatch('[a-z0-9_]+', key) for key in facts['tables']), '富集展示表名不是安全的固定标识')
        translations = _translation_audit(facts, lexicon)
        tables.update({'a05_'+key:deepcopy(rows) for key,rows in facts['tables'].items()})
        counts['enrichment'] = deepcopy(facts['groups'])
    if payload.get('docking'):
        facts = payload['docking'];preparation = facts['preparation_only']
        require(facts['study_id']==payload['study_id'] and facts['run_id']==payload['run_ids'].get('A06_PREP' if preparation else 'A06'),
                '评分矩阵不属于本批固定运行')
        expected = check_docking({'study_id':facts['study_id'],'run_id':facts['run_id'],
            'compounds':facts['compounds'],'receptors':facts['receptors'],
            'planned_pairs' if preparation else 'pairs':facts['pairs']},facts['configuration'],preparation_only=preparation)
        require(fingerprint(expected)==fingerprint(facts), '评分原值、NA或完整固定矩阵与事实模型不同')
        tables['a06_compounds'] = deepcopy(facts['compounds'])
        tables['a06_receptors'] = deepcopy(facts['receptors'])
        tables['a06_pairs'] = deepcopy(facts['pairs'])
        counts['docking'] = deepcopy(facts['counts'])
    counts['translation_terms'] = len(translations)
    counts['translation_rows'] = sum(len(rows) for rows in (payload.get('enrichment') or {}).get('tables',{}).values())
    return {'schema_version':VERSION,'study_id':payload['study_id'],'run_ids':deepcopy(payload['run_ids']),
            'payload_hash':fingerprint(payload),'a03_result_hash':fingerprint(a03_result),
            'tables':tables,'translation_audit':translations,'counts':counts,
            'sources':deepcopy(payload.get('sources',[])),
            'notes_zh':['仅更新图表、核译和名称展示；原统计、BH、排序、评分及全部NA保持。',
                        'PPI主图为原Degree第二轮及内部边，全网仅作独立概览，均不等于固定对接受体名单。',
                        '韦恩图面积仅示意；数值取本批标准化的不同人类基因。'],
            'statistics_changed':False,'human_review_written':False,'word_generated':False}


def _figure_specs(payload, a03_result):
    """将每个图件的固定角色、原事实范围和布局路径绑定；不能只换标题冒充新范围。"""
    specs=[]
    def add(key,module,stem,role,caption,scope,group=None):
        """路径和元数据均由实际适用分支派生，不接受调用方自报。"""
        specs.append({'key':key,'module':module,'group':group,'role':role,'caption':caption,
                      'source_run_id':payload['run_ids'][module],'scope_hash':fingerprint(scope),
                      'files':{kind:stem+'.'+kind for kind in ('png','svg')}})
    add('venn','A03','figures/intersection','intersection',
        '同批标准化交集；面积为示意，原集合数量见数据表。',a03_result)
    if payload.get('network'):
        for key,scope,caption in (
                ('ppi_degree_round2',payload['network']['main'],'本批Degree第二轮全部节点及内部边；仅少量标签辅助阅读，完整名称保留SVG提示与数据表。'),
                ('ppi_overview',payload['network']['overview'],'本批已识别全网络概览，与Degree第二轮主图分开解释。')):
            add(key,'A04','figures/'+key,scope['kind'],caption,scope)
    if payload.get('enrichment'):
        facts=payload['enrichment']
        included={row['group'] for row in facts['groups'] if row['included']}
        expected=({'BP','CC','MF'} if payload['plan']['parameters']['a05.include_go'] else set()) | ({'KEGG'} if payload['plan']['parameters']['a05.include_kegg'] else set())
        require(included==expected, '富集事实适用类别与本批方案不同')
        for group in ('BP','CC','MF','KEGG'):
            if group in included:
                add('enrichment_'+group.lower(),'A05','figures/enrichment/'+group+'_plan','enrichment',
                    group+'本批原展示范围；稳定ID、原英文、核译及完整精度保留。',facts,group)
    if payload.get('docking'):
        facts=payload['docking'];module='A06_PREP' if facts['preparation_only'] else 'A06'
        for row in range(0,len(facts['compounds']),20):
            for col in range(0,len(facts['receptors']),8):
                key=f'scores_{row+1}_{col+1}'
                add(key,module,'figures/docking/'+key,'score_matrix',
                    '完整同批评分矩阵；行列使用本批实际名称，全部NA和原始评分保留。',facts)
    return specs


def _record(folder, path, role):
    """附件只返回本展示目录内的相对索引，便于公开Workflow统一登记。"""
    path=Path(path).resolve();relative=path.relative_to(folder.resolve()).as_posix()
    raw=path.read_bytes()
    return {'path':relative,'bytes':len(raw),'sha256':sha256(raw).hexdigest(),'role':role}


def build_bundle(payload, a03_result, folder, *, lexicon=None):
    """为已绑定事实创建全新展示包；调用方负责科学来源与研究写锁，不覆盖旧附件。"""
    from .a07.plan_translations_v2 import merged_lexicon
    from .a07 import plan_figures_v2 as figures
    from .a05.plan_display_figures import draw as draw_enrichment
    lexicon=merged_lexicon() if lexicon is None else deepcopy(lexicon)
    data=_checked_data(payload,a03_result,lexicon)
    entries=_figure_specs(payload,a03_result)
    folder=Path(folder).resolve();require(not folder.exists(),'展示目录已存在，不能覆盖原附件')
    folder.mkdir(parents=True)
    files=[]
    def add(key,paths):
        """PNG与SVG保留同一范围身份，下载表保留全部节点和原分数。"""
        spec=next(row for row in entries if row['key']==key)
        refs={kind:_record(folder,path,'presentation_figure_'+kind) for kind,path in paths.items()}
        require({kind:ref['path'] for kind,ref in refs.items()}==spec['files'], '绘图器输出路径或格式与固定图件不同')
        for kind,path in paths.items():
            if kind=='svg':require(not PLACEHOLDER.search(Path(path).read_text('utf-8')),'图中文字仍含缺译占位')
        files.extend(refs.values())
    add('venn',figures.venn(a03_result['summary'],folder/'figures'))
    if payload.get('network'):
        for name,scope,caption in (('ppi_degree_round2',payload['network']['main'],'本批Degree第二轮全部节点及内部边；仅少量标签辅助阅读，完整名称保留SVG提示与数据表。'),
                                   ('ppi_overview',payload['network']['overview'],'本批已识别全网络概览，与Degree第二轮主图分开解释。')):
            add(name,figures.ppi(scope,folder/'figures'))
    if payload.get('enrichment'):
        paths=draw_enrichment(payload['enrichment'],payload['plan'],folder/'figures/enrichment')
        for group in ('BP','CC','MF','KEGG'):
            if group+'_png' in paths:
                add('enrichment_'+group.lower(),{'png':paths[group+'_png'],'svg':paths[group+'_svg']})
    if payload.get('docking'):
        for paths,caption in figures.heatmaps(payload['docking'],folder/'figures/docking'):
            add(Path(paths['png']).stem,paths)
    for name,rows in data['tables'].items():
        path=folder/'tables'/(name+'.csv');path.parent.mkdir(exist_ok=True)
        path.write_bytes(_csv_bytes(rows));files.append(_record(folder,path,'presentation_table'))
    translation_path=folder/'translation_audit.json';translation_path.write_bytes(_json_bytes(data['translation_audit']))
    files.append(_record(folder,translation_path,'presentation_translation_audit'))
    path=folder/'presentation_data.json';path.write_bytes(_json_bytes(data));files.append(_record(folder,path,'presentation_data'))
    value={key:deepcopy(data[key]) for key in ('schema_version','study_id','run_ids','payload_hash','a03_result_hash','counts')}
    value.update(figures=entries,tables=deepcopy(data['tables']),translation_audit=deepcopy(data['translation_audit']),
                 data_file='presentation_data.json',files=files,statistics_changed=False,human_review_written=False,word_generated=False)
    validate_bundle(payload,a03_result,folder,value,lexicon=lexicon)
    return value


def validate_bundle(payload, a03_result, folder, manifest, *, lexicon=None):
    """核对实际表值、矩阵NA、译名覆盖和全部文件，不相信自填通过标记或新SHA。"""
    from .a07.plan_translations_v2 import merged_lexicon
    data=_checked_data(payload,a03_result,merged_lexicon() if lexicon is None else lexicon)
    folder=Path(folder).resolve()
    require(all(manifest.get(key)==data[key] for key in ('schema_version','study_id','run_ids','payload_hash','a03_result_hash','counts','tables','translation_audit')),
            '展示索引与本批事实、译名或数量不同')
    require(manifest.get('statistics_changed') is False and manifest.get('human_review_written') is False
            and manifest.get('word_generated') is False,'展示修订不能改科学结果、写复核或生成Word')
    specs=_figure_specs(payload,a03_result)
    require(manifest.get('figures')==specs and manifest.get('data_file')=='presentation_data.json', '图件角色、范围、名称或顺序与本批实际范围不同')
    records=manifest['files'];paths=[row['path'] for row in records]
    require(len(paths)==len(set(paths)), '展示附件索引重复')
    roles={path:'presentation_figure_'+kind for row in specs for kind,path in row['files'].items()}
    roles.update({'tables/'+name+'.csv':'presentation_table' for name in data['tables']})
    roles.update({'translation_audit.json':'presentation_translation_audit','presentation_data.json':'presentation_data'})
    require(set(paths)==set(roles), '展示附件索引缺少原表图或混入额外文件')
    for ref in records:
        name=ref['path'];relative=PurePosixPath(name)
        require(isinstance(name,str) and not relative.is_absolute() and '..' not in relative.parts
                and '\\' not in name and relative.as_posix()==name, '展示附件路径不是目录内的规范相对路径')
        path=folder/relative
        require(not any((folder/Path(*relative.parts[:i])).is_symlink() for i in range(1,len(relative.parts)+1)), '展示附件不允许符号链接')
        path=path.resolve()
        require(path.is_relative_to(folder) and path.is_file() and ref['role']==roles[name]
                and _record(folder,path,ref['role'])==ref,'展示附件指纹、角色或路径不同')
        require(path.suffix.lower() in ('.png','.svg','.csv','.json'),'展示包含未授权文件类型')
        if path.suffix.lower()=='.svg':require(not PLACEHOLDER.search(path.read_text('utf-8')),'SVG仍有缺译占位')
    require((folder/'presentation_data.json').read_bytes()==_json_bytes(data),'展示数据表的原值或完整NA发生变化')
    require((folder/'translation_audit.json').read_bytes()==_json_bytes(data['translation_audit']),'译名审计与实际条目不同')
    for name,rows in data['tables'].items():
        relative='tables/'+name+'.csv'
        require(relative in paths and (folder/relative).read_bytes()==_csv_bytes(rows),'下载表原值、列序或缺失含义发生变化：'+name)
    return True

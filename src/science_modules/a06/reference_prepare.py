"""已集中核定共晶参考先按冻结严格规则重对接，否则继续第二版探索。"""
from copy import deepcopy
from contracts import require
from storage import verified_file, write_json
from .reference_candidates import apply_choices, cif_categories


def verify_sequence(root, origin, row, folder):
    """复用旧连接不能跳过实际序列映射；官方原件随新执行保存。"""
    from storage import read_json
    from .automatic_coverage_sources import Fetcher, sequence_scope
    record = origin.get('official_sequence_file') or row.get('official_sequence_file')
    if record:
        official = read_json(verified_file(root, record))
    else:
        official, record = Fetcher(root, folder).get('https://rest.uniprot.org/uniprotkb/'+origin['spec']['uniprot']+'.json')
    scope = sequence_scope(verified_file(root, origin['cif']).read_text('utf-8'), origin['spec'], official)
    return {'official_sequence_file': record, 'sequence_scope': scope}


def complete_reference(root, origin, ccd):
    """从实际CCD拓扑与原CIF核对全部重原子，不以人工选择代替完整性。"""
    from .reference_candidates import _identity
    spec = origin['spec']
    tables = cif_categories(verified_file(root, origin['cif']).read_text('utf-8'))
    definition = cif_categories(ccd)
    require(definition.get('_chem_comp', [{}])[0].get('id') == spec['reference_code'], '官方CCD组件身份不符')
    expected = {a['atom_id'] for a in definition.get('_chem_comp_atom', []) if a.get('comp_id') == spec['reference_code'] and a.get('type_symbol', '').upper() not in ('H', 'D')}
    actual = [a for a in tables.get('_atom_site', []) if _identity(a) == (spec['reference_code'], spec['reference_chain'], str(spec['reference_sequence'])) and a.get('type_symbol', '').upper() not in ('H', 'D') and a.get('label_alt_id', '.') in ('.', '?', spec.get('altloc'))]
    names = [a.get('label_atom_id') for a in actual]
    require(expected and len(names) == len(set(names)) and set(names) == expected, '共晶参考实际重原子与官方CCD不完整匹配')
    return dict(deepcopy(origin), reference_audit={'reference_count_matches': True, 'reference_covalent_count': 0})


def prepare(workflow, sid, connection, row, folder, tools, repair_packages, code, authorization_id, progress):
    """只执行本次授权稳定键选中的方案；严格失败不变标签，独立保留并回退。"""
    from .automatic_coverage_prepare import prepare as previous_prepare
    from .automatic_engine import preparation_source
    from .automatic_rules import assess
    from .quality_engine import attempt, download_ccd
    exploration_row = deepcopy(row)
    for origin in exploration_row.get('candidates', []):
        if origin['spec'].get('pocket') == 'reference':
            # 旧人工参考不自动升级到新授权；未在本次集中核定时只走原预测探索。
            origin['spec'] = {k: v for k, v in origin['spec'].items() if not k.startswith('reference_')}
            origin['spec']['pocket'] = 'p2rank'
            origin.pop('reference_audit', None)
    choices = [r for r in connection.get('reference_choices', []) if r['target_id'] == row['target_id']]
    if not choices:
        return previous_prepare(workflow, sid, connection, exploration_row, folder, tools, repair_packages, code, authorization_id, progress)
    root = workflow.location(sid)
    adapted = apply_choices(root, connection, choices)
    chosen = next(r for r in adapted['receptors'] if r['target_id'] == row['target_id'])['candidates'][0]
    trace = {'candidate': chosen}
    try:
        progress('已核定共晶参考质控：'+row['symbol']+' / '+chosen['spec']['pdb_id']+' / '+chosen['spec']['reference_code'])
        (folder/'reference_topology').mkdir(parents=True, exist_ok=False)
        chosen['reference_sequence_audit'] = verify_sequence(root, chosen, row, folder/'reference_sequence')
        ccd = download_ccd(chosen['spec']['reference_code'], folder/'reference_topology')
        chosen = complete_reference(root, chosen, ccd.read_text('utf-8'))
        chosen_row = dict(row, candidates=[chosen])
        source = preparation_source(dict(connection, receptors=[chosen_row]))
        evidence = attempt(root, source, row, chosen['spec'], 1, folder/'confirmed_reference', tools, progress)
        trace.update(candidate=chosen, evidence=evidence)
        result = assess(chosen['spec'], evidence, authorization_id, row)
        if result['state'] == 'ready' and result['quality'] == '严格':
            return dict(row, state='ready', quality='严格', selected_candidate=chosen, evidence=evidence,
                regions=[dict(evidence['box'], region_id='fixed_site')], mode='fixed_site', receptor=evidence['receptor'],
                reason_zh=result['reason_zh'], attempts=[trace])
        trace['reason_zh'] = result['reason_zh']
    except Exception as error:
        trace['reason_zh'] = str(error)
    write_json(folder/'confirmed_reference_failure.json', trace)
    value = previous_prepare(workflow, sid, connection, exploration_row, folder/'exploration_fallback', tools, repair_packages, code, authorization_id, progress)
    value['attempts'] = [trace] + value.get('attempts', [])
    return value

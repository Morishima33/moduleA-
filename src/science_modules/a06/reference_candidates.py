"""共晶候选的只读清点与稳定键验证；仅标准库，无联网或科学工具加载。"""
from copy import deepcopy
import math
import re
from contracts import fingerprint, require
from storage import verified_file

ADDITIVES = frozenset("HOH DOD GOL EDO PEG PGE PG4 P6G MPD DMS SO4 PO4 ACT ACE BME TRS MES HEP CL NA K MG CA ZN MN NI CO CU FE FES NAG MAN BMA FUC GAL GLC".split())


def cif_categories(text):
    """读取mmCIF循环及单值；保留引号和分号多行值，不执行文件内容。"""
    tokens = []
    lines = iter(text.splitlines())
    for line in lines:
        if line.startswith(';'):
            value = [line[1:]]
            for following in lines:
                if following.startswith(';'):
                    break
                value.append(following)
            else:
                raise ValueError('mmCIF分号多行值未结束')
            tokens.append(('\n'.join(value), True))
            continue
        pattern = r"(?:'[^']*'(?=\s|$)|\"[^\"]*\"(?=\s|$)|[^\s]+)"
        for match in re.finditer(pattern, line):
            value = match.group()
            if value.startswith('#'):
                break
            quoted = value[:1] in ('\"', "'")
            tokens.append((value[1:-1] if quoted else value, quoted))
    categories, i = {}, 0
    def control(token):
        return not token[1] and (token[0].startswith(('_', 'data_', 'save_')) or token[0] in ('loop_', 'stop_'))
    while i < len(tokens):
        value, quoted = tokens[i]
        if not quoted and value == 'loop_':
            i += 1
            columns = []
            while i < len(tokens) and tokens[i][0].startswith('_') and not tokens[i][1]:
                columns.append(tokens[i][0]); i += 1
            require(columns and len({c.split('.')[0] for c in columns}) == 1, 'mmCIF循环类别不完整')
            values = []
            while i < len(tokens) and not control(tokens[i]):
                values.append(tokens[i][0]); i += 1
            require(len(values) % len(columns) == 0, 'mmCIF循环行长度不一致')
            name = columns[0].split('.')[0]
            categories.setdefault(name, []).extend(dict(zip([c.split('.', 1)[1] for c in columns], values[n:n+len(columns)])) for n in range(0, len(values), len(columns)))
        elif not quoted and value.startswith('_'):
            require(i+1 < len(tokens) and not control(tokens[i+1]), 'mmCIF字段缺值')
            category, key = value.split('.', 1)
            rows = categories.setdefault(category, [{}])
            require(len(rows) == 1, 'mmCIF重复类别冲突')
            rows[0][key] = tokens[i+1][0]; i += 2
        else:
            i += 1
    return categories


def candidate_key(origin):
    """结构键绑定原字节和全部原方案，不接受客户端路径或方案覆盖。"""
    return fingerprint({'cif': origin['cif'], 'spec': origin['spec']})


def _identity(atom):
    """参考使用作者链、作者残基号及插入码，与冻结准备器一致。"""
    insertion = atom.get('pdbx_PDB_ins_code', '?')
    return (atom.get('auth_comp_id', atom.get('label_comp_id')), atom.get('auth_asym_id'),
        atom.get('auth_seq_id', '') + (insertion if insertion not in ('.', '?') else ''))


def discover(root, connection, selected_keys=None):
    """列出可见共结构小分子及拒绝原因；从不自动选择或宣称位点通过。"""
    output = []
    for receptor in connection.get('receptors', []):
        for origin in receptor.get('candidates', []):
            spec = origin['spec']
            if spec.get('source_type') != 'experimental':
                continue
            if selected_keys is not None and (receptor['target_id'], candidate_key(origin)) not in selected_keys:
                continue
            text = verified_file(root, origin['cif']).read_text('utf-8')
            tables = cif_categories(text)
            entry = tables.get('_entry', [{}])[0].get('id', '').upper()
            require(entry == spec['pdb_id'].upper(), '共晶候选原件PDB身份不符')
            atoms = tables.get('_atom_site', [])
            nonpoly = {r['entity_id']: r for r in tables.get('_pdbx_entity_nonpoly', [])}
            metadata = {r['id']: r for r in tables.get('_chem_comp', [])}
            heavy = [a for a in atoms if a.get('type_symbol', '').upper() not in ('H', 'D') and a.get('label_alt_id', '.') in ('.', '?', spec.get('altloc'))]
            groups = {}
            for atom in heavy:
                if atom.get('label_entity_id') in nonpoly:
                    groups.setdefault(_identity(atom), []).append(atom)
            protein = [a for a in heavy if a.get('auth_asym_id') in spec['chains'] and a.get('label_seq_id', '.') not in ('.', '?')]
            for identity, actual in sorted(groups.items()):
                code, chain, sequence = identity
                # 水、单原子离子和极小分子仍保留在原CIF；不把数千水分子列成参考候选。
                if len(actual) < 8 or not any(a.get('type_symbol', '').upper() == 'C' for a in actual):
                    continue
                name = metadata.get(code, {}).get('name') or nonpoly[actual[0]['label_entity_id']].get('name', code)
                key = fingerprint({'candidate_key': candidate_key(origin), 'reference': identity})
                covalent = []
                for row in tables.get('_struct_conn', []):
                    if not row.get('conn_type_id', '').startswith(('covale', 'disulf', 'modres')):
                        continue
                    for side in ('ptnr1', 'ptnr2'):
                        # 使用作者编号时不猜测标签编号；未知映射保守拒绝。
                        if row.get(side+'_label_comp_id') == code and (row.get(side+'_auth_asym_id') == chain or row.get(side+'_label_asym_id') == actual[0].get('label_asym_id')):
                            covalent.append(row)
                            break
                reasons = []
                if code in ADDITIVES or re.search(r'polyethylene|glycerol|buffer|ethylene glycol', name, re.I):
                    reasons.append('水、离子、常见添加剂或糖组分，不自动作为参考配体')
                if covalent:
                    reasons.append('存在共价连接，不能进入非共价重对接')
                if len({a.get('pdbx_PDB_model_num', '1') for a in atoms}) != 1:
                    reasons.append('原件多模型，未核定模型')
                if len(chain or '') != 1 or not re.fullmatch(r'-?\d+[A-Za-z]?', sequence):
                    reasons.append('作者链或残基号不适用于现有工具')
                if not re.fullmatch(r'[A-Za-z0-9]{1,3}', code or ''):
                    reasons.append('组件编号超过现有PDB准备工具的3位范围，不能截断身份采用')
                if len({a.get('label_atom_id') for a in actual}) != len(actual):
                    reasons.append('配体原子存在未解决替代构象或重复')
                distance = None
                try:
                    def xyz(a):
                        result = tuple(float(a[k]) for k in ('Cartn_x', 'Cartn_y', 'Cartn_z'))
                        require(all(math.isfinite(x) for x in result), '原坐标非有限数')
                        return result
                    pp, ll = [xyz(a) for a in protein], [xyz(a) for a in actual]
                    distance = min((math.dist(a, b) for a in pp for b in ll), default=None)
                    if distance is None or distance > 5:
                        reasons.append('未在所选受体链5Å邻域，不推荐作为该链参考')
                except (KeyError, ValueError):
                    reasons.append('配体或蛋白坐标无法核对')
                output.append({'target_id': receptor['target_id'], 'symbol': receptor['symbol'],
                    'candidate_key': candidate_key(origin), 'reference_key': key,
                    'pdb_id': entry, 'chains': spec['chains'], 'component_id': code,
                    'reference_chain': chain, 'reference_sequence': sequence, 'name': name,
                    'selectable': not reasons, 'reason_zh': '；'.join(reasons) if reasons else '仅候选；须核定其为本受体非共价参考配体，原子完整性、拓扑及环境仍由旧准备和重对接检查',
                    'heavy_atom_count': len(actual), 'minimum_distance_A': distance,
                    'role_status': 'requires_user_target_and_non_covalent_role_confirmation',
                    'covalent_count': len(covalent), 'source_url': 'https://www.rcsb.org/structure/'+entry,
                    'component_url': 'https://www.rcsb.org/ligand/'+code,
                    'evidence': origin['cif'], 'covalent_evidence': covalent})
    return output


def validate_choices(root, connection, choices):
    """每个受体至多一个明确方案；重算候选与指纹，拒绝跨版本及客户端路径。"""
    require(isinstance(choices, list), 'reference_choices必须是列表')
    for choice in choices:
        require(isinstance(choice, dict) and set(choice) == {'target_id', 'candidate_key', 'reference_key'}, '共晶选择只能提交目标和两个稳定编号')
        require(all(isinstance(v, str) for v in choice.values()), '共晶稳定编号必须是字符串')
    if not choices:
        return []
    wanted = {(r['target_id'], r['candidate_key']) for r in choices}
    available = {(r['target_id'], r['candidate_key'], r['reference_key']): r for r in discover(root, connection, wanted)}
    selected, targets = [], set()
    for choice in choices:
        key = (choice['target_id'], choice['candidate_key'], choice['reference_key'])
        require(key in available and available[key]['selectable'], '共晶选择已失效、跨结构或不符合非共价候选条件')
        require(choice['target_id'] not in targets, '一个受体只能核定一个共晶参考方案')
        targets.add(choice['target_id']); selected.append(available[key])
    return selected


def apply_choices(root, connection, choices):
    """只在本次内存副本派生已核定参考方案，连接原件和旧授权保持。"""
    selected = validate_choices(root, connection, choices)
    value = deepcopy(connection)
    for choice in selected:
        row = next(r for r in value['receptors'] if r['target_id'] == choice['target_id'])
        original = next(c for c in row['candidates'] if candidate_key(c) == choice['candidate_key'])
        explicit = deepcopy(original)
        explicit['spec'].update(pocket='reference', reference_code=choice['component_id'],
            reference_chain=choice['reference_chain'], reference_sequence=choice['reference_sequence'])
        # 拓扑和实际原子完整性由冻结prepare_reference_ligand再次核对；此处不以摘要代替。
        explicit['reference_audit'] = {'reference_count_matches': False, 'reference_covalent_count': 0}
        explicit['reference_choice'] = choice
        row['candidates'] = [explicit] + row['candidates']
    return value

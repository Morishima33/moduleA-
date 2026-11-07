"""来源身份补救：复用旧精确编号核验，内部编号不冒充数据库编号。"""
from copy import deepcopy
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote

from contracts import require
from storage import verified_file
from .compound_recovery import PUBCHEM, normalized_name, parse_tcmsp

VERSION = 'A06.compound_sources.2'
KEY = re.compile(r'[A-Z]{14}-[A-Z]{10}-[A-Z]')
STAGES = {'name': '名称定位', 'identity': '来源身份核验', 'source_3d': '官方三维下载',
          'coordinate_identity': '三维坐标身份核验', 'preparation': '配体参数化',
          'receptor_source': '受体来源', 'pocket_environment': '口袋与必要环境质控'}


class SourceFailure(ValueError):
    """保留实际失败阶段与可重试性，不将无结果解释为结合差。"""
    def __init__(self, stage, code, detail, retryable=False):
        self.stage, self.code, self.retryable = stage, code, retryable
        super().__init__(STAGES[stage] + '失败：' + str(detail))


def diagnosis(error, stage):
    """机器字段与中文原因同源；未知错误不猜测为永久缺失。"""
    if isinstance(error, SourceFailure):
        return {'failure_stage': error.stage, 'failure_code': error.code,
                'retryable': error.retryable, 'reason_zh': str(error)}
    transient = isinstance(error, (TimeoutError, ConnectionError, URLError))
    if isinstance(error, HTTPError):
        transient = error.code in (429, 500, 502, 503, 504)
    return {'failure_stage': stage, 'failure_code': 'request_failed' if transient else 'validation_failed',
            'retryable': transient, 'reason_zh': STAGES[stage] + '失败：' + str(error)}


def _cid(value):
    """来源字段必须明确给出一个正整数CID，不拆分候选列表。"""
    value = str(value or '').strip()
    require(not value or re.fullmatch(r'[1-9][0-9]*', value), '原来源CID不是单一有效编号')
    return int(value) if value else None


def _consistent(rows):
    """保留全部来源，但完整结构键、分子式或明确CID冲突不能择优。"""
    keys = {str(r.get('inchikey') or '').strip() for r in rows} - {''}
    formulas = {str(r.get('formula') or '').strip() for r in rows} - {''}
    cids = {_cid(r.get('pubchem_id')) for r in rows} - {None}
    require(all(KEY.fullmatch(k) for k in keys), '原来源完整InChIKey格式无效')
    require(len(keys) <= 1 and len(formulas) <= 1 and len(cids) <= 1,
            '本批来源完整结构键、分子式或CID相互冲突，不能自动选取')
    return next(iter(keys), None), next(iter(formulas), None), next(iter(cids), None)


def resolve(row, fetch, identities):
    """只采用本批精确来源、唯一CID和原始三维；不生成构象、不改形态。"""
    from docking_audit import ligand_identity
    stage = 'identity'
    origin = deepcopy(identities)
    evidence, method, original_id = [], 'archived_source_identity', None
    name_checked = False
    try:
        expected_key, formula, cid = _consistent(origin)
        # 已归档身份缺失时才按原HERB编号补查，响应身份须与来源一致。
        if not expected_key and cid is None:
            for item in list(origin):
                if item.get('source') != 'HERB':
                    continue
                identifier = item.get('source_id', '')
                require(re.fullmatch(r'HBIN[0-9]+', identifier), 'HERB原成分编号无效')
                if not hasattr(fetch, 'herb_detail'):
                    continue
                detail, ref = fetch.herb_detail(identifier)
                summary = detail.get('summary', [])
                require(len(summary) == 2 and len(summary[0]) == len(summary[1]), 'HERB详情字段改变')
                values = dict(zip(summary[0], summary[1]))
                text = lambda value: str(value.get('title', '') if isinstance(value, dict) else value or '').strip()
                require(text(values.get('Ingredient id')) == identifier, 'HERB返回其他成分编号')
                require(normalized_name(text(values.get('Ingredient name'))) == normalized_name(item['name']),
                        'HERB详情与原来源名称不一致')
                origin.append(dict(item, inchikey=text(values.get('InChIKey')),
                                   formula=text(values.get('Molecule formula')) or item.get('formula', ''),
                                   pubchem_id=text(values.get('PubChem id')),
                                   tcmsp_id=text(values.get('TCMSP id'))))
                evidence.append(ref)
            expected_key, formula, cid = _consistent(origin)
        # 旧TCMSP解析器保留编号、原名称和完整立体身份三个约束。
        if not expected_key and cid is None:
            candidates = []
            for item in origin:
                identifier = item.get('source_id') if item.get('source') == 'TCMSP' else item.get('tcmsp_id')
                if identifier:
                    require(re.fullmatch(r'MOL[0-9]{6}', str(identifier)), 'TCMSP原成分编号无效')
                    candidates.append((str(identifier), item.get('name') or row['name']))
            for identifier, original_name in sorted(set(candidates)):
                url = 'https://old.tcmsp-e.com/molecule.php?qn=' + str(int(identifier[3:]))
                raw, ref = fetch.get(url, 'html')
                html = raw if isinstance(raw, str) else verified_file(fetch.root, ref).read_text('utf8')
                parsed = parse_tcmsp(html, {'compound_id': identifier, 'name': original_name})
                origin.append({'source': 'TCMSP', 'source_id': identifier, 'name': original_name,
                               'inchikey': parsed['inchikey'], 'pubchem_id': parsed.get('pubchem_cid', '')})
                evidence.append(ref); original_id = identifier; method = 'tcmsp_exact_identity'
            expected_key, formula, cid = _consistent(origin)
        if cid is None:
            stage = 'identity' if expected_key else 'name'
            query = 'inchikey/' + expected_key if expected_key else 'name/' + quote(row['name'], safe='')
            ids, ref = fetch.get(PUBCHEM + query + '/cids/JSON')
            cids = ids.get('IdentifierList', {}).get('CID', [])
            require(len(cids) == 1, '检索未定位唯一CID，保留身份待核')
            cid = cids[0]; evidence.append(ref)
            if not expected_key:
                method = 'unique_approved_name'
                name_checked = True
        require(type(cid) is int and cid > 0, 'CID编号无效')
        stage = 'identity'
        if not expected_key and origin and not name_checked:
            # 无完整来源结构键时，已能唯一定位的原名称不得指向另一CID。
            # 名称404才允许沿精确来源编号补救；临时网络失败不能当作无冲突。
            try:
                named, ref = fetch.get(PUBCHEM + 'name/' + quote(row['name'], safe='') + '/cids/JSON')
                named_ids = named.get('IdentifierList', {}).get('CID', [])
                require(not named_ids or cid in named_ids, '原名称与来源明确CID冲突，不能自动替换分子')
                evidence.append(ref)
            except HTTPError as error:
                if error.code != 404:
                    raise
        props, properties = fetch.get(PUBCHEM + f'cid/{cid}/property/InChIKey,MolecularFormula/JSON')
        values = props.get('PropertyTable', {}).get('Properties', [])
        require(len(values) == 1 and values[0].get('CID') == cid, '官方属性与精确CID不同')
        key = values[0].get('InChIKey', '')
        require(KEY.fullmatch(key) and (not expected_key or key == expected_key), '官方完整立体身份与来源不一致')
        require(not formula or values[0].get('MolecularFormula') == formula, '官方分子式与原来源不一致')
        stage = 'source_3d'
        _, sdf = fetch.get(PUBCHEM + f'cid/{cid}/SDF?record_type=3d', 'sdf')
        stage = 'coordinate_identity'
        audit = ligand_identity(verified_file(fetch.root, sdf).read_text('utf8'), cid, key)
        return {**row, 'name_zh': row['name'], 'cid': cid, 'identity_matched': True,
                'audit': audit, 'properties': properties, 'sdf': sdf, 'state': 'connected',
                'identity_resolution': {'version': VERSION, 'method': method, 'original_source_id': original_id,
                                        'sources': origin, 'files': evidence},
                'identity_basis_zh': '本批原来源、唯一CID、完整InChIKey及官方原始三维核验；未生成坐标或替换形态'}
    except (ValueError, KeyError, TypeError, OSError) as error:
        if isinstance(error, SourceFailure):
            raise
        retryable = diagnosis(error, stage)['retryable']
        missing = {'source_3d': 'official_3d_unavailable', 'name': 'name_not_found'}
        code = missing.get(stage, 'official_identity_unavailable') \
            if isinstance(error, HTTPError) and error.code == 404 else ('request_failed' if retryable else 'identity_unresolved')
        raise SourceFailure(stage, code, error, retryable) from error


def structure_counts(rows):
    """来源行与实际核实结构分别计数，不改固定范围或候选次序。"""
    keys = []; verified_records = 0; total_records = 0
    for row in rows:
        count = len(row['original_sources']) if 'original_sources' in row else 1
        total_records += count
        key = row.get('preparation', {}).get('identity', {}).get('inchi_key')
        if row.get('state') == 'ready' and isinstance(key, str) and KEY.fullmatch(key):
            keys.append(key)
            verified_records += count
    return {'source_record_count': total_records, 'verified_structure_count': len(set(keys)),
            'verified_record_count': verified_records, 'pending_structure_records': total_records - verified_records}

"""第三版来源修复：名称失败后回查本条TCMSP身份，不更换异构体或生成坐标。"""
import json
import re
import unicodedata
from urllib.error import HTTPError
from urllib.parse import quote

from contracts import require
from storage import verified_file

VERSION = 'A06.compound_identity.1'
PUBCHEM = 'https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/'


def normalized_name(value):
    """仅统一Unicode及空白，不删除立体标记、位置或官能团。"""
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


def parse_tcmsp(text, row):
    """只解析官方页面明确的JSON记录；主页、错号和名字改变都拒绝。"""
    match = re.findall(r'\bvar\s+mol\s*=\s*(\[.*?\])\s*;', text, re.S)
    require(len(match) == 1, 'TCMSP身份资料未返回唯一分子记录，不能从主页猜测CID')
    values = json.loads(match[0])
    require(isinstance(values, list) and len(values) == 1, 'TCMSP分子记录不唯一')
    value = values[0]
    require(value.get('MOL_ID') == row['compound_id'] and
            str(value.get('molecule_ID')) == str(int(row['compound_id'][3:])), 'TCMSP分子编号不一致')
    require(normalized_name(value.get('molecule_name', '')) == normalized_name(row['name']),
            'TCMSP名称与本研究来源不一致，保留身份待核对')
    require(re.fullmatch(r'[A-Z]{14}-[A-Z]{10}-[A-Z]', value.get('inchikey', '')),
            'TCMSP缺少完整立体化学身份InChIKey')
    cid = str(value.get('pubchem_cid', '')).strip()
    require(not cid or bool(re.fullmatch(r'[1-9][0-9]*', cid)), 'TCMSP的CID不是单一有效编号')
    return value


def compound_source(row, fetch):
    """记录精确定位、属性匹配、原始三维下载和坐标身份核验各个阶段。"""
    from docking_audit import ligand_identity
    stage = '名称检索'
    try:
        evidence, expected_key = None, None
        name_failure = None
        try:
            ids, _ = fetch.get(PUBCHEM + 'name/' + quote(row['name'], safe='') + '/cids/JSON')
            cids = ids.get('IdentifierList', {}).get('CID', [])
            if len(cids) != 1:
                name_failure = '名称未定位唯一CID'
        except HTTPError as error:
            if error.code != 404:
                raise
            cids, name_failure = [], 'PubChem名称查询404'
        if name_failure:
            stage = '来源身份回查'
            require(re.fullmatch(r'MOL[0-9]{6}', row['compound_id']),
                    '缺少可回查的TCMSP稳定编号，不能猜测身份')
            url = 'https://old.tcmsp-e.com/molecule.php?qn=' + str(int(row['compound_id'][3:]))
            html, record = fetch.get(url, 'html')
            if not isinstance(html, str):
                html = verified_file(fetch.root, record).read_text('utf-8')
            origin = parse_tcmsp(html, row)
            expected_key = origin['inchikey']
            cid = str(origin.get('pubchem_cid', '')).strip()
            if not cid:
                ids, key_record = fetch.get(PUBCHEM + 'inchikey/' + expected_key + '/cids/JSON')
                cids = ids.get('IdentifierList', {}).get('CID', [])
                require(len(cids) == 1, '完整InChIKey未定位唯一CID，保留待核对')
            else:
                cids, key_record = [int(cid)], None
            evidence = {'version': VERSION, 'method': 'tcmsp_exact_identity',
                        'original_failure': name_failure, 'source_url': url, 'source_file': record,
                        'inchikey_lookup_file': key_record, 'expected_inchikey': expected_key,
                        'compound_id': row['compound_id']}
        cid = cids[0]
        require(isinstance(cid, int) and not isinstance(cid, bool) and cid > 0, 'CID编号无效')
        stage = '化学身份核对'
        props, properties = fetch.get(PUBCHEM + f'cid/{cid}/property/InChIKey,MolecularFormula/JSON')
        values = props.get('PropertyTable', {}).get('Properties', [])
        require(len(values) == 1 and values[0].get('CID') == cid, '官方化学身份响应不一致')
        key = values[0]['InChIKey']
        require(expected_key is None or key == expected_key,
                'TCMSP与PubChem完整立体化学身份不一致，不自动替换分子')
        stage = '三维下载'
        _, sdf = fetch.get(PUBCHEM + f'cid/{cid}/SDF?record_type=3d', 'sdf')
        stage = '三维坐标身份核对'
        audit = ligand_identity(verified_file(fetch.root, sdf).read_text('utf-8'), cid, key)
        return {**row, 'name_zh': row['name'], 'cid': cid, 'identity_matched': True,
                'audit': audit, 'sdf': sdf, 'properties': properties, 'state': 'connected',
                'identity_resolution': evidence or {'version': VERSION, 'method': 'unique_approved_name'},
                'identity_basis_zh': '唯一官方CID、完整InChIKey与原始三维坐标一致；未生成坐标或替换异构体'}
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise ValueError(f'{stage}失败：{error}') from error

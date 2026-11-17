"""救援展示名称的可读性检查；不据字段名称推定中文或结构身份已核验。"""
from copy import deepcopy
import re
from urllib.parse import urlsplit

from contracts import require

CATALOG_VERSION = 'ModuleA.rescue_display_name_catalog.1'


def chinese_name(value):
    """返回实际中文名称；英文假中文和已有禁止占位文字均不作为核译完成。"""
    from science_modules.a07.plan_translations_v2 import PLACEHOLDER
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if not re.search(r'[\u3400-\u9fff]', value) or PLACEHOLDER.search(value):
        return ''
    return value


def checked_catalog(catalog):
    """只接稳定编号和明确原名的人工核译目录；不接受重号、英文假中文或隐式原专名豁免。"""
    require(isinstance(catalog, dict) and catalog.get('schema_version') == CATALOG_VERSION
            and isinstance(catalog.get('entries'), list), '名称目录协议或条目格式错误')
    index = {}
    for row in catalog['entries']:
        require(isinstance(row, dict) and isinstance(row.get('identity'), dict), '名称目录缺少稳定身份')
        identity = row['identity']
        scheme, identifier = identity.get('scheme'), identity.get('id')
        scope = row.get('scope')
        require((scheme == 'PubChem' and isinstance(identifier, str) and re.fullmatch('[1-9][0-9]*', identifier)
                 and scope == 'prepared_identity_translation') or
                (scheme == 'HERB' and isinstance(identifier, str) and re.fullmatch('HBIN[0-9]+', identifier)
                 and scope in ('source_term_translation_only', 'original_name_requires_user_decision')),
                '名称目录的稳定编号或核译范围不同')
        key = scheme, identifier
        require(key not in index, '名称目录稳定编号重复')
        aliases = row.get('source_names')
        require(isinstance(aliases, list) and aliases and all(isinstance(value, str) and value.strip() for value in aliases)
                and len({value.strip().casefold() for value in aliases}) == len(aliases), '名称目录原名缺失或重复')
        require(isinstance(row.get('translation_basis'), str) and row['translation_basis'].strip(), '名称目录缺少核译依据')
        links = row.get('sources')
        require(isinstance(links, list) and links and all(isinstance(link, dict) and link.get('label')
                and isinstance(link.get('url'), str) and urlsplit(link['url']).scheme in ('https', 'http')
                and urlsplit(link['url']).netloc for link in links), '名称目录缺少明确来源链接')
        if scope == 'original_name_requires_user_decision':
            require(row.get('display_name_zh') == '', '需要原专名决定的条目不能冒充已核中文')
        else:
            require(chinese_name(row.get('display_name_zh')), '名称目录仍缺中文或含占位文字')
        index[key] = deepcopy(row)
    return index


def derive_names(basis, catalog, *, allowed_original_names=None):
    """仅用外层已核的同批准备和原HERB证据派生标签；原专名允许范围须由外层核真实决定。"""
    index = checked_catalog(catalog)
    fixed, prepared_rows = basis['compounds'], basis['prepared']
    ids = [row['compound_id'] for row in fixed]
    require(ids and len(ids) == len(set(ids)) and [row['compound_id'] for row in prepared_rows] == ids,
            '名称证据的准备对象与固定范围或顺序不同')
    require(isinstance(basis.get('evidence'), list) and basis['evidence'], '名称证据缺少原输入和准备引用')
    prepared = {row['compound_id']: row for row in prepared_rows}
    allowed = set(allowed_original_names or ())
    names, missing, details, original_ids = [], [], [], set()
    for source in fixed:
        cid = source['compound_id']
        en = source.get('name_en') or source.get('name') or cid
        require(isinstance(en, str) and en.strip(), '原成分名称格式错误')
        entry, identity = None, {}
        evidence = deepcopy(basis['evidence'])
        current = prepared[cid]
        if current.get('state') == 'ready':
            number = current.get('cid')
            if type(number) is int and number > 0:
                identity = {'scheme': 'PubChem', 'id': str(number)}
                entry = index.get(('PubChem', str(number)))
        elif current.get('state') == 'NA':
            sources = basis.get('herb_sources', {}).get(cid, [])
            if sources and all(isinstance(row.get('name'), str) and row['name'].strip().casefold() == en.strip().casefold()
                               for row in sources) and len({row.get('id') for row in sources}) == 1:
                identifier = sources[0].get('id')
                identity = {'scheme': 'HERB', 'id': identifier}
                entry = index.get(('HERB', identifier))
                evidence.extend(deepcopy(row['file']) for row in sources)
        if entry and en.strip().casefold() not in {value.strip().casefold() for value in entry['source_names']}:
            entry = None
        row = {'compound_id': cid, 'source_name': en, 'display_name_zh': '', 'scope': 'unresolved',
               'identity': identity, 'evidence': evidence, 'translation_basis': '', 'translation_status': 'missing'}
        reason = '缺少与本批原名和稳定编号一致的名称证据'
        if entry:
            row.update(display_name_zh=entry['display_name_zh'], scope=entry['scope'],
                       translation_basis=entry['translation_basis'], catalog_sources=deepcopy(entry['sources']),
                       translation_status='checked' if current['state'] == 'ready' else 'source_term_translated')
            if entry['scope'] == 'original_name_requires_user_decision':
                original_ids.add(cid)
                row.update(scope='original_proper_name', translation_status='original_name_requires_user_decision')
                reason = '需要明确允许保留这一条原来源专名，不能冒充中文核译'
                if cid in allowed:
                    row['translation_status'] = 'original_term_retained'
            else:
                reason = ''
        if reason and not (entry and entry['scope'] == 'original_name_requires_user_decision' and cid in allowed):
            missing.append(cid)
            details.append({'compound_id': cid, 'reason_zh': reason})
        names.append(row)
    require(allowed <= original_ids, '原专名允许范围不是本批有明确原术语证据的待决定对象')
    return {'names': names, 'missing_ids': missing, 'blockers': details, 'allowed_original_name_ids': sorted(allowed)}

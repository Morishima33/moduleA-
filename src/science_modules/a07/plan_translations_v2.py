"""报告二版独立核译补充与可读性门控；旧全局词典、统计和历史快照保持。"""
from copy import deepcopy
from pathlib import Path
import json
import re

from contracts import require
from science_modules.a05 import display as original

VERSION = 'A07.plan_translation.2'
SUPPLEMENT = Path(__file__).with_name('term_translation_supplement_v2.json')
PLACEHOLDER = re.compile(r'中文待核(?:译)?|待核译|待翻译')


def merged_lexicon():
    """读取原词典加独立补充；不原地更新旧词典或研究已归档快照。"""
    entries = json.loads(original.LEXICON.read_text(encoding='utf-8'))
    additions = json.loads(SUPPLEMENT.read_text(encoding='utf-8'))
    for key, entry in additions.items():
        require((re.fullmatch(r'GO:\d{7}', key) or re.fullmatch(r'hsa\d{5}', key))
                and all(entry.get(k) for k in ('english', 'zh', 'source', 'translation_basis')),
                '报告译名补充缺少编号、原文、中文或核译依据')
        require(key not in entries or entries[key]['english'] == entry['english'], '补充译名与既有英文编号冲突')
        entries[key] = deepcopy(entry)
    return entries


def checked_translation(row, entries):
    """稳定编号和本批英文均匹配才返回译名，未知条目不猜译。"""
    entry = entries.get(row['ID'], {})
    require(entry.get('english') == original.english(row) and isinstance(entry.get('zh'), str) and entry['zh'].strip()
            and entry.get('source') and entry.get('translation_basis'), '缺少匹配本批英文的中文核译：' + row['ID'])
    require(not PLACEHOLDER.search(entry['zh']), '中文核译仍含占位文字：' + row['ID'])
    return deepcopy(entry)


def check_readability(payload):
    """在绘图和交付前检查实际表图条目及所有可见文字，缺译不发布最终文件。"""
    facts = payload.get('enrichment')
    if facts:
        require(not facts.get('pending_translations'), '实际展示条目仍缺中文核译：' + '、'.join(facts['pending_translations']))
        missing = set()
        for rows in facts.get('tables', {}).values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and row.get('ID') and ('english' in row or 'Description' in row):
                    if not (row.get('chinese') or row.get('description_zh')):
                        missing.add(row['ID'])
        require(not missing, '实际正文或附录条目缺少中文核译：' + '、'.join(sorted(missing)))
    def visit(value):
        """扫描事实文本，不将原始二进制文件或不可见科学原件当作展示正文。"""
        if isinstance(value, str):
            require(not PLACEHOLDER.search(value), '交付内容仍含未完成核译的占位文字')
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit({key: value for key, value in payload.items() if key not in ('source_evidence', 'translation_audit')})
    return True

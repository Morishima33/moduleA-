"""新方案A05契约桥接；只读资格和版本保护不依赖R或第三方科学库。"""
from science_modules.a05.plan_contract import FIELDS, info, is_current as original_is_current, validate


def is_current(workflow,manifest):
    """显式中文修订版同样拒绝旧报告/continue；冻结第一版契约文件不回写。"""
    rid=manifest.get('current',{}).get('A05')
    return original_is_current(workflow,manifest) or bool(rid and workflow.run(manifest,rid)['config'].get('version')=='A05.plan_enrichment.2')

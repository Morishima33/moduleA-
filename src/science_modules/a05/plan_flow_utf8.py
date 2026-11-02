"""A05显式第二版：R中文常量用Unicode转义，原统计和第一版实现保持。"""
import hashlib
from pathlib import Path
from types import FunctionType

from . import plan_flow as original

VERSION='A05.plan_enrichment.2'
SCRIPT=Path(__file__).with_name('plan_enrichment_utf8.R')
TEXT_RULE='R.unicode_literals.1'
parameters=original.parameters
groups=original.groups
read_source=original.read_source
# 注释/背景仍使用原不可变注释来源；只有analyze的中文常量修复，不新增联网导出。
source_snapshot=original.source_snapshot
_namespace=dict(vars(original),__file__=__file__,VERSION=VERSION,SCRIPT=SCRIPT)


def _bind(name):
    """复用冻结第一版函数代码，仅在独立命名空间绑定新脚本，不改原全局变量。"""
    function=getattr(original,name)
    return FunctionType(function.__code__,_namespace,function.__name__,function.__defaults__,function.__closure__)


def configuration(plan):
    """新协议同时固定适配器、原函数、原R脚本和Unicode脚本全部实现字节。"""
    config=_bind('configuration')(plan)
    config['text_encoding_rule']=TEXT_RULE
    config['implementation_sha256'].update({path.name:hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (Path(original.__file__),original.SCRIPT,Path(__file__).parents[2]/'modulea/core/plan_a05_text.py')})
    return config


_namespace['configuration']=configuration
r_call=_bind('r_call')
_namespace['r_call']=r_call
evaluate=_bind('evaluate')
_namespace['evaluate']=evaluate
facts=_bind('facts')
_namespace['facts']=facts


def validator(root,fallback):
    """第二版仍逐件核验原件并实际R复算；第一版和其他版本交原校验器。"""
    bound=_bind('validator')(root,fallback)
    def check(run,*args):
        if run['config'].get('version')==VERSION:
            from modulea.core.analysis_plans import AnalysisPlanWorkflow
            from modulea.core.plan_a05_text import validate_run
            workflow=AnalysisPlanWorkflow(root);validate_run(workflow,workflow.load(run['study_id']),run)
        return bound(run,*args)
    return check

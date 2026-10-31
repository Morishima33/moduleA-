"""系统结构结果页读取本运行固定范围；不调用旧执行器或改动研究事实。"""
from contracts import require
from storage import read_json,verified_file
from ..presenters.system_docking import VERSIONS,present


def apply(workflow,manifest,run,result,response):
    """系统1/2版均使用自己的固定名单，历史页保留原复核只读规则。"""
    require(run['config'].get('version') in VERSIONS and run['study_id']==manifest['study_id'],
        '系统结构展示版本或研究不同')
    fixed=read_json(verified_file(workflow.location(manifest['study_id']),run['inputs']['system_input_ref']))
    require(fixed['study_id']==manifest['study_id'] and fixed['stage']=='A06_INPUT'
        and fixed['binding']['batch_file']==run['batch_file']
        and fixed['payload']['input_key']==result['summary']['input_key'],'系统结构展示固定范围不同')
    response.update(present(result,fixed['payload']))
    for key in ('automatic_docking','docking_trial','docking_coverage','docking_preparation','docking_candidates',
        'docking_review','docking_artifacts','reference_qualification','scoring_readiness','review_packet',
        'review_gate','reviewable_preparation','plan_scoring','plan_selection_ui','plan_preparation_ui'):
        response[key]=None
    response['review']['continue'].update(available=False,note_zh='本批科学计算从统一执行与续做入口接续，人工复核决定单独保存。')

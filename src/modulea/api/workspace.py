"""同页研究与模块只读组装；本请求共用一次原Workflow快照及完整SHA范围。"""
from urllib.parse import parse_qs,urlsplit

from contracts import ContractError,require
from ..core.read_archive import SnapshotFlight
from ..core.read_evidence import current_evidence,read_call
from .errors import ApiError,from_contract
from .views import Views


class _PageViews(Views):
    """每个HTTP请求独立创建，缓存不离开当前线程/研究/证据范围。"""
    def __init__(self,kernel,tasks,study_id,evidence):
        super().__init__(kernel,tasks)
        self.study_id=study_id;self.evidence=evidence;self.snapshot=None

    def _snapshot(self,study_id):
        """调用原快照一次；给两个原Views方法独立容器，不重写状态规则。"""
        if study_id!=self.study_id or current_evidence(self.kernel.settings.data_root) is not self.evidence:
            return super()._snapshot(study_id)
        if self.snapshot is None:
            workflow,view,error=super()._snapshot(study_id)
            self.snapshot=(workflow,SnapshotFlight._clone(view),error)
        workflow,view,error=self.snapshot
        return workflow,SnapshotFlight._clone(view),error


def build(app,study_id,module_id,run_id,include_rescue=False):
    """先原研究框架，再原模块；模块选择错误保持在模块区，退出SHA失败仍整体拒绝。"""
    evidence=current_evidence(app.settings.data_root)
    if evidence is None:
        # 缺研究的scope按原规则为disabled，先沿原manifest入口给404；存在研究仍禁止无scope组装。
        app.views._manifest(study_id)
    require(evidence is not None and evidence.study_id==study_id,'同页读取必须在本研究证据范围内')
    views=_PageViews(app.kernel,app.tasks,study_id,evidence)
    study=read_call(views.study,study_id)
    if module_id is None:
        next_step=study.get('next_step') or {}
        first=(study.get('nav') or [{}])[0].get('modules') or [{}]
        module_id=next_step.get('module_id') or first[0].get('module_id')
    module=None;error=None
    if module_id:
        try:module=read_call(views.module,study_id,module_id,run_id)
        except (ApiError,ContractError) as failure:
            if isinstance(failure,ContractError):failure=from_contract(str(failure))
            error={'status':failure.status,**failure.body()['error']}
    if include_rescue and module_id == 'A06' and module:
        special = module.get('special') or {}
        rescue = special.get('system_rescue') or {}
        run = module.get('run') or {}
        if rescue.get('presentation_url') and run.get('run_id'):
            from .rescue_presentations import read_directory
            try:
                directory = read_directory(app, study_id, run['run_id'], include_current=True,
                                           page_snapshot=views.snapshot)
                special['rescue_presentation'] = {'directory': directory}
            except ApiError as failure:
                special['rescue_presentation'] = {'error_zh': failure.body()['error']['message_zh']}
    return {'study':study,'module':module,'module_error':error}


def get(app,request,study_id):
    """仅当前新端点保留空查询以严格校验，不改变原Request的解析约定。"""
    query=parse_qs(urlsplit(request.handler.path).query,keep_blank_values=True)
    if (set(query)-{'module_id','run_id','include_rescue'} or
            any(len(values)!=1 or not values[0].strip() for values in query.values()) or
            query.get('include_rescue', ['1']) != ['1']):
        raise ApiError(422,'VALIDATION_FAILED','同页读取参数缺失、重复或越界')
    return app._json_read(study_id,build,app,study_id,
        query.get('module_id',[None])[0],query.get('run_id',[None])[0],'include_rescue' in query)

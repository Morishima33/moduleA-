"""原生A06的只读条件和明确提交；HTTP不加载科学库或运行工具。"""
import json
import platform

from contracts import ContractError,require
from storage import new_id,read_json
from modulea.core import native_execution as core
from modulea.core.bounded_evidence import digest_file,verified_file
from .errors import ApiError,from_contract


def configuration_blockers(settings):
    """只核本机配置存在；完整版本/源码/依赖SHA由隔离worker执行前核验。"""
    reasons=[]
    if not settings.tools_profile or not settings.tools_profile.is_file():reasons.append('尚未生成本机原生工具配置')
    else:
        try:
            value=read_json(settings.tools_profile)
            machine={'AMD64':'x86_64','aarch64':'arm64'}.get(platform.machine(),platform.machine())
            require(value['science_protocol']==core.SCORING and value['system']==platform.system()
                and value['machine']==machine,'工具配置的协议、系统或芯片与本机不同')
        except (ValueError,KeyError,TypeError,OSError) as error:reasons.append('本机工具配置无效：'+str(error))
    for name in ('font_regular','font_bold'):
        value=getattr(settings,name)
        if not value or not value.is_file():reasons.append('缺少本机中文图表字体：'+name)
    return reasons


def info(app,req,sid):
    """所有阶段资格、恢复模板和口袋选项由后端提供，刷新不产生执行副作用。"""
    w=app.kernel.read_workflow();m=w.load(sid);home=w.location(sid)
    record=w.analysis_plan_info(sid).get('a06_preparation_input')
    common=configuration_blockers(app.settings)
    if m.get('trashed'):common.append('回收站研究只读')
    if app.tasks.active_for(sid):common.append('请等待当前研究后台任务结束')
    prep_id=m['current'].get('A06_PREP');a06=m['current'].get('A06')
    prep=w.run(m,prep_id) if prep_id else None
    result=w.result(m,prep_id) if prep_id else None
    fact=read_json(verified_file(home,result['tables']['preparation_packet'][0])) if result and prep['config'].get('version') in (core.PREPARATION,core.QUALIFIED) else None
    pockets=[]
    if fact and prep['config']['version']==core.PREPARATION:
        from science_modules.a06.plan_pockets import options
        pockets=options(home,fact)
    stages=[]
    for stage,label,prefix in (('prepare','本机结构与配体准备','nativeprep'),('qualify','核查口袋并生成待整体复核准备','nativequal'),('score','按已批准本机准备评分','nativescore')):
        reasons=list(common);body={'request_id':new_id(prefix),'platform_protocol':core.SCORING,'author':'','note':'','confirmed':False}
        if stage in ('prepare','qualify'):
            body.update(expected_input_id=record['input_id'] if record else None,expected_preparation_run_id=prep_id)
        if stage=='qualify':body['decisions']=[{'target_id':r['target_id'],'pocket_key':None} for r in pockets]
        if stage=='score':
            review=w.latest_review(m,prep['artifact_id']) if prep else None
            body.update(expected_preparation_run_id=prep_id,expected_preparation_result_sha256=m['runs'][prep_id]['result_file']['sha256'] if result else None,
                expected_preparation_review_id=review['review_id'] if review else None,expected_a06_run_id=a06)
        rid=prep_id if stage!='score' else a06;run=w.run(m,rid) if rid else None
        resumable=False
        if run and run['config'].get('version')=={'prepare':core.PREPARATION,'qualify':core.QUALIFIED,'score':core.SCORING}[stage] and not m['runs'][rid]['result_file']:
            envelope=read_json(verified_file(home,run['inputs']['native_request']))
            body=envelope['request'];resumable=True
        if not record:reasons.append('请先固定并分别复核完整成分与受体输入')
        elif not resumable:
            if stage=='prepare' and fact:reasons.append('本批原生准备已归档，请核查后续环节，避免重复准备')
            if stage=='qualify' and (not prep or prep['config'].get('version')!=core.PREPARATION or not result):reasons.append('请先完成本机原生准备')
            if stage=='qualify' and fact and not result['summary']['ready_pairs'] and not any(o['eligible'] for r in pockets for o in r['options']):reasons.append('当前没有可用严格项或可明确采用的探索口袋，NA须保留')
            if stage=='score' and (not prep or prep['config'].get('version')!=core.QUALIFIED or not w.approved(m,prep_id)):reasons.append('须先完成本机资料复验并由原复核栏人工整体通过')
            if stage=='score' and a06 and w.run(m,a06)['config'].get('version')==core.SCORING and w.result(m,a06):reasons.append('本批评分已归档，查看原结果与诊断')
        if not reasons and (stage!='qualify' or resumable):
            try:core.source(w,sid,stage,body)
            except (ValueError,OSError,KeyError,TypeError) as error:reasons.append(str(error))
        stages.append({'key':stage,'label_zh':label,'enabled':not reasons,'blockers_zh':reasons,'resumable':resumable,'request_template':body})
    return {'supported':bool(record or fact),'protocol':core.SCORING,'stages':stages,'pockets':pockets,
        'notice_zh':'本平台新协议：提交后worker先核完整工具及依赖。旧Windows批次继续原规则，不能在此冒充原批无缝恢复。',
        'current_preparation_run_id':prep_id,'current_scoring_run_id':a06}


def submit(app,req,sid,stage):
    """只接受明确版本模板；同研究原队列去重，实际环境变化由worker继续阻断。"""
    body=req.json()
    try:
        core.request(stage,body)
        core.source(app.kernel.workflow(),sid,stage,body)
    except ContractError as error:raise from_contract(str(error)) from error
    reasons=configuration_blockers(app.settings)
    if app.tasks.active_for(sid):reasons.append('本研究已有活动任务')
    if reasons:raise ApiError(409,'GATE_BLOCKED','；'.join(reasons))
    task,created=app.tasks.submit(sid,'native_a06',body['author'],
        payload={'stage':stage,'request':body,'profile_sha256':digest_file(app.settings.tools_profile)[1]})
    if not created:raise ApiError(409,'GATE_BLOCKED','本研究已有活动任务')
    return {'task':task,'created':True,'message_zh':'本平台明确请求已排队；完整依赖复验后执行，结果待独立科研复核。'},202

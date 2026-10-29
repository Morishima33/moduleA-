"""新版阶段接续的标准库契约：绑定同研究方案、当前输入及实际人工复核。"""
from contracts import fingerprint, require, safe_id
from storage import read_json, verified_file
from science_modules.analysis_protocol import VERSION as PLAN_VERSION

VERSION = 'ModuleA.plan_stages.1'
STAGES = ('A02', 'A03', 'A04')


def is_current(workflow,manifest):
    """识别当前新方案交集，阻止旧接续绕过明确阶段入口。"""
    rid=manifest.get('current',{}).get('A03')
    return bool(rid and workflow.run(manifest,rid)['config'].get('version')=='A03.plan_intersection.1')


def context(workflow, sid):
    """只读取登记和不可变方案，不启动任务或改变研究。"""
    manifest=workflow.load(sid)
    a00=manifest['current'].get('A00','')
    intake=workflow.result(manifest,a00)['summary'] if a00 else {}
    supported=intake.get('analysis_plan_profile')==PLAN_VERSION
    records=workflow._analysis_plan_records(manifest) if supported else []
    draft=records[-1] if records and records[-1]['expected_a00']==a00 else None
    return manifest,intake,draft


def binding(workflow, manifest, draft):
    """完整输入快照包含当前运行/复核和方案原件，旧窗口或上游重批均失效。"""
    reviews={}
    for module,rid in manifest['current'].items():
        review=workflow.latest_review(manifest,workflow.run(manifest,rid)['artifact_id'])
        reviews[module]=review['review_id'] if review else None
    return {'study_id':manifest['study_id'],'a00':manifest['current'].get('A00',''),
            'plan_id':draft['plan_id'] if draft else '',
            'parameter_hash':draft['plan']['parameter_hash'] if draft else '',
            'current':dict(manifest['current']),'reviews':reviews,
            'component_uploads':manifest.get('current_component_uploads')}


def info(workflow,sid):
    """逐阶段展示真正就绪条件；A04与A05独立，资料/批准缺口不靠默认值补齐。"""
    m,intake,draft=context(workflow,sid)
    if intake.get('analysis_plan_profile')!=PLAN_VERSION:
        return {'schema_version':VERSION,'supported':False,'expected_input_hash':'','expected_a00':m['current'].get('A00',''),
                'expected_plan_id':'','parameter_hash':'','parameters':{},'stages':[],
                'message_zh':'历史固定研究保持原流程，不启用新版阶段接续'}
    blockers=[]
    if intake.get('analysis_plan_profile')!=PLAN_VERSION:blockers.append('历史固定研究不启用新版阶段接续')
    if m.get('trashed'):blockers.append('回收站研究只读')
    a00=m['current'].get('A00')
    if not a00 or not workflow.approved(m,a00):blockers.append('请先通过当前A00登记')
    if not draft:blockers.append('当前登记没有有效方案草稿')
    snapshot=binding(workflow,m,draft)
    stages=[]
    for stage in STAGES:
        reasons=list(blockers)
        rid=m['current'].get(stage)
        config=workflow.run(m,rid)['config'] if rid else {}
        inputs=workflow.run(m,rid)['inputs'] if rid else {}
        active=bool(rid and workflow.active(m,rid))
        if stage=='A02':
            if rid:reasons.append('已有A02，请在A02来源、范围及身份入口补齐当前版本，不重新初始化')
            if m.get('workflow_profile')!='A00.preupload.2':reasons.append('五库初始化要求已核验疾病身份的新登记')
        else:
            parents=('A01','A02') if stage=='A03' else ('A03',)
            for module in parents:
                parent=m['current'].get(module)
                if not parent or not workflow.approved(m,parent):reasons.append('请先通过当前'+module)
            if active and draft and inputs.get('analysis_plan_id')==draft['plan_id'] and config.get('version')=={'A03':'A03.plan_intersection.1','A04':'A04.plan_network.1'}[stage]:
                reasons.append('本方案已有当前有效'+stage+'，请核查或复核结果，不重复生成')
        if draft and stage in ('A03','A04'):
            a01=m['current'].get('A01')
            plan_id=workflow.run(m,a01).get('inputs',{}).get('analysis_plan_id') if a01 else None
            old=next((r for r in workflow._analysis_plan_records(m) if r['plan_id']==plan_id),None)
            if old and any(old['plan']['parameters'][key]!=draft['plan']['parameters'][key] for key in ('a01.ob_min','a01.dl_min')):
                reasons.append('本方案A01门槛已变化，须先生成并复核对应A01/A03')
        stages.append({'stage':stage,'enabled':not reasons,'blockers':reasons,'current_run':rid,
                       'active':active,'approved':bool(rid and workflow.approved(m,rid))})
    return {'schema_version':VERSION,'supported':intake.get('analysis_plan_profile')==PLAN_VERSION,
            'expected_input_hash':fingerprint(snapshot),'expected_a00':a00 or '',
            'expected_plan_id':draft['plan_id'] if draft else '',
            'parameter_hash':draft['plan']['parameter_hash'] if draft else '',
            'parameters':draft['plan']['parameters'] if draft else {},'stages':stages,
            'message_zh':'按当前方案明确执行一个就绪阶段，结果仍须独立复核；缺少资料会显示具体原因。'}


def validate(workflow,sid,body):
    """任务开始再次核对全输入指纹，拒绝任何隐藏参数、路径或批准覆盖。"""
    fields={'stage','expected_a00','expected_plan_id','expected_input_hash','operator','reason','confirmed'}
    require(isinstance(body,dict) and set(body)==fields,'新版阶段请求字段不完整或含未支持选项')
    require(body['stage'] in STAGES and body['confirmed'] is True,'请明确核对支持的执行阶段')
    safe_id(body['expected_a00'],'run');safe_id(body['expected_plan_id'],'plan')
    require(all(isinstance(body[k],str) and 0<len(body[k].strip())<=2000 for k in ('operator','reason')),'请填写执行人与依据，最多2000字')
    value=info(workflow,sid)
    require(value['supported'],'上游研究不支持新版阶段接续')
    require(not workflow.load(sid).get('trashed'),'回收站研究只读')
    require(all(value[k]==body[k] for k in ('expected_a00','expected_plan_id','expected_input_hash')),'阶段输入、复核或方案已改变，请刷新后重新确认')
    stage=next(r for r in value['stages'] if r['stage']==body['stage'])
    require(stage['enabled'],'上游条件未就绪：'+'；'.join(stage['blockers']))
    return value


def plan_reference(workflow,manifest,plan_id):
    """从研究自身索引获取明确方案，不能接受浏览器给出的路径。"""
    home=workflow.location(manifest['study_id'])
    for ref in manifest.get('analysis_plan_records',[]):
        record=read_json(verified_file(home,ref))
        if record['plan_id']==plan_id:return ref,record
    require(False,'方案不属于本研究')


def verified_request(home,reference,stage,plan_id,a00):
    """离线复算只读当次明确确认和完整绑定快照，不借用后来确认。"""
    record=read_json(verified_file(home,reference));body=record['request']
    require(record['schema_version']==VERSION and record['study_id']==home.name
            and body['stage']==stage and body['expected_plan_id']==plan_id and body['expected_a00']==a00
            and body['confirmed'] is True and body['expected_input_hash']==fingerprint(record['binding']),
            '阶段明确确认与原始输入快照不一致')
    return record

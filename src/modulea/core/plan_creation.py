"""标准/个性化新建的预检、明确确认和不可变初始方案；不自动批准或计算。"""
from datetime import datetime, timezone, timedelta

from contracts import fingerprint, require, safe_id
from mesh_identity import verify_mesh_identity
from science_modules.analysis_protocol import VERSION as PLAN_VERSION, checked_plan, compile_plan
from storage import file_record, new_id, now, read_json, verified_file, write_json, write_lock
from ..preflight import REFERENCE_FILES, reference_status
from .study_creation import CreationConflict, StudyCreation, FIELDS

VERSION = 'ModuleA.plan_creation.1'
LIFETIME_MINUTES = 30


def is_plan_created(workflow, manifest):
    """仅识别本新增建档协议；旧研究、内部方案测试及历史流程保持。"""
    # 后续登记修订即使漏带扩展字段，也不能把已建档的新方案退回旧自动协议。
    if manifest.get('initial_analysis_plan'):
        return True
    a00 = manifest.get('current', {}).get('A00')
    return bool(a00 and (workflow.result(manifest, a00) or {}).get('summary', {}).get('creation_protocol') == VERSION)


def materials(settings):
    """核验本机真实共享资料，研究专属来源明确未提供，不用勾选冒充完整。"""
    refs = [reference_status(settings.data_root, spec) for spec in REFERENCE_FILES]
    return {'references': refs, 'references_verified': all(row['status'] == 'verified' for row in refs),
            'research_sources': [{'database': db, 'status': 'not_provided', 'reason_zh': reason} for db, reason in (
                ('TCMSP', '建档后按本方药味和方案核查来源及OB/DL，不能由共享快照存在推断完整'),
                ('HERB', '建档后核查本方全部药味、成分身份及已有靶点关系'),
                ('BATMAN', '建档后核查本方known关系，不纳入预测关系'),
                ('GeneCards', '在本研究A02来源区上传官方疾病检索原件，尚未提供'),
                ('OMIM', '在本研究A02来源区上传官方疾病检索原件，尚未提供'),
                ('TTD', '建档后绑定本研究疾病范围并核查实际来源'),
                ('PharmGKB', '建档后绑定本研究疾病范围并核查实际来源'),
                ('OTP', '建档后按官方疾病身份获取并核查实际来源'))],
            'execution_available': False,
            'reason_zh': '资料缺口允许先建档；来源未齐备或新编排未接通前不启动分析'}


def canonical(body):
    """复用原登记字段校验，分析方案使用统一编译器，无客户端保护项覆盖。"""
    require(isinstance(body, dict) and set(body) == {'intake', 'specification'}, '新建预检字段不完整或含不支持选项')
    require(isinstance(body['intake'], dict) and set(body['intake']) == set(FIELDS), '新建登记字段不完整或含不支持选项')
    _, fields = StudyCreation._fields(dict(body['intake'], request_id='create_' + '0' * 32))
    plan = compile_plan(body['specification'])
    return {'intake': fields, 'plan': plan}


def record_for_a00(workflow, manifest, run, intake):
    """在原Workflow.create的同一写锁和索引发布前保存初始方案及预检证据。"""
    require(intake.get('analysis_plan_profile') == PLAN_VERSION and run['inputs'] == intake,
            '新建方案与A00登记输入不一致')
    plan = checked_plan(intake['initial_analysis_plan'])
    proof = intake['creation_preflight']
    require(proof['schema_version'] == VERSION and proof['input_hash'] == fingerprint({'intake': {
        key: intake[key] for key in FIELDS}, 'plan': plan}) and proof['plan_parameter_hash'] == plan['parameter_hash'],
        '新建方案或预检内容指纹不一致')
    rid = new_id('plan')
    request_id = intake['creation_request_id']
    safe_id(request_id, 'plancreate')
    record = {'schema_version': PLAN_VERSION, 'study_id': manifest['study_id'], 'plan_id': rid,
              'expected_a00': run['run_id'], 'parent_draft_id': '', 'request_id': 'planreq_' + request_id.split('_')[1],
              'request_hash': fingerprint({'creation_request_id': request_id, 'plan': plan}),
              'created_at': now(), 'author': intake['operator'], 'note': '新建时明确确认的初始方案；建档不启动计算',
              'state': 'draft', 'plan': plan, 'applies_to_running_batch': False}
    home = workflow.location(manifest['study_id'])
    folder = home / 'decisions/analysis_plans'
    write_json(folder / (rid + '.json'), record)
    ref = file_record(home, folder / (rid + '.json'), 'analysis_plan_draft')
    manifest.setdefault('analysis_plan_records', []).append(ref)
    manifest['initial_analysis_plan'] = ref
    return ref


def create_study(workflow, content, proof, evidence, request_id):
    """公开Workflow方法调用原建档内核；初始方案在同一原子发布前归档。"""
    safe_id(request_id, 'plancreate')
    plan = checked_plan(content['plan'])
    intake = dict(content['intake'], species=9606, disease_scope='仅本病，不纳入亚型', mesh_verification=evidence,
                  creation_protocol=VERSION, creation_request_id=request_id, analysis_plan_profile=PLAN_VERSION,
                  component_source_profile='A01.plan_publication.1', initial_analysis_plan=plan,
                  creation_preflight=proof)
    return workflow.create(intake)


def response(workflow, sid, created):
    """恢复重复请求时只返回原初始版本，不修改已存在的后续方案或批准。"""
    manifest = workflow.load(sid)
    ref = manifest.get('initial_analysis_plan')
    require(ref, '新建初始方案尚未完整发布')
    record = read_json(verified_file(workflow.location(sid), ref))
    a00 = record['expected_a00']
    saved = workflow.result(manifest, a00)['summary']
    require(saved['creation_protocol'] == VERSION and saved['initial_analysis_plan'] == record['plan'], '初始方案与登记归档不一致')
    return {'study_id': sid, 'run_id': a00, 'plan_id': record['plan_id'], 'created': created,
            'mode': record['plan']['mode'], 'parameter_hash': record['plan']['parameter_hash'],
            'directory': str(workflow.location(sid)), 'execution_available': False,
            'message_zh': '新版研究及初始方案已独立建档；请在A00核对资料，不自动批准或计算' if created else
                          '返回本次已建档的研究及初始方案，未重复创建或修改后续版本'}


class PlanCreation:
    """运行目录仅保存短期预检凭证，研究事实通过Workflow公开创建方法写入。"""
    def __init__(self, kernel):
        self.kernel = kernel
        self.folder = kernel.settings.runtime_dir / 'plan-creation'

    def preflight(self, body):
        """先校验字段，再核对官方疾病身份与真实资料；不创建研究或任务。"""
        content = canonical(body)
        evidence = verify_mesh_identity(content['intake']['mesh_term'], content['intake']['mesh_id'])
        snapshot = materials(self.kernel.settings)
        identifier = new_id('creationcheck')
        value = {'schema_version': VERSION, 'preflight_id': identifier, 'input_hash': fingerprint(content),
                 'content': content, 'mesh_verification': evidence, 'materials': snapshot,
                 'data_root_hash': fingerprint(str(self.kernel.settings.data_root.resolve())),
                 'created_at': now(), 'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=LIFETIME_MINUTES)).isoformat()}
        with write_lock(self.folder):
            write_json(self.folder / (identifier + '.json'), value)
        return {'schema_version': VERSION, 'preflight_id': identifier, 'input_hash': value['input_hash'],
                'plan': content['plan'], 'mesh_verification': evidence, 'materials': snapshot,
                'expires_at': value['expires_at'], 'can_create': True, 'execution_available': False,
                'message_zh': '登记与方案校验通过。建档后请补齐资料，再按执行页提示推进。'}

    def create(self, body):
        """锁内防重复并复核预检指纹和资料变化；过期凭证不产生新研究。"""
        require(isinstance(body, dict) and set(body) == {'request_id', 'preflight_id', 'expected_input_hash', 'confirmed'},
                '新建确认字段不完整或含不支持选项')
        safe_id(body['request_id'], 'plancreate'); safe_id(body['preflight_id'], 'creationcheck')
        require(body['confirmed'] is True and isinstance(body['expected_input_hash'], str), '请明确确认新建登记与方案')
        with write_lock(self.folder):
            workflow = self.kernel.workflow()
            # 原A00为幂等事实来源，运行目录丢失或服务重启也不重复建档。
            for manifest in workflow.studies(False) + workflow.studies(True):
                if not manifest.get('initial_analysis_plan'):
                    continue
                initial = read_json(verified_file(workflow.location(manifest['study_id']), manifest['initial_analysis_plan']))
                saved = workflow.result(manifest, initial['expected_a00'])['summary']
                if saved.get('creation_request_id') != body['request_id']:
                    continue
                if (saved['creation_preflight']['input_hash'] != body['expected_input_hash'] or
                        saved['creation_preflight']['preflight_id'] != body['preflight_id']):
                    raise CreationConflict('此新建请求编号已用于其他登记或预检，请重新预检')
                return response(workflow, manifest['study_id'], False)
            path = self.folder / (body['preflight_id'] + '.json')
            require(path.is_file(), '新建预检已失效，请刷新后重新预检')
            record = read_json(path)
            require(record['schema_version'] == VERSION and record['preflight_id'] == body['preflight_id'] and
                    record['input_hash'] == fingerprint(record['content']) == body['expected_input_hash'], '新建预检内容已改变，请刷新后重新预检')
            require(record['data_root_hash'] == fingerprint(str(self.kernel.settings.data_root.resolve())), '预检数据目录已改变，请刷新后重新预检')
            require(datetime.fromisoformat(record['expires_at']) > datetime.now(timezone.utc), '新建预检已过期，请刷新后重新预检')
            require(fingerprint(materials(self.kernel.settings)) == fingerprint(record['materials']), '资料状态已改变，请刷新后重新预检再确认')
            proof = {'schema_version': VERSION, 'preflight_id': record['preflight_id'], 'input_hash': record['input_hash'],
                     'checked_at': record['created_at'], 'plan_parameter_hash': record['content']['plan']['parameter_hash'],
                     'materials': record['materials'], 'execution_available': False}
            # 运行目录只作暂存；传入内容由Workflow复制为研究内原始证据。
            sid = workflow.create_analysis_plan_study(record['content'], proof, record['mesh_verification'], body['request_id'])
            return response(workflow, sid, True)


def context(workflow, sid):
    """当前A00显示已绑定方案和实际资料状态；初始预检与当前缺口分别保留。"""
    manifest = workflow.load(sid)
    if not is_plan_created(workflow, manifest):
        return None
    home = workflow.location(sid)
    initial = read_json(verified_file(home, manifest['initial_analysis_plan']))
    saved = workflow.result(manifest, initial['expected_a00'])['summary']
    current = workflow.analysis_plan_info(sid).get('draft')
    return {'schema_version': VERSION, 'initial_plan_id': initial['plan_id'], 'initial_a00_run_id': initial['expected_a00'],
            'initial_plan': initial['plan'], 'current_plan_id': current['plan_id'] if current else None,
            'current_plan': current['plan'] if current else None, 'materials_at_creation': saved['creation_preflight']['materials'],
            'preflight_id': saved['creation_preflight']['preflight_id'], 'execution_available': False,
            'reason_zh': '初始方案及资料预检已归档。请核对本研究资料，并按执行页提示推进和复核。'}

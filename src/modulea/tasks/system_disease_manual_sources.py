"""独立科学worker处理受限疾病原件预上传，原始字节与排队确认逐件重核。"""
import hashlib,json
from contracts import require


def run(settings,task,manager):
    """读取队列的固定字节后调用公开Workflow；解析或身份失败保持实际失败。"""
    payload=json.loads(task['payload']);require(set(payload)=={'request','blob_name','blob_sha256','blob_bytes'},'上传队列字段错误')
    folder=(settings.runtime_dir/'upload_queue').resolve();path=(folder/payload['blob_name']).resolve()
    require(path.parent==folder and path.is_file(),'上传队列原件路径不合法或已缺失')
    raw=path.read_bytes();require(hashlib.sha256(raw).hexdigest()==payload['blob_sha256'] and len(raw)==payload['blob_bytes'],
        '上传队列原件校验失败，请重新上传')
    manager.update(task['task_id'],progress={'step_zh':'核对登记、疾病标题并校验原件格式','done':0,'total':1})
    from ..core.kernel import full_workflow
    result=full_workflow(settings.data_root).stage_analysis_plan_system_disease_source(task['study_id'],payload['request'],raw)
    manager.update(task['task_id'],progress={'step_zh':'本研究原件已预上传，未批准登记或发布候选','done':1,'total':1})
    return result['request']['source']['database']+'原件已校验并保存，SHA-256：'+result['upload_sha256']+'；请明确核验五库。'

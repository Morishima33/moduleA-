"""新登记手动原件复用冻结预上传器；原解析、格式和身份规则不改。"""
from intake_sources import stage as original_stage,OFFICIAL_URLS
from disease import metadata
from source_identity import validate_source_identity


def stage(workflow,sid,a00,source,guard,publish):
    """原锁内重核当前输入，并在原Workflow.save前同次登记明确上传回执。"""
    summary=workflow.result(workflow.load(sid),a00)['summary']
    item=metadata(dict(source,source_url=OFFICIAL_URLS[source['database']],source_status='staged'))
    validate_source_identity(summary,item,source['data'])
    class GuardedStaging:
        """只在这一原预上传调用中代理load/save；真实状态与文件仍由原Workflow持有。"""
        def __getattr__(self,name):return getattr(workflow,name)
        def load(self,study_id):
            value=workflow.load(study_id);guard(value);return value
        def save(self,manifest):
            publish(manifest);workflow.save(manifest)
    return original_stage(GuardedStaging(),sid,a00,source)

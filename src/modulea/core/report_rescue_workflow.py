"""补救报告三版的公开Workflow接线；冻结的分析/状态与旧报告实现保持。"""
from .system_receptor_rescue_v2 import SystemReceptorRescueV2Workflow
from . import plan_reports_v3 as reports


class ReportRescueWorkflow(SystemReceptorRescueV2Workflow):
    """仅明确三版报告使用新事实，其余运行继续原继承链。"""
    def rescue_report_info(self, study_id):
        """只读技术资格，不生成Word、提交任务或签署复核。"""
        return reports.info(self, study_id)

    def publish_analysis_plan_rescue_report(self, study_id, body):
        """明确请求才另存双报告，历史附件和复核保持。"""
        return reports.publish(self, study_id, body)

    def _begin(self, manifest, module, inputs, config, reason):
        """系统证据依赖只分派显式三版，科学运行沿原入口。"""
        if module == 'A07' and config.get('version') == reports.VERSION:
            return reports.begin(self, manifest, inputs, config, reason)
        return super()._begin(manifest, module, inputs, config, reason)

    def _active(self, manifest, run_id):
        """三版仍逐项检查真实上游和系统回执，不制造人工批准。"""
        run = self.run(manifest, run_id)
        if run['module_id'] == 'A07' and run['config'].get('version') == reports.VERSION:
            return reports.is_active(self, manifest, run)
        return super()._active(manifest, run_id)

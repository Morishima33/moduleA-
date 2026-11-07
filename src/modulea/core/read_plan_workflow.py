"""冻结报告校验的嵌套读取：原规则不变，仅复用现有只读文件核验。"""

from .analysis_plans import AnalysisPlanWorkflow
from .read_archive import ReadResultMixin


class ReadPlanWorkflow(ReadResultMixin, AnalysisPlanWorkflow):
    """只由同线程、同数据根的读取作用域创建；原状态与报告重建照常执行。"""

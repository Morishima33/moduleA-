"""第三版来源准备的评分分派，执行与恢复算法复用原实现。"""
from .system_scoring_incremental import execute_protocol


def execute(workflow, sid, body, *, tools, progress=None):
    """只接受第三版实际资格；名单、工具和参数不能由请求覆盖。"""
    from science_modules.a06 import system_scoring_sources as science
    return execute_protocol(workflow, sid, body, tools=tools, progress=progress,
                            science=science, qualification_version='A06.system_qualification.3')

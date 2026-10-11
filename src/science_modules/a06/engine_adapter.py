"""A06代码复用适配：保留旧科学键，代码修改阶段关闭所有执行入口。"""
from contracts import ContractError, require

MODE = "A06.code_only.1"

# 分组标签不改变分子结构、盒或软件；同一科学输入继续使用冻结的精确复用键。
def pair_cache_key(preparation,receptor,compound):
    from docking_automation_compute import pair_key
    return pair_key(preparation,receptor,compound)

# 阶段入口先阻断，再导入或调用科学工具；不允许布尔参数解除本轮约束。
def run_stage(stage,*args,**kwargs):
    require(stage in ("prepare","execute","deliver"),"未知对接阶段")
    raise ContractError("当前仅复用和修改代码；结构准备、真实对接与交付计算入口未开放，须等待用户明确计算指示")

"""与已验收科学内核（src/ 下的扁平模块）之间的唯一桥梁。

设计要点：
- 研究状态、复核、失效判断全部交给原 Workflow 计算，本包不另写一套规则，
  因此新接口显示的状态与原工作台逐项一致。
- 接口进程只做“读取 + 复核 + 回收站管理”，不在进程内提交科学结果。
  这样接口进程只依赖 Python 标准库，在缺少科学依赖的电脑（例如 macOS）上也能启动。
- 需要科学计算时，由后台任务子进程调用 full_workflow()，那里才导入完整科学依赖。
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..config import LEGACY_SRC, Settings


def _ensure_legacy_path() -> None:
    """把 src/ 加入导入路径，使 workflow、storage 等扁平模块可以被导入。"""
    path = str(LEGACY_SRC)
    if path not in sys.path:
        sys.path.insert(0, path)


_ensure_legacy_path()

# 以下导入只依赖标准库，接口进程可以安全加载。
from contracts import MODULES, ContractError  # noqa: E402
from storage import read_json, verified_file  # noqa: E402
from workflow import Workflow  # noqa: E402
from .system_receptor_rescue import SystemReceptorRescueWorkflow as DockingWorkflow  # noqa: E402
from .read_archive import ReadResultMixin  # noqa: E402

__all__ = ["Kernel", "ContractError", "MODULES", "read_json", "verified_file", "full_workflow"]


def _read_only_validator(*_args, **_kwargs):
    """接口进程中的占位校验器：说明科学模块已接入，但禁止在接口进程中提交结果。"""
    raise ContractError("接口进程不提交科学结果；请通过后台任务执行")


# 每个科学模块都登记占位校验器，使状态推导把“可开始”的模块显示为 ready，而不是“未接入”。
VIEW_VALIDATORS = {module: _read_only_validator for module in MODULES if module != "A00"}


class Kernel:
    """为每个请求创建独立的 Workflow 实例。

    原 Workflow 把单次请求的缓存挂在实例属性上；接口服务是多线程的，
    所以每个请求各用一个实例，避免线程之间互相覆盖缓存。
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def workflow(self) -> Workflow:
        return DockingWorkflow(self.settings.data_root, VIEW_VALIDATORS)

    def read_workflow(self) -> Workflow:
        """只读列表、表格和下载使用；写入口继续使用workflow()完整核验。"""
        return _ReadWorkflow(self.settings.data_root, VIEW_VALIDATORS)

    def display_workflow(self) -> Workflow:
        """只用于显示状态的实例：回收站中的研究也按原有批准关系计算状态。

        原内核在研究位于回收站时把所有批准视为无效（以阻止写入），直接显示会让全部模块变成“已失效”。
        这里只在读取时忽略回收站标记；写入一律使用 workflow()，回收站仍然只读。
        """
        return _DisplayWorkflow(self.settings.data_root, VIEW_VALIDATORS)


class _ReadWorkflow(ReadResultMixin, DockingWorkflow):
    """只读I/O适配，不改动科学内核或写入实例。"""


class _DisplayWorkflow(_ReadWorkflow):
    def load(self, study_id):
        manifest = dict(super().load(study_id))
        manifest["trashed"] = False
        return manifest


def full_workflow(data_root: Path) -> Workflow:
    """后台任务使用的完整 Workflow：登记全部科学模块的真实校验器。

    与原网页 src/web.py 中 create_server 的登记内容完全相同；只在后台子进程中调用，
    因为这里会导入 python-docx、networkx 等科学依赖。
    """
    from normalization import validator as normalization_validator
    from components import validate_components
    from components_multisource_flow import validator as multisource_validator
    from science_modules.a01.uploads import validator as upload_validator
    from science_modules.a01.collection_flow import validator as collection_validator
    from science_modules.a01.plan_flow import validator as plan_a01_validator
    from science_modules.a01.system_source_binding import validator as system_a01_validator
    from science_modules.a01.identity_exception import validator as identity_a01_validator
    from disease import validate_disease
    from science_modules.a02.system_collection import validator as system_collection_validator
    from science_modules.a02.historical_collection import validator as historical_collection_validator
    from intersection_flow import validate_intersection, validate_selection
    from science_modules.plan_stages import a02_validator as stage_a02_validator, a03_validator as stage_a03_validator
    from science_modules.plan_compounds import validator as plan_compound_validator
    from .system_execution_science import compound_validator as system_compound_validator
    from .system_execution_science import a02_validator as system_a02_validator
    from ppi_dispatch import validator as ppi_validator, docking_validator
    from science_modules.a04.plan_flow import validator as plan_ppi_validator
    from science_modules.a04.plan_identity_network import validator as identity_ppi_validator
    from science_modules.a05.compact_flow import validator as enrichment_validator
    from science_modules.a05.plan_flow import validator as plan_enrichment_validator
    from science_modules.a05.plan_flow_utf8 import validator as plan_enrichment_utf8_validator
    from docking_formal import prep_validator, formal_validator
    from report_dispatch import validator as report_validator
    from science_modules.a07.plan_report_flow import validator as plan_report_validator
    from science_modules.a07.plan_report_flow_v2 import validator as revised_report_validator
    from science_modules.a06.quality_flow import validator as quality_validator
    from science_modules.a06.plan_preparation import validator as plan_preparation_validator
    from science_modules.a06.plan_preparation_v2 import validator as plan_preparation_v2_validator
    from science_modules.a06.system_preparation import validator as system_preparation_validator
    from science_modules.a06.system_qualification import validator as system_qualification_validator
    from science_modules.a06.system_scoring import validator as system_scoring_validator
    from science_modules.a06.system_preparation_incremental import validator as incremental_preparation_validator
    from science_modules.a06.system_qualification_incremental import validator as incremental_qualification_validator
    from science_modules.a06.system_qualification_paths import validator as path_qualification_validator
    from science_modules.a06.system_scoring_incremental import validator as incremental_scoring_validator
    from science_modules.a06.system_scoring_paths import validator as path_scoring_validator
    from science_modules.a06.plan_pocket_review import validator as plan_pocket_validator
    from science_modules.a06.reference_preparation import validator as reference_preparation_validator
    from science_modules.a06.plan_reference_publication_v2 import validator as reference_qualification_v2_validator
    from science_modules.a06.plan_reviewable_preparation import validator as reviewable_preparation_validator
    from science_modules.a06.plan_scoring_results import validator as plan_scoring_validator
    from science_modules.a06.coverage_flow import validator as coverage_validator
    from science_modules.a06.trial_handoff import validator as trial_handoff_validator
    from science_modules.a06.automatic_engine import validator as automatic_validator
    from science_modules.a06.automatic_coverage_engine import validator as rescue_validator
    from science_modules.a06.reference_engine import validator as reference_validator
    from science_modules.literature_input import validator as literature_validator

    root = data_root
    validators = {
        "A01": identity_a01_validator(root,system_a01_validator(root,plan_a01_validator(root, literature_validator(root, "A01", collection_validator(root, upload_validator(root, multisource_validator(root, normalization_validator(root, validate_components)))))))),
        "A02": historical_collection_validator(root,system_collection_validator(root,system_a02_validator(root,stage_a02_validator(root, literature_validator(root, "A02", normalization_validator(root, validate_disease)))))),
        "A03": stage_a03_validator(root, validate_intersection),
        "A03_SELECT": system_compound_validator(root,plan_compound_validator(root,validate_selection)),
        "A04": identity_ppi_validator(root, plan_ppi_validator(root, ppi_validator(root))),
        "A05": plan_enrichment_utf8_validator(root,plan_enrichment_validator(root, enrichment_validator(root))),
        "A06_PREP": incremental_qualification_validator(root,incremental_preparation_validator(root,system_qualification_validator(root,system_preparation_validator(root,reviewable_preparation_validator(root, reference_qualification_v2_validator(root, reference_preparation_validator(root, plan_pocket_validator(root, plan_preparation_v2_validator(root, plan_preparation_validator(root, coverage_validator(root, quality_validator(root, docking_validator(root, prep_validator(root)))))))))))))),
        "A06": incremental_scoring_validator(root,system_scoring_validator(root,plan_scoring_validator(root, reference_validator(root, rescue_validator(root, automatic_validator(root, trial_handoff_validator(root, formal_validator(root)))))))),
        "A07": revised_report_validator(root, plan_report_validator(root, report_validator(root))),
    }
    validators["A06_PREP"] = path_qualification_validator(root, validators["A06_PREP"])
    validators["A06"] = path_scoring_validator(root, validators["A06"])
    from science_modules.a06.system_preparation_sources import validator as source_preparation_validator
    from science_modules.a06.system_qualification_sources import validator as source_qualification_validator
    from science_modules.a06.system_scoring_sources import validator as source_scoring_validator
    from science_modules.a06.system_receptor_rescue import validator as receptor_rescue_validator
    validators['A06_PREP'] = source_qualification_validator(root, source_preparation_validator(root, validators['A06_PREP']))
    validators['A06'] = source_scoring_validator(root, validators['A06'])
    validators['A06'] = receptor_rescue_validator(root, validators['A06'])
    return DockingWorkflow(root, validators)

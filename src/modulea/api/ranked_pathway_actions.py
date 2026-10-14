"""A05排名首位图件的只读预校验及后台任务提交。"""

from contracts import ContractError
from .errors import ApiError, from_contract


def ranked_map_task(app, req, study_id):
    payload = req.json()
    if set(payload) != {"expected_a05"}:
        raise ApiError(422, "VALIDATION_FAILED", "请只提交当前A05版本")
    if app.tasks.active_for(study_id):
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，请等待完成")
    try:
        _, _, facts = app.kernel.workflow().ranked_map_source(study_id, payload["expected_a05"])
        if not facts:
            raise ApiError(422, "VALIDATION_FAILED", "当前确认范围无显著KEGG条目，不补图")
    except ContractError as error:
        raise from_contract(str(error))
    task, created = app.tasks.submit(
        study_id, "a05_pathway_maps", "生成KEGG排名首位命中图", payload
    )
    if not created:
        raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，请等待完成")
    return {
        "task": task,
        "created": created,
        "message_zh": "两个首位通路图已提交后台生成。" + app._task_message(task),
    }, 202

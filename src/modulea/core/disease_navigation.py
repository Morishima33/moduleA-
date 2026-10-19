"""A02操作导航：只整理归档事实与Workflow批准状态，不推算科学结果。"""


def context(workflow, manifest, result, normalization, state):
    """给出下一操作所在位置；导航不开放按钮、不写入任何研究决定。"""
    summary = (result or {}).get("summary", {})
    tables = (result or {}).get("tables", {})
    current = manifest.get("current", {})
    if not result or summary.get("失败来源库数") or any(row.get("availability") not in ("已有候选资料，待核验", "已查询但0条精确记录") for row in tables.get("source_summary", [])):
        step, note = 1, "先核对五库资料、检索疾病和获取状态，补齐缺失或获取失败的来源。"
    elif "标准化基因数" not in summary and summary.get("待范围复核条目数", summary.get("待定范围组数", 0)):
        step, note = 2, "逐组确认本病、亚型或范围外，再保存本批范围核验。每一组可能包含多条原始记录。"
    elif normalization:
        step = 4 if normalization.get("preview") else 3
        note = "身份预览已完成。请查看身份例外、填写依据并确认生成待复核结果。" if step == 4 else "范围已保存。点击核查基因身份，由程序生成身份核查预览。"
        if not normalization["enabled"]:
            note = normalization["disabled_reason_zh"]
    elif all(current.get(mid) and workflow.approved(manifest, current[mid]) for mid in ("A01", "A02")):
        step, note = 6, "A01和A02均已通过，请查看A03。若尚未生成，可从研究管理选择推进到下一人工关口。"
    else:
        step, note = 5, "标准化结果已生成，请整体复核A01与A02；两项通过后后台接续A03。"
    if state.get("code") in ("stale", "unavailable") or manifest.get("trashed"):
        note = state.get("reason_zh") or "当前版本只读，请先处理失效或归档问题。"
    labels = {1: ("查看数据库资料", "disease-source-inputs"), 2: ("前往疾病范围核验", "disease-scope-review"),
              3: ("前往基因身份核查", "normalization-review"), 4: ("前往确认身份处理", "normalization-confirmation"),
              5: ("前往整体复核", "module-review-panel"), 6: ("查看A03交集", "A03")}
    label, target = labels[step]
    return {"current_step": step, "note_zh": note, "next_label_zh": label, "next_target": target}

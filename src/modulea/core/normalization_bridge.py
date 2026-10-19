"""标准化衔接的只读上下文与版本校验；科学预览和发布仅由后台调用原内核。"""
from contracts import require, safe_id
from storage import read_json


def bindings(manifest):
    """三侧输入一起绑定，不能将旧项目或旧方剂侧预览交给新疾病。"""
    return {"expected_" + key.lower(): manifest.get("current", {}).get(key, "") for key in ("A00", "A01", "A02")}


def preview_path(settings, sid):
    """预览是运行缓存，按项目独立存放，不进入科研归档。"""
    safe_id(sid, "study")
    return settings.runtime_dir / "normalization_previews" / sid / "preview.json"


def context(workflow, manifest, result, settings, busy=False):
    """只翻译既有候选阶段与范围事实，不计算科学身份或解除交接门控。"""
    if not result or "标准化基因数" in result.get("summary", {}) or not result.get("tables", {}).get("scope_groups"):
        return None
    expected = bindings(manifest)
    reasons = []
    if manifest.get("trashed"):
        reasons.append("研究在回收站中，只读")
    if busy:
        reasons.append("当前研究已有后台任务，请等待完成")
    if not all(expected.values()) or not all(workflow.active(manifest, rid) for rid in expected.values() if rid):
        reasons.append("请先补齐有效的A00、A01和A02")
    if expected["expected_a00"] and not workflow.approved(manifest, expected["expected_a00"]):
        reasons.append("请先复核通过A00研究登记")
    groups = result["tables"]["scope_groups"]
    if any(row["scope"] == "pending" for row in groups):
        reasons.append("请先在上方处理并保存全部待核验范围")
    preview = None
    path = preview_path(settings, manifest["study_id"])
    if path.is_file():
        saved = read_json(path)
        if saved.get("study_id") == manifest["study_id"] and saved.get("bindings") == expected:
            preview = saved["preview"]
    return dict(expected, enabled=not reasons, disabled_reason_zh="；".join(reasons), preview=preview,
                scope_note_zh="当前所有条目均已排除，标准化后疾病集合将为空。请确认这符合本次研究的决定。" if all(row["scope"] in ("outside", "subtype") for row in groups) else "已保存的采用和排除决定将原样用于标准化。")


def validate(workflow, sid, payload):
    """请求与后台共用校验，当前指针或输入失效时停止，不自动重提。"""
    manifest = workflow.load(sid)
    require(not manifest.get("trashed"), "回收站研究只读")
    require(all(payload.get(k) == v and v for k, v in bindings(manifest).items()), "A00、A01或A02版本已改变，请重新生成标准化预览")
    require(all(workflow.active(manifest, rid) for rid in bindings(manifest).values()), "输入已失效，请重新整理资料")
    require(workflow.approved(manifest, manifest["current"]["A00"]), "请先复核通过A00")
    result = workflow.result(manifest, manifest["current"]["A02"])
    require("标准化基因数" not in result.get("summary", {}), "当前已是标准化结果，请直接整体复核")
    require(all(row["scope"] != "pending" for row in result["tables"]["scope_groups"]), "仍有待核验范围，请先保存完整范围决定")
    # 复用来源身份提示，拒绝将错疾病附件作为直接条目发布。
    from .disease_scope import context as scope_context
    info = scope_context(workflow, manifest, result, True)
    require(all(row["scope"] != "direct" or row["direct_allowed"] for row in info["items"]), "来源检索身份不匹配，请先更换文件或修订范围")
    require(payload.get("action") in ("preview", "publish"), "未知标准化操作")
    if payload["action"] == "publish":
        require(payload.get("confirmed") is True, "请明确确认范围及身份处理")
        require(all(isinstance(payload.get(k), str) and 0 < len(payload[k].strip()) <= 4000 for k in ("reviewer", "note", "stamp")), "请填写核验人与依据，并先生成预览")
        require(all(type(payload.get(k)) is bool for k in ("accept_omit", "accept_source_exception")), "例外确认必须明确选择")
    return manifest


def execute(settings, workflow, sid, payload):
    """后台唯一执行入口：复用已有HGNC标准化，不复制科学算法。"""
    from normalization import preview, publish
    from storage import write_json
    manifest = validate(workflow, sid, payload)
    if payload["action"] == "publish":
        made = publish(workflow, sid, payload["stamp"], payload["reviewer"], payload["note"], True, payload["accept_omit"], payload["accept_source_exception"])
        return "标准化结果已生成，等待A01/A02整体复核；未批准或启动A03。", made
    data = preview(workflow, sid)
    results = data[5]
    projected = {"stamp": data[-1], "modules": [{"module": key, "summary": value[0], "identity_issues": value[1]["identity_issues"]} for key, value in results.items()], "source_exceptions": results["A02"][1].get("source_exceptions", [])}
    # 只保存与当前输入一致的预览；发布时原内核仍将重新计算指纹。
    require(bindings(workflow.load(sid)) == bindings(manifest), "预览期间版本已改变，请重新生成")
    write_json(preview_path(settings, sid), {"study_id": sid, "bindings": bindings(manifest), "preview": projected}, replace=True)
    return "身份预览已完成；请核对例外并生成标准化结果，再进行整体复核。", projected

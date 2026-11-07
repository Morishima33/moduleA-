"""同批Top-1原字节只读下载及其来源说明；不写原件、不联网、不重算。"""
from hashlib import sha256
import json

from contracts import ContractError, fingerprint, require
from storage import read_json, verified_file
from ..core.foundation_evidence import build
from .errors import ApiError, from_contract


def _binding(manifest, rid, prep_id):
    """下载前后只核对本运行与原准备登记，不因其他新运行阻断历史读取。"""
    return fingerprint({"study_id": manifest["study_id"], "run": manifest.get("runs", {}).get(rid),
                        "preparation": manifest.get("runs", {}).get(prep_id)})


def _checked(app, req, sid, rid, number):
    """服务端回读固定编号与原归档，浏览器不能提供路径、姿势号或评分。"""
    expected = {"expected_input_key", "expected_pose_sha256"}
    if set(req.query) != expected or any(len(values) != 1 for values in req.query.values()):
        raise ApiError(422, "VALIDATION_FAILED", "Top-1下载字段错误，不接受路径、其他姿势或参数覆盖")
    if len(str(number)) > 8 or not str(number).isdigit() or int(number) < 1:
        raise ApiError(404, "NOT_FOUND", "找不到本批原始组合")
    workflow = app.kernel.read_workflow()
    manifest = workflow.load(sid)
    home = workflow.location(sid)
    record = manifest.get("runs", {}).get(rid)
    if not record or not record.get("result_file"):
        raise ApiError(404, "NOT_FOUND", "找不到本研究已归档的评分运行")
    try:
        run = read_json(verified_file(home, record["run_file"]))
        result = read_json(verified_file(home, record["result_file"]))
        if run.get("module_id") != "A06":
            raise ApiError(404, "NOT_FOUND", "该运行没有原始组合评分")
        prep_id = run.get("parent_runs", {}).get("A06_PREP")
        before = _binding(manifest, rid, prep_id)
        fixed_record = read_json(verified_file(home, run["inputs"]["system_input_ref"]))
        require(fixed_record.get("study_id") == sid and fixed_record.get("stage") == "A06_INPUT"
                and fixed_record.get("binding", {}).get("batch_file") == run["batch_file"], "Top-1下载固定范围或批次不同")
        fixed = fixed_record["payload"]
        value = build(workflow, manifest, run, result, fixed, [])
        index = int(number) - 1
        if value is None or index >= len(value["scores"]):
            raise ApiError(404, "NOT_FOUND", "找不到本批原始组合")
        pair = value["scores"][index]
        if pair["state"] != "completed":
            raise ApiError(409, "GATE_BLOCKED", "本组合没有通过原始评分核验的Top-1构象，NA及失败原因保持")
        if req.query1("expected_input_key") != value["input_key"] or req.query1("expected_pose_sha256") != pair["pose_sha256"]:
            raise ApiError(409, "STALE_VERSION", "Top-1构象或固定输入已改变，请刷新后下载")
        score_packet = read_json(verified_file(home, result["tables"]["scoring_packet"][0]))
        execution_ref = score_packet["pairs"][index]["execution"]
        execution = read_json(verified_file(home, execution_ref))
        source_ref = execution["pose"]
        raw = verified_file(home, source_ref).read_bytes()
        require(len(raw) == source_ref["bytes"] and sha256(raw).hexdigest() == source_ref["sha256"] == pair["pose_sha256"],
                "Top-1下载读取期间原始构象已改变")
        selected = []
        started = False
        for line in raw.splitlines(keepends=True):
            if line.startswith(b"MODEL ") and line.split()[1] == b"1": started = True
            if started: selected.append(line)
            if started and line.startswith(b"ENDMDL"): break
        require(selected and selected[-1].startswith(b"ENDMDL"), "Top-1原始字节未形成完整MODEL")
        top1 = b"".join(selected)
        require(before == _binding(workflow.load(sid), rid, prep_id), "Top-1下载期间运行或原准备登记已改变")
        context = {"schema_version": "ModuleA.foundation_top1.1", "study_id": sid, "run_id": rid,
                   "pair_number": int(number), "compound_id": pair["compound_id"], "compound_name": pair["compound_name"],
                   "target_id": pair["target_id"], "symbol": pair["symbol"], "top_mode": 1, "score": pair["score"],
                   "score_unit": "kcal/mol", "box": pair["box"], "input_key": value["input_key"],
                   "source_pose_sha256": source_ref["sha256"], "top1_sha256": sha256(top1).hexdigest(),
                   "top1_bytes": len(top1), "execution_sha256": execution_ref["sha256"],
                   "configuration": run["config"], "coordinates_source": "saved_vina_model_1_exact_bytes",
                   "read_only": True, "scientific_results_changed": False,
                   "message_zh": "仅从本批原始Vina输出提取MODEL 1原字节；未重排、重对接、生成坐标或修改原文件。"}
        return top1, context
    except ContractError as error:
        raise from_contract(str(error)) from error


def top1(app, req, sid, rid, number):
    """返回已核验MODEL 1原字节；所有其余模式保留在原归档中。"""
    raw, _ = _checked(app, req, sid, rid, number)
    return "download", raw, f"{rid}_pair_{int(number):06d}_top1.pdbqt", "chemical/x-pdbqt"


def context(app, req, sid, rid, number):
    """下载同一Top-1的评分、搜索盒及原始/提取字节指纹说明。"""
    _, value = _checked(app, req, sid, rid, number)
    return "download", json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"), \
        f"{rid}_pair_{int(number):06d}_top1_context.json", "application/json; charset=utf-8"

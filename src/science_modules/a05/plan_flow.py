"""A05新方案参数执行及独立复算发布；历史A05协议与统计实现保持。"""
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import FunctionType

from contracts import fingerprint, require
from storage import file_record, new_id, read_json, verified_file, write_json, write_lock
from science_modules.analysis_protocol import checked_plan
import enrichment_flow as legacy
from . import flow as runtime

VERSION = "A05.plan_enrichment.1"
SOURCE_VERSION = "A05.plan_source.1"
SCRIPT = Path(__file__).with_name("plan_enrichment.R")
GROUPS = ("BP", "CC", "MF", "KEGG")


def parameters(plan):
    """只从统一校验后的方案提取本统计器支持的参数。"""
    p = checked_plan(plan)["parameters"]
    return {"include_go": p["a05.include_go"], "include_kegg": p["a05.include_kegg"],
            "min_size": p["a05.min_term_size"], "max_size": p["a05.max_term_size"],
            "adjusted_p_lt": p["a05.adjusted_p_max"]}


def groups(plan):
    """未纳入的类别不是空检验族，不进入R计算。"""
    p = parameters(plan)
    return (["BP", "CC", "MF"] if p["include_go"] else []) + (["KEGG"] if p["include_kegg"] else [])


def configuration(plan):
    """科学版本与全部实际消费的参数同时归档，不沿用旧固定版本标记。"""
    p = checked_plan(plan)["parameters"]
    return dict(legacy.CONFIG, version=VERSION, **parameters(plan), adjust_groups=groups(plan),
                tested_terms="input_hit_and_plan_size_range", show_GO=p["a05.go_plot_top"],
                show_KEGG=p["a05.kegg_plot_top"], go_table_top=p["a05.go_table_top"],
                kegg_table_top=p["a05.kegg_table_top"],
                implementation_sha256={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in
                    (Path(__file__), SCRIPT, Path(__file__).with_name('plan_contract.py'), Path(__file__).with_name('plan_figures.py'))})


def r_call(root, mode, value):
    """调用配置的固定R环境并保留日志；缺工具和超时均失败，不发布零结果。"""
    binary = os.environ.get("MODULEA_RSCRIPT", "")
    require(binary and Path(binary).is_file(), "新方案A05尚未配置有效Rscript，请配置science_rscript")
    work = Path(root) / "environments"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="a05_plan_", dir=work) as directory:
        folder = Path(directory)
        write_json(folder / "input.json", value)
        try:
            process = subprocess.run([binary, "--vanilla", str(SCRIPT), mode, "input.json", "output.json"],
                                     cwd=folder, capture_output=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as error:
            from contracts import ContractError
            diagnostic = failure_record(root, folder, str(error))
            raise ContractError("新方案A05的R计算未完成，原结果保持；完整输入与诊断已保留：" + str(diagnostic)) from error
        log = (process.stdout + process.stderr).decode("utf8", errors="replace")
        if process.returncode != 0 or not (folder / "output.json").is_file():
            diagnostic = failure_record(root, folder, log)
            require(False, "新方案A05计算失败：" + log[-1500:] + "；完整输入与诊断：" + str(diagnostic))
        trace = {'command': [binary, '--vanilla', str(SCRIPT), mode, 'input.json', 'output.json'],
                 'return_code': process.returncode, 'script_sha256': hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
                 'rscript_sha256': hashlib.sha256(Path(binary).read_bytes()).hexdigest()}
        return read_json(folder / "output.json"), json.dumps(trace,ensure_ascii=False) + '\n' + log


def failure_record(root, folder, log):
    """失败时另存本次完整输入、实际输出和日志；不覆盖旧尝试或发布空结果。"""
    target=Path(root)/'environments/A05_plan_failures'/new_id('attempt')
    target.mkdir(parents=True)
    for name in ('input.json','output.json'):
        path=Path(folder)/name
        if path.is_file():
            shutil.copyfile(path,target/name)
    (target/'R_log.txt').write_text(log,encoding='utf8')
    return target


def read_source(path, plan):
    """新注释包与纳入类别严格一致，KEGG派生关系仍从官方原文复算。"""
    with gzip.open(path, "rt", encoding="utf8") as stream:
        source = json.load(stream)
    require(source.get("schema_version") == SOURCE_VERSION and source.get("config") == legacy.CONFIG,
            "A05来源版本或固定工具配置不一致")
    require(set(source["annotations"]) == set(groups(plan)), "A05来源类别与本方案不同")
    if "KEGG" in groups(plan):
        require(source["annotations"]["KEGG"] == legacy.kegg_terms(source["kegg_sources"]), "KEGG注释与原响应不一致")
    return source


def source_snapshot(root, plan):
    """来源按实际纳入类别冻结，不取旧研究结果；GO-only不请求KEGG。"""
    root = Path(root)
    key = "_".join(groups(plan))
    index = root / "environments" / ("A05_plan_sources_" + key + ".json")
    if index.is_file():
        ref = read_json(index)
        read_source(verified_file(root, ref), plan)
        return ref
    go, log = r_call(root, "export", {"include_go": parameters(plan)["include_go"]})
    annotations = go["annotations"] if parameters(plan)["include_go"] else {}
    kegg = {}
    if parameters(plan)["include_kegg"]:
        kegg = {"names": legacy.download("list/pathway/hsa"), "links": legacy.download("link/pathway/hsa"),
                "release": legacy.download("info/pathway")}
        annotations["KEGG"] = legacy.kegg_terms(kegg)
    source = {"schema_version": SOURCE_VERSION, "config": legacy.CONFIG, "annotations": annotations,
              "metadata": go["metadata"], "kegg_sources": kegg, "export_log": log}
    raw = gzip.compress(json.dumps(source, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0)
    path = root / "references" / ("enrichment_plan_" + hashlib.sha256(raw).hexdigest() + ".json.gz")
    with write_lock(root):
        if index.exists():
            return read_json(index)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)
        ref = file_record(root, path, "annotation_source")
        write_json(index, ref)
    return ref


def evaluate(root, targets, source, hgnc_raw, purpose, plan):
    """复用原HGNC映射/检验族组装，只将实际参数交给新版本R统计器。"""
    config = configuration(plan)
    def call(root, mode, value):
        return r_call(root, mode, dict(value, parameters=parameters(plan)))
    original = legacy.evaluate
    bound = FunctionType(original.__code__, dict(vars(legacy), CONFIG=config, r_call=call), original.__name__)
    summary, tables, log = bound(root, targets, source, hgnc_raw, purpose)
    p = checked_plan(plan)["parameters"]
    for group in GROUPS:
        name = group.lower()
        if group not in groups(plan):
            for key in ("all", "significant", "display", "skipped", "background", "effective", "missing"):
                tables[name + "_" + key] = []
            tables["group_summary"].append({"group": group, "included": False, "state_zh": "本方案未纳入",
                "background_count": None, "effective_count": None, "missing_count": None,
                "tested_count": None, "significant_count": None, "display_count": None})
            summary[group + "显著条目数"] = None
        else:
            next(r for r in tables["group_summary"] if r["group"] == group).update(included=True, state_zh="已完成统计")
        top = p["a05.kegg_plot_top"] if group == "KEGG" else p["a05.go_plot_top"]
        tables[name + "_display"] = deepcopy(tables[name + "_significant"][:top])
        if group in groups(plan):
            next(r for r in tables["group_summary"] if r["group"] == group)["display_count"] = len(tables[name + "_display"])
        table_top = p["a05.kegg_table_top"] if group == "KEGG" else p["a05.go_table_top"]
        tables[name + "_plan_top"] = deepcopy(tables[name + "_significant"][:table_top])
    tables["kegg_plan_count_top"] = sorted(tables["kegg_significant"], key=lambda r: (-int(r["Count"]), float(r["p.adjust"]), r["ID"]))[:p["a05.kegg_table_top"]]
    summary.update(protocol_version=VERSION, analysis_parameter_hash=plan["parameter_hash"],
                   effective_parameters=parameters(plan), **{"主显著性": f"BH p.adjust < {p['a05.adjusted_p_max']:g}"})
    return summary, tables, log


def facts(home, inputs):
    """逐件核验绑定方案、A03、注释和HGNC，历史复算不读取最新草稿。"""
    record = read_json(verified_file(home, inputs["analysis_plan_file"]))
    parent = read_json(verified_file(home, inputs["parent_result"]))
    require(record["study_id"] == inputs["study_id"] == parent["study_id"] and
            record["expected_a00"] == inputs["expected_a00"] and record["plan_id"] == inputs["analysis_plan_id"],
            "A05方案或交集不属于本研究登记")
    plan = checked_plan(record["plan"])
    require(plan["parameter_hash"] == inputs["analysis_parameter_hash"], "A05参数指纹不一致")
    source = read_source(verified_file(home, inputs["source_file"]), plan)
    summary, tables, log = evaluate(Path(home).parent.parent, parent["tables"]["intersection_targets"], source,
                                    verified_file(home, inputs["mapping_file"]).read_bytes(),
                                    parent["summary"].get("analysis_purpose"), plan)
    summary["analysis_plan_id"] = record["plan_id"]
    return plan, summary, tables, log


def validator(root, fallback):
    """新协议独立实际R复算；旧统计和展示协议委托原校验器。"""
    def check(run, summary, tables, anomalies, outcome):
        if run["config"].get("version") != VERSION:
            return fallback(run, summary, tables, anomalies, outcome)
        home = Path(root) / "studies" / run["study_id"]
        plan, expected, rows, _ = facts(home, run["inputs"])
        parent = read_json(verified_file(home, run["inputs"]["parent_result"]))
        require(parent["module_id"] == "A03" and parent["run_id"] == run["parent_runs"]["A03"], "A05实际父运行不一致")
        require(fingerprint(run["config"]) == fingerprint(configuration(plan)) and fingerprint(summary) == fingerprint(expected)
                and fingerprint(tables) == fingerprint(rows), "A05统计、参数或表格与实际R复算不一致")
        script = verified_file(home, run["inputs"]["execution_script"])
        require(script.read_bytes() == SCRIPT.read_bytes(), "A05执行脚本与本协议固定版本不一致")
        require(outcome == ("success" if any(rows[g.lower()+"_significant"] for g in groups(plan)) else "empty"), "A05结果状态不一致")
    return check


def publish(workflow, sid, payload, *, progress=None):
    """固定本批方案，锁外取来源和计算，锁内复核上游并经完整校验器发布。"""
    from .plan_contract import validate
    validate(workflow, sid, payload)
    manifest = workflow.load(sid)
    draft = workflow._analysis_plan_records(manifest)[-1]
    reference = deepcopy(manifest["analysis_plan_records"][-1])
    a03 = payload["expected_a03"]
    a03_review = workflow.latest_review(manifest, workflow.run(manifest, a03)["artifact_id"])["review_id"]
    mapping = runtime.mapping_record(workflow, manifest, a03)
    if progress:
        progress("核验固定注释来源及本批参数")
    source_ref = source_snapshot(workflow.root, draft["plan"])
    source_path = verified_file(workflow.root, source_ref)
    home = workflow.location(sid)
    # 原件按内容寻址，不覆盖历史；只有Workflow公开发布入口可以执行此写入。
    archived = home / "raw" / source_path.name
    if not archived.exists():
        archived.write_bytes(source_path.read_bytes())
    require(hashlib.sha256(archived.read_bytes()).hexdigest() == source_ref['sha256'], '本研究A05注释原件与固定来源指纹不一致')
    inputs = {"study_id": sid, "expected_a00": payload["expected_a00"],
              "analysis_plan_id": draft["plan_id"], "analysis_parameter_hash": draft["plan"]["parameter_hash"],
              "analysis_plan_file": reference, "parent_result": deepcopy(manifest["runs"][a03]["result_file"]),
              "mapping_file": mapping, "source_file": file_record(home, archived, "annotation_source")}
    script_path = home / "raw" / ("a05_plan_script_" + hashlib.sha256(SCRIPT.read_bytes()).hexdigest() + ".R")
    if not script_path.exists():
        script_path.write_bytes(SCRIPT.read_bytes())
    inputs['execution_script'] = file_record(home, script_path, 'execution_script')
    if progress:
        progress("按本方案执行ORA及各检验族独立BH校正")
    plan, summary, tables, log = facts(home, inputs)
    with write_lock(workflow.root):
        current = workflow.load(sid)
        require(not current.get("trashed") and current["current"].get("A00") == payload["expected_a00"] and
                current["current"].get("A03") == a03 and current["current"].get("A05", "") == payload["expected_a05"] and
                workflow.approved(current, a03) and workflow.latest_review(current, workflow.run(current, a03)["artifact_id"])["review_id"] == a03_review,
                "A05上游或复核已改变，请刷新；计算原件保留")
        run = workflow._begin(current, "A05", inputs, configuration(plan), payload["reason"])
        folder = home / "runs/A05" / run["run_id"]
        from .plan_figures import draw
        figures = [file_record(home, path, "figure") for path in draw(tables, plan, folder).values()]
        logfile = folder / "R_log.txt"
        logfile.write_text(log, encoding="utf8")
        result = workflow._finish(current, run["run_id"], summary, tables,
            ["GO三类分别BH校正，KEGG单独校正；未纳入类别不执行。", "完整原统计保留；展示数量不改变BH校正，富集不代表通路激活或疗效。"],
            "success" if any(tables[g.lower()+"_significant"] for g in groups(plan)) else "empty",
            sources=[reference, inputs["parent_result"], mapping, inputs["source_file"], inputs['execution_script']], figures=figures,
            attachments=[file_record(home, logfile, "log")])
        workflow.save(current)
    return result

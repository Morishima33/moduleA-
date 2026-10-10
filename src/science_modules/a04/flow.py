"""A04双分支来源契约与显式运行入口；旧版本保持原实现。"""
from pathlib import Path
from contracts import require, fingerprint
from storage import read_json, verified_file, file_record, write_json, write_lock, within
from science_modules.a04.selection import VERSION, from_legacy
import ppi_flow as legacy
from ppi_identity import authorization, context, SNAPSHOT

CONFIG = dict(legacy.CONFIG, version=VERSION, selection_rule=VERSION, ranking_rule="A04.equal_rank.1", identity_rule="STRING.explicit_scope.1")

# 原来源校验和网络指标只计算一次；身份补查必须有当前研究与上游的明确授权。
def evaluate(targets, bundle, purpose, raw=None, scope=None):
    require(bundle.get("schema_version") != "A04.source.2" or (raw is not None and scope is not None), "PPI身份补查缺少本研究、本A03版本的明确授权，不能沿用历史默认授权")
    summary, tables = legacy.evaluate(targets, bundle, purpose, raw, scope)
    return from_legacy(summary, tables)

# 新运行以原来源独立复算；旧运行仍交给冻结校验器。
def validator(root):
    previous = legacy.validator(root)
    def check(run, summary, tables, anomalies, outcome):
        if run.get("config", {}).get("version") != VERSION:
            return previous(run, summary, tables, anomalies, outcome)
        require(run["config"] == CONFIG, "双分支PPI配置与已确认规则不一致")
        home = within(Path(root) / "studies", run["study_id"])
        parent = read_json(verified_file(home, run["inputs"]["parent_result"]))
        require(parent["run_id"] == run["parent_runs"]["A03"], "双分支PPI上游版本不一致")
        source = read_json(verified_file(home, run["inputs"]["source_file"]))
        raw = verified_file(home, run["inputs"]["identity_snapshot"]).read_bytes() if source.get("schema_version") == "A04.source.2" else None
        scope = authorization(run["study_id"], parent["run_id"], Path(root)) if raw is not None else None
        expected = evaluate(parent["tables"]["intersection_targets"], source, parent["summary"].get("analysis_purpose", "research"), raw, scope)
        require((summary, tables) == expected, "双分支名单、阈值或排名与来源复算不一致")
        require(outcome == ("success" if summary["参与节点数"] else "empty"), "双分支PPI空结果状态不一致")
    return check

# 仅供明确启动后的科学子进程调用；本轮实现和范图生成不调用当前研究入口。
def run_ppi(workflow, sid, expected_a03, expected_a04, reason, bundle=None):
    manifest = workflow.load(sid)
    require(not manifest.get("trashed") and manifest["current"].get("A03") == expected_a03 and workflow.active(manifest, expected_a03) and workflow.approved(manifest, expected_a03), "请先复核通过当前有效A03交集")
    require(manifest["current"].get("A04", "") == expected_a04, "PPI版本已改变，请刷新")
    parent = workflow.result(manifest, expected_a03)
    scope = authorization(sid, expected_a03, workflow.root)
    raw = context(workflow.root, sid, expected_a03) if scope is not None else None
    require(raw is None or scope is not None, "身份证据不能在无明确授权时启用")
    source = legacy.fetch(parent["tables"]["intersection_targets"], raw, scope) if bundle is None else bundle
    summary, tables = evaluate(parent["tables"]["intersection_targets"], source, parent["summary"].get("analysis_purpose", "research"), raw, scope)
    with write_lock(workflow.root):
        manifest = workflow.load(sid)
        require(manifest["current"].get("A03") == expected_a03 and manifest["current"].get("A04", "") == expected_a04 and workflow.active(manifest, expected_a03) and workflow.approved(manifest, expected_a03), "上游或PPI版本已改变，请刷新")
        home = workflow.location(sid)
        path = home / "raw" / ("string_" + fingerprint(source) + ".json")
        if not path.exists(): write_json(path, source)
        inputs = {"source_file": file_record(home, path, "string_source"), "parent_result": manifest["runs"][expected_a03]["result_file"]}
        if source.get("schema_version") == "A04.source.2":
            snapshot = home / "raw" / ("hgnc_" + SNAPSHOT + ".tsv")
            if not snapshot.exists(): snapshot.write_bytes(raw)
            inputs["identity_snapshot"] = file_record(home, snapshot, "hgnc_source")
        run = workflow._begin(manifest, "A04", inputs, dict(CONFIG), reason)
        result = workflow._finish(manifest, run["run_id"], summary, tables, ["STRING功能关联不等于直接物理结合。", "两轮均使用完整网络原指标；前十、前十五仅为展示名额，边界并列保留。", "网络图方案和后续对接候选来源尚待用户确认。"], "success" if summary["参与节点数"] else "empty", sources=list(inputs.values()))
        workflow.save(manifest)
    return result

# 未确定新分支的对接来源时，显式中文阻断；不把任一分支塞进旧round1字段。
def docking_validator(root, previous):
    def check(run, *args):
        parent = run.get("parent_runs", {}).get("A04")
        if parent:
            from workflow import Workflow
            workflow = Workflow(Path(root))
            manifest = workflow.load(run["study_id"])
            require(not workflow.result(manifest, parent).get("summary", {}).get("docking_candidate_source_pending"), "双分支PPI的对接候选来源尚未确认，本轮不生成或运行A06")
        return previous(run, *args)
    return check

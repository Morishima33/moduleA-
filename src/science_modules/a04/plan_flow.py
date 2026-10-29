"""A04 新方案 STRING 网络路径。

方案版本的阈值同时进入官方请求、边过滤和复算，旧版 ``ppi_flow`` 保持冻结。
"""
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from time import sleep

import networkx as nx

from contracts import require, fingerprint, safe_id
from storage import read_json, verified_file, write_json, write_lock, file_record, new_id
from science_modules.analysis_protocol import checked_plan

BASE = "https://version-12-0.string-db.org/api/json/"
NETWORKX_VERSION = "3.6.1"


def _threshold(plan):
    plan = checked_plan(plan)
    return plan["parameters"]["a04.required_score"]


def request(method, params, opener=None):
    """请求并保留原始响应；测试可注入 opener，生产只允许官方地址。"""
    url = BASE + method
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(),
                                 headers={"User-Agent": "ModuleA/A04.plan_network.1"})
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=40) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
        require(len(raw) <= 16 * 1024 * 1024, "STRING响应过大，请使用离线资料")
        data = json.loads(raw)
        require(isinstance(data, list), "STRING未返回完整记录列表")
        return {"url": url, "params": params, "response_text": raw.decode("utf-8"),
                "response_sha256": fingerprint(raw.decode("utf-8")), "method": method}
    except (OSError, ValueError) as exc:
        raise ValueError("STRING获取未完成；可重试或导入同研究离线资料包")


def calculate(targets, mapping, network, plan):
    """按新方案阈值计算；中心性算法与旧版相同，阈值不再写死。"""
    threshold = _threshold(plan)
    require(nx.__version__ == NETWORKX_VERSION, "NetworkX版本不一致")
    require(len({x["target_id"] for x in targets}) == len(targets), "交集身份重复")
    lookup, issues, mapped = {}, [], []
    for index, target in enumerate(targets):
        matches = [x for x in mapping if int(x["queryIndex"]) == index]
        valid = (len(matches) == 1 and int(matches[0]["ncbiTaxonId"]) == 9606
                 and matches[0]["preferredName"] == target["symbol"]
                 and matches[0]["stringId"].startswith("9606."))
        if not valid:
            issues.append(dict(target, reason="未返回唯一且名称一致的人类STRING身份",
                               returned="|".join(x.get("preferredName", "") for x in matches)))
            continue
        sid = matches[0]["stringId"]
        require(sid not in lookup, "多个交集基因映射到同一STRING蛋白，须先复核")
        lookup[sid] = target
        mapped.append(dict(target, string_id=sid))
    require(all(0 <= int(x["queryIndex"]) < len(targets) for x in mapping), "STRING映射包含额外查询项")
    graph = nx.Graph()
    graph.add_nodes_from(x["target_id"] for x in mapped)
    edges, discarded = {}, []
    for number, row in enumerate(network, 1):
        a, b = row["stringId_A"], row["stringId_B"]
        score = float(row["score"])
        require(int(row["ncbiTaxonId"]) == 9606 and math.isfinite(score) and 0 <= score <= 1,
                "STRING物种或评分格式错误")
        require(a in lookup and b in lookup, "STRING网络包含未核验或额外节点，请核对来源")
        if a == b or score < threshold:
            discarded.append({"source_row": number, "reason": "自环或低于方案置信度",
                              "score": score, "required_score": threshold})
            continue
        key = tuple(sorted((lookup[a]["target_id"], lookup[b]["target_id"])))
        if key in edges:
            require(edges[key]["score"] == score, "重复STRING边评分不一致，须核对来源")
            continue
        edges[key] = {"source": key[0], "target": key[1], "score": score, "source_row": number}
        graph.add_edge(*key)
    isolated = set(nx.isolates(graph))
    active = graph.subgraph(set(graph) - isolated).copy()
    degree = dict(active.degree())
    bc = nx.betweenness_centrality(active, normalized=False, weight=None)
    cc = nx.closeness_centrality(active, distance=None, wf_improved=True)
    components = sorted(nx.connected_components(active), key=lambda x: (-len(x), sorted(x)))
    part = {gid: i + 1 for i, group in enumerate(components) for gid in group}
    symbols = {x["target_id"]: x["symbol"] for x in targets}
    rows = [{"target_id": gid, "symbol": symbols[gid], "degree": degree[gid], "bc": bc[gid],
             "cc": cc[gid], "component": part[gid]} for gid in sorted(active)]
    thresholds, selected = [], rows
    from statistics import median
    for round_number in (1, 2):
        med = {key: median(x[key] for x in selected) if selected else None for key in ("degree", "bc", "cc")}
        item = {"round": round_number, "population": len(selected),
                "degree": med["degree"] * (2 if round_number == 1 else 1) if selected else None,
                "bc": med["bc"], "cc": med["cc"]}
        thresholds.append(item)
        chosen = {x["target_id"] for x in selected if x["degree"] >= item["degree"]
                  and x["bc"] > item["bc"] and x["cc"] > item["cc"]}
        for row in rows:
            row["round" + str(round_number)] = row["target_id"] in chosen
        selected = [x for x in rows if x["target_id"] in chosen]
    core = sorted([x for x in rows if x["round1"]], key=lambda x: (-x["degree"], x["target_id"]))
    tables = {"mapping": mapped, "identity_issues": issues,
              "isolates": [dict(lookup[sid], string_id=sid, reason="已识别，无达到方案置信度的合格边")
                           for sid in lookup if lookup[sid]["target_id"] in isolated],
              "edges": list(edges.values()), "discarded_edges": discarded, "metrics": rows,
              "round1": core, "round2": [x for x in core if x["round2"]], "thresholds": thresholds}
    summary = {"交集输入数": len(targets), "已识别数": len(mapped), "身份待核验数": len(issues),
               "孤立节点数": len(isolated), "参与节点数": len(active), "合格边数": len(edges),
               "有边分量数": len(components), "第一轮主候选数": len(core),
               "第二轮参考数": len(tables["round2"]), "required_score": threshold,
               "handoff_blocked": bool(issues)}
    return summary, tables


def evaluate(targets, bundle, plan):
    """校验来源参数与方案一致，并复算结果；返回值可直接用于发布前指纹比较。"""
    plan = checked_plan(plan)
    threshold = _threshold(plan)
    require(bundle.get("schema_version") == "A04.plan_source.1", "A04新方案来源包版本不一致")
    require(bundle.get("analysis_plan_id") == plan["parameter_hash"]
            and bundle.get("analysis_parameter_hash") == plan["parameter_hash"],
            "A04来源包与分析方案指纹不一致")
    mapping, network = bundle["mapping"], bundle["network"]
    ids = bundle.get("mapped_string_ids", [])
    expected_network = {"identifiers": "\r".join(ids), "species": 9606,
                       "required_score": int(round(threshold * 1000)), "network_type": "functional",
                       "add_nodes": 0, "caller_identity": "ModuleA"}
    require(network["params"] == expected_network, "STRING网络请求与分析方案阈值不一致")
    summary, tables = calculate(targets, json.loads(mapping["response_text"]),
                                json.loads(network["response_text"]), plan)
    summary.update(analysis_plan_id=bundle["analysis_plan_id"], analysis_parameter_hash=plan["parameter_hash"],
                   STRING版本="12.0", 计算库版本=NETWORKX_VERSION)
    if bundle.get('execution_request_file'):
        summary['analysis_purpose']=bundle.get('analysis_purpose')
    return summary, tables


def fetch(targets, plan, opener=None, evidence=None):
    """按方案置信度生成映射与网络请求；不扩展交集之外的节点。"""
    plan = checked_plan(plan)
    threshold = _threshold(plan)
    mapping_params = {"identifiers": "\r".join(x["symbol"] for x in targets), "species": 9606,
                      "echo_query": 1, "caller_identity": "ModuleA"}
    mapping = request("get_string_ids", mapping_params, opener) if targets else {
        "url": BASE + "get_string_ids", "params": mapping_params, "response_text": "[]",
        "response_sha256": fingerprint("[]"), "method": "get_string_ids"}
    if evidence:evidence('mapping', mapping)
    records = json.loads(mapping["response_text"])
    ids = [x["stringId"] for i, target in enumerate(targets)
           for x in records if int(x["queryIndex"]) == i and int(x["ncbiTaxonId"]) == 9606
           and x["preferredName"] == target["symbol"] and x["stringId"].startswith("9606.")]
    ids = sorted(set(ids))
    network_params = {"identifiers": "\r".join(ids), "species": 9606,
                      "required_score": int(round(threshold * 1000)), "network_type": "functional",
                      "add_nodes": 0, "caller_identity": "ModuleA"}
    network = request("network", network_params, opener) if len(ids) > 1 else {
        "url": BASE + "network", "params": network_params, "response_text": "[]",
        "response_sha256": fingerprint("[]"), "method": "network", "skipped": "少于两个已核验节点"}
    if evidence:evidence('network', network)
    return {"schema_version": "A04.plan_source.1", "string_version": "12.0",
            "analysis_plan_id": plan["parameter_hash"], "analysis_parameter_hash": plan["parameter_hash"],
            "mapped_string_ids": ids, "mapping": mapping, "network": network}


def _plan_record(workflow, manifest, plan_id, expected_a00):
    records = workflow._analysis_plan_records(manifest)
    rows = [row for row in records if row["plan_id"] == plan_id]
    require(len(rows) == 1 and rows[0]["expected_a00"] == expected_a00, "A04方案不属于本研究登记")
    return rows[0]


def publish(workflow, study_id, payload):
    """绑定当前A03与方案、复算来源包并追加A04运行；不批准下游。"""
    fields = {"expected_a00", "expected_a03", "expected_plan_id", "source_file", "reason"}
    require(isinstance(payload, dict) and set(payload) in (fields,fields|{'expected_a04','expected_a03_review'}), "A04发布字段不完整或含未支持选项")
    safe_id(payload["expected_a00"], "run"); safe_id(payload["expected_a03"], "run")
    safe_id(payload["expected_plan_id"], "plan")
    require(isinstance(payload["reason"], str) and payload["reason"].strip(), "请填写A04发布依据")
    with write_lock(workflow.root):
        manifest = workflow.load(study_id)
        require(manifest["current"].get("A00") == payload["expected_a00"]
                and manifest["current"].get("A03") == payload["expected_a03"], "上游版本已改变，请刷新")
        require(workflow.approved(manifest, payload["expected_a03"]), "请先通过当前A03")
        if 'expected_a04' in payload:
            review=workflow.latest_review(manifest,workflow.run(manifest,payload['expected_a03'])['artifact_id'])
            require(manifest['current'].get('A04','')==payload['expected_a04'] and review['review_id']==payload['expected_a03_review'],
                    'A04或A03复核已改变，请刷新；本次STRING原件保留')
        record = _plan_record(workflow, manifest, payload["expected_plan_id"], payload["expected_a00"])
        plan = checked_plan(record["plan"])
        home = workflow.location(study_id)
        source_ref = payload["source_file"]
        source = read_json(verified_file(home, source_ref))
        parent = workflow.result(manifest, payload["expected_a03"])
        targets = parent["tables"]["intersection_targets"]
        summary, tables = evaluate(targets, source, plan)
        summary["analysis_plan_id"] = record["plan_id"]
        summary["analysis_parameter_hash"] = plan["parameter_hash"]
        plan_ref = next(ref for ref in manifest["analysis_plan_records"]
                        if read_json(verified_file(home, ref))["plan_id"] == record["plan_id"])
        inputs = {"study_id": study_id, "bound_a00": payload["expected_a00"],
                  "parent_result": manifest["runs"][payload["expected_a03"]]["result_file"],
                  "source_file": source_ref, "analysis_plan_id": record["plan_id"],
                  "analysis_plan_file": plan_ref,
                  "analysis_parameter_hash": plan["parameter_hash"]}
        run = workflow._begin(manifest, "A04", inputs,
                              {"version": "A04.plan_network.1", "string_version": "12.0",
                               "required_score": int(round(_threshold(plan) * 1000)),
                               "network_type": "functional", "add_nodes": 0,
                               "analysis_plan_id": record["plan_id"],
                               "analysis_parameter_hash": plan["parameter_hash"]}, payload["reason"])
        result = workflow._finish(manifest, run["run_id"], summary, tables,
                                  ["新方案A04来源、方案和A03已绑定；仍需独立复核。"],
                                  "success" if summary["参与节点数"] else "empty",
                                  sources=[source_ref, inputs["parent_result"]])
        workflow.save(manifest)
        return result


def validator(root, fallback):
    """新方案运行按绑定来源复算；旧A04运行继续使用冻结校验器。"""
    def check(run, summary, tables, anomalies, outcome):
        if run["config"].get("version") != "A04.plan_network.1":
            return fallback(run, summary, tables, anomalies, outcome)
        home = Path(root) / "studies" / run["study_id"]
        require(run["inputs"]["study_id"] == run["study_id"], "A04输入研究绑定不一致")
        source = read_json(verified_file(home, run["inputs"]["source_file"]))
        parent = read_json(verified_file(home, run["inputs"]["parent_result"]))
        plan_record = read_json(verified_file(home, run["inputs"]["analysis_plan_file"]))
        require(plan_record["study_id"] == run["study_id"]
                and plan_record["plan_id"] == run["inputs"]["analysis_plan_id"]
                and plan_record["expected_a00"] == run["inputs"]["bound_a00"],
                "A04方案记录与研究或登记绑定不一致")
        plan = checked_plan(plan_record["plan"])
        if source.get('execution_request_file'):
            from science_modules.plan_stages_contract import verified_request
            verified_request(home,source['execution_request_file'],'A04',plan_record['plan_id'],run['inputs']['bound_a00'])
            require(source.get('analysis_purpose')==parent['summary'].get('analysis_purpose'),'A04研究用途与本次A03不同')
        require(plan["parameter_hash"] == run["inputs"]["analysis_parameter_hash"], "A04方案指纹不一致")
        require(run["config"]["analysis_plan_id"] == plan_record["plan_id"]
                and run["config"]["analysis_parameter_hash"] == plan["parameter_hash"],
                "A04运行配置与方案绑定不一致")
        require(run["config"]["required_score"] == int(round(_threshold(plan) * 1000)), "A04阈值配置被改变")
        expected, expected_tables = evaluate(parent["tables"]["intersection_targets"], source, plan)
        expected["analysis_plan_id"] = run["inputs"]["analysis_plan_id"]
        require((summary, tables) == (expected, expected_tables), "A04结果与绑定来源复算不一致")
        require(outcome == ("success" if summary["参与节点数"] else "empty"), "A04状态与结果不一致")
    return check


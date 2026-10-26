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

from contracts import require, fingerprint
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
              "round1": core, "round2": [x for x in core if x["round2"]], "thresholds": thresholds,
              "required_score": threshold}
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
    return summary, tables


def fetch(targets, plan, opener=None):
    """按方案置信度生成映射与网络请求；不扩展交集之外的节点。"""
    plan = checked_plan(plan)
    threshold = _threshold(plan)
    mapping_params = {"identifiers": "\r".join(x["symbol"] for x in targets), "species": 9606,
                      "echo_query": 1, "caller_identity": "ModuleA"}
    mapping = request("get_string_ids", mapping_params, opener) if targets else {
        "url": BASE + "get_string_ids", "params": mapping_params, "response_text": "[]",
        "response_sha256": fingerprint("[]"), "method": "get_string_ids"}
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
    return {"schema_version": "A04.plan_source.1", "string_version": "12.0",
            "analysis_plan_id": plan["parameter_hash"], "analysis_parameter_hash": plan["parameter_hash"],
            "mapped_string_ids": ids, "mapping": mapping, "network": network}


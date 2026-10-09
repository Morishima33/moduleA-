# A04纯计算：所有有合格边分量统一计算，不重建第二轮网络。
import sys  # 只加载项目固定依赖。
import math  # 校验数值和绘图坐标。
from pathlib import Path  # 固定项目环境。
from statistics import median  # 中位数不提前四舍五入。
from html import escape  # 图内名称安全转义。
from contracts import require  # 无效资料明确停止。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "environments/python_packages"))  # 不依赖旧Kimi环境。
import networkx as nx  # 使用已批准算法的固定实现。
CONFIG = {"version":"A04.1", "species":9606, "string_version":"12.0", "network_type":"functional", "required_score":900, "add_nodes":0, "degree_weighted":False, "bc_normalized":False, "cc_wf_improved":True, "networkx":"3.6.1"}  # 大纲6.5的固定参数。

def calculate(targets, mapping, network):  # 输入为交集、官方映射和官方网络原响应。
    require(nx.__version__ == CONFIG["networkx"], "NetworkX版本不一致")  # 不静默改变算法实现。
    require(len({x["target_id"] for x in targets}) == len(targets), "交集身份重复")  # 上游应为标准去重集合。
    lookup, issues, mapped = {}, [], []  # 未识别与已识别分别记录。
    for index, target in enumerate(targets):  # 按实际请求顺序关联响应。
        matches = [x for x in mapping if int(x["queryIndex"]) == index]  # 不凭返回顺序猜编号。
        valid = len(matches) == 1 and int(matches[0]["ncbiTaxonId"]) == 9606 and matches[0]["preferredName"] == target["symbol"] and matches[0]["stringId"].startswith("9606.")  # 首版仅自动接受精确一致名称，其他交专业核对。
        if not valid:  # 不把模糊映射当孤立节点。
            issues.append(dict(target, reason="未返回唯一且名称一致的人类STRING身份", returned="|".join(x.get("preferredName", "") for x in matches)))  # 原响应仍归档。
            continue  # 不给未识别者伪造Degree=0。
        sid = matches[0]["stringId"]  # 已核验STRING编号。
        require(sid not in lookup, "多个交集基因映射到同一STRING蛋白，须先复核")  # 不合并不同基因。
        lookup[sid] = target  # 入网成员限定原交集。
        mapped.append(dict(target, string_id=sid))  # 保存可回查映射。
    require(all(0 <= int(x["queryIndex"]) < len(targets) for x in mapping), "STRING映射包含额外查询项")  # 防止外部节点混入。
    graph = nx.Graph()  # 无向、无权简单网络。
    graph.add_nodes_from(x["target_id"] for x in mapped)  # 已识别孤立节点保留。
    edges, discarded = {}, []  # 重复边去重但原网络原文不丢。
    for number, row in enumerate(network, 1):  # 保留原响应行定位。
        a, b = row["stringId_A"], row["stringId_B"]  # 使用STRING稳定编号。
        score = float(row["score"])  # 官方JSON为0至1。
        require(int(row["ncbiTaxonId"]) == 9606 and math.isfinite(score) and 0 <= score <= 1, "STRING物种或评分格式错误")  # 不猜0至1000格式。
        require(a in lookup and b in lookup, "STRING网络包含未核验或额外节点，请核对来源")  # 不静默截去外部邻居。
        if a == b or score < 0.9:  # 自环不属于本简单图，低分不合格。
            discarded.append({"source_row":number, "reason":"自环或低于0.9", "score":score})  # 排除原因留存。
            continue  # 不进入中心性计算。
        key = tuple(sorted((lookup[a]["target_id"], lookup[b]["target_id"])))  # 无向重复边只计一次。
        if key in edges:  # 重复证据不得增加Degree。
            require(edges[key]["score"] == score, "重复STRING边评分不一致，须核对来源")  # 不任取一个分数。
            continue  # 一致重复原始行仍在原文。
        edges[key] = {"source":key[0], "target":key[1], "score":score, "source_row":number}  # 边证据可追溯。
        graph.add_edge(*key)  # 明确不将score当作路径长度或权重。
    isolated = set(nx.isolates(graph))  # 已识别但无合格边。
    active = graph.subgraph(set(graph) - isolated).copy()  # 主分析保留全部有边分量。
    degree = dict(active.degree())  # 无权连边数。
    bc = nx.betweenness_centrality(active, normalized=False, weight=None)  # 未归一化BC。
    cc = nx.closeness_centrality(active, distance=None, wf_improved=True)  # 全网可达比例修正CC。
    components = sorted(nx.connected_components(active), key=lambda x:(-len(x), sorted(x)))  # 最大分量仅作显示。
    part = {gid:i+1 for i,group in enumerate(components) for gid in group}  # 分量编号不改变筛选总体。
    symbols = {x["target_id"]:x["symbol"] for x in targets}  # 统一显示名称。
    rows = [{"target_id":gid, "symbol":symbols[gid], "degree":degree[gid], "bc":bc[gid], "cc":cc[gid], "component":part[gid]} for gid in sorted(active)]  # 全参与节点指标。
    thresholds = []  # 两轮阈值均保存，空集为None。
    selected = rows  # 第一轮使用全体参与节点。
    for round_number in (1, 2):  # 第二轮只重取中位数，不重算指标。
        med = {key:median(x[key] for x in selected) if selected else None for key in ("degree", "bc", "cc")}  # 空集不崩溃。
        threshold = {"round":round_number, "population":len(selected), "degree":med["degree"] * (2 if round_number == 1 else 1) if selected else None, "bc":med["bc"], "cc":med["cc"]}  # 精确大纲不等号。
        thresholds.append(threshold)  # 记录实际筛选总体和数值。
        chosen = {x["target_id"] for x in selected if x["degree"] >= threshold["degree"] and x["bc"] > threshold["bc"] and x["cc"] > threshold["cc"]}  # 三条件同时满足。
        for row in rows:  # 全量保留两轮是否入选。
            row["round" + str(round_number)] = row["target_id"] in chosen  # 不覆盖指标。
        selected = [x for x in rows if x["target_id"] in chosen]  # 下一轮只在上一轮候选中取阈值。
    core = sorted([x for x in rows if x["round1"]], key=lambda x:(-x["degree"], x["target_id"]))  # 第一轮为主集合。
    tables = {"mapping":mapped, "identity_issues":issues, "isolates":[dict(lookup[sid], string_id=sid, reason="已识别，无score≥0.9合格边") for sid in lookup if lookup[sid]["target_id"] in isolated], "edges":list(edges.values()), "discarded_edges":discarded, "metrics":rows, "round1":core, "round2":[x for x in core if x["round2"]], "thresholds":thresholds}  # 原表与主/参考子集可对照。
    summary = {"交集输入数":len(targets), "已识别数":len(mapped), "身份待核验数":len(issues), "孤立节点数":len(isolated), "参与节点数":len(active), "合格边数":len(edges), "有边分量数":len(components), "第一轮主候选数":len(core), "第二轮参考数":len(tables["round2"]), "handoff_blocked":bool(issues)}  # 未识别问题不自动获得排除授权。
    return summary, tables  # 下游以明确复核后的第一轮主集合为起点。

def network_svg(tables):  # 确定性示意图，图形位置不是科学指标。
    rows = sorted(tables["metrics"], key=lambda x:x["target_id"])  # 稳定显示顺序。
    positions = {x["target_id"]:(350+270*math.cos(2*math.pi*i/max(1,len(rows))),350+270*math.sin(2*math.pi*i/max(1,len(rows)))) for i,x in enumerate(rows)}  # 不增加随机种子或依赖。
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 730"><rect width="700" height="730" fill="white"/><text x="350" y="25" text-anchor="middle">PPI全部有边分量；橙色为第一轮主候选</text>']  # 面积及位置不解释为关联强弱。
    for edge in tables["edges"]:  # 仅绘制实际合格边。
        a,b=positions[edge["source"]],positions[edge["target"]]  # 两端来自已核验成员。
        parts.append(f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="#cbd5e1" stroke-width=".6"/>')  # 坐标只是布局。
    for row in rows:  # 所有参与节点可悬停查看名称。
        x,y=positions[row["target_id"]]  # 固定节点位置。
        color="#e58b35" if row["round1"] else "#3486a0"  # 颜色来自同一筛选结果。
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="{color}"><title>{escape(row["symbol"])}</title></circle>')  # 名称安全转义。
    parts.append('</svg>')  # 完成标准SVG。
    return ''.join(parts)  # 孤立节点另外列示，不混入中心性总体。

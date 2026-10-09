# A03使用同一HGNC快照的已复核上游，不替代A02正式筛选。
import re  # 检查标准标识格式。
from pathlib import Path  # 定位同次运行文件。
from contracts import require  # 复用统一错误报告。
from storage import write_lock, write_json, file_record  # 复用研究留存和完整性规则。
from intersection import calculate, coverage  # 同一计算内核供网页和测试使用。

CONFIG = {"version": "A03.1", "namespace": "HGNC", "max_candidates": 5}  # 已确认的交集与主候选规则。
SELECT_CONFIG = {"version": "A03.select.1", "max_candidates": 5}  # 选择仅影响对接分支。
SELECT_CONFIG_EXPANDED = {"version": "A03.select.2", "base_max_candidates": 5, "expansion": ["cutoff_ties", "uncovered_herb_top"], "manual_confirmation_required": True}  # 人工决定时可纳入截断并列和药味代表。
SELECT_CONFIG_MANUAL = {"version": "A03.select.3", "base_max_candidates": 5, "expansion": ["cutoff_ties", "uncovered_herb_top", "explicit_manual_supplements"], "manual_confirmation_required": True}  # 人工补充另立版本，旧规则不改写。
SELECT_CONFIG_MANUAL_PRECISE = dict(SELECT_CONFIG_MANUAL, version="A03.select.4", cutoff_role="distinguish_single_cutoff")  # 修正单独第五位的标签，新旧表都能原样复算。
FIELD_MANUAL_REASON = "manual_selection_reason"  # 本版逐项人工理由固定字段。
TABLE_LABELS = {"formula_targets": "方剂靶点T", "disease_targets": "疾病靶点D", "intersection_targets": "交集靶点I", "ranking": "按交集靶点数主排序", "degree_ranking": "按混合Degree参考排序", "formula_evidence": "方剂逐靶点来源", "disease_evidence": "疾病逐靶点来源", "network_edges": "混合网络连边", "suggestions": "主候选建议与边界并列", "selected": "已选择主候选", "coverage": "药味覆盖", "supplements": "补充候选（不自动对接）"}  # 科学表以中文展示。
FIELD_LABELS = {"target_id": "HGNC编号", "symbol": "标准基因符号", "namespace": "标识体系", "compound_id": "成分编号", "name": "成分名称", "species": "物种", "source_ref": "来源定位", "herb": "药味", "herbs": "全部来源药味", "main_rank": "主排序名次", "degree_rank": "Degree参考名次", "intersection_count": "不同交集靶点数", "target_edges": "靶点边数", "herb_edges": "药味边数", "mixed_degree": "混合Degree", "in_network": "参与交集混合图", "group": "建议分组", "selection_role": "入选角色", "covered": "主候选已覆盖", "supplement_count": "补充候选数", "status": "状态", "automatic_docking": "自动进入对接", "proposed_for": "为哪些药味提出", "source": "起点", "target": "终点", "edge_type": "边类型"}  # 不改变原字段数据。

FIELD_LABELS[FIELD_MANUAL_REASON] = "人工补充入选理由"  # 网页明细以中文显示新理由。

def payload_from(a01, a02):  # 正式上游接口要求显式标准化结果。
    require(not a02["summary"].get("handoff_blocked"), "A02候选不能用于正式交集")  # 不绕过候选阶段阻断。
    first, second = a01["summary"].get("mapping_snapshot"), a02["summary"].get("mapping_snapshot")  # 两侧必须使用同一快照。
    require(isinstance(first, str) and re.fullmatch(r"[0-9a-f]{64}", first) and first == second, "A01与A02尚未使用同一HGNC映射快照，不能计算正式交集")  # 不把原始名称当标准编号。
    require(a01["summary"].get("namespace") == a02["summary"].get("namespace") == "HGNC", "上游靶点身份体系必须为HGNC")  # 冻结统一身份规则。
    rule_one, rule_two = a01["summary"].get("mapping_rule"), a02["summary"].get("mapping_rule")  # 数据快照相同不代表映射处理规则相同。
    require(rule_one == rule_two, "A01与A02的基因映射规则版本不同，请使用同一规则重新整理")  # 兼容均无规则字段的历史合同测试，禁止单边遗漏或版本不一致。
    require(a01["summary"].get("identity_evidence_snapshot") == a02["summary"].get("identity_evidence_snapshot"), "A01与A02补充身份依据不同，请使用同一证据包")  # 不能只比较HGNC原表。
    one, two = a01["tables"], a02["tables"]  # 读取明确的上游表。
    require("normalized_compound_targets" in one and "normalized_targets" in two, "上游标准化靶点表尚未生成")  # 不回退到候选或旧符号表。
    return {"components": one["components"], "memberships": one["herb_components"], "compound_targets": one["normalized_compound_targets"], "disease_targets": two["normalized_targets"], "herbs": [row["herb"] for row in one["herb_summary"]], "namespace": "HGNC", "mapping_snapshot": first, "analysis_purpose": "workflow_test" if any(result["summary"].get("analysis_purpose") == "workflow_test" for result in (a01, a02)) else "research"}  # 输入完整绑定上游结果。

def build(payload):  # 生成图表共享的唯一事实集。
    require(payload.get("namespace") == "HGNC" and isinstance(payload.get("mapping_snapshot"), str) and re.fullmatch(r"[0-9a-f]{64}", payload["mapping_snapshot"]), "A03输入须声明HGNC及映射快照指纹")  # 校验固定交接身份。
    symbols = {}  # 同一HGNC编号不得带冲突符号。
    for row in payload["compound_targets"] + payload["disease_targets"]:  # 两侧统一检查。
        require(re.fullmatch(r"HGNC:\d+", row.get("target_id", "")) and bool(row.get("symbol")), "标准化靶点缺少HGNC编号或标准符号")  # 不接受临时名称键。
        symbols.setdefault(row["target_id"], row["symbol"])  # 固定当前快照符号。
        require(symbols[row["target_id"]] == row["symbol"], "同一HGNC编号出现冲突符号")  # 不按第一项静默处理。
    calc = calculate(*(payload[key] for key in ("components", "memberships", "compound_targets", "disease_targets", "herbs", "namespace")))  # 调用可独立复算内核。
    target_rows = lambda key: [{"target_id": row["target_id"], "symbol": symbols[row["target_id"]], "namespace": "HGNC"} for row in calc["sets"] if row[key]]  # T/D/I直接来自同一成员表。
    tables = {"formula_targets": target_rows("in_formula"), "disease_targets": target_rows("in_disease"), "intersection_targets": target_rows("in_intersection"), "ranking": calc["ranking"], "formula_evidence": calc["formula_evidence"], "disease_evidence": calc["disease_evidence"]}  # 来源证据不因去重丢失。
    tables["degree_ranking"] = sorted(calc["ranking"], key=lambda row: (-row["mixed_degree"], row["compound_id"]))  # 第二张排序表不改变主候选顺序。
    inside = {row["target_id"] for row in tables["intersection_targets"]}  # 网络仅用交集靶点。
    active = {row["compound_id"] for row in calc["ranking"] if row["in_network"]}  # 零命中成分只在完整排名表保留。
    edges = {("成分:" + row["compound_id"], "靶点:" + row["target_id"], "成分—靶点") for row in payload["compound_targets"] if row["target_id"] in inside}  # 节点类型前缀避免名称碰撞。
    edges |= {("药味:" + row["herb"], "成分:" + row["compound_id"], "药味—成分") for row in payload["memberships"] if row["compound_id"] in active}  # 共享成分保留所有药味边。
    tables["network_edges"] = [{"source": a, "target": b, "edge_type": kind} for a, b, kind in sorted(edges)]  # 关系去重后稳定导出。
    tables["suggestions"] = [{"compound_id": cid, "group": "边界以上建议" if cid in calc["above_cutoff"] else ("截断处并列，待选择" if calc["requires_tie_review"] else "主候选建议，待身份确认")} for cid in calc["above_cutoff"] + calc["boundary"]]  # 建议不等于自动批准。
    summary = {"方剂靶点数": calc["counts"]["formula"], "疾病靶点数": calc["counts"]["disease"], "交集靶点数": calc["counts"]["intersection"], "仅方剂靶点数": calc["counts"]["formula_only"], "仅疾病靶点数": calc["counts"]["disease_only"], "截断处需要并列选择": calc["requires_tie_review"], "边界可选名额": calc["boundary_slots"], "候选状态": "在A03主候选确认关口选择；不阻断交集单独复核", "namespace": "HGNC", "mapping_snapshot": payload["mapping_snapshot"]}  # 不制造关联强弱综合分。
    if payload.get("analysis_purpose") == "workflow_test":  # 测试用途随交集传递。
        summary["analysis_purpose"] = "workflow_test"  # 不将旧资料测试伪装正式研究。
    return calc, summary, tables  # 网页和归档从同一输出读取。

def study_labels(workflow, manifest, run_id):  # 图名绑定该次运行的登记版本，不能取另一次研究名称。
    run = workflow.run(manifest, run_id)  # 读取真实A03来源链。
    a01 = workflow.run(manifest, run["parent_runs"]["A01"])  # 定位当时的方剂模块。
    intake = workflow.result(manifest, a01["parent_runs"]["A00"])["summary"]  # 使用当时登记信息。
    disease = intake["disease"]  # 保留疾病原名。
    return intake["formula"], "COPD" if disease.casefold() == "copd" else disease  # 仅规范已知缩写显示，不更改登记。


def venn_svg(summary, formula="方剂", disease="疾病"):  # 名称只影响图面，不改变科学计数。
    from html import escape  # 防止研究名称成为SVG代码。
    from textwrap import wrap  # 长名称自动分行，完整保留。
    left, middle, right = (int(summary[key]) for key in ("仅方剂靶点数", "交集靶点数", "仅疾病靶点数"))  # 同一归档计数。
    names = [wrap(str(formula) + "（T）", width=20) or ["方剂（T）"], wrap(str(disease) + "（D）", width=20) or ["疾病（D）"]]  # 每侧独立换行。
    top = max(map(len, names)) * 20 + 15  # 名称长时向下移动圆形，避免遮挡。
    labels = "".join('<text x="' + str(x) + '" y="20" font-size="15">' + "".join('<tspan x="' + str(x) + '" dy="' + ("0" if number == 0 else "20") + '">' + escape(line) + '</tspan>' for number, line in enumerate(lines)) + '</text>' for x, lines in zip((145, 455), names))  # 所有名称安全转义。
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 ' + str(top + 250) + '" role="img" aria-label="方剂与疾病靶点交集示意图"><rect width="600" height="100%" fill="white"/><ellipse cx="235" cy="' + str(top + 100) + '" rx="155" ry="100" fill="#4ca6be" fill-opacity=".35" stroke="#267c95"/><ellipse cx="365" cy="' + str(top + 100) + '" rx="155" ry="100" fill="#e8ad55" fill-opacity=".35" stroke="#aa7123"/><g text-anchor="middle" font-family="sans-serif" fill="#203342">' + labels + "".join('<text x="' + str(x) + '" y="' + str(top + 110) + '" font-size="26">' + str(value) + '</text>' for x, value in zip((170, 300, 430), (left, middle, right))) + '<text x="300" y="' + str(top + 235) + '">交集 I = T ∩ D；面积仅作示意，不代表数量比例</text></g></svg>'  # 图内数量与原结果一致。


def validate_intersection(run, summary, tables, anomalies, outcome):  # 提交前独立复算所有表和摘要。
    require(run["config"] == CONFIG, "A03配置不一致")  # 不静默改规则。
    calc, expected, expected_tables = build(run["inputs"]["payload"])  # 从固定输入重新计算。
    require(summary == expected and tables == expected_tables, "A03结果与固定输入复算不一致")  # 拒绝改数或漏表。
    require(outcome == ("success" if calc["counts"]["intersection"] else "empty"), "A03空集状态不一致")  # 空结果不是执行失败。

def run_intersection(workflow, study_id, expected, reason):  # 实际网页与自动调用统一入口。
    with write_lock(workflow.root):  # 固定上游和当前运行版本。
        manifest = workflow.load(study_id)  # 不操作其他研究。
        require(all(manifest["current"].get(key, "") == expected.get(key, "") for key in ("A01", "A02", "A03")), "页面版本已改变，请刷新后运行A03")  # 防止重复提交旧页。
        require(all(manifest["current"].get(key) and workflow.approved(manifest, manifest["current"][key]) for key in ("A01", "A02")), "A01或A02尚未复核通过")  # 真实候选仍被阻断。
        payload = payload_from(*(workflow.result(manifest, manifest["current"][key]) for key in ("A01", "A02")))  # 读取已核验的来源。
        calc, summary, tables = build(payload)  # 预检完成后才建立运行。
        run = workflow._begin(manifest, "A03", {"payload": payload}, dict(CONFIG), reason)  # 沿用统一父版本及批准记录。
        root = workflow.location(study_id)  # 所有文件在本研究包。
        folder = root / "runs" / "A03" / run["run_id"]  # 同一运行路径。
        with (folder / "venn.svg").open("x", encoding="utf-8") as stream:  # 不覆盖旧图。
            stream.write(venn_svg(summary, *study_labels(workflow, manifest, run["run_id"])))  # 图和集合表同源。
        result = workflow._finish(manifest, run["run_id"], summary, tables, ["两种排序相关，不相加、不代表对接效果或疗效。", "韦恩图面积仅作示意；主候选另行确认，不影响交集独立复核。"], "success" if calc["counts"]["intersection"] else "empty", figures=[file_record(root, folder / "venn.svg", "figure")])  # 关联真实图形及校验。
        workflow.save(manifest)  # 发布待复核交集，不自动批准。
        return result  # 当前结果可重新打开。

def select_build(inputs):  # 主候选选择与交集计算分开。
    calc, unused, tables = build(inputs["payload"])  # 保留原始候选排名。
    require(inputs.get("identity_confirmed") is True, "请确认所选成分身份已核对")  # 结构身份不能由排名代替。
    manual_policy = inputs.get("selection_policy") in ("explicit_manual_supplements", "explicit_manual_supplements_v2")  # 人工补充策略必须显式登记。
    manual = inputs.get("manual_supplements", {}) if manual_policy else {}  # 历史运行不读取新字段。
    require(not manual_policy or bool(manual), "人工补充策略缺少逐项理由")  # 防止自动切换策略绕过默认规则。
    expanded = manual_policy or inputs.get("selection_policy") == "boundary_ties_and_herb_representatives"  # 只有明确记录的扩展策略可超过五个。
    choice = coverage(calc, inputs["selected"], inputs["payload"]["herbs"], inputs["reviewer"], inputs["reason"], expanded, manual)  # 核查预算、资格并生成补充。
    rows = {row["compound_id"]: row for row in calc["ranking"]}  # 本次结果唯一身份索引。
    selected_rows = []  # 正式候选逐项记录选择角色。
    for cid in choice["selected"]:  # 保持用户提交顺序。
        row = dict(rows[cid])  # 不修改A03原排名表。
        if expanded:  # 旧A03.select.1结果必须保持原表结构可复算。
            row["selection_role"] = choice["roles"][cid]  # 新版区分并列纳入与药味代表纳入。
        if inputs.get('selection_policy') == 'explicit_manual_supplements_v2' and cid in calc['boundary'] and not calc['requires_tie_review'] and cid not in manual:  # 第五位无并列时不能写成并列入选。
            row['selection_role'] = '主排序前五候选'  # 只修正角色文字，排名及数值保持不变。
        selected_rows.append(row)  # 下游仍从selected统一读取正式对接对象。
        if manual_policy and cid in manual:  # 逐项理由进入新表且不修改历史表。
            row['manual_selection_reason'] = manual[cid]  # 报告可以说明排名之外的人工目的。
    if expanded:  # 新版保存扩展角色和策略。
        promoted = sum(row["selection_role"] == "药味代表性补充纳入" for row in selected_rows)  # 汇总正式提升的药味代表数。
        summary = {"主候选数": len(choice["selected"]), "补充候选数": len(choice["supplements"]), "药味代表性纳入数": promoted, "选择策略": "并列边界及未覆盖药味代表人工扩展", "复核人": choice["reviewer"], "选择及替换理由": choice["reason"], "身份核对": "已由提交人确认", "补充用途": "未正式纳入者仅保存待评估，不自动进入对接"}  # 仍需总体复核通过才能给对接用。
    else:  # 历史默认版本按原合同重建，避免旧研究失效。
        summary = {"主候选数": len(choice["selected"]), "补充候选数": len(choice["supplements"]), "复核人": choice["reviewer"], "选择及替换理由": choice["reason"], "身份核对": "已由提交人确认", "补充用途": "仅保存待评估，不自动进入对接"}  # 与A03.select.1原结果完全一致。
    if inputs["payload"].get("analysis_purpose") == "workflow_test":  # 主候选也保留测试标签。
        summary["analysis_purpose"] = "workflow_test"  # 用途不在选择关口丢失。
    if manual_policy:  # 新版准确说明人工补充，不再声称全部扩展都是并列。
        summary.update(选择策略="前列候选、药味代表及逐项明确人工补充", 人工补充纳入数=len(manual))  # 数量直接来自本次明确决定。
    return summary, {"selected": selected_rows, "coverage": choice["coverage"], "supplements": choice["supplements"]}  # 少于五个或人工扩展均如实保存。

def validate_selection(run, summary, tables, anomalies, outcome):  # 选择结果也按固定输入复算。
    expected_config = SELECT_CONFIG_MANUAL_PRECISE if run['inputs'].get('selection_policy') == 'explicit_manual_supplements_v2' else (SELECT_CONFIG_MANUAL if run['inputs'].get('selection_policy') == 'explicit_manual_supplements' else (SELECT_CONFIG_EXPANDED if run["inputs"].get("selection_policy") == "boundary_ties_and_herb_representatives" else SELECT_CONFIG))  # 按归档策略选择固定配置。
    require(run["config"] == expected_config, "候选配置不一致")  # 固定默认或扩展规则。
    expected, expected_tables = select_build(run["inputs"])  # 不仅检查数量。
    require(summary == expected and tables == expected_tables and outcome == ("success" if tables["selected"] else "empty"), "主候选结果校验失败")  # 无候选不能伪造成功名单。

def run_selection(workflow, study_id, expected_a03, expected_select, selected, reviewer, reason, confirmed, manual_supplements=None):  # 保存独立选择版本。
    with write_lock(workflow.root):  # 防止同时修改候选。
        manifest = workflow.load(study_id)  # 获取当前研究。
        require(manifest["current"].get("A03") == expected_a03 and manifest["current"].get("A03_SELECT", "") == expected_select, "候选页面版本改变，请刷新")  # 旧页不能覆盖新选择。
        require(workflow.approved(manifest, expected_a03), "请先复核交集结果")  # 选择依赖明确交集版本。
        payload = workflow.run(manifest, expected_a03)["inputs"]["payload"]  # 不重新取另一个研究的成分。
        policy = "explicit_manual_supplements_v2" if manual_supplements else ("boundary_ties_and_herb_representatives" if len(selected) > SELECT_CONFIG["max_candidates"] else "default_top_five")  # 人工补充不能自动从数量或旧选择推断。
        inputs = {"payload": payload, "selected": selected, "reviewer": reviewer, "reason": reason, "identity_confirmed": confirmed, "selection_policy": policy}  # 留存人工选择依据。
        if manual_supplements:  # 新字段只属于明确使用新策略的运行。
            inputs['manual_supplements'] = dict(manual_supplements)  # 与本次名单和运行共同归档。
        summary, tables = select_build(inputs)  # 无效选择写入前拒绝。
        config = SELECT_CONFIG_MANUAL_PRECISE if manual_supplements else (SELECT_CONFIG_EXPANDED if policy == "boundary_ties_and_herb_representatives" else SELECT_CONFIG)  # 配置与输入策略一一对应。
        run = workflow._begin(manifest, "A03_SELECT", inputs, dict(config), reason)  # 只更改候选分支。
        anomalies = ["超过五个包括逐项明确的人工补充；原名次保留，候选选择不能证明结合活性。"] if manual_supplements else ["超过五个仅因截断并列及药味代表性人工纳入；候选选择不能证明结合活性。"]  # 新版解释不混用旧版限制。
        result = workflow._finish(manifest, run["run_id"], summary, tables, anomalies, "success" if selected else "empty")  # 原交集版本保持。
        workflow.save(manifest)  # 按统一规则发布待复核结果。
        return result  # 不自动批准。

"""A03纯计算内核：输入须由上游完成同一标识体系的复核。"""  # 不自行执行基因名称映射。
from contracts import require  # 沿用项目统一校验错误。


def calculate(components, memberships, compound_targets, disease_targets, herbs, namespace):  # 供后续编排复用的计算入口。
    require(isinstance(namespace, str) and bool(namespace.strip()), "必须声明上下游共同使用的靶点标识体系")  # 不猜测符号对应关系。
    ids = [row["compound_id"] for row in components]  # 使用稳定成分编号。
    require(len(ids) == len(set(ids)), "成分编号重复，请先完成身份整理")  # 不静默合并身份。
    require(len(herbs) == len(set(herbs)), "药味清单重复")  # 药味节点只出现一次。
    names = {row["compound_id"]: row["name"] for row in components}  # 展示名称不作为身份键。
    origins = {cid: set() for cid in ids}  # 保留全部共享药味。
    for row in memberships:  # 检查药味与成分边。
        require(row["compound_id"] in names and row["herb"] in herbs, "药味关系引用未知成员")  # 防止跨集合混入。
        origins[row["compound_id"]].add(row["herb"])  # 重复来源边只计一次。
    targets = {cid: set() for cid in ids}  # 靶点按成分分别去重。
    evidence = []  # 来源明细与用于计数的边分开。
    for row in compound_targets:  # 接收已整理的人类关系。
        require(row["compound_id"] in names and row["species"] == 9606, "方剂关系包含未知成分或非人类靶点")  # 不跨物种求交集。
        require(isinstance(row["target_id"], str) and bool(row["target_id"].strip()) and bool(row.get("source_ref")), "方剂靶点缺少标识或来源定位")  # 不能把缺失标识计为节点。
        require(bool(origins[row["compound_id"]]), "有靶点的成分缺少药味来源")  # 混合图必须有完整来源边。
        targets[row["compound_id"]].add(row["target_id"])  # 不擅自转换大小写。
        evidence.append(dict(row))  # 保留原始来源关系。
    disease = set()  # 疾病主集合使用同一标识。
    for row in disease_targets:  # 候选收集表不能直接作为本接口输入。
        require(row["species"] == 9606 and isinstance(row["target_id"], str) and bool(row["target_id"].strip()) and bool(row.get("source_ref")), "疾病靶点缺少人类身份、标识或来源定位")  # 检查最小交接字段。
        disease.add(row["target_id"])  # 多库命中仍只计一个节点。
    formula = set().union(*targets.values()) if targets else set()  # 空方剂集合也能正常返回。
    intersection = formula & disease  # 全部交集供后续PPI和富集使用。
    ranking = []  # 两项指标分开保存。
    for cid in ids:  # 零命中成分也在完整表中保留。
        count = len(targets[cid] & intersection)  # 只计不同交集靶点。
        herb_count = len(origins[cid]) if count else 0  # 无交集边的成分不进入当前交集混合图。
        ranking.append({"compound_id": cid, "name": names[cid], "intersection_count": count, "target_edges": count, "herb_edges": herb_count, "mixed_degree": count + herb_count, "herbs": "、".join(h for h in herbs if h in origins[cid]), "in_network": bool(count)})  # 零命中者明确标记不入图。
    for row in ranking:  # 同分同名次，不用编号打破科学并列。
        row["main_rank"] = 1 + sum(other["intersection_count"] > row["intersection_count"] for other in ranking) if row["in_network"] else None  # 主排序采用竞赛名次。
        row["degree_rank"] = 1 + sum(other["mixed_degree"] > row["mixed_degree"] for other in ranking) if row["in_network"] else None  # 参考排序单独计算。
    ranking.sort(key=lambda row: (-row["intersection_count"], row["compound_id"]))  # 编号仅稳定展示顺序。
    eligible = [row for row in ranking if row["in_network"]]  # 不用零命中者凑足五个。
    cutoff = eligible[min(5, len(eligible)) - 1]["intersection_count"] if eligible else None  # 固定主候选上限。
    above = [row["compound_id"] for row in eligible if row["intersection_count"] > cutoff] if eligible else []  # 记录边界以上建议。
    boundary = [row["compound_id"] for row in eligible if row["intersection_count"] == cutoff] if eligible else []  # 完整保留边界并列池。
    sets = [{"target_id": target, "in_formula": target in formula, "in_disease": target in disease, "in_intersection": target in intersection, "namespace": namespace} for target in sorted(formula | disease)]  # 三集合由同一张成员表表达。
    return {"sets": sets, "ranking": ranking, "formula_evidence": evidence, "disease_evidence": [dict(row) for row in disease_targets], "above_cutoff": above, "boundary": boundary, "boundary_slots": min(5, len(eligible)) - len(above), "requires_tie_review": len(above) + len(boundary) > 5, "counts": {"formula": len(formula), "disease": len(disease), "intersection": len(intersection), "formula_only": len(formula - disease), "disease_only": len(disease - formula)}}  # 建议不是人工批准结果。


def expanded_pool(result, herbs):  # 计算人工可扩展的截断并列及未覆盖药味代表池。
    rows = {row["compound_id"]: row for row in result["ranking"]}  # 仅使用本次A03排名事实。
    primary = list(dict.fromkeys(result["above_cutoff"] + result["boundary"]))  # 完整保留前五截断处并列。
    covered = {herb for cid in primary for herb in rows[cid]["herbs"].split("、")}  # 先看并列全部纳入后的药味覆盖。
    representatives = []  # 未覆盖药味仅提出本味排名最高者。
    for herb in herbs:  # 逐味计算，药味增加时仍可复用。
        if herb in covered:  # 已被主排序候选覆盖时不再扩张。
            continue  # 保持候选预算受控。
        candidates = [row for row in rows.values() if row["in_network"] and herb in row["herbs"].split("、")]  # 只看该味有交集靶点的成分。
        best = max((row["intersection_count"] for row in candidates), default=0)  # 无合格成分时不虚构代表。
        representatives.extend(row["compound_id"] for row in candidates if row["intersection_count"] == best and best > 0)  # 并列代表完整保留。
    return {"primary": primary, "representatives": list(dict.fromkeys(representatives)), "allowed": list(dict.fromkeys(primary + representatives))}  # 稳定顺序便于复算。


def coverage(result, selected, herbs, reviewer, reason, allow_expansion=False, manual_supplements=None):  # 主候选人工确认后生成药味补充建议。
    require(bool(reviewer.strip()) and bool(reason.strip()), "候选选择须填写复核人及理由")  # 选择理由由调用方归档。
    require(len(selected) == len(set(selected)), "主候选不可重复")  # 重复编号不能扩大实际名单。
    rows = {row["compound_id"]: row for row in result["ranking"]}  # 从本次计算结果取候选身份。
    require(all(cid in rows and rows[cid]["in_network"] for cid in selected), "主候选必须来自有交集靶点的成分")  # 不放宽基础条件。
    pool = expanded_pool(result, herbs)  # 扩展名额只能来自可复算的并列和药味代表池。
    manual = manual_supplements or {}  # 只有显式传入的本次人工补充才能放行。
    require(isinstance(manual, dict) and set(manual) <= set(selected) and all(isinstance(value, str) and value.strip() for value in manual.values()), "人工补充必须在本次名单内且逐项说明理由")  # 不允许空理由或未选成分。
    require(not manual or allow_expansion, "人工补充须使用明确的新版扩展策略")  # 默认预算不自动变化。
    if len(selected) > 5:  # 超过默认预算必须走人工扩展规则。
        require(allow_expansion, "超过五个候选须明确采用并列及药味代表扩展规则")  # 不能凭数量自动放宽。
        require(set(selected).issubset(set(pool["allowed"]) | set(manual)), "扩展候选只能来自已允许的并列、药味代表或逐项明确人工补充")  # 未指定对象仍不能追加。
        require(set(result["above_cutoff"]).issubset(selected), "扩展选择须保留边界以上主候选")  # 扩展不能反向删除明确前列者。
    else:  # 五个以内继续兼容既有人工替换规则。
        require(len(selected) <= 5, "主候选最多五个")  # 明确保留旧边界。
    covered = {herb for cid in selected for herb in rows[cid]["herbs"].split("、")}  # 共享成分覆盖多个药味。
    supplements, status = {}, []  # 补充成分去重，药味状态分别保留。
    for herb in herbs:  # 药味较多时仍逐味可检索。
        candidates = [row for row in rows.values() if row["in_network"] and herb in row["herbs"].split("、")]  # 限于该味药有效成分。
        best = max((row["intersection_count"] for row in candidates), default=0)  # 无合格者不虚构代表。
        proposed = [row for row in candidates if row["intersection_count"] == best] if herb not in covered else []  # 已覆盖药味不追加。
        status.append({"herb": herb, "covered": herb in covered, "supplement_count": len(proposed), "status": "已覆盖" if herb in covered else ("补充候选待评估" if proposed else "无合格补充候选")})  # 与空结果区分。
        for row in proposed:  # 并列候选全列出等待复核。
            item = supplements.setdefault(row["compound_id"], {"compound_id": row["compound_id"], "name": row["name"], "herbs": row["herbs"], "intersection_count": row["intersection_count"], "proposed_for": [], "automatic_docking": False})  # 共享身份不重复增加预算。
            item["proposed_for"].append(herb)  # 保留每味药提出的原因。
    for row in supplements.values():  # 转为项目平表可存字段。
        row["proposed_for"] = "、".join(row["proposed_for"])  # 不丢失药味来源。
    roles = {}  # 对超过前五的纳入原因逐项留痕。
    for cid in selected:  # 每个正式候选只有一个主要来源角色。
        roles[cid] = "人工补充研究候选" if cid in manual else ("边界以上主候选" if cid in result["above_cutoff"] else ("截断处并列纳入" if cid in result["boundary"] else ("药味代表性补充纳入" if cid in pool["representatives"] else "人工替换候选")))  # 新增角色不冒充截断并列。
    return {"selected": list(selected), "reviewer": reviewer, "reason": reason, "coverage": status, "supplements": list(supplements.values()), "roles": roles, "expanded_pool": pool}  # 仅生成可保存内容，不触发对接。

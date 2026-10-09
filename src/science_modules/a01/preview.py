"""A01 三库候选计算；来源和处方由调用方传入，不复用病例审批。"""
import json
from contracts import require
from .multisource import batman_known, deduplicate

# 按明确路径读取已由调用方核验指纹的来源，失败不回退空结果。
def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

# 复用原三库身份与已有关系计算；标准化TCMSP和HGNC必须属于同一研究依据。
def build_candidate(raw, tc, hr, br, mapper, normalized_tcmsp, identity_summary, herbs, source_coverage, batman_raw=None):
    require(identity_summary.get("mapping_snapshot") == mapper.digest, "TCMSP与新增来源HGNC快照不一致")
    require(identity_summary.get("mapping_rule") == mapper.rule, "TCMSP与新增来源HGNC规则不一致")
    require(identity_summary.get("identity_evidence_snapshot") == (mapper.supplement.digest if mapper.supplement else ""), "TCMSP与新增来源补充证据不一致")
    require(bool(herbs) and len(set(herbs)) == len(herbs), "当前药味清单缺失或重复")
    require(set(source_coverage) == {"TCMSP", "HERB", "BATMAN"} and all(set(values) == set(herbs) for values in source_coverage.values()), "三库导入清单未完整覆盖当前处方")
    require(all(r["herb"] in herbs for r in tc + hr + br), "来源记录包含当前处方以外的药味")
    components, memberships, source_rows, conflicts = deduplicate(tc + hr + br, herbs)  # 按完整结构键保守去重。
    require(not conflicts, "同结构键分子式冲突，须先复核")  # 不把身份冲突带入自动流程。
    lookup = {(r["source"], r["source_id"]): r["compound_id"] for r in source_rows}  # 原编号到主成分稳定映射。
    normalized, issues, evidence_rows = [], [], []  # 标准关系与异常分别保存。
    for edge in normalized_tcmsp:  # 原TCMSP已复核人类关系不改写。
        normalized.append(dict(edge, compound_id=lookup[("TCMSP", edge["compound_id"])], database="TCMSP"))  # 去重后的编号仍能回到原记录。
    browse = read(raw / "HERB_target_browse_page001.json")  # 固定官方靶点命名表。
    require(len(browse["browse_data"]) - 1 == browse["total_num"], "HERB靶点浏览表不完整")  # 不将分页截断冒充全表。
    target_names = {row[0]["title"]: row[1] for row in browse["browse_data"][1:]}  # HBTAR编号不冒充HGNC编号。
    def add(source, cid, gene, reference, raw_target=""):  # 仅标准化已有关系，不预测新靶点。
        mapped = mapper.resolve(gene)  # 只接受现有唯一人类基因映射。
        row = {"database": source, "raw_compound_id": cid, "raw_symbol": gene, "raw_target_id": raw_target, "source_ref": reference, "identity_status": mapped["status"]}  # 保留每条关系来源。
        evidence_rows.append(row)  # 成功与失败均有明细。
        if mapped["status"] != "matched":  # 不能查实的基因不进入交集。
            issues.append(dict(row, candidate_ids=mapped.get("candidate_ids", [])))  # 新例外待用户审核，不代签不采用。
            return  # 不伪造标准身份。
        normalized.append({"compound_id": lookup[(source, cid)], "target_id": mapped["target_id"], "symbol": mapped["symbol"], "species": 9606, "source_ref": reference, "database": source})  # 仅指人类基因身份，不声称原实验均来自人体。
    for cid in sorted({r["source_id"] for r in hr}):  # 同一HERB成分仅解析一次完整详情。
        detail_path = raw / "HERB_existing_details" / (cid + ".json")  # 每条请求有完整原文。
        data = read(detail_path)  # 采集失败不写成零关系。
        require(len(data.get("summary", [])) == 2 and data["summary"][1][0] == cid, "HERB详情成分身份不一致")
        require(data.get("ingredient_target") and data["ingredient_target"][0] == ["Target id", "Target name", "Database sources"], "HERB已有关系表缺失或格式改变")
        for line, row in enumerate(data["ingredient_target"][1:], 2):  # 表达实验及疾病推断表不参与。
            tid, gene = row[0]["title"], row[1]  # 提取来源HBTAR与原始名称。
            require(tid in target_names, "HERB关系靶点未对应官方命名表")  # 不猜靶点编号。
            add("HERB", cid, target_names[tid], ("raw/" + detail_path.relative_to(raw).as_posix()) + ":ingredient_target:" + str(line), tid)  # 使用官方现行名字核对HGNC。
    bnames = {r["source_id"]: r["name"] for r in br}  # 核对官方成分总表与已有关系表名称一致。
    for line, row in enumerate(batman_known((batman_raw or raw) / "BATMAN_known_browse_by_ingredients.txt.gz"), 2):  # 明确不读取预测表。
        cid = row["PubChem_CID"]  # 原始数字身份完整保留。
        if cid not in bnames:  # 其他药味成分不纳入。
            continue  # 不把全库靶点作为全方靶点。
        require(row["IUPAC_name"] == bnames[cid], "BATMAN同编号成分名称冲突")  # 冲突不能任取名称。
        for gene in row["known_target_proteins"].split("|"):  # 每条已有基因关系保存来源行。
            add("BATMAN", cid, gene, "raw/BATMAN_known_browse_by_ingredients.txt.gz:" + str(line))  # 不设置新增预测阈值。
    unique = {}  # 相同成分到相同标准基因只计一条。
    for edge in normalized:  # 证据仍在独立明细中完整留存。
        key = (edge["compound_id"], edge["target_id"])  # 不将重复数据库记录算成额外靶点。
        unique.setdefault(key, {k: edge[k] for k in ("compound_id", "target_id", "symbol", "species")})  # 交集接口保持原字段。
        unique[key].setdefault("source_refs", set()).add(edge["source_ref"])  # 合并证据而非删掉来源。
    edges = []  # 稳定输出便于复算。
    for key in sorted(unique):  # 固定排序与编号。
        edge = unique[key]  # 汇总每条标准关系。
        edge["source_ref"] = "|".join(sorted(edge.pop("source_refs")))  # 保留所有关联来源。
        edges.append(edge)  # 交集计数不受多库重复影响。
    summary = {key: identity_summary[key] for key in ("analysis_purpose", "namespace", "mapping_snapshot", "mapping_rule", "identity_evidence_snapshot")}  # 仅继承固定身份依据，不继承旧37成分与210靶点计数。
    summary.update(candidate_only=True, component_source_profile="A01.multisource.candidate.4", target_policy="existing_relations_only_new_sources", handoff_blocked=bool(issues), **{"候选成分分组数": len(components), "结构键分组数": sum(bool(r["inchikey"]) for r in components), "结构待核分组数": sum(not r["inchikey"] for r in components), "标准化基因数": len({r["target_id"] for r in edges}), "去重成分—人类基因关系数": len(edges), "新增待核基因关系数": len(issues), "资料阶段": "三库候选，须按当前研究独立复核后发布"})  # 待审核异常不能继承旧批准。
    candidate = {"run_id": "candidate_A01_multisource_v4", "summary": summary, "tables": {"components": components, "herb_components": memberships, "herb_summary": [{"herb": h} for h in herbs], "normalized_compound_targets": edges}}  # 候选记录不写研究索引。
    return {"result": candidate, "source_records": source_rows,
            "new_relation_evidence": evidence_rows, "identity_issues": issues}

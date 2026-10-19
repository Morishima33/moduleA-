"""KEGG.disease_screening.1按官方分类生成候选，不替用户排除、不改变富集统计。"""
from copy import deepcopy
from pathlib import Path
import json
import re
import unicodedata
from .display import english

VERSION = "KEGG.disease_screening.1"
CATALOG = Path(__file__).with_name("kegg_classification.json")
CATEGORY_ZH = {"Human Diseases": "人类疾病", "Metabolism": "代谢", "Genetic Information Processing": "遗传信息处理", "Environmental Information Processing": "环境信息处理", "Cellular Processes": "细胞过程", "Organismal Systems": "生物体系统", "Drug Development": "药物开发"}
DISEASE_ZH = {"Cancer: overview": "癌症总览", "Cancer: specific types": "具体癌种", "Infectious disease: viral": "病毒感染性疾病", "Infectious disease: bacterial": "细菌感染性疾病", "Infectious disease: parasitic": "寄生虫感染性疾病", "Immune disease": "免疫疾病", "Neurodegenerative disease": "神经退行性疾病", "Substance dependence": "物质依赖", "Cardiovascular disease": "心血管疾病", "Endocrine and metabolic disease": "内分泌与代谢疾病", "Drug resistance: antimicrobial": "抗微生物药物耐药", "Drug resistance: antineoplastic": "抗肿瘤药物耐药"}


# 仅做大小写、标点及空白归一；不做模糊匹配、亚型扩展或器官相同推断。
def normalize(value):
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", str(value)).casefold()))


# 只采用当前A00已核验的MeSH名称/同义词；缺证据时疾病类条目保持待判断。
def disease_identity(intake):
    mesh = intake.get("mesh_verification") or {}
    valid = bool(mesh.get("status") == "verified" and mesh.get("mesh_id") == intake.get("mesh_id") and intake.get("mesh_id"))
    terms = [mesh.get("preferred_term", ""), intake.get("mesh_term", ""), *(mesh.get("entry_terms") or [])] if valid else []
    return {"mesh_id": intake.get("mesh_id"), "verified": valid, "names": sorted({normalize(t) for t in terms if normalize(t)})}


# 对完整显著表按稳定编号查分类；癌症与其他疾病机制不再享有例外。
def assess(rows, catalog, identity):
    result = {}
    for row in rows:
        tid = row["ID"]
        classes = catalog.get("pathways", {}).get(tid[3:]) if re.fullmatch(r"hsa\d{5}", tid) else None
        label = english(row)
        status, reason = "uncertain", "官方分类缺失，需人工判断，未自动列为排除。"
        official = classes[0]["name"] if classes else ""
        if classes:
            names = {normalize(label), normalize(official)}
            aliases = set(identity["names"])
            disease = any(c["category"] == "Human Diseases" for c in classes)
            if not disease:
                status, reason = "retain", "官方分类为通用机制或生理过程，保留为候选机制，不等于已证实与本病有关。"
            elif not identity["verified"]:
                reason = "本研究缺少已核验疾病身份，不能判断是否为本病，需人工核对。"
            elif names & aliases:
                status, reason = "retain", "与本研究已核验MeSH本病名称或同义词精确匹配，保留。"
            elif any(len(alias.split()) > 1 and (" " + alias + " ") in (" " + name + " ") for alias in aliases for name in names):
                reason = "名称包含本病但不是直接同名条目，可能涉及亚型或并发症，需人工判断。"
            else:
                status, reason = "exclude", "官方归入人类疾病，且不是本研究本病直接条目；按已确认报告范围列为拟排除，含癌症机制及耐药，不表示生物学上完全无关。"
        classification = "；".join(dict.fromkeys(CATEGORY_ZH.get(c["category"], c["category"]) + " / " + DISEASE_ZH.get(c["subcategory"], c["subcategory"]) for c in classes)) if classes else "官方分类待补"
        result[tid] = {"classification_status": status, "classification_zh": classification, "official_name": official, "reason_zh": reason, "evidence_url": "https://www.kegg.jp/pathway/" + tid}
    return result


# 官方分类及本病证据随展示来源归档，未来更新代码资料不会改变历史候选。
def snapshot(rows, intake):
    catalog = json.loads(CATALOG.read_text("utf-8"))
    identity = disease_identity(intake)
    return {"version": VERSION, "catalog": catalog, "identity": identity, "assessments": assess(rows, catalog, identity)}


# 只为明确其他疾病建立建议；待判断项单列，不能自动转成排除。
def proposals(screen):
    return {tid: deepcopy(row) for tid, row in screen["assessments"].items() if row["classification_status"] == "exclude"}

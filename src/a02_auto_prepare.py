# 本文件在A00通过后准备可公开自动获取的A02来源，不替代三库上传或人工范围复核。
import json  # 读取已归档官方快照以核验命中数。
from storage import now  # 记录每个自动来源的失败时间。
from contracts import require  # 所有歧义均明确停止。
from disease import run_disease  # 通过统一A02入口归档来源与结果。
from disease_io import fetch_otp  # 获取本病直接关联，不设置评分阈值。
from mesh_identity import validate_mesh_identity  # 只接受A00已核验的MeSH身份。
from otp_search import search_disease  # 先解析当前Open Targets疾病编号。
from ttd_source import fetch_ttd, make_source, parse_snapshot  # TTD下载一次后逐个核验官方词。
from pharmgkb_source import fetch_pharmgkb  # 查询ClinPGx唯一精确疾病实体及直接Gene关系。
from intake_sources import COMPATIBLE_PROFILES as PREUPLOAD_PROFILES, SOURCE_PROFILE, sources_for_a02  # 读取A00预上传且仍有效的来源。


def _normal(value):  # 数据库名称比较只统一首尾空白与大小写。
    return str(value or "").strip().casefold()  # 不删除标点后冒充精确匹配。


def _terms(a00_summary):  # 从已核对MeSH身份取得唯一有序官方词。
    identity = validate_mesh_identity(a00_summary)  # 未通过NLM核验的自由文本不自动查询。
    return list(dict.fromkeys([identity["preferred_term"]] + identity.get("entry_terms", [])))  # 首选词在前，同义词去重。

def _otp_source(a00_summary):  # 独立获取Open Targets，失败不影响其他来源。
    terms = _terms(a00_summary)  # 只使用NLM归档词。
    official = {_normal(term) for term in terms}  # 只允许官方词精确命中。
    candidates = []  # Open Targets搜索对MeSH倒装词序未必返回本病，需逐个官方词查找。
    for term in terms:  # 只搜索NLM归档的首选词和Entry Term。
        candidates.extend(search_disease(term))  # 不添加程序自拟疾病词。
    exact_by_id = {row["id"]: row for row in candidates if _normal(row.get("name")) in official}  # 亚型和近似疾病不自动纳入。
    exact = list(exact_by_id.values())  # 同一实体被多个官方词命中时只计一次。
    require(len(exact) == 1, "Open Targets未找到唯一的本病精确条目；请人工核对疾病编号")  # 0项或多项都不能猜。
    otp = fetch_otp(exact[0]["id"])  # 完整直接关联取得后才返回来源。
    otp_snapshot = json.loads(otp["data"].decode("utf-8"))  # 再核对接口实际返回身份。
    require(_normal(otp_snapshot["disease_name"]) in official, "Open Targets返回疾病名称与A00官方词不一致")  # 搜索结果和正式查询双重核验。
    return otp, {"otp_id": exact[0]["id"], "otp_name": otp_snapshot["disease_name"], "otp_records": otp_snapshot["total"]}  # 返回来源和诊断。

def _ttd_source(a00_summary):  # 独立获取TTD完整文件并核对官方词。
    terms = _terms(a00_summary)  # 不添加程序自拟词。
    ttd = fetch_ttd(terms[0])  # 两份官方文件只下载一次。
    snapshot = json.loads(ttd["data"].decode("utf-8"))  # 保留下载日期、版本和文件指纹。
    chosen, counts = ttd, {}  # 默认保存MeSH首选词的真实零命中结果。
    for term in terms:  # 首选词无命中时再检查NLM官方同义词。
        candidate = make_source(snapshot["files"], term)  # 复用同一批TTD原始字节，避免版本漂移。
        count = len(parse_snapshot(json.loads(candidate["data"].decode("utf-8")))[0])  # 精确名称匹配数量。
        counts[term] = count  # 供页面和治理记录解释选择依据。
        if count:  # 第一个有精确命中的官方词成为实际检索词。
            chosen = candidate  # 不尝试模糊词或疾病亚型。
            break  # 首选词优先于同义词。
    return chosen, {"ttd_query": chosen["query"], "ttd_exact_matches": counts.get(chosen["query"], 0), "ttd_term_checks": counts}  # 返回来源和诊断。

def public_sources(a00_summary):  # 历史入口继续要求OTP与TTD整体成功。
    otp, otp_diagnostic = _otp_source(a00_summary)  # 保持原失败语义。
    ttd, ttd_diagnostic = _ttd_source(a00_summary)  # 保持旧研究不发布半成品。
    return [otp, ttd], otp_diagnostic | ttd_diagnostic  # 兼容既有测试和历史行为。

def _failure(database, error):  # 将单库失败保存为可追溯状态，而不是伪零结果。
    message = str(error).strip() or type(error).__name__  # 页面显示业务错误，不保存堆栈。
    snapshot = {"database": database, "status": "query_failed", "attempted_at": now(), "error": message, "trace": getattr(error, "source_trace", {})}  # 失败原响应仅归档，不发布候选。
    return {"database": database, "format": "source_failure", "query": "按A00已核对MeSH词自动查询", "retrieved_at": snapshot["attempted_at"], "version": "查询未完成，无数据库结果版本", "source_url": {"OTP": "https://api.platform.opentargets.org/", "TTD": "https://ttd.idrblab.cn/", "PharmGKB": "https://api.clinpgx.org/v1"}[database], "name": database.lower() + "_failure.json", "encoding": "utf-8-sig", "source_status": "query_failed", "data": json.dumps(snapshot, ensure_ascii=False).encode("utf-8")}  # 统一进入A02来源清单。

def new_research_sources(workflow, manifest, a00):  # 新流程独立采集三库并合并A00预上传资料。
    updates = sources_for_a02(workflow, manifest)  # GeneCards、OMIM及可能的备用来源。
    existing = {item["database"] for item in updates}  # 手动备用来源优先，避免重复联网。
    diagnostic = {"staged_databases": sorted(existing), "automatic": {}}  # 页面可回查每库结果。
    jobs = [("OTP", lambda: _otp_source(a00)), ("TTD", lambda: _ttd_source(a00)), ("PharmGKB", lambda: (fetch_pharmgkb(_terms(a00)), {"terms": _terms(a00)}))]  # 三个来源彼此独立。
    for database, job in jobs:  # 单库失败不吞掉其他成功来源。
        if database in existing:  # TTD或PharmGKB已提供备用文件时不联网替换。
            diagnostic["automatic"][database] = {"status": "使用A00预上传备用来源"}  # 说明实际选择。
            continue
        try:  # 成功和真实零结果都由来源适配器返回。
            source, detail = job()  # 取得完整来源后才加入当前A02。
            updates.append(source)  # 原始响应由统一入口归档。
            diagnostic["automatic"][database] = {"status": "完成", "detail": detail}  # 不把零结果写成失败。
        except Exception as error:  # 单库失败形成显式阻断状态。
            updates.append(_failure(database, error))  # 不产生候选基因。
            diagnostic["automatic"][database] = {"status": "查询失败", "error": str(error)}  # 提供重试依据。
    return updates, diagnostic  # GeneCards或OMIM缺失由source_summary显示。


def prepare(workflow, study_id):  # 在当前研究中生成候选A02版本，仍保持待人工复核。
    manifest = workflow.load(study_id)  # 所有版本绑定当前研究。
    require(not manifest.get("trashed") and manifest["current"].get("A00"), "研究不可用或缺少A00")  # 回收站不联网更新。
    require(workflow.approved(manifest, manifest["current"]["A00"]), "请先通过A00研究登记")  # 未批准身份不自动获取。
    require(not manifest["current"].get("A02"), "A02已有当前版本；请从网页明确更新来源")  # 自动入口不覆盖人工上传版本。
    a00 = workflow.result(manifest, manifest["current"]["A00"])["summary"]  # 只读取当前批准登记。
    modern = manifest.get("workflow_profile") in PREUPLOAD_PROFILES  # 新研究使用三库自动及预上传资料。
    updates, diagnostic = new_research_sources(workflow, manifest, a00) if modern else public_sources(a00)  # 历史研究保持原整体成功语义。
    reason = "A00通过后生成A02：接入预上传GeneCards/OMIM并自动获取TTD、PharmGKB、Open Targets" if modern else "A00通过后自动准备A02公开来源：获取Open Targets本病直接关联与TTD官方快照；GeneCards、OMIM、DisGeNET保持待上传"  # 运行历史说明实际方案。
    profile = SOURCE_PROFILE if manifest.get("workflow_profile") == "A00.preupload.2" else ("A02.source_profile.2" if modern else None)  # 历史预上传研究保持原来源契约。
    result = run_disease(workflow, study_id, manifest["current"]["A00"], "", updates, reason, profile_version=profile)  # 使用统一原始资料归档。
    return {"run_id": result["run_id"], "diagnostic": diagnostic}  # A02仍须补齐三库并人工复核。

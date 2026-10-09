# 官方身份查询采集器；只保存证据，不自动批准基因或研究。
import datetime  # 记录实际查询时间。
import hashlib  # 记录原响应指纹。
import json  # 发送结构化查询并留存响应。
import urllib.request  # 只访问指定官方接口。
import urllib.parse  # 安全编码原始编号。
from contracts import require  # 避免覆盖既有快照。

def request(url, payload=None):  # 单次有限时长查询，失败与无结果分开。
    record = {"url": url, "payload": payload, "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}  # 记录原请求。
    try:  # 网络失败也形成明确状态。
        body = None if payload is None else json.dumps(payload).encode("utf-8")  # 不拼接查询语法。
        query = urllib.request.Request(url, data=body, headers={"Content-Type":"application/json", "Accept":"application/json"})  # 官方JSON接口。
        with urllib.request.urlopen(query, timeout=35) as response:  # 超时不会当作生物学无记录。
            raw = response.read()  # 保存实际响应字节对应文本。
            record.update(status="ok", http_status=response.status, response_text=raw.decode("utf-8"), response_sha256=hashlib.sha256(raw).hexdigest())  # 原文和指纹。
    except Exception as error:  # 网络、解析前错误独立记录。
        record.update(status="query_failed", error=type(error).__name__ + ": " + str(error))  # 不返回伪造空基因集合。
    return record  # 后续只读取有成功证据的条目。

def collect(path, ensembl_ids, accessions, previous=None, xref_ids=()):  # 可供后续方剂研究调用的采集入口。
    require(not path.exists(), "查询快照已存在，不能覆盖；请使用明确的新版本文件")  # 旧查询不可改写。
    previous = previous or {}  # 扩展时复用已保存请求，不覆盖旧快照。
    records = list(previous.get("queries", [])) + [request("https://rest.ensembl.org/info/data?content-type=application/json")]  # 记录服务数据版本。
    done_lookup = {x for q in previous.get("queries", []) if q["status"] == "ok" and q["url"].endswith("/lookup/id") for x in (q.get("payload") or {}).get("ids", [])}  # 失败请求仍可重试。
    done_archive = {x for q in previous.get("queries", []) if q["status"] == "ok" and q["url"].endswith("/archive/id") for x in (q.get("payload") or {}).get("id", [])}  # 两类证据均成功才复用。
    ids = sorted(set(ensembl_ids) - (done_lookup & done_archive))  # 重复编号只查询一次。
    for start in range(0, len(ids), 1000):  # 不超过官方批量上限。
        batch = ids[start:start + 1000]  # 固定批次内容。
        records.append(request("https://rest.ensembl.org/lookup/id", {"ids":batch}))  # 查当前身份和物种。
        records.append(request("https://rest.ensembl.org/archive/id", {"id":batch}))  # 查历史替换关系。
    for identifier in sorted(set(xref_ids)):  # 仅对需要跨库消歧的编号取官方HGNC链接。
        records.append(request("https://rest.ensembl.org/xrefs/id/" + urllib.parse.quote(identifier, safe="") + "?content-type=application/json"))  # 不凭显示名称造映射。
    completed_accessions = {q["url"].rsplit("/", 1)[1].removesuffix(".json") for q in previous.get("queries", []) if q["status"] == "ok" and "rest.uniprot.org/uniprotkb/" in q["url"]}  # 失败不永久缓存为无记录。
    for accession in sorted(set(accessions) - completed_accessions):  # 同一蛋白编号复用查询。
        url = "https://rest.uniprot.org/uniprotkb/" + urllib.parse.quote(accession, safe="") + ".json"  # 不靠模糊名称检索。
        records.append(request(url))  # 失活和拆分也按官方原文保存。
    payload = {"schema_version":"identity_queries.1", "ensembl_ids":sorted(set(ids) | set(previous.get("ensembl_ids", []))), "accessions":sorted(set(accessions) | set(previous.get("accessions", []))), "queries":records}  # 不混入推测性映射。
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")  # 可读查询记录。
    with path.open("xb") as stream:  # 不覆盖已有同名记录。
        stream.write(raw)  # 保存完整原响应。
    meta = {"filename":path.name, "bytes":len(raw), "sha256":hashlib.sha256(raw).hexdigest(), "purpose":"官方身份查询原文；失败不等于查无记录"}  # 供发布校验。
    with path.with_name(path.stem + "_manifest.json").open("x", encoding="utf-8") as stream:  # 固定旁附来源清单。
        json.dump(meta, stream, ensure_ascii=False, indent=2)  # 不覆盖历史清单。
    return payload  # 调用者可检查失败并明确重试。

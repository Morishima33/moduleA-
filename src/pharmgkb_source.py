# ClinPGx（原PharmGKB）疾病—基因来源适配器；只接受本病唯一精确实体。
import json  # 完整保存查询请求和官方响应。
import time  # 控制官方接口请求频率。
import urllib.error  # 区分无精确实体与接口故障。
import urllib.parse  # 安全编码查询词。
import urllib.request  # 仅访问固定的ClinPGx官方接口。
from contracts import ContractError, require  # 使用项目统一错误类型。
from storage import now  # 保存可追溯查询时间。

BASE_URL = "https://api.clinpgx.org/v1"  # 固定官方生产接口，页面不能替换。
DISEASE_ENDPOINT = BASE_URL + "/data/disease/"  # 按疾病名称查找实体。
GENE_ENDPOINT = BASE_URL + "/report/connectedObjects/{disease_id}/gene"  # 获取疾病直接连接的基因。
RATE_SECONDS = 0.5  # 官方限制每秒不超过两次请求。

def _request_json(url, opener=urllib.request.urlopen):  # 一次受控读取官方JSON。
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ModuleA/1.0"})  # 不携带用户凭据。
    try:  # 404表示没有该精确名称，其余失败不能发布部分数据。
        with opener(request, timeout=20) as response:  # 网络等待有明确上限。
            raw = response.read(8 * 1024 * 1024 + 1)  # 防止异常大响应占满内存。
        require(len(raw) <= 8 * 1024 * 1024, "ClinPGx响应异常过大，本次未发布结果")  # 不截断后继续。
        return response.status, json.loads(raw)  # 原响应进入来源快照。
    except urllib.error.HTTPError as error:  # 404与接口错误语义不同。
        if error.code == 404:  # 无实体是有效零结果。
            return 404, None  # 调用方继续核对其他官方词。
        raise ContractError("ClinPGx查询失败，本次未发布部分数据") from error  # 保留旧A02。
    except (OSError, ValueError) as error:  # 网络或JSON失败都不是零结果。
        raise ContractError("ClinPGx查询失败，本次未发布部分数据") from error  # 提示稍后重试或上传。

def fetch_pharmgkb(terms, opener=urllib.request.urlopen, sleeper=time.sleep):  # 依次核对MeSH首选词和Entry Term。
    cleaned = []  # 保留原顺序并去除完全重复词。
    for term in terms:  # 只查询A00已经核验的官方词。
        value = str(term).strip()  # 空词不发送请求。
        if value and value.casefold() not in {item.casefold() for item in cleaned}:  # 大小写不形成新查询。
            cleaned.append(value)  # 记录实际查询词。
    require(bool(cleaned), "缺少已核对的MeSH首选词或Entry Term")  # 不由简称猜疾病。
    requests, exact = [], {}  # 保存每次响应和唯一精确实体。
    for index, term in enumerate(cleaned):  # 顺序查询方便复算。
        if index:  # 首次请求前无需等待。
            sleeper(RATE_SECONDS)  # 遵守每秒不超过两次。
        url = DISEASE_ENDPOINT + "?" + urllib.parse.urlencode({"name": term})  # 查询参数安全编码。
        status, payload = _request_json(url, opener)  # 失败时整体退出。
        requests.append({"term": term, "url": url, "status": status, "response": payload})  # 404也完整留痕。
        candidates = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []  # 兼容官方列表包装。
        for row in candidates:  # 只有名称完全等于当前官方词才算精确实体。
            if str(row.get("name", "")).strip().casefold() == term.casefold() and row.get("id"):
                exact[str(row["id"])] = row  # 同一实体跨Entry Term只保留一份。
    require(len(exact) <= 1, "ClinPGx返回多个精确疾病实体，须人工核对后再获取")  # 不任选一个。
    genes, disease = [], next(iter(exact.values()), None)  # 无精确实体是合格零结果。
    if disease:  # 只有唯一精确实体才读取直接连接基因。
        sleeper(RATE_SECONDS)  # 与上一请求保持官方频率。
        url = GENE_ENDPOINT.format(disease_id=urllib.parse.quote(str(disease["id"]), safe=""))  # 稳定ID进入固定路径。
        status, payload = _request_json(url, opener)  # 基因接口失败时不发布疾病半成品。
        require(status == 200 and isinstance(payload, list), "ClinPGx基因关系响应不完整")  # 失败不是零结果。
        requests.append({"term": "direct genes", "url": url, "status": status, "response": payload})  # 直接关系完整留痕。
        for row in payload:  # 不经药物或变异间接扩展。
            obj = row.get("connectedObject", {})  # 官方连接对象。
            if obj.get("objCls") == "Gene" and obj.get("id"):  # 只收直接Gene对象。
                genes.append({"id": obj["id"], "symbol": obj.get("symbol", ""), "name": obj.get("name", ""), "connectionTypes": row.get("connectionTypes", [])})  # 保存官方关系类型。
    snapshot = {"api": BASE_URL, "queried_at": now(), "official_terms": cleaned, "exact_disease": disease, "records": genes, "requests": requests, "status": "queried_zero_exact" if disease is None else "queried_exact"}  # 零结果与失败明确区分。
    data = json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode("utf-8")  # 作为原始来源归档。
    return {"database": "PharmGKB", "format": "pharmgkb_api", "query": " | ".join(cleaned), "retrieved_at": snapshot["queried_at"], "version": "ClinPGx API v1；以响应快照固定", "source_url": DISEASE_ENDPOINT, "name": "pharmgkb_exact_disease.json", "encoding": "utf-8-sig", "data": data, "source_status": snapshot["status"]}  # 进入统一A02入口。

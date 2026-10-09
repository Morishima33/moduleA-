# TTD官方文件读取与候选提取；不制定评分或正式纳入规则。
import hashlib  # 校验每份完整下载的原始字节。
import json  # 将两份文件和请求元信息封装归档。
import re  # 严格检查文件头与靶点编号。
import urllib.request  # 使用官方公开下载地址。
from concurrent.futures import ThreadPoolExecutor  # 两份独立资料可并行下载。
from contracts import require, ContractError  # 统一失败说明。
from storage import now  # 保存获取时间。

FILES = {"targets": "P1-01-TTD_target_download.txt", "diseases": "P1-06-Target_disease.txt"}  # 使用靶点身份与治疗疾病映射，未混入其他关联产品。
BASE = "https://ttd.idrblab.cn/files/download/"  # 固定官方来源。

def fetch_file(role):  # 每份下载完整保存，不读取Kimi资料。
    url = BASE + FILES[role]  # 不接受任意地址。
    with urllib.request.urlopen(url, timeout=25) as response:  # 有限等待。
        raw = response.read(16 * 1024 * 1024 + 1)  # 超限明确失败。
    require(len(raw) <= 16 * 1024 * 1024, "TTD文件超出当前容量，未截断发布")  # 不把片段当全量。
    text = raw.decode("utf-8", errors="strict")  # 原编码异常不能忽略。
    require("TTD - Therapeutic Targets Database" in text[:500], "TTD返回内容不是预期原始文件")  # 登录或错误页不是数据。
    return role, {"url": url, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "retrieved_at": now(), "text": text}  # 原字节可由UTF8无损恢复。

def make_source(files, query):  # 已下载文件与联网获取共用封装接口。
    snapshot = {"version": "TTD.snapshot.1", "query": query, "files": files}  # 逐份保存日期及原文。
    entries, versions = parse_snapshot(snapshot)  # 先检查再交给A02。
    data = json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode("utf-8")  # 完整原文进入本研究来源文件。
    require(len(data) <= 16 * 1024 * 1024, "TTD完整快照超出当前A02容量")  # 不只保存筛选后的片段。
    return {"database": "TTD", "format": "ttd_snapshot", "query": query, "retrieved_at": max(item["retrieved_at"] for item in files.values()), "version": "；".join(versions), "source_url": BASE + FILES["diseases"], "name": "ttd_snapshot.json", "encoding": "utf-8-sig", "data": data}  # 不自动批准疾病范围。

def fetch_ttd(query):  # 网页运行时重新联网获取两份原始数据。
    require(isinstance(query, str) and 0 < len(query.strip()) <= 2000, "请填写明确的TTD疾病英文名称")  # 联网前检查检索输入。
    try:  # 网络失败不等于没有靶点。
        with ThreadPoolExecutor(max_workers=2) as pool:  # 独立请求同时执行。
            files = dict(pool.map(fetch_file, FILES))  # 任一失败都不发布不完整快照。
    except (OSError, UnicodeError) as error:  # 不发布部分来源。
        raise ContractError("TTD官方下载未完成，请稍后重试；未以旧资料补齐本次结果。") from error  # 给出明确操作说明。
    return make_source(files, query)  # 不使用旧名单补缺失。

def parse_snapshot(snapshot):  # 从固定原文件中提取精确疾病条目候选。
    require(snapshot.get("version") == "TTD.snapshot.1" and isinstance(snapshot.get("query"), str) and snapshot["query"].strip(), "TTD快照缺少版本或明确疾病名称")  # 不根据方剂猜疾病。
    files = snapshot.get("files", {})  # 必须有两种原始来源。
    require(set(files) == set(FILES), "TTD身份文件与疾病关系文件必须齐全")  # 不用旧资料替代一侧。
    versions = []  # 文件头与网站宣传版本分开。
    for role, item in files.items():  # 校验实际原文内容。
        raw = item["text"].encode("utf-8")  # 恢复原字节参与校验。
        require(item["bytes"] == len(raw) and item["sha256"] == hashlib.sha256(raw).hexdigest(), "TTD原文件指纹不一致")  # 防止只改某几行。
        require(item["url"] == BASE + FILES[role] and "TTD - Therapeutic Targets Database" in item["text"][:500], "TTD来源或文件头不一致")  # 不接受其他下载类型。
        match = re.search(r"Version[^\r\n]+", item["text"][:1500])  # 读取真实版本说明。
        versions.append(role + ": " + (match.group(0) if match else "文件未标版本"))  # 缺版本如实记录。
    targets = {}  # 按TTD稳定编号关联身份字段。
    for line_number, line in enumerate(files["targets"]["text"].splitlines(), 1):  # 行号对应已归档原文。
        cells = line.split("\t")  # 官方原始文件不是一般列标题表。
        if len(cells) >= 3 and re.fullmatch(r"T\d+", cells[0]):  # 跳过说明与空行。
            if cells[1] in ("GENENAME", "UNIPROID", "TARGNAME"):  # 仅读取明确字段。
                targets.setdefault(cells[0], {}).setdefault(cells[1], []).append((line_number, "\t".join(cells[2:])))  # 多值不任取首项。
    entries = []  # 保留每条匹配疾病的原关系。
    for line_number, line in enumerate(files["diseases"]["text"].splitlines(), 1):  # 只筛选具体疾病名称。
        cells = line.split("\t")  # 原文完整留存。
        if len(cells) >= 5 and cells[1] == "INDICATI" and cells[3].strip().casefold() == snapshot["query"].strip().casefold():  # 名称精确匹配仅为检索，范围仍待复核。
            require(re.fullmatch(r"T\d+", cells[0]), "TTD疾病关系靶点编号无效")  # 不丢弃异常后冒充完整。
            identity = targets.get(cells[0], {})  # 未找到身份仍保留关系。
            values = lambda key: ";".join(dict.fromkeys(value for number, value in identity.get(key, [])))  # 不按分隔符猜测并拆分基因。
            entries.append({"raw_symbol": values("GENENAME"), "raw_id": cells[0], "raw_score": "", "score_name": "", "source_row": "diseases:" + str(line_number) + ";targets:" + ",".join(str(number) for number, value in identity.get("GENENAME", [])), "disease_term": cells[3], "disease_id": cells[4], "relation_type": "TTD疾病映射原始行；范围待复核", "clinical_status": cells[2], "target_name": values("TARGNAME"), "raw_uniprot": values("UNIPROID")})  # 临床状态不是通用评分。
    return entries, versions  # 空命中不是五库不存在疾病关联。

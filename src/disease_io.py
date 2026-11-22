# 本文件负责受限的文件上传与OTP读取，不决定评分阈值或疾病纳入范围。
from email import policy  # 使用标准库解析浏览器上传格式。
from email.parser import BytesParser  # 避免使用已弃用的cgi模块。
import json  # 保存完整分页响应。
import re  # 限定疾病标识和表单字段。
import time  # 为在线查询设工程超时，不截断后冒充全量。
import urllib.request  # 仅连接明确的官方API。
from contracts import require, ContractError  # 统一处理可预期失败。
from storage import now  # 保存获取时间。
ENDPOINT = "https://api.platform.opentargets.org/api/v4/graphql"  # 不接受用户提供任意请求地址。
LEGACY_QUERY = "query DiseaseTargets($id:String!,$index:Int!,$size:Int!){disease(efoId:$id){id name associatedTargets(enableIndirect:false,page:{index:$index,size:$size}){count rows{score target{id approvedSymbol}}}}}"
QUERY = LEGACY_QUERY.replace("{disease(", "{meta{dataVersion{year month iteration} apiVersion{x y z}} disease(", 1)
OTP_RELEASE_PROTOCOL = "OTP.direct.complete.3"


def otp_release(response):
    """Read version metadata from the same GraphQL response as the disease page."""
    meta = response.get("data", {}).get("meta")
    require(isinstance(meta, dict), "OTP本页缺少官方发布版本")
    release = {}
    for name, fields in (("dataVersion", ("year", "month", "iteration")), ("apiVersion", ("x", "y", "z"))):
        block = meta.get(name)
        require(isinstance(block, dict) and all(k in block for k in fields), "OTP官方发布版本字段不完整")
        values = {}
        for key in fields:
            value = block[key]
            if key == "iteration" and value is None:
                values[key] = None  # Production explicitly returns null for some releases.
            else:
                require((type(value) is int and value >= 0) or
                        (isinstance(value, str) and re.fullmatch(r"[0-9]{1,8}", value)),
                        "OTP官方发布版本字段格式无效")
                values[key] = int(value)
        release[name] = values
    require(release["dataVersion"]["year"] > 0 and 1 <= release["dataVersion"]["month"] <= 12,
            "OTP官方数据发布年月无效")
    return release


def otp_release_label(release):
    data = release["dataVersion"]
    return f"{data['year']:02d}.{data['month']:02d}"

def multipart(content_type, body):  # 读取一个受大小限制的上传表单。
    require(len(body) <= 17 * 1024 * 1024 and "\r" not in content_type and "\n" not in content_type, "上传请求大小或格式不合法")  # 不将用户头部当成任意MIME指令。
    message = BytesParser(policy=policy.default).parsebytes(("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode("ascii") + body)  # 按浏览器实际boundary解析。
    require(message.is_multipart() and not message.defects, "上传格式损坏，请重新选择文件")  # 不尝试猜测残缺上传。
    fields, files = {}, {}  # 普通表单和文件分开处理。
    for part in message.iter_parts():  # 不递归读取嵌套附件。
        require(not part.is_multipart() and not part.defects, "不支持嵌套或损坏的上传内容")  # 只接受标准单层表单。
        name = part.get_param("name", header="content-disposition")  # 字段名来自明确表单项。
        require(part.get_content_disposition() == "form-data" and name and name not in fields and name not in files, "上传字段重复或不合法")  # 不任取重复字段首项。
        data = part.get_payload(decode=True) or b""  # 文件原始字节完整保留。
        filename = part.get_filename()  # 文件名仅供溯源说明。
        if filename is not None:  # 仅允许一个名为upload的文件。
            require(name == "upload" and filename and len(data) <= 16 * 1024 * 1024, "请选择一个不超过16MB的资料文件")  # 不自动截取大文件。
            files[name] = {"name": filename, "data": data}  # 不将文件名用于磁盘路径。
        else:  # 文本字段长度单独控制。
            require(len(data) <= 8000, "上传说明字段过长")  # 不把整份数据塞进元信息。
            fields[name] = data.decode("utf-8", errors="strict")  # 不静默丢弃中文乱码。
    require("upload" in files, "尚未选择上传文件")  # 缺文件不生成来源记录。
    return fields, files  # 外层继续检查令牌、版本和来源元信息。

def request_page(disease_id, index, size=3000):  # 从官方接口读取一页明确的疾病查询。
    payload = json.dumps({"query": QUERY, "variables": {"id": disease_id, "index": index, "size": size}}).encode("utf-8")  # 变量传递避免把输入拼进查询语句。
    request = urllib.request.Request(ENDPOINT, data=payload, headers={"Content-Type": "application/json", "User-Agent": "ModuleA/collect-1"})  # 请求不携带旧项目凭据。
    try:  # 网络错误给出可操作的失败信息。
        with urllib.request.urlopen(request, timeout=10) as response:  # 单页最长等待10秒。
            raw = response.read(8 * 1024 * 1024 + 1)  # 超大响应不无界读取。
        require(len(raw) <= 8 * 1024 * 1024, "OTP单页响应异常过大")  # 不发布残缺响应。
        return json.loads(raw)  # 完整JSON留给后续分页核验。
    except (OSError, ValueError) as error:  # 不将网络失败解释为没有靶点。
        raise ContractError("OTP查询未完成；请稍后重试或上传已下载快照。本次不发布部分结果。") from error  # 保留既有版本。

def _fetch_otp(disease_id, fetch, trace):  # 收集全部直接关联候选，不做分数筛选。
    require(bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9]+", disease_id)), "请输入明确的疾病本体编号，例如MONDO_0005002")  # 不根据简称猜编号。
    pages, requests, total, seen, disease_name = [], [], None, {}, ""  # 保留重试响应及稳定标识。
    started, page_count, page_size = time.monotonic(), 1, 3000  # 首次使用官方允许的最大页宽。
    adaptive = fetch is request_page  # 生产接口可改变页宽，旧测试注入保持两参数约定。
    release = None
    tried_sizes = [page_size]  # 防止重复使用同一分页边界。
    for attempt in range(8 if adaptive else 3):  # 生产环境可尝试多个完整同分边界。
        if adaptive:  # 每轮重算页数，跨轮只合并相同身份、总量且无冲突的稳定ID。
            page_count = 1  # 跨轮累积同一疾病与总量下的稳定ID，逐条检查冲突。
            current_pages = []  # 当前首个响应用于选择下一次补取边界。
        index = 0  # 每轮覆盖全部页，不能凭重复行直接截断。
        while index < page_count:  # 按本次接口总数读取。
            require(time.monotonic() - started < 120 and len(pages) < 100, "OTP完整性补取超出工程预算；未发布部分结果，请使用官方导出")  # 不无限重试。
            response = fetch(disease_id, index, page_size) if adaptive else fetch(disease_id, index)  # 读取一个明确页号。
            trace.append({"attempt": attempt + 1, "index": index, "size": page_size, "response": response})
            require(not response.get("errors") and response.get("data", {}).get("disease"), "OTP未返回有效疾病；请核对编号或接口提示")  # 错误不是空集合。
            if adaptive or release is not None or "meta" in response["data"]:
                page_release = otp_release(response)
                if release is None:
                    require(not pages, "OTP分页的发布版本证据不一致")
                    release = page_release
                require(page_release == release, "OTP分页期间数据或API版本发生变化，未发布混合结果")
            disease = response["data"]["disease"]  # 保存真实疾病身份。
            require(disease["id"] == disease_id, "OTP返回疾病身份不一致")  # 不混合其他疾病。
            block = disease["associatedTargets"]  # 本页数据和接口总数。
            if total is None:  # 首次固定身份及总数。
                total, disease_name = block["count"], disease["name"]  # 全过程保持一致。
            if index == 0:  # 每次改变页宽后都必须重新计算页数。
                width = page_size if adaptive and total > page_size else len(block["rows"])  # 非末页按请求宽度核查页数。
                page_count = max(1, (total + max(width, 1) - 1) // max(width, 1))  # 空结果也核验一次响应。
            require(isinstance(total, int) and total >= 0 and block["count"] == total and disease["name"] == disease_name, "OTP查询期间数量或疾病身份变化，请重试")  # 不混合更新中的快照。
            require(block["rows"] or total == 0, "OTP提前返回空页，未发布部分结果")  # 未完成与真实空结果区分。
            pages.append(response)  # 所有原始响应均保留，包括补取重复行。
            requests.append({"attempt": attempt + 1, "index": index, "size": page_size})  # 精确记录实际请求分页配置。
            if adaptive:  # 生产快照只保留最终自洽分页方案。
                current_pages.append(response)  # 当前页进入本轮候选快照。
            for row in block["rows"]:  # 只对完全一致的稳定ID去重。
                key = row["target"]["id"]  # 不按可能重复的基因名称代替稳定ID。
                require(key not in seen or seen[key] == row, "OTP同一稳定标识的评分或属性发生变化，请重新获取")  # 不从冲突记录任取一条。
                seen[key] = row  # 原始重复响应仍在pages中。
            require(len(seen) <= total, "OTP唯一标识数超过接口总数，请重新获取")  # 数量异常不能发布。
            index += 1  # 前进到下一页。
        if len(seen) == total:  # 唯一稳定ID数达到接口总数才完整。
            break  # 不按重复行累积数判断完成。
        if adaptive:  # 官方按分数排序时，页尾切入同分组会造成下一页重复和遗漏。
            first_rows = current_pages[0]["data"]["disease"]["associatedTargets"]["rows"]  # 读取首个大页的排序边界。
            boundaries = [i for i in range(1, len(first_rows)) if first_rows[i - 1].get("score") != first_rows[i].get("score")]  # 只在完整同分组之间切页。
            choices = [value for value in reversed(boundaries) if value not in tried_sizes and value >= 100]  # 优先使用较大边界以减少请求。
            require(bool(choices), "OTP同分分页没有可用完整边界；未发布部分结果，请使用官方导出")  # 不用简单去重掩盖遗漏。
            preferred = [2999, 2950, 2800, 2500, 2000, 1500, 1000][min(attempt, 6)]
            page_size = min(choices, key=lambda value: (abs(value - preferred), -value))  # 改变分页边界，避免连续落在同一同分组。
            tried_sizes.append(page_size)  # 不重复尝试相同边界。
    require(len(seen) == total, "OTP同分分页仍未取得全部唯一标识；未发布部分结果，请使用官方导出")  # 补取失败不放宽完整性。
    snapshot = {"disease_id": disease_id, "disease_name": disease_name, "enableIndirect": False, "total": total, "queried_at": now(), "query": QUERY if release else LEGACY_QUERY, "endpoint": ENDPOINT, "collection_version": OTP_RELEASE_PROTOCOL if release else "OTP.direct.complete.2", "requests": requests, "pages": pages}  # 固定每次响应及配置。
    if release:
        snapshot["release"] = release
    data = json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode("utf-8")  # 保存完整候选来源。
    require(len(data) <= 16 * 1024 * 1024, "OTP完整快照超过当前容量，请使用官方导出")  # 不截断来源文件。
    return {"database": "OTP", "format": "otp_api", "query": disease_name, "retrieved_at": snapshot["queried_at"], "version": otp_release_label(release) if release else "接口未提供数据库发布版本；以响应快照固定", "source_url": ENDPOINT, "name": "otp_direct.json", "encoding": "utf-8-sig", "data": data}  # 与上传共用整理流程。


def fetch_otp(disease_id, fetch=request_page):
    """有界累积补取；不完整时保存每次原响应供诊断。"""
    trace = []
    try:
        return _fetch_otp(disease_id, fetch, trace)
    except Exception as error:
        error.source_trace = {"disease_id": disease_id, "enableIndirect": False, "requests": trace}
        raise

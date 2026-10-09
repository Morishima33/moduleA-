# 本文件核对用户提供的MeSH标准词和编号，并保存可复核的NLM官方响应证据。
from datetime import datetime, timezone  # 记录本次官方核对时间。
import json  # 解析NLM返回的JSON数据。
import re  # 限定MeSH描述词编号格式。
from urllib.error import HTTPError, URLError  # 将网络失败转换成用户可理解的提示。
from urllib.parse import urlencode  # 安全生成官方查询参数。
from urllib.request import Request, urlopen  # 只访问固定的NLM HTTPS接口。
from contracts import fingerprint, require, ContractError  # 复用项目校验和指纹规则。

API_ROOT = "https://id.nlm.nih.gov/mesh/lookup"  # 固定使用NLM官方MeSH RDF查询服务。
API_VERSION = "MeSH RDF API 1.0.1"  # 保存当前官方接口版本说明。

def _request_json(path, parameters=None, timeout=30):  # 获取并严格解析一个官方JSON响应。
    query = "?" + urlencode(parameters) if parameters else ""  # 只有明确参数才追加查询字符串。
    url = API_ROOT + path + query  # 主机和路径均由程序固定，用户不能提交任意网址。
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "ModuleA-MeSH-Identity/1.0"})  # 明确响应格式和客户端身份。
    try:  # 网络异常必须停止登记，不能伪装核对成功。
        with urlopen(request, timeout=timeout) as response:  # 设置超时，避免网页无限等待。
            payload = response.read(2 * 1024 * 1024 + 1)  # 官方身份响应不应超过2MB。
            require(len(payload) <= 2 * 1024 * 1024, "NLM MeSH响应异常过大，未保存研究")  # 拒绝异常内容。
            require(response.status == 200, "NLM MeSH服务没有返回成功状态")  # 只接受完整成功响应。
    except (HTTPError, URLError, TimeoutError, OSError) as error:  # 汇总常见联网错误。
        raise ContractError("暂时无法连接NLM官方MeSH服务，请检查网络后重试；本次未保存研究") from error  # 不泄露内部连接细节。
    try:  # JSON损坏与零结果需要分别处理。
        value = json.loads(payload.decode("utf-8"))  # NLM接口使用UTF-8 JSON。
    except (UnicodeDecodeError, json.JSONDecodeError) as error:  # 非JSON响应不能作为证据。
        raise ContractError("NLM MeSH响应格式异常，请稍后重试；本次未保存研究") from error  # 不使用部分数据。
    return url, value, fingerprint(value)  # 同时返回实际网址、内容和稳定指纹。

def _production_year(years):  # 从官方可用年份中选择最新明确数字版本。
    require(isinstance(years, list), "NLM MeSH年份响应格式异常")  # 官方响应应为列表。
    numeric = sorted((int(value) for value in years if re.fullmatch(r"20\d{2}", str(value))), reverse=True)  # 忽略current等别名。
    require(bool(numeric), "NLM MeSH没有返回可固定的年度版本")  # 正式核对必须绑定数字年份。
    return str(numeric[0])  # 使用官方当前列出的最新生产年份。

def verify_mesh_identity(mesh_term, mesh_id):  # 核对标准词与描述词编号是否属于同一官方记录。
    term = str(mesh_term or "").strip()  # 只去除用户输入两端空白。
    descriptor_id = str(mesh_id or "").strip().upper()  # MeSH描述词编号统一显示为大写D。
    require(bool(term) and len(term) <= 500, "请填写MeSH标准词")  # 空值或异常长文字不能联网查询。
    require(bool(re.fullmatch(r"D\d{6,9}", descriptor_id)), "MeSH编号格式应类似D029424")  # 不接受网页数字UID或其他体系编号。
    years_url, years, years_hash = _request_json("/years")  # 先固定本次可用生产年份。
    year = _production_year(years)  # 后续精确查询绑定该年度。
    descriptor_url, matches, descriptor_hash = _request_json("/descriptor", {"label": term, "match": "exact", "year": year, "limit": 50})  # 只进行官方精确名称查询。
    rows = matches if isinstance(matches, list) else [matches] if isinstance(matches, dict) else []  # 兼容单条和数组JSON表示。
    expected_suffix = "/" + descriptor_id  # 年度资源网址末段必须是用户编号。
    exact = [row for row in rows if isinstance(row, dict) and str(row.get("resource", "")).rstrip("/").endswith(expected_suffix) and str(row.get("label", "")).strip().casefold() == term.casefold()]  # 名称和编号必须同时一致。
    require(bool(exact), "MeSH标准词与编号未在NLM官方记录中精确对应，请核对后重试")  # 不自动替用户选择相近疾病。
    details_url, details, details_hash = _request_json("/details", {"descriptor": descriptor_id, "includes": "terms"})  # 保存首选词和官方同义词用于追溯。
    require(isinstance(details, dict) and str(details.get("descriptor", "")).rstrip("/").endswith(expected_suffix), "NLM MeSH详情与编号不一致")  # 防止响应错配。
    preferred = [row for row in details.get("terms", []) if isinstance(row, dict) and row.get("preferred") is True]  # 官方详情应有唯一首选词。
    require(any(str(row.get("label", "")).strip().casefold() == term.casefold() for row in preferred), "所填文字不是该编号的MeSH首选词，请填写官方标准词")  # Entry Term不能冒充首选词字段。
    checked_at = datetime.now(timezone.utc).isoformat()  # 记录可比较的UTC时间。
    return {"status": "verified", "mesh_id": descriptor_id, "preferred_term": term, "mesh_year": year, "checked_at": checked_at, "provider": "U.S. National Library of Medicine", "api_version": API_VERSION, "descriptor_resource": exact[0]["resource"], "entry_terms": [str(row.get("label", "")) for row in details.get("terms", []) if isinstance(row, dict) and row.get("label")], "evidence": {"years_url": years_url, "years_sha256": years_hash, "descriptor_url": descriptor_url, "descriptor_sha256": descriptor_hash, "details_url": details_url, "details_sha256": details_hash, "years_response": years, "descriptor_response": rows, "details_response": details}}  # 完整响应随A00登记归档。

def validate_mesh_identity(intake):  # 校验已归档的MeSH身份没有与登记字段脱节。
    term = intake.get("mesh_term")  # 读取用户确认的标准词。
    descriptor_id = intake.get("mesh_id")  # 读取用户确认的描述词编号。
    evidence = intake.get("mesh_verification")  # 读取服务器生成的官方核对记录。
    require(isinstance(term, str) and term.strip() and isinstance(descriptor_id, str) and re.fullmatch(r"D\d{6,9}", descriptor_id), "正式研究登记缺少有效MeSH标准词或编号")  # 两个字段都必须存在。
    require(isinstance(evidence, dict) and evidence.get("status") == "verified", "正式研究登记缺少NLM官方MeSH核对证据")  # 不能只填文字绕过核对。
    require(evidence.get("preferred_term") == term and evidence.get("mesh_id") == descriptor_id, "MeSH核对证据与登记字段不一致")  # 修改字段后旧证据立即失效。
    require(re.fullmatch(r"20\d{2}", str(evidence.get("mesh_year", ""))) is not None, "MeSH核对证据缺少年度版本")  # 必须绑定可复现版本。
    require(str(evidence.get("descriptor_resource", "")).rstrip("/").endswith("/" + descriptor_id), "MeSH官方资源与编号不一致")  # 再次核对官方资源标识。
    require(isinstance(evidence.get("evidence"), dict) and all(evidence["evidence"].get(key) for key in ("years_sha256", "descriptor_sha256", "details_sha256")), "MeSH核对证据不完整")  # 三项官方响应均须有指纹。
    return evidence  # 供网页和后续A02读取同一身份。

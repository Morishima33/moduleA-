"""新版STRING传输：显式环境代理或直连，不继承失效的Windows注册表代理。"""

import json
from types import FunctionType
import urllib.request
import urllib.parse
from contracts import require, ContractError
from storage import now
import ppi_flow as legacy


# 固定官方12.0接口、参数及TLS核验，失败与有效空响应分开。
def request(method, params):
    require(method in ("get_string_ids", "network"), "不支持的STRING请求")
    url = legacy.BASE + method
    query = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(params).encode(),
        headers={"User-Agent": "ModuleA/A04.dual.2"},
    )
    proxies = urllib.request.getproxies_environment()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    try:
        with opener.open(query, timeout=40) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
        require(len(raw) <= 16 * 1024 * 1024, "STRING响应过大，请使用离线资料")
        require(isinstance(json.loads(raw), list), "STRING未返回完整记录列表")
        return {
            "url": url,
            "params": params,
            "retrieved_at": now(),
            "response_text": raw.decode("utf-8"),
            "transport": "explicit_environment_proxy_or_direct_tls.1",
        }
    except (OSError, ValueError) as error:
        raise ContractError("STRING获取未完成，未发布结果；请检查网络后重试。") from error


# 只替换本次函数的传输依赖；科学获取口径和旧模块全局保持原样。
def fetch(targets, raw=None, scope=None):
    obtain = FunctionType(legacy.fetch.__code__, dict(legacy.fetch.__globals__, request=request))
    return obtain(targets, raw, scope)

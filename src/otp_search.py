# Open Targets疾病实体搜索；只返回候选身份，不自动选择或发布A02。
import json  # 编码GraphQL请求并解析响应。
import urllib.request  # 连接固定官方接口。

from contracts import ContractError, require  # 使用项目统一错误说明。
from disease_io import ENDPOINT  # 与A02采集器使用同一官方端点。


SEARCH_QUERY = "query Search($text:String!){search(queryString:$text,entityNames:[\"disease\"],page:{index:0,size:20}){total hits{id name entity}}}"  # 只搜索疾病实体。


def search_disease(text):  # 根据已核验疾病词查找当前OTP标识候选。
    require(isinstance(text, str) and text.strip(), "请提供明确疾病名称")  # 空词不请求网络。
    payload = json.dumps({"query": SEARCH_QUERY, "variables": {"text": text.strip()}}).encode("utf-8")  # 参数不拼接进GraphQL源码。
    request = urllib.request.Request(ENDPOINT, data=payload, headers={"Content-Type": "application/json", "User-Agent": "ModuleA/collect-1"})  # 固定官方地址。
    try:  # 网络失败与真实无候选分开。
        with urllib.request.urlopen(request, timeout=20) as response:  # 设置有限等待。
            raw = response.read(2 * 1024 * 1024 + 1)  # 防止异常超大响应。
        require(len(raw) <= 2 * 1024 * 1024, "OTP搜索响应异常过大")  # 不截断后解析。
        data = json.loads(raw)  # 完整解析官方响应。
    except (OSError, ValueError) as error:  # 不把连接失败解释为空集合。
        raise ContractError("OTP疾病搜索未完成，请稍后重试") from error  # 保留当前研究不变。
    require(not data.get("errors") and data.get("data", {}).get("search") is not None, "OTP疾病搜索返回错误")  # GraphQL错误不继续。
    hits = data["data"]["search"].get("hits", [])  # 读取当前候选。
    return [{"id": row.get("id"), "name": row.get("name"), "entity": row.get("entity")} for row in hits if row.get("id") and row.get("name")]  # 只返回有稳定身份的候选。


if __name__ == "__main__":  # 提供维护入口供自动准备A02前核对。
    import argparse  # 解析疾病名称。
    parser = argparse.ArgumentParser(description="搜索Open Targets当前疾病实体")  # 说明用途。
    parser.add_argument("--term", required=True)  # 必须明确检索词。
    arguments = parser.parse_args()  # 读取参数。
    print(json.dumps(search_disease(arguments.term), ensure_ascii=False, indent=2))  # 输出候选供核对。

# 采集HERB已有成分靶点；不运行新的预测，不改当前研究。
import re  # 校验来源编号，禁止把外部编号当路径。
from contracts import require
import json  # 留存完整官方响应和采集状态。
import hashlib  # 保存原始响应指纹。
import threading  # 限制同时请求与请求频率。
import time  # 控制请求间隔和超时。
import urllib.request  # 使用官方详情接口。
from concurrent.futures import ThreadPoolExecutor, as_completed  # 有限并行下载。
from pathlib import Path  # 所有输出留在核查目录。
from .multisource import catalog, herb_records  # 复用成分身份核查。

_lock = threading.Lock()  # 防止多个线程同时发起请求。
_last_request = 0.0  # 记录上次请求时间。

def fetch(identifier, destination):  # 每个成分保留独立原始响应。
    require(re.fullmatch(r"HBIN\d+", identifier) is not None, "HERB成分编号格式错误")
    global _last_request  # 仅控制本采集器请求频率。
    path = destination / (identifier + ".json")  # 使用明确HERB编号命名。
    payload = {"func_name": "detail_api", "label": "Ingredient", "v": identifier, "key_id": identifier}  # 与官方页面请求一致。
    url = "http://herb.ac.cn/chedi/api/"  # 仅请求官方只读查询。
    for attempt in range(2):  # 只重试网络失败，不修改科学参数。
        try:  # 失败记录不能写成零靶点。
            with _lock:  # 控制全局发起频率。
                time.sleep(max(0, 0.5 - (time.monotonic() - _last_request)))  # 保护公共服务。
                _last_request = time.monotonic()  # 两次请求间隔至少半秒。
            request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})  # 不发送凭据。
            with urllib.request.urlopen(request, timeout=15) as response:  # 避免无限等待。
                raw = response.read(6000000)  # 单个详情设置安全大小上限。
            data = json.loads(raw)  # 先验证响应再归档。
            summary = data.get("summary", [])  # 验证返回的成分身份。
            require(len(summary) == 2 and summary[1][0] == identifier, "返回的成分身份不一致")  # 不能接收其他成分详情。
            targets = data.get("ingredient_target")  # 只使用数据库已有成分靶点关系。
            require(isinstance(targets, list) and bool(targets) and targets[0] == ["Target id", "Target name", "Database sources"], "已有关系表缺失或格式改变")  # 不把响应异常当零关系。
            if path.exists():  # 恢复采集时复核已经留存的字节。
                require(path.read_bytes() == raw, "已有响应变化，须另建版本")  # 不覆盖历史。
            else:  # 首次成功响应独立留存。
                with path.open("xb") as stream:  # 防止重复请求互相覆盖。
                    stream.write(raw)  # 保存完整原始JSON。
            return {"id": identifier, "status": "success", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "existing_rows": len(targets) - 1, "url": url, "payload": payload}  # 成功空关系独立记录。
        except Exception as error:  # 保留实际失败诊断。
            if attempt == 1:  # 两次网络尝试后停止该条目。
                return {"id": identifier, "status": "failed", "error": str(error), "url": url, "payload": payload}  # 不伪造零记录。

def collect(folder, herb_files):  # 本次核查运行，不写生产研究索引。
    raw = folder / "raw"  # 使用归档输入。
    identities = catalog(raw / "HERB_ingredient_info_v2.txt")  # 固定全量身份快照。
    records = herb_records(raw, identities, herb_files)  # 固定用户提供的药味导出。
    identifiers = sorted({r["source_id"] for r in records})  # 同一成分只查询一次。
    destination = raw / "HERB_existing_details"  # 官方响应与计算表分开。
    destination.mkdir(exist_ok=True)  # 支持中断后继续采集。
    outputs = []  # 记录每条成功或失败。
    with ThreadPoolExecutor(max_workers=2) as pool:  # 限制公共服务负载。
        jobs = [pool.submit(fetch, identifier, destination) for identifier in identifiers]  # 只查询本次成分。
        for job in as_completed(jobs):  # 保存实际完成状态。
            outputs.append(job.result())  # 不忽略失败。
            if len(outputs) % 25 == 0:  # 输出必要进度便于中途报告。
                print("HERB completed", len(outputs), "of", len(identifiers), flush=True)  # 不宣称科学审核完成。
    outputs.sort(key=lambda row: row["id"])  # 固定记录顺序。
    with (folder / "HERB已有关系获取记录_v1.json").open("x", encoding="utf-8") as stream:  # 运行记录不覆盖。
        json.dump(outputs, stream, ensure_ascii=False, indent=2)  # 保存所有来源与失败。
    print("HERB acquisition finished", len(outputs), "failed", sum(r["status"] != "success" for r in outputs), flush=True)  # 真实总结。


    return outputs  # 调用方依据成功与失败明细决定是否进入候选预览。

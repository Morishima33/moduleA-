# A06只读来源采集；原始回应内容寻址保存，不自动批准结构。
import urllib.request  # 官方HTTP请求。
import urllib.error  # 区分404与网络失败。
import urllib.parse  # 编码成分名与限制主机。
import json  # JSON来源解析。
from contracts import require, fingerprint  # 统一证据校验。
from storage import now, write_json, file_record  # 统一位置及指纹记录。
HOSTS={"pubchem.ncbi.nlm.nih.gov","www.ebi.ac.uk","rest.uniprot.org","data.rcsb.org","files.rcsb.org","pypi.org"}  # 不允许任意外站输入。

def capture(root,url):  # 不把请求失败视为无结构。
    require(urllib.parse.urlsplit(url).scheme=="https" and urllib.parse.urlsplit(url).hostname in HOSTS,"不是允许的官方结构来源")  # 禁止任意文件和主机。
    record={"url":url,"retrieved_at":now(),"method":"GET"}  # 时间与原地址。
    try:  # 保存成功或HTTP错误原文。
        request=urllib.request.Request(url,headers={"User-Agent":"ModuleA/A06-source"})  # 明确工具标识。
        with urllib.request.urlopen(request,timeout=40) as response:  # 有限等待。
            require(urllib.parse.urlsplit(response.url).hostname in HOSTS,"来源重定向到未允许主机")  # 限定最终来源。
            body=response.read(24*1024*1024+1)  # 不无界读取。
            require(len(body)<=24*1024*1024,"来源过大，未截断后继续")  # 不发布残缺回应。
            record.update(status=response.status,state="success",response_text=body.decode("utf-8"),final_url=response.url)  # SDF和JSON保留原文。
    except urllib.error.HTTPError as error:  # 原HTTP状态保留。
        record.update(status=error.code,state="http_error",response_text=error.read(1024*1024).decode("utf-8",errors="replace"))  # 404与其他失败不合并。
    except (OSError,UnicodeError) as error:  # 无网络不能声称无可用结构。
        record.update(status=None,state="request_failed",error=str(error))  # 保存失败原因。
    path=root/"references"/("structure_"+fingerprint(record)+".json")  # 命名遵循来源内容指纹。
    write_json(path,record)  # 不覆盖历史查询。
    return record,file_record(root,path,"structure_source")  # 不产生科研批准状态。

def json_data(record):  # 仅成功JSON才能用于核对。
    require(record.get("state")=="success","结构来源未成功返回，需重试或核对")  # 失败不转为空列表。
    return json.loads(record["response_text"])  # 错误格式明确抛出。

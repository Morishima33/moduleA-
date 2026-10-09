# A04获取、归档与复算；沿用统一研究和复核状态。
import json  # 官方JSON原响应归档。
import time  # 遵守官方接口间隔。
import urllib.request  # 固定官方版本地址。
import urllib.parse  # 安全编码查询字段。
from contracts import require, ContractError  # 保留明确阻断原因。
from storage import write_lock, write_json, file_record, verified_file, read_json, now, within  # 复用文件管理。
from ppi import CONFIG, calculate, network_svg  # 唯一计算实现。
from ppi_identity import authorization as identity_authorization, context as identity_context, queries as identity_queries, params as identity_params, resolve as resolve_identity, SNAPSHOT, SCOPE  # 已批准的限定身份补查。
CONFIG2 = dict(CONFIG, version="A04.2", identity_rule="STRING.identity.2")  # 保留A04.1历史复算。
BASE = "https://version-12-0.string-db.org/api/json/"  # 核对官方version接口后固定12.0。

def request(method, params):  # 不允许自定义任意网址。
    url = BASE + method  # 限定官方方法。
    query = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), headers={"User-Agent":"ModuleA/A04.1"})  # POST避免长URL截断。
    try:  # 查询失败不是空网络。
        with urllib.request.urlopen(query, timeout=40) as response:  # 单次有限等待。
            raw = response.read(16*1024*1024+1)  # 不无界读取响应。
        require(len(raw)<=16*1024*1024, "STRING响应过大，请使用离线资料")  # 不截断后继续分析。
        data=json.loads(raw)  # 错误响应不冒充正常记录。
        require(isinstance(data,list), "STRING未返回完整记录列表")  # 不接受错误对象。
        return {"url":url,"params":params,"retrieved_at":now(),"response_text":raw.decode("utf-8")}  # 原文保存便于追溯。
    except (OSError,ValueError) as error:  # 失败清楚提示。
        raise ContractError("STRING获取未完成，未发布结果；可重试或在其他信息中导入资料包。") from error  # 不把失败当无关联。

def mapped_ids(targets, records):  # 只对明确核对的STRING身份请求网络。
    ids=[]  # 保留已确认编号。
    for i,target in enumerate(targets):  # 与计算器采用相同输入顺序。
        matches=[x for x in records if int(x["queryIndex"])==i]  # 避免返回顺序变化。
        if len(matches)==1 and int(matches[0]["ncbiTaxonId"])==9606 and matches[0]["preferredName"]==target["symbol"] and matches[0]["stringId"].startswith("9606."):  # 不自动接受相似名称。
            ids.append(matches[0]["stringId"])  # 其余留在问题表。
    return sorted(set(ids))  # 不扩展邻居。

def fetch(targets, identity_raw=None, approved_scope=None):  # 自动来源与上传来源进入同一计算器。
    params={"identifiers":"\r".join(x["symbol"] for x in targets),"species":9606,"echo_query":1,"caller_identity":"ModuleA"}  # 绑定实际交集。
    mapping=request("get_string_ids",params) if targets else {"url":BASE+"get_string_ids","params":params,"retrieved_at":now(),"response_text":"[]"}  # 空交集不发无效请求。
    records=json.loads(mapping["response_text"])  # 原名称响应保留。
    evidence=None  # 无范围授权时仍使用旧规则。
    if identity_raw is not None:  # 仅指定研究启用已批准补查。
        approved_scope=approved_scope or SCOPE  # 旧测试调用保持原COPD授权。
        evidence={"authorization":dict(approved_scope),"hgnc_sha256":SNAPSHOT,"queries":[]}  # 与原始查询一起归档。
        for spec in identity_queries(targets,identity_raw,approved_scope):  # 从官方快照生成稳定编号。
            time.sleep(1)  # 遵守STRING请求间隔。
            evidence["queries"].append({"query":spec,"source":request("get_string_ids",identity_params(spec["identifier"]))})  # 失败立即中止而非假作空结果。
        records,_,_=resolve_identity(targets,records,evidence,identity_raw,approved_scope)  # 只有有证据的旧名进入网络。
    ids=mapped_ids(targets,records)  # 不凭未核验最佳匹配建图。
    parameters={"identifiers":"\r".join(ids),"species":9606,"required_score":900,"network_type":"functional","add_nodes":0,"caller_identity":"ModuleA"}  # 与大纲一致。
    if len(ids)>1:  # 单节点接口会自动扩展邻居，明确跳过。
        time.sleep(1)  # STRING官方要求请求间隔。
        network=request("network",parameters)  # 获取集合内部关联。
    else:  # 少于两节点的无向无自环图必为空。
        network={"url":BASE+"network","params":parameters,"retrieved_at":now(),"response_text":"[]","skipped":"少于两个已核验节点；避免API自动扩展"}  # 不假称调用成功。
    bundle={"schema_version":"A04.source.1","string_version":"12.0","mapping":mapping,"network":network}  # 旧来源包结构保持。
    if evidence is not None:  # 新规则明确版本。
        bundle.update(schema_version="A04.source.2",identity_evidence=evidence)  # 不覆盖原响应。
    return bundle  # 整包原文供重复使用。

def evaluate(targets, bundle, purpose, identity_raw=None, approved_scope=None):  # 上传与自动查询都必须通过相同来源校验。
    require(bundle.get("schema_version") in ("A04.source.1","A04.source.2") and bundle.get("string_version")=="12.0", "A04来源包格式或STRING版本不一致")  # 不猜版本。
    mapping,network=bundle["mapping"],bundle["network"]  # 两份来源缺一不可。
    expected={"identifiers":"\r".join(x["symbol"] for x in targets),"species":9606,"echo_query":1,"caller_identity":"ModuleA"}  # 防止导入其他交集的网络。
    require(mapping["url"]==BASE+"get_string_ids" and mapping["params"]==expected and bool(mapping["retrieved_at"]), "STRING映射请求与本次交集不一致")  # 不靠文件名判断。
    records=json.loads(mapping["response_text"])  # 保留原响应定位。
    adjustments,excluded=[],[]  # 旧版本不增加输出字段。
    if bundle["schema_version"]=="A04.source.2":  # 独立复算补查和授权。
        records,adjustments,excluded=resolve_identity(targets,records,bundle["identity_evidence"],identity_raw,approved_scope or SCOPE)  # 不直接信任派生映射。
    ids=mapped_ids(targets,records)  # 明确全部已核验节点。
    expected={"identifiers":"\r".join(ids),"species":9606,"required_score":900,"network_type":"functional","add_nodes":0,"caller_identity":"ModuleA"}  # 限定网络类型和阈值。
    require(network["url"]==BASE+"network" and network["params"]==expected and bool(network["retrieved_at"]), "STRING网络请求与已核验节点或大纲参数不一致")  # 禁止额外扩展。
    summary,tables=calculate(targets,records,json.loads(network["response_text"]))  # 独立复算。
    if bundle["schema_version"]=="A04.source.2":  # 仅移出已明确批准的PPI问题清单。
        omitted={r["target_id"] for r in excluded}  # 不删改交集及其他分支。
        tables["identity_issues"]=[r for r in tables["identity_issues"] if r["target_id"] not in omitted]  # 已处理缺口不是待审问题。
        tables.update(identity_adjustments=adjustments,ppi_exclusions=excluded)  # 仍可查明所有未入网者。
        summary.update(身份待核验数=len(tables["identity_issues"]),本次PPI暂不采用数=len(excluded),handoff_blocked=bool(tables["identity_issues"]),覆盖说明="已批准缺口仅影响PPI；A03及富集输入保留原交集")  # 明确覆盖限制。
    summary.update(analysis_purpose=purpose, STRING版本="12.0", 计算库版本=CONFIG["networkx"])  # 测试标签继续传播。
    return summary,tables  # 第一轮与第二轮均提供复核。

def validator(root):  # 从归档原文与真实上游复算，不能只检查表形状。
    def check(run,summary,tables,anomalies,outcome):  # 沿用核心签名。
        require(run["config"] in (CONFIG,CONFIG2), "A04配置与大纲不一致")  # 不悄悄改参数。
        home=within(root/"studies",run["study_id"])  # 只读本研究来源。
        source=read_json(verified_file(home,run["inputs"]["source_file"]))  # 检查原始包指纹。
        parent=read_json(verified_file(home,run["inputs"]["parent_result"]))  # 不依赖任意传入靶点。
        require(parent["run_id"]==run["parent_runs"]["A03"], "PPI上游不是本次批准的A03")  # 来源一致。
        raw=None  # 旧运行按旧规则复算。
        require((source["schema_version"]=="A04.source.2") == (run["config"]==CONFIG2), "A04来源与计算规则版本不一致")  # 防止升级冒充旧结果。
        if run["config"]==CONFIG2:  # 已批准身份例外必须绑定研究和上游。
            approved_scope=identity_authorization(run["study_id"],parent["run_id"],root)  # 读取绑定当前研究及A03的明确授权。
            require(approved_scope is not None, "身份例外授权不适用于本研究或上游")  # 不能跨研究导入放行。
            raw=verified_file(home,run["inputs"]["identity_snapshot"]).read_bytes()  # 使用研究包归档的官方快照。
        expected=evaluate(parent["tables"]["intersection_targets"],source,parent["summary"].get("analysis_purpose","research"),raw,approved_scope if run["config"]==CONFIG2 else None)  # 使用归档实际输入。
        require((summary,tables)==expected, "A04结果与原始来源复算不一致")  # 表图不能另造数。
        require(outcome==("success" if summary["参与节点数"] else "empty"), "A04空网络状态不一致")  # 孤立与失败分开。
    return check  # 登记为真正的科学模块。

def run_ppi(workflow,sid,expected_a03,expected_a04,reason,bundle=None):  # 网页与自动调用统一入口。
    manifest=workflow.load(sid)  # 获取当前上游。
    require(manifest["current"].get("A03")==expected_a03 and workflow.approved(manifest,expected_a03), "请先复核通过当前A03交集")  # 不代签。
    parent=workflow.result(manifest,expected_a03)  # 核查所有源文件。
    approved_scope=identity_authorization(sid,expected_a03,workflow.root)  # 用户决定只作用于当前研究及上游版本。
    raw=identity_context(workflow.root,sid,expected_a03)  # 本次授权与研究版本绑定。
    bundle=fetch(parent["tables"]["intersection_targets"],raw,approved_scope) if bundle is None else bundle  # 获取失败不覆盖旧结果。
    summary,tables=evaluate(parent["tables"]["intersection_targets"],bundle,parent["summary"].get("analysis_purpose","research"),raw,approved_scope)  # 先完成科学校验。
    with write_lock(workflow.root):  # 只有完整结果才进入发布阶段。
        manifest=workflow.load(sid)  # 获取期间发生变更时拒绝旧页面。
        require(manifest["current"].get("A03")==expected_a03 and manifest["current"].get("A04","")==expected_a04, "上游或PPI版本已改变，请刷新")  # 不覆盖并发结果。
        home=workflow.location(sid)  # 保存至既定研究目录。
        from contracts import fingerprint  # 按内容指纹命名证据包。
        path=home/"raw"/("string_"+fingerprint(bundle)+".json")  # 同样证据只保存一次。
        if not path.exists():  # 原资料不可覆盖。
            write_json(path,bundle)  # 保存完整请求及响应。
        inputs={"source_file":file_record(home,path,"string_source"),"parent_result":manifest["runs"][expected_a03]["result_file"]}  # 绑定上游和来源。
        config=CONFIG  # 旧格式保留旧算法身份规则。
        if bundle["schema_version"]=="A04.source.2":  # 归档官方快照，内容相同只保留一份。
            snapshot=home/"raw"/("hgnc_"+SNAPSHOT+".tsv")  # 与A01/A02相同命名规则。
            if not snapshot.exists():  # 不覆盖已有身份来源。
                with snapshot.open("xb") as stream:  # 独占创建原件副本。
                    stream.write(raw)  # 字节与官方固定快照一致。
            inputs["identity_snapshot"]=file_record(home,snapshot,"hgnc_source")  # 随运行校验文件指纹。
            config=CONFIG2  # 与来源包新版本对应。
        run=workflow._begin(manifest,"A04",inputs,dict(config),reason)  # 创建新版本但不批准。
        image=home/"runs"/"A04"/run["run_id"]/"ppi.svg"  # 图形属于同一运行。
        with image.open("x",encoding="utf-8") as stream:  # 不改旧图。
            stream.write(network_svg(tables))  # 图由同一表生成。
        result=workflow._finish(manifest,run["run_id"],summary,tables,["STRING功能关联不等于直接物理结合。","第二轮只使用原网络指标重新取中位数，是参考子集。","身份问题未自动排除；有问题时下游保持阻断。"],"success" if summary["参与节点数"] else "empty",sources=list(inputs.values()),figures=[file_record(home,image,"figure")])  # 独立校验后发布。
        workflow.save(manifest)  # 待人工总体复核。
    return result  # 不自动选择对接蛋白。

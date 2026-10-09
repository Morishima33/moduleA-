# A05统一来源、固定版本ORA、归档与复算入口。
import csv  # 读取官方身份快照。
import io  # 不生成额外映射副本。
import json  # 交换R输入输出。
import gzip  # 压缩完整注释快照。
import hashlib  # 原始来源按内容寻址。
import tempfile  # 仅在运行环境中暂存工作文件。
import subprocess  # 调用已固定的R实现。
import urllib.request  # 读取KEGG官方注释。
from pathlib import Path  # 约束项目文件位置。
from contracts import require, ContractError, fingerprint, check_result  # 使用统一校验。
from storage import read_json, write_json, verified_file, file_record, write_lock, now, within  # 使用同一归档规则。
CONFIG={"version":"A05.1","tool":"clusterProfiler","tool_version":"4.14.6","org.Hs.eg.db":"3.20.0","GO.db":"3.20.0","DOSE":"4.0.1","method":"ORA","adjust":"BH","adjust_groups":["BP","CC","MF","KEGG"],"min_size":10,"max_size":500,"adjusted_p_lt":0.05,"show_GO":10,"show_KEGG":20,"background":"each_annotation_human_genes","tested_terms":"input_hit_and_size_10_500","sort":["p.adjust","ID"]}  # 用户批准的统计与展示配置。
RSCRIPT=Path("D:/R/R-4.4.1/bin/x64/Rscript.exe")  # 本机已核验R入口，不使用旧项目代码。

def r_call(root, mode, value):  # R接口失败不伪装为空富集。
    with tempfile.TemporaryDirectory(prefix="a05_",dir=root/"environments") as folder:  # 临时文件归属运行环境。
        directory=Path(folder)  # 本次隔离工作位置。
        source,dest=directory/"input.json",directory/"output.json"  # 固定用途名称。
        source.write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")  # 真实输入。
        try:  # 不发布半份计算。
            process=subprocess.run([str(RSCRIPT),"--vanilla","../../src/enrichment.R",mode,"input.json","output.json"],cwd=directory,capture_output=True,timeout=300)  # 不经过shell拼接。
        except (OSError,subprocess.TimeoutExpired) as error:  # 失败可重新运行。
            raise ContractError("A05的R计算未完成；请核对本机固定环境或稍后重试") from error  # 不标成无显著。
        require(process.returncode==0 and dest.is_file(),"A05计算失败："+process.stderr.decode("utf-8",errors="replace")[-1500:])  # 保留可定位原因。
        return read_json(dest),process.stdout.decode("utf-8",errors="replace")+process.stderr.decode("utf-8",errors="replace")  # 日志归档。

def download(endpoint):  # KEGG原响应完整保存。
    url="https://rest.kegg.jp/"+endpoint  # 限定官方域名。
    try:  # 错误页面不得继续分析。
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"ModuleA/A05.1"}),timeout=60) as response:  # 有限等待。
            raw=response.read(20*1024*1024+1)  # 防止无界读取。
        require(len(raw)<=20*1024*1024,"KEGG响应过大")  # 不截断来源。
        return {"url":url,"retrieved_at":now(),"response_text":raw.decode("utf-8")}  # 下载日期不冒充发布版本。
    except OSError as error:  # 无静默旧缓存替代。
        raise ContractError("KEGG官方来源获取失败；未发布富集结果") from error  # 重试时产生完整来源。

def kegg_terms(sources):  # 从两份官方原文生成唯一注释表。
    names={}  # 通路名称。
    for line in sources["names"]["response_text"].splitlines():  # 原始TSV格式。
        cells=line.split("\t")  # 只按官方列切分。
        require(len(cells)==2 and cells[0].removeprefix("path:").startswith("hsa"),"KEGG通路名称格式异常")  # 不接受非人类库。
        names[cells[0].removeprefix("path:")]=cells[1]  # 保存原英文描述。
    sets={key:set() for key in names}  # 背景来自实际可分析通路。
    for line in sources["links"]["response_text"].splitlines():  # 保留所有基因—通路关系。
        cells=line.split("\t")  # 输入格式限定。
        require(len(cells)==2 and cells[0].startswith("hsa:") and cells[1].startswith("path:hsa"),"KEGG注释关系格式异常")  # 非人类不入库。
        gid,term=cells[0][4:],cells[1][5:]  # 提取官方Entrez及通路编号。
        require(gid.isdigit() and term in names,"KEGG注释编号或名称不完整")  # 不丢失无法解释的关系。
        sets[term].add(gid)  # 去重。
    require(bool(names) and any(sets.values()),"KEGG来源为空，不能作为正常空分析")  # 抓取失败与无富集不同。
    return [{"id":k,"description":names[k],"genes":sorted(v)} for k,v in sorted(sets.items()) if v]  # 无注释条目不进实际背景。

def source_snapshot(root):  # 可复用固定完整来源而非旧研究结果。
    index=root/"environments/A05_sources.json"  # 唯一来源索引，不按修改时间找最新。
    if index.exists():  # 已固定来源只读复用。
        record=read_json(index)  # 含文件指纹。
        return record  # 读取内容时另行校验。
    go,log=r_call(root,"export",{})  # 使用实际安装注释包完整导出。
    kegg={"names":download("list/pathway/hsa"),"links":download("link/pathway/hsa"),"release":download("info/pathway")}  # 保存真实发布说明和查询日期。
    go["annotations"]["KEGG"]=kegg_terms(kegg)  # 人类通路背景与原文一致。
    bundle={"schema_version":"A05.source.1","config":CONFIG,"annotations":go["annotations"],"metadata":go["metadata"],"kegg_sources":kegg,"export_log":log,"created_at":now()}  # 无结果参与来源选择。
    raw=gzip.compress(json.dumps(bundle,ensure_ascii=False,separators=(",",":")).encode(),mtime=0)  # 同内容稳定压缩。
    path=root/"references"/("enrichment_"+hashlib.sha256(raw).hexdigest()+".json.gz")  # 来源按完整内容指纹命名。
    with write_lock(root):  # 防止并发创建竞争索引。
        if index.exists():  # 其他运行先完成时使用明确既存版本。
            return read_json(index)  # 不覆盖其索引。
        if not path.exists():  # 不覆盖原件。
            with path.open("xb") as stream:  # 完整保存。
                stream.write(raw)  # 原始注释和响应一起保留。
        record=file_record(root,path,"annotation_source")  # 记录字节及指纹。
        write_json(index,record)  # 首次冻结来源版本。
    return record  # 后续重跑不静默重新下载改变结果。

def read_source(path):  # 计算只能用已归档完整注释。
    with gzip.open(path,"rt",encoding="utf-8") as stream:  # 解压源包。
        bundle=json.load(stream)  # 保留原始来源信息。
    require(bundle.get("schema_version")=="A05.source.1" and bundle.get("config")==CONFIG,"A05来源版本不一致")  # 不猜不同工具来源。
    require(bundle["annotations"]["KEGG"]==kegg_terms(bundle["kegg_sources"]),"KEGG派生注释与原响应不一致")  # 核对派生关系。
    return bundle  # 所有背景成员随包留存。

def evaluate(root, targets, source, hgnc_raw, purpose):  # 从真实交集与官方身份快照进行映射。
    hgnc={r["hgnc_id"]:r for r in csv.DictReader(io.StringIO(hgnc_raw.decode("utf-8-sig")),delimiter="\t")}  # 不用名称模糊匹配。
    mapped,issues=[],[]  # 身份失败不悄悄删除。
    for target in targets:  # 208项等实际输入全部保留。
        row=hgnc.get(target["target_id"],{})  # 与上游相同快照。
        gid=row.get("entrez_id","")  # 明确官方稳定编号。
        if row.get("symbol")==target["symbol"] and gid.isdigit():  # 唯一且名称一致才接入。
            mapped.append(dict(target,entrez_id=gid))  # 保存来源身份。
        else:  # 无法直接确认需人工处理。
            issues.append(dict(target,reason="HGNC快照缺少唯一一致的Entrez编号"))  # 不赋假编号。
    require(len({r["entrez_id"] for r in mapped})==len(mapped),"多个HGNC身份对应同一Entrez，须先核对")  # 不任取一个基因。
    result,log=r_call(root,"analyze",{"genes":[r["entrez_id"] for r in mapped],"annotations":source["annotations"]})  # 调用固定工具计算。
    tables={"identity_mapping":mapped,"identity_issues":issues,"group_summary":[]}  # 中文网页可集中复核。
    names={r["entrez_id"]:r["symbol"] for r in mapped}  # 展示用标准名，不改统计编号。
    for group in CONFIG["adjust_groups"]:  # 四类的分母分别保存。
        data=result[group]  # 包含所有实际检验和未检验。
        for key in ("all","significant","display","skipped"):  # 全表与图来自同一筛选结果。
            rows=data[key]  # JSON保留数组形式。
            for row in rows:  # 增加可读命中名，不改变工具原字段。
                if "geneID" in row:  # 未检验表没有命中列表。
                    row["gene_symbols"]="/".join(names.get(x,x) for x in row["geneID"].split("/"))  # 保留原Entrez字段。
            tables[group.lower()+"_"+key]=rows  # 结构固定。
        for key in ("background","effective","missing"):  # 全背景与实际分母留存。
            values=data[key] if isinstance(data[key],list) else [data[key]]  # 单元素R向量仍视为列表。
            tables[group.lower()+"_"+key]=[{"entrez_id":x,"symbol":names.get(x,"")} for x in values]  # 未注释与身份失败不同。
        tables["group_summary"].append({"group":group,"background_count":len(tables[group.lower()+"_background"]),"effective_count":len(tables[group.lower()+"_effective"]),"missing_count":len(tables[group.lower()+"_missing"]),"tested_count":len(data["all"]),"significant_count":len(data["significant"]),"display_count":len(data["display"])})  # 不机械沿用208分母。
    summary={"交集输入数":len(targets),"Entrez映射数":len(mapped),"身份待核验数":len(issues),"handoff_blocked":bool(issues),"analysis_purpose":purpose,"主显著性":"BH p.adjust < 0.05","说明":"探索性功能概览；富集不代表通路激活或疗效"}  # 用途继续传递。
    for row in tables["group_summary"]:  # 顶部只展示每类显著数量。
        summary[row["group"]+"显著条目数"]=row["significant_count"]  # 数值来自完整表。
    return summary,tables,log  # 日志单独保存。

def validator(root):  # 新结果必须能从原始来源复算。
    def check(run,summary,tables,anomalies,outcome):  # 与统一框架接口一致。
        require(run["config"]==CONFIG,"A05配置不一致")  # 不接受临时放宽阈值。
        home=within(root/"studies",run["study_id"])  # 只读本研究证据。
        parent=read_json(verified_file(home,run["inputs"]["parent_result"]))  # 绑定A03。
        require(parent["run_id"]==run["parent_runs"]["A03"],"A05上游不一致")  # 不误用PPI候选。
        source=read_source(verified_file(home,run["inputs"]["source_file"]))  # 核对来源指纹。
        expected=evaluate(root,parent["tables"]["intersection_targets"],source,verified_file(home,run["inputs"]["mapping_file"]).read_bytes(),parent["summary"].get("analysis_purpose","research"))  # 全过程重复计算。
        require((summary,tables)==expected[:2],"A05统计或表格与原始来源复算不一致")  # 不只检查表头。
        require(outcome==("success" if any(tables[g.lower()+"_significant"] for g in CONFIG["adjust_groups"]) else "empty"),"A05空结果状态不一致")  # 无显著可正常输出。
    return check  # 不自动批准。

def run_enrichment(workflow,sid,a03,a05,reason):  # 网页和程序使用同一入口。
    manifest=workflow.load(sid)  # 当前输入版本。
    require(manifest["current"].get("A03")==a03 and workflow.approved(manifest,a03),"请先通过当前A03交集")  # 不要求PPI先完成。
    parent=workflow.result(manifest,a03)  # 上游原始集合。
    a01=workflow.run(manifest,workflow.run(manifest,a03)["parent_runs"]["A01"])  # 从实际上游追溯HGNC快照。
    mapping=a01["inputs"]["mapping_file"]  # 复用相同归档文件，不按最新版猜。
    home=workflow.location(sid)  # 本研究包。
    reference=source_snapshot(workflow.root)  # 与研究独立、固定后可重复使用。
    path=verified_file(workflow.root,reference)  # 完整源文件核验。
    source=read_source(path)  # 完整注释。
    summary,tables,log=evaluate(workflow.root,parent["tables"]["intersection_targets"],source,verified_file(home,mapping).read_bytes(),parent["summary"].get("analysis_purpose","research"))  # 先计算再发布。
    check_result(summary,tables,[],"success" if any(tables[g.lower()+"_significant"] for g in CONFIG["adjust_groups"]) else "empty")  # 先核对统一表名与形状，失败不创建运行目录。
    with write_lock(workflow.root):  # 发布前核对版本没有变化。
        manifest=workflow.load(sid)  # 获取最新状态。
        require(manifest["current"].get("A03")==a03 and manifest["current"].get("A05","")==a05 and workflow.approved(manifest,a03),"上游或富集版本已改变，请刷新")  # 防止过期页面发布。
        archived=home/"raw"/path.name  # 研究包包含来源，独立可追溯。
        if not archived.exists():  # 不覆盖来源历史。
            with archived.open("xb") as stream:  # 一次完整归档。
                stream.write(path.read_bytes())  # 原字节保存。
        inputs={"parent_result":manifest["runs"][a03]["result_file"],"source_file":file_record(home,archived,"annotation_source"),"mapping_file":mapping}  # 上游和来源均有指纹。
        run=workflow._begin(manifest,"A05",inputs,dict(CONFIG),reason)  # 新运行默认未复核。
        from enrichment_plot import chart  # 图表只读display表。
        figures=[]  # 四类各两幅图。
        for group in CONFIG["adjust_groups"]:  # GO三类与KEGG分别出图。
            for kind in ("bar","bubble"):  # 柱状图和气泡图。
                target=home/"runs"/"A05"/run["run_id"]/(group+"_"+kind+".svg")  # 明确研究和运行归属。
                with target.open("x",encoding="utf-8") as stream:  # 不覆盖旧图。
                    stream.write(chart(tables[group.lower()+"_display"],group,kind))  # 同一统计结果生成。
                figures.append(file_record(home,target,"figure"))  # 图文件参与完整性检查。
        logfile=home/"runs"/"A05"/run["run_id"]/"R_log.txt"  # 运行日志归属明确。
        logfile.write_text(log,encoding="utf-8")  # 本次新目录中的日志。
        result=workflow._finish(manifest,run["run_id"],summary,tables,["背景为各类注释实际可分析的人类基因，未消除数据库选择偏倚。","GO三类分别BH校正，KEGG单独校正。","qvalue原字段仅保留，不作为主要筛选条件。"],"success" if any(tables[g.lower()+"_significant"] for g in CONFIG["adjust_groups"]) else "empty",sources=list(inputs.values()),figures=figures,attachments=[file_record(home,logfile,"log")])  # 独立复算后发布。
        workflow.save(manifest)  # 待用户总体复核。
    return result  # 不代选重点通路。

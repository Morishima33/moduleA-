"""A05第三版展示修订仅重绘并归档，不再计算ORA，也不覆盖已发布结果。"""

from copy import deepcopy
from pathlib import Path
from contracts import require
from storage import read_json, verified_file, write_json, file_record, new_id
from . import flow as runtime
from .compact_display import VERSION, RULE, build, translation_snapshot, metadata, english
from . import display_flow as previous

CONFIG = dict(runtime.CONFIG, display_version=VERSION, display_rule=RULE)


# 每个展示修订回指原统计运行及同一A03；来源文件仍有逐字节指纹。
def base_inputs(workflow, manifest, rid):
    run = workflow.run(manifest,rid)
    inputs = deepcopy(run["inputs"])
    if run["config"].get("display_version") in (previous.VERSION, VERSION):
        return inputs
    require(run["config"] == runtime.CONFIG, "不支持的A05统计版本")
    return dict(inputs, statistical_result=deepcopy(manifest["runs"][rid]["result_file"]), statistical_run=deepcopy(manifest["runs"][rid]["run_file"]))


# 自动接续只生成待确认的预览；不替用户排除、确认版式或批准模块。
def run_enrichment(workflow,sid,expected_a03,expected_a05,reason):
    baseline=runtime.run_enrichment(workflow,sid,expected_a03,expected_a05,reason)
    return prepare(workflow,sid,baseline["run_id"])


# 将本轮译名和候选理由独立归档；属于资料，不把病例编号写入通用代码。
def prepare(workflow, sid, rid, proposals=None):
    manifest = workflow.load(sid)
    require(manifest["current"].get("A05") == rid and workflow.active(manifest,rid), "A05已失效，请刷新")
    result = workflow.result(manifest,rid)
    require(not workflow.run(manifest,rid)["config"].get("display_version"), "本版展示已准备，请在页面确认或修订")
    inputs = base_inputs(workflow,manifest,rid)
    translations = translation_snapshot(result["tables"])
    source = {"version": VERSION, "translations": translations, "proposals": proposals or {}}
    return publish(workflow,sid,rid,inputs,source,{"base_run":rid,"excluded_ids":[],"exclusions_confirmed":False,"layout_confirmed":False,"decision_id":None},"按已确认A05图表要求生成真实研究预览")


# 来源材料通过Workflow公开入口归档，再作为新运行的不可变输入。
def publish(workflow,sid,rid,inputs,source,control,reason,decision_record=None):
    home = workflow.location(sid)
    record = workflow.archive_enrichment_display_source(sid,rid,source)
    inputs = dict(inputs,display_source=record)
    if decision_record:
        inputs["display_decision"] = decision_record
    base = read_json(verified_file(home,inputs["statistical_result"]))
    summary,tables = build(base,source["translations"],source["proposals"],control)
    anomalies = list(base["anomalies"]) + ["图表仅展示前列显著条目；人工排除不改变完整统计及BH校正。"]
    def figures_builder(folder):
        from .compact_figures import draw_all
        records=[]
        metadata=[]
        for group,pair in draw_all(tables,folder/"display").items():
            row={"group":group}
            for kind,path in pair.items():
                item=file_record(home,path,"figure")
                records.append(item)
                row.update({kind+"_"+k:item[k] for k in ("path","bytes","sha256")})
            metadata.append(row)
        tables["display_figures"]=metadata
        return records
    return workflow.publish_enrichment_display(sid,rid,inputs,dict(CONFIG),summary,tables,figures_builder,reason,anomalies)


# 两种人工确认都产生新展示版本，修改名单会撤销旧版式确认，不自动通过A05。
def apply_confirmation(workflow,sid,payload):
    decision,record = workflow.save_display_confirmation(sid,payload)
    manifest=workflow.load(sid)
    current=manifest["current"].get("A05")
    result=workflow.result(manifest,current)
    if (metadata(result["tables"]) or {}).get("decision_id") == decision["decision_id"]:
        return result
    require(current == payload["expected_a05"], "A05已改变，请刷新后重新确认")
    inputs=base_inputs(workflow,manifest,current)
    source=read_json(verified_file(workflow.location(sid),inputs["display_source"]))
    control={"base_run":decision["base_run"],"excluded_ids":decision["excluded_ids"],"exclusions_confirmed":True,"layout_confirmed":decision["layout_confirmed"],"decision_id":decision["decision_id"]}
    return publish(workflow,sid,current,inputs,source,control,"用户确认A05"+("展示范围" if decision["action"]=="exclusions" else "图表版式")+"："+decision["note"],record)


# 新图表规则核验来源、完整统计、排名、翻译及人工范围；旧A05仍按原R复算。
def validator(root):
    legacy_check=previous.validator(root)
    def check(run,summary,tables,anomalies,outcome):
        if run["config"].get("display_version") != VERSION:
            return legacy_check(run,summary,tables,anomalies,outcome)
        require(run["config"] == CONFIG, "A05展示规则被修改")
        home=Path(root)/"studies"/run["study_id"]
        base=read_json(verified_file(home,run["inputs"]["statistical_result"]))
        require(base["module_id"]=="A05" and base["study_id"]==run["study_id"],"统计来源归属不一致")
        base_run=read_json(verified_file(home,run["inputs"]["statistical_run"]))
        require(base_run["config"]==runtime.CONFIG and base_run["parent_runs"]==run["parent_runs"] and base_run["parent_review_ids"]==run["parent_review_ids"], "统计来源与当前批准A03不一致")
        source=read_json(verified_file(home,run["inputs"]["display_source"]))
        control=metadata(tables)
        require(control["base_run"] == base["run_id"] == base_run["run_id"], "展示未绑定原统计运行")
        decision_record=run["inputs"].get("display_decision")
        if decision_record:
            d=read_json(verified_file(home,decision_record))
            require(d["study_id"]==run["study_id"] and d["base_run"]==base["run_id"] and d["a03_run"]==run["parent_runs"]["A03"] and d["decision_id"]==control["decision_id"],"确认记录不是本次研究范围")
            require(d["excluded_ids"]==control["excluded_ids"] and d["exclusions_confirmed"]==control["exclusions_confirmed"] and d["layout_confirmed"]==control["layout_confirmed"],"确认范围与展示不一致")
        elif run["inputs"].get("display_layout_source"):
            old=read_json(verified_file(home,run["inputs"]["display_layout_source"]))
            old_meta=metadata(old["tables"])
            old_run=read_json(verified_file(home,run["inputs"]["display_layout_run"]))
            require(old["module_id"]=="A05" and old["study_id"]==run["study_id"] and old["run_id"]==old_run["run_id"] and old_run["config"] in (previous.CONFIG,CONFIG),"版式修订来源归属或规则不一致")
            require(old_run["parent_runs"]==run["parent_runs"] and old_run["parent_review_ids"]==run["parent_review_ids"] and old_run["inputs"]["statistical_result"]==run["inputs"]["statistical_result"],"版式修订上游或统计来源不一致")
            require(old_meta and old_meta["base_run"]==control["base_run"] and old_meta["excluded_ids"]==control["excluded_ids"] and old_meta["exclusions_confirmed"]==control["exclusions_confirmed"],"版式修订不能修改已确认展示范围")
            require(not control["layout_confirmed"] and control["decision_id"] is None,"版式修订不能代签新图")
        else:
            require(not control["exclusions_confirmed"] and not control["layout_confirmed"] and not control["excluded_ids"] and control["decision_id"] is None,"未获人工确认不能排除或采用版式")
        expected_summary,expected_tables=build(base,source["translations"],source["proposals"],control)
        actual=deepcopy(tables);figures=actual.pop("display_figures",[])
        require((summary,actual)==(expected_summary,expected_tables),"A05展示、排名或完整统计与来源不一致")
        require({r["group"] for r in figures}=={"go","kegg"},"A05缺少同源两幅图")
        for row in figures:
            for kind in ("png","svg"):
                verified_file(home,{k:row[kind+"_"+k] for k in ("path","bytes","sha256")})
        require(outcome==("success" if any(tables[g+"_significant"] for g in ("bp","cc","mf","kegg")) else "empty"),"展示修订不能改变空结果状态")
    return check

# 用户要求调整版式时复用当前归档统计、译名和名单；不执行R或冒充人工确认。
def revise_layout(workflow, sid, expected_a05):
    manifest=workflow.load(sid)
    require(manifest["current"].get("A05")==expected_a05 and workflow.active(manifest,expected_a05) and not manifest.get("trashed"),"当前A05已改变或研究只读，请刷新")
    result=workflow.result(manifest,expected_a05)
    old=metadata(result["tables"])
    require(old and old["version"] in (previous.VERSION,VERSION),"请先准备同源A05展示")
    inputs=base_inputs(workflow,manifest,expected_a05)
    inputs.pop("display_decision",None)
    inputs["display_layout_source"]=deepcopy(manifest["runs"][expected_a05]["result_file"])
    inputs["display_layout_run"]=deepcopy(manifest["runs"][expected_a05]["run_file"])
    source=read_json(verified_file(workflow.location(sid),inputs["display_source"]))
    source=dict(source,version=VERSION)
    control={"base_run":old["base_run"],"excluded_ids":old["excluded_ids"],"exclusions_confirmed":old["exclusions_confirmed"],"layout_confirmed":False,"decision_id":None}
    return publish(workflow,sid,expected_a05,inputs,source,control,"按用户要求精简核查清单、中英文分列及KEGG单蓝渐变；仅版式修订")


# 补齐当前缺译后追加展示修订；原统计、范围及历史译名快照不回写，新图仍待人工确认。
def refresh_translations(workflow, sid, expected_a05):
    manifest = workflow.load(sid)
    require(manifest["current"].get("A05") == expected_a05 and workflow.active(manifest, expected_a05) and not manifest.get("trashed"), "当前A05已改变或研究只读，请刷新")
    old = metadata(workflow.result(manifest, expected_a05)["tables"])
    require(old and old["version"] in (previous.VERSION, VERSION), "请先准备同源A05展示")
    inputs = base_inputs(workflow, manifest, expected_a05)
    inputs.pop("display_decision", None)
    inputs["display_layout_source"] = deepcopy(manifest["runs"][expected_a05]["result_file"])
    inputs["display_layout_run"] = deepcopy(manifest["runs"][expected_a05]["run_file"])
    home = workflow.location(sid)
    source = deepcopy(read_json(verified_file(home, inputs["display_source"])))
    original = deepcopy(source["translations"])
    base = read_json(verified_file(home, inputs["statistical_result"]))
    translations = translation_snapshot(base["tables"])
    english_by_id = {row["ID"]: english(row) for group in ("bp", "cc", "mf", "kegg") for row in base["tables"].get(group + "_significant", [])}
    # 只补已归档缺译项；新的词库不覆盖本轮已有核译，也不改统计表的英文名称。
    for tid in old["missing_translations"]:
        if tid in translations and translations[tid].get("english") == english_by_id.get(tid) and translations[tid].get("zh"):
            source["translations"][tid] = translations[tid]
    source["version"] = VERSION
    require(source["translations"] != original, "当前没有可补齐的译名，不生成重复版本")
    control = {"base_run": old["base_run"], "excluded_ids": old["excluded_ids"], "exclusions_confirmed": old["exclusions_confirmed"], "layout_confirmed": False, "decision_id": None}
    return publish(workflow, sid, expected_a05, inputs, source, control, "补齐同源GO/KEGG缺失中文译名并重绘；统计和展示范围保持，新版式仍待人工确认")

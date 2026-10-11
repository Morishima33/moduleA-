"""专业报告第18版：沿用第17版及临床简略版，仅更新已人工确认的A05段落。"""

from copy import deepcopy
from pathlib import Path
from types import FunctionType
from docx import Document
from contracts import require
from storage import verified_file, read_json
from science_modules.a05.display import VERSION, metadata
from science_modules.a05.report_section import add_section,validate_section
from . import circular_reports as previous

CONFIG=dict(previous.CONFIG,schema_version="A07.report.config.18",template_version="A07.double_report.18")


# 新模板绑定当前已确认的A05展示，完整统计和其他模块不改变。
def assemble_payload(workflow,manifest,parent_runs,heatmap_metadata_record=None):
    a05=workflow.result(manifest,parent_runs["A05"])
    meta=metadata(a05["tables"])
    require(meta and meta["exclusions_confirmed"] and meta["layout_confirmed"] and not meta["missing_translations"],"请先确认当前A05展示范围、中文和图表版式")
    payload=previous.assemble_payload(workflow,manifest,parent_runs,heatmap_metadata_record)
    payload["a05_display"]=deepcopy(a05)
    return payload


# 专业版A05章节完整替换，已确认A04表图、A06和临床版按原模板生成。
def build_detailed(payload,destination,root,revision):
    previous.build_detailed(payload,destination,root,revision)
    document=Document(destination)
    headings=[p for p in document.paragraphs if p.text=="5 GO与KEGG富集结果"]
    stops=[p for p in document.paragraphs if p.text=="6 分子对接结果"]
    require(len(headings)==len(stops)==1,"A05报告章节位置不唯一")
    node=headings[0]._p.getnext()
    while node is not stops[0]._p:
        following=node.getnext();node.getparent().remove(node);node=following
    before=list(document._element.body)
    add_section(document,payload["a05_display"]["tables"],root,include_heading=False)
    # 已认可的独立通路图仍按原规则纳入专业版，不因更换富集图表丢失。
    previous.legacy.add_selected_pathway(document,payload,root,previous.legacy._font)
    for node in list(document._element.body):
        if node not in before:stops[0]._p.addprevious(node)
    validate_section(document,payload["a05_display"]["tables"])
    document.save(destination)


# 报告目录为新修订；替换新生成的A05中间图为用户核查过的同源图片。
def generate_report_figures(directory,payload):
    paths=previous.generate_report_figures(directory,payload)
    home=Path(payload["_a05_home"])
    for group,name in (("go","05_GO富集三分类柱状图"),("kegg","06_KEGG富集气泡图")):
        row=next(r for r in payload["a05_display"]["tables"]["display_figures"] if r["group"]==group)
        for kind in ("png","svg"):
            source=verified_file(home,{k:row[kind+"_"+k] for k in ("path","bytes","sha256")})
            paths[name][kind].write_bytes(source.read_bytes())
    return paths


# 冻结报告内核在_begin时附加同源A05指纹输入，只有内核调用这个兼容视图。
class ReportView:
    def __init__(self,workflow):self.workflow=workflow
    def __getattr__(self,name):return getattr(self.workflow,name)
    def _begin(self,manifest,module_id,inputs,config,reason):
        inputs=dict(inputs,a05_display_source=deepcopy(manifest["runs"][manifest["current"]["A05"]]["result_file"]))
        return self.workflow._begin(manifest,module_id,inputs,config,reason)


# 复用冻结生成流程的局部函数绑定，不修改第17版模块全局或历史行为。
def run_reports(workflow,study_id,expected_a07,reason,**kwargs):
    manifest=workflow.load(study_id)
    def assemble(*args,**options):
        payload=assemble_payload(*args,**options)
        payload["_a05_home"]=str(workflow.location(study_id))
        return payload
    context=dict(vars(previous),CONFIG=CONFIG,assemble_payload=assemble,build_detailed=build_detailed,generate_report_figures=generate_report_figures)
    generate=FunctionType(previous.run_reports.__code__,context,previous.run_reports.__name__,previous.run_reports.__defaults__)
    return generate(ReportView(workflow),study_id,expected_a07,reason,**kwargs)


# 第18版继承原A03/A04检查并逐格核验A05；旧报告仍走原版本校验。
def validator(root):
    legacy_check=previous.validator(root)
    current=FunctionType(previous.validator.__code__,dict(vars(previous),CONFIG=CONFIG))(root)
    def check(run,summary,tables,anomalies,outcome):
        if run["config"].get("schema_version") != CONFIG["schema_version"]:
            return legacy_check(run,summary,tables,anomalies,outcome)
        current(run,summary,tables,anomalies,outcome)
        home=Path(root)/"studies"/run["study_id"]
        source=run["inputs"].get("a05_display_source")
        require(source and source["path"].endswith("/"+run["parent_runs"]["A05"]+"/result.json"),"报告缺少同源A05指纹输入")
        parent=read_json(verified_file(home,source))
        meta=metadata(parent["tables"])
        require(meta and meta["layout_confirmed"] and meta["exclusions_confirmed"],"报告未绑定已确认的A05展示")
        detail=next(r for r in tables["report_files"] if r["role"]=="detailed_report")
        validate_section(Document(verified_file(home,detail)),parent["tables"])
    return check

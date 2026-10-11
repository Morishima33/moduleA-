"""专业报告第20版：只为有效同源矩阵接入新热图，历史报告与临床模板保持。"""
from copy import deepcopy
from pathlib import Path
from types import FunctionType
from docx import Document
from contracts import require
from storage import verified_file,read_json,file_record
from modulea.core.docking_review import review_context
from science_modules.a06.matrix_display import matrix_view
from science_modules.a06.matrix_palette import VERSION
from science_modules.a06.matrix_exports import export_heatmap
from science_modules.a06.matrix_report_section import replace_section,validate_section
from . import compact_enrichment_reports as previous
from . import circular_reports as base
CONFIG=dict(previous.CONFIG,schema_version="A07.report.config.20",template_version="A07.double_report.20")

# 使用已批准A06的同源事实包，不为报告另算或填充评分。
def assemble_payload(workflow,manifest,parent_runs,heatmap_metadata_record=None):
    payload=previous.assemble_payload(workflow,manifest,parent_runs,heatmap_metadata_record)
    info=review_context(workflow,manifest);require(info and info["enabled"] and info["matrix"]["ready"] and info["matrix"]["display_version"]==VERSION,"本轮同源矩阵未就绪")
    require(parent_runs["A06"]==manifest["current"]["A06"],"报告不能借用其他A06批次")
    payload["a06_matrix"]=deepcopy(info["matrix"]);return payload

def generate_report_figures(directory,payload):
    paths=previous.generate_report_figures(directory,payload)
    matrix_paths=export_heatmap(payload["a06_matrix"],directory)
    payload["_a06_matrix_png"]=str(matrix_paths["png"]);return paths

def build_detailed(payload,destination,root,revision):
    previous.build_detailed(payload,destination,root,revision)
    document=Document(destination);notes=[p.text for p in document.paragraphs if p.text.startswith("单位：kcal/mol。")];replace_section(document,payload["a06_matrix"],payload["_a06_matrix_png"],payload.get("receptor_setup"),payload.get("receptor_limitations"),notes[-1] if notes else None);document.save(destination)

# 输入与导出图均独立索引；报告批准仍由原Workflow管理。
class ReportView(previous.ReportView):
    def _begin(self,manifest,module_id,inputs,config,reason):
        draft=self.workflow.current_docking_review(manifest)
        from science_modules.a06.plan_adapter import source_context
        context=source_context(self.workflow,manifest["study_id"],manifest)
        inputs=dict(inputs,a06_matrix_display_source=deepcopy(manifest["matrix_display_records"][-1]),a06_compound_review_source=deepcopy(manifest["docking_review_records"][-1]),a06_matrix_source_key=context["source_key"])
        return super()._begin(manifest,module_id,inputs,config,reason)
    def _finish(self,manifest,run_id,summary,tables,anomalies,outcome,**kwargs):
        home=self.workflow.location(manifest["study_id"]);folder=home/"reports"/("report_rev_"+run_id.removeprefix("run_"))/"figures"
        records=[file_record(home,folder/("A06_01_重点结合能热图."+kind),"a06_matrix_"+kind) for kind in ("svg","png")]
        kwargs["attachments"]=list(kwargs.get("attachments",[]))+records
        inputs=manifest["runs"][run_id]["inputs"];kwargs["sources"]=list(kwargs.get("sources",[]))+[inputs["a06_matrix_display_source"],inputs["a06_compound_review_source"]]
        return self.workflow._finish(manifest,run_id,summary,tables,anomalies,outcome,**kwargs)

def run_reports(workflow,study_id,expected_a07,reason,**kwargs):
    def assemble(*args,**options):
        payload=assemble_payload(*args,**options);payload["_a05_home"]=str(workflow.location(study_id));return payload
    scope=dict(vars(base),CONFIG=CONFIG,assemble_payload=assemble,build_detailed=build_detailed,generate_report_figures=generate_report_figures)
    generate=FunctionType(base.run_reports.__code__,scope,base.run_reports.__name__,base.run_reports.__defaults__)
    return generate(ReportView(workflow),study_id,expected_a07,reason,**kwargs)

# 新报告回读已归档配置和结果验证，历史报告继续使用自身版本。
def validator(root):
    old=previous.validator(root)
    baseline=FunctionType(previous.validator.__code__,dict(vars(previous),CONFIG=CONFIG))(root)
    def check(run,summary,tables,anomalies,outcome):
        if run["config"].get("schema_version")!=CONFIG["schema_version"]:return old(run,summary,tables,anomalies,outcome)
        baseline(run,summary,tables,anomalies,outcome);home=Path(root)/"studies"/run["study_id"]
        display=read_json(verified_file(home,run["inputs"]["a06_matrix_display_source"]));draft=read_json(verified_file(home,run["inputs"]["a06_compound_review_source"]));require(display["compound_review_id"]==draft["review_id"] and display["study_id"]==draft["study_id"]==run["study_id"] and display["source_key"]==run["inputs"]["a06_matrix_source_key"],"报告配色与名单来源不一致")
        from storage import read_json as load
        manifest=load(home/"manifest.json");a06=load(verified_file(home,manifest["runs"][run["parent_runs"]["A06"]]["result_file"]))
        matrix=matrix_view(display["config"],draft["compounds"],draft["receptors"],a06["docking_matrix_result"],a06["docking_matrix_preparation"],home,run["inputs"]["a06_matrix_source_key"])
        detail=next(r for r in tables["report_files"] if r["role"]=="detailed_report");validate_section(Document(verified_file(home,detail)),matrix)
    return check

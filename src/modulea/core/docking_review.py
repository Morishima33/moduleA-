"""研究级成分核查资料与矩阵展示配置：独立留存，不代替批准或计算。"""
from copy import deepcopy
from uuid import uuid4
from contracts import require
from storage import write_lock,write_json,read_json,verified_file,file_record,now
from science_modules.a06.matrix_display import check_display,matrix_view
from science_modules.a06.plan_adapter import source_context

SCHEMA="A06.compound_review.1"

# 补充草案绑定当前批准来源及候选分组；重签或换源都须重新核查。
class DockingReviewMixin:
    def docking_review_binding(self,manifest):
        binding=self.candidate_binding(manifest)
        group,_=self.candidate_record(manifest,binding)
        require(group is not None,"请先生成当前A/B受体候选")
        runs={k:manifest["current"].get(k) for k in ("A00","A01","A03","A04")}
        require(all(runs.values()),"成分核查来源不完整")
        reviews={}
        for module,rid in runs.items():
            require(self.approved(manifest,rid),"成分核查来源未批准："+module)
            reviews[module]=self.latest_review(manifest,self.run(manifest,rid)["artifact_id"])["review_id"]
        return {"study_id":manifest["study_id"],"source_runs":runs,"source_reviews":reviews,"candidate_group":group["group_id"]}

    # 只核验资料、排名和展示范围，不更改科学运行、名单批准或真实评分。
    def save_docking_review(self,sid,payload):
        with write_lock(self.root):
            manifest=self.load(sid);binding=self.docking_review_binding(manifest)
            require(payload.get("schema_version")==SCHEMA and payload.get("binding")==binding,"核查资料跨研究或来源已过期")
            require(payload.get("study_id")==sid and payload.get("execution_allowed") is False and payload.get("approval") is None,"资料不能代签或请求计算")
            rows=payload.get("compounds",[]);excluded=payload.get("excluded",[])
            ranking={r["compound_id"]:r for r in self.result(manifest,binding["source_runs"]["A03"])["tables"]["ranking"]}
            ids=[r["compound_id"] for r in rows]
            require(rows and len(ids)==len(set(ids)) and set(ids)<=set(ranking),"待核查成分重复或不属于当前A03")
            require(all(r.get("compound_id") in ranking and isinstance(r.get("reason_zh"),str) and r["reason_zh"].strip() for r in excluded),"待补资料须属于当前排名并有原因")
            require(not set(ids)&{r["compound_id"] for r in excluded},"待补对象不能同时加入本轮名单")
            for row in rows:
                original=ranking[row["compound_id"]]
                require(all(row.get(k)==original.get(k) for k in ("name","herbs","intersection_count","main_rank")),"核查草案改变了A03名称或排名")
                require(isinstance(row.get("identity_prechecked"),bool) and all(isinstance(row.get(k),str) and row[k] for k in ("name_zh","identity_state_zh","source_3d_state_zh","evidence_zh","manual_reason_zh")),"成分核查资料不完整")
            for record in payload.get("source_files",[]):verified_file(self.location(sid),record)
            cb=self.candidate_binding(manifest);group,_=self.candidate_record(manifest,cb)
            receptors=[{**r,"candidate_grade":r["evidence_group"]} for r in group["group_a"]+group["group_b"]]
            require(payload.get("receptors")==receptors,"核查草案改变了完整A/B受体")
            check_display(payload["display"],rows,receptors)
            data=deepcopy(payload);data.update(review_id="compound_review_"+uuid4().hex,created_at=now())
            # 全部组合独立留存；待核查不填NA或示例评分。
            data["planned_pairs"]=[{"compound_id":c["compound_id"],"target_id":t["target_id"],"candidate_grade":t["candidate_grade"],"state":"awaiting_confirmation_and_preparation","score":None} for c in rows for t in receptors]
            path=self.location(sid)/"decisions/A06_compound_review"/(data["review_id"]+".json")
            write_json(path,data);manifest.setdefault("docking_review_records",[]).append(file_record(self.location(sid),path,"docking_compound_review"));self.save(manifest)
            return data

    # 最新资料可以失效，不能退回更早草案或借用别的研究。
    def current_docking_review(self,manifest):
        records=manifest.get("docking_review_records",[])
        if not records:return None
        data=read_json(verified_file(self.location(manifest["study_id"]),records[-1]))
        require(data.get("schema_version")==SCHEMA and data.get("study_id")==manifest["study_id"],"核查资料身份不符")
        require(data["binding"]==self.docking_review_binding(manifest),"核查资料来源已改变，请重新核查")
        for record in data.get("source_files",[]):verified_file(self.location(manifest["study_id"]),record)
        return data

# 当前页始终展示待核查草案；计算图件只读取匹配且有效的新结果契约。
def review_context(workflow,manifest,historical=False):
    if historical or not manifest.get("docking_review_records"):return None
    try:
        data=workflow.current_docking_review(manifest)
        config=data["display"]
        if manifest.get("matrix_display_records"):
            ctx=source_context(workflow,manifest["study_id"],manifest)
            display=workflow.current_matrix_display(manifest,ctx,data)
            require(display is not None,"矩阵展示配色来源已改变，请重新绑定")
            config=display["config"]
        matrix=matrix_view(config,data["compounds"],data["receptors"])
        selected=manifest["current"].get("A03_SELECT")
        if selected and workflow.approved(manifest,selected):
            ctx=source_context(workflow,manifest["study_id"],manifest)
            rid=manifest["current"].get("A06")
            if rid and workflow.active(manifest,rid):
                result=workflow.result(manifest,rid)
                # 新版结果须显式归档准备和结果包；旧评分不作为缺省回退。
                packet=result.get("docking_matrix_result")
                prep=result.get("docking_matrix_preparation")
                if packet is not None:
                    require([r["compound_id"] for r in ctx["compounds"]]==[r["compound_id"] for r in data["compounds"]],"批准成分与展示草案不符")
                    matrix=matrix_view(config,data["compounds"],data["receptors"],packet,prep,workflow.location(manifest["study_id"]),ctx["source_key"])
        return {"enabled":True,"reason_zh":"","review_id":data["review_id"],"proposal":data,"matrix":matrix}
    except (ValueError,KeyError,TypeError) as error:
        return {"enabled":False,"reason_zh":str(error),"review_id":None,"proposal":None,"matrix":None}

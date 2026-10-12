"""A06两遍人工方案与成分选择：只经公开Workflow方法留存，不执行科学准备。"""
from copy import deepcopy
from uuid import uuid4
import base64,re
from contracts import require,safe_id
from storage import write_lock,write_json,read_json,verified_file,file_record,now
from .docking_workflow import DockingWorkflow
from .docking_review import DockingReviewMixin
from .receptor_review import ReceptorReviewMixin
from .two_pass_draft import TwoPassDraftMixin
from .two_pass_confirmation import confirmation_summary
from .source_review import SourceReviewMixin, merged_metadata, source_row_checks, source_compound_issues
from science_modules.a06.plan_adapter import source_context
from science_modules.a06.two_pass_plan import SCHEMA,blank,row_check,validate
from science_modules.a06.two_pass import POLICY,CONFIDENCE

# 与旧方案并存的新版本，唯一研究索引及锁沿用原Workflow。
class TwoPassWorkflow(SourceReviewMixin,TwoPassDraftMixin,ReceptorReviewMixin,DockingReviewMixin,DockingWorkflow):
    def selection_binding(self,sid):
        manifest=self.load(sid);a03=manifest["current"].get("A03")
        require(not manifest.get("trashed") and a03 and self.approved(manifest,a03),"请先通过当前A03；回收站只读")
        return {"expected_a03":a03,"expected_select":manifest["current"].get("A03_SELECT","")}

    # 只检查来源和请求格式；科学资格交给后台既有选择内核。
    def validate_selection_request(self,sid,payload):
        binding=self.selection_binding(sid)
        require(isinstance(payload,dict) and set(payload) in ({"expected_a03","expected_select","selected","manual_supplements","reviewer","reason","confirmed"},{"expected_a03","expected_select","selected","manual_supplements","reviewer","reason","confirmed","expected_docking_review"}),"成分选择请求字段不完整或含未授权参数")
        require(all(payload.get(k)==v for k,v in binding.items()),"成分选择版本已改变，请刷新")
        require(payload.get("confirmed") is True,"请明确确认成分身份")
        require(isinstance(payload.get("selected"),list) and payload["selected"] and all(isinstance(x,str) for x in payload["selected"]) and len(set(payload["selected"]))==len(payload["selected"]),"请选择不重复的成分编号")
        require(all(isinstance(payload.get(k),str) and 0<len(payload[k].strip())<=2000 for k in ("reviewer","reason")),"请填写核验人与成分选择依据")
        require(isinstance(payload.get("manual_supplements",{}),dict),"人工补充理由须逐项填写")
        # 当前草案版本及身份预核对同时保护API和后台任务，不能凭勾选绕过缺口。
        draft=self.current_docking_review(self.load(sid))
        if draft:
            require(payload.get("expected_docking_review")==draft["review_id"],"成分核查草案已改变，请刷新")
            blocked={r["compound_id"] for r in draft["compounds"] if not r["identity_prechecked"]}
            blocked.update(r["compound_id"] for r in draft["excluded"])
            require(not set(payload["selected"])&blocked,"所选成分存在身份或来源待补，不能确认为已核对")
        return binding

    # 仅生成待复核选择；既有模块复核栏负责独立批准。
    def save_selection(self,sid,payload):
        self.validate_selection_request(sid,payload)
        from intersection_flow import run_selection
        return run_selection(self,sid,payload["expected_a03"],payload["expected_select"],payload["selected"],payload["reviewer"],payload["reason"],payload["confirmed"],payload.get("manual_supplements") or None,request_guard=lambda:self.validate_selection_request(sid,payload))

    # 新人工方案只追加版本，历史保存与本研究引用都逐字节核对。
    def latest_two_pass(self,manifest,context):
        for record in reversed(manifest.get("two_pass_plan_records",[])):
            data=read_json(verified_file(self.location(manifest["study_id"]),record))
            require(data["study_id"]==manifest["study_id"] and data["schema_version"]==SCHEMA,"两遍方案身份或版本不符")
            if data["source_key"]==context["source_key"]:
                source=self.current_source_review(manifest,context)
                if source and data.get("source_review_id")!=source["review_id"]:continue
                return data,record
        return None,None

    # 手工提供来源三维SDF，原件单独归档；这里不宣称化学身份已通过。
    def materials(self,manifest,context):
        rows=[]
        for record in manifest.get("docking_material_records",[]):
            data=read_json(verified_file(self.location(manifest["study_id"]),record))
            require(data["study_id"]==manifest["study_id"],"三维资料不属于当前研究")
            verified_file(self.location(manifest["study_id"]),data["file"])
            if data["source_key"]==context["source_key"]:rows.append(data)
        return rows

    def save_material(self,sid,payload):
        with write_lock(self.root):
            manifest=self.load(sid);context=source_context(self,sid,manifest)
            require(payload.get("expected_source")==context["source_key"],"上传来源版本已改变，请刷新")
            require(payload.get("compound_id") in {r["compound_id"] for r in context["compounds"]},"上传成分不在当前已批准名单")
            require(re.fullmatch(r"[0-9]+",str(payload.get("cid",""))) and int(payload["cid"])>0,"请明确上传来源的CID")
            require(isinstance(payload.get("name"),str) and payload["name"].lower().endswith(".sdf"),"仅支持来源SDF三维文件")
            try:raw=base64.b64decode(payload.get("content_base64",""),validate=True);text=raw.decode("utf-8")
            except (ValueError,UnicodeError,TypeError):raise ValueError("SDF内容编码无效")
            require(0<len(raw)<=600000 and "$$$$" in text and "M  END" in text,"SDF为空、过大或格式不完整")
            # 保留原字节，准备阶段再验证CID、立体身份与三维坐标。
            mid="material_"+uuid4().hex;folder=self.location(sid)/"raw/A06_materials"/mid;folder.mkdir(parents=True)
            path=folder/"source.sdf";path.write_bytes(raw)
            data={"schema_version":"A06.source_3d.material.1","study_id":sid,"material_id":mid,"source_key":context["source_key"],"compound_id":payload["compound_id"],"cid":str(payload["cid"]),"name":payload["name"],"file":file_record(self.location(sid),path,"source_3d_sdf"),"state_zh":"已归档，化学及三维身份待准备阶段核验","created_at":now()}
            record_path=folder/"material.json";write_json(record_path,data);manifest.setdefault("docking_material_records",[]).append(file_record(self.location(sid),record_path,"docking_material"));self.save(manifest)
            return data

    # 草案校验不写文件，服务端返回可勾选资格，防止前端推算通过。
    def check_two_pass(self,sid,payload):
        manifest=self.load(sid);context=source_context(self,sid,manifest)
        require(payload.get("expected_source")==context["source_key"],"两遍方案来源已改变，请刷新")
        source=self.guard_source_review(manifest,context,payload)
        plan=payload.get("plan",{})
        require(isinstance(plan,dict),"方案须为对象")
        rows=plan.get("receptors",[])
        require(isinstance(rows,list) and all(isinstance(r,dict) for r in rows) and [r.get("target_id") for r in rows]==[r["target_id"] for r in context["receptors"]],"草案受体范围不符")
        checks=[{"target_id":r["target_id"],**row_check(r,s,context)} for r,s in zip(rows,context["receptors"])]
        checks=source_row_checks(source,plan,checks)
        summary=confirmation_summary(plan,context,checks,self.materials(manifest,context),self.current_receptor_review(manifest,context))
        issues=source_compound_issues(source,plan,self.materials(manifest,context))
        summary["pending"].extend(issues);summary["ready"]=summary["ready"] and not issues
        return {"items":checks,"confirmation":summary,"calculation_started":False}

    # 保存完整名单需要明确确认；不创建运行、不审批、不解除计算关闭状态。
    def save_two_pass(self,sid,payload):
        with write_lock(self.root):
            manifest=self.load(sid);context=source_context(self,sid,manifest)
            require(set(payload)-{"expected_draft_id","expected_source_review_id"}=={"expected_source","expected_plan_id","plan_id","confirmed_target_ids","reviewer","note","confirmed","plan"},"方案请求字段不完整或含未授权执行参数")
            self.guard_source_review(manifest,context,payload)
            require(payload["expected_source"]==context["source_key"],"两遍方案来源已改变，请刷新")
            safe_id(payload["plan_id"],"plan")
            require(payload["confirmed"] is True and all(isinstance(payload[k],str) and 0<len(payload[k].strip())<=2000 for k in ("reviewer","note")),"请明确确认并填写核验人与依据")
            for record in manifest.get("two_pass_plan_records",[]):
                data=read_json(verified_file(self.location(sid),record))
                if data["plan_id"]==payload["plan_id"]:
                    require(data["request"]==payload,"重试方案内容不一致");return data
            latest,_=self.latest_two_pass(manifest,context)
            require(payload["expected_plan_id"]==(latest["plan_id"] if latest else None),"两遍方案已更新，请刷新")
            draft=self.current_two_pass_draft(manifest,context,latest)
            require(draft is None or payload.get("expected_draft_id")==draft["draft_id"],"核查草案已改变，请刷新后确认完整方案")
            plan=validate(payload["plan"],context,payload["confirmed_target_ids"],self.materials(manifest,context))
            verified=self.check_two_pass(sid,payload)
            require(verified["confirmation"]["ready"],"来源原件选择未核对或已改变")
            data={"source_review_id":payload.get("expected_source_review_id"),"schema_version":SCHEMA,"policy_version":POLICY,"study_id":sid,"plan_id":payload["plan_id"],"source_key":context["source_key"],"source_binding":{k:deepcopy(v) for k,v in context.items() if k not in ("receptors","compounds")},"plan":plan,"execution_allowed":False,"status_zh":"方案已确认；尚未实际准备或质控","reviewer":payload["reviewer"].strip(),"note":payload["note"].strip(),"created_at":now(),"request":deepcopy(payload)}
            path=self.location(sid)/"decisions/A06_two_pass"/(data["plan_id"]+".json");write_json(path,data)
            manifest.setdefault("two_pass_plan_records",[]).append(file_record(self.location(sid),path,"two_pass_plan"));self.save(manifest)
            return data

# 成分页只展示当前A03归档，旧选择单独对照；不会自动选中旧版本。
def selection_context(workflow,manifest,historical=False,busy=False):
    if historical:return None
    try:
        binding=workflow.selection_binding(manifest["study_id"]);draft=workflow.current_docking_review(manifest)
        reason="请等待当前研究后台任务结束" if busy else ""
    except ValueError as error:return {"enabled":False,"disabled_reason_zh":str(error),"rows":[]}
    result=workflow.result(manifest,binding["expected_a03"]);tables=result["tables"]
    suggested={r["compound_id"]:r.get("group","") for r in tables.get("suggestions",[])}
    rows=[{**r,"suggestion_zh":suggested.get(r["compound_id"],"需逐项说明人工补充理由"),"eligible":bool(r.get("in_network"))} for r in tables.get("ranking",[])]
    # 身份待补不可通过批量选择；三维资料缺失另外提示，不冒充准备完成。
    if draft:
        pending={r["compound_id"] for r in draft["compounds"] if not r["identity_prechecked"]}|{r["compound_id"] for r in draft["excluded"]}
        for row in rows:
            if row["compound_id"] in pending:row.update(eligible=False,suggestion_zh="身份或来源待补，暂不能确认")
    old=workflow.result(manifest,binding["expected_select"]) if binding["expected_select"] else None
    current=bool(old and workflow.active(manifest,binding["expected_select"]))
    # 旧展示档缺编号时保持只读；不能根据成分名称猜测选择身份。
    previous=(old or {}).get("tables",{}).get("selected",[])
    if current and any(not isinstance(r.get("compound_id"),str) or not r["compound_id"] for r in previous):
        reason="当前选择归档缺少成分编号，不能按名称确认身份；请核查来源资料"
    return {**binding,"enabled":not reason,"disabled_reason_zh":reason,"rows":rows,"current_selected":[r["compound_id"] for r in previous] if current and not reason else [],"previous_rows":(old or {}).get("tables",{}).get("selected",[]),"previous_active":current,"rule_zh":"沿用当前A03候选、边界并列、药味代表及逐项人工补充规则；保存后仍须独立复核。"}

# A06顶部核查入口，当前研究无来源时明确提示成分关口而不借用旧结果。
def preparation_context(workflow,manifest,historical=False,busy=False):
    if historical:return None
    try:context=source_context(workflow,manifest["study_id"],manifest)
    except ValueError as error:return {"enabled":False,"disabled_reason_zh":str(error),"policy_version":POLICY,"execution_allowed":False}
    latest,_=workflow.latest_two_pass(manifest,context);draft=workflow.current_two_pass_draft(manifest,context,latest);plan=draft["plan"] if draft else latest["plan"] if latest else blank(context)
    checks=[{"target_id":r["target_id"],**row_check(r,s,context)} for r,s in zip(plan["receptors"],context["receptors"])]
    source=workflow.current_source_review(manifest,context)
    checks=source_row_checks(source,plan,checks)
    metadata=merged_metadata(workflow.current_receptor_review(manifest,context),source);materials=workflow.materials(manifest,context)
    confirmation=confirmation_summary(plan,context,checks,materials,metadata)
    issues=source_compound_issues(source,plan,materials)
    confirmation["pending"].extend(issues);confirmation["ready"]=confirmation["ready"] and not issues
    return {"enabled":not busy,"disabled_reason_zh":"请等待当前研究后台任务结束" if busy else "","expected_source":context["source_key"],"expected_plan_id":latest["plan_id"] if latest else None,"expected_draft_id":draft["draft_id"] if draft else None,"draft":{k:deepcopy(draft[k]) for k in ("draft_id","created_at","reviewer","note","checked_target_ids")} if draft else None,"policy_version":POLICY,"confidence_thresholds":CONFIDENCE,"context":context,"plan":plan,"checks":checks,"latest":latest,"source_review":source,"expected_source_review_id":source["review_id"] if source else None,"metadata_review":metadata,"materials":materials,"confirmation":confirmation,"planned_pair_count":len(context["receptors"])*len(context["compounds"]),"execution_allowed":False,"status_zh":"核查草案已保存，尚未确认完整方案" if draft else "方案已确认，仍待准备与质控" if latest else "待核对成分及受体结构方案"}

"""候选分组只追加独立归档，不改A04/A05科学产物或模块审批。"""
from contracts import require, safe_id
from storage import write_lock, write_json, read_json, verified_file, file_record, now
from .enrichment_workflow import EnrichmentWorkflow
from science_modules.a06.candidates import VERSION

# 候选写入通过Workflow公开方法和研究锁，唯一状态来源保持不变。
class DockingWorkflow(EnrichmentWorkflow):
    def candidate_binding(self,manifest):
        a03,a04=(manifest["current"].get(m) for m in ("A03","A04"))
        require(not manifest.get("trashed") and a03 and a04,"请使用当前研究的已通过A03与A04；回收站只读")
        require(self.approved(manifest,a03) and self.approved(manifest,a04),"请先通过当前A03与A04")
        run=self.run(manifest,a04)
        require(run["parent_runs"].get("A03")==a03,"A04不属于当前交集")
        tables=self.result(manifest,a04)["tables"]
        require(all(isinstance(tables.get(k),list) for k in ("degree_round2","degree_top10","bc_cc_top15")),"当前A04没有双分支第二轮归档，不能套用新版候选规则")
        review=self.latest_review(manifest,run["artifact_id"])
        return {"expected_a03":a03,"expected_a04":a04,"expected_a04_review":review["review_id"]}

    # 页面和子进程两次核对上游与复核版本，拒绝跨研究及过期任务。
    def validate_candidates(self,sid,payload,manifest=None):
        manifest=manifest or self.load(sid)
        binding=self.candidate_binding(manifest)
        require(all(payload.get(k)==v for k,v in binding.items()),"A03、A04或A04复核已改变，请刷新")
        require(isinstance(payload.get("reason"),str) and 0<len(payload["reason"].strip())<=2000,"请填写候选分组原因")
        return manifest,binding

    # 当前方案按完整来源键绑定；同运行重签、更换成分或更新分组都会使旧方案失效。
    def current_docking_plan(self,manifest,context):
        from science_modules.a06.plan_adapter import SCHEMA
        for record in reversed(manifest.get("docking_plan_records",[])):
            data=read_json(verified_file(self.location(manifest["study_id"]),record))
            require(data.get("study_id")==manifest["study_id"] and data.get("schema_version")==SCHEMA,"方案身份或版本不一致")
            if data["source_key"]==context["source_key"]:
                return data,record
        return None,None

    # 只追加人工方案，不运行、下载、批准或改变任何模块当前指针。
    def save_docking_plan(self,sid,payload):
        from science_modules.a06.plan_adapter import source_context,validate_plan,plan_metadata
        with write_lock(self.root):
            require(isinstance(payload,dict) and set(payload)=={"expected_source","expected_plan_id","plan_id","confirmed","reviewer","note","plan"},"方案请求字段不完整或含未授权运行参数")
            manifest=self.load(sid)
            context=source_context(self,sid,manifest)
            require(payload.get("expected_source")==context["source_key"],"方案上游或候选分组已改变，请刷新")
            require(payload.get("confirmed") is True,"请明确确认本次结构方案")
            require(all(isinstance(payload.get(k),str) and 0<len(payload[k].strip())<=2000 for k in ("reviewer","note")),"请填写实际核验人与结构选择依据")
            safe_id(payload.get("plan_id"),"plan")
            for record in manifest.get("docking_plan_records",[]):
                saved=read_json(verified_file(self.location(sid),record))
                if saved["plan_id"]==payload["plan_id"]:
                    require(saved["request"]==payload,"重试方案内容不一致")
                    return saved,record
            previous,_=self.current_docking_plan(manifest,context)
            require((previous["plan_id"] if previous else None)==payload.get("expected_plan_id"),"方案已更新，请刷新")
            data={**plan_metadata(context),"plan":validate_plan(payload.get("plan"),context),
                  "study_id":sid,"plan_id":payload["plan_id"],"created_at":now(),
                  "reviewer":payload["reviewer"].strip(),"note":payload["note"].strip(),"request":dict(payload)}
            path=self.location(sid)/"decisions/A06_plans"/(data["plan_id"]+".json")
            write_json(path,data)
            record=file_record(self.location(sid),path,"docking_two_tier_plan")
            manifest.setdefault("docking_plan_records",[]).append(record)
            self.save(manifest)
            return data,record

    # 只有指纹核验且绑定当前批准结果的记录才展示；旧分组仍可追溯。
    def candidate_record(self,manifest,binding):
        for record in reversed(manifest.get("docking_candidate_records",[])):
            data=read_json(verified_file(self.location(manifest["study_id"]),record))
            require(data.get("study_id")==manifest["study_id"] and data.get("schema_version")==VERSION,"候选归属或版本不一致")
            if data["source_runs"]=={"A03":binding["expected_a03"],"A04":binding["expected_a04"]} and data["source_review"]==binding["expected_a04_review"]:
                return data,record
        return None,None

    # 锁内重新读取归档并生成小规模名单；失败重试沿用相同请求。
    def generate_candidates(self,sid,payload):
        from science_modules.a06.candidates import build
        with write_lock(self.root):
            manifest,binding=self.validate_candidates(sid,payload)
            safe_id(payload["group_id"],"group")
            for record in manifest.get("docking_candidate_records",[]):
                saved=read_json(verified_file(self.location(sid),record))
                if saved["group_id"]==payload["group_id"]:
                    require(saved["request"]==payload,"重试候选请求不一致")
                    return saved
            result=self.result(manifest,binding["expected_a04"])
            data={**build(result["tables"]),"group_id":payload["group_id"],"study_id":sid,"created_at":now(),
                  "source_runs":{"A03":binding["expected_a03"],"A04":binding["expected_a04"]},
                  "source_review":binding["expected_a04_review"],"source_result":manifest["runs"][binding["expected_a04"]]["result_file"],
                  "request":dict(payload)}
            path=self.location(sid)/"decisions/A06_candidates"/(data["group_id"]+".json")
            write_json(path,data)
            manifest.setdefault("docking_candidate_records",[]).append(file_record(self.location(sid),path,"docking_candidates"))
            self.save(manifest)
            return data

# 展示只读归档，不现场计算，不借用历史版本；结构准备状态与分组分开。
def candidate_context(workflow,manifest,historical=False,busy=False):
    if historical:
        return None
    binding={"expected_a03":manifest["current"].get("A03",""),"expected_a04":manifest["current"].get("A04",""),"expected_a04_review":""}
    data=None
    try:
        binding=workflow.candidate_binding(manifest)
        data,_=workflow.candidate_record(manifest,binding)
        reason="" if not busy else "请等待当前研究后台任务结束"
    except ValueError as error:
        reason=str(error)
    selection=manifest["current"].get("A03_SELECT")
    ready=bool(selection and workflow.approved(manifest,selection))
    return {**binding,"enabled":not reason,"disabled_reason_zh":reason,"data":data,
            "preparation_note_zh":"候选成分已通过；受体结构、搜索盒与重对接质控待独立核查。" if ready else "A03对接成分名单需重新选择并复核；旧A06准备及对接结果保留为历史，不作为本轮结果。"}

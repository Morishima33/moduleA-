"""A06未完成核查进度独立暂存：只验证范围与数据形状，不代签或生成质控事实。"""
from copy import deepcopy
from uuid import uuid4
import json
from contracts import require,safe_id
from storage import write_lock,write_json,read_json,verified_file,file_record,now
from science_modules.a06.plan_adapter import source_context
from science_modules.a06.two_pass_plan import blank,row_check
from science_modules.a06.two_pass import POLICY
from .source_review import source_row_checks
SCHEMA="A06.two_pass.draft.1"

# 草案允许缺字段；禁用未知执行/评分字段，真实完整校验仍使用既有科学契约。
def validate_partial(plan,context):
    empty=blank(context)
    require(isinstance(plan,dict) and set(plan)==set(empty) and plan["policy_version"]==POLICY,"草案字段或规则版本不符")
    require(all(isinstance(plan[k],str) and len(plan[k])<=2000 for k in ("package_id","pymol_executable")),"草案任务/工具字段格式无效")
    for key,id_key in (("compounds","compound_id"),("receptors","target_id")):
        rows=plan[key];sources=context[key]
        require(isinstance(rows,list) and all(isinstance(r,dict) for r in rows) and [r.get(id_key) for r in rows]==[r[id_key] for r in sources],"草案须保留完整当前"+key+"名单")
        for row,source in zip(rows,sources):
            if key=="compounds":
                require(set(row)<={"compound_id","status","reason","cid","protonation_policy","material_id"} and {"compound_id","status","reason"}<=set(row) and row["status"] in (None,"use","unavailable"),"成分草案字段无效")
                require(all(isinstance(v,str) and len(v)<=2000 for k,v in row.items() if k!="status"),"成分草案文字字段格式无效")
            else:
                require(set(row)==set(empty["receptors"][0]) and all(row[k]==source[k] for k in ("target_id","symbol","candidate_grade")),"受体草案身份或A/B范围改变")
                require(isinstance(row["unavailable"],bool) and all(isinstance(row[k],str) and len(row[k])<=2000 for k in ("first_reason","second_reason","reason")),"受体草案说明格式无效")
                for number,key_spec in enumerate(("first","second"),1):
                    spec=row[key_spec]
                    if spec is None:continue
                    allowed={"source_type","uniprot","chains","pocket","pdb_id","model_id","sequence_start","sequence_end","altloc","reference_code","reference_chain","reference_sequence"}
                    require(isinstance(spec,dict) and set(spec)<=allowed and spec.get("source_type") in (("experimental",) if number==1 else ("experimental","alphafold")),"结构草案含未知来源或计算字段")
                    for k,v in spec.items():
                        if k=="chains":require(isinstance(v,list) and len(v)<=32 and all(isinstance(c,str) and 0<len(c)<=16 for c in v),"草案链格式无效")
                        elif k in ("sequence_start","sequence_end"):require(v is None or (isinstance(v,int) and not isinstance(v,bool) and v>0),"草案序列范围格式无效")
                        else:require(v is None or (isinstance(v,str) and len(v)<=2000),"结构草案文字字段无效")
    return deepcopy(plan)

# Workflow公开写方法追加草案；批准和运行索引完全不改。
class TwoPassDraftMixin:
    def current_two_pass_draft(self,manifest,context,latest):
        records=manifest.get("two_pass_draft_records",[])
        if not records:return None
        data=read_json(verified_file(self.location(manifest["study_id"]),records[-1]))
        require(data.get("schema_version")==SCHEMA and data.get("study_id")==manifest["study_id"] and data.get("execution_allowed") is False and data.get("approval") is None,"核查草案身份或版本无效")
        if data["source_key"]!=context["source_key"] or data["base_plan_id"]!=(latest["plan_id"] if latest else None):return None
        source=self.current_source_review(manifest,context)
        if source and data.get("source_review_id")!=source["review_id"]:return None
        if data.get("metadata_source"):verified_file(self.location(manifest["study_id"]),data["metadata_source"])
        validate_partial(data["plan"],context)
        return data

    # 已过期页面不能覆盖新版；确认勾选只保留已填写且校验合格的人工行。
    def validate_two_pass_draft_request(self,sid,payload):
        manifest=self.load(sid);context=source_context(self,sid,manifest)
        require(isinstance(payload,dict) and set(payload)-{"expected_source_review_id"}=={"expected_source","expected_plan_id","expected_draft_id","draft_id","plan","checked_target_ids","reviewer","note"},"草案请求字段不完整或含执行参数")
        require(payload["expected_source"]==context["source_key"],"核查草案来源已改变，请刷新")
        source=self.guard_source_review(manifest,context,payload)
        safe_id(payload["draft_id"],"draft")
        require(all(isinstance(payload[k],str) and len(payload[k])<=2000 for k in ("reviewer","note")),"草案核验文字格式无效")
        plan=validate_partial(payload["plan"],context);checked=payload["checked_target_ids"]
        facts=[{"target_id":r["target_id"],**row_check(r,s,context)} for r,s in zip(plan["receptors"],context["receptors"])]
        eligible={r["target_id"] for r in source_row_checks(source,plan,facts) if r["valid"]}
        require(isinstance(checked,list) and all(isinstance(x,str) for x in checked) and len(checked)==len(set(checked)) and set(checked)<=eligible,"草案勾选含未填齐或越界的受体")
        require(len(json.dumps(payload,ensure_ascii=False))<=200000,"草案过大")
        latest,_=self.latest_two_pass(manifest,context)
        require(payload["expected_plan_id"]==(latest["plan_id"] if latest else None),"完整方案已改变，请刷新后保存草案")
        for record in manifest.get("two_pass_draft_records",[]):
            data=read_json(verified_file(self.location(sid),record))
            if data["draft_id"]==payload["draft_id"]:
                require(data["request"]==payload,"重试草案内容不一致");return manifest,context,plan,data
        current=self.current_two_pass_draft(manifest,context,latest)
        require(payload["expected_draft_id"]==(current["draft_id"] if current else None),"核查草案已更新，请刷新后核对")
        return manifest,context,plan,None

    # 与完整方案分目录保存，反复保存相同内容不生成多余版本。
    def save_two_pass_draft(self,sid,payload):
        with write_lock(self.root):
            manifest,context,plan,retry=self.validate_two_pass_draft_request(sid,payload)
            if retry:return retry
            latest,_=self.latest_two_pass(manifest,context);current=self.current_two_pass_draft(manifest,context,latest)
            if current and all(current[k]==payload[k] for k in ("plan","checked_target_ids","reviewer","note")):return current
            data={"source_review_id":payload.get("expected_source_review_id"),"schema_version":SCHEMA,"study_id":sid,"draft_id":payload["draft_id"],"source_key":context["source_key"],"base_plan_id":payload["expected_plan_id"],"metadata_source":deepcopy(manifest.get("receptor_review_records",[])[-1]) if manifest.get("receptor_review_records") else None,"plan":plan,"checked_target_ids":deepcopy(payload["checked_target_ids"]),"reviewer":payload["reviewer"],"note":payload["note"],"approval":None,"execution_allowed":False,"created_at":now(),"request":deepcopy(payload)}
            path=self.location(sid)/"decisions/A06_two_pass_draft"/(data["draft_id"]+".json");write_json(path,data)
            manifest.setdefault("two_pass_draft_records",[]).append(file_record(self.location(sid),path,"two_pass_draft"));self.save(manifest)
            return data

"""A06官方结构摘要核查包：独立归档，不能替代结构准备、方案确认或结果批准。"""
from copy import deepcopy
from uuid import uuid4
from urllib.parse import urlsplit
from contracts import require
from storage import write_lock,write_json,read_json,verified_file,file_record,now
from science_modules.a06.plan_adapter import source_context

SCHEMA="A06.receptor_review.1"

# 官方JSON只用于来源证明；限定摘要来源，不接收执行参数或坐标文件。
def source_url(value):
    parts=urlsplit(value)
    require(parts.scheme=="https" and (parts.hostname in {"rest.uniprot.org","www.uniprot.org","search.rcsb.org","data.rcsb.org","www.rcsb.org","alphafold.ebi.ac.uk"} or (parts.hostname=="www.ebi.ac.uk" and parts.path.startswith("/pdbe/api/"))) and not parts.username and not parts.password,"受体摘要须引用官方HTTPS来源")

# 新核查包只追加；保留原始摘要、既有文件指纹及当前已批准成分来源。
class ReceptorReviewMixin:
    def save_receptor_review(self,sid,payload):
        with write_lock(self.root):
            manifest=self.load(sid);context=source_context(self,sid,manifest)
            require(isinstance(payload,dict) and set(payload)=={"schema_version","study_id","source_key","execution_allowed","approval","note_zh","receptors","compounds","evidence","historical_result_file"},"受体核查包字段不完整或含执行参数")
            require(payload["schema_version"]==SCHEMA and payload["study_id"]==sid and payload["source_key"]==context["source_key"],"受体核查包跨研究或来源已改变")
            require(payload["execution_allowed"] is False and payload["approval"] is None,"资料归档不能计算或代签")
            require(isinstance(payload["note_zh"],str) and payload["note_zh"].strip(),"核查包须说明用途与限制")
            rows=payload["receptors"];compounds=payload["compounds"]
            require(isinstance(rows,list) and all(isinstance(r,dict) for r in rows) and [r.get("target_id") for r in rows]==[r["target_id"] for r in context["receptors"]],"受体摘要须覆盖完整当前A/B名单")
            require(isinstance(compounds,list) and all(isinstance(r,dict) for r in compounds) and [r.get("compound_id") for r in compounds]==[r["compound_id"] for r in context["compounds"]],"成分摘要与已批准名单不一致")
            draft=self.current_docking_review(manifest);known={r["compound_id"]:r for r in (draft or {}).get("compounds",[])}
            excluded={r["compound_id"] for r in (draft or {}).get("excluded",[])}
            for row,original in zip(compounds,context["compounds"]):
                require(row["compound_id"] not in excluded and row.get("identity_prechecked") is True,"身份冲突或待补成分不得进入本轮")
                require(all(row.get(k)==original[k] for k in ("name","herbs")),"成分摘要改变了已批准身份")
                if known:
                    k=known.get(row["compound_id"]);require(k is not None and k["identity_prechecked"] and all(row.get(x)==k.get(x) for x in ("cid","name_zh","source_3d_evidence","source_3d_state_zh")),"成分资料与核查草案不一致")
                for record in row.get("source_3d_evidence",[]):verified_file(self.location(sid),record)
            for row,original in zip(rows,context["receptors"]):
                require(all(row.get(k)==original[k] for k in ("symbol","candidate_grade")),"受体身份或候选梯队改变")
                require(row.get("current_qc_zh")=="尚未准备或质控","结构元数据不能冒充当前质控通过")
                require(isinstance(row.get("uniprot"),str) and isinstance(row.get("candidates"),list),"受体摘要缺少身份或候选")
                source_url(row["identity_url"])
                history=row.get("historical")
                require(history is None or history.get("current_passed") is False,"历史质控不能自动写成本次通过")
                for candidate in row["candidates"]:
                    source_url(candidate["url"])
                    require(isinstance(candidate.get("target_chains"),list) and candidate["target_chains"] and isinstance(candidate.get("ligands"),list),"候选缺少目标链或共晶组分摘要")
            require(isinstance(payload["evidence"],list) and payload["evidence"],"核查包缺少原始官方摘要")
            for evidence in payload["evidence"]:
                source_url(evidence["url"]);require(isinstance(evidence.get("response"),dict),"来源摘要须保留原JSON响应")
            verified_file(self.location(sid),payload["historical_result_file"])
            data=deepcopy(payload);data.update(review_id="receptor_review_"+uuid4().hex,created_at=now())
            path=self.location(sid)/"decisions/A06_receptor_review"/(data["review_id"]+".json")
            write_json(path,data);manifest.setdefault("receptor_review_records",[]).append(file_record(self.location(sid),path,"receptor_metadata_review"));self.save(manifest)
            return data

    # 明确最新索引；版本不匹配时不回退更早资料，更不恢复旧评分。
    def current_receptor_review(self,manifest,context):
        records=manifest.get("receptor_review_records",[])
        if not records:return None
        data=read_json(verified_file(self.location(manifest["study_id"]),records[-1]))
        require(data.get("schema_version")==SCHEMA and data.get("study_id")==manifest["study_id"],"受体核查包版本或研究身份不符")
        if data["source_key"]!=context["source_key"]:return None
        for row in data["compounds"]:
            for record in row.get("source_3d_evidence",[]):verified_file(self.location(manifest["study_id"]),record)
        verified_file(self.location(manifest["study_id"]),data["historical_result_file"])
        return {k:deepcopy(data[k]) for k in ("review_id","created_at","note_zh","execution_allowed","approval","compounds","receptors")}

    # 配色授权只改变展示，范围必须与用户已确认的草案一致。
    def save_matrix_display(self,sid,payload):
        from science_modules.a06.matrix_palette import VERSION
        from science_modules.a06.matrix_display import check_display
        with write_lock(self.root):
            manifest=self.load(sid);context=source_context(self,sid,manifest);draft=self.current_docking_review(manifest)
            require(draft is not None and set(payload)=={"expected_source","expected_display_id","config"},"配色配置字段不完整")
            require(payload["expected_source"]==context["source_key"],"配色来源已更新，请刷新")
            require([r["compound_id"] for r in context["compounds"]]==[r["compound_id"] for r in draft["compounds"]],"当前批准名单与展示草案不同")
            current=self.current_matrix_display(manifest,context,draft)
            require(payload["expected_display_id"]==(current["display_id"] if current else None),"配色版本已更新，请刷新")
            config=payload["config"];check_display(config,draft["compounds"],draft["receptors"])
            require(config==dict(draft["display"],version=VERSION),"本次配色授权不能改变展示范围或其他规则")
            data={"schema_version":"A06.matrix_display.record.1","study_id":sid,"source_key":context["source_key"],"compound_review_id":draft["review_id"],"display_id":"matrix_display_"+uuid4().hex,"config":deepcopy(config),"execution_allowed":False,"created_at":now()}
            path=self.location(sid)/"decisions/A06_matrix_display"/(data["display_id"]+".json");write_json(path,data)
            manifest.setdefault("matrix_display_records",[]).append(file_record(self.location(sid),path,"matrix_display"));self.save(manifest)
            return data

    # 上游或草案变更后的配色记录不作当前配置；保留索引供历史核查。
    def current_matrix_display(self,manifest,context,draft):
        records=manifest.get("matrix_display_records",[])
        if not records:return None
        data=read_json(verified_file(self.location(manifest["study_id"]),records[-1]))
        require(data.get("schema_version")=="A06.matrix_display.record.1" and data.get("study_id")==manifest["study_id"],"矩阵配色记录身份或版本不符")
        if data["source_key"]!=context["source_key"] or data["compound_review_id"]!=draft["review_id"]:return None
        return data

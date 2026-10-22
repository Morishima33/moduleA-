"""新建研究的登记适配与防重复提交；科学状态及项目目录均由Workflow创建。"""

from __future__ import annotations

import re
import threading

from contracts import ContractError, fingerprint, require
from mesh_identity import verify_mesh_identity
from storage import read_json, write_json, write_lock


PROJECT_FOLDERS = [
    {"name": "intake", "label_zh": "研究登记原文"},
    {"name": "raw", "label_zh": "原始上传与来源资料"},
    {"name": "normalized", "label_zh": "标准化资料"},
    {"name": "runs", "label_zh": "各模块运行及结果版本"},
    {"name": "reviews", "label_zh": "人工复核记录"},
    {"name": "reports", "label_zh": "报告及图表附件"},
]
FIELDS = ("formula", "herbs", "disease", "mesh_term", "mesh_id", "operator", "analysis_purpose")


class CreationConflict(ContractError):
    """已成功保存的请求编号不能用于另一份登记。"""


class StudyCreation:
    """仅核对疾病身份并登记，不提交批准或自动接续任务。"""

    def __init__(self, kernel):
        self.kernel = kernel
        self._lock = threading.Lock()

    @staticmethod
    def _fields(body):
        """先检查普通表单，避免缺项时发起网络核对或创建不完整目录。"""
        require(isinstance(body, dict) and set(body) == {"request_id", *FIELDS}, "登记字段不完整或包含不支持的选项")
        request_id = body["request_id"]
        require(isinstance(request_id, str) and re.fullmatch(r"create_[0-9a-f]{32}", request_id), "提交编号无效，请重新打开新建研究")
        require(all(isinstance(body[k], str) and 0 < len(body[k].strip()) <= 2000 for k in FIELDS), "请完整填写方剂、药味、疾病、MeSH身份、登记人及用途")
        fields = {k: body[k].strip() for k in FIELDS}
        fields["mesh_id"] = fields["mesh_id"].upper()
        require(fields["analysis_purpose"] in ("formal_research", "workflow_test"), "请选择研究用途")
        require(len(fields["mesh_term"]) <= 500 and re.fullmatch(r"D\d{6,9}", fields["mesh_id"]), "请填写MeSH首选词和D开头的描述词编号")
        return request_id, fields

    def _response(self, workflow, study_id, run_id, created):
        """保存位置由服务配置和内核生成，不从疾病名拼接目录。"""
        return {"study_id": study_id, "run_id": run_id, "created": created,
                "directory": str(workflow.location(study_id)),
                "message_zh": "研究已独立建档，请在A00核对登记并准备来源资料。" if created else "本次登记已保存，已返回原项目。"}

    def _existing(self, workflow, request_id, fields):
        """从内核核验的原始A00恢复提交记录，处理服务重启或去重记录丢失。"""
        for manifest in workflow.studies(trashed=False) + workflow.studies(trashed=True):
            root = workflow.location(manifest["study_id"])
            for path in (root / "intake").glob("*.json"):
                # 目录名只定位候选；身份始终读取经内核核验的A00，原文不作为批准依据。
                run_id = path.stem
                if run_id not in manifest["runs"]:
                    continue
                result = workflow.result(manifest, run_id)
                saved = (result or {}).get("summary", {})
                if saved.get("creation_request_id") != request_id:
                    continue
                require(workflow.run(manifest, run_id)["module_id"] == "A00", "创建记录归属不一致")
                if {k: saved[k] for k in FIELDS} != fields:
                    raise CreationConflict("此提交编号已保存其他登记，请重新打开新建窗口")
                return self._response(workflow, manifest["study_id"], run_id, False)
        return None

    def create(self, body):
        """重复点击不重复建档；每个新操作仍获得独立研究目录。"""
        request_id, fields = self._fields(body)
        with self._lock, write_lock(self.kernel.settings.runtime_dir / "study-creation"):
            workflow = self.kernel.workflow()
            ledger = self.kernel.settings.runtime_dir / "study-creation" / (request_id + ".json")
            if ledger.is_file():
                record = read_json(ledger)
                if record["input_hash"] != fingerprint(fields):
                    raise CreationConflict("此提交编号已保存其他登记，请重新打开新建窗口")
                # 去重记录不是科研事实，仍核验研究内A00的真实登记。
                manifest = workflow.load(record["study_id"])
                saved = workflow.result(manifest, record["run_id"])["summary"]
                require(saved.get("creation_request_id") == request_id and {k: saved[k] for k in FIELDS} == fields, "创建记录指纹不一致")
                return self._response(workflow, record["study_id"], record["run_id"], False)
            recovered = self._existing(workflow, request_id, fields)
            if recovered:
                response = recovered
            else:
                evidence = verify_mesh_identity(fields["mesh_term"], fields["mesh_id"])
                intake = dict(fields, species=9606, disease_scope="仅本病，不纳入亚型",
                              mesh_verification=evidence, creation_request_id=request_id,
                              component_source_profile="A01.multisource.collect.1")
                study_id = workflow.create(intake)
                response = self._response(workflow, study_id, workflow.load(study_id)["current"]["A00"], True)
            write_json(ledger, {"input_hash": fingerprint(fields), "study_id": response["study_id"], "run_id": response["run_id"]})
            return response

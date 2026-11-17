"""本机 JSON 接口服务（/api/v1）与预构建前端的静态托管。

安全措施沿用原工作台：
- 只绑定 127.0.0.1；Host 头必须是 127.0.0.1:<端口> 或 localhost:<端口>（防止 DNS 重绑定）；
- 写请求必须带 X-ModuleA-Token（启动时随机生成，前端从 /api/v1/session 取得）；
- 写请求的 Origin 必须是本服务自身，或 allowed_origins 中明确允许的前端开发地址；
- 只能下载结果索引中登记且指纹核验通过的文件；所有响应禁止缓存，并带内容安全策略。
服务是多线程的：慢请求不会卡住其他页面；长计算一律交给后台任务子进程。
"""

from __future__ import annotations

import json
import hashlib
import uuid
import mimetypes
import os
import re
import secrets
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from .. import __version__
from ..config import Settings
from ..service_identity import ServiceIdentity
from ..core.kernel import ContractError, Kernel, read_json, verified_file
from ..core.study_creation import CreationConflict, StudyCreation
from ..core.plan_creation import PlanCreation, is_plan_created
from ..core.plan_a05 import is_current as has_new_a05
from science_modules.plan_stages_contract import is_current as has_new_intersection
from ..tasks.manager import TaskManager
from .errors import ApiError, from_contract, not_found
from .views import PREUPLOAD_PROFILES, Views
from ..core.source_uploads import formats as upload_formats, template as upload_template, staging as upload_staging
from disease_io import multipart

API_CSP = "default-src 'none'; frame-ancestors 'none'"
FILE_CSP = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
STATIC_CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
              "font-src 'self' data: https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
MAX_BODY = 1024 * 1024
ID = r"([A-Za-z0-9_]+)"


class App:
    """接口应用：持有配置、内核、任务管理和视图组装；路由表把 (方法, 路径) 对应到处理函数。"""

    def __init__(self, settings: Settings):
        # 先核对运行写入范围，错误配置不能先让TaskManager在研究包创建数据库。
        from ..service_control import runtime_location
        runtime_location(settings)
        self.settings = settings
        self.kernel = Kernel(settings)
        self.tasks = TaskManager(settings)
        self.views = Views(self.kernel, self.tasks)
        self.creation = StudyCreation(self.kernel)
        self.plan_creation = PlanCreation(self.kernel)
        self.token = secrets.token_urlsafe(32)
        self._listen_port = 0
        self._shutdown_callback = None
        self._service_stopping = False
        self._service_lock = threading.RLock()
        self._write_local = threading.local()
        self._writes_in_flight = 0
        self._service_identity_error = None
        try:self.service_identity = ServiceIdentity(settings)
        except (OSError,ValueError) as error:
            # 旧API-only嵌入仍可使用；运行交付健康检查明确报告配置错误。
            self.service_identity = None
            self._service_identity_error = str(error)
        self.routes = [
            ("GET", r"/api/v1/health", self.get_health),
            ("GET", rf"/api/v1/studies/{ID}/native-compute", self.get_native_compute),
            ("GET", rf"/api/v1/studies/{ID}/runs/{ID}/native/pairs/([0-9]+)/(top1\.pdbqt|context\.json)", self.get_native_top1),
            ("POST", rf"/api/v1/studies/{ID}/native-compute/(prepare|qualify|score)", self.post_native_compute),
            ("GET", rf"/api/v1/studies/{ID}/runs/{ID}/acceptance", self.get_acceptance),
            ("GET", rf"/api/v1/studies/{ID}/runs/{ID}/acceptance\.zip", self.get_acceptance_zip),
            ("GET", rf"/api/v1/tasks/{ID}/scientific-progress", self.get_scientific_progress),
            ("GET", rf"/api/v1/studies/{ID}/runs/{ID}/rescue-evidence/(details|top1|source|context|execution)", self.get_rescue_evidence),
            ("GET", rf"/api/v1/studies/{ID}/runs/{ID}/rescue-focus", self.get_rescue_focus),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/receptor-rescue", self.get_receptor_rescue),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/receptor-rescue/execute", self.post_receptor_rescue),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/receptor-rescue-v2", self.get_receptor_rescue_v2),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/receptor-rescue-v2/execute", self.post_receptor_rescue_v2),
            ("POST", r"/api/v1/service/stop", self.post_service_stop),
            ("GET", rf"/api/v1/studies/{ID}/runs/{ID}/foundation/pairs/([0-9]+)/top1\.pdbqt", self.get_foundation_top1),
            ("GET", rf"/api/v1/studies/{ID}/runs/{ID}/foundation/pairs/([0-9]+)/context\.json", self.get_foundation_context),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/historical-disease-sources", self.get_historical_disease_sources),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/historical-disease-sources/publish", self.post_historical_disease_sources),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/component-identity-probes", self.get_component_identity_probes),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/component-identity-probes/execute", self.post_component_identity_probes),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/component-identity-probes/(componentprobe_[0-9a-f]{{32}})/files/([0-9]+)", self.file_component_identity_probes),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/component-identity-evidence", self.get_component_identity_evidence),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/component-identity-evidence/export", self.export_component_identity_evidence),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/component-identity-evidence/files/([0-9]+)", self.file_component_identity_evidence),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/disease-acquisition", self.get_system_disease_acquisition),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/disease-acquisition/execute", self.post_system_disease_acquisition),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/disease-acquisition/publish", self.post_system_disease_publication),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/disease-manual-sources", self.get_system_disease_manual_sources),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/disease-manual-sources", self.post_system_disease_manual_sources),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/system-acquisition", self.get_system_acquisition),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/system-acquisition/execute", self.post_system_acquisition),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/system-acquisition/bind", self.post_system_source_binding),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/system-pipeline", self.get_system_pipeline),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/system-pipeline/start", self.post_system_pipeline_start),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/system-pipeline/continue", self.post_system_pipeline_continue),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/reports", self.get_plan_reports),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/display-revisions", self.get_display_revisions),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/display-revisions", self.post_display_revision),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/display-revisions/(displayrev_[0-9a-f]{{32}})/files/([0-9]+)", self.get_display_revision_file),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/reports/generate", self.post_plan_report),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/reports/{ID}/files/([0-9]+)", self.get_plan_report_file),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/reports/{ID}/annotations/{ID}", self.get_plan_report_annotation),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/system-validations", self.get_plan_system_validations),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/system-validations/execute", self.post_plan_system_validation),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a05-display", self.get_plan_a05_display),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a05-display/prepare", self.post_plan_a05_display_prepare),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a05-display/confirm", self.post_plan_a05_display_confirm),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a05-display/{ID}/files/([0-9]+)", self.get_plan_a05_display_file),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/preparation-ui", self.get_plan_preparation_ui),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/preparation-ui", self.post_plan_preparation_ui),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/selection-ui", self.get_plan_selection_ui),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a03-selection", self.get_plan_compounds),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a03-selection/execute", self.post_plan_compounds),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/stages", self.get_plan_stages),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/stages/execute", self.post_plan_stage),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a05", self.get_plan_a05),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a05", self.post_plan_a05),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a01", self.get_plan_a01),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a01/acquire", self.post_plan_a01_acquire),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a01/publish", self.post_plan_a01_publish),
            ("GET", r"/api/v1/analysis-plans/parameters", self.get_analysis_parameters),
            ("POST", r"/api/v1/analysis-plans/validate", self.post_analysis_validate),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan", self.get_analysis_plan),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/drafts", self.post_analysis_draft),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a04-selection", self.post_analysis_a04_selection),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a04-selection/{ID}/reviews", self.post_analysis_a04_selection_review),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a06-preparation-input", self.post_analysis_a06_preparation_input),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a06-preparation", self.post_analysis_a06_preparation),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-pockets", self.get_analysis_a06_pockets),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a06-pockets/reviews", self.post_analysis_a06_pockets),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-references", self.get_analysis_a06_references),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a06-references/reviews", self.post_analysis_a06_references),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-reference-preparation", self.get_analysis_a06_reference_preparation),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a06-reference-preparation", self.post_analysis_a06_reference_preparation),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-reference-preparation-v2", self.get_analysis_a06_reference_preparation_v2),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a06-reference-preparation-v2", self.post_analysis_a06_reference_preparation_v2),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-reference-qualification", self.get_analysis_a06_reference_qualification),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-scoring-readiness", self.get_analysis_a06_scoring_readiness),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-review-packet", self.get_analysis_a06_review_packet),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-review-packet/export.json", self.export_analysis_a06_review_packet),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-review-gate", self.get_analysis_a06_review_gate),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a06-scoring/validate", self.post_analysis_a06_scoring_validate),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-scoring", self.get_analysis_a06_scoring),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a06-scoring", self.post_analysis_a06_scoring),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-scoring/export.csv", self.export_analysis_a06_scoring),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/system-exports", self.get_system_exports),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/system-exports", self.post_system_exports),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/system-exports/{ID}/files/([0-9]+)", self.download_system_export),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/a06-reviewable-preparation", self.get_analysis_a06_reviewable),
            ("POST", rf"/api/v1/studies/{ID}/analysis-plan/a06-reviewable-preparation", self.post_analysis_a06_reviewable),
            ("GET", rf"/api/v1/studies/{ID}/trace", self.get_study_trace),
            ("GET", rf"/api/v1/studies/{ID}/trace/export.json", self.export_study_trace_json),
            ("GET", rf"/api/v1/studies/{ID}/trace/export.csv", self.export_study_trace_csv),
            ("GET", rf"/api/v1/studies/{ID}/automatic_docking/{ID}/pairs", self.get_automatic_pairs),
            ("GET", rf"/api/v1/studies/{ID}/automatic_docking/{ID}/pairs/{ID}", self.get_automatic_evidence),
            ("GET", rf"/api/v1/studies/{ID}/automatic_docking/{ID}/files", self.get_automatic_files),
            ("GET", rf"/api/v1/studies/{ID}/automatic_docking/{ID}/matrix", self.get_automatic_matrix),
            ("GET", rf"/api/v1/studies/{ID}/automatic_displays/{ID}/files/([0-9]+)", self.get_automatic_display_file),
            ("POST", rf"/api/v1/studies/{ID}/modules/A06/actions/automatic_display", self.post_automatic_display),
            ("POST", rf"/api/v1/studies/{ID}/modules/A06_PREP/actions/automatic_connect", self.post_automatic_connect),
            ("POST", rf"/api/v1/studies/{ID}/modules/A06_PREP/actions/automatic_run", self.post_automatic_run),
            ("POST", rf"/api/v1/studies/{ID}/modules/A06_PREP/actions/automatic_start", self.post_automatic_start),
            ("GET", rf"/api/v1/studies/{ID}/automatic_docking/{ID}/files/([0-9]+)", self.get_automatic_file),
            ("GET", r"/api/v1/session", self.session),
            ("GET", r"/api/v1/environment", self.get_environment),
            ("GET", rf"/api/v1/studies/{ID}/source_previews/{ID}", self.get_source_preview),
            ("POST", rf"/api/v1/studies/{ID}/modules/A01/actions/acquire_sources", self.post_source_acquire),
            ("POST", rf"/api/v1/studies/{ID}/modules/A01/actions/resolve_sources", self.post_source_resolve),
            ("POST", rf"/api/v1/studies/{ID}/modules/A02/actions/mapping_preview", self.post_mapping_preview),
            ("GET", r"/api/v1/studies", self.list_studies),
            ("POST", r"/api/v1/studies", self.post_create_study),
            ("POST", r"/api/v1/analysis-plans/creation/preflight", self.post_plan_creation_preflight),
            ("POST", r"/api/v1/analysis-plans/creation", self.post_plan_creation),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/creation", self.get_plan_creation),
            ("GET", rf"/api/v1/studies/{ID}/analysis-plan/creation/export.json", self.export_plan_creation),
            ("GET", rf"/api/v1/studies/{ID}", self.get_study),
            ("GET", rf"/api/v1/studies/{ID}/modules/{ID}", self.get_module),
            ("GET", rf"/api/v1/studies/{ID}/modules/{ID}/runs", self.get_runs),
            ("GET", rf"/api/v1/studies/{ID}/modules/{ID}/tables/{ID}", self.get_table),
            ("GET", rf"/api/v1/studies/{ID}/files/([A-Za-z0-9_.]+)", self.get_file),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/reviews", self.post_review),
            ("POST", rf"/api/v1/studies/{ID}/reviews:batch", self.post_batch_review),
            ("POST", rf"/api/v1/studies/{ID}:continue", self.post_continue),
            ("POST", rf"/api/v1/studies/{ID}:trash", self.post_trash),
            ("POST", rf"/api/v1/studies/{ID}:restore", self.post_restore),
            ("GET", rf"/api/v1/studies/{ID}/modules/{ID}/sources", self.get_sources),
            ("GET", rf"/api/v1/studies/{ID}/modules/{ID}/sources/{ID}/template", self.get_source_template),
            ("GET", rf"/api/v1/studies/{ID}/modules/{ID}/sources/{ID}/file", self.get_source_file),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/selection", self.post_selection),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/check_two_pass", self.post_check_two_pass),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/two_pass_plan", self.post_two_pass_plan),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/two_pass_draft", self.post_two_pass_draft),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/trial_review", self.post_trial_review),
            ("POST", rf"/api/v1/studies/{ID}/modules/A06/actions/figure", self.post_docking_figure),
            ("POST", rf"/api/v1/studies/{ID}/modules/A06/actions/pair_packages", self.post_pair_packages),
            ("POST", rf"/api/v1/studies/{ID}/modules/A06/actions/pair_bundle", self.post_pair_bundle),
            ("POST", rf"/api/v1/studies/{ID}/modules/A05/actions/ranked_pathway_maps", self.post_ranked_pathway_maps),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/coverage_selection", self.post_coverage_selection),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/material", self.post_docking_material),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/docking_candidates", self.post_docking_candidates),
            ("GET", rf"/api/v1/studies/{ID}/docking_candidates/{ID}", self.get_docking_candidates),
            ("GET", rf"/api/v1/studies/{ID}/source_reviews/{ID}/files/{ID}", self.get_review_source_file),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/run_ppi", self.post_run_ppi),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/identity_plan", self.post_identity_plan),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/display_confirmation", self.post_display_confirmation),
            ("GET", rf"/api/v1/studies/{ID}/modules/A04/identity_evidence/{ID}", self.get_identity_evidence),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/upload", self.post_source_upload),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/process_sources", self.post_source_process),
            ("POST", rf"/api/v1/studies/{ID}/modules/A02/actions/retry_sources", self.post_source_retry),
            ("POST", rf"/api/v1/studies/{ID}/modules/A02/actions/scope_review", self.post_disease_scope),
            ("POST", rf"/api/v1/studies/{ID}/modules/A02/actions/normalization", self.post_normalization),
            ("GET", r"/api/v1/trash", self.list_trash),
            ("GET", r"/api/v1/inbox", self.get_inbox),
            ("GET", r"/api/v1/tasks", self.list_tasks),
            ("GET", rf"/api/v1/tasks/{ID}", self.get_task),
            ("GET", rf"/api/v1/tasks/{ID}/log", self.get_task_log),
            ("POST", rf"/api/v1/tasks/{ID}:cancel", self.post_cancel),
            ("POST", rf"/api/v1/tasks/{ID}:retry", self.post_retry),
        ]
        self.compiled = [(method, re.compile("^" + pattern + "$"), handler) for method, pattern, handler in self.routes]

    # ------------------------------------------------------------------ 读取
    def get_foundation_top1(self, req, study_id, run_id, pair_number):
        """只读提取本批原MODEL1，来源、评分与盒均由服务端逐件核验。"""
        from .foundation_evidence import top1
        return top1(self, req, study_id, run_id, pair_number)

    def get_foundation_context(self, req, study_id, run_id, pair_number):
        """下载同一Top1原件与提取字节指纹，不写研究或更改计算。"""
        from .foundation_evidence import context
        return context(self, req, study_id, run_id, pair_number)

    def get_environment(self, req):
        """仅用户按需请求，避免每个模块页面反复读取大参考快照。"""
        from ..preflight import inspect_environment
        return inspect_environment(self.settings)

    def get_source_preview(self, req, study_id, identity):
        """按固定预览索引分页，不接收任意路径或返回完整原始响应。"""
        from ..core.source_previews import mapping
        workflow = self.kernel.read_workflow()
        manifest = workflow.load(study_id)
        value = mapping(workflow, manifest, identity)
        database = req.query1("database") or "TTD"
        if database not in ("TTD", "PharmGKB"):
            raise ApiError(422, "VALIDATION_FAILED", "请选择TTD或PharmGKB")
        try:
            page, size = int(req.query1("page") or 1), int(req.query1("size") or 25)
        except (ValueError, TypeError):
            raise ApiError(422, "VALIDATION_FAILED", "分页参数应为整数")
        if page < 1 or size < 1 or size > 100:
            raise ApiError(422, "VALIDATION_FAILED", "分页参数超出范围")
        row = next((r for r in value["databases"] if r["database"] == database), {"candidates": [], "status_zh": "本轮未查询此库"})
        candidates = row.get("candidates", [])
        return {"preview_id": identity, "database": database, "status_zh": row.get("status_zh"), "error_zh": row.get("error_zh"),
                "page": page, "size": size, "total": len(candidates), "items": candidates[(page-1)*size:page*size],
                "current": value["bound_a00"] == manifest["current"].get("A00") and value["bound_a02"] == manifest["current"].get("A02", ""),
                "note_zh": "候选只供核验，当前A02未改变；合并疾病及亚型不自动纳入。"}

    def _source_task(self, req, study_id, module_id, kind, allowed):
        """公共版本和范围校验后排队，后台再次核验，不自动批准。"""
        body = req.json()
        info = self._source_versions(req, study_id, module_id, body)
        if kind == 'a01_acquire' and not (info.get('acquisition') or {}).get('enabled'):
            raise ApiError(409, 'GATE_BLOCKED', '请使用新方案获取入口，不能使用旧固定OB/DL获取')
        databases = body.get("databases")
        if not isinstance(databases, list) or not databases or not all(isinstance(v, str) for v in databases) or len(set(databases)) != len(databases) or not set(databases) <= set(allowed):
            raise ApiError(422, "VALIDATION_FAILED", "请选择本入口支持的非重复数据库")
        if not isinstance(body.get("reason"), str) or not 0 < len(body["reason"].strip()) <= 2000:
            raise ApiError(422, "VALIDATION_FAILED", "请填写本次操作依据")
        payload = {k: info[k] for k in ("expected_a00", "expected_run", "expected_staging")}
        payload.update(databases=databases, reason=body["reason"].strip())
        if kind == "a01_acquire":
            payload["acquisition_id"] = "fetch_" + uuid.uuid4().hex
        task, created = self.tasks.submit(study_id, kind, "网页来源核查", payload)
        if not created:
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，请完成后重试")
        return {"task": task, "created": created, "message_zh": "操作已提交后台；原始资料与当前A02保留，未自动批准。"}, 202

    def post_source_acquire(self, req, study_id):
        """显式采集三库固定官方来源，浏览器不能提供目标URL。"""
        return self._source_task(req, study_id, "A01", "a01_acquire", ("TCMSP", "HERB", "BATMAN"))

    def post_mapping_preview(self, req, study_id):
        """疾病定位独立预览，不保存范围决定或替换来源。"""
        return self._source_task(req, study_id, "A02", "a02_mapping_preview", ("TTD", "PharmGKB"))

    def post_source_resolve(self, req, study_id):
        """确认本次完整性与身份例外，结果仍由原科学内核独立门控。"""
        body = req.json()
        info = self._source_versions(req, study_id, "A01", body)
        if not (info.get("verification") or {}).get("enabled"):
            raise ApiError(409, "GATE_BLOCKED", "请先整理当前完整三库并查看核验问题")
        if body.get("confirmed") is not True or any(type(body.get(k)) is not bool for k in ("confirm_coverage", "omit_unresolved")):
            raise ApiError(422, "VALIDATION_FAILED", "请明确选择并确认处理范围")
        if any(not isinstance(body.get(k), str) or not 0 < len(body[k].strip()) <= 2000 for k in ("reviewer", "note")):
            raise ApiError(422, "VALIDATION_FAILED", "请填写核验人及处理依据")
        payload = {k: body[k] for k in ("expected_a00", "expected_run", "expected_staging", "confirmed", "confirm_coverage", "omit_unresolved", "reviewer", "note")}
        task, created = self.tasks.submit(study_id, "a01_resolve", body["reviewer"].strip(), payload)
        if not created:
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务")
        return {"task": task, "created": created, "message_zh": "处理已提交；生成后仍须整体复核，当前A02保持。"}, 202

    def get_automatic_pairs(self, req, sid, batch):
        from .automatic_view import pairs
        return pairs(self, req, sid, batch)

    def get_automatic_evidence(self, req, sid, batch, key):
        from .automatic_view import evidence
        return evidence(self, req, sid, batch, key)

    def get_automatic_files(self, req, sid, batch):
        from .automatic_view import files
        return files(self, req, sid, batch)

    def get_automatic_matrix(self, req, sid, batch):
        from .automatic_view import matrix
        return matrix(self, req, sid, batch)

    def post_automatic_display(self, req, sid):
        from .automatic_view import display
        return display(self, req, sid)

    def get_automatic_display_file(self, req, sid, identity, index):
        from .automatic_view import display_file
        return display_file(self, req, sid, identity, index)

    def get_analysis_parameters(self, req):
        """读取参数定义，不创建研究或启动任务。"""
        from .analysis_plan_view import schema
        return schema(self, req)

    def get_plan_a05_display(self,req,sid):
        """读取实际新版A05展示资料。"""
        from .plan_a05_display import info
        return info(self,req,sid)

    def post_plan_a05_display_prepare(self,req,sid):
        """明确准备分类与核译资料。"""
        from .plan_a05_display import execute
        return execute(self,req,sid,'prepare')

    def post_plan_a05_display_confirm(self,req,sid):
        """明确保存展示范围与逐项核译。"""
        from .plan_a05_display import execute
        return execute(self,req,sid,'confirm')

    def get_plan_a05_display_file(self,req,sid,identity,index):
        """下载登记图件，不接受路径。"""
        from .plan_a05_display import file
        return file(self,req,sid,identity,index)

    def post_analysis_validate(self, req):
        """校验方案；全流程执行未接通前保持不可启动。"""
        from .analysis_plan_view import validate
        return validate(self, req)

    def get_analysis_plan(self, req, study_id):
        """仅读取本研究显式新协议的方案草稿。"""
        from .analysis_plan_view import info
        return info(self, req, study_id)

    def post_analysis_draft(self, req, study_id):
        """保存草稿，不触碰活动计算。"""
        from .analysis_plan_view import draft
        return draft(self, req, study_id)

    def post_analysis_a04_selection(self, req, study_id):
        """提交新方案A04选择归档任务；结果仍待独立复核。"""
        from .analysis_plan_view import a04_selection
        return a04_selection(self, req, study_id)

    def post_analysis_a04_selection_review(self, req, study_id, selection_id):
        """保存A04受体选择的独立复核决定。"""
        from .analysis_plan_view import a04_selection_review
        return a04_selection_review(self, req, study_id, selection_id)

    def post_analysis_a06_preparation_input(self, req, study_id):
        """提交两份已复核选择的新版A06准备输入归档任务。"""
        from .analysis_plan_view import a06_preparation_input
        return a06_preparation_input(self, req, study_id)

    def post_analysis_a06_preparation(self, req, study_id):
        """提交真实来源连接及结构/配体准备任务，组合评分仍关闭。"""
        from .analysis_plan_view import a06_preparation
        return a06_preparation(self, req, study_id)

    def get_analysis_a06_pockets(self, req, study_id):
        """只读预测口袋证据清单。"""
        from .analysis_pocket_view import info
        return info(self, req, study_id)

    def post_analysis_a06_pockets(self, req, study_id):
        """提交明确口袋采用决定，结果仍待独立核查。"""
        from .analysis_pocket_view import review
        return review(self, req, study_id)

    def get_analysis_a06_references(self, req, study_id):
        """只读共晶参考候选；不联网、不准备、不保存选择。"""
        from .analysis_reference_view import info
        return info(self, req, study_id)

    def post_analysis_a06_references(self, req, study_id):
        """提交显式共晶参考选择，交由隔离科学任务复核。"""
        from .analysis_reference_view import review
        return review(self, req, study_id)

    def get_analysis_a06_reference_preparation(self, req, study_id):
        """只读当前参考证据绑定准备状态。"""
        from .analysis_reference_preparation_view import info
        return info(self, req, study_id)

    def post_analysis_a06_reference_preparation(self, req, study_id):
        """提交参考证据绑定新版准备任务。"""
        from .analysis_reference_preparation_view import prepare
        return prepare(self, req, study_id)

    def get_analysis_a06_reference_qualification(self, req, study_id):
        """只读复算新版准备的整体复核资料资格。"""
        from .analysis_reference_preparation_view import qualification
        return qualification(self, req, study_id)

    def get_analysis_a06_reference_preparation_v2(self, req, study_id):
        """只读参考资格复算准备状态。"""
        from .analysis_reference_preparation_view import info_v2
        return info_v2(self, req, study_id)

    def post_analysis_a06_reference_preparation_v2(self, req, study_id):
        """显式提交参考资格复算后台任务。"""
        from .analysis_reference_preparation_view import prepare_v2
        return prepare_v2(self, req, study_id)

    def get_analysis_a06_scoring_readiness(self, req, study_id):
        """只读复算正式评分是否具备启动条件。"""
        from .analysis_reference_preparation_view import scoring_readiness
        return scoring_readiness(self, req, study_id)

    def get_analysis_a06_review_packet(self, req, study_id):
        """只读获取A06整体复核材料包。"""
        from .analysis_reference_preparation_view import review_packet
        return review_packet(self, req, study_id)

    def export_analysis_a06_review_packet(self, req, study_id):
        """下载A06整体复核材料包JSON。"""
        from .analysis_reference_preparation_view import export_review_packet
        return export_review_packet(self, req, study_id)

    def get_analysis_a06_review_gate(self, req, study_id):
        """只读获取A06人工整体复核闸门。"""
        from .analysis_reference_preparation_view import review_gate
        return review_gate(self, req, study_id)

    def post_analysis_a06_scoring_validate(self, req, study_id):
        """只读预检正式评分请求。"""
        from .analysis_reference_preparation_view import validate_scoring
        return validate_scoring(self, req, study_id)

    def get_analysis_a06_scoring(self, req, study_id):
        """只读新版评分资格与本批状态。"""
        from .plan_scoring_view import info
        return info(self, req, study_id)

    def post_analysis_a06_scoring(self, req, study_id):
        """明确确认后提交独立评分后台任务。"""
        from .plan_scoring_view import submit
        return submit(self, req, study_id)

    def export_analysis_a06_scoring(self, req, study_id):
        """核验指纹后下载当前批次完整评分CSV。"""
        from .plan_scoring_view import export_csv
        return export_csv(self, req, study_id)

    def get_analysis_a06_reviewable(self, req, study_id):
        """只读当前准备的人工整体复核接入资格。"""
        from .reviewable_preparation_view import info
        return info(self, req, study_id)

    def post_analysis_a06_reviewable(self, req, study_id):
        """显式提交资料复验；不会代签复核决定。"""
        from .reviewable_preparation_view import publish
        return publish(self, req, study_id)

    def get_system_exports(self, req, study_id):
        """只读系统评分同批导出资格和既有文件。"""
        from .system_exports import info
        return info(self, req, study_id)

    def post_system_exports(self, req, study_id):
        """明确派生Excel/CSV/图，不计算科学评分。"""
        from .system_exports import submit
        return submit(self, req, study_id)

    def download_system_export(self, req, study_id, export_id, index):
        """核指纹后读取本研究已登记导出。"""
        from .system_exports import download
        return download(self, req, study_id, export_id, index)

    def get_study_trace(self, req, study_id):
        """返回当前研究的只读追溯摘要；详细数据通过显式导出下载。"""
        from .trace_actions import trace_summary
        return trace_summary(self, req, study_id)

    def export_study_trace_json(self, req, study_id):
        """下载完整参数、版本、来源和结果追溯JSON。"""
        from .trace_actions import export_trace_json
        return export_trace_json(self, req, study_id)

    def export_study_trace_csv(self, req, study_id):
        """下载当前模块结果表的UTF-8 CSV。"""
        from .trace_actions import export_trace_csv
        return export_trace_csv(self, req, study_id)

    def _automatic_ready(self, study_id):
        """只读校验工具、当前上游及并发状态；不自动签署授权。"""
        if self.tasks.active_for(study_id):
            raise ApiError(409, "GATE_BLOCKED", "请等待当前研究后台任务结束")
        if not self.settings.science_tools_root:
            raise ApiError(409, "GATE_BLOCKED", "尚未配置固定对接工具目录")
        return self.kernel.workflow()

    def post_automatic_connect(self, req, study_id):
        """连接与评分分离；请求不接受路径或隐藏名单。"""
        body = req.json()
        if not isinstance(body, dict) or set(body) != {"expected_binding"} or not isinstance(body["expected_binding"], str) or not re.fullmatch(r"[0-9a-f]{64}", body["expected_binding"]):
            raise ApiError(422, "VALIDATION_FAILED", "连接请求字段不合法")
        workflow = self._automatic_ready(study_id)
        try:
            workflow.automatic_binding(study_id, body["expected_binding"])
            workflow.validate_extended_scope(study_id)
        except ContractError as error:
            raise from_contract(str(error))
        payload = dict(body, connection_id="connection_" + uuid.uuid4().hex, policy_version="A06.automatic.3")
        task, created = self.tasks.submit(study_id, "a06_auto_connect", "网页连接对接资料（不评分）", payload)
        if not created:
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务")
        return {"task": task, "message_zh": "开始连接资料；完成后由你一次确认计算范围。"}, 202

    def post_automatic_start(self, req, study_id):
        """一次明确确认后连续连接及计算；不将连接请求当成执行授权。"""
        from ..core.automatic_start import validate
        payload = req.json()
        workflow = self._automatic_ready(study_id)
        try:
            validate(workflow, study_id, payload)
        except ContractError as error:
            raise from_contract(str(error))
        task, created = self.tasks.submit(study_id, "a06_auto_start", "网页一次确认连接并计算", payload)
        if not created:
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务")
        return {"task": task, "message_zh": "已确认连续执行：先连接或补齐资料，再自动准备、质控、对接和出图；结果待独立复核。"}, 202

    def post_automatic_run(self, req, study_id):
        """登记显式授权任务，子进程开始及发布前再次校验版本。"""
        payload = req.json()
        workflow = self._automatic_ready(study_id)
        if isinstance(payload, dict) and payload.get("policy_version") == "A06.automatic.1":
            # 明确声明旧协议的请求仍按旧协议验证，绝不升级其授权。
            from ..core.automatic_docking import AutomaticDockingWorkflow
            workflow = AutomaticDockingWorkflow(self.settings.data_root, workflow.validators)
        elif isinstance(payload, dict) and payload.get("policy_version") == "A06.automatic.2":
            from ..core.automatic_coverage import AutomaticCoverageWorkflow
            workflow = AutomaticCoverageWorkflow(self.settings.data_root, workflow.validators)
        try:
            workflow.validate_automatic_request(study_id, payload)
        except ContractError as error:
            raise from_contract(str(error))
        task, created = self.tasks.submit(study_id, "a06_auto_run", "网页一次授权自动对接", payload)
        if not created:
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务")
        return {"task": task, "message_zh": "已提交一次授权，后台依次准备、质控、对接和出图；结果仍待独立复核。"}, 202

    def get_automatic_file(self, req, study_id, identity, index):
        """仅从本研究登记的文件索引下载，逐次校验原始指纹。"""
        workflow = self.kernel.read_workflow()
        record = workflow.automatic_record(workflow.load(study_id), identity)
        number = int(index)
        if not record or number >= len(record["files"]):
            raise not_found("本研究的自动对接证据")
        path = verified_file(workflow.location(study_id), record["files"][number])
        mime = "image/png" if path.suffix.lower() == ".png" else "application/octet-stream"
        return ("file", path, path.name, mime, mime == "image/png")

    def session(self, req):
        return {"token": self.token, "version": __version__, "platform": sys.platform,
                "capabilities": {"review": True, "batch_review": True, "tasks": True, "trash": True, "module_actions": False, "source_upload": True, "ppi_compute": True, "create_study": True, "system_pipeline": True, "system_acquisition": True, "system_source_binding": True, "system_disease_acquisition": True, "system_disease_publication": True, "system_preparation_recovery": True, "system_disease_manual_sources": True, "component_identity_evidence": True, "component_identity_probes": True, "historical_disease_sources": True, "system_exports": True},
                "decisions_zh": {"approved": "通过，允许下游使用", "rejected": "退回修改", "pending": "暂存待定"}}

    def post_create_study(self, req):
        """核对官方疾病身份并独立建档；不代签、不提交计算任务。"""
        try:
            result = self.creation.create(req.json())
        except CreationConflict as error:
            raise ApiError(409, "CREATE_CONFLICT", str(error)) from error
        except ContractError as error:
            if "暂时无法连接NLM" in str(error):
                raise ApiError(503, "MESH_UNAVAILABLE", str(error), retryable=True) from error
            raise from_contract(str(error)) from error
        return result, 201 if result["created"] else 200

    def get_plan_a01(self, req, study_id):
        """读取新方案A01实际就绪条件。"""
        from .plan_a01_view import info
        return info(self, req, study_id)

    def get_plan_a05(self, req, study_id):
        """读取新版富集资格，不执行统计。"""
        from .plan_a05_view import info
        return info(self, req, study_id)

    def get_plan_stages(self,req,study_id):
        """只读新版阶段实际依赖与执行条件。"""
        from .plan_stages_view import info
        return info(self,req,study_id)

    def get_plan_system_validations(self,req,study_id):
        """只读当前系统校验资格、原科学状态及不可变历史。"""
        from .system_validation import info
        return self._json_read(study_id,info,self,req,study_id)

    def get_plan_reports(self,req,study_id):
        """只读本批报告资格和真实历史下载。"""
        from .plan_reports import info
        return self._json_read(study_id,info,self,req,study_id)

    def get_display_revisions(self,req,study_id):
        """只读同批另存图表和核译；完成证据范围复验后才返回JSON。"""
        from .display_revisions import info
        return self._json_read(study_id,info,self,req,study_id)

    def post_display_revision(self,req,study_id):
        """明确请求仍沿原完整写入预检与预算，不采用读取范围。"""
        from .display_revisions import submit
        return submit(self,req,study_id)

    def get_display_revision_file(self,req,study_id,revision_id,index):
        """附件流单独逐件检查，不借用JSON响应范围。"""
        from .display_revisions import download
        return download(self,req,study_id,revision_id,index)

    def _json_read(self,study_id,function,*args):
        """只给指定JSON入口复用同请求证据，退出全SHA成功才交给HTTP响应。"""
        from ..core.checkpoint_json_read import json_evidence_scope
        with json_evidence_scope(self.settings.data_root,study_id) as evidence:
            result=evidence.call(function,*args)
        return result

    def get_system_pipeline(self,req,study_id):
        """只读统一编排的真实批次和阶段流水。"""
        from .system_pipeline import info
        return info(self,req,study_id)

    def get_system_acquisition(self,req,study_id):
        """只读三库原件获取条件、实际失败和逐库恢复进度。"""
        from .system_acquisition import info
        return info(self,req,study_id)

    def get_component_identity_evidence(self,req,study_id):
        """本版系统A01原件与原官方响应只读核对。"""
        from .component_identity_evidence import info
        return info(self,req,study_id)

    def get_historical_disease_sources(self,req,study_id):
        """读取本研究例外条件和已记录的用户决定。"""
        from .historical_disease_sources import info
        return info(self,req,study_id)

    def post_historical_disease_sources(self,req,study_id):
        """明确例外仅排队，候选整理在独立后台执行。"""
        from .historical_disease_sources import publish
        return publish(self,req,study_id)

    def get_component_identity_probes(self,req,study_id):
        """读取正式补查历史及当前资格，不发出外部请求。"""
        from .component_identity_probes import info
        return info(self,req,study_id)

    def post_component_identity_probes(self,req,study_id):
        """明确补查只排队，不在HTTP联网或采用身份。"""
        from .component_identity_probes import execute
        return execute(self,req,study_id)

    def file_component_identity_probes(self,req,study_id,probe_id,index):
        """按已登记补查回执下载原文。"""
        from .component_identity_probes import file
        return file(self,req,study_id,probe_id,index)

    def export_component_identity_evidence(self,req,study_id):
        """导出必须保持读到的研究和版本绑定。"""
        from .component_identity_evidence import export
        return export(self,req,study_id)

    def file_component_identity_evidence(self,req,study_id,index):
        """附件由服务端编号选择，客户端不能指定路径。"""
        from .component_identity_evidence import file
        return file(self,req,study_id,index)

    def get_system_disease_acquisition(self,req,study_id):
        """只读疾病五库原件及恢复资格，不解析来源、不联网。"""
        from .system_disease_acquisition import info
        return info(self,req,study_id)

    def get_system_disease_manual_sources(self,req,study_id):
        """只读首次预上传资格与本研究原件元信息。"""
        from .system_disease_manual_sources import info
        return info(self,req,study_id)

    def post_system_disease_manual_sources(self,req,study_id):
        """严格原件上传仅排队，科学解析在独立后台执行。"""
        from .system_disease_manual_sources import upload
        return upload(self,req,study_id)

    def post_system_disease_acquisition(self,req,study_id):
        """明确提交疾病获取任务，失败不能被当成科学零结果。"""
        from .system_disease_acquisition import execute
        return execute(self,req,study_id)

    def post_system_disease_publication(self,req,study_id):
        """完整原件明确提交独立疾病候选任务，不在HTTP进行科学整理。"""
        from .system_disease_acquisition import publish
        return publish(self,req,study_id)

    def post_system_acquisition(self,req,study_id):
        """严格明确确认后仅排队，HTTP不获取或发布科学结果。"""
        from .system_acquisition import execute
        return execute(self,req,study_id)

    def post_system_source_binding(self,req,study_id):
        """明确绑定已有三库原件，HTTP不解包、不发布科学结果。"""
        from .system_acquisition import bind_sources
        return bind_sources(self,req,study_id)

    def post_system_pipeline_start(self,req,study_id):
        """登记一次明确授权并提交独立后台任务。"""
        from .system_pipeline import execute
        return execute(self,req,study_id,start=True)

    def post_system_pipeline_continue(self,req,study_id):
        """只对当前实际输入明确续做，不从GET或重启自动执行。"""
        from .system_pipeline import execute
        return execute(self,req,study_id)

    def post_plan_report(self,req,study_id):
        """明确提交实际同批双报告，不在HTTP生成文档。"""
        from .plan_reports import execute
        return execute(self,req,study_id)

    def get_plan_report_file(self,req,study_id,run_id,index):
        """下载本研究登记的当前或历史Word，逐件核验。"""
        from .plan_reports import file
        return file(self,req,study_id,run_id,index)

    def get_plan_report_annotation(self,req,study_id,run_id,repair_id):
        """只读下载已登记且指纹完整的用户批注版。"""
        from .plan_reports import annotation_file
        return annotation_file(self,req,study_id,run_id,repair_id)

    def post_plan_system_validation(self,req,study_id):
        """显式提交真实科学复算，不在接口进程执行。"""
        from .system_validation import execute
        return execute(self,req,study_id)

    def get_plan_compounds(self,req,study_id):
        """读取本方案成分选择资格，不计算名单。"""
        from .plan_compounds_view import info
        return self._json_read(study_id,info,self,req,study_id)

    def get_receptor_rescue(self, req, study_id):
        """补救资格只取当前来源，GET不准备结构或启动评分。"""
        from .receptor_rescue import info
        return self._json_read(study_id, info, self, req, study_id)

    def post_receptor_rescue(self, req, study_id):
        """明确同批执行请求进入原重任务队列，科研复核独立保存。"""
        from .receptor_rescue import execute
        return execute(self, req, study_id)

    def get_receptor_rescue_v2(self, req, study_id):
        """明确二版资格；未完成第一版仍提供其原请求恢复，不自动升级。"""
        from .receptor_rescue_v2 import info
        return self._json_read(study_id, info, self, req, study_id)

    def post_receptor_rescue_v2(self, req, study_id):
        """新的二版请求独立排队，旧版执行地址与请求内容保持。"""
        from .receptor_rescue_v2 import execute
        return execute(self, req, study_id)

    def get_plan_selection_ui(self,req,study_id):
        """只读受体选择及新版准备输入的当前资格。"""
        from .plan_selection_ui import info
        return info(self,req,study_id)

    def get_plan_preparation_ui(self,req,study_id):
        """只读固定输入至新版准备和后续证据导航。"""
        from .plan_preparation_ui import info
        return info(self,req,study_id)

    def post_plan_preparation_ui(self,req,study_id):
        """明确启动本批第二版科学准备，不启动评分。"""
        from .plan_preparation_ui import execute
        return execute(self,req,study_id)

    def post_plan_compounds(self,req,study_id):
        """明确提交本方案成分选择后台任务。"""
        from .plan_compounds_view import execute
        return execute(self,req,study_id)

    def post_plan_stage(self,req,study_id):
        """明确执行当前方案中的就绪阶段。"""
        from .plan_stages_view import execute
        return execute(self,req,study_id)

    def post_plan_a05(self, req, study_id):
        """提交按当前方案执行的独立富集任务。"""
        from .plan_a05_view import submit
        return submit(self, req, study_id)

    def post_plan_a01_acquire(self, req, study_id):
        """明确提交按本方案门槛获取所选库。"""
        from .plan_a01_view import submit
        return submit(self, req, study_id, "acquire")

    def post_plan_a01_publish(self, req, study_id):
        """明确提交三库标准化，仍停在独立复核。"""
        from .plan_a01_view import submit
        return submit(self, req, study_id, "publish")

    def post_plan_creation_preflight(self, req):
        """校验登记、方案及真实材料状态，不创建研究或任务。"""
        from .plan_creation_view import preflight
        return preflight(self, req)

    def post_plan_creation(self, req):
        """明确确认后独立建档并共同留存初始方案。"""
        from .plan_creation_view import create
        return create(self, req)

    def get_plan_creation(self, req, study_id):
        """只读研究绑定的初始方案与预检。"""
        from .plan_creation_view import info
        return info(self, req, study_id)

    def export_plan_creation(self, req, study_id):
        """下载本研究初始及当前方案，不修改研究状态。"""
        from .plan_creation_view import export
        return export(self, req, study_id)

    def list_studies(self, req):
        return {"items": self.views.study_cards(trashed=False)}

    def list_trash(self, req):
        return {"items": self.views.study_cards(trashed=True)}

    def get_study(self, req, study_id):
        return self._json_read(study_id,self.views.study,study_id)

    def get_module(self, req, study_id, module_id):
        return self._json_read(study_id,self.views.module,study_id,module_id,req.query1("run_id"))

    def get_runs(self, req, study_id, module_id):
        return {"items": self.views.runs(study_id, module_id)}

    def get_table(self, req, study_id, module_id, name):
        return self.views.table(study_id, module_id, name, req.query1("run_id"), req.query_int("page", 1),
                                req.query_int("size", 50), req.query1("q") or "")

    def get_inbox(self, req):
        return {"items": self.views.inbox()}

    def list_tasks(self, req):
        self.tasks.reconcile()
        return {"items": self.tasks.list(req.query1("study"), active_only=req.query1("active") == "1")}

    def get_task(self, req, task_id):
        self.tasks.reconcile()
        task = self.tasks.get(task_id)
        if not task:
            raise not_found("任务")
        return task

    def get_scientific_progress(self, req, task_id):
        """按本任务原请求读取已登记科学进度，不改任务或研究状态。"""
        from .scientific_progress import info
        return info(self,req,task_id)

    def get_native_compute(self,req,study_id):
        """本平台准备、核查与评分资格只读，不运行工具。"""
        from .native_execution import info
        return info(self,req,study_id)

    def get_native_top1(self,req,study_id,run_id,pair_number,kind):
        """只读导出本批实际MODEL1及同构象说明；没有工具或路径覆盖入口。"""
        from .native_results import top1
        return top1(self,req,study_id,run_id,pair_number,kind)

    def post_native_compute(self,req,study_id,stage):
        """明确新平台请求进入同一任务队列，参数由后台读取同批方案。"""
        from .native_execution import submit
        return submit(self,req,study_id,stage)

    def get_task_log(self, req, task_id):
        try:
            return self.tasks.log(task_id, req.query_int("offset", 0))
        except KeyError:
            raise not_found("任务")

    def get_file(self, req, study_id, key):
        from .rescue_evidence import file_download
        checked = file_download(self, req, study_id, key)
        if checked is not None:
            return checked
        path, name, mime = self.views.file(study_id, key)
        inline = req.query1("inline") == "1" and mime.startswith("image/")
        return ("file", path, name, mime, inline)

    def get_rescue_evidence(self, req, study_id, run_id, kind):
        """详情沿同请求证据范围；字节下载按实际读取内容独立核验。"""
        from .rescue_evidence import read
        if kind == 'details':
            return self._json_read(study_id, read, self, req, study_id, run_id, kind)
        return read(self, req, study_id, run_id, kind)

    def get_rescue_focus(self, req, study_id, run_id):
        """焦点图只显示后端返回的同批格子，不触发任何科学计算。"""
        from .rescue_evidence import focus
        return self._json_read(study_id, focus, self, req, study_id, run_id)

    def get_acceptance(self, req, study_id, run_id):
        """验收资料仅核对同批登记原件齐备性，不补图或重算。"""
        from .acceptance_bundle import info
        return info(self,req,study_id,run_id)

    def get_acceptance_zip(self, req, study_id, run_id):
        """只读整理既有原件和构象，下载发送同一份已核验字节。"""
        from .acceptance_bundle import download
        return download(self,req,study_id,run_id)

    # ------------------------------------------------------------------ 写入
    def post_review(self, req, study_id, module_id):
        body = req.json()
        decision = body.get("decision")
        after = body.get("after", "save")
        workflow = self.kernel.workflow()
        try:
            manifest = workflow.load(study_id)
            run_id = body.get("run_id") or ""
            if run_id not in manifest["runs"] or workflow.run(manifest, run_id)["module_id"] != module_id:
                raise ApiError(409, "STALE_VERSION", "复核对象与模块不一致，请刷新后重试")
            review = workflow.review(study_id, run_id, decision, body.get("reviewer", ""), body.get("note", ""), body.get("expected_review_id") or None)
        except ModuleNotFoundError as error:
            # A07 通过需核对报告通路，依赖 python-docx 等报告库；本机缺少时如实说明
            raise ApiError(503, "TOOL_UNAVAILABLE", f"本机缺少报告依赖（{error.name}），暂不能完成该项复核")
        except ContractError as error:
            raise from_contract(str(error))
        task = None
        automatic_a00 = module_id == "A00" and manifest.get("workflow_profile") in PREUPLOAD_PROFILES
        if decision == "approved" and (after == "continue" or automatic_a00):
            prep_id = manifest.get('current', {}).get('A06_PREP')
            reviewable = bool(prep_id and workflow.run(manifest, prep_id)['config'].get('version') == 'A06.plan_reviewable_preparation.1')
            if not reviewable and not is_plan_created(workflow, manifest) and not has_new_a05(workflow,manifest) and not has_new_intersection(workflow,manifest):
                task, _ = self.tasks.submit(study_id, "continue", "保存并继续")
        return {"review": review, "task": task,
                "message_zh": "复核决定已保存。" + self._task_message(task)}, 201

    def post_batch_review(self, req, study_id):
        """A01 与 A02 一次提交、分别留下独立复核记录；任一项冲突则整批拒绝。"""
        body = req.json()
        entries = {}
        for module in ("A01", "A02"):
            item = (body.get("entries") or {}).get(module) or {}
            entries[module] = {"run_id": item.get("run_id", ""), "expected_review": item.get("expected_review_id") or None,
                               "action": item.get("action", "decide"), "decision": item.get("decision", ""), "note": item.get("note", "")}
        workflow = self.kernel.workflow()
        try:
            reviews = workflow.review_a01_a02(study_id, entries, body.get("reviewer", ""))
        except ContractError as error:
            raise from_contract(str(error))
        task = None
        study = self.views.study(study_id)
        codes = {m["module_id"]: m["code"] for group in study["nav"] for m in group["modules"]}
        if codes.get("A01") == "approved" and codes.get("A02") == "approved" and not is_plan_created(workflow, workflow.load(study_id)) and not has_new_a05(workflow,workflow.load(study_id)) and not has_new_intersection(workflow,workflow.load(study_id)):
            task, _ = self.tasks.submit(study_id, "continue", "A01与A02均通过")
        return {"reviews": reviews, "task": task, "message_zh": "两项复核决定已保存。" + self._task_message(task)}, 201

    @staticmethod
    def _task_message(task):
        if not task:
            return ""
        if task["state"] == "failed":
            return "后台任务未能启动：" + (task.get("error_zh") or "请在任务面板查看原因并手动重试。")
        return "后台任务已提交，可在任务面板查看进度。"

    def post_continue(self, req, study_id):
        """手动触发“推进到下一人工关口”（与保存并继续相同的后台任务）。"""
        manifest = self.views._manifest(study_id)
        if manifest.get("trashed"):
            raise ApiError(423, "TRASHED_READONLY", "研究在回收站中，不能继续；请先恢复")
        if is_plan_created(self.kernel.workflow(), manifest) or has_new_a05(self.kernel.workflow(),manifest) or has_new_intersection(self.kernel.workflow(),manifest):
            raise ApiError(409, 'GATE_BLOCKED', '新方案自动编排尚未接通，不能使用旧固定参数接续')
        prep_id = manifest.get('current', {}).get('A06_PREP')
        if prep_id and self.kernel.workflow().run(manifest, prep_id)['config'].get('version') == 'A06.plan_reviewable_preparation.1':
            raise ApiError(409, 'GATE_BLOCKED', '新版准备不能接续旧协议；请到新版评分区独立明确确认，报告仍待新协议接入')
        task, created = self.tasks.submit(study_id, "continue", "手动继续")
        return {"task": task, "created": created}, 202

    def _trash(self, req, study_id, trashed: bool):
        body = req.json()
        if body.get("confirm") is not True:
            raise ApiError(422, "VALIDATION_FAILED", "请勾选确认后再提交")
        try:
            action = self.kernel.workflow().set_trashed(study_id, trashed, body.get("operator", ""), body.get("reason", ""), body.get("expected_action_id") or None)
        except ContractError as error:
            raise from_contract(str(error))
        return {"action": action}, 201

    def post_trash(self, req, study_id):
        return self._trash(req, study_id, True)

    def post_restore(self, req, study_id):
        return self._trash(req, study_id, False)

    def post_cancel(self, req, task_id):
        try:
            return self.tasks.cancel(task_id)
        except KeyError:
            raise not_found("任务")

    def post_retry(self, req, task_id):
        old = self.tasks._raw(task_id)
        if old and self.views._manifest(old["study_id"]).get("trashed"):
            raise ApiError(423, "TRASHED_READONLY", "研究在回收站中，不能重试任务；请先恢复")
        if (old and old["kind"] == "a06_pair_packages"
                and json.loads(old.get("payload") or "{}").get("request_version") != "A06.drawing.on_demand.2"):
            raise ApiError(409, "GATE_BLOCKED", "旧批量整理已停止，请在A06页面重新选择需要的组合")
        try:
            task, created = self.tasks.retry(task_id, "重试")
        except KeyError:
            raise not_found("任务")
        return {"task": task, "created": created}, 202

    # 读取来源入口时只核对归档，不导入科学依赖。
    def get_sources(self, req, study_id, module_id):
        value = self.views.module(study_id, module_id).get("source_uploads")
        if value is None:
            raise not_found("该模块没有资料上传入口")
        return value

    def get_source_template(self, req, study_id, module_id, database):
        info = self.get_sources(req, study_id, module_id)
        fmt = req.query1("format")
        if database not in {r["database"] for r in info["sources"]} or fmt not in upload_formats(module_id, database):
            raise ApiError(422, "VALIDATION_FAILED", "数据库或资料格式不属于当前研究方案")
        workflow = self.kernel.workflow()
        manifest = workflow.load(study_id)
        summary = workflow.result(manifest, manifest["current"]["A00"])["summary"]
        from components import parse_herbs
        data, name, mime = upload_template(module_id, database, fmt, parse_herbs(summary["herbs"]))
        return ("download", data, name, mime)

    # 原始资料下载只允许当前研究清单中登记且指纹核验通过的文件。
    def get_source_file(self, req, study_id, module_id, database):
        info = self.get_sources(req, study_id, module_id)
        if not any(s["database"] == database and s["download_url"] for s in info["sources"]):
            raise not_found("当前库的上传资料")
        workflow = self.kernel.workflow()
        manifest = workflow.load(study_id)
        if module_id == "A01":
            sources = upload_staging(workflow, manifest)["datasets"]
        else:
            result = workflow.result(manifest, manifest["current"]["A02"])
            record = next(r for r in result["sources"] if r.get("role") == "source_manifest")
            sources = read_json(verified_file(workflow.location(study_id), record))["datasets"]
        item = next(r for r in sources if r["database"] == database)
        path = verified_file(workflow.location(study_id), item["source_record"])
        return ("file", path, item.get("name") or path.name, "application/octet-stream", False)

    # 双重校验页面版本：提交前检查，后台进入科学写锁后再次检查。
    def _source_versions(self, req, study_id, module_id, body):
        info = self.get_sources(req, study_id, module_id)
        if not info["enabled"]:
            raise ApiError(409, "GATE_BLOCKED", info["disabled_reason_zh"])
        if any(body.get(k, "") != info[k] for k in ("expected_a00", "expected_run", "expected_staging")):
            raise ApiError(409, "STALE_VERSION", "研究或资料版本已改变，请刷新后重新提交")
        return info

    def post_source_upload(self, req, study_id, module_id):
        fields, files = req.multipart()
        info = self._source_versions(req, study_id, module_id, fields)
        database, fmt = fields.get("database"), fields.get("format")
        if database not in {s["database"] for s in info["sources"]} or fmt not in upload_formats(module_id, database):
            raise ApiError(422, "VALIDATION_FAILED", "数据库或格式不属于当前研究方案")
        if fields.get("confirmed") != "yes":
            raise ApiError(422, "VALIDATION_FAILED", "请确认资料属于当前研究后上传")
        for key in ("query", "retrieved_at", "version", "source_url", "reason"):
            if not fields.get(key, "").strip():
                raise ApiError(422, "VALIDATION_FAILED", "请填写检索词、获取日期、版本、来源和上传原因", {"field": key})
        source = {k: fields.get(k, "").strip() for k in ("database", "format", "encoding", "query", "retrieved_at", "version", "source_url")}
        source["encoding"] = source["encoding"] or "utf-8-sig"
        if database == "GeneCards":
            source.update(query_quoted=fields.get("query_quoted", "unknown"), export_completeness=fields.get("export_completeness", "unknown"))
        source["name"] = files["upload"]["name"]
        payload = {k: info[k] for k in ("expected_a00", "expected_run", "expected_staging")}
        payload.update(module_id=module_id, source=source, reason=fields["reason"].strip())
        if module_id == "A02":
            summary = self.views._snapshot(study_id)[1]
            current = next(m for m in summary["modules"] if m["module_id"] == "A02")["result"]
            payload["source_profile"] = (current or {}).get("summary", {}).get("source_profile") or ("A02.source_profile.3" if self.views._manifest(study_id).get("workflow_profile") in PREUPLOAD_PROFILES else "A02.source_profile.default.1")
        # 原始字节暂存到运行目录，任务输入只保存固定文件名与指纹，不保存客户端路径。
        folder = self.settings.runtime_dir / "upload_queue"
        folder.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex + ".bin"
        path = folder / name
        path.write_bytes(files["upload"]["data"])
        payload.update(blob_name=name, blob_sha256=hashlib.sha256(files["upload"]["data"]).hexdigest())
        task, created = self.tasks.submit(study_id, "source_upload", "网页分库上传", payload)
        if not created:
            path.unlink()
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，本次资料未提交，请完成后重试")
        return {"task": task, "created": created, "message_zh": "资料已提交后台校验，处理结果见任务面板；尚未批准。" + self._task_message(task)}, 202

    def post_normalization(self, req, study_id):
        """标准化明确预览、明确发布；只提交后台，不在接口做身份计算。"""
        from ..core.normalization_bridge import validate
        body = req.json()
        info = self.views.module(study_id, "A02").get("normalization")
        if not info or any(body.get(k) != info[k] for k in ("expected_a00", "expected_a01", "expected_a02")):
            raise ApiError(409, "STALE_VERSION", "资料版本已改变，请重新加载标准化入口")
        if not info["enabled"]:
            raise ApiError(409, "GATE_BLOCKED", info["disabled_reason_zh"])
        payload = {k: body.get(k) for k in ("expected_a00", "expected_a01", "expected_a02", "action", "stamp", "reviewer", "note", "confirmed", "accept_omit", "accept_source_exception")}
        validate(self.kernel.workflow(), study_id, payload)
        if payload["action"] == "publish" and (not info["preview"] or payload["stamp"] != info["preview"]["stamp"]):
            raise ApiError(409, "STALE_VERSION", "请先生成并核对当前版本的标准化预览")
        kind = "normalization_" + payload["action"]
        task, created = self.tasks.submit(study_id, kind, "网页标准化" if payload["action"] == "preview" else payload["reviewer"].strip(), payload)
        if not created:
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，请等待完成")
        return {"task": task, "created": created, "message_zh": "标准化操作已提交，完成后仍需独立整体复核。" + self._task_message(task)}, 202

    def post_disease_scope(self, req, study_id):
        """保存完整范围决定，来源身份不符不能纳入本病。"""
        from ..core.disease_scope import validate_submission
        body = req.json()
        self._source_versions(req, study_id, "A02", body)
        info = self.views.module(study_id, "A02").get("disease_scope")
        if not info or not info["enabled"]:
            raise ApiError(409, "GATE_BLOCKED", "当前范围条目不可核验，请刷新")
        validate_submission(info, body)
        payload = {k: body[k] for k in ("expected_a00", "expected_run", "expected_staging", "decisions", "reviewer", "note", "confirmed")}
        task, created = self.tasks.submit(study_id, "a02_scope_review", "网页疾病范围核验", payload)
        if not created:
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，请完成后重试")
        return {"task": task, "created": created, "message_zh": "范围核验已提交；保存后仍需身份核查及A02整体复核。" + self._task_message(task)}, 202

    def post_source_retry(self, req, study_id):
        """绑定当前来源版本，只提交选中的失败库。"""
        body = req.json()
        info = self._source_versions(req, study_id, "A02", body)
        databases = body.get("databases")
        allowed = {s["database"] for s in info["sources"] if s.get("can_retry")}
        if not isinstance(databases, list) or not databases or not all(isinstance(db, str) for db in databases) or len(databases) != len(set(databases)) or not set(databases) <= allowed:
            raise ApiError(422, "VALIDATION_FAILED", "请选择当前获取失败且支持自动重试的来源")
        if not isinstance(body.get("reason"), str) or not 0 < len(body["reason"].strip()) <= 2000:
            raise ApiError(422, "VALIDATION_FAILED", "请填写本次重试原因")
        payload = {k: info[k] for k in ("expected_a00", "expected_run", "expected_staging")}
        payload.update(databases=databases, reason=body["reason"].strip())
        task, created = self.tasks.submit(study_id, "a02_sources_retry", "网页重试失败来源", payload)
        if not created:
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，请完成后重试")
        return {"task": task, "created": created, "message_zh": "失败来源重试已提交；结果仍需人工复核。" + self._task_message(task)}, 202

    def post_source_process(self, req, study_id, module_id):
        if module_id != "A01":
            raise not_found("该模块没有三库整理操作")
        body = req.json()
        info = self._source_versions(req, study_id, module_id, body)
        if not info["can_process"]:
            raise ApiError(409, "GATE_BLOCKED", info["process_reason_zh"])
        if not isinstance(body.get("reason"), str) or not body["reason"].strip():
            raise ApiError(422, "VALIDATION_FAILED", "请填写本次整理原因")
        payload = {k: info[k] for k in ("expected_a00", "expected_run", "expected_staging")}
        payload["reason"] = body["reason"].strip()
        task, created = self.tasks.submit(study_id, "a01_sources", "网页整理三库", payload)
        if not created:
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，请完成后重试")
        return {"task": task, "created": created, "message_zh": "三库整理任务已提交，结果仍需独立复核。" + self._task_message(task)}, 202

    # 页面和后台两次核对上游版本，仅登记A04科学任务。
# 写入口先核对同源当前页面；格式与科学规则由公开Workflow再次检查。
    def _docking_action(self,study_id,module_id,field):
        info=self.views.module(study_id,module_id).get(field)
        if not info:raise not_found("该模块没有本操作")
        if not info["enabled"]:raise ApiError(409,"GATE_BLOCKED",info["disabled_reason_zh"])
        return info

    def post_selection(self,req,study_id,module_id):
        if module_id!="A03_SELECT":raise not_found("成分选择")
        self._docking_action(study_id,module_id,"compound_selection");payload=req.json()
        try:self.kernel.workflow().validate_selection_request(study_id,payload)
        except ContractError as error:raise from_contract(str(error))
        task,created=self.tasks.submit(study_id,"a03_selection","页面成分选择",payload)
        if not created:raise ApiError(409,"GATE_BLOCKED","当前研究已有后台任务")
        return {"task":task,"created":created,"message_zh":"选择已提交；保存后须在复核栏独立确认。"},202

    def post_check_two_pass(self,req,study_id,module_id):
        if module_id!="A06_PREP":raise not_found("两遍方案")
        self._docking_action(study_id,module_id,"docking_preparation")
        try:return self.kernel.workflow().check_two_pass(study_id,req.json()),200
        except ContractError as error:raise from_contract(str(error))

    # 不完整草案只经公开Workflow方法暂存，复用同源、令牌和研究锁保护。
    def post_two_pass_draft(self,req,study_id,module_id):
        if module_id!="A06_PREP":raise not_found("两遍核查草案")
        info=self._docking_action(study_id,module_id,"docking_preparation");body=req.json()
        require_keys={"expected_source","expected_plan_id","expected_draft_id","plan","checked_target_ids","reviewer","note"}
        if not isinstance(body,dict) or set(body)-{"expected_source_review_id"}!=require_keys:raise ApiError(422,"VALIDATION_FAILED","草案请求字段不完整或包含隐藏参数")
        payload={**body,"draft_id":"draft_"+uuid.uuid4().hex}
        try:data=self.kernel.workflow().save_two_pass_draft(study_id,payload)
        except ContractError as error:raise from_contract(str(error))
        return {"draft":{k:data[k] for k in ("draft_id","created_at","reviewer","note","checked_target_ids")},"message_zh":"核查草案已保存；刷新可继续填写，尚未确认完整方案。"},201

    def post_trial_review(self,req,study_id,module_id):
        """试算核查独立保存；不触发正式批准或隐藏计算。"""
        if module_id not in ("A06_PREP", "A06"):
            raise not_found("试算核查")
        body = req.json()
        if not isinstance(body,dict) or set(body) != {"trial_id","reviewer","note","confirmed"} or not isinstance(body["confirmed"],bool):
            raise ApiError(422,"VALIDATION_FAILED","试算核查字段非法")
        if self.tasks.active_for(study_id):
            raise ApiError(409,"GATE_BLOCKED","请等待本研究任务结束再保存核查")
        try:
            value = self.kernel.workflow().save_trial_review(study_id,body["trial_id"],body["note"],body["reviewer"],body["confirmed"])
        except ContractError as error:
            raise from_contract(str(error))
        return {"review":value,"message_zh":"试算核查已保存；未批准正式科研结果。"},201

    def post_coverage_selection(self,req,study_id,module_id):
        """集中采用的结果生成走后台，接口进程只读取与登记，不能载入科学依赖。"""
        if module_id!="A06_PREP":raise not_found("本轮可用范围")
        body=req.json()
        if not isinstance(body,dict):
            raise ApiError(422,"VALIDATION_FAILED","范围请求必须为对象")
        if self.tasks.active_for(study_id):
            raise ApiError(409,"GATE_BLOCKED","请等待当前研究后台任务结束")
        try:
            # 内核校验保留身份、归档、回收站与过期阻断；不额外构造整张只读页面。
            workflow=self.kernel.workflow()
            if body.get("confirmed") is False:
                return workflow.save_coverage_selection(study_id,body),201
            workflow.validate_coverage_selection(study_id,body)
        except ContractError as error:raise from_contract(str(error))
        task,created=self.tasks.submit(study_id,"a06_coverage_confirm","页面集中确认可用范围",body)
        if not created:raise ApiError(409,"GATE_BLOCKED","当前研究已有后台任务")
        return {"task":task,"created":created,"message_zh":"本轮采用范围已提交，后台留存准备版本；不运行批量结合能。"},202

    def post_two_pass_plan(self,req,study_id,module_id):
        if module_id!="A06_PREP":raise not_found("两遍方案")
        info=self._docking_action(study_id,module_id,"docking_preparation");payload=req.json()
        if payload.get("expected_source")!=info["expected_source"] or payload.get("expected_plan_id")!=info["expected_plan_id"]:raise ApiError(409,"STALE_VERSION","两遍方案已改变，请刷新")
        if set(payload)-{"expected_draft_id","expected_source_review_id"}!={"expected_source","expected_plan_id","confirmed_target_ids","reviewer","note","confirmed","plan"} or payload.get("confirmed") is not True or any(not isinstance(payload.get(k),str) or not payload[k].strip() for k in ("reviewer","note")):raise ApiError(422,"VALIDATION_FAILED","请明确确认并填写核验人与依据，不接受隐藏执行参数")
        if info.get("expected_draft_id") and payload.get("expected_draft_id")!=info["expected_draft_id"]:raise ApiError(409,"STALE_VERSION","核查草案已更新，请刷新后确认完整方案")
        if info.get("expected_source_review_id") and payload.get("expected_source_review_id")!=info["expected_source_review_id"]:raise ApiError(409,"STALE_VERSION","来源原件核查版本已更新，请刷新")
        from science_modules.a06.two_pass_plan import validate
        try:
            validate(payload.get("plan"),info["context"],payload.get("confirmed_target_ids"),info["materials"])
            verified=self.kernel.workflow().check_two_pass(study_id,payload)
            if not verified["confirmation"]["ready"]:raise ContractError("来源原件选择未核对或已改变")
        except ContractError as error:raise from_contract(str(error))
        payload["plan_id"]="plan_"+uuid.uuid4().hex
        task,created=self.tasks.submit(study_id,"a06_plan","页面确认两遍方案",payload)
        if not created:raise ApiError(409,"GATE_BLOCKED","当前研究已有后台任务")
        return {"task":task,"created":created,"message_zh":"方案已提交；只保存，不执行科学计算。"},202

    def post_docking_material(self,req,study_id,module_id):
        if module_id!="A06_PREP":raise not_found("来源三维资料")
        self._docking_action(study_id,module_id,"docking_preparation")
        try:data=self.kernel.workflow().save_material(study_id,req.json())
        except ValueError as error:raise from_contract(str(error))
        return {"material":data,"message_zh":"来源三维SDF已独立归档；化学及三维身份待后续核验。"},201

    def post_docking_candidates(self,req,study_id,module_id):
        if module_id not in ("A04","A06_PREP"):
            raise not_found("该模块没有候选分组操作")
        body=req.json()
        info=self.views.module(study_id,module_id).get("docking_candidates")
        keys=("expected_a03","expected_a04","expected_a04_review")
        if not info or any(body.get(k)!=info[k] for k in keys):
            raise ApiError(409,"STALE_VERSION","A03、A04或A04复核已改变，请刷新")
        if not info["enabled"]:
            raise ApiError(409,"GATE_BLOCKED",info["disabled_reason_zh"])
        payload={k:body.get(k) for k in keys}
        payload.update(reason=body.get("reason"),group_id="group_"+uuid.uuid4().hex)
        try:
            self.kernel.workflow().validate_candidates(study_id,payload)
        except ContractError as error:
            raise from_contract(str(error))
        task,created=self.tasks.submit(study_id,"a06_candidates","页面生成两梯队候选",payload)
        if not created:
            raise ApiError(409,"GATE_BLOCKED","当前研究已有后台任务，请等待完成")
        return {"task":task,"created":created,"message_zh":"候选分组已提交；不运行真实分子对接。"+self._task_message(task)},202

    # 下载只查本研究索引，拒绝任意路径与跨研究编号。
    # 仅下载当前研究明确登记的原件，历史亦校验指纹，不接收任意路径。
    def get_review_source_file(self,req,study_id,review_id,file_key):
        workflow=self.kernel.workflow()
        if not (workflow.location(study_id)/"manifest.json").is_file():raise not_found("研究")
        manifest=workflow.load(study_id)
        for record in manifest.get("source_review_records",[]):
            data=read_json(verified_file(workflow.location(study_id),record))
            if data.get("study_id")==study_id and data.get("review_id")==review_id:
                for item in data["files"]:
                    if item["key"]==file_key:
                        path=verified_file(workflow.location(study_id),item["file"])
                        return ("file",path,item["name"],"application/octet-stream",False)
        raise not_found("本研究已归档的来源原件")

    def get_docking_candidates(self,req,study_id,group_id):
        workflow=self.kernel.workflow()
        manifest=workflow.load(study_id)
        for record in manifest.get("docking_candidate_records",[]):
            path=verified_file(workflow.location(study_id),record)
            data=read_json(path)
            if data.get("group_id")==group_id and data.get("study_id")==study_id:
                return ("file",path,path.name,"application/json",False)
        raise not_found("本研究的候选分组")

    def post_run_ppi(self, req, study_id, module_id):
        if module_id != "A04":
            raise not_found("该模块没有PPI计算操作")
        body = req.json()
        info = self.views.module(study_id, module_id).get("ppi_run")
        if not info or any(body.get(k) != info[k] for k in ("expected_a03", "expected_a04")):
            raise ApiError(409, "STALE_VERSION", "交集或PPI版本已改变，请刷新后重试")
        if not info["enabled"]:
            raise ApiError(409, "GATE_BLOCKED", info["disabled_reason_zh"])
        if not isinstance(body.get("reason"), str) or not body["reason"].strip():
            raise ApiError(422, "VALIDATION_FAILED", "请填写本次PPI计算原因")
        payload = {key: info[key] for key in ("expected_a03", "expected_a04")}
        payload["reason"] = body["reason"].strip()
        task, created = self.tasks.submit(study_id, "a04_ppi", "页面启动A04", payload)
        if not created:
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，请等待完成")
        return {"task": task, "created": created, "message_zh": "A04计算已提交，完成后需独立复核。" + self._task_message(task)}, 202

    # 补查原文按研究索引下载；人工方案明确提交后台，不代签身份结果。
    def get_identity_evidence(self, req, study_id, evidence_id):
        workflow = self.kernel.workflow()
        manifest = workflow.load(study_id)
        for record in manifest.get("identity_evidence", []):
            path = verified_file(workflow.location(study_id), record)
            data = read_json(path)
            if data.get("evidence_id") == evidence_id and data.get("study_id") == study_id:
                return ("file", path, path.name, "application/json", False)
        raise not_found("本研究的身份补查原文")

    # 校验本研究版本与人工范围，长计算走后台。
    def post_identity_plan(self, req, study_id, module_id):
        if module_id != "A04":
            raise not_found("该模块没有PPI身份操作")
        body = req.json()
        info = self.views.module(study_id, module_id).get("identity_plan")
        if not info or any(
            body.get(k) != info[k] for k in ("expected_a03", "expected_a04", "expected_decision_id")
        ):
            raise ApiError(409, "STALE_VERSION", "身份方案、交集或PPI版本已改变，请刷新")
        if not info["enabled"]:
            raise ApiError(409, "GATE_BLOCKED", info["disabled_reason_zh"])
        keys = (
            "expected_a03",
            "expected_a04",
            "expected_decision_id",
            "reviewer",
            "note",
            "check_ids",
            "omit_ids",
            "confirmed",
        )
        payload = {k: body.get(k) for k in keys}
        payload["decision_id"] = "decision_" + uuid.uuid4().hex
        try:
            self.kernel.workflow().validate_identity_plan(study_id, payload)
        except ContractError as error:
            raise from_contract(str(error))
        task, created = self.tasks.submit(
            study_id, "a04_identity", payload["reviewer"].strip(), payload
        )
        if not created:
            raise ApiError(409, "GATE_BLOCKED", "当前研究已有后台任务，本次方案未提交")
        return {
            "task": task,
            "created": created,
            "message_zh": "方案已提交后台保存与应用，请查看任务结果；尚未批准A04。"
            + self._task_message(task),
        }, 202

    # 同研究同版本的人工展示确认立即提交后台；所有必填项由服务端再次验证。
    def post_display_confirmation(self, req, study_id, module_id):
        if module_id != "A05":
            raise not_found("该模块没有富集展示确认")
        body = req.json()
        info = self.views.module(study_id,module_id).get("enrichment_display")
        if not info or any(body.get(k) != info[k] for k in ("expected_a03","expected_a05","expected_decision_id")):
            raise ApiError(409,"STALE_VERSION","富集结果或确认版本已改变，请刷新")
        if not info["enabled"]:
            raise ApiError(409,"GATE_BLOCKED",info["disabled_reason_zh"])
        payload = {k:body.get(k) for k in ("expected_a03","expected_a05","expected_decision_id","action","reviewer","note","excluded_ids","confirmed","exclude_all_confirmed")}
        payload["decision_id"]="decision_"+uuid.uuid4().hex
        try:
            self.kernel.workflow().validate_display_confirmation(study_id,payload)
        except ContractError as error:
            raise from_contract(str(error))
        task,created = self.tasks.submit(study_id,"a05_display",payload["reviewer"].strip(),payload)
        if not created:
            raise ApiError(409,"GATE_BLOCKED","当前研究已有后台任务，本次确认未提交")
        return {"task":task,"created":created,"message_zh":"确认已提交后台保存与重绘，请查看应用结果；尚未批准A05。"+self._task_message(task)},202

    # ------------------------------------------------------------------ 分派
    def post_docking_figure(self, req, study_id):
        """通过令牌验证后将图片验证提交独立后台任务。"""
        from .drawing_actions import upload_figure
        return upload_figure(self, req, study_id)

    def post_ranked_pathway_maps(self, req, study_id):
        """显式点击生成两个排名首位图件，不代签机制通路审批。"""
        from .ranked_pathway_actions import ranked_map_task
        return ranked_map_task(self, req, study_id)

    def post_pair_packages(self, req, study_id):
        """只制作原始评分≤−8的选中组合，不运行Vina。"""
        from .drawing_actions import pair_task
        return pair_task(self, req, study_id, "a06_pair_packages")

    def post_pair_bundle(self, req, study_id):
        """将已准备组合包按本次选择整理为下载合集。"""
        from .drawing_actions import pair_task
        return pair_task(self, req, study_id, "a06_pair_bundle")

    def dispatch(self, method: str, path: str, req):
        for route_method, pattern, handler in self.compiled:
            match = pattern.match(path)
            if match and route_method == method:
                return handler(req, *match.groups())
        raise not_found("接口 " + path)

    def get_health(self, req):
        """毫秒级实例/前端健康信息；不读取Workflow、研究或科学执行环境。"""
        if self.service_identity is None:
            raise ApiError(503,'SERVICE_CONFIG_UNAVAILABLE','服务源码配置不可用：'+str(self._service_identity_error))
        value=self.service_identity.describe(self._listen_port)
        value['stopping']=self._service_stopping
        return value

    @contextmanager
    def admit_write(self,path=None):
        """关闭前阻断新增写请求；正常请求并行，不新增研究状态或任务队列。"""
        with self._service_lock:
            if self._service_stopping and path!='/api/v1/service/stop':raise ApiError(503,'SERVICE_STOPPING','工作台正在关闭，请完成重新启动后刷新',retryable=True)
            self._writes_in_flight+=1
        previous=getattr(self._write_local,'admitted',False);self._write_local.admitted=True
        try:yield
        finally:
            self._write_local.admitted=previous
            with self._service_lock:self._writes_in_flight-=1

    def post_service_stop(self, req):
        """只关闭此实例监听；明确身份、无后台任务和无其他写入才允许。"""
        body=req.json()
        if not isinstance(body,dict) or set(body)!={'instance_id','confirmed'} or body['confirmed'] is not True:
            raise ApiError(422,'VALIDATION_FAILED','请明确确认停止当前工作台，不接受进程号或额外参数')
        if self.service_identity is None or body['instance_id']!=self.service_identity.instance_id:
            raise ApiError(409,'STALE_INSTANCE','工作台实例已变化，未停止任何服务')
        with self._service_lock:
            if self._service_stopping:
                return {'instance_id':self.service_identity.instance_id,'accepted':True,'message_zh':'本实例已经在安全关闭中。'},202
            own=1 if getattr(self._write_local,'admitted',False) else 0
            if self._writes_in_flight>own:
                raise ApiError(409,'ACTIVE_WRITE','当前有资料操作尚未结束，请稍后再停止工作台')
            if self.tasks.list(active_only=True,limit=1):
                raise ApiError(409,'ACTIVE_TASKS','当前有后台任务排队或运行，请先完成或在任务面板明确取消')
            if self._shutdown_callback is None:raise ApiError(503,'SERVICE_CONTROL_UNAVAILABLE','当前实例未接通安全关闭入口')
            self._service_stopping=True
            # 稍后关闭自己的监听，让确认响应先写完；不操作任何PID或worker。
            timer=threading.Timer(.15,self._shutdown_callback);timer.daemon=True
            try:timer.start()
            except Exception:
                self._service_stopping=False
                raise
        return {'instance_id':self.service_identity.instance_id,'accepted':True,
                'message_zh':'已接受停止工作台；研究资料和任务历史保留。'},202


class Request:
    """一次请求的查询参数与 JSON 正文。"""

    def __init__(self, handler: BaseHTTPRequestHandler, query: dict):
        self.handler = handler
        self.query = query

    def query1(self, name: str) -> str | None:
        values = self.query.get(name)
        return values[0] if values else None

    def query_int(self, name: str, default: int) -> int:
        try:
            return int(self.query1(name) or default)
        except (ValueError, TypeError):
            raise ApiError(400, "BAD_REQUEST", f"查询参数 {name} 必须是整数", {"field": name}) from None

    # multipart容量沿用原上传入口；JSON容量保持1MiB，安全检查仍在读取正文之前。
    def multipart(self):
        try:
            length = int(self.handler.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "BAD_REQUEST", "Content-Length必须是非负整数") from None
        if length <= 0:
            raise ApiError(400, "BAD_REQUEST", "请选择一个资料文件")
        if length > 17 * 1024 * 1024:
            raise ApiError(413, "BODY_TOO_LARGE", "上传请求超过17MiB，请按库上传不超过16MiB的文件")
        try:
            return multipart(self.handler.headers.get("Content-Type", ""), self.handler.rfile.read(length))
        except (UnicodeError, ValueError):
            raise ApiError(422, "VALIDATION_FAILED", "上传格式或文本编码损坏，请重新选择文件") from None

    def json(self) -> dict:
        try:
            length = int(self.handler.headers.get("Content-Length") or 0)
            if length < 0:
                raise ValueError
        except ValueError:
            raise ApiError(400, "BAD_REQUEST", "Content-Length 必须是非负整数", {"field": "Content-Length"}) from None
        if length > MAX_BODY:
            raise ApiError(413, "BODY_TOO_LARGE", "请求内容过大")
        try:
            data = json.loads(self.handler.rfile.read(length) or b"{}")
        except ValueError:
            raise ApiError(400, "BAD_REQUEST", "请求内容不是有效的 JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "BAD_REQUEST", "请求内容必须是 JSON 对象")
        return data


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ModuleA"

        def log_message(self, format, *args):  # 不把研究内容写进控制台
            return

        # ---- 安全检查 ----
        def _host_ok(self) -> bool:
            port = str(self.server.server_port)
            return self.headers.get("Host") in ("127.0.0.1:" + port, "localhost:" + port)

        def _origin(self) -> str | None:
            return self.headers.get("Origin")

        def _origin_allowed(self) -> bool:
            origin = self._origin()
            port = str(self.server.server_port)
            return origin is None or origin in ("http://127.0.0.1:" + port, "http://localhost:" + port) or origin in app.settings.allowed_origins

        def _cors(self):
            origin = self._origin()
            if origin and origin in app.settings.allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-ModuleA-Token")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        # ---- 响应 ----
        def _headers(self, status: int, size: int, mime: str, csp: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", csp)
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self._cors()
            self.end_headers()

        def _send(self, status: int, data: bytes, mime: str, csp: str, extra: dict | None = None):
            self._headers(status, len(data), mime, csp, extra)
            if self.command != "HEAD":
                self.wfile.write(data)

        def _send_file(self, path, mime: str, csp: str, extra: dict | None = None):
            """已授权文件分块发送，避免每个图片/下载请求再分配一整件附件的内存。"""
            with Path(path).open("rb") as stream:
                self._headers(200, os.fstat(stream.fileno()).st_size, mime, csp, extra)
                if self.command != "HEAD":
                    while data := stream.read(256 * 1024):
                        self.wfile.write(data)

        def _json(self, status: int, payload):
            self._send(status, json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8", API_CSP)

        def _error(self, error: ApiError):
            self._json(error.status, error.body())

        # ---- 方法 ----
        def do_OPTIONS(self):
            if not self._host_ok() or not self._origin_allowed():
                return self._error(ApiError(403, "FORBIDDEN_ORIGIN", "访问来源不被允许"))
            self._send(204, b"", "text/plain", API_CSP)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def _handle(self, method: str):
            try:
                if not self._host_ok():
                    raise ApiError(403, "FORBIDDEN_ORIGIN", "访问地址不匹配")
                route = urlsplit(self.path)
                if not route.path.startswith("/api/"):
                    if method != "GET":
                        raise not_found(route.path)
                    return self._static(route.path)
                if method == "POST":
                    if not self._origin_allowed():
                        raise ApiError(403, "FORBIDDEN_ORIGIN", "不接受其他网页发起的操作")
                    if not secrets.compare_digest(self.headers.get("X-ModuleA-Token", ""), app.token):
                        raise ApiError(403, "BAD_TOKEN", "操作令牌无效，请刷新页面")
                request=Request(self, parse_qs(route.query))
                if method == 'POST':
                    with app.admit_write(route.path):result = app.dispatch(method, route.path, request)
                else:result = app.dispatch(method, route.path, request)
                if isinstance(result, tuple) and result and result[0] == "verified_download":
                    _, data, name, mime, inline = result
                    disposition = ("inline" if inline else "attachment") + "; filename*=UTF-8''" + quote(name, safe="")
                    return self._send(200, data, mime, FILE_CSP, {"Content-Disposition": disposition,
                        "X-Content-SHA256": hashlib.sha256(data).hexdigest()})
                if isinstance(result, tuple) and result and result[0] == "file":
                    _, path, name, mime, inline = result
                    disposition = ("inline" if inline else "attachment") + "; filename*=UTF-8''" + quote(name, safe="")
                    return self._send_file(path, mime, FILE_CSP, {"Content-Disposition": disposition})
                if isinstance(result, tuple) and result and result[0] == "download":
                    _, data, name, mime = result
                    disposition = "attachment; filename*=UTF-8''" + quote(name, safe="")
                    return self._send(200, data, mime, API_CSP, {"Content-Disposition": disposition})
                status = 200
                if isinstance(result, tuple):
                    result, status = result
                self._json(status, result)
            except ApiError as error:
                self._error(error)
            except ContractError as error:
                self._error(from_contract(str(error)))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # 浏览器已离开或取消下载，不再尝试向断开的连接发送第二份错误响应。
                self.close_connection = True
            except Exception as error:  # 未预期错误：返回说明，不泄露路径细节
                self._error(ApiError(500, "INTERNAL", f"服务内部错误：{type(error).__name__}"))

        def _static(self, path: str):
            """托管预构建前端；未知路径回到 index.html（单页应用路由）。"""
            root = app.settings.static_dir
            if not root or not (root / "index.html").exists():
                return self._json(200, {"name": "Module A", "version": __version__, "api": "/api/v1",
                                        "note_zh": "未找到预构建前端；请运行 npm run build（见 web/README）或使用 --static-dir 指定。"})
            target = (root / path.lstrip("/")).resolve()
            if not target.is_relative_to(root.resolve()) or not target.is_file():
                target = root / "index.html"
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if mime.startswith("text/") or mime in ("application/javascript", "application/json"):
                mime += "; charset=utf-8"
            self._send_file(target, mime, STATIC_CSP)

    return Handler


def create_server(settings: Settings, port: int = 8765) -> tuple[ThreadingHTTPServer, App]:
    app = App(settings)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    server.daemon_threads = True
    app._listen_port=server.server_port
    def stop_own_listener():
        """同时释放本监听；嵌入式运行也不依赖CLI finally才关闭端口。"""
        server.shutdown()
        server.server_close()
    app._shutdown_callback=stop_own_listener
    return server, app

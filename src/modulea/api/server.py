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
import re
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from .. import __version__
from ..config import Settings
from ..core.kernel import ContractError, Kernel, read_json, verified_file
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
        self.settings = settings
        self.kernel = Kernel(settings)
        self.tasks = TaskManager(settings)
        self.views = Views(self.kernel, self.tasks)
        self.token = secrets.token_urlsafe(32)
        self.routes = [
            ("GET", r"/api/v1/session", self.session),
            ("GET", r"/api/v1/studies", self.list_studies),
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
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/run_ppi", self.post_run_ppi),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/identity_plan", self.post_identity_plan),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/display_confirmation", self.post_display_confirmation),
            ("GET", rf"/api/v1/studies/{ID}/modules/A04/identity_evidence/{ID}", self.get_identity_evidence),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/upload", self.post_source_upload),
            ("POST", rf"/api/v1/studies/{ID}/modules/{ID}/actions/process_sources", self.post_source_process),
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
    def session(self, req):
        return {"token": self.token, "version": __version__, "platform": sys.platform,
                "capabilities": {"review": True, "batch_review": True, "tasks": True, "trash": True, "module_actions": False, "source_upload": True, "ppi_compute": True},
                "decisions_zh": {"approved": "通过，允许下游使用", "rejected": "退回修改", "pending": "暂存待定"}}

    def list_studies(self, req):
        return {"items": self.views.study_cards(trashed=False)}

    def list_trash(self, req):
        return {"items": self.views.study_cards(trashed=True)}

    def get_study(self, req, study_id):
        return self.views.study(study_id)

    def get_module(self, req, study_id, module_id):
        return self.views.module(study_id, module_id, req.query1("run_id"))

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

    def get_task_log(self, req, task_id):
        try:
            return self.tasks.log(task_id, req.query_int("offset", 0))
        except KeyError:
            raise not_found("任务")

    def get_file(self, req, study_id, key):
        path, name, mime = self.views.file(study_id, key)
        inline = req.query1("inline") == "1" and mime.startswith("image/")
        return ("file", path, name, mime, inline)

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
        if codes.get("A01") == "approved" and codes.get("A02") == "approved":
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
        self.views._manifest(study_id)
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
        payload = {k:body.get(k) for k in ("expected_a03","expected_a05","expected_decision_id","action","reviewer","note","excluded_ids","confirmed")}
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
    def dispatch(self, method: str, path: str, req):
        for route_method, pattern, handler in self.compiled:
            match = pattern.match(path)
            if match and route_method == method:
                return handler(req, *match.groups())
        raise not_found("接口 " + path)


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
        def _send(self, status: int, data: bytes, mime: str, csp: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", csp)
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self._cors()
            self.end_headers()
            if self.command != "HEAD":
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
                result = app.dispatch(method, route.path, Request(self, parse_qs(route.query)))
                if isinstance(result, tuple) and result and result[0] == "file":
                    _, path, name, mime, inline = result
                    disposition = ("inline" if inline else "attachment") + "; filename*=UTF-8''" + quote(name, safe="")
                    return self._send(200, Path(path).read_bytes(), mime, FILE_CSP, {"Content-Disposition": disposition})
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
            self._send(200, target.read_bytes(), mime, STATIC_CSP)

    return Handler


def create_server(settings: Settings, port: int = 8765) -> tuple[ThreadingHTTPServer, App]:
    app = App(settings)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    server.daemon_threads = True
    return server, app

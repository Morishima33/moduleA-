"""后台任务登记与调度。

任务状态：queued(排队) → running(运行中) → succeeded(完成) / failed(失败) / cancelled(已取消) / interrupted(已中断)。
规则（问题清单 Q13/Q14，用户同意按建议执行）：
- 同一研究同一时刻只运行一个写入型任务；重复提交返回已有任务，不重复执行。
- 取消会结束子进程；被取消或中断的运行不会被复用，旧文件全部保留。
- 启动失败记为 failed；丢失进程的 running 或过期 queued 记为 interrupted，不自动重跑，由用户点“重试”。
任务索引存在 <runtime_dir>/tasks.sqlite，它只是运行时信息；研究事实仍以 studies/ 下的归档为准。
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import threading
import uuid
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from ..config import LEGACY_SRC, Settings

ACTIVE = ("queued", "running")
KINDS = {"a02_scope_review": "保存疾病范围核验", "a02_sources_retry": "重试A02失败来源", "a06_trial": "15×15全覆盖结合能试算","a06_coverage_confirm":"留存已确认可用范围（不计算结合能）","a06_coverage":"扩大受体可用范围技术核查（不计算批量结合能）","a06_quality":"两遍结构准备与质控（不计算批量结合能）","a03_selection":"保存对接成分候选，等待复核","a06_plan":"确认并保存A06两遍方案","a06_candidates": "生成A06两梯队候选名单", "a05_display": "确认并生成A05展示图表", "a04_identity": "确认并应用A04身份补查方案", "continue": "自动推进到下一人工关口", "source_upload": "分库资料上传与校验", "a01_sources": "整理已上传三库资料", "a04_ppi": "计算A04双分支PPI"}


KINDS["a05_pathway_maps"] = "生成KEGG排名首位命中图"
KINDS['a06_resume'] = '核验原件并续算明确授权的中断批次'
KINDS.update(a01_acquire="获取本研究三库原始资料", a01_resolve="保存A01完整性与身份例外处理", a02_mapping_preview="预览TTD与PharmGKB疾病候选（不改变A02）")
KINDS.update({"a06_display": "生成同批对接图表与矩阵", "a06_auto_connect": "连接本研究对接资料（不评分）", "a06_auto_run": "一次授权自动准备、质控、对接和出图"})
KINDS.update({"normalization_preview": "核查基因身份并生成标准化预览", "normalization_publish": "生成标准化结果，等待整体复核"})
KINDS.update({"a06_figure": "验证并保存对接结果图片", "a06_pair_packages": "整理所选对接出图包",
              "a06_pair_bundle": "汇集所选对接包下载"})
KINDS["a04_plan_selection"] = "保存A04方案受体选择，等待独立复核"
KINDS["a06_plan_input"] = "绑定已复核成分与受体，保存新版A06准备输入"
KINDS["a06_plan_preparation"] = "连接官方来源并准备新方案A06结构与配体（不评分）"
KINDS["a06_plan_pocket_review"] = "复验预测口袋决定并归档新准备版本（不评分）"
KINDS["a06_plan_reference_review"] = "复核明确共晶参考并追加证据（不评分）"
KINDS["a06_plan_reference_preparation"] = "将共晶参考证据绑定新版准备（不评分）"
KINDS["a06_plan_reference_qualification_v2"] = "复算共晶参考并生成新版准备（不评分）"
KINDS["a06_plan_reviewable_preparation"] = "复验同批资料并生成可人工整体复核准备（不评分）"
KINDS["a06_plan_scoring"] = "按已批准新方案准备执行Vina评分，结果待独立复核"
KINDS["a01_plan_acquire"] = "按本方案OB/DL获取A01三库原件（不发布）"
KINDS["a01_plan_publish"] = "按本方案整理三库及HGNC，结果待独立复核"
KINDS["a05_plan_enrichment"] = "按本方案执行GO/KEGG富集，结果待独立复核"
KINDS['plan_stage'] = '按已确认方案执行A02/A03/A04阶段，结果待复核'
KINDS['a03_plan_selection'] = '按本方案生成成分名单，等待独立复核'
KINDS['a06_plan_preparation_ui'] = '明确执行本批新版结构与配体准备（不评分）'
KINDS['a05_plan_display'] = '准备A05分类核译或保存本批明确展示决定（不重算统计）'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int | None) -> bool:
    """只读检测进程；Windows 上 os.kill(pid, 0) 会终止进程，禁止使用。"""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE，无写权限。
        if not handle:
            return ctypes.get_last_error() == 5  # 拒绝访问不代表进程已退出。
        try:
            return kernel.WaitForSingleObject(handle, 0) != 0  # WAIT_OBJECT_0 表示已经退出。
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False
    return True


KINDS["a06_auto_start"] = "一次确认连接、补齐并计算"


class TaskManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = settings.runtime_dir / "tasks.sqlite"
        self.log_dir = settings.runtime_dir / "task_logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')  # 多个worker首次并发启动时串行迁移运行索引。
            db.execute(
                "CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, study_id TEXT, kind TEXT, state TEXT,"
                " pid INTEGER, requested_by TEXT, message_zh TEXT, error_zh TEXT, progress TEXT, log_path TEXT,"
                " created_at TEXT, started_at TEXT, finished_at TEXT)"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
            if "payload" not in columns:
                db.execute("ALTER TABLE tasks ADD COLUMN payload TEXT")
            if 'resource_owner_pid' not in columns:
                db.execute('ALTER TABLE tasks ADD COLUMN resource_owner_pid INTEGER')
        self.reconcile()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:  # 正常提交、异常回滚；SQLite 自身的上下文并不关闭连接。
                yield db
        finally:
            db.close()

    # ---- 查询 ----
    def get(self, task_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._public(row) if row else None

    def list(self, study_id: str | None = None, active_only: bool = False, limit: int = 100) -> list[dict]:
        sql, args = "SELECT * FROM tasks", []
        clauses = []
        if study_id:
            clauses.append("study_id=?")
            args.append(study_id)
        if active_only:
            clauses.append("state IN ('queued','running')")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._connect() as db:
            rows = db.execute(sql, args).fetchall()
        return [self._public(r) for r in rows]

    def active_for(self, study_id: str) -> dict | None:
        tasks = self.list(study_id, active_only=True, limit=1)
        return tasks[0] if tasks else None

    def recovery_source(self, task: dict) -> dict:
        """恢复只接受同请求真实中断的原计算任务，取消或失败不视为中断。"""
        request = json.loads(task['payload'])
        with self._connect() as db:
            rows = db.execute("SELECT task_id,kind,state,payload FROM tasks WHERE study_id=? AND kind IN ('a06_auto_start','a06_auto_run','a06_resume') ORDER BY created_at DESC", (task['study_id'],)).fetchall()
        matches = [r for r in rows if r['task_id'] != task.get('task_id') and json.loads(r['payload'] or '{}').get('request_id') == request['request_id']]
        source = next((r for r in matches if r['kind'] in ('a06_auto_start','a06_auto_run') and r['state'] == 'interrupted'), None)
        if source is None or (matches and matches[0]['state'] in ('cancelled','succeeded','running','queued')):
            raise ValueError('仅能在明确继续后恢复同请求的中断任务；取消、失败或其他研究不适用')
        return {'task_id':source['task_id'],'state':source['state']}

    def _public(self, row: sqlite3.Row) -> dict:
        data = dict(row)
        data["progress"] = json.loads(data["progress"]) if data.get("progress") else None
        data["kind_zh"] = KINDS.get(data["kind"], data["kind"])
        data["state_zh"] = {"queued": "排队中", "running": "运行中", "succeeded": "已完成", "failed": "失败",
                            "cancelled": "已取消", "interrupted": "已中断"}.get(data["state"], data["state"])
        data.pop("payload", None)  # 私有上传输入不进入接口或日志。
        data.pop("pid", None)
        data.pop('resource_owner_pid',None)
        data.pop("log_path", None)
        return data

    # ---- 状态维护 ----
    def reconcile(self) -> None:
        """恢复丢失进程的活动任务；启动阶段保留 30 秒宽限，不自动重跑。"""
        with self._lock:
            self.reconcile_unlocked()

    def claim(self, task_id: str, pid: int) -> bool:
        """由子进程原子认领排队任务；取消或已认领的任务不能重新开始。"""
        with self._connect() as db:
            changed = db.execute(
                "UPDATE tasks SET state='running', pid=?, started_at=? WHERE task_id=? AND state='queued' AND (resource_owner_pid IS NULL OR resource_owner_pid=?)",
                (pid, _now(), task_id,pid),
            ).rowcount
        return changed == 1

    def claim_resources(self,task_id,pid):
        """原子登记实际等待worker，兼容Windows虚拟环境解释器启动器与内部PID不同。"""
        with self._connect() as db:
            return db.execute("UPDATE tasks SET pid=?,resource_owner_pid=? WHERE task_id=? AND state='queued' AND resource_owner_pid IS NULL",
                (pid,pid,task_id)).rowcount==1

    def finish(self, task_id: str, state: str, **fields) -> None:
        """终态只覆盖运行中任务，保留并发取消或中断的决定。"""
        fields = dict(fields, state=state, finished_at=_now())
        keys = ", ".join(f"{key}=?" for key in fields)
        with self._connect() as db:
            db.execute(f"UPDATE tasks SET {keys} WHERE task_id=? AND state='running'", (*fields.values(), task_id))

    def update(self, task_id: str, **fields) -> None:
        """后台子进程用来回写状态、进度和结果说明。"""
        if "progress" in fields and fields["progress"] is not None:
            fields["progress"] = json.dumps(fields["progress"], ensure_ascii=False)
        keys = ", ".join(f"{k}=?" for k in fields)
        with self._connect() as db:
            db.execute(f"UPDATE tasks SET {keys} WHERE task_id=?", (*fields.values(), task_id))

    # ---- 提交、取消、重试 ----
    def submit(self, study_id: str, kind: str, requested_by: str, payload: dict | None = None) -> tuple[dict, bool]:
        """提交任务。返回 (任务, 是否新建)。同一研究已有活动任务时返回该任务。"""
        if kind not in KINDS:
            raise ValueError("未知任务类型：" + kind)
        with self._lock:
            self.reconcile_unlocked()
            existing = self.active_for(study_id)
            if existing:
                return existing, False
            task_id = "task_" + uuid.uuid4().hex
            log_path = self.log_dir / (task_id + ".log")
            with self._connect() as db:
                db.execute("INSERT INTO tasks (task_id, study_id, kind, state, requested_by, log_path, created_at, payload) VALUES (?,?,?,?,?,?,?,?)",
                           (task_id, study_id, kind, "queued", requested_by, str(log_path), _now(), json.dumps(payload, ensure_ascii=False) if payload is not None else None))
            try:
                self._spawn(task_id, log_path)
            except Exception as error:
                self.update(task_id, state="failed", finished_at=_now(),
                            error_zh=f"任务启动失败（{type(error).__name__}）：{error}；请检查 science_python 与运行目录权限后手动重试。")
            return self.get(task_id), True

    def reconcile_unlocked(self) -> None:
        with self._connect() as db:
            rows = db.execute("SELECT task_id, state, pid, created_at FROM tasks WHERE state IN ('queued','running')").fetchall()
            for row in rows:
                if _pid_alive(row["pid"]):
                    continue
                if row["state"] == "queued":
                    try:
                        created = datetime.fromisoformat(row["created_at"])
                        if (datetime.now(timezone.utc) - created).total_seconds() < 30:
                            continue
                    except (TypeError, ValueError):
                        pass
                db.execute("UPDATE tasks SET state='interrupted', finished_at=?, error_zh=? WHERE task_id=? AND state IN ('queued','running')",
                           (_now(), "任务进程已不存在；不会自动重跑，请确认后手动重试。", row["task_id"]))

    def _spawn(self, task_id: str, log_path: Path) -> None:
        """用配置的科学解释器启动子进程：python -m modulea task-run <task_id>。"""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(LEGACY_SRC) + os.pathsep + env.get("PYTHONPATH", "")
        env["MODULEA_DATA_ROOT"] = str(self.settings.data_root)
        self.settings.validate_resources()
        env['MODULEA_COMPUTE_SLOTS'] = str(self.settings.compute_slots)
        env['MODULEA_COMPUTE_MIN_FREE_BYTES'] = str(self.settings.compute_min_free_bytes)
        if self.settings.science_rscript:
            env["MODULEA_RSCRIPT"] = str(self.settings.science_rscript)
        if self.settings.science_tools_root:
            env["MODULEA_SCIENCE_TOOLS_ROOT"] = str(self.settings.science_tools_root)
        if self.settings.science_repair_packages:
            env["MODULEA_SCIENCE_REPAIR_PACKAGES"] = str(self.settings.science_repair_packages)
        command = [self.settings.science_python, "-m", "modulea", "--runtime-dir", str(self.settings.runtime_dir), "task-run", task_id]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with open(log_path, "ab") as stream:
            process = subprocess.Popen(command, cwd=str(self.settings.project_root), env=env, stdout=stream, stderr=subprocess.STDOUT,
                                       creationflags=flags, start_new_session=(os.name != "nt"))
        # 启动器PID只在worker尚未认领时登记，不能覆盖真实worker/取消/运行态。
        with self._connect() as db:
            db.execute("UPDATE tasks SET pid=? WHERE task_id=? AND state='queued' AND resource_owner_pid IS NULL",(process.pid,task_id))

    def cancel(self, task_id: str) -> dict:
        task = self._raw(task_id)
        if not task:
            raise KeyError(task_id)
        if task["state"] not in ACTIVE:
            return self.get(task_id)
        if _pid_alive(task["pid"]):
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(task["pid"]), "/T", "/F"], capture_output=True)
                else:
                    os.killpg(task["pid"], signal.SIGTERM)
            except OSError:
                pass
        self.update(task_id, state="cancelled", finished_at=_now(), error_zh="用户取消；本次未完整提交的运行不可复用，原文件保留")
        if task["kind"] in ("a06_auto_run", "a06_auto_start", "a06_resume"):
            from ..core.kernel import Kernel
            payload = json.loads(task["payload"])
            Kernel(self.settings).workflow().fail_automatic(task["study_id"], payload["request_id"], "用户取消，已有原件和尝试保留")
        if task["kind"] == "a06_trial":
            from ..core.kernel import Kernel
            workflow = Kernel(self.settings).workflow()
            for record in workflow.load(task["study_id"]).get("docking_trial_records", []):
                if record.get("payload", {}).get("task_id") == task_id:
                    workflow.stop_trial(task["study_id"], record["trial_id"], "用户取消；本次未完整运行不可复用")
        return self.get(task_id)

    def retry(self, task_id: str, requested_by: str) -> tuple[dict, bool]:
        task = self._raw(task_id)
        if not task:
            raise KeyError(task_id)
        if task["state"] in ACTIVE:
            return self.get(task_id), False
        if task['kind'] in ('a06_auto_start','a06_auto_run','a06_resume') and task.get('payload'):
            request = json.loads(task['payload'])
            if request.get('policy_version') == 'A06.automatic.3' and task['state'] != 'cancelled':
                from ..core.kernel import Kernel
                from storage import read_json, verified_file
                workflow = Kernel(self.settings).workflow()
                manifest = workflow.load(task['study_id'])
                batch = workflow.automatic_record(manifest,request['request_id'])
                if batch and batch.get('state') == 'running' and batch.get('run_id') == manifest['current'].get('A06'):
                    # 重试恢复原授权，不能把首次expected_a06旧值当作新建一批的请求。
                    authorization = read_json(verified_file(workflow.location(task['study_id']),batch['authorization']))
                    payload = authorization['request']
                    self.recovery_source(dict(task,payload=json.dumps(payload)))
                    return self.submit(task['study_id'],'a06_resume',requested_by,payload)
        return self.submit(task["study_id"], task["kind"], requested_by, json.loads(task["payload"]) if task.get("payload") else None)

    def log(self, task_id: str, offset: int = 0, limit: int = 65536) -> dict:
        task = self._raw(task_id)
        if not task:
            raise KeyError(task_id)
        offset = max(0, offset)
        path = Path(task["log_path"])
        if not path.exists():
            return {"offset": offset, "next_offset": offset, "text": ""}
        with path.open("rb") as stream:
            stream.seek(max(0, offset))
            data = stream.read(limit)
        return {"offset": offset, "next_offset": offset + len(data), "text": data.decode("utf-8", errors="replace")}

    def _raw(self, task_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return dict(row) if row else None

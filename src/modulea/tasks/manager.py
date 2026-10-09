"""后台任务登记与调度。

任务状态：queued(排队) → running(运行中) → succeeded(完成) / failed(失败) / cancelled(已取消) / interrupted(已中断)。
规则（问题清单 Q13/Q14，用户同意按建议执行）：
- 同一研究同一时刻只运行一个写入型任务；重复提交返回已有任务，不重复执行。
- 取消会结束子进程；被取消或中断的运行不会被复用，旧文件全部保留。
- 服务重启时，记录为 running 但进程已不存在的任务标记为 interrupted，不自动重跑，由用户点“重试”。
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
from datetime import datetime, timezone
from pathlib import Path

from ..config import LEGACY_SRC, Settings

ACTIVE = ("queued", "running")
KINDS = {"continue": "自动推进到下一人工关口"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int | None) -> bool:
    """判断进程是否仍在运行。"""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


class TaskManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = settings.runtime_dir / "tasks.sqlite"
        self.log_dir = settings.runtime_dir / "task_logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, study_id TEXT, kind TEXT, state TEXT,"
                " pid INTEGER, requested_by TEXT, message_zh TEXT, error_zh TEXT, progress TEXT, log_path TEXT,"
                " created_at TEXT, started_at TEXT, finished_at TEXT)"
            )
        self.reconcile()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

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

    def _public(self, row: sqlite3.Row) -> dict:
        data = dict(row)
        data["progress"] = json.loads(data["progress"]) if data.get("progress") else None
        data["kind_zh"] = KINDS.get(data["kind"], data["kind"])
        data["state_zh"] = {"queued": "排队中", "running": "运行中", "succeeded": "已完成", "failed": "失败",
                            "cancelled": "已取消", "interrupted": "已中断"}.get(data["state"], data["state"])
        data.pop("pid", None)
        data.pop("log_path", None)
        return data

    # ---- 状态维护 ----
    def reconcile(self) -> None:
        """把进程已经不存在的运行中任务标记为中断。"""
        with self._lock, self._connect() as db:
            for row in db.execute("SELECT task_id, pid FROM tasks WHERE state='running'").fetchall():
                if not _pid_alive(row["pid"]):
                    db.execute("UPDATE tasks SET state='interrupted', finished_at=?, error_zh=? WHERE task_id=?",
                               (_now(), "任务进程已不存在（工作台关闭或进程异常退出）；不会自动重跑，请确认后重试", row["task_id"]))

    def update(self, task_id: str, **fields) -> None:
        """后台子进程用来回写状态、进度和结果说明。"""
        if "progress" in fields and fields["progress"] is not None:
            fields["progress"] = json.dumps(fields["progress"], ensure_ascii=False)
        keys = ", ".join(f"{k}=?" for k in fields)
        with self._connect() as db:
            db.execute(f"UPDATE tasks SET {keys} WHERE task_id=?", (*fields.values(), task_id))

    # ---- 提交、取消、重试 ----
    def submit(self, study_id: str, kind: str, requested_by: str) -> tuple[dict, bool]:
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
                db.execute("INSERT INTO tasks (task_id, study_id, kind, state, requested_by, log_path, created_at) VALUES (?,?,?,?,?,?,?)",
                           (task_id, study_id, kind, "queued", requested_by, str(log_path), _now()))
            self._spawn(task_id, log_path)
            return self.get(task_id), True

    def reconcile_unlocked(self) -> None:
        with self._connect() as db:
            for row in db.execute("SELECT task_id, pid FROM tasks WHERE state='running'").fetchall():
                if not _pid_alive(row["pid"]):
                    db.execute("UPDATE tasks SET state='interrupted', finished_at=? WHERE task_id=?", (_now(), row["task_id"]))

    def _spawn(self, task_id: str, log_path: Path) -> None:
        """用配置的科学解释器启动子进程：python -m modulea task-run <task_id>。"""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(LEGACY_SRC) + os.pathsep + env.get("PYTHONPATH", "")
        env["MODULEA_DATA_ROOT"] = str(self.settings.data_root)
        command = [self.settings.science_python, "-m", "modulea", "--runtime-dir", str(self.settings.runtime_dir), "task-run", task_id]
        stream = open(log_path, "ab")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(command, cwd=str(self.settings.project_root), env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   creationflags=flags, start_new_session=(os.name != "nt"))
        stream.close()
        self.update(task_id, pid=process.pid)

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
        return self.get(task_id)

    def retry(self, task_id: str, requested_by: str) -> tuple[dict, bool]:
        task = self._raw(task_id)
        if not task:
            raise KeyError(task_id)
        if task["state"] in ACTIVE:
            return self.get(task_id), False
        return self.submit(task["study_id"], task["kind"], requested_by)

    def log(self, task_id: str, offset: int = 0, limit: int = 65536) -> dict:
        task = self._raw(task_id)
        if not task:
            raise KeyError(task_id)
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

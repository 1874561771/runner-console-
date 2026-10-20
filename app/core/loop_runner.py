"""LoopRunner：单环境循环执行器（迁移重构自 webui/jobs.py 的 LoopRunner）。

与原版的关键差异：
1. run_id 获取改为契约优先：Popen 后轮询 console 文件捕获 ``RUN_ID: xxx``
   行（RUN_ID_LINE_RE，60s 超时）；兜底才扫 artifacts 目录
   （_newest_run_id/_detect_run_id 保留，命中兜底记 warning）。
2. 每轮 iteration 结束调用 app.ingest.run_ingest.ingest_run()（T5 实现；
   ImportError/异常仅告警，不中断循环，T5 完成后自动生效）。
3. DB 写入走 app.db.dao.loops；jobs 表不再写 passed/total（归 runs 表）。
4. Popen 注入 PYTHONIOENCODING=utf-8 到子进程 env。
5. pause_on_fail 语义保留：fail/setup_fail 停止循环，终态由原 'paused'
   收敛为 'failed'（新 schema loops.status 枚举无 paused）。
6. 每轮结束后 env_lock.update 写入 run_id、_cleanup 时 release 保留。
7. 停止语义对齐原版 webui：request_stop() 置位标记并 terminate 正在运行
   的 iteration 子进程（STOP 立即生效）；准备阶段到达的 STOP 会跳过本次
   iteration。
8. artifacts 清理（原 manager.prune_artifacts）移除——T6 retention 负责。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from app.core import env_lock, git_worktree
from app.db.dao import loops as loops_dao

if TYPE_CHECKING:
    from app.core.job_manager import JobManager

logger = logging.getLogger("runnerconsole.core.loop_runner")

# 产物目录 run id：YYYYMMDDHHMMSS[_n]
RUN_ID_RE = re.compile(r"^(\d{14})(_\d+)?$")
# runner 契约行：console 中打印 ``RUN_ID: <run_id>``
RUN_ID_LINE_RE = re.compile(r"^RUN_ID:\s*(\S+)")
# 契约行捕获超时（秒）
RUN_ID_CAPTURE_TIMEOUT_S = 60.0
# console 轮询间隔（秒）
_RUN_ID_POLL_INTERVAL_S = 0.5

_INGEST_UNAVAILABLE = False  # app.ingest.run_ingest 缺失时只告警一次


class LoopStartError(Exception):
    """loop 无法启动（参数非法 / 环境锁被占用等）。"""

    def __init__(
        self,
        message: str,
        *,
        holder: dict | None = None,
        lock_payload: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.holder = holder
        self.lock_payload = lock_payload or {}


class LoopStopError(Exception):
    """对不存在或未运行的 loop 执行 stop。"""


class LoopRunner:
    """One repeat-loop occupying a single environment."""

    def __init__(
        self,
        *,
        manager: "JobManager",
        loop_id: str,
        command: list[str],
        cwd: Path,
        workdir: Path,
        worktrees_root: Path,
        lock_dir: Path,
        env_file: Path | None,
        git_ref: str,
        use_worktree: bool,
        overlays: list[tuple[str, Path]],
        repeat: int,
        pause_on_fail: bool,
        owner: str,
        owner_id: int,
        env_id: str | None,
        runner_py: str,
        artifacts_dir: Path,
        console_log: Path,
    ) -> None:
        self.manager = manager
        self.loop_id = loop_id
        self.base_command = command
        self.workdir = workdir
        self.worktrees_root = worktrees_root
        self.lock_dir = lock_dir
        self.env_file = env_file
        self.git_ref = git_ref
        self.use_worktree = use_worktree
        self.overlays = overlays
        self.repeat_total = repeat
        self.pause_on_fail = pause_on_fail
        self.owner = owner
        self.owner_id = owner_id
        self.env_id = env_id
        self.runner_py = runner_py
        self.artifacts_dir = artifacts_dir
        self.console_log = console_log
        self.cwd = cwd

        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.started_at: float | None = None
        self.exit_code: int | None = None
        self.lock_token: str | None = None
        self.iteration = 0
        self.looping = True
        self.loop_stop = threading.Event()
        self._console_mark = 0
        self._job_setup_failed = False
        self.worktree: Path | None = None
        self.current_job_id: str | None = None
        self.current_run_id: str | None = None
        self._last_status: str | None = None

    # ---------------------------------------------------------- lifecycle

    def snapshot(self) -> dict:
        with self.lock:
            running = self.proc is not None and self.proc.poll() is None
            return {
                "loop_id": self.loop_id,
                "running": running,
                "looping": self.looping,
                "loop_stopping": self.looping and self.loop_stop.is_set(),
                "repeat_total": self.repeat_total,
                "pause_on_fail": self.pause_on_fail,
                "iteration": self.iteration,
                "started_at": self.started_at,
                "exit_code": self.exit_code,
                "pid": self.proc.pid if self.proc else None,
                "run_id": self.current_run_id,
                "command": self.base_command,
                "owner": self.owner,
                "owner_id": self.owner_id,
                "env_id": self.env_id,
            }

    def request_stop(self) -> bool:
        """停止循环：置位标记并终止正在运行的 iteration 子进程。

        对齐原版 webui 行为——STOP 立即生效（不等当前 case 自然跑完）。
        返回 True 表示停止时有子进程在运行（已被 terminate）。
        """
        with self.lock:
            self.loop_stop.set()
            proc = self.proc
            running = proc is not None and proc.poll() is None
        if running:
            self._append_console("\n[loop] 收到 STOP：终止当前 iteration 子进程\n")
            try:
                proc.terminate()
            except OSError:
                pass
        return running

    def start(self) -> None:
        """获取环境锁并启动循环线程；锁被占用时抛 LoopStartError。"""
        ok, holder = env_lock.acquire(
            self.lock_dir,
            run_id=None,
            source="runnerconsole",
            command=self.base_command,
            extra={"owner": self.owner, "loop_id": self.loop_id},
        )
        if not ok:
            raise LoopStartError(
                f"环境被占用：{env_lock.describe(holder)}",
                holder=holder,
                lock_payload=env_lock.info_payload(self.lock_dir),
            )
        self.lock_token = holder["token"]
        threading.Thread(
            target=self._run_loop, daemon=True, name=f"loop-{self.loop_id}"
        ).start()

    def _run_loop(self) -> None:
        reason = "loop ended"
        try:
            while not self.loop_stop.is_set():
                with self.lock:
                    if self.repeat_total != 0 and self.iteration >= self.repeat_total:
                        reason = f"all {self.repeat_total} iterations completed"
                        break
                self._one_iteration()
                with self.lock:
                    if self.exit_code == 2 and not self._job_setup_failed:
                        reason = "runner could not start at all (exit 2)"
                        break
                    if self.pause_on_fail and getattr(self, "_last_status", None) in (
                        "fail", "setup_fail",
                    ):
                        reason = (
                            "pause on fail "
                            f"(iteration {self.iteration} status={self._last_status})"
                        )
                        break
                    if self.repeat_total != 0 and self.iteration >= self.repeat_total:
                        reason = f"all {self.repeat_total} iterations completed (last exit={self.exit_code})"
                        break
                    if self.loop_stop.is_set():
                        reason = "user pressed STOP"
                        break
                # 原版此处调用 manager.prune_artifacts()；T6 retention 负责，已移除。
                gap = 30.0 if self._job_setup_failed else 2.0
                # interruptible wait
                if self.loop_stop.wait(gap):
                    reason = "user pressed STOP"
                    break
            else:
                reason = "user pressed STOP"
        except Exception as exc:
            reason = f"loop error: {exc}"
            self._append_console(f"\n[loop error] {exc}\n")
        finally:
            # 原版 finally 中的 prune_artifacts 同样移除（T6）。
            self._cleanup_tmp_overlays()
            self._cleanup(reason)

    # ------------------------------------------------------- one iteration

    def _one_iteration(self) -> None:
        job_id = uuid.uuid4().hex[:12]
        cwd = self.workdir
        wt: Path | None = None
        try:
            if self.use_worktree:
                dest = self.worktrees_root / f"{self.loop_id}_{job_id}"
                wt = git_worktree.prepare_worktree(self.workdir, dest, self.git_ref or "HEAD")
                git_worktree.link_artifacts(wt, self.artifacts_dir)
                if self.env_file and self.env_file.is_file():
                    git_worktree.copy_env(wt, self.env_file)
                for rel, src in self.overlays:
                    git_worktree.overlay_file(wt, rel, src)
                cwd = wt
            else:
                if self.env_file and self.env_file.is_file():
                    dest_env = self.workdir / "framework" / "firebox" / ".firebox_env"
                    dest_env.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(self.env_file, dest_env)
        except git_worktree.GitError as exc:
            self._append_console(f"\n[git] {exc}\n")
            with self.lock:
                self.iteration += 1
                self.exit_code = 2
                self._job_setup_failed = False
            loops_dao.insert_job(
                job_id=job_id, loop_id=self.loop_id, owner_id=self.owner_id,
                env_id=self.env_id, iteration=self.iteration, git_ref=self.git_ref,
            )
            loops_dao.update_job_result(
                job_id, status="fail", exit_code=2, failed_reason=str(exc),
            )
            with self.lock:
                self._last_status = "fail"
            return

        mark_before = self._newest_run_id()
        started = time.time()
        with self.lock:
            self.iteration += 1
            self.started_at = started
            self.exit_code = None
            self.worktree = wt
            self.current_job_id = job_id
            self.current_run_id = None
            self.cwd = cwd

        loops_dao.insert_job(
            job_id=job_id, loop_id=self.loop_id, owner_id=self.owner_id,
            env_id=self.env_id, iteration=self.iteration, git_ref=self.git_ref,
        )

        self.console_log.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if self.iteration == 1 else "a"
        with open(self.console_log, mode, encoding="utf-8", errors="replace") as fh:
            total = "∞" if self.repeat_total == 0 else str(self.repeat_total)
            if mode == "a":
                fh.write(f"\n===== iteration {self.iteration}/{total} =====\n")
            fh.flush()
            self._console_mark = fh.buffer.tell()
            kwargs: dict = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            cmd = list(self.base_command)
            cmd[0] = self.runner_py
            child_env = dict(os.environ)
            child_env["PYTHONIOENCODING"] = "utf-8"
            if self.loop_stop.is_set():
                # STOP 在准备阶段就到达：不再启动子进程，跳过本次 iteration
                self._append_console("\n[loop] 收到 STOP——跳过本次 iteration\n")
                return
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=fh,
                stderr=subprocess.STDOUT,
                text=True,
                env=child_env,
                **kwargs,
            )

        # 契约优先：console 流捕获 RUN_ID 行（60s 超时，子进程提前退出则提前结束）
        run_id = self._capture_run_id_from_console()
        try:
            code = self.proc.wait()
        except Exception:
            code = None

        if run_id is None:
            # 兜底：扫 artifacts 目录（保留原逻辑）
            run_id = self._detect_run_id(mark_before, started)
            if run_id:
                logger.warning(
                    "loop %s iteration %s: RUN_ID 契约行未捕获，兜底扫目录得到 run_id=%s",
                    self.loop_id, self.iteration, run_id,
                )

        summary = _load_summary(self.artifacts_dir, run_id) if run_id else None
        setup_fail = self._detect_job_setup_failure()
        status = _job_status(code, summary, setup_fail)
        loops_dao.update_job_result(
            job_id,
            run_id=run_id,
            status=status,
            exit_code=code,
            job_duration_s=summary.get("job_duration_s") if summary else None,
            failed_reason=(summary.get("failed_reason") or "") if summary else None,
            job_setup_failed=bool(setup_fail),
        )

        with self.lock:
            self.exit_code = code
            self._job_setup_failed = setup_fail
            self.current_run_id = run_id
            self._last_status = status
            self.proc = None

        if wt is not None:
            try:
                git_worktree.remove_worktree(self.workdir, wt)
            except Exception:
                pass
            self.worktree = None

        env_lock.update(self.lock_dir, self.lock_token or "", run_id=run_id)

        # 每轮 iteration 结束：run 入库（T5 实现；未就绪/异常只告警不中断）
        if run_id:
            job_row = loops_dao.get_job(job_id)
            if job_row:
                self._maybe_ingest(job_row, run_id)

    # ------------------------------------------------------------ run id

    def _capture_run_id_from_console(
        self, timeout_s: float = RUN_ID_CAPTURE_TIMEOUT_S
    ) -> str | None:
        """轮询 console 文件，捕获 ``RUN_ID: xxx`` 契约行。

        从 self._console_mark（本轮起始字节）开始增量读取，只解析完整行；
        捕获成功、超时或子进程退出（且无新输出）时返回。
        """
        deadline = time.monotonic() + timeout_s
        buf = ""
        while time.monotonic() < deadline:
            try:
                with open(self.console_log, "rb") as fh:
                    fh.seek(self._console_mark)
                    chunk = fh.read()
            except OSError:
                chunk = b""
            if chunk:
                self._console_mark += len(chunk)
                buf += chunk.decode("utf-8", errors="replace")
                lines = buf.split("\n")
                buf = lines[-1]  # 末尾可能是半行，留到下一轮
                for line in lines[:-1]:
                    m = RUN_ID_LINE_RE.match(line.strip())
                    if m:
                        return m.group(1)
            elif self.proc is not None and self.proc.poll() is not None:
                return None
            time.sleep(_RUN_ID_POLL_INTERVAL_S)
        return None

    def _newest_run_id(self) -> str | None:
        best = None
        if self.artifacts_dir.is_dir():
            for p in self.artifacts_dir.iterdir():
                if p.is_dir() and RUN_ID_RE.match(p.name):
                    if best is None or p.name > best:
                        best = p.name
        return best

    def _detect_run_id(self, before: str | None, started: float) -> str | None:
        stamp = time.strftime("%Y%m%d%H%M%S", time.localtime(started))
        best = None
        if self.artifacts_dir.is_dir():
            for p in self.artifacts_dir.iterdir():
                m = RUN_ID_RE.match(p.name)
                if not (p.is_dir() and m):
                    continue
                if before and p.name <= before:
                    continue
                if m.group(1) >= stamp or (before and p.name > before):
                    if best is None or p.name > best:
                        best = p.name
        return best

    def _detect_job_setup_failure(self) -> bool:
        try:
            size = self.console_log.stat().st_size
            if size <= self._console_mark:
                return False
            with open(self.console_log, "rb") as fh:
                fh.seek(self._console_mark)
                chunk = fh.read()
            return "job setup failed" in chunk.decode("utf-8", errors="replace").lower()
        except Exception:
            return False

    # ------------------------------------------------------------ ingest

    def _maybe_ingest(self, job_row: dict, run_id: str) -> None:
        """调 app.ingest.run_ingest.ingest_run(job_row, run_id, artifacts_dir)。

        T5 未实现（ImportError）或运行异常时只告警，不中断循环。
        """
        global _INGEST_UNAVAILABLE
        try:
            from app.ingest.run_ingest import ingest_run  # noqa: PLC0415
        except ImportError:
            if not _INGEST_UNAVAILABLE:
                logger.warning(
                    "app.ingest.run_ingest 尚未实现（T5），暂跳过 run 入库；"
                    "T5 完成后自动生效"
                )
                _INGEST_UNAVAILABLE = True
            return
        except Exception as exc:  # pragma: no cover - 防御性
            logger.warning("ingest 模块导入异常（跳过本轮入库）: %s", exc)
            return
        try:
            ingest_run(job_row, run_id, self.artifacts_dir)
        except Exception as exc:
            logger.warning(
                "ingest_run 失败（job=%s run=%s）: %s", job_row.get("id"), run_id, exc
            )

    # ----------------------------------------------------------- console

    def _append_console(self, text: str) -> None:
        try:
            self.console_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.console_log, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(text)
        except OSError:
            pass

    # ----------------------------------------------------------- cleanup

    def _cleanup_tmp_overlays(self) -> None:
        """删除 data/console/tmp 下的临时 overlay 源文件（勾选 Case 生成的临时 suite）。

        worktree 内的副本随 worktree 清理消失；这里的源文件若不删会积压。
        只删 console tmp 目录内的，uploads 等其它 overlay 源不受影响。
        """
        try:
            from app.api.common import console_dir  # 局部导入避免环

            tmp_root = (console_dir() / "tmp").resolve()
        except Exception:
            return
        for _rel, src in self.overlays:
            try:
                if tmp_root in src.resolve().parents:
                    src.unlink(missing_ok=True)
            except OSError:
                pass

    def _cleanup(self, reason: str) -> None:
        self._append_console(
            f"\n[loop stopped] iteration {self.iteration}/{self.repeat_total or '∞'}, "
            f"exit_code={self.exit_code}, reason: {reason}\n"
        )
        env_lock.release(self.lock_dir, self.lock_token)
        if self.loop_stop.is_set():
            status = "stopped"
        elif reason.startswith("pause on fail"):
            # 原 webui 终态 'paused'，新 schema 枚举收敛为 'failed'
            status = "failed"
        else:
            status = "done"
        try:
            loops_dao.update_loop_status(self.loop_id, status, stop_reason=reason)
        except Exception:
            logger.exception("loop %s 终态写库失败（status=%s）", self.loop_id, status)
        with self.lock:
            self.looping = False
            self.lock_token = None
        self.manager.drop(self.loop_id)


# ------------------------------------------------------------- helpers

def _load_summary(artifacts_dir: Path, run_id: str) -> dict | None:
    p = artifacts_dir / run_id / "summary.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _job_status(code: int | None, summary: dict | None, setup_fail: bool) -> str:
    """jobs.status 判定（原逻辑；'incomplete' 收敛为 'broken'——新枚举无 incomplete）。

    passed/total 只用于本地判定 status；不入 jobs 表（归 runs，T5 ingest）。
    """
    if setup_fail:
        return "setup_fail"
    if summary:
        total = summary.get("total") or 0
        passed = summary.get("passed") or 0
        if total and passed == total:
            return "pass"
        return "fail"
    if code == 0:
        return "pass"
    if code is None:
        return "broken"
    return "fail"

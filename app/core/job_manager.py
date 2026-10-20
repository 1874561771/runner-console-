"""JobManager：loop 注册表与生命周期管理（迁移重构自 webui/jobs.py 的 JobManager）。

与原版的关键差异：
1. start() 锁 acquire 失败改为抛 LoopStartError（携带持有者描述与锁信息），
   不再返回 (False, msg, holder) 三元组。
2. stop() 协作式：置 stop_requested，当前 iteration 结束后停止；
   不再 terminate 子进程；对不存在/未运行的 loop 抛 LoopStopError。
3. recover_orphans()：启动时回收 DB 中 status='running' 的孤儿 loop——
   锁文件存在且 holder pid 存活 → 保留 running 并返回告警（管理页提示
   人工介入）；pid 已死或无锁 → loop 置 stopped（stop_reason=
   'recovered orphan on startup'）并清锁。main.py lifespan 中调用。
4. 不做 artifacts 清理（原 prune_artifacts 删除）——T6 retention 负责。
5. 路径全部来自 config.paths：workdir / artifacts_root / console_dir（env
   与数据根，environments.relpath 相对它）/ consoles_dir（loop console 日志）；
   worktree 根 = console_dir/worktrees。
"""

from __future__ import annotations

import logging
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.core import env_lock, git_worktree
from app.core.loop_runner import (
    LoopRunner,
    LoopStartError,
    LoopStopError,
)
from app.db.dao import audit as audit_dao
from app.db.dao import loops as loops_dao

__all__ = [
    "JobManager",
    "LoopStartError",
    "LoopStopError",
    "build_command",
    "PRODUCTS",
    "get_job_manager",
    "init_job_manager",
]

logger = logging.getLogger("runnerconsole.core.job_manager")

PRODUCTS = ["firebox", "fccm"]


def _operator_name(user: dict | None) -> str | None:
    """从 user dict 取操作者用户名（审计 detail 用）。"""
    if not user:
        return None
    return str(user.get("username") or "")


def _actor_id(user: dict | None) -> int | None:
    """从 user dict 取操作者 users.id（audit.actor_id 用）。"""
    if not user:
        return None
    try:
        return int(user.get("id") or user.get("user_id"))
    except (TypeError, ValueError):
        return None


def build_command(
    params: dict, runner_py: str
) -> tuple[list[str], str | None]:
    """拼接 runner CLI 命令（迁移自 webui/server.py build_command）。

    返回 (命令列表, 错误消息)；合法时错误消息为 None。
    命令文本由调用方写入 loops.command。
    """
    product = params.get("product")
    if product not in PRODUCTS:
        return [], "product must be one of: " + ", ".join(PRODUCTS)
    suite = params.get("suite")
    test = params.get("test")
    if suite and test:
        return [], "Use either suite or test, not both"
    if not suite and not test:
        return [], "Required: suite or test"
    fw_branch = (params.get("branch") or params.get("firmware_branch") or "").strip()
    fw_build = (params.get("build") or params.get("firmware_build") or "").strip()
    if fw_build and not fw_branch:
        return [], "固件 Build 需要同时填写固件 Branch"
    cmd = [runner_py, "-m", "runner", "--product", product]
    if suite:
        cmd += ["--suite", suite]
    if test:
        cmd += ["--test", test]
    if params.get("headless"):
        cmd += ["--headless", "true"]
    if fw_branch:
        cmd += ["--branch", fw_branch]
    if fw_build:
        cmd += ["--build", fw_build]
    return cmd, None


def _resolve_runner_py(workdir: Path) -> str:
    """优先用 workdir/.venv 里的解释器跑 runner，否则用当前解释器。"""
    if sys.platform.startswith("win"):
        cand = workdir / ".venv" / "Scripts" / "python.exe"
    else:
        cand = workdir / ".venv" / "bin" / "python"
    return str(cand) if cand.is_file() else sys.executable


class JobManager:
    """内存注册表 {loop_id: LoopRunner}；单例，经 init_job_manager() 创建。"""

    def __init__(
        self,
        *,
        workdir: Path,
        artifacts_root: Path,
        env_root: Path,
        consoles_dir: Path,
        worktrees_root: Path,
        runner_py: str,
    ) -> None:
        self.workdir = workdir
        self.artifacts_root = artifacts_root
        self.env_root = env_root
        self.consoles_dir = consoles_dir
        self.worktrees_root = worktrees_root
        self.runner_py = runner_py
        self._loops: dict[str, LoopRunner] = {}
        self._guard = threading.Lock()

    # ------------------------------------------------------------ paths

    def env_dir_for(self, env_row: dict) -> Path:
        """environments 表 relpath → env 目录（也是锁目录）。"""
        return (self.env_root / str(env_row["relpath"])).resolve()

    def env_file_for(self, env_row: dict) -> Path:
        return self.env_dir_for(env_row) / "firebox.env"

    def console_path_for(self, loop_id: str) -> Path:
        return self.consoles_dir / f"{loop_id}.log"

    # ---------------------------------------------------------- registry

    def get(self, loop_id: str) -> LoopRunner | None:
        with self._guard:
            return self._loops.get(loop_id)

    def active(self) -> list[LoopRunner]:
        with self._guard:
            return [r for r in self._loops.values() if r.looping]

    def drop(self, loop_id: str) -> None:
        with self._guard:
            self._loops.pop(loop_id, None)

    # ------------------------------------------------------------- start

    def start(
        self,
        *,
        user: dict,
        env_row: dict,
        params: dict,
        repeat: int,
        overlays: list[tuple[str, Path]] | None = None,
    ) -> dict:
        """启动一个 loop。

        参数/锁非法 → LoopStartError；环境锁被占用 → LoopStartError
        （message 含持有者描述，.holder/.lock_payload 带原始信息）。
        成功返回 {"loop_id", "command", "repeat"}。
        """
        cmd, err = build_command(params, runner_py=self.runner_py)
        if err:
            raise LoopStartError(err)

        loop_id = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
        git_ref = (params.get("git_ref") or "").strip() or "HEAD"
        use_wt = git_worktree.is_git_repo(self.workdir)
        env_dir = self.env_dir_for(env_row)
        console = self.console_path_for(loop_id)
        owner_id = int(user.get("id") or user.get("user_id"))
        owner_name = str(user.get("username") or "")

        runner = LoopRunner(
            manager=self,
            loop_id=loop_id,
            command=cmd,
            cwd=self.workdir,
            workdir=self.workdir,
            worktrees_root=self.worktrees_root,
            lock_dir=env_dir,
            env_file=self.env_file_for(env_row),
            git_ref=git_ref,
            use_worktree=use_wt,
            overlays=list(overlays or []),
            repeat=repeat,
            pause_on_fail=bool(params.get("pause_on_fail")),
            owner=owner_name,
            owner_id=owner_id,
            env_id=env_row["id"],
            runner_py=self.runner_py,
            artifacts_dir=self.artifacts_root,
            console_log=console,
        )
        # 先落库（status='running'），锁失败时回写 stopped——与原版一致，
        # 保证启动失败也有迹可查。
        loops_dao.insert_loop(
            loop_id=loop_id,
            owner_id=owner_id,
            env_id=env_row["id"],
            product=params.get("product"),
            suite=params.get("suite"),
            test=params.get("test"),
            git_ref=git_ref,
            source=params.get("source") or "repo",
            firmware_branch=params.get("branch") or params.get("firmware_branch"),
            firmware_build=params.get("build") or params.get("firmware_build"),
            headless=bool(params.get("headless")),
            pause_on_fail=bool(params.get("pause_on_fail")),
            repeat_total=repeat,
            command=" ".join(cmd),
        )
        with self._guard:
            self._loops[loop_id] = runner
        try:
            runner.start()
        except LoopStartError as exc:
            loops_dao.update_loop_status(loop_id, "stopped", stop_reason=str(exc))
            raise
        audit_dao.insert_audit(
            owner_id,
            "loop.start",
            {
                "loop_id": loop_id,
                "env_id": env_row["id"],
                "operator": owner_name,
                "product": params.get("product"),
                "suite": params.get("suite"),
                "test": params.get("test"),
                "repeat": repeat,
            },
        )
        return {"loop_id": loop_id, "command": cmd, "repeat": repeat}

    # -------------------------------------------------------------- stop

    def stop(
        self, loop_id: str, *, user: dict | None = None
    ) -> tuple[bool, str]:
        """协作式停止：置 stop_requested，当前 iteration 结束后停止。

        对不存在/未运行的 loop 抛 LoopStopError。
        user 为操作者（写审计用；系统内部调用可传 None）。
        """
        runner = self.get(loop_id)
        if not runner:
            row = loops_dao.get_loop(loop_id)
            if row and row["status"] == "running":
                # DB 挂着 running 但内存没有（如 recover 之前被调用），
                # 收敛为 stopped，避免永久僵尸行。
                loops_dao.update_loop_status(
                    loop_id, "stopped", stop_reason="stop after finish"
                )
            raise LoopStopError("没有正在运行的 loop")
        was_running = runner.request_stop()
        if not was_running and not runner.looping:
            raise LoopStopError("没有正在运行的 loop")
        audit_dao.insert_audit(
            _actor_id(user),
            "loop.stop",
            {
                "loop_id": loop_id,
                "env_id": runner.env_id,
                "operator": _operator_name(user),
            },
        )
        if was_running:
            return True, "已停止：正在运行的 iteration 已被终止"
        return True, "loop 已取消（尚无运行中的迭代）"

    # ----------------------------------------------------------- console

    def console_tail(self, loop_id: str, n: int = 80) -> list[str]:
        path = self.console_path_for(loop_id)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return text.splitlines()[-n:]

    # ------------------------------------------------------------ status

    def get_status(self) -> list[dict]:
        """全部活跃 loop 的快照（管理/状态页轮询用）。"""
        return [r.snapshot() for r in self.active()]

    # ---------------------------------------------------- orphan recover

    def recover_orphans(self) -> list[dict]:
        """启动时回收 DB 中 status='running' 的孤儿 loop。

        * 锁文件存在且 holder pid 存活 → 保留 running，返回告警条目
          （管理页提示人工介入）。
        * pid 已死或无锁 → loop 置 stopped（stop_reason='recovered orphan
          on startup'）并清锁。

        返回告警列表 [{loop_id, env_id, holder, message}, ...]。
        """
        warnings: list[dict] = []
        for row in loops_dao.get_running_loops():
            loop_id = row["id"]
            env_dir: Path | None = None
            if row.get("env_relpath"):
                env_dir = (self.env_root / str(row["env_relpath"])).resolve()
            holder = env_lock.read_lock(env_dir) if env_dir else None
            if holder and env_lock.pid_alive(int(holder.get("pid") or 0)):
                warnings.append({
                    "loop_id": loop_id,
                    "env_id": row.get("env_id"),
                    "holder": env_lock.describe(holder),
                    "message": (
                        f"loop {loop_id} 标记为 running 且环境锁仍被存活进程持有，"
                        "已保留状态，请人工确认后处理"
                    ),
                })
                logger.warning(
                    "orphan loop %s: lock still held by live pid %s, kept as running",
                    loop_id, holder.get("pid"),
                )
                continue
            # pid 已死或无锁 → 回收
            if env_dir:
                env_lock.force_release(env_dir)
            try:
                loops_dao.update_loop_status(
                    loop_id, "stopped", stop_reason="recovered orphan on startup"
                )
            except Exception:
                logger.exception("orphan loop %s 回收写库失败", loop_id)
                continue
            audit_dao.insert_audit(
                None,
                "loop.recovered",
                {
                    "loop_id": loop_id,
                    "env_id": row.get("env_id"),
                    "operator": "system",
                    "stop_reason": "recovered orphan on startup",
                },
            )
            logger.warning(
                "orphan loop %s recovered: no live lock holder, set to stopped", loop_id
            )
        return warnings

    # -------------------------------------------------------- admin lock

    def clear_lock(
        self, env_row: dict, *, user: dict | None = None
    ) -> tuple[bool, str]:
        """管理员清除环境锁；对应 loop 仍在运行时拒绝（迁移自原版 clear_lock）。

        user 为操作者（写审计用；系统内部调用可传 None）。
        """
        env_dir = self.env_dir_for(env_row)
        for r in self.active():
            if r.lock_dir == env_dir and r.proc is not None and r.proc.poll() is None:
                return False, "有任务正在运行，不能清除锁；请先停止"
        removed = env_lock.force_release(env_dir)
        audit_dao.insert_audit(
            _actor_id(user),
            "env.lock.force-release",
            {
                "env_id": env_row["id"],
                "operator": _operator_name(user),
                "removed": removed is not None,
                "holder": env_lock.describe(removed) if removed else None,
            },
        )
        if removed is None:
            return True, "环境已是空闲（没有锁文件）"
        return True, f"已清除锁（原占用：{env_lock.describe(removed)}）"


# ------------------------------------------------------------- singleton

_manager: JobManager | None = None
_manager_guard = threading.Lock()


def init_job_manager() -> JobManager:
    """按 config.paths 创建 JobManager 单例（main.py lifespan 调用一次）。"""
    global _manager
    with _manager_guard:
        if _manager is None:
            cfg = get_settings()
            paths = cfg.paths
            workdir = Path(paths.workdir).expanduser().resolve()
            env_root = Path(paths.console_dir).expanduser().resolve()
            consoles_dir = Path(paths.consoles_dir).expanduser().resolve()
            artifacts_root = Path(paths.artifacts_root).expanduser().resolve()
            worktrees_root = env_root / "worktrees"
            worktrees_root.mkdir(parents=True, exist_ok=True)
            consoles_dir.mkdir(parents=True, exist_ok=True)
            _manager = JobManager(
                workdir=workdir,
                artifacts_root=artifacts_root,
                env_root=env_root,
                consoles_dir=consoles_dir,
                worktrees_root=worktrees_root,
                runner_py=_resolve_runner_py(workdir),
            )
            if not (workdir / "runner.py").is_file():
                logger.warning("runner.py 不存在: %s", workdir / "runner.py")
        return _manager


def get_job_manager() -> JobManager:
    if _manager is None:
        raise RuntimeError("JobManager not initialised: call init_job_manager() first")
    return _manager

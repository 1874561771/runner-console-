"""SSE 路由：loop 控制台实时推送（T8）。

路由：
  GET /api/loops/{loop_id}/console     —— 主路由
  GET /api/streams/console?loop_id=…   —— 兼容 frontend api.js openConsoleStream
                                          现行请求 URL 的别名（行为完全一致）

事件契约：
  event: snapshot  data: {"offset": <byte>, "text": "<尾部 64KB 文本>"}
                   连接建立（且无 Last-Event-ID 或偏移越界）后首发；
  event: append    data: <原始文本块>（多行按 SSE 规范逐行加 data: 前缀），
                   带 id: <块末字节偏移>——EventSource 断线自动重连时
                   携带 Last-Event-ID，服务端从该偏移续读；
  event: reset     data: {}          文件被清理 / Last-Event-ID 越界时先发，
                   随后补发新 snapshot；
  event: end       data: {"status": "done|failed|stopped"}
                   loop 进入终态后发送并关闭连接（含 too_many_subscribers）；
  心跳：每 15s 无事件发 SSE 注释行 ": ping"（防代理空闲断连）。

实现要点：
* 处理函数与事件生成器均为 sync —— FastAPI / Starlette 自动放入线程池
  执行，文件 IO 与 DB 查询都不会阻塞事件循环。
* 认证复用 deps.get_current_user：Cookie rc_session 优先、Bearer 兼容
  （EventSource 不能带 header，浏览器对同源请求自动携带 Cookie）。
* 权限：loop owner 或 admin（perms.can_access_owner），否则 403；
  loop 不存在返回 404。
"""

from __future__ import annotations

import json
import logging
import queue as queue_mod
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.auth import perms
from app.core.job_manager import get_job_manager
from app.db.dao import loops as loops_dao
from app.realtime.console_tail import RESET, TailStream, hub

logger = logging.getLogger("runnerconsole.api.sse")

router = APIRouter()

HEARTBEAT_INTERVAL_S = 15.0    # 无事件时发 ": ping" 的间隔
STATUS_CHECK_INTERVAL_S = 2.0  # loop 终态检查限频（DB 查询节流）


# ---------------------------------------------------------------- helpers

def _sse(event: str, data: str, event_id: str | None = None) -> str:
    """按 SSE 规范编码一条事件（双换行结尾；data 多行逐行加前缀）。"""
    parts: list[str] = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event}")
    for line in data.split("\n"):
        parts.append(f"data: {line}")
    return "\n".join(parts) + "\n\n"


def _normalize(text: str) -> str:
    """CR 归一为 LF（Windows 子进程输出可能带 \\r\\n），避免破坏 SSE 分帧。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _final_status(loop_id: str) -> str | None:
    """loop 终态判定。None = 仍在运行；否则 done/failed/stopped。

    先查内存注册表（JobManager）：runner 存在且循环线程/子进程仍在
    → 运行中；否则查 DB loops.status（dao get_loop）：
    status=='running'（如孤儿 loop 尚未回收）视为仍在运行；
    无 DB 行（已被清理）按 stopped 收敛。
    """
    try:
        runner = get_job_manager().get(loop_id)
    except RuntimeError:
        runner = None
    if runner is not None:
        snap = runner.snapshot()
        if snap["running"] or snap["looping"]:
            return None
    row = loops_dao.get_loop(loop_id)
    if row is None:
        return "stopped"
    status = str(row.get("status") or "")
    if status == "running":
        return None
    return status or "stopped"


# -------------------------------------------------------------- generator

def _console_events(loop_id: str, last_event_id: int | None) -> Iterator[str]:
    try:
        yield from _console_events_inner(loop_id, last_event_id)
    except Exception:
        # 流中途异常：记录后直接关闭连接；EventSource 会自动重连并
        # 携带 Last-Event-ID 从断点续传。
        logger.exception("console SSE 流异常: loop=%s", loop_id)


def _console_events_inner(loop_id: str, last_event_id: int | None) -> Iterator[str]:
    manager = get_job_manager()
    path = manager.console_path_for(loop_id)
    stream = TailStream(path)

    # 1. 初始阶段：Last-Event-ID 断点续传，或全量 snapshot
    if last_event_id is not None:
        if last_event_id > stream.file_size():
            # 偏移越界（文件已被清理重建）：先 reset 再补新 snapshot
            yield _sse("reset", "{}")
            cursor, text = stream.snapshot()
            yield _sse(
                "snapshot",
                json.dumps({"offset": cursor, "text": text}, ensure_ascii=False),
            )
        else:
            cursor = last_event_id  # 不发 snapshot，直接从该偏移续读
    else:
        cursor, text = stream.snapshot()
        yield _sse(
            "snapshot",
            json.dumps({"offset": cursor, "text": text}, ensure_ascii=False),
        )

    # 2. 订阅 Hub（同一 loop 的订阅者共享 tail 线程；第 3 个被拒绝）
    sub = hub.subscribe(loop_id, path, init_offset=cursor)
    if sub is None:
        yield _sse("end", json.dumps({"status": "too_many_subscribers"}))
        return

    try:
        # 空窗补偿：snapshot 与 subscribe 之间的增量直接补读一次；
        # 队列中与 cursor 重叠的回放块由下方重叠跳过逻辑去重。
        new_off, text = stream.read_from(cursor)
        if text:
            cursor = new_off
            yield _sse("append", _normalize(text), event_id=str(cursor))

        last_status_check = 0.0
        while True:
            try:
                item: Any = sub.get(timeout=HEARTBEAT_INTERVAL_S)
            except queue_mod.Empty:
                # 心跳：SSE 注释行，防止代理空闲断连
                yield ": ping\n\n"
            else:
                if item is RESET:
                    # 文件被清理：通知客户端重置，随后补发新 snapshot
                    yield _sse("reset", "{}")
                    cursor, text = stream.snapshot()
                    yield _sse(
                        "snapshot",
                        json.dumps({"offset": cursor, "text": text}, ensure_ascii=False),
                    )
                else:
                    chunk_start, chunk_end, text = item
                    if chunk_start < cursor:
                        # tail 线程的回放块与本地 cursor 重叠：跳过已收部分
                        enc = text.encode("utf-8")
                        skip = cursor - chunk_start
                        if skip >= len(enc):
                            continue
                        text = enc[skip:].decode("utf-8", errors="replace")
                    text = _normalize(text)
                    if not text:  # 空块跳过
                        continue
                    cursor = chunk_end
                    # 增量事件：id = 块末字节偏移（断线续传游标）
                    yield _sse("append", text, event_id=str(cursor))

            # 终态检查（限频，避免每个事件都查 DB）；命中即发 end 并关闭
            now = time.monotonic()
            if now - last_status_check >= STATUS_CHECK_INTERVAL_S:
                last_status_check = now
                status = _final_status(loop_id)
                if status is not None:
                    yield _sse("end", json.dumps({"status": status}))
                    return
    finally:
        hub.unsubscribe(loop_id, sub)


# ----------------------------------------------------------------- routes

def _console_response(loop_id: str, request: Request, user: dict) -> StreamingResponse:
    row = loops_dao.get_loop(loop_id)
    if row is None:
        raise HTTPException(status_code=404, detail="loop not found")
    if not perms.can_access_owner(user, row.get("owner_id")):
        raise HTTPException(status_code=403, detail="forbidden")

    raw = (request.headers.get("last-event-id") or "").strip()
    last_event_id: int | None = None
    if raw:
        try:
            last_event_id = int(raw)
        except ValueError:
            last_event_id = None
        if last_event_id is not None and last_event_id < 0:
            last_event_id = None

    return StreamingResponse(
        _console_events(loop_id, last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/loops/{loop_id}/console")
def stream_loop_console(
    loop_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """loop 控制台 SSE 实时流（EventSource；会话经 Cookie rc_session）。"""
    return _console_response(loop_id, request, user)


@router.get("/api/streams/console")
def stream_console_compat(
    request: Request,
    loop_id: str = "",
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """兼容别名：frontend api.js openConsoleStream 现行请求
    GET /api/streams/console?loop_id=…；与主路由行为完全一致。"""
    if not loop_id:
        raise HTTPException(status_code=400, detail="loop_id is required")
    return _console_response(loop_id, request, user)

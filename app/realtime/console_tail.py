"""控制台实时 tail：文件尾读取 + 共享轮询线程 + 订阅分发（T8）。

组成：
* TailStream —— 单个 console 文件的字节偏移读取器：
  - snapshot()        读文件尾 64KB，返回 (offset, text)，offset 为文本末字节
                      之后的文件位置（即安全的续读游标）；
  - read_from(offset) 从 offset 增量读到 EOF，返回 (new_offset, text)；
    文件变小/被清理返回 (0, None) 作为 RESET 信号。
  多字节 UTF-8 边界（64KB 窗口起点截断、读取时刻的半截写入）一律剔除，
  保证 text 始终落在完整字符边界上，offset 可安全作为 Last-Event-ID 续传游标。

* Hub（模块级单例 hub）—— {loop_id: _Topic}。同一 loop 的多个订阅者共享
  一个 0.5s 轮询（stat + 增量读）的 daemon tail 线程，把增量块广播到每个
  订阅者的 queue；最后一个订阅者断开后线程退出、topic 从注册表摘除。
  单 loop 订阅上限 MAX_SUBSCRIBERS_PER_LOOP（第 3 个 subscribe 返回 None，
  由路由层发 end 事件后关闭）。

线程模型：TailStream 的文件 IO 全部是阻塞调用，只允许在 tail 线程或
Starlette 线程池（sync generator）中执行，禁止在事件循环内直调。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

logger = logging.getLogger("runnerconsole.realtime.console_tail")

SNAPSHOT_WINDOW_BYTES = 64 * 1024  # snapshot 读取文件尾的窗口大小
POLL_INTERVAL_S = 0.5              # tail 线程轮询间隔
MAX_SUBSCRIBERS_PER_LOOP = 2       # 单 loop 订阅上限（第 3 个被拒绝）
QUEUE_CAPACITY = 256               # 订阅者队列深度（约 128s 背压缓冲）

# 队列哨兵：文件被清理/重建，订阅方应重置游标并重新 snapshot
RESET = object()


# ------------------------------------------------------------ utf-8 边界

def _utf8_seq_len(lead: int) -> int:
    """由起始字节判断 UTF-8 序列长度；非法起始字节返回 0。"""
    if lead & 0x80 == 0:
        return 1
    if lead & 0xE0 == 0xC0:
        return 2
    if lead & 0xF0 == 0xE0:
        return 3
    if lead & 0xF8 == 0xF0:
        return 4
    return 0


def _trailing_partial_len(data: bytes) -> int:
    """末尾被截断的多字节 UTF-8 序列长度（0 = 无截断）。"""
    n = len(data)
    if n == 0:
        return 0
    k = n - 1
    # 回扫最多 3 个连续 continuation byte（合法序列最长 4 字节）
    while k >= max(0, n - 3) and (data[k] & 0xC0) == 0x80:
        k -= 1
    if k < 0:
        return 0
    need = _utf8_seq_len(data[k])
    if need <= 1:
        return 0
    have = n - k
    return have if have < need else 0


def _leading_partial_len(data: bytes) -> int:
    """窗口起点切在多字节字符中间时，头部残字节数（合法截断 ≤3）。"""
    i = 0
    while i < len(data) and i < 3 and (data[i] & 0xC0) == 0x80:
        i += 1
    return i


# -------------------------------------------------------------- TailStream

class TailStream:
    """console 文件的字节偏移读取器（阻塞 IO；勿在事件循环内直调）。

    实例无内部可变状态除 text_start（最近一次返回文本的起始字节偏移，
    供 tail 线程计算回放块的 chunk_start），同一实例只被单线程使用。
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.text_start: int = 0

    def file_size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def snapshot(self) -> tuple[int, str]:
        """读文件尾 64KB，返回 (offset, text)。

        offset = text 末字节之后的文件位置（安全续读游标）；
        文件不存在/为空返回 (0, "")。窗口起点切在多字节字符中间时
        丢弃首个残字节的 continuation 部分（≤3 字节）。
        """
        size = self.file_size()
        if size <= 0:
            self.text_start = 0
            return 0, ""
        start = max(0, size - SNAPSHOT_WINDOW_BYTES)
        raw = self._read_range(start, size)
        if not raw:
            self.text_start = 0
            return 0, ""
        lead = _leading_partial_len(raw) if start > 0 else 0
        body = raw[lead:]
        trail = _trailing_partial_len(body)
        if trail:
            body = body[:-trail]
        self.text_start = start + lead
        return start + len(raw) - trail, body.decode("utf-8", errors="replace")

    def read_from(self, offset: int) -> tuple[int, str | None]:
        """从 offset 增量读到 EOF，返回 (new_offset, text)。

        * 文件变大   → (新末偏移, 增量文本)；无增量时 text=""；
        * 文件变小/被清理（size < offset，或文件消失且 offset>0）
                     → (0, None) 即 RESET 信号；
        * 文件不存在且 offset==0 → (0, "")（尚无内容，无需重置）。
        末尾半截写入的多字节字符留到下次读取（new_offset 落在字符边界）。
        """
        try:
            size = self.path.stat().st_size
        except OSError:
            if offset > 0:
                return 0, None
            self.text_start = 0
            return 0, ""
        if size < offset:
            return 0, None
        if size == offset:
            self.text_start = offset
            return offset, ""
        raw = self._read_range(offset, size)
        if not raw:
            self.text_start = offset
            return offset, ""
        trail = _trailing_partial_len(raw)
        kept = raw[:-trail] if trail else raw
        new_off = offset + len(raw) - trail
        self.text_start = offset
        return new_off, kept.decode("utf-8", errors="replace")

    def _read_range(self, start: int, end: int) -> bytes:
        try:
            with open(self.path, "rb") as fh:
                fh.seek(start)
                return fh.read(max(0, end - start))
        except OSError:
            return b""


# ------------------------------------------------------------------ Topic

class _Topic:
    """同一 loop 的共享 tail 线程与订阅者队列。仅经 Hub 访问。"""

    def __init__(self, loop_id: str, path: Path) -> None:
        self.loop_id = loop_id
        self.stream = TailStream(path)
        self.lock = threading.Lock()
        self.subscribers: list[queue.Queue] = []
        # _offset 仅 tail 线程写（启动参数由 subscribe 在 start 前写入，
        # 与线程启动存在 happens-before），读侧为 CPython 原子属性访问
        self._offset: int | None = None
        self._thread: threading.Thread | None = None

    # -- 订阅管理（Hub 保证跨 topic 的 get-or-create 原子性）-----------

    def subscribe(self, init_offset: int | None) -> queue.Queue | None:
        """注册订阅者队列；达到上限返回 None。

        init_offset 仅在 tail 线程尚未启动时作为初始游标（首个订阅者把
        自己的 snapshot offset 传进来，避免 tail 线程从 0 回放整个文件）。
        """
        with self.lock:
            if len(self.subscribers) >= MAX_SUBSCRIBERS_PER_LOOP:
                return None
            sub: queue.Queue = queue.Queue(maxsize=QUEUE_CAPACITY)
            self.subscribers.append(sub)
            if self._thread is None:
                self._offset = init_offset
                self._thread = threading.Thread(
                    target=self._run,
                    name=f"console-tail-{self.loop_id}",
                    daemon=True,
                )
                self._thread.start()
            return sub

    def unsubscribe(self, sub: queue.Queue) -> None:
        with self.lock:
            if sub in self.subscribers:
                self.subscribers.remove(sub)

    def idle(self) -> bool:
        with self.lock:
            return not self.subscribers and self._thread is None

    # -- tail 线程 -----------------------------------------------------

    def _run(self) -> None:
        try:
            while True:
                with self.lock:
                    subs = list(self.subscribers)
                    if not subs:
                        # 最后一个订阅者已断开：清空线程引用并退出。
                        # 退出决策与 subscribe 互斥（同一把锁），
                        # 不会出现"刚有新订阅者线程却退出"的悬挂。
                        self._thread = None
                        return
                self._tick(subs)
                time.sleep(POLL_INTERVAL_S)
        finally:
            need_restart = False
            with self.lock:
                if self._thread is threading.current_thread():
                    # 异常退出兜底（正常退出路径上面已置 None，走不到这里）
                    self._thread = None
                    need_restart = bool(self.subscribers)
            if need_restart:
                self._ensure_thread()
            hub._maybe_reap(self.loop_id)

    def _ensure_thread(self) -> None:
        with self.lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run,
                    name=f"console-tail-{self.loop_id}",
                    daemon=True,
                )
                self._thread.start()

    def _tick(self, subs: list[queue.Queue]) -> None:
        """轮询一次文件并广播增量（阻塞 IO，仅 tail 线程调用）。"""
        offset = self._offset
        if offset is None:
            end_off, text = self.stream.snapshot()
            chunk_start = self.stream.text_start
            self._publish(subs, (chunk_start, end_off, text))
            self._offset = end_off
            return
        new_off, text = self.stream.read_from(offset)
        if text is None:
            self._publish(subs, RESET)
            self._offset = None  # 下一轮重新 snapshot
        elif text:
            self._publish(subs, (offset, new_off, text))
            self._offset = new_off
        else:
            self._offset = new_off

    def _publish(self, subs: list[queue.Queue], item: object) -> None:
        for sub in subs:
            try:
                sub.put_nowait(item)
            except queue.Full:
                # 订阅者消费停滞：剔除以免内存堆积（路由层收尾时 unsubscribe 无副作用）
                with self.lock:
                    if sub in self.subscribers:
                        self.subscribers.remove(sub)
                logger.warning("console tail %s: 订阅者队列已满，剔除该订阅者", self.loop_id)


# -------------------------------------------------------------------- Hub

class Hub:
    """loop → 共享 tail topic 注册表（模块级单例 hub）。"""

    def __init__(self) -> None:
        self._topics: dict[str, _Topic] = {}
        self._guard = threading.Lock()

    def subscribe(
        self, loop_id: str, path: Path, init_offset: int | None
    ) -> queue.Queue | None:
        """取/建 topic 并注册订阅者；满员返回 None。

        get-or-create 与 subscribe 在同一把锁内完成，
        避免与 tail 线程退出回收发生竞态。
        """
        with self._guard:
            topic = self._topics.get(loop_id)
            if topic is None:
                topic = _Topic(loop_id, Path(path))
                self._topics[loop_id] = topic
            return topic.subscribe(init_offset)

    def unsubscribe(self, loop_id: str, sub: queue.Queue) -> None:
        with self._guard:
            topic = self._topics.get(loop_id)
        if topic is not None:
            topic.unsubscribe(sub)
            self._maybe_reap(loop_id)

    def _maybe_reap(self, loop_id: str) -> None:
        """无订阅者且线程已退出的 topic 从注册表摘除（tail 线程 finally 调用）。"""
        with self._guard:
            topic = self._topics.get(loop_id)
            if topic is not None and topic.idle():
                self._topics.pop(loop_id, None)


hub = Hub()

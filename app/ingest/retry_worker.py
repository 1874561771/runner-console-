"""后台补偿未成功入库的已结束 jobs。"""

from __future__ import annotations

import logging
import threading

from app.ingest.run_ingest import retry_pending_ingest

logger = logging.getLogger("runnerconsole.ingest.retry")


class IngestRetryWorker:
    def __init__(self, interval_seconds: float = 60.0, batch_size: int = 200) -> None:
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="ingest-retry",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                count = retry_pending_ingest(self.batch_size)
                if count:
                    logger.info("ingest compensation completed: %s runs", count)
            except Exception:
                logger.exception("ingest compensation failed")
            if self._stop.wait(self.interval_seconds):
                break


_worker = IngestRetryWorker()


def get_ingest_retry_worker() -> IngestRetryWorker:
    return _worker

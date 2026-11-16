"""后台拉取队列。只在进程入口启动，create_app 本身不拉起线程，避免测试抢跑。"""

from __future__ import annotations

import logging
import threading

from sarap_engine.orchestration.worker import Worker

log = logging.getLogger("sarap_engine.worker")


def start_background_worker(worker: Worker, *, poll_seconds: float = 0.4) -> tuple[threading.Event, threading.Thread]:
    """Drain queued jobs until the returned event is set. The thread is a daemon."""
    stop = threading.Event()

    def _loop() -> None:
        while not stop.is_set():
            try:
                row = worker.queue.pop_next()
            except Exception:
                log.exception("engine worker failed while polling the queue")
                stop.wait(poll_seconds)
                continue
            if row is None:
                stop.wait(poll_seconds)
                continue
            try:
                worker.execute(row.id)
            except Exception:
                log.exception("engine worker failed job %s", row.id)

    thread = threading.Thread(target=_loop, name="sarap-engine-worker", daemon=True)
    thread.start()
    log.info("engine background worker started (poll %.2fs)", poll_seconds)
    return stop, thread

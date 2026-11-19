import json

from app.core import run_queue, run_service


def _item():
    return {
        "id": "queue123456",
        "owner_id": 7,
        "username": "alice",
        "role": "user",
        "env_id": "env-1",
        "params": json.dumps(
            {"env_id": "env-1", "git_ref": "main", "suite": "regression"}
        ),
    }


def _setup(monkeypatch, starter):
    updates = []
    monkeypatch.setattr(run_queue.pool, "query", lambda *_args: [_item()])
    monkeypatch.setattr(
        run_queue.pool,
        "execute",
        lambda sql, params=(): updates.append((sql, params)) or 1,
    )
    monkeypatch.setattr(run_queue.run_service, "do_start_run", starter)
    run_queue.RunQueueWorker().tick()
    return updates


def test_queue_success_records_started_loop(monkeypatch):
    updates = _setup(monkeypatch, lambda *_args: {"loop_id": "loop123456"})
    assert any("status = 'started'" in sql for sql, _ in updates)
    assert any("loop123456" in params for _, params in updates)


def test_queue_busy_returns_to_waiting(monkeypatch):
    def busy(*_args):
        raise run_service.RunError(409, "环境正忙")

    updates = _setup(monkeypatch, busy)
    assert any("status = 'queued'" in sql for sql, _ in updates)


def test_queue_non_conflict_error_is_terminal(monkeypatch):
    def invalid(*_args):
        raise run_service.RunError(400, "配置无效")

    updates = _setup(monkeypatch, invalid)
    assert any("status = 'failed'" in sql for sql, _ in updates)


def test_queue_start_recovers_interrupted_claims(monkeypatch):
    updates = []
    monkeypatch.setattr(
        run_queue.pool,
        "execute",
        lambda sql, params=(): updates.append((sql, params)) or 1,
    )
    worker = run_queue.RunQueueWorker(interval_seconds=60)
    monkeypatch.setattr(worker, "_run", lambda: None)
    worker.start()
    worker.stop()
    assert any("WHERE status = 'starting'" in sql for sql, _ in updates)

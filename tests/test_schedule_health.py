from app.core import scheduler


def test_schedule_health_reconciles_success_and_failure(monkeypatch):
    rows = [
        {
            "id": "schedule-ok",
            "last_loop_id": "loop-ok",
            "loop_status": "done",
            "has_failed_job": 0,
        },
        {
            "id": "schedule-fail",
            "last_loop_id": "loop-fail",
            "loop_status": "done",
            "has_failed_job": 1,
        },
    ]
    updates = []
    monkeypatch.setattr(scheduler.pool, "query", lambda *_args: rows)
    monkeypatch.setattr(
        scheduler.pool,
        "execute",
        lambda sql, params=(): updates.append((sql, params)) or 1,
    )

    scheduler.Scheduler()._reconcile_started()

    assert any("last_status = 'ok'" in sql and "failure_streak = 0" in sql for sql, _ in updates)
    assert any("failure_streak = failure_streak + 1" in sql for sql, _ in updates)

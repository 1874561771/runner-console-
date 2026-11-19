from app.ingest import run_ingest


def test_retry_only_selects_finished_jobs(monkeypatch):
    captured = {}

    def query(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(run_ingest.pool, "query", query)

    assert run_ingest.retry_pending_ingest(limit=25) == 0
    assert "j.ended_at IS NOT NULL" in captured["sql"]
    assert captured["params"] == (25,)

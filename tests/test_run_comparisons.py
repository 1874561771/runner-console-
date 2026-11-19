from app.api import runs_routes


def test_compare_runs_classifies_case_changes(monkeypatch):
    rows = {
        "base": {
            "run_id": "base",
            "pass_rate": 80,
            "passed": 8,
            "failed": 2,
            "broken": 0,
            "total": 10,
            "job_duration_s": 100,
        },
        "target": {
            "run_id": "target",
            "pass_rate": 90,
            "passed": 9,
            "failed": 1,
            "broken": 0,
            "total": 10,
            "job_duration_s": 90,
        },
    }
    cases = {
        "base": [
            {"name": "regressed", "seq": 0, "status": "pass"},
            {"name": "fixed", "seq": 0, "status": "fail"},
            {"name": "persistent", "seq": 0, "status": "broken"},
        ],
        "target": [
            {"name": "regressed", "seq": 0, "status": "fail"},
            {"name": "fixed", "seq": 0, "status": "pass"},
            {"name": "persistent", "seq": 0, "status": "fail"},
        ],
    }
    monkeypatch.setattr(runs_routes, "get_run_or_404", lambda *_args: {})
    monkeypatch.setattr(
        runs_routes.pool, "query_one", lambda _sql, params: rows[params[0]]
    )
    monkeypatch.setattr(
        runs_routes.runs_dao, "list_cases", lambda run_id: cases[run_id]
    )

    result = runs_routes.compare_runs("base", "target", None)

    assert result["delta"]["pass_rate"] == 10
    assert result["delta"]["duration_s"] == -10
    assert [x["name"] for x in result["changes"]["regressions"]] == ["regressed"]
    assert [x["name"] for x in result["changes"]["fixed"]] == ["fixed"]
    assert [x["name"] for x in result["changes"]["unchanged_failures"]] == [
        "persistent"
    ]

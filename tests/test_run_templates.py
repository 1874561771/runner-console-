import json

from app.api import templates_routes


def _body():
    return templates_routes.RunTemplateIn(
        name="Regression latest",
        run={
            "env_id": "env-1",
            "git_ref": "main",
            "suite": "regression",
            "branch": "utm-mainline",
            "build": "",
        },
    )


def test_create_template_stores_complete_run_snapshot(monkeypatch):
    executed = {}
    row = {
        "id": "template1234",
        "owner_id": 7,
        "name": "Regression latest",
        "params": json.dumps(_body().run.model_dump()),
        "created_at": None,
        "updated_at": None,
    }

    monkeypatch.setattr(templates_routes, "new_id", lambda: "template1234")
    monkeypatch.setattr(
        templates_routes.pool,
        "execute",
        lambda sql, params: executed.update(sql=sql, params=params) or 1,
    )
    monkeypatch.setattr(templates_routes.pool, "query_one", lambda _sql, _params: row)
    monkeypatch.setattr(templates_routes.audit_dao, "insert_audit", lambda *_args: None)

    result = templates_routes.create_template(
        _body(), {"id": 7, "username": "alice", "role": "user"}
    )

    stored = json.loads(executed["params"][3])
    assert stored["env_id"] == "env-1"
    assert stored["branch"] == "utm-mainline"
    assert stored["suite"] == "regression"
    assert result["template"]["params"]["git_ref"] == "main"

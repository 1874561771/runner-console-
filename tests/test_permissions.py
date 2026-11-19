from app.auth import perms


def test_anonymous_can_view_only_public_environment(monkeypatch):
    def query_one(sql, params):
        assert "visibility = 'public'" in sql
        return {"ok": 1} if params == ("env-public",) else None

    monkeypatch.setattr(perms.pool, "query_one", query_one)

    assert perms.can_view_env(None, "env-public") is True
    assert perms.can_view_env(None, "env-private") is False
    assert perms.can_operate_env(None, "env-public") is False


def test_anonymous_scope_is_limited_to_public_environments():
    sql, params = perms.visible_scope_sql("l.owner_id", "l.env_id", None)

    assert "visibility = 'public'" in sql
    assert "l.env_id" in sql
    assert params == ()


def test_authenticated_scope_includes_shared_visibility():
    sql, params = perms.visible_scope_sql(
        "l.owner_id", "l.env_id", {"id": 42, "role": "user"}
    )

    assert "authenticated" in sql
    assert "public" in sql
    assert params == (42, 42, 42)


def test_admin_can_access_any_owner_and_environment():
    admin = {"id": 1, "role": "admin"}

    assert perms.can_access_owner(admin, 999) is True
    assert perms.can_view_env(admin, "any") is True
    assert perms.can_operate_env(admin, "any") is True

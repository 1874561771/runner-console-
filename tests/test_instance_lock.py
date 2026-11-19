import pytest

from app.core.instance_lock import DatabaseInstanceLock, InstanceAlreadyRunning


class FakeCursor:
    def __init__(self, acquired):
        self.acquired = acquired

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _sql, _params):
        return None

    def fetchone(self):
        return {"acquired": self.acquired}


class FakeConnection:
    def __init__(self, acquired):
        self.acquired = acquired
        self.closed = False

    def cursor(self):
        return FakeCursor(self.acquired)

    def close(self):
        self.closed = True


def test_instance_lock_rejects_second_instance(monkeypatch):
    conn = FakeConnection(acquired=0)
    monkeypatch.setattr("app.core.instance_lock.pymysql.connect", lambda **_kwargs: conn)

    lock = DatabaseInstanceLock({"database": "runner_console"})
    with pytest.raises(InstanceAlreadyRunning):
        lock.acquire()

    assert conn.closed is True


def test_instance_lock_holds_connection_until_release(monkeypatch):
    conn = FakeConnection(acquired=1)
    monkeypatch.setattr("app.core.instance_lock.pymysql.connect", lambda **_kwargs: conn)

    lock = DatabaseInstanceLock({"database": "runner_console"})
    lock.acquire()
    assert conn.closed is False

    lock.release()
    assert conn.closed is True

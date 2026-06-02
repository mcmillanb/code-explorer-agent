import sqlite3

from ce_agent.storage import Store


class TrackingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.closed = False

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self.connection.__exit__(exc_type, exc, tb)

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def close(self):
        self.closed = True
        self.connection.close()


def test_jsonl_events_are_sequenced_and_replayed_after_requested_seq(tmp_path):
    store = Store(tmp_path)
    store.create_session("sess_test", "shell", "bash")

    first = store.append_output("sess_test", "one")
    second = store.append_output("sess_test", "two")

    assert first["seq"] == 1
    assert second["seq"] == 2
    assert store.replay_after("sess_test", 1) == [second]
    assert (tmp_path / "logs" / "sess_test.jsonl").read_text().count("\n") == 2


def test_sequence_continues_when_store_is_reopened(tmp_path):
    store = Store(tmp_path)
    store.create_session("sess_test", "shell", "bash")
    store.append_output("sess_test", "before restart")

    reopened = Store(tmp_path)
    assert reopened.append_output("sess_test", "after restart")["seq"] == 2


def test_sqlite_connections_are_closed(tmp_path, monkeypatch):
    connections = []

    def connect(store):
        connection = sqlite3.connect(str(store.db_path))
        connection.row_factory = sqlite3.Row
        tracked = TrackingConnection(connection)
        connections.append(tracked)
        return tracked

    monkeypatch.setattr(Store, "_connect", connect)

    store = Store(tmp_path)
    store.create_session("sess_test", "shell", "bash")
    store.get_session("sess_test")
    store.list_sessions()
    store.touch("sess_test")
    store.set_raw_offset("sess_test", 10)
    store.delete_session("sess_test")

    assert connections
    assert all(connection.closed for connection in connections)

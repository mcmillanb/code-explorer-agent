from ce_agent.storage import Store


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


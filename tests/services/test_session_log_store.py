"""Session log histories remain independent, ephemeral, and isolated by session name."""

from packpatch_ui.services.session_log_store import LogEntry, LogSeverity, LogVerbosity, SessionLogStore


def entry(message: str) -> LogEntry:
    return LogEntry("12:34:56", message, LogVerbosity.DETAILS, LogSeverity.INFO)


def test_independent_session_histories_and_snapshots() -> None:
    store = SessionLogStore()
    store.append("alpha", entry("A1"))
    store.append("beta", entry("B1"))
    store.append("alpha", entry("A2"))

    assert [item.message for item in store.entries_for("alpha")] == ["A1", "A2"]
    assert [item.message for item in store.entries_for("beta")] == ["B1"]
    assert store.entries_for("fresh") == ()
    assert isinstance(store.entries_for("alpha"), tuple)


def test_clear_only_one_session_and_reuse_name_starts_empty() -> None:
    store = SessionLogStore()
    store.append("alpha", entry("old history"))
    store.append("beta", entry("keep me"))
    store.clear("alpha")
    assert store.entries_for("alpha") == ()
    assert [item.message for item in store.entries_for("beta")] == ["keep me"]
    store.append("alpha", entry("new history"))
    assert [item.message for item in store.entries_for("alpha")] == ["new history"]


def test_new_application_store_starts_without_old_logs() -> None:
    original = SessionLogStore()
    original.append("alpha", entry("not persisted"))
    fresh = SessionLogStore()
    assert fresh.entries_for("alpha") == ()

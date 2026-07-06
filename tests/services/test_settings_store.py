from __future__ import annotations

import json
from pathlib import Path

from packpatch_ui.services.settings_store import (
    DEFAULT_SESSION_NAME,
    AppSession,
    SessionStore,
    default_sessions_path,
)


def test_app_session_defaults_match_current_workflow() -> None:
    session = AppSession()

    assert session.name == DEFAULT_SESSION_NAME
    assert session.pack_mode == "slice"
    assert session.apply_mode == "compatch_then_packpatch"
    assert session.git_history_depth == 1
    assert session.log_verbosity == "status"
    assert session.watch_repository_state
    assert not session.include_sensitive_files
    assert not session.include_unversioned_files


def test_app_session_from_dict_migrates_legacy_and_ignores_extra_fields() -> None:
    session = AppSession.from_dict(
        {
            "name": "legacy",
            "repo_path": "/repo",
            "git_history_depth": 0,
            "selected_files": "not-a-list",
            "extra_field": "ignored",
        }
    )

    assert session.name == "legacy"
    assert session.repo_path == "/repo"
    assert session.git_history_depth == 1
    assert session.selected_files == []
    assert session.log_verbosity == "status"


def test_app_session_roundtrip_preserves_all_current_fields() -> None:
    original = AppSession(
        name="vpn",
        repo_path="/repo/vpn",
        patch_dir="/patches",
        task_name="vpn",
        pack_mode="full",
        commit_message="Commit message",
        patch_target_mode="selected",
        apply_mode="packpatch_then_compatch",
        allow_unversioned_apply=True,
        stash_changes_after_undo=True,
        auto_export_pack=True,
        include_sensitive_files=True,
        include_unversioned_files=True,
        git_history_depth=3,
        auto_create_pack_after_apply=True,
        export_dir="/exports",
        deploy_dir="/deploy",
        auto_deploy_after_commit=True,
        watch_repository_state=False,
        selected_files=["src", "README.md"],
        file_filter="*.py",
        window_geometry="geometry",
        latest_packs_collapsed=False,
        latest_patches_collapsed=True,
        patch_preview_collapsed=False,
        repository_status_collapsed=True,
        file_tree_collapsed=True,
        log_collapsed=True,
        log_verbosity="debug",
        git_commits_collapsed=True,
    )

    restored = AppSession.from_dict(original.to_dict())

    assert restored == original


def test_session_store_roundtrip_sorts_sessions_and_restores_active_name(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.json")
    sessions = [AppSession(name="VPN"), AppSession(name="ias"), AppSession(name="alpha")]

    store.save_sessions(sessions, active_session="ias")

    assert [session.name for session in store.load_sessions()] == ["alpha", "ias", "VPN"]
    assert store.load_active_session_name() == "ias"
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["format"] == "packpatch-ui-sessions-v2"


def test_upsert_replaces_existing_session_and_can_preserve_active_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.json")
    store.save_sessions([AppSession(name="one"), AppSession(name="two")], active_session="one")

    store.upsert_session(AppSession(name="two", repo_path="/updated"), make_active=False)

    assert store.load_active_session_name() == "one"
    assert store.get_session("two") == AppSession(name="two", repo_path="/updated")
    assert len(store.load_sessions()) == 2


def test_delete_active_session_falls_back_to_default(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.json")
    store.save_sessions([AppSession(name="one"), AppSession(name="two")], active_session="two")

    store.delete_session("two")

    assert store.load_active_session_name() == DEFAULT_SESSION_NAME
    assert [session.name for session in store.load_sessions()] == ["one"]


def test_malformed_or_wrong_shape_session_file_is_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(path)

    path.write_text("{broken", encoding="utf-8")
    assert store.load_sessions() == []
    assert store.load_active_session_name() == DEFAULT_SESSION_NAME

    path.write_text("[]\n", encoding="utf-8")
    assert store.load_sessions() == []

    path.write_text(json.dumps({"sessions": "wrong", "active_session": 42}), encoding="utf-8")
    assert store.load_sessions() == []
    assert store.load_active_session_name() == DEFAULT_SESSION_NAME


def test_default_sessions_path_honors_xdg_config_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert default_sessions_path() == tmp_path / "xdg" / "packpatch-ui" / "sessions.json"

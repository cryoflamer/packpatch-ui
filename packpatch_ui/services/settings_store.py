"""Persistent user-level session storage for PackPatch UI."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


APP_CONFIG_DIR_NAME = "packpatch-ui"
SESSIONS_FILE_NAME = "sessions.json"
DEFAULT_SESSION_NAME = "default"


@dataclass(slots=True)
class AppSession:
    """Saved UI state for a repository workflow."""

    name: str = DEFAULT_SESSION_NAME
    repo_path: str = ""
    patch_dir: str = ""
    task_name: str = ""
    pack_mode: str = "slice"
    commit_message: str = ""
    patch_target_mode: str = "latest"
    auto_export_pack: bool = False
    export_dir: str = ""
    deploy_dir: str = ""
    auto_deploy_after_commit: bool = False
    selected_files: list[str] = field(default_factory=list)
    file_filter: str = ""
    window_geometry: str = ""
    latest_packs_collapsed: bool = True
    latest_patches_collapsed: bool = False
    patch_preview_collapsed: bool = True
    repository_status_collapsed: bool = False
    file_tree_collapsed: bool = False
    log_collapsed: bool = False
    git_commits_collapsed: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSession":
        """Build a session from JSON data while tolerating missing/extra fields."""
        selected_files = data.get("selected_files", [])
        if not isinstance(selected_files, list):
            selected_files = []

        return cls(
            name=str(data.get("name") or DEFAULT_SESSION_NAME),
            repo_path=str(data.get("repo_path") or ""),
            patch_dir=str(data.get("patch_dir") or ""),
            task_name=str(data.get("task_name") or ""),
            pack_mode=str(data.get("pack_mode") or "slice"),
            commit_message=str(data.get("commit_message") or ""),
            patch_target_mode=str(data.get("patch_target_mode") or "latest"),
            auto_export_pack=bool(data.get("auto_export_pack", False)),
            export_dir=str(data.get("export_dir") or ""),
            deploy_dir=str(data.get("deploy_dir") or ""),
            auto_deploy_after_commit=bool(data.get("auto_deploy_after_commit", False)),
            selected_files=[str(path) for path in selected_files if str(path)],
            file_filter=str(data.get("file_filter") or ""),
            window_geometry=str(data.get("window_geometry") or ""),
            latest_packs_collapsed=bool(data.get("latest_packs_collapsed", True)),
            latest_patches_collapsed=bool(data.get("latest_patches_collapsed", False)),
            patch_preview_collapsed=bool(data.get("patch_preview_collapsed", True)),
            repository_status_collapsed=bool(data.get("repository_status_collapsed", False)),
            file_tree_collapsed=bool(data.get("file_tree_collapsed", False)),
            log_collapsed=bool(data.get("log_collapsed", False)),
            git_commits_collapsed=bool(data.get("git_commits_collapsed", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the session to JSON-serializable data."""
        return asdict(self)


class SessionStore:
    """Read and write PackPatch UI sessions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_sessions_path()

    def _read_payload(self) -> dict[str, Any]:
        """Return the raw sessions payload, or an empty payload when it cannot be read."""
        if not self.path.is_file():
            return {}

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        return raw if isinstance(raw, dict) else {}

    def load_active_session_name(self) -> str:
        """Return the last active session name saved by the UI."""
        active_session = self._read_payload().get("active_session")
        if isinstance(active_session, str) and active_session:
            return active_session
        return DEFAULT_SESSION_NAME

    def load_sessions(self) -> list[AppSession]:
        """Return all saved sessions sorted by name."""
        items = self._read_payload().get("sessions", [])
        if not isinstance(items, list):
            return []

        sessions = [AppSession.from_dict(item) for item in items if isinstance(item, dict)]
        return sorted(sessions, key=lambda session: session.name.lower())

    def save_sessions(self, sessions: list[AppSession], *, active_session: str | None = None) -> None:
        """Persist *sessions* atomically enough for local UI usage."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "packpatch-ui-sessions-v2",
            "active_session": active_session or self.load_active_session_name(),
            "sessions": [session.to_dict() for session in sorted(sessions, key=lambda item: item.name.lower())],
        }
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    def upsert_session(self, session: AppSession, *, make_active: bool = True) -> None:
        """Insert or replace a session by name."""
        sessions = [item for item in self.load_sessions() if item.name != session.name]
        sessions.append(session)
        active_session = session.name if make_active else self.load_active_session_name()
        self.save_sessions(sessions, active_session=active_session)

    def delete_session(self, name: str) -> None:
        """Delete a session by name if it exists."""
        remaining_sessions = [session for session in self.load_sessions() if session.name != name]
        active_session = self.load_active_session_name()
        if active_session == name:
            active_session = DEFAULT_SESSION_NAME
        self.save_sessions(remaining_sessions, active_session=active_session)

    def get_session(self, name: str) -> AppSession | None:
        """Return a saved session by name."""
        for session in self.load_sessions():
            if session.name == name:
                return session
        return None


def default_sessions_path() -> Path:
    """Return the default sessions.json path."""
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home).expanduser() / APP_CONFIG_DIR_NAME / SESSIONS_FILE_NAME
    return Path.home() / ".config" / APP_CONFIG_DIR_NAME / SESSIONS_FILE_NAME

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
    commit_message: str = ""
    selected_files: list[str] = field(default_factory=list)
    window_geometry: str = ""
    latest_packs_collapsed: bool = True
    latest_patches_collapsed: bool = False
    patch_preview_collapsed: bool = True

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
            commit_message=str(data.get("commit_message") or ""),
            selected_files=[str(path) for path in selected_files if str(path)],
            window_geometry=str(data.get("window_geometry") or ""),
            latest_packs_collapsed=bool(data.get("latest_packs_collapsed", True)),
            latest_patches_collapsed=bool(data.get("latest_patches_collapsed", False)),
            patch_preview_collapsed=bool(data.get("patch_preview_collapsed", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the session to JSON-serializable data."""
        return asdict(self)


class SessionStore:
    """Read and write PackPatch UI sessions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_sessions_path()

    def load_sessions(self) -> list[AppSession]:
        """Return all saved sessions sorted by name."""
        if not self.path.is_file():
            return []

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        items = raw.get("sessions", []) if isinstance(raw, dict) else []
        if not isinstance(items, list):
            return []

        sessions = [AppSession.from_dict(item) for item in items if isinstance(item, dict)]
        return sorted(sessions, key=lambda session: session.name.lower())

    def save_sessions(self, sessions: list[AppSession]) -> None:
        """Persist *sessions* atomically enough for local UI usage."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "packpatch-ui-sessions-v1",
            "sessions": [session.to_dict() for session in sorted(sessions, key=lambda item: item.name.lower())],
        }
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    def upsert_session(self, session: AppSession) -> None:
        """Insert or replace a session by name."""
        sessions = [item for item in self.load_sessions() if item.name != session.name]
        sessions.append(session)
        self.save_sessions(sessions)

    def delete_session(self, name: str) -> None:
        """Delete a session by name if it exists."""
        self.save_sessions([session for session in self.load_sessions() if session.name != name])

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

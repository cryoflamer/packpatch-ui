"""Ephemeral, session-scoped execution log data (never written to sessions.json)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class LogVerbosity(IntEnum):
    """Maximum detail shown in the execution log."""

    STATUS = 0
    DETAILS = 1
    DEBUG = 2


class LogSeverity(IntEnum):
    """Severity that may override verbosity filtering."""

    INFO = 0
    WARNING = 1
    ERROR = 2


@dataclass(frozen=True, slots=True)
class LogEntry:
    """Structured in-memory log entry."""

    timestamp: str
    message: str
    verbosity: LogVerbosity
    severity: LogSeverity


class SessionLogStore:
    """Keep independent log histories for saved sessions during this application run."""

    def __init__(self) -> None:
        self._entries_by_session: dict[str, list[LogEntry]] = {}

    def append(self, session_name: str, entry: LogEntry) -> None:
        self._entries_by_session.setdefault(session_name, []).append(entry)

    def entries_for(self, session_name: str) -> tuple[LogEntry, ...]:
        """Return a snapshot; callers cannot mutate a different session's history."""
        return tuple(self._entries_by_session.get(session_name, ()))

    def clear(self, session_name: str) -> None:
        """Discard only this session's entries, including on deletion."""
        self._entries_by_session.pop(session_name, None)

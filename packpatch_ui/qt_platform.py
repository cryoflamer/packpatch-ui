"""Choose a Qt window-system backend before QApplication is created."""

from __future__ import annotations

import os
import sys
from collections.abc import MutableMapping
from pathlib import Path


def _running_in_wsl(environment: MutableMapping[str, str]) -> bool:
    if environment.get("WSL_DISTRO_NAME") or environment.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def configure_qt_platform(environment: MutableMapping[str, str] | None = None) -> None:
    """Prefer XWayland on WSLg so Qt can request positions for top-level dialogs.

    Native Wayland compositors decide window positions themselves, ignoring Qt's
    move() requests. Keep the explicit QT_QPA_PLATFORM override and a Wayland
    fallback if the XCB backend is not available.
    """
    if environment is None:
        environment = os.environ
    if (
        sys.platform != "linux"
        or "QT_QPA_PLATFORM" in environment
        or not environment.get("DISPLAY")
        or not environment.get("WAYLAND_DISPLAY")
        or not _running_in_wsl(environment)
    ):
        return
    environment["QT_QPA_PLATFORM"] = "xcb;wayland"

"""Selecting the Qt platform before creating an application."""

from __future__ import annotations

import pytest

from packpatch_ui import qt_platform


def test_wslg_prefers_xwayland(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qt_platform.sys, "platform", "linux")
    environment = {
        "WSL_DISTRO_NAME": "Ubuntu",
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "wayland-0",
    }
    qt_platform.configure_qt_platform(environment)
    assert environment["QT_QPA_PLATFORM"] == "xcb;wayland"


def test_explicit_qt_platform_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qt_platform.sys, "platform", "linux")
    environment = {
        "WSL_DISTRO_NAME": "Ubuntu",
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "wayland-0",
        "QT_QPA_PLATFORM": "wayland",
    }
    qt_platform.configure_qt_platform(environment)
    assert environment["QT_QPA_PLATFORM"] == "wayland"


@pytest.mark.parametrize("missing", ["DISPLAY", "WAYLAND_DISPLAY", "WSL_DISTRO_NAME"])
def test_no_wslg_does_not_override_platform(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.setattr(qt_platform.sys, "platform", "linux")
    monkeypatch.setattr(qt_platform, "_running_in_wsl", lambda environment: "WSL_DISTRO_NAME" in environment)
    environment = {
        "WSL_DISTRO_NAME": "Ubuntu",
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "wayland-0",
    }
    environment.pop(missing)
    qt_platform.configure_qt_platform(environment)
    assert "QT_QPA_PLATFORM" not in environment


def test_non_linux_platform_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qt_platform.sys, "platform", "win32")
    environment = {
        "WSL_DISTRO_NAME": "Ubuntu",
        "DISPLAY": ":0",
        "WAYLAND_DISPLAY": "wayland-0",
    }
    qt_platform.configure_qt_platform(environment)
    assert "QT_QPA_PLATFORM" not in environment

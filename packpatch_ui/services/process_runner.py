"""Thin subprocess wrapper for command execution."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping, Sequence


def run_process(
    command: Sequence[str],
    cwd: Path | None = None,
    check: bool = True,
    *,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run *command* and capture text output."""
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
        env=env,
    )

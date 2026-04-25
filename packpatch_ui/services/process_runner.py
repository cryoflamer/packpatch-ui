"""Thin subprocess wrapper for command execution."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


def run_process(command: Sequence[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run *command* and capture text output."""
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )

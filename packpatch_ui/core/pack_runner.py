"""Helpers for creating PackPatch archives from the UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from packpatch_ui.services.process_runner import run_process


@dataclass(frozen=True)
class PackResult:
    """Result of a pack creation command."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        """Return True when the pack command finished successfully."""
        return self.returncode == 0


def default_pack_script_path() -> Path:
    """Return the repository-local pack script path."""
    return Path(__file__).resolve().parents[2] / "tools" / "pack-for-chatgpt.sh"


def create_slice_pack(repo_root: Path, task_name: str, selected_files: Sequence[str]) -> PackResult:
    """Create a slice pack for *selected_files* inside *repo_root*."""
    cleaned_task = task_name.strip()
    if not cleaned_task:
        raise ValueError("Task name is required.")

    files = [path.strip() for path in selected_files if path.strip()]
    if not files:
        raise ValueError("Select at least one file for slice pack creation.")

    script = default_pack_script_path()
    if not script.is_file():
        raise FileNotFoundError(f"Pack script not found: {script}")

    command = ["bash", str(script), "slice", cleaned_task, *files]
    result = run_process(command, cwd=repo_root, check=False)
    return PackResult(
        command=command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )

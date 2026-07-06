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

    @property
    def archive_path(self) -> Path | None:
        """Return the created archive path reported by the pack script, if any."""
        for line in self.stdout.splitlines():
            candidate = line.strip()
            if candidate.endswith((".tar.gz", ".tgz")):
                path = Path(candidate).expanduser()
                if path.is_file():
                    return path
        return None


def default_pack_script_path() -> Path:
    """Return the repository-local pack script path."""
    return Path(__file__).resolve().parents[2] / "tools" / "pack-for-chatgpt.sh"


PACK_MODE_DEFAULT_TASKS = {
    "slice": "slice",
    "changed": "changed",
    "full": "overview",
    "full-untracked": "overview",
}

PACK_MODE_LABELS = {
    "slice": "slice",
    "changed": "changed",
    "full": "full",
    "full-untracked": "full + untracked",
}


def default_task_name_for_mode(mode: str) -> str:
    """Return a compact default task name for a pack mode."""
    return PACK_MODE_DEFAULT_TASKS.get(mode, "pack")


def create_pack(
    repo_root: Path,
    mode: str,
    task_name: str,
    selected_files: Sequence[str],
    *,
    include_sensitive: bool = False,
    include_unversioned: bool = False,
    history_depth: int = 1,
) -> PackResult:
    """Create a PackPatch archive for *mode* inside *repo_root*."""
    cleaned_task = task_name.strip() or default_task_name_for_mode(mode)

    script = default_pack_script_path()
    if not script.is_file():
        raise FileNotFoundError(f"Pack script not found: {script}")

    sensitive_args = ["--include-sensitive"] if include_sensitive else []
    unversioned_args = ["--include-untracked"] if include_unversioned else []
    history_args = ["--history-depth", str(max(0, history_depth))]

    if mode == "slice":
        files = [path.strip() for path in selected_files if path.strip()]
        if not files:
            raise ValueError("Select at least one file for slice pack creation.")
        command = ["bash", str(script), "slice", cleaned_task, *history_args, *unversioned_args, *sensitive_args, *files]
    elif mode == "changed":
        command = ["bash", str(script), "changed", cleaned_task, *history_args, *unversioned_args, *sensitive_args]
    elif mode == "full":
        command = ["bash", str(script), "full", cleaned_task, *history_args, *unversioned_args, *sensitive_args]
    elif mode == "full-untracked":
        command = ["bash", str(script), "full", cleaned_task, *history_args, "--include-untracked", *sensitive_args]
    else:
        raise ValueError(f"Unsupported pack mode: {mode}")

    result = run_process(command, cwd=repo_root, check=False)
    return PackResult(
        command=command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


# Backward-compatible helper for older callers/tests.
def create_slice_pack(repo_root: Path, task_name: str, selected_files: Sequence[str]) -> PackResult:
    """Create a slice pack for *selected_files* inside *repo_root*."""
    return create_pack(repo_root, "slice", task_name, selected_files)

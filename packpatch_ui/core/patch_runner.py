"""Helpers for applying PackPatch patches from the UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packpatch_ui.core.artifacts import list_patch_files
from packpatch_ui.services.process_runner import run_process


@dataclass(frozen=True)
class PatchApplyResult:
    """Result of a patch apply command."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    selected_patch: Path | None = None

    @property
    def succeeded(self) -> bool:
        """Return True when the patch command finished successfully."""
        return self.returncode == 0


def default_apply_script_path() -> Path:
    """Return the repository-local apply script path."""
    return Path(__file__).resolve().parents[2] / "tools" / "apply-latest-patch.sh"


def apply_latest_patch(repo_root: Path, patch_dir: Path, *, dry_run: bool = False, strict: bool = False) -> PatchApplyResult:
    """Apply the latest patch from *patch_dir* to *repo_root*."""
    if not patch_dir.is_dir():
        raise FileNotFoundError(f"Patch directory not found: {patch_dir}")

    script = default_apply_script_path()
    if not script.is_file():
        raise FileNotFoundError(f"Apply script not found: {script}")

    command = ["bash", str(script), "-d", str(patch_dir)]
    if dry_run:
        command.append("-n")
    if strict:
        command.append("--strict")

    result = run_process(command, cwd=repo_root, check=False)
    return PatchApplyResult(
        command=command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def check_latest_patch(repo_root: Path, patch_dir: Path) -> PatchApplyResult:
    """Check whether the latest patch from *patch_dir* applies cleanly to *repo_root*."""
    if not patch_dir.is_dir():
        raise FileNotFoundError(f"Patch directory not found: {patch_dir}")

    patches = list_patch_files(patch_dir)
    if not patches:
        raise FileNotFoundError(f"No .patch or .diff files found in: {patch_dir}")

    patch_path = patches[0].path
    command = ["git", "apply", "--check", str(patch_path)]
    result = run_process(command, cwd=repo_root, check=False)
    selected_line = f"Selected patch: {patch_path}\n"
    return PatchApplyResult(
        command=command,
        returncode=result.returncode,
        stdout=selected_line + result.stdout,
        stderr=result.stderr,
        selected_patch=patch_path,
    )

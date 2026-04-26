"""Repository deploy helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from packpatch_ui.services.process_runner import run_process


DEPLOY_EXCLUDES = (
    ".git",
    ".gitignore",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
)


@dataclass(frozen=True)
class DeployResult:
    """Result of a repository deploy operation."""

    command: list[str]
    stdout: str
    stderr: str
    returncode: int

    @property
    def succeeded(self) -> bool:
        """Return whether the deploy command completed successfully."""
        return self.returncode == 0


def deploy_repo(source: Path, target: Path) -> DeployResult:
    """Synchronize *source* into *target* while excluding git and cache files."""
    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    _validate_deploy_paths(source, target)

    rsync_path = shutil.which("rsync")
    if rsync_path is None:
        raise FileNotFoundError("rsync was not found in PATH")

    target.mkdir(parents=True, exist_ok=True)
    command = [rsync_path, "-av", "--delete"]
    for pattern in DEPLOY_EXCLUDES:
        command.append(f"--exclude={pattern}")
    command.extend([f"{source}/", f"{target}/"])

    completed = run_process(command, check=False)

    return DeployResult(
        command=list(command),
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )


def _validate_deploy_paths(source: Path, target: Path) -> None:
    if not source.exists():
        raise ValueError(f"source does not exist: {source}")
    if not source.is_dir():
        raise ValueError(f"source is not a directory: {source}")
    if target == Path(target.anchor):
        raise ValueError(f"target cannot be filesystem root: {target}")
    if target == Path.home().resolve():
        raise ValueError(f"target cannot be the home directory: {target}")
    if target == source:
        raise ValueError("target cannot be the same directory as source")
    if _is_relative_to(target, source):
        raise ValueError("target cannot be inside source")
    if _is_relative_to(source, target):
        raise ValueError("target cannot contain source")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True

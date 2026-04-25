"""Helpers for detecting and inspecting git repositories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packpatch_ui.services.process_runner import run_process


@dataclass(frozen=True)
class GitRepoInfo:
    """Minimal git repository information shown by the UI."""

    root: Path
    branch: str
    is_dirty: bool


def find_git_root(start_dir: Path) -> Path | None:
    """Return the git root for *start_dir*, or None if it is not inside a git repository."""
    result = run_process(["git", "rev-parse", "--show-toplevel"], cwd=start_dir, check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def read_git_repo_info(start_dir: Path) -> GitRepoInfo | None:
    """Read basic repository information for *start_dir*."""
    root = find_git_root(start_dir)
    if root is None:
        return None

    branch = run_process(["git", "branch", "--show-current"], cwd=root).stdout.strip()
    status = run_process(["git", "status", "--porcelain"], cwd=root).stdout
    return GitRepoInfo(root=root, branch=branch, is_dirty=bool(status.strip()))

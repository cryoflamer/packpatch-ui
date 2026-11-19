"""Bounded, non-interactive fast-forward pulls of the current upstream."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from packpatch_ui.core.git_push import PushTarget, PushUnavailable, current_push_target

PULL_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class PullResult:
    succeeded: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    updated: bool = False


def pull_current_branch(root: Path, *, expected_target: PushTarget | None = None) -> PullResult:
    """Reject dirty/in-progress repositories and never merge divergent histories."""
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", SSH_ASKPASS_REQUIRE="never")

    def git(*args: str):
        return subprocess.run(["git", *args], cwd=root, env=env, capture_output=True,
                              text=True, check=True, timeout=PULL_TIMEOUT_SECONDS)

    def output(value):
        return value.decode(errors="replace") if isinstance(value, bytes) else value or ""

    try:
        target = current_push_target(root)
        if expected_target is not None and target != expected_target:
            return PullResult(False, "Current branch or upstream changed; pull cancelled.")
        for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer", "BISECT_START"):
            path = Path(git("rev-parse", "--git-path", marker).stdout.strip())
            if (root / path).exists():
                return PullResult(False, "A Git operation is in progress; pull cancelled.")
        if git("status", "--porcelain", "--untracked-files=all").stdout.strip():
            return PullResult(False, "Working tree is not clean; pull cancelled.")
        before = git("rev-parse", "HEAD").stdout.strip()
        result = git("-c", "merge.autostash=false", "pull", "--ff-only", "--no-rebase", "--no-recurse-submodules",
                     "--", target.remote, target.destination_ref)
        updated = before != git("rev-parse", "HEAD").stdout.strip()
        return PullResult(True, "Pull completed." if updated else "No incoming commits.",
                          result.stdout, result.stderr, updated)
    except subprocess.TimeoutExpired as exc:
        return PullResult(False, "Git pull timed out; check repository state and network.",
                          output(exc.stdout), output(exc.stderr))
    except subprocess.CalledProcessError as exc:
        return PullResult(False, f"Git pull failed (exit {exc.returncode}).", output(exc.stdout), output(exc.stderr))
    except (PushUnavailable, OSError) as exc:
        return PullResult(False, str(exc))

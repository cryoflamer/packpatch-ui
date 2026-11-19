"""Fetch only the current upstream tracking ref, without modifying the working tree."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from packpatch_ui.core.git_push import PushTarget, PushUnavailable, current_push_target

FETCH_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class FetchResult:
    succeeded: bool
    message: str


def fetch_current_branch(root: Path, *, expected_target: PushTarget) -> FetchResult:
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", SSH_ASKPASS_REQUIRE="never")
    try:
        if current_push_target(root) != expected_target:
            return FetchResult(False, "Branch or upstream changed; fetch cancelled.")
        tracking = subprocess.run(
            ["git", "rev-parse", "--symbolic-full-name", "@{upstream}"],
            cwd=root, capture_output=True, text=True, check=True, timeout=FETCH_TIMEOUT_SECONDS,
        ).stdout.strip()
        if not tracking.startswith("refs/remotes/"):
            return FetchResult(False, "Upstream is not a remote-tracking ref.")
        result = subprocess.run(
            ["git", "fetch", "--no-tags", "--no-prune", "--no-recurse-submodules",
             "--no-auto-gc", "--refmap=", "--", expected_target.remote,
             f"+{expected_target.destination_ref}:{tracking}"],
            cwd=root, env=env, capture_output=True, text=True, check=False,
            timeout=FETCH_TIMEOUT_SECONDS,
        )
        if result.returncode:
            return FetchResult(False, result.stderr.strip() or f"Git fetch failed (exit {result.returncode}).")
        return FetchResult(True, "Remote tracking ref refreshed.")
    except subprocess.TimeoutExpired:
        return FetchResult(False, "Git fetch timed out.")
    except (PushUnavailable, OSError, subprocess.CalledProcessError) as exc:
        return FetchResult(False, str(exc))

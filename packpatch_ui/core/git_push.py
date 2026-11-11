"""Safe, non-forcing pushes of the currently checked-out tracking branch."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from packpatch_ui.services.process_runner import run_process


PUSH_TIMEOUT_SECONDS = 30


class PushUnavailable(ValueError):
    """Raised when the current branch has no usable remote upstream."""


@dataclass(frozen=True)
class PushTarget:
    """An explicit remote and destination ref for the checked-out branch."""

    branch: str
    remote: str
    destination_ref: str

    @property
    def description(self) -> str:
        return f"{self.branch} → {self.remote}/{self.destination_ref.removeprefix('refs/heads/')}"


@dataclass(frozen=True)
class PushResult:
    succeeded: bool
    message: str
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""


def _git_value(root: Path, *args: str) -> str:
    result = run_process(["git", *args], cwd=root, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def current_push_target(root: Path) -> PushTarget:
    """Resolve only an existing remote upstream; never create or guess one."""
    branch = _git_value(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        raise PushUnavailable("No current branch (detached HEAD or unborn repository).")

    remote = _git_value(root, "config", "--get", f"branch.{branch}.remote")
    destination_ref = _git_value(root, "config", "--get", f"branch.{branch}.merge")
    if not remote or remote == "." or not destination_ref.startswith("refs/heads/"):
        raise PushUnavailable(f"Branch '{branch}' has no remote tracking upstream.")
    if not _git_value(root, "remote", "get-url", remote):
        raise PushUnavailable(f"Remote '{remote}' is not configured.")
    if not _git_value(root, "rev-parse", "--verify", "@{upstream}"):
        raise PushUnavailable(f"Upstream for branch '{branch}' is not available locally; fetch or set tracking first.")

    return PushTarget(branch=branch, remote=remote, destination_ref=destination_ref)


def push_current_branch(root: Path, *, expected_target: PushTarget | None = None) -> PushResult:
    """Push HEAD to its exact configured upstream, without force or other refs.

    The remote and branch are explicit rather than relying on push.default or
    configured remote push refspecs. Prompts are disabled and the call is bounded.
    """
    try:
        target = current_push_target(root)
    except (PushUnavailable, OSError) as exc:
        return PushResult(False, str(exc))

    if expected_target is not None and target != expected_target:
        return PushResult(False, "The current branch or its upstream changed before push; push was cancelled.")

    command = ["git", "push", "--porcelain", "--", target.remote, f"HEAD:{target.destination_ref}"]
    env = os.environ.copy()
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "SSH_ASKPASS_REQUIRE": "never",
    })
    try:
        result = subprocess.run(
            command, cwd=root, env=env, capture_output=True, text=True,
            check=False, timeout=PUSH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return PushResult(False, f"Push timed out after {PUSH_TIMEOUT_SECONDS} seconds ({target.description}).")
    except OSError as exc:
        return PushResult(False, f"Could not start Git push: {exc}")

    if result.returncode:
        return PushResult(False, f"Git rejected push to {target.description} (exit {result.returncode}).",
                          result.returncode, result.stdout, result.stderr)
    return PushResult(True, f"Pushed {target.description}.", result.returncode, result.stdout, result.stderr)

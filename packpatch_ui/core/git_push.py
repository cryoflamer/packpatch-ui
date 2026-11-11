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
class PushState:
    """Commit comparison against the *local* upstream tracking ref (no fetch)."""

    target: PushTarget
    ahead: int
    behind: int


@dataclass(frozen=True)
class PushResult:
    succeeded: bool
    message: str
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    pushed: bool = False
    ahead: int | None = None
    behind: int | None = None


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


def current_push_state(root: Path) -> PushState:
    """Compare HEAD to its local upstream without contacting the remote server.

    These counters do not establish the server's current state: another user
    may have pushed since the last fetch or successful push.
    """
    target = current_push_target(root)
    comparison = run_process(
        ["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
        cwd=root, check=False,
    )
    if comparison.returncode != 0:
        raise PushUnavailable(
            f"Could not compare {target.description} with its local upstream: "
            f"{comparison.stderr.strip() or 'git rev-list failed'}."
        )
    try:
        ahead_text, behind_text = comparison.stdout.split()
        ahead, behind = int(ahead_text), int(behind_text)
        if ahead < 0 or behind < 0:
            raise ValueError("negative commit count")
    except ValueError as exc:
        raise PushUnavailable("Git returned an invalid upstream comparison.") from exc
    return PushState(target, ahead, behind)


def _timeout_output(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def push_current_branch(root: Path, *, expected_target: PushTarget | None = None) -> PushResult:
    """Push HEAD to its exact configured upstream, without force or other refs.

    The remote and branch are explicit rather than relying on push.default or
    configured remote push refspecs. Prompts are disabled and the call is bounded.
    No network command is needed when the local upstream has nothing to receive.
    """
    try:
        state = current_push_state(root)
    except (PushUnavailable, OSError) as exc:
        return PushResult(False, str(exc))

    target = state.target
    if expected_target is not None and target != expected_target:
        return PushResult(False, "The current branch or its upstream changed before push; push was cancelled.")

    if state.ahead == 0:
        if state.behind:
            message = (
                f"Nothing to push: local upstream {target.description} is ahead by "
                f"{state.behind} commit(s). Fetch/pull before pushing."
            )
        else:
            message = f"Already up to date (local tracking ref): {target.description}. Nothing to push."
        return PushResult(True, message, ahead=state.ahead, behind=state.behind)

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
    except subprocess.TimeoutExpired as exc:
        output = _timeout_output(exc.stdout)
        error = _timeout_output(exc.stderr)
        detail = "Git produced no output before the timeout" if not output.strip() and not error.strip() else "Partial Git output was retained in Debug log"
        return PushResult(
            False,
            f"Push timed out after {PUSH_TIMEOUT_SECONDS} seconds ({target.description}). "
            f"{detail}; check network, SSH and credential helpers in a terminal.",
            stdout=output, stderr=error, ahead=state.ahead, behind=state.behind,
        )
    except OSError as exc:
        return PushResult(False, f"Could not start Git push: {exc}", ahead=state.ahead, behind=state.behind)

    if result.returncode:
        return PushResult(
            False, f"Git rejected push to {target.description} (exit {result.returncode}).",
            result.returncode, result.stdout, result.stderr,
            ahead=state.ahead, behind=state.behind,
        )
    return PushResult(
        True, f"Pushed {target.description}.", result.returncode, result.stdout, result.stderr,
        pushed=True, ahead=state.ahead, behind=state.behind,
    )

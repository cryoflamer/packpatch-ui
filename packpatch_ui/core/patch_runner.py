"""Helpers for applying PackPatch and Compatсh patches from the UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packpatch_ui.core.artifacts import list_patch_files
from packpatch_ui.services.process_runner import run_process

MAX_PATCH_PREVIEW_BYTES = 512_000
FORMAT_PATCH_DETECTION_BYTES = 64_000

APPLY_MODE_PACKPATCH_THEN_COMPATCH = "packpatch_then_compatch"
APPLY_MODE_COMPATCH_THEN_PACKPATCH = "compatch_then_packpatch"

APPLY_MODE_LABELS: dict[str, str] = {
    APPLY_MODE_PACKPATCH_THEN_COMPATCH: "PackPatch -> Compatсh fallback",
    APPLY_MODE_COMPATCH_THEN_PACKPATCH: "Compatсh -> PackPatch fallback",
}


@dataclass(frozen=True)
class PatchApplyResult:
    """Result of a patch apply command."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    selected_patch: Path | None = None
    created_commit: bool = False
    applied_with: str = ""

    @property
    def succeeded(self) -> bool:
        """Return True when the patch command finished successfully."""
        return self.returncode == 0


def default_apply_script_path() -> Path:
    """Return the repository-local apply script path."""
    return Path(__file__).resolve().parents[2] / "tools" / "apply-latest-patch.sh"


def apply_latest_patch(
    repo_root: Path,
    patch_dir: Path,
    *,
    dry_run: bool = False,
    strict: bool = False,
    commit_message: str = "",
    patch_path: Path | None = None,
    apply_mode: str = APPLY_MODE_COMPATCH_THEN_PACKPATCH,
) -> PatchApplyResult:
    """Apply a selected patch or fall back to the latest patch from *patch_dir*."""
    patch_path = _resolve_patch_path(patch_dir, patch_path)
    normalized_mode = normalize_apply_mode(apply_mode)
    format_patch = is_format_patch(patch_path)

    if dry_run:
        return _dry_run_result(repo_root, patch_path, normalized_mode, format_patch)

    if normalized_mode == APPLY_MODE_COMPATCH_THEN_PACKPATCH:
        return _apply_with_order(
            repo_root,
            patch_path,
            commit_message=commit_message,
            format_patch=format_patch,
            primary="compatch",
            fallback="packpatch",
        )

    return _apply_with_order(
        repo_root,
        patch_path,
        commit_message=commit_message,
        format_patch=format_patch,
        primary="packpatch",
        fallback="compatch",
    )


def normalize_apply_mode(apply_mode: str) -> str:
    """Return a supported apply mode, falling back to the safest default."""
    if apply_mode in APPLY_MODE_LABELS:
        return apply_mode
    return APPLY_MODE_COMPATCH_THEN_PACKPATCH


def is_format_patch(patch_path: Path) -> bool:
    """Return True when *patch_path* looks like a git format-patch file."""
    try:
        data = patch_path.read_bytes()[:FORMAT_PATCH_DETECTION_BYTES]
    except OSError:
        return False

    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        return False

    first_line = lines[0]
    has_from_header = first_line.startswith("From ") and " Mon Sep 17 00:00:00 " in first_line
    has_patch_subject = any(line.startswith("Subject: [PATCH") for line in lines[:50])
    has_separator = any(line == "---" for line in lines[:100])
    return has_from_header and has_patch_subject and has_separator


def undo_last_commit(repo_root: Path) -> PatchApplyResult:
    """Undo the latest local commit while keeping changes in the working tree."""
    command = ["git", "reset", "--mixed", "HEAD~1"]
    result = run_process(command, cwd=repo_root, check=False)
    return PatchApplyResult(
        command=command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def read_patch_preview(patch_path: Path, *, max_bytes: int = MAX_PATCH_PREVIEW_BYTES) -> tuple[str, bool]:
    """Return patch text preview and whether preview was truncated."""
    if not patch_path.is_file():
        raise FileNotFoundError(f"Patch file not found: {patch_path}")

    data = patch_path.read_bytes()
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    text = data.decode("utf-8", errors="replace")
    return text, truncated


def latest_patch_path(patch_dir: Path) -> Path:
    """Return the latest patch path from *patch_dir*."""
    if not patch_dir.is_dir():
        raise FileNotFoundError(f"Patch directory not found: {patch_dir}")

    patches = list_patch_files(patch_dir)
    if not patches:
        raise FileNotFoundError(f"No .patch or .diff files found in: {patch_dir}")
    return patches[0].path


def read_latest_patch_preview(patch_dir: Path, *, max_bytes: int = MAX_PATCH_PREVIEW_BYTES) -> tuple[Path, str, bool]:
    """Return latest patch path, text preview, and whether preview was truncated."""
    patch_path = latest_patch_path(patch_dir)
    text, truncated = read_patch_preview(patch_path, max_bytes=max_bytes)
    return patch_path, text, truncated


def check_latest_patch(repo_root: Path, patch_dir: Path, *, patch_path: Path | None = None) -> PatchApplyResult:
    """Check whether a selected or latest patch applies cleanly to *repo_root*."""
    patch_path = _resolve_patch_path(patch_dir, patch_path)

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


def _resolve_patch_path(patch_dir: Path, patch_path: Path | None) -> Path:
    if patch_path is None:
        return latest_patch_path(patch_dir)
    if not patch_path.is_file():
        raise FileNotFoundError(f"Patch file not found: {patch_path}")
    return patch_path


def _dry_run_result(repo_root: Path, patch_path: Path, apply_mode: str, format_patch: bool) -> PatchApplyResult:
    command = ["git", "apply", "--check", str(patch_path)]
    result = run_process(command, cwd=repo_root, check=False)
    format_label = "yes" if format_patch else "no"
    stdout = (
        f"Selected patch: {patch_path}\n"
        f"Apply mode: {APPLY_MODE_LABELS[apply_mode]}\n"
        f"Looks like Compatсh / git format-patch: {format_label}\n"
        + result.stdout
    )
    return PatchApplyResult(
        command=command,
        returncode=0 if result.returncode == 0 or format_patch else result.returncode,
        stdout=stdout,
        stderr=result.stderr,
        selected_patch=patch_path,
    )


def _apply_with_order(
    repo_root: Path,
    patch_path: Path,
    *,
    commit_message: str,
    format_patch: bool,
    primary: str,
    fallback: str,
) -> PatchApplyResult:
    attempts: list[str] = []
    primary_result = _try_apply_strategy(
        repo_root,
        patch_path,
        strategy=primary,
        commit_message=commit_message,
        format_patch=format_patch,
    )
    attempts.append(_format_attempt(primary, primary_result))
    if primary_result.succeeded:
        return _with_attempt_log(primary_result, attempts)

    if primary == "compatch":
        _abort_git_am(repo_root)

    fallback_result = _try_apply_strategy(
        repo_root,
        patch_path,
        strategy=fallback,
        commit_message=commit_message,
        format_patch=format_patch,
    )
    attempts.append(_format_attempt(fallback, fallback_result))
    return _with_attempt_log(fallback_result, attempts)


def _try_apply_strategy(
    repo_root: Path,
    patch_path: Path,
    *,
    strategy: str,
    commit_message: str,
    format_patch: bool,
) -> PatchApplyResult:
    if strategy == "compatch":
        return _apply_compatch(repo_root, patch_path, format_patch=format_patch)
    return _apply_packpatch(repo_root, patch_path, commit_message=commit_message)


def _apply_packpatch(repo_root: Path, patch_path: Path, *, commit_message: str) -> PatchApplyResult:
    check_command = ["git", "apply", "--check", str(patch_path)]
    check_result = run_process(check_command, cwd=repo_root, check=False)
    if check_result.returncode != 0:
        return PatchApplyResult(
            command=check_command,
            returncode=check_result.returncode,
            stdout=check_result.stdout,
            stderr=check_result.stderr,
            selected_patch=patch_path,
            applied_with="PackPatch",
        )

    apply_command = ["git", "apply", "--index", str(patch_path)]
    apply_result = run_process(apply_command, cwd=repo_root, check=False)
    if apply_result.returncode != 0:
        return PatchApplyResult(
            command=apply_command,
            returncode=apply_result.returncode,
            stdout=check_result.stdout + apply_result.stdout,
            stderr=check_result.stderr + apply_result.stderr,
            selected_patch=patch_path,
            applied_with="PackPatch",
        )

    stdout = check_result.stdout + apply_result.stdout + "Applied with PackPatch via git apply.\n"
    stderr = check_result.stderr + apply_result.stderr
    command = apply_command
    created_commit = False
    stripped_message = commit_message.strip()
    if stripped_message:
        commit_command = ["git", "commit", "-m", stripped_message]
        commit_result = run_process(commit_command, cwd=repo_root, check=False)
        command = commit_command
        stdout += commit_result.stdout
        stderr += commit_result.stderr
        created_commit = commit_result.returncode == 0
        returncode = commit_result.returncode
    else:
        returncode = apply_result.returncode

    return PatchApplyResult(
        command=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        selected_patch=patch_path,
        created_commit=created_commit,
        applied_with="PackPatch",
    )


def _apply_compatch(repo_root: Path, patch_path: Path, *, format_patch: bool) -> PatchApplyResult:
    command = ["git", "am", "--3way", str(patch_path)]
    if not format_patch:
        return PatchApplyResult(
            command=command,
            returncode=1,
            stdout="",
            stderr="Patch does not look like a git format-patch file.\n",
            selected_patch=patch_path,
            applied_with="Compatсh",
        )

    identity_error = _git_identity_error(repo_root)
    if identity_error:
        return PatchApplyResult(
            command=command,
            returncode=1,
            stdout="",
            stderr=identity_error,
            selected_patch=patch_path,
            applied_with="Compatсh",
        )

    result = run_process(command, cwd=repo_root, check=False)
    stdout = result.stdout
    if result.returncode == 0:
        stdout += "Applied with Compatсh via git am.\n"
    return PatchApplyResult(
        command=command,
        returncode=result.returncode,
        stdout=stdout,
        stderr=result.stderr,
        selected_patch=patch_path,
        created_commit=result.returncode == 0,
        applied_with="Compatсh",
    )


def _git_identity_error(repo_root: Path) -> str:
    name_result = run_process(["git", "config", "user.name"], cwd=repo_root, check=False)
    email_result = run_process(["git", "config", "user.email"], cwd=repo_root, check=False)
    missing: list[str] = []
    if name_result.returncode != 0 or not name_result.stdout.strip():
        missing.append("user.name")
    if email_result.returncode != 0 or not email_result.stdout.strip():
        missing.append("user.email")
    if not missing:
        return ""
    joined = ", ".join(missing)
    return (
        f"Git identity is not configured for Compatсh apply: {joined}.\n"
        "Set it with:\n"
        "  git config user.name \"Your Name\"\n"
        "  git config user.email \"you@example.com\"\n"
    )


def _abort_git_am(repo_root: Path) -> None:
    git_dir_result = run_process(["git", "rev-parse", "--git-dir"], cwd=repo_root, check=False)
    if git_dir_result.returncode != 0:
        return
    git_dir = (repo_root / git_dir_result.stdout.strip()).resolve()
    if not (git_dir / "rebase-apply").exists():
        return
    run_process(["git", "am", "--abort"], cwd=repo_root, check=False)


def _format_attempt(strategy: str, result: PatchApplyResult) -> str:
    label = "Compatсh" if strategy == "compatch" else "PackPatch"
    status = "OK" if result.succeeded else f"failed ({result.returncode})"
    return f"[{label}] {status}: {' '.join(result.command)}"


def _with_attempt_log(result: PatchApplyResult, attempts: list[str]) -> PatchApplyResult:
    attempt_log = "Apply strategy attempts:\n" + "\n".join(f"  {attempt}" for attempt in attempts) + "\n"
    return PatchApplyResult(
        command=result.command,
        returncode=result.returncode,
        stdout=attempt_log + result.stdout,
        stderr=result.stderr,
        selected_patch=result.selected_patch,
        created_commit=result.created_commit,
        applied_with=result.applied_with,
    )

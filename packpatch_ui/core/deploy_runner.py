"""Repository deploy helpers."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from packpatch_ui.services.process_runner import run_process


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
    """Synchronize the committed HEAD tree from *source* into *target*."""
    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    _validate_deploy_paths(source, target)

    git_path = shutil.which("git")
    if git_path is None:
        raise FileNotFoundError("git was not found in PATH")

    tar_path = shutil.which("tar")
    if tar_path is None:
        raise FileNotFoundError("tar was not found in PATH")

    rsync_path = shutil.which("rsync")
    if rsync_path is None:
        raise FileNotFoundError("rsync was not found in PATH")

    target.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="packpatch-deploy-") as staging_text:
        staging = Path(staging_text)
        git_command = [git_path, "archive", "HEAD"]
        tar_command = [tar_path, "-x", "-C", str(staging)]
        rsync_command = [rsync_path, "-av", "--delete", f"{staging}/", f"{target}/"]
        display_command = [*git_command, "|", *tar_command, "&&", *rsync_command]

        archive = subprocess.run(
            git_command,
            cwd=source,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        archive_stderr = _decode_process_output(archive.stderr)
        if archive.returncode != 0:
            return DeployResult(
                command=display_command,
                stdout="",
                stderr=archive_stderr,
                returncode=archive.returncode,
            )

        extract = subprocess.run(
            tar_command,
            input=archive.stdout,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        extract_stdout = _decode_process_output(extract.stdout)
        extract_stderr = _decode_process_output(extract.stderr)
        if extract.returncode != 0:
            return DeployResult(
                command=display_command,
                stdout=extract_stdout,
                stderr="\n".join(part for part in (archive_stderr, extract_stderr) if part),
                returncode=extract.returncode,
            )

        completed = run_process(rsync_command, check=False)

    stdout = "\n".join(part for part in (extract_stdout, completed.stdout) if part)
    stderr = "\n".join(part for part in (archive_stderr, extract_stderr, completed.stderr) if part)
    return DeployResult(
        command=display_command,
        stdout=stdout,
        stderr=stderr,
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


def _decode_process_output(output: bytes) -> str:
    return output.decode(errors="replace")

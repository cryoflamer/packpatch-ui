from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from packpatch_ui.core.pack_runner import create_pack, default_pack_script_path


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=check,
    )


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.name", "Pack Test User")
    git(repo, "config", "user.email", "pack-test@example.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('base')\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Initial source commit")
    return repo


def commit(repo: Path, message: str, path: str, content: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git(repo, "add", path)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def unpack_archive(archive: Path, tmp_path: Path) -> Path:
    unpacked = tmp_path / f"unpacked-{archive.stem.replace('.', '-')}"
    unpacked.mkdir(parents=True)
    subprocess.run(
        ["tar", "-xzf", str(archive), "-C", str(unpacked)],
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    return unpacked / "chatgpt-pack"


def make_pack(
    repo: Path,
    tmp_path: Path,
    mode: str,
    *,
    selected_files: list[str] | None = None,
    include_sensitive: bool = False,
    include_unversioned: bool = False,
    history_depth: int = 1,
) -> tuple[Path, Path]:
    out_dir = tmp_path / "pack-output"
    out_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "bash",
        str(default_pack_script_path()),
        "full" if mode == "full-untracked" else mode,
        "pack-tests",
        "--history-depth",
        str(history_depth),
    ]
    if include_unversioned or mode == "full-untracked":
        command.append("--include-untracked")
    if include_sensitive:
        command.append("--include-sensitive")
    command.extend(selected_files or [])

    env = dict(os.environ)
    env["CHATGPT_PACK_OUT_DIR"] = str(out_dir)
    completed = subprocess.run(
        command,
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    archives = sorted(out_dir.glob("chatgpt-pack-*.tar.gz"), key=lambda path: path.stat().st_mtime_ns)
    assert archives
    archive = archives[-1]
    return archive, unpack_archive(archive, tmp_path)


def read_meta(pack_dir: Path) -> dict[str, object]:
    return json.loads((pack_dir / "patch.meta.json").read_text(encoding="utf-8"))


def pack_files(pack_dir: Path) -> set[str]:
    excluded = {"CHATGPT_PACK_USAGE.md", "patch.base.sha256", "patch.meta.json"}
    return set(git(pack_dir, "status", "--short").stdout.split()) | {
        path.relative_to(pack_dir).as_posix()
        for path in pack_dir.rglob("*")
        if path.is_file()
        and ".git" not in path.relative_to(pack_dir).parts
        and path.name not in excluded
    }


def test_full_pack_preserves_head_worktree_metadata_and_usage(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    source_head = commit(repo, "Second source commit", "README.md", "second\n")
    (repo / "README.md").write_text("working tree\n", encoding="utf-8")
    (repo / "local.tmp").write_text("local\n", encoding="utf-8")

    archive, pack_dir = make_pack(repo, tmp_path, "full", history_depth=1)
    meta = read_meta(pack_dir)
    usage = (pack_dir / "CHATGPT_PACK_USAGE.md").read_text(encoding="utf-8")

    assert archive.name.startswith("chatgpt-pack-full-pack-tests-")
    assert archive.name.endswith(".tar.gz")
    assert git(pack_dir, "rev-parse", "HEAD").stdout.strip() == source_head
    assert git(pack_dir, "log", "-1", "--pretty=%s").stdout.strip() == "Second source commit"
    assert (pack_dir / "README.md").read_text(encoding="utf-8") == "working tree\n"
    assert "README.md" in git(pack_dir, "status", "--short").stdout
    assert not (pack_dir / "local.tmp").exists()
    assert (pack_dir / ".git" / "shallow").is_file()
    assert meta["mode"] == "full"
    assert meta["task"] == "pack-tests"
    assert meta["history_depth"] == "1"
    assert meta["source"]["branch"] == "main"
    assert meta["source"]["head"] == source_head
    assert "## PackPatch mode" in usage
    assert "## Compatсh mode" in usage
    assert "git format-patch -1 --stdout" in usage
    assert "git am --3way" in usage
    assert "Verify that the `.patch` file exists and is non-empty" in usage


def test_full_pack_can_include_unversioned_files_and_preserve_depth_two(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    commit(repo, "Second commit", "README.md", "second\n")
    commit(repo, "Third commit", "README.md", "third\n")
    (repo / "local.tmp").write_text("local\n", encoding="utf-8")

    _, pack_dir = make_pack(repo, tmp_path, "full", include_unversioned=True, history_depth=2)

    assert (pack_dir / "local.tmp").read_text(encoding="utf-8") == "local\n"
    assert int(git(pack_dir, "rev-list", "--count", "HEAD").stdout.strip()) == 2
    assert read_meta(pack_dir)["history_depth"] == "2"


def test_full_untracked_mode_always_includes_unversioned_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "local.tmp").write_text("local\n", encoding="utf-8")

    _, pack_dir = make_pack(repo, tmp_path, "full-untracked", include_unversioned=False)

    assert (pack_dir / "local.tmp").is_file()


def test_safe_env_templates_are_included_in_full_slice_and_changed_packs(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    templates = {
        ".env.example": "EXAMPLE=value\n",
        "config/.env.sample": "SAMPLE=value\n",
        "config/.env.template": "TEMPLATE=value\n",
        "config/.env.dist": "DIST=value\n",
    }
    for path, content in templates.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(repo, "add", *templates)
    git(repo, "commit", "-m", "Env templates were added")

    _, full_pack = make_pack(repo, tmp_path / "full", "full")
    for path, content in templates.items():
        assert (full_pack / path).read_text(encoding="utf-8") == content

    _, slice_pack = make_pack(
        repo,
        tmp_path / "slice",
        "slice",
        selected_files=[".env.example", "config"],
    )
    for path, content in templates.items():
        assert (slice_pack / path).read_text(encoding="utf-8") == content

    (repo / ".env.example").write_text("EXAMPLE=changed\n", encoding="utf-8")
    (repo / "config" / ".env.sample").write_text("SAMPLE=changed\n", encoding="utf-8")
    _, changed_pack = make_pack(repo, tmp_path / "changed", "changed")
    assert (changed_pack / ".env.example").read_text(encoding="utf-8") == "EXAMPLE=changed\n"
    assert (changed_pack / "config" / ".env.sample").read_text(encoding="utf-8") == "SAMPLE=changed\n"


def test_real_env_files_remain_sensitive(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    secrets = {
        ".env": "SECRET=root\n",
        ".env.production": "SECRET=prod\n",
        "config/.env": "SECRET=nested\n",
        "config/.env.local": "SECRET=local\n",
    }
    for path, content in secrets.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(repo, "add", "-f", *secrets)
    git(repo, "commit", "-m", "Tracked env files were added")

    _, excluded_pack = make_pack(repo, tmp_path / "excluded", "full")
    for path in secrets:
        assert not (excluded_pack / path).exists()

    _, included_pack = make_pack(repo, tmp_path / "included", "full", include_sensitive=True)
    for path, content in secrets.items():
        assert (included_pack / path).read_text(encoding="utf-8") == content


def test_tracked_sensitive_files_require_explicit_opt_in(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "client.key").write_text("tracked-secret\n", encoding="utf-8")
    git(repo, "add", "client.key")
    git(repo, "commit", "-m", "Tracked key was added")

    _, excluded_pack = make_pack(repo, tmp_path / "excluded", "full")
    _, included_pack = make_pack(repo, tmp_path / "included", "full", include_sensitive=True)

    assert not (excluded_pack / "client.key").exists()
    assert (included_pack / "client.key").read_text(encoding="utf-8") == "tracked-secret\n"


def test_untracked_sensitive_files_are_never_included(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "local.key").write_text("never-pack\n", encoding="utf-8")

    _, pack_dir = make_pack(
        repo,
        tmp_path,
        "full",
        include_sensitive=True,
        include_unversioned=True,
    )

    assert not (pack_dir / "local.key").exists()


def test_changed_pack_defaults_to_changed_tracked_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    (repo / "local.tmp").write_text("local\n", encoding="utf-8")

    _, pack_dir = make_pack(repo, tmp_path, "changed")

    assert (pack_dir / "README.md").read_text(encoding="utf-8") == "changed\n"
    assert not (pack_dir / "src" / "app.py").exists()
    assert not (pack_dir / "local.tmp").exists()


def test_changed_pack_can_include_unversioned_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    (repo / "local.tmp").write_text("local\n", encoding="utf-8")

    _, pack_dir = make_pack(repo, tmp_path, "changed", include_unversioned=True)

    assert (pack_dir / "README.md").is_file()
    assert (pack_dir / "local.tmp").is_file()


def test_slice_pack_contains_only_selected_paths(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    commit(repo, "Docs were added", "docs/guide.md", "guide\n")

    _, pack_dir = make_pack(repo, tmp_path, "slice", selected_files=["docs"])

    assert (pack_dir / "docs" / "guide.md").is_file()
    assert not (pack_dir / "README.md").exists()
    assert not (pack_dir / "src" / "app.py").exists()


def test_slice_pack_requires_a_selected_path(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)

    with pytest.raises(ValueError, match="Select at least one file"):
        create_pack(repo, "slice", "pack-tests", [], history_depth=1)

"""Helpers for listing PackPatch archives and patch files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactInfo:
    """File artifact shown in the UI."""

    path: Path
    size_bytes: int
    modified_timestamp: float

    @property
    def display_name(self) -> str:
        """Return a compact display name with size information."""
        return f"{self.path.name} ({self.size_label})"

    @property
    def size_label(self) -> str:
        """Return a human-readable file size."""
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0 or unit == "GB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
            size /= 1024.0
        return f"{self.size_bytes} B"


def list_pack_archives(repo_root: Path) -> list[ArtifactInfo]:
    """Return pack archives from the repository-local chatgpt-packs directory."""
    return _list_artifacts(repo_root / "chatgpt-packs", patterns=("chatgpt-pack-*.tar.gz",))


def list_patch_files(patch_dir: Path) -> list[ArtifactInfo]:
    """Return patch files from *patch_dir*."""
    return _list_artifacts(patch_dir, patterns=("*.patch", "*.diff"))


def _list_artifacts(directory: Path, *, patterns: tuple[str, ...]) -> list[ArtifactInfo]:
    if not directory.is_dir():
        return []

    artifacts: list[ArtifactInfo] = []
    for pattern in patterns:
        for path in directory.glob(pattern):
            if not path.is_file():
                continue
            stat = path.stat()
            artifacts.append(
                ArtifactInfo(
                    path=path,
                    size_bytes=stat.st_size,
                    modified_timestamp=stat.st_mtime,
                )
            )

    return sorted(artifacts, key=lambda item: (item.modified_timestamp, item.path.name), reverse=True)

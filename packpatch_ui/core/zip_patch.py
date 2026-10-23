"""Safely inspect and extract a single patch member from ZIP archives."""

from __future__ import annotations

import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator

MAX_PATCH_BYTES = 32 * 1024 * 1024


def patch_members(archive: Path) -> list[str]:
    """List safe, non-directory patch members without extracting the archive."""
    members: list[str] = []
    try:
        with zipfile.ZipFile(archive) as handle:
            for entry in handle.infolist():
                name = entry.filename
                parts = PurePosixPath(name).parts
                if (entry.is_dir() or name.startswith(("/", "\\")) or "\\" in name
                        or ".." in parts or not parts or parts[0].endswith(":")
                        or Path(name).suffix.lower() not in (".patch", ".diff")):
                    continue
                if entry.file_size > MAX_PATCH_BYTES:
                    continue
                if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    continue
                members.append(name)
    except (zipfile.BadZipFile, OSError, RuntimeError) as error:
        raise ValueError(f"Cannot read ZIP archive: {error}") from error
    return members


@contextmanager
def extracted_patch(archive: Path, member: str) -> Iterator[Path]:
    """Extract only the validated member to a private, temporary patch file."""
    if member not in patch_members(archive):
        raise ValueError(f"Invalid or missing ZIP patch member: {member}")
    with tempfile.TemporaryDirectory(prefix="packpatch-zip-") as directory:
        target = Path(directory) / Path(member).name
        try:
            with zipfile.ZipFile(archive) as handle:
                with handle.open(member) as source, target.open("wb") as output:
                    remaining = MAX_PATCH_BYTES + 1
                    while remaining > 0:
                        chunk = source.read(min(65536, remaining))
                        if not chunk:
                            break
                        output.write(chunk)
                        remaining -= len(chunk)
                    if remaining == 0:
                        raise ValueError("ZIP patch exceeds size limit")
        except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as error:
            raise ValueError(f"Cannot extract ZIP patch: {error}") from error
        if target.stat().st_size > MAX_PATCH_BYTES:
            raise ValueError("ZIP patch exceeds size limit")
        yield target

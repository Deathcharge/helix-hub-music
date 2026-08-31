"""Small filesystem guards shared by the private recovery stores."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from samsarix_workspace.errors import WorkspaceError

MAX_METADATA_BYTES = 8192
RESERVED_NAMES = {".samsarix-trash", ".samsarix-history"}


def reserved_name(name: str) -> bool:
    """Include Windows trailing-dot/space and alternate-stream spellings."""
    return name.split(":", 1)[0].rstrip(" .").casefold() in RESERVED_NAMES


def linked_metadata(metadata: os.stat_result) -> bool:
    """Treat Windows junctions/reparse points as links on Python 3.11 too."""
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x400
    )


def plain_directory(path: Path) -> None:
    metadata = path.lstat()
    if linked_metadata(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Not a plain directory")


def read_regular(path: Path, limit: int) -> bytes:
    metadata = path.lstat()
    if (
        linked_metadata(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size > limit
    ):
        raise ValueError("Invalid recovery file")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as document:
        opened = os.fstat(document.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ValueError("Invalid opened recovery file")
        encoded = document.read(limit + 1)
    if len(encoded) > limit:
        raise ValueError("Recovery file exceeds its size limit")
    return encoded


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(read_regular(path, MAX_METADATA_BYTES))
    if not isinstance(value, dict):
        raise ValueError("Invalid metadata object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True).encode("utf-8")
    if len(encoded) > MAX_METADATA_BYTES:
        raise WorkspaceError("invalid_path", "Recovery metadata exceeds its size limit.")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as document:
        document.write(encoded)
        document.flush()
        os.fsync(document.fileno())

"""Sandboxed, persistent workspace operations.

All public paths are POSIX-style and relative to ``root``. The implementation
rejects symlinks instead of following them so an in-root link cannot escape the
workspace boundary.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


class WorkspaceError(Exception):
    """A stable, user-facing workspace failure."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class Entry:
    """Serializable metadata for a workspace entry."""

    path: str
    name: str
    kind: str
    size: int
    modified_at: str
    etag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileDocument:
    """Text file content with optimistic-concurrency metadata."""

    path: str
    content: str
    size: int
    modified_at: str
    etag: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Workspace:
    """A bounded text-file workspace rooted at one canonical directory."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int = 1_048_576,
        max_total_bytes: int = 52_428_800,
        max_entries: int = 2_000,
    ) -> None:
        requested_root = Path(root).expanduser()
        requested_root.mkdir(parents=True, exist_ok=True)
        self.root = requested_root.resolve(strict=True)
        if not self.root.is_dir():
            raise WorkspaceError("invalid_root", "Workspace root must be a directory.")
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.max_entries = max_entries
        self._lock = threading.RLock()

    @staticmethod
    def _public_path(path: str) -> PurePosixPath:
        if "\x00" in path or "\\" in path:
            raise WorkspaceError("invalid_path", "Paths must be relative and use forward slashes.")
        if any(part in {"", ".", ".."} for part in path.split("/")):
            raise WorkspaceError("invalid_path", "Path traversal is not allowed.")
        public = PurePosixPath(path)
        if public.is_absolute() or public.drive:
            raise WorkspaceError("invalid_path", "Absolute paths are not allowed.")
        return public

    def normalize(self, path: str, *, allow_root: bool = True) -> str:
        """Return a canonical public path without touching the filesystem."""

        if path in {"", "."}:
            if allow_root:
                return ""
            raise WorkspaceError("root_not_allowed", "This operation cannot target the root.")
        return self._public_path(path).as_posix()

    def _lexical(self, path: str, *, allow_root: bool = True) -> Path:
        normalized = self.normalize(path, allow_root=allow_root)
        candidate = (
            self.root.joinpath(*PurePosixPath(normalized).parts) if normalized else self.root
        )
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:  # defensive: PurePosixPath already rejects this
            raise WorkspaceError("path_escape", "Path escapes the workspace root.") from exc
        return candidate

    def _reject_symlink_parts(self, candidate: Path, *, include_leaf: bool = True) -> None:
        relative = candidate.relative_to(self.root)
        current = self.root
        parts = relative.parts if include_leaf else relative.parts[:-1]
        for part in parts:
            current = current / part
            try:
                if current.is_symlink():
                    raise WorkspaceError(
                        "symlink_not_allowed", "Symbolic links are not allowed in workspaces."
                    )
            except OSError as exc:
                raise WorkspaceError(
                    "path_unavailable", "The requested path is unavailable."
                ) from exc
        if include_leaf and candidate.exists() and candidate.is_file():
            try:
                if candidate.stat(follow_symlinks=False).st_nlink > 1:
                    raise WorkspaceError(
                        "hardlink_not_allowed", "Hard-linked files are not allowed in workspaces."
                    )
            except OSError as exc:
                raise WorkspaceError(
                    "path_unavailable", "The requested path is unavailable."
                ) from exc

    def _safe_path(
        self,
        path: str,
        *,
        allow_root: bool = True,
        must_exist: bool = False,
        include_leaf: bool = True,
    ) -> Path:
        candidate = self._lexical(path, allow_root=allow_root)
        self._reject_symlink_parts(candidate, include_leaf=include_leaf)
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(self.root)
        except (OSError, ValueError) as exc:
            raise WorkspaceError("path_escape", "Path escapes the workspace root.") from exc
        if must_exist and not candidate.exists():
            raise WorkspaceError("not_found", "The requested entry does not exist.", 404)
        return candidate

    @staticmethod
    def _timestamp(path: Path) -> str:
        metadata = path.lstat() if path.is_symlink() else path.stat()
        stamp = datetime.fromtimestamp(metadata.st_mtime, tz=UTC)
        return stamp.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _etag_bytes(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _entry(self, path: Path) -> Entry:
        relative = path.relative_to(self.root).as_posix()
        if path.is_symlink():
            return Entry(relative, path.name, "blocked_symlink", 0, self._timestamp(path))
        if path.is_dir():
            return Entry(relative, path.name, "directory", 0, self._timestamp(path))
        if not path.is_file():
            return Entry(relative, path.name, "blocked_special", 0, self._timestamp(path))
        size = path.stat().st_size
        if path.stat(follow_symlinks=False).st_nlink > 1:
            return Entry(relative, path.name, "blocked_hardlink", size, self._timestamp(path))
        return Entry(relative, path.name, "file", size, self._timestamp(path))

    def list_entries(self, path: str = "", *, recursive: bool = False) -> list[Entry]:
        """List a folder with deterministic ordering and an entry ceiling."""

        directory = self._safe_path(path, must_exist=True)
        if not directory.is_dir():
            raise WorkspaceError("not_a_directory", "The requested path is not a directory.")

        entries: list[Entry] = []
        if recursive:
            for current_root, directories, files in os.walk(directory, followlinks=False):
                current = Path(current_root)
                linked_directories = [name for name in directories if (current / name).is_symlink()]
                directories[:] = sorted(
                    name for name in directories if not (current / name).is_symlink()
                )
                names = [*directories, *sorted(linked_directories), *sorted(files)]
                for name in names:
                    entries.append(self._entry(current / name))
                    if len(entries) > self.max_entries:
                        raise WorkspaceError(
                            "entry_limit_exceeded",
                            f"Workspace listing exceeds {self.max_entries} entries.",
                            413,
                        )
        else:
            entries = [
                self._entry(item) for item in sorted(directory.iterdir(), key=lambda p: p.name)
            ]
            if len(entries) > self.max_entries:
                raise WorkspaceError(
                    "entry_limit_exceeded",
                    f"Folder listing exceeds {self.max_entries} entries.",
                    413,
                )
        return sorted(entries, key=lambda entry: (entry.path.casefold(), entry.path))

    def read_file(self, path: str) -> FileDocument:
        """Read one bounded UTF-8 text file."""

        candidate = self._safe_path(path, allow_root=False, must_exist=True)
        if not candidate.is_file():
            raise WorkspaceError("not_a_file", "The requested path is not a file.")
        size = candidate.stat().st_size
        if size > self.max_file_bytes:
            raise WorkspaceError(
                "file_too_large",
                f"Files are limited to {self.max_file_bytes} bytes.",
                413,
            )
        try:
            content_bytes = candidate.read_bytes()
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError(
                "binary_file", "Only UTF-8 text files can be opened in the editor.", 415
            ) from exc
        except OSError as exc:
            raise WorkspaceError("read_failed", "The file could not be read.", 500) from exc
        return FileDocument(
            path=self.normalize(path, allow_root=False),
            content=content,
            size=len(content_bytes),
            modified_at=self._timestamp(candidate),
            etag=self._etag_bytes(content_bytes),
        )

    def usage_bytes(self) -> int:
        """Return total regular-file bytes without following symlinks."""

        total = 0
        for current_root, directories, files in os.walk(self.root, followlinks=False):
            current = Path(current_root)
            directories[:] = [name for name in directories if not (current / name).is_symlink()]
            for name in files:
                item = current / name
                try:
                    mode = item.stat(follow_symlinks=False).st_mode
                    if stat.S_ISREG(mode):
                        total += item.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
        return total

    def write_file(
        self,
        path: str,
        content: str,
        *,
        expected_etag: str | None = None,
    ) -> FileDocument:
        """Atomically create or replace a UTF-8 file within configured quotas."""

        content_bytes = content.encode("utf-8")
        if len(content_bytes) > self.max_file_bytes:
            raise WorkspaceError(
                "file_too_large",
                f"Files are limited to {self.max_file_bytes} bytes.",
                413,
            )
        candidate = self._safe_path(path, allow_root=False)
        self._reject_symlink_parts(candidate, include_leaf=True)
        parent = candidate.parent
        self._reject_symlink_parts(parent)
        if not parent.exists() or not parent.is_dir():
            raise WorkspaceError("parent_not_found", "The parent folder does not exist.", 404)

        with self._lock:
            old_size = 0
            if candidate.exists():
                if not candidate.is_file():
                    raise WorkspaceError("not_a_file", "The destination is not a file.")
                existing = candidate.read_bytes()
                old_size = len(existing)
                if expected_etag is not None and self._etag_bytes(existing) != expected_etag:
                    raise WorkspaceError(
                        "edit_conflict",
                        "The file changed after it was opened. Reload it before saving.",
                        409,
                    )
            elif expected_etag is not None:
                raise WorkspaceError(
                    "edit_conflict", "The file no longer exists. Refresh before saving.", 409
                )

            projected = self.usage_bytes() - old_size + len(content_bytes)
            if projected > self.max_total_bytes:
                raise WorkspaceError(
                    "workspace_quota_exceeded",
                    f"Workspace storage is limited to {self.max_total_bytes} bytes.",
                    413,
                )

            temporary_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=parent,
                    prefix=".samsarix-",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary.write(content_bytes)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_name = temporary.name
                os.replace(temporary_name, candidate)
            except OSError as exc:
                if temporary_name:
                    Path(temporary_name).unlink(missing_ok=True)
                raise WorkspaceError("write_failed", "The file could not be saved.", 500) from exc
        return self.read_file(path)

    def make_directory(self, path: str) -> Entry:
        """Create one directory; its parent must already exist."""

        candidate = self._safe_path(path, allow_root=False)
        self._reject_symlink_parts(candidate.parent)
        if not candidate.parent.exists() or not candidate.parent.is_dir():
            raise WorkspaceError("parent_not_found", "The parent folder does not exist.", 404)
        try:
            candidate.mkdir()
        except FileExistsError as exc:
            raise WorkspaceError(
                "already_exists", "An entry already exists at that path.", 409
            ) from exc
        except OSError as exc:
            raise WorkspaceError("create_failed", "The folder could not be created.", 500) from exc
        return self._entry(candidate)

    def move(self, source: str, destination: str) -> Entry:
        """Move or rename one entry without overwriting an existing destination."""

        source_path = self._safe_path(source, allow_root=False, must_exist=True)
        destination_path = self._safe_path(destination, allow_root=False)
        self._reject_symlink_parts(destination_path.parent)
        if source_path.is_symlink():
            raise WorkspaceError("symlink_not_allowed", "Symbolic links cannot be moved.")
        if not destination_path.parent.exists() or not destination_path.parent.is_dir():
            raise WorkspaceError("parent_not_found", "The destination folder does not exist.", 404)
        if destination_path.exists():
            raise WorkspaceError("already_exists", "The destination already exists.", 409)
        if source_path.is_dir():
            try:
                destination_path.relative_to(source_path)
            except ValueError:
                pass
            else:
                raise WorkspaceError("invalid_move", "A folder cannot be moved into itself.")
        try:
            source_path.rename(destination_path)
        except OSError as exc:
            raise WorkspaceError("move_failed", "The entry could not be moved.", 500) from exc
        return self._entry(destination_path)

    def delete(self, path: str, *, recursive: bool = False) -> None:
        """Delete an entry; deleting the workspace root is structurally impossible."""

        candidate = self._lexical(path, allow_root=False)
        self._reject_symlink_parts(candidate, include_leaf=False)
        if candidate.is_symlink():
            candidate.unlink()
            return
        if (
            candidate.exists()
            and candidate.is_file()
            and candidate.stat(follow_symlinks=False).st_nlink > 1
        ):
            candidate.unlink()
            return
        candidate = self._safe_path(path, allow_root=False, must_exist=True)
        try:
            if candidate.is_dir():
                if recursive:
                    shutil.rmtree(candidate)
                else:
                    candidate.rmdir()
            else:
                candidate.unlink()
        except OSError as exc:
            code = (
                "directory_not_empty" if candidate.is_dir() and not recursive else "delete_failed"
            )
            status = 409 if code == "directory_not_empty" else 500
            message = (
                "The folder is not empty; confirm recursive deletion."
                if code == "directory_not_empty"
                else "The entry could not be deleted."
            )
            raise WorkspaceError(code, message, status) from exc

    def summary(self) -> dict[str, Any]:
        """Return safe workspace metadata without exposing the host root path."""

        entries = self.list_entries("", recursive=True)
        return {
            "name": self.root.name,
            "entries": len(entries),
            "usage_bytes": self.usage_bytes(),
            "limits": {
                "max_file_bytes": self.max_file_bytes,
                "max_total_bytes": self.max_total_bytes,
                "max_entries": self.max_entries,
            },
        }

"""Sandboxed, persistent workspace operations.

All public paths are POSIX-style and relative to ``root``. The implementation
rejects symlinks instead of following them so an in-root link cannot escape the
workspace boundary.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import stat
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any, Concatenate, ParamSpec, TypeVar

from samsarix_workspace.errors import WorkspaceError as WorkspaceError
from samsarix_workspace.history import HistoryStore
from samsarix_workspace.trash import TrashStore, linked_metadata, reserved_name

P = ParamSpec("P")
T = TypeVar("T")


def _locked(
    method: Callable[Concatenate[Workspace, P], T],
) -> Callable[Concatenate[Workspace, P], T]:
    """Keep reads and mutations consistent within one application instance."""

    @wraps(method)
    def invoke(self: Workspace, /, *args: P.args, **kwargs: P.kwargs) -> T:
        with self._lock:
            return method(self, *args, **kwargs)

    return invoke


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


@dataclass(frozen=True, slots=True)
class SearchMatch:
    """One bounded matching line in a UTF-8 workspace file."""

    path: str
    line: int
    column: int
    length: int
    preview: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SearchReport:
    """Resource accounting and matches for one workspace search."""

    query: str
    path: str
    matches: tuple[SearchMatch, ...]
    scanned_files: int
    scanned_bytes: int
    skipped_files: int
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["matches"] = [match.to_dict() for match in self.matches]
        return payload


class Workspace:
    """A bounded text-file workspace rooted at one canonical directory."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int = 1_048_576,
        max_total_bytes: int = 52_428_800,
        max_entries: int = 2_000,
        max_trash_bytes: int = 52_428_800,
        max_trash_items: int = 100,
        max_trash_entries: int = 2_000,
        max_history_bytes: int = 52_428_800,
        max_history_items: int = 200,
        max_history_per_file: int = 20,
    ) -> None:
        requested_root = Path(root).expanduser()
        requested_root.mkdir(parents=True, exist_ok=True)
        self.root = requested_root.resolve(strict=True)
        if not self.root.is_dir():
            raise WorkspaceError("invalid_root", "Workspace root must be a directory.")
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.max_entries = max_entries
        self.workspace_id = secrets.token_hex(8)
        self._lock = threading.RLock()
        self._trash = TrashStore(
            self,
            max_bytes=max_trash_bytes,
            max_items=max_trash_items,
            max_entries=max_trash_entries,
        )
        self._history = HistoryStore(
            self,
            max_bytes=max_history_bytes,
            max_items=max_history_items,
            max_per_file=max_history_per_file,
        )

    @staticmethod
    def _public_path(path: str) -> PurePosixPath:
        try:
            path.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise WorkspaceError("invalid_path", "Paths must contain valid Unicode text.") from exc
        if "\x00" in path or "\\" in path:
            raise WorkspaceError("invalid_path", "Paths must be relative and use forward slashes.")
        if any(part in {"", ".", ".."} for part in path.split("/")):
            raise WorkspaceError("invalid_path", "Path traversal is not allowed.")
        public = PurePosixPath(path)
        if public.is_absolute() or public.drive:
            raise WorkspaceError("invalid_path", "Absolute paths are not allowed.")
        if any(reserved_name(part) for part in public.parts):
            raise WorkspaceError(
                "reserved_path",
                "Samsarix recovery storage is private; use Trash or History actions.",
            )
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
                if os.path.lexists(current) and linked_metadata(current.lstat()):
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
            relative = resolved.relative_to(self.root)
        except (OSError, ValueError) as exc:
            raise WorkspaceError("path_escape", "Path escapes the workspace root.") from exc
        if any(reserved_name(part) for part in relative.parts):
            raise WorkspaceError(
                "reserved_path",
                "Samsarix recovery storage is private; use Trash or History actions.",
            )
        if must_exist and not candidate.exists():
            raise WorkspaceError("not_found", "The requested entry does not exist.", 404)
        return candidate

    @staticmethod
    def _timestamp(metadata: os.stat_result) -> str:
        stamp = datetime.fromtimestamp(metadata.st_mtime, tz=UTC)
        return stamp.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _etag_bytes(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _entry(self, path: Path) -> Entry:
        relative = path.relative_to(self.root).as_posix()
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise WorkspaceError("path_unavailable", "The requested path is unavailable.") from exc
        modified_at = self._timestamp(metadata)
        mode = metadata.st_mode
        if linked_metadata(metadata):
            return Entry(relative, path.name, "blocked_symlink", 0, modified_at)
        if stat.S_ISDIR(mode):
            return Entry(relative, path.name, "directory", 0, modified_at)
        if not stat.S_ISREG(mode):
            return Entry(relative, path.name, "blocked_special", 0, modified_at)
        if metadata.st_nlink > 1:
            return Entry(relative, path.name, "blocked_hardlink", metadata.st_size, modified_at)
        return Entry(relative, path.name, "file", metadata.st_size, modified_at)

    @staticmethod
    def _walk_directories(current: Path, names: list[str]) -> tuple[list[str], list[str]]:
        """Classify walk results without following links or failing on removed folders."""

        ordinary: list[str] = []
        linked: list[str] = []
        for name in names:
            if reserved_name(name):
                continue
            try:
                metadata = (current / name).lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise WorkspaceError(
                    "path_unavailable", "A workspace folder is unavailable."
                ) from exc
            (linked if linked_metadata(metadata) else ordinary).append(name)
        return sorted(ordinary), sorted(linked)

    @_locked
    def list_entries(self, path: str = "", *, recursive: bool = False) -> list[Entry]:
        """List a folder with deterministic ordering and an entry ceiling."""

        directory = self._safe_path(path, must_exist=True)
        if not directory.is_dir():
            raise WorkspaceError("not_a_directory", "The requested path is not a directory.")

        entries: list[Entry] = []
        if recursive:
            for current_root, directories, files in os.walk(directory, followlinks=False):
                current = Path(current_root)
                ordinary, linked_directories = self._walk_directories(current, directories)
                directories[:] = ordinary
                files = [name for name in files if not reserved_name(name)]
                names = [*directories, *linked_directories, *sorted(files)]
                for name in names:
                    entries.append(self._entry(current / name))
                    if len(entries) > self.max_entries:
                        raise WorkspaceError(
                            "entry_limit_exceeded",
                            f"Workspace listing exceeds {self.max_entries} entries.",
                            413,
                        )
        else:
            for item in sorted(directory.iterdir(), key=lambda item: item.name):
                if reserved_name(item.name):
                    continue
                entries.append(self._entry(item))
                if len(entries) > self.max_entries:
                    raise WorkspaceError(
                        "entry_limit_exceeded",
                        f"Folder listing exceeds {self.max_entries} entries.",
                        413,
                    )
        return sorted(entries, key=lambda entry: (entry.path.casefold(), entry.path))

    @_locked
    def assert_directory(self, path: str = "") -> None:
        """Validate that a public path resolves to an existing workspace directory."""

        candidate = self._safe_path(path, must_exist=True)
        if not candidate.is_dir():
            raise WorkspaceError("not_a_directory", "The requested path is not a directory.")

    @staticmethod
    def _search_preview(line: str, column: int, *, limit: int = 240) -> str:
        compact = line.strip()
        if len(compact) <= limit:
            return compact
        stripped_prefix = len(line) - len(line.lstrip())
        compact_column = max(0, column - stripped_prefix)
        start = max(0, compact_column - limit // 3)
        end = min(len(compact), start + limit)
        if end - start < limit:
            start = max(0, end - limit)
        return ("…" if start else "") + compact[start:end] + ("…" if end < len(compact) else "")

    @staticmethod
    def _casefold_span(line: str, needle: str) -> tuple[int, int] | None:
        """Map a case-folded match back to a source-character span."""

        folded_parts: list[str] = []
        folded_to_source: list[int] = []
        for source_index, character in enumerate(line):
            folded = character.casefold()
            folded_parts.append(folded)
            folded_to_source.extend([source_index] * len(folded))
        folded_position = "".join(folded_parts).find(needle)
        if folded_position < 0:
            return None
        start = folded_to_source[folded_position]
        end = folded_to_source[folded_position + len(needle) - 1] + 1
        return start, end - start

    def _read_file_bytes(self, path: str, *, limit: int) -> tuple[Path, bytes]:
        """Read no more than ``limit`` bytes plus one detection byte."""

        candidate = self._safe_path(path, allow_root=False, must_exist=True)
        if not candidate.is_file():
            raise WorkspaceError("not_a_file", "The requested path is not a file.")
        try:
            with candidate.open("rb") as document:
                content_bytes = document.read(limit + 1)
        except OSError as exc:
            raise WorkspaceError("read_failed", "The file could not be read.", 500) from exc
        return candidate, content_bytes

    @_locked
    def search_text(
        self,
        query: str,
        path: str = "",
        *,
        case_sensitive: bool = False,
        limit: int = 100,
        max_scan_bytes: int = 10_485_760,
    ) -> SearchReport:
        """Search matching lines across bounded UTF-8 files without following links."""

        if not query:
            raise WorkspaceError("invalid_search", "Search text cannot be empty.")
        if not 1 <= limit <= 200:
            raise WorkspaceError("invalid_search", "Search result limit must be between 1 and 200.")
        if max_scan_bytes < 0:
            raise WorkspaceError("invalid_search", "Search byte limit cannot be negative.")
        self.assert_directory(path)
        normalized_path = self.normalize(path)
        needle = query if case_sensitive else query.casefold()
        matches: list[SearchMatch] = []
        scanned_files = 0
        scanned_bytes = 0
        skipped_files = 0
        truncated = False

        for entry in self.list_entries(normalized_path, recursive=True):
            if entry.kind != "file":
                continue
            remaining_bytes = max_scan_bytes - scanned_bytes
            if remaining_bytes <= 0:
                truncated = True
                break
            try:
                _candidate, content_bytes = self._read_file_bytes(
                    entry.path,
                    limit=min(remaining_bytes, self.max_file_bytes),
                )
            except WorkspaceError as exc:
                if exc.code != "read_failed":
                    raise
                skipped_files += 1
                continue
            scanned_bytes += len(content_bytes)
            oversized = len(content_bytes) > self.max_file_bytes
            if oversized:
                skipped_files += 1
            if len(content_bytes) > remaining_bytes:
                truncated = True
                break
            if oversized:
                continue
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                skipped_files += 1
                continue
            scanned_files += 1
            for line_number, line in enumerate(content.splitlines(), 1):
                if case_sensitive:
                    column = line.find(needle)
                    span = None if column < 0 else (column, len(query))
                else:
                    span = self._casefold_span(line, needle)
                if span is None:
                    continue
                column, match_length = span
                matches.append(
                    SearchMatch(
                        path=entry.path,
                        line=line_number,
                        column=column + 1,
                        length=match_length,
                        preview=self._search_preview(line, column),
                    )
                )
                if len(matches) >= limit:
                    truncated = True
                    return SearchReport(
                        query,
                        normalized_path,
                        tuple(matches),
                        scanned_files,
                        scanned_bytes,
                        skipped_files,
                        truncated,
                    )
        return SearchReport(
            query,
            normalized_path,
            tuple(matches),
            scanned_files,
            scanned_bytes,
            skipped_files,
            truncated,
        )

    @_locked
    def read_file(self, path: str) -> FileDocument:
        """Read one bounded UTF-8 text file."""

        try:
            candidate, content_bytes = self._read_file_bytes(path, limit=self.max_file_bytes)
            if len(content_bytes) > self.max_file_bytes:
                raise WorkspaceError(
                    "file_too_large",
                    f"Files are limited to {self.max_file_bytes} bytes.",
                    413,
                )
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError(
                "binary_file", "Only UTF-8 text files can be opened in the editor.", 415
            ) from exc
        except OSError as exc:
            raise WorkspaceError("read_failed", "The file could not be read.", 500) from exc
        try:
            modified_at = self._timestamp(candidate.stat())
        except OSError as exc:
            raise WorkspaceError("read_failed", "The file could not be read.", 500) from exc
        return FileDocument(
            path=self.normalize(path, allow_root=False),
            content=content,
            size=len(content_bytes),
            modified_at=modified_at,
            etag=self._etag_bytes(content_bytes),
        )

    @_locked
    def usage_bytes(self) -> int:
        """Return total regular-file bytes without following symlinks."""

        total = 0
        for current_root, directories, files in os.walk(self.root, followlinks=False):
            current = Path(current_root)
            directories[:], _ = self._walk_directories(current, directories)
            for name in files:
                if reserved_name(name):
                    continue
                item = current / name
                try:
                    metadata = item.stat(follow_symlinks=False)
                    if stat.S_ISREG(metadata.st_mode):
                        total += metadata.st_size
                except OSError:
                    continue
        return total

    @_locked
    def write_file(
        self,
        path: str,
        content: str,
        *,
        expected_etag: str | None = None,
        create_only: bool = False,
    ) -> FileDocument:
        """Atomically create or replace a UTF-8 file within configured quotas."""

        try:
            content_bytes = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise WorkspaceError(
                "invalid_content", "File content must be valid UTF-8 text."
            ) from exc
        if len(content_bytes) > self.max_file_bytes:
            raise WorkspaceError(
                "file_too_large",
                f"Files are limited to {self.max_file_bytes} bytes.",
                413,
            )
        candidate = self._safe_path(path, allow_root=False)
        parent = candidate.parent
        self._reject_symlink_parts(parent)
        if not parent.exists() or not parent.is_dir():
            raise WorkspaceError("parent_not_found", "The parent folder does not exist.", 404)

        with self._lock:
            old_size = 0
            existing: bytes | None = None
            if candidate.exists():
                if create_only:
                    raise WorkspaceError(
                        "already_exists", "An entry already exists at that path.", 409
                    )
                if not candidate.is_file():
                    raise WorkspaceError("not_a_file", "The destination is not a file.")
                existing = self.read_file(path).content.encode("utf-8")
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

            if existing == content_bytes:
                return self.read_file(path)

            projected = self.usage_bytes() - old_size + len(content_bytes)
            if projected > self.max_total_bytes:
                raise WorkspaceError(
                    "workspace_quota_exceeded",
                    f"Workspace storage is limited to {self.max_total_bytes} bytes.",
                    413,
                )

            if existing is not None:
                self._history.checkpoint(path, existing)

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
                if existing is None:
                    os.link(temporary_name, candidate)
                    Path(temporary_name).unlink()
                    temporary_name = None
                else:
                    # Check again after checkpoint I/O: never overwrite an intervening disk edit
                    # whose contents have not been preserved in this transaction's snapshot.
                    try:
                        current_etag = self.read_file(path).etag
                    except WorkspaceError as exc:
                        raise WorkspaceError(
                            "edit_conflict",
                            "The file changed while saving; refresh before retrying.",
                            409,
                        ) from exc
                    if current_etag != self._etag_bytes(existing):
                        raise WorkspaceError(
                            "edit_conflict",
                            "The file changed while saving; refresh before retrying.",
                            409,
                        )
                    os.replace(temporary_name, candidate)
            except FileExistsError as exc:
                if temporary_name:
                    Path(temporary_name).unlink(missing_ok=True)
                raise WorkspaceError(
                    "already_exists", "An entry already exists at that path.", 409
                ) from exc
            except (OSError, WorkspaceError) as exc:
                if temporary_name:
                    Path(temporary_name).unlink(missing_ok=True)
                if isinstance(exc, WorkspaceError):
                    raise
                raise WorkspaceError("write_failed", "The file could not be saved.", 500) from exc
        return self.read_file(path)

    @_locked
    def history_report(self, path: str | None = None) -> dict[str, Any]:
        """List retained checkpoints; paths remain the names used at capture time."""
        return self._history.report(path)

    @_locked
    def read_version(self, version_id: str) -> dict[str, Any]:
        """Read and verify a bounded UTF-8 checkpoint without changing the active file."""
        return self._history.read(version_id)

    @_locked
    def restore_version(
        self, version_id: str, destination: str, *, expected_etag: str | None = None
    ) -> FileDocument:
        """Restore to a new path, or replace only the explicitly identified disk version."""
        version = self._history.read(version_id)
        return self.write_file(
            destination,
            version["content"],
            expected_etag=expected_etag,
            create_only=expected_etag is None,
        )

    @_locked
    def purge_version(self, version_id: str) -> None:
        """Permanently remove one checkpoint; public callers must confirm intent."""
        self._history.purge(version_id)

    @_locked
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

    @_locked
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

    @_locked
    def delete(
        self,
        path: str,
        *,
        recursive: bool = False,
        permanent: bool = False,
        expected_etag: str | None = None,
    ) -> dict[str, Any] | None:
        """Move to Trash by default; permanent deletion must be explicitly requested."""

        if not permanent:
            return self._trash.take(path, recursive=recursive, expected_etag=expected_etag)

        candidate = self._lexical(path, allow_root=False)
        self._reject_symlink_parts(candidate, include_leaf=False)
        if candidate.is_symlink():
            candidate.unlink()
            return None
        if os.path.lexists(candidate) and linked_metadata(candidate.lstat()):
            tag = getattr(candidate.lstat(), "st_reparse_tag", None)
            if (
                tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
                and candidate.is_dir()
            ):
                candidate.rmdir()
            else:
                raise WorkspaceError(
                    "reparse_not_allowed", "Remove this unsupported reparse entry outside the app."
                )
            return None
        if (
            candidate.exists()
            and candidate.is_file()
            and candidate.stat(follow_symlinks=False).st_nlink > 1
        ):
            candidate.unlink()
            return None
        candidate = self._safe_path(path, allow_root=False, must_exist=True)
        if expected_etag is not None and self.read_file(path).etag != expected_etag:
            raise WorkspaceError(
                "edit_conflict", "The file changed; reload before deleting it.", 409
            )
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
        return None

    @_locked
    def trash_report(self) -> dict[str, Any]:
        """List bounded recovery metadata, never private storage paths or content."""
        return self._trash.report()

    @_locked
    def restore(self, trash_id: str, destination: str | None = None) -> dict[str, Any]:
        """Restore a recovery item without replacing an existing destination."""
        return self._trash.restore(trash_id, destination)

    @_locked
    def purge(self, trash_id: str) -> None:
        """Permanently remove one explicitly selected recovery item."""
        self._trash.purge(trash_id)

    @_locked
    def summary(self) -> dict[str, Any]:
        """Return safe workspace metadata without exposing the host root path."""

        entries = self.list_entries("", recursive=True)
        return {
            "id": self.workspace_id,
            "name": self.root.name,
            "entries": len(entries),
            "usage_bytes": sum(
                entry.size for entry in entries if entry.kind in {"file", "blocked_hardlink"}
            ),
            "limits": {
                "max_file_bytes": self.max_file_bytes,
                "max_total_bytes": self.max_total_bytes,
                "max_entries": self.max_entries,
            },
        }

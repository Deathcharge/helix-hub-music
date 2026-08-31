"""Bounded, persistent recovery storage; callers hold the workspace lock.

Metadata is file-fsynced before a same-filesystem rename removes the source.
Restore creates destinations exclusively and retains the archive on copy failure.
The store is private to the application, not an OS Recycle Bin implementation.
This handles ordinary failures/restarts, not all filesystem or power-loss scenarios.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from samsarix_workspace.errors import WorkspaceError
from samsarix_workspace.recovery import MAX_METADATA_BYTES as MAX_METADATA_BYTES
from samsarix_workspace.recovery import linked_metadata as linked_metadata
from samsarix_workspace.recovery import plain_directory, read_json, write_json
from samsarix_workspace.recovery import reserved_name as reserved_name

if TYPE_CHECKING:
    from samsarix_workspace.workspace import Workspace

TRASH_NAME = ".samsarix-trash"
OWNER = {"format": "samsarix-workspace-trash", "version": 1}


@dataclass(frozen=True)
class TreeNode:
    path: Path
    relative: Path
    kind: str
    size: int


class TrashStore:
    """App-owned recovery records, addressed only by random opaque IDs."""

    def __init__(
        self, workspace: Workspace, *, max_bytes: int, max_items: int, max_entries: int
    ) -> None:
        if max_bytes < 0 or not 1 <= max_items <= 1000 or not 1 <= max_entries <= 10_000:
            raise ValueError(
                "Trash limits require nonnegative bytes, 1-1000 items, 1-10000 entries"
            )
        self.workspace = workspace
        self.root = workspace.root / TRASH_NAME
        self.max_bytes = max_bytes
        self.max_items = max_items
        self.max_entries = max_entries
        if os.path.lexists(self.root):
            self._validate_store()

    _plain_directory = staticmethod(plain_directory)
    _read_json = staticmethod(read_json)
    _write_json = staticmethod(write_json)

    def _validate_store(self) -> None:
        try:
            self._plain_directory(self.root)
            if self._read_json(self.root / "owner.json") != OWNER:
                raise ValueError("Unrecognized store")
        except (OSError, ValueError, RecursionError) as exc:
            raise WorkspaceError(
                "trash_unavailable",
                "The reserved .samsarix-trash folder is not a readable Samsarix Trash store. "
                "Inspect or rename it outside the app; existing files were not changed.",
                409,
            ) from exc

    def _ensure_store(self) -> None:
        if not os.path.lexists(self.root):
            try:
                self.root.mkdir(mode=0o700)
            except FileExistsError:
                pass
            else:
                try:
                    self._write_json(self.root / "owner.json", OWNER)
                except OSError:
                    # No archive has been created yet. Never recursively clean this directory.
                    (self.root / "owner.json").unlink(missing_ok=True)
                    self.root.rmdir()
                    raise
        self._validate_store()

    def _record(self, trash_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", trash_id):
            raise WorkspaceError("invalid_trash_id", "The Trash item ID is invalid.")
        if not os.path.lexists(self.root):
            raise WorkspaceError("not_found", "The Trash item does not exist.", 404)
        self._validate_store()
        record = self.root / trash_id
        try:
            self._plain_directory(record)
        except FileNotFoundError as exc:
            raise WorkspaceError("not_found", "The Trash item does not exist.", 404) from exc
        except (OSError, ValueError) as exc:
            raise WorkspaceError(
                "trash_unavailable", "The Trash item is unavailable.", 409
            ) from exc
        return record

    def _metadata(self, record: Path) -> dict[str, Any]:
        try:
            info = self._read_json(record / "info.json")
            if set(info) != {"version", "path", "kind", "deleted_at"}:
                raise ValueError("Invalid fields")
            if type(info["version"]) is not int or info["version"] != 1:
                raise ValueError("Unknown format")
            if not isinstance(info["path"], str) or len(info["path"]) > 512:
                raise ValueError("Invalid path")
            self.workspace.normalize(info["path"], allow_root=False)
            if info["kind"] not in {"file", "directory"}:
                raise ValueError("Invalid kind")
            if not isinstance(info["deleted_at"], str):
                raise ValueError("Invalid date")
            stamp = datetime.fromisoformat(info["deleted_at"])
            if stamp.tzinfo is None:
                raise ValueError("Date needs a timezone")
            return info
        except (OSError, ValueError, TypeError, RecursionError, WorkspaceError) as exc:
            raise WorkspaceError(
                "trash_unavailable",
                "Recovery metadata is invalid; this item cannot be restored.",
                409,
            ) from exc

    def _tree(self, root: Path, budget: int | None = None) -> tuple[list[TreeNode], int]:
        limit = self.max_entries if budget is None else min(self.max_entries, budget)
        if limit < 1:
            raise WorkspaceError("trash_entry_limit", "The recovery entry limit was exceeded.", 413)
        nodes: list[TreeNode] = []
        total = 0
        pending = [root]
        while pending:
            path = pending.pop()
            metadata = path.lstat()
            if linked_metadata(metadata) or (
                stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1
            ):
                raise WorkspaceError(
                    "recovery_unsupported", "Trash does not follow or retain links.", 409
                )
            if stat.S_ISDIR(metadata.st_mode):
                kind = "directory"
                # Bound enumeration before allocating or sorting a potentially huge directory.
                children: list[Path] = []
                with os.scandir(path) as directory:
                    for child in directory:
                        if reserved_name(child.name):
                            raise WorkspaceError(
                                "reserved_path", "Nested recovery stores cannot be moved to Trash."
                            )
                        children.append(Path(child.path))
                        if len(nodes) + len(pending) + len(children) + 1 > limit:
                            raise WorkspaceError(
                                "trash_entry_limit",
                                "This recovery tree exceeds the entry limit.",
                                413,
                            )
                pending.extend(sorted(children, reverse=True))
                size = 0
            elif stat.S_ISREG(metadata.st_mode):
                kind = "file"
                size = metadata.st_size
            else:
                raise WorkspaceError(
                    "recovery_unsupported", "Trash supports regular files and folders only.", 409
                )
            nodes.append(TreeNode(path, path.relative_to(root), kind, size))
            total += size
            if len(nodes) > limit:
                raise WorkspaceError(
                    "trash_entry_limit", "The recovery entry limit was exceeded.", 413
                )
        return nodes, total

    def _item(self, record: Path, budget: int | None = None) -> dict[str, Any]:
        info = self._metadata(record)
        payload = record / "payload"
        if not os.path.lexists(payload):
            return {
                **info,
                "id": record.name,
                "bytes": 0,
                "entries": 0,
                "state": "incomplete",
                "message": "No archived content; the interrupted operation did not finish.",
            }
        nodes, size = self._tree(payload, budget)
        if nodes[0].kind != info["kind"]:
            raise WorkspaceError(
                "trash_unavailable", "Archived content has an unexpected type.", 409
            )
        return {**info, "id": record.name, "bytes": size, "entries": len(nodes), "state": "ready"}

    def report(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        remaining_entries = self.max_entries
        if os.path.lexists(self.root):
            self._validate_store()
            with os.scandir(self.root) as directory:
                for entry in directory:
                    if entry.name == "owner.json":
                        continue
                    if len(items) >= self.max_items:
                        raise WorkspaceError(
                            "trash_item_limit", "Trash exceeds its item limit.", 413
                        )
                    record = self._record(entry.name)
                    try:
                        item = self._item(record, remaining_entries)
                        remaining_entries -= item["entries"]
                    except (OSError, WorkspaceError):
                        item = {
                            "id": entry.name,
                            "path": None,
                            "kind": "unknown",
                            "deleted_at": None,
                            "bytes": 0,
                            "entries": 0,
                            "state": "unavailable",
                            "message": "This item needs inspection; restore is unavailable.",
                        }
                    items.append(item)
        return {
            "items": sorted(
                items, key=lambda item: (item["deleted_at"] or "", item["id"]), reverse=True
            ),
            "usage_bytes": sum(item["bytes"] for item in items),
            "entries": sum(item["entries"] for item in items),
            "unavailable_items": sum(item["state"] == "unavailable" for item in items),
            "limits": {
                "max_bytes": self.max_bytes,
                "max_items": self.max_items,
                "max_entries": self.max_entries,
            },
        }

    def take(
        self, path: str, *, recursive: bool = False, expected_etag: str | None = None
    ) -> dict[str, Any]:
        public = self.workspace.normalize(path, allow_root=False)
        if len(public) > 512:
            raise WorkspaceError("invalid_path", "Recovery paths are limited to 512 characters.")
        candidate = self.workspace._safe_path(public, allow_root=False, must_exist=True)
        try:
            nodes, size = self._tree(candidate)
            kind = nodes[0].kind
            if kind == "directory" and len(nodes) > 1 and not recursive:
                raise WorkspaceError(
                    "directory_not_empty", "Confirm moving the folder tree to Trash.", 409
                )
            if expected_etag is not None and (
                kind != "file" or self.workspace.read_file(public).etag != expected_etag
            ):
                raise WorkspaceError(
                    "edit_conflict", "The file changed; reload before deleting it.", 409
                )
            report = self.report()
            if report["unavailable_items"]:
                raise WorkspaceError(
                    "trash_unavailable",
                    "Inspect unreadable Trash items before deleting more files.",
                    409,
                )
            if (
                len(report["items"]) >= self.max_items
                or report["usage_bytes"] + size > self.max_bytes
                or report["entries"] + len(nodes) > self.max_entries
            ):
                raise WorkspaceError(
                    "trash_full", "Trash is full. Restore or permanently delete an item first.", 413
                )
            self._ensure_store()
            record = self.root / secrets.token_hex(16)
            record.mkdir(mode=0o700)
            info = {
                "version": 1,
                "path": public,
                "kind": kind,
                "deleted_at": datetime.now(UTC).isoformat(),
            }
            try:
                self._write_json(record / "info.json", info)
                # Same-filesystem rename, never shutil.move's copy-and-delete fallback.
                candidate.rename(record / "payload")
            except OSError:
                # A failed rename leaves the active source intact. Only remove our empty record.
                if not os.path.lexists(record / "payload"):
                    (record / "info.json").unlink(missing_ok=True)
                    record.rmdir()
                raise
            return {
                **info,
                "id": record.name,
                "bytes": size,
                "entries": len(nodes),
                "state": "ready",
            }
        except OSError as exc:
            raise WorkspaceError(
                "trash_failed",
                "The entry could not be moved to Trash; no permanent deletion was attempted.",
                500,
            ) from exc

    @staticmethod
    def _copy_file(node: TreeNode, destination: Path) -> None:
        descriptor = os.open(node.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise WorkspaceError(
                    "trash_changed", "Archived content changed during restore.", 409
                )
            with destination.open("xb") as target:
                remaining = node.size
                while chunk := source.read(min(65536, remaining + 1)):
                    if len(chunk) > remaining:
                        raise WorkspaceError(
                            "trash_changed", "Archived content grew during restore.", 409
                        )
                    target.write(chunk)
                    remaining -= len(chunk)
                if remaining:
                    raise WorkspaceError(
                        "trash_changed", "Archived content shrank during restore.", 409
                    )
                target.flush()
                os.fsync(target.fileno())
        shutil.copystat(node.path, destination, follow_symlinks=False)

    def restore(self, trash_id: str, destination: str | None = None) -> dict[str, Any]:
        record = self._record(trash_id)
        info = self._metadata(record)
        payload = record / "payload"
        try:
            nodes, size = self._tree(payload)
        except OSError as exc:
            raise WorkspaceError(
                "trash_unavailable", "Archived content is unavailable.", 409
            ) from exc
        if nodes[0].kind != info["kind"]:
            raise WorkspaceError(
                "trash_unavailable", "Archived content has an unexpected type.", 409
            )
        public = self.workspace.normalize(
            info["path"] if destination is None else destination, allow_root=False
        )
        target = self.workspace._safe_path(public, allow_root=False)
        self.workspace.assert_directory(target.parent.relative_to(self.workspace.root).as_posix())
        if os.path.lexists(target):
            raise WorkspaceError(
                "already_exists", "The restore path already exists. Choose another path.", 409
            )
        if self.workspace.usage_bytes() + size > self.workspace.max_total_bytes:
            raise WorkspaceError(
                "workspace_quota_exceeded", "Restore would exceed workspace storage.", 413
            )
        if (
            len(self.workspace.list_entries(recursive=True)) + len(nodes)
            > self.workspace.max_entries
        ):
            raise WorkspaceError(
                "entry_limit_exceeded", "Restore would exceed the workspace entry limit.", 413
            )
        claimed_directory = False
        try:
            for node in nodes:
                output = target / node.relative
                if node.kind == "directory":
                    output.mkdir()
                    claimed_directory = True
                else:
                    self._copy_file(node, output)
            for node in reversed(nodes):
                if node.kind == "directory":
                    shutil.copystat(node.path, target / node.relative, follow_symlinks=False)
        except FileExistsError as exc:
            if not claimed_directory:
                raise WorkspaceError(
                    "already_exists", "The restore path already exists. Choose another path.", 409
                ) from exc
            raise WorkspaceError(
                "restore_failed",
                "Restore stopped at a conflicting entry. Trash is retained; "
                "inspect the partial destination or choose another path.",
                409,
            ) from exc
        except (OSError, WorkspaceError) as exc:
            raise WorkspaceError(
                "restore_failed",
                "Restore did not finish. Trash is retained; a partial destination may exist. "
                "Inspect it or choose another path.",
                500,
            ) from exc
        retained = False
        try:
            self.purge(trash_id)
        except WorkspaceError:
            retained = True
        return {"entry": self.workspace._entry(target).to_dict(), "trash_retained": retained}

    def purge(self, trash_id: str) -> None:
        record = self._record(trash_id)
        try:
            # The record root was validated; rmtree unlinks nested links, not their targets.
            shutil.rmtree(record)
        except OSError as exc:
            raise WorkspaceError(
                "purge_failed",
                "Permanent deletion did not finish. Refresh Trash before retrying.",
                500,
            ) from exc

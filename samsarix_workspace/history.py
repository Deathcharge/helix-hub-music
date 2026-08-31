"""Bounded, path-addressed snapshots made before application overwrites.

Callers hold the Workspace lock. Snapshots are flushed before active writes.
Retention applies on checkpoint creation, including a later failed active write.
This is local recovery, not Git, an external-change watcher, or a backup system.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from samsarix_workspace.errors import WorkspaceError
from samsarix_workspace.recovery import (
    linked_metadata,
    plain_directory,
    read_json,
    read_regular,
    write_json,
)

if TYPE_CHECKING:
    from samsarix_workspace.workspace import Workspace

HISTORY_NAME = ".samsarix-history"
OWNER = {"format": "samsarix-workspace-history", "version": 1}
MAX_RECORDS = 1001  # At most one staged checkpoint above the configured item cap.


class HistoryStore:
    """Immutable snapshots with independent byte, item and per-path retention."""

    def __init__(
        self, workspace: Workspace, *, max_bytes: int, max_items: int, max_per_file: int
    ) -> None:
        if not 1 <= max_bytes <= 1_073_741_824 or not 1 <= max_items <= 1000:
            raise ValueError("History requires 1-1073741824 bytes and 1-1000 items")
        if not 1 <= max_per_file <= max_items:
            raise ValueError("History per-file limit must be between 1 and its item limit")
        self.workspace = workspace
        self.root = workspace.root / HISTORY_NAME
        self.max_bytes = max_bytes
        self.max_items = max_items
        self.max_per_file = max_per_file
        if os.path.lexists(self.root):
            self._validate_store()

    def _validate_store(self) -> None:
        try:
            plain_directory(self.root)
            if read_json(self.root / "owner.json") != OWNER:
                raise ValueError("Unknown store")
        except (OSError, ValueError, RecursionError) as exc:
            raise WorkspaceError(
                "history_unavailable",
                "The reserved .samsarix-history folder is not a readable Samsarix store. "
                "Inspect it outside the app; existing files were not changed.",
                409,
            ) from exc

    def _ensure_store(self) -> None:
        if not os.path.lexists(self.root):
            try:
                self.root.mkdir(mode=0o700)
            except FileExistsError:
                pass
            else:
                # An interrupted initialization is left for explicit inspection, never adopted.
                write_json(self.root / "owner.json", OWNER)
        self._validate_store()

    def _record(self, version_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", version_id):
            raise WorkspaceError("invalid_version_id", "The history version ID is invalid.")
        if not os.path.lexists(self.root):
            raise WorkspaceError("not_found", "The saved version does not exist.", 404)
        self._validate_store()
        record = self.root / version_id
        try:
            plain_directory(record)
        except FileNotFoundError as exc:
            raise WorkspaceError("not_found", "The saved version does not exist.", 404) from exc
        except (OSError, ValueError) as exc:
            raise WorkspaceError(
                "history_unavailable", "The saved version is unavailable.", 409
            ) from exc
        return record

    def _item(self, record: Path) -> dict[str, Any]:
        info = read_json(record / "info.json")
        if set(info) != {"version", "path", "saved_at", "size", "etag", "sequence"}:
            raise ValueError("Invalid metadata fields")
        if type(info["version"]) is not int or info["version"] != 1:
            raise ValueError("Unknown format")
        if not isinstance(info["path"], str) or len(info["path"]) > 512:
            raise ValueError("Invalid path")
        self.workspace.normalize(info["path"], allow_root=False)
        if not isinstance(info["saved_at"], str):
            raise ValueError("Invalid date")
        if datetime.fromisoformat(info["saved_at"]).tzinfo is None:
            raise ValueError("Missing timezone")
        if type(info["size"]) is not int or not 0 <= info["size"] <= self.workspace.max_file_bytes:
            raise ValueError("Invalid size")
        if type(info["sequence"]) is not int or not 1 <= info["sequence"] < 2**53:
            raise ValueError("Invalid sequence")
        if not isinstance(info["etag"], str) or not re.fullmatch(r"[0-9a-f]{64}", info["etag"]):
            raise ValueError("Invalid content digest")
        payload = (record / "content").lstat()
        if (
            linked_metadata(payload)
            or not stat.S_ISREG(payload.st_mode)
            or payload.st_nlink != 1
            or payload.st_size != info["size"]
        ):
            raise ValueError("Invalid content file")
        return {**info, "id": record.name, "state": "ready"}

    @staticmethod
    def _path_key(path: str) -> str:
        return path.casefold() if os.name == "nt" else path

    def report(self, path: str | None = None) -> dict[str, Any]:
        public = self.workspace.normalize(path, allow_root=False) if path is not None else None
        items: list[dict[str, Any]] = []
        if os.path.lexists(self.root):
            self._validate_store()
            try:
                with os.scandir(self.root) as entries:
                    for entry in entries:
                        if entry.name == "owner.json":
                            continue
                        if len(items) >= MAX_RECORDS:
                            raise WorkspaceError(
                                "history_item_limit",
                                "Inspect excess history records outside the app.",
                                413,
                            )
                        record = self._record(entry.name)
                        try:
                            item = self._item(record)
                        except (OSError, ValueError, TypeError, RecursionError, WorkspaceError):
                            item = {
                                "id": entry.name,
                                "path": None,
                                "saved_at": None,
                                "size": 0,
                                "etag": None,
                                "sequence": 0,
                                "state": "unavailable",
                            }
                        items.append(item)
            except OSError as exc:
                raise WorkspaceError(
                    "history_unavailable", "History could not be listed.", 409
                ) from exc
        selected = [
            item
            for item in items
            if public is None
            or item["path"] is None
            or self._path_key(item["path"]) == self._path_key(public)
        ]
        return {
            "path": public,
            "items": sorted(
                selected, key=lambda item: (item["sequence"], item["id"]), reverse=True
            ),
            "usage_bytes": sum(item["size"] for item in items),
            "total_items": len(items),
            "unavailable_items": sum(item["state"] == "unavailable" for item in items),
            "limits": {
                "max_bytes": self.max_bytes,
                "max_items": self.max_items,
                "max_per_file": self.max_per_file,
            },
        }

    def read(self, version_id: str) -> dict[str, Any]:
        record = self._record(version_id)
        try:
            item = self._item(record)
            content = read_regular(record / "content", self.workspace.max_file_bytes)
            if len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["etag"]:
                raise ValueError("Content does not match its digest")
            return {**item, "content": content.decode("utf-8")}
        except (OSError, ValueError, TypeError, RecursionError, WorkspaceError) as exc:
            raise WorkspaceError(
                "history_unavailable",
                "This saved version cannot be read; inspect or remove it.",
                409,
            ) from exc

    def purge(self, version_id: str) -> None:
        record = self._record(version_id)
        try:
            shutil.rmtree(record)
        except OSError as exc:
            raise WorkspaceError(
                "history_purge_failed", "The saved version could not be removed.", 500
            ) from exc

    def _prune(self, items: list[dict[str, Any]]) -> None:
        retained: list[dict[str, Any]] = []
        discarded: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        for item in sorted(items, key=lambda item: (item["sequence"], item["id"]), reverse=True):
            key = self._path_key(item["path"])
            if counts.get(key, 0) >= self.max_per_file:
                discarded.append(item)
            else:
                retained.append(item)
                counts[key] = counts.get(key, 0) + 1
        size = sum(item["size"] for item in retained)
        while len(retained) > self.max_items or size > self.max_bytes:
            item = retained.pop()
            size -= item["size"]
            discarded.append(item)
        for item in discarded:
            self.purge(item["id"])

    def checkpoint(self, path: str, content: bytes) -> None:
        public = self.workspace.normalize(path, allow_root=False)
        if len(public) > 512:
            raise WorkspaceError("invalid_path", "History paths are limited to 512 characters.")
        if len(content) > min(self.max_bytes, self.workspace.max_file_bytes):
            raise WorkspaceError(
                "history_quota_exceeded",
                "The prior file cannot fit in history; it was not overwritten.",
                413,
            )
        report = self.report()
        if (
            report["unavailable_items"]
            or report["total_items"] > self.max_items
            or report["usage_bytes"] > self.max_bytes
        ):
            raise WorkspaceError(
                "history_unavailable",
                "Inspect or remove unavailable/excess history before saving; "
                "the file was not overwritten.",
                409,
            )
        etag = hashlib.sha256(content).hexdigest()
        previous = next(
            (
                item
                for item in report["items"]
                if self._path_key(item["path"]) == self._path_key(public)
            ),
            None,
        )
        if previous is not None and previous["etag"] == etag:
            self.read(previous["id"])  # Do not trust a matching digest without checking the bytes.
            self._prune(report["items"])
            return
        info = {
            "version": 1,
            "path": public,
            "saved_at": datetime.now(UTC).isoformat(),
            "size": len(content),
            "etag": etag,
            "sequence": max((item["sequence"] for item in report["items"]), default=0) + 1,
        }
        record: Path | None = None
        try:
            self._ensure_store()
            record = self.root / secrets.token_hex(16)
            record.mkdir(mode=0o700)
            descriptor = os.open(record / "content", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as snapshot:
                snapshot.write(content)
                snapshot.flush()
                os.fsync(snapshot.fileno())
            write_json(record / "info.json", info)
        except (OSError, WorkspaceError) as exc:
            # Incomplete records remain visible and block further checkpoints, bounding retries.
            raise WorkspaceError(
                "history_write_failed",
                "A recovery checkpoint could not be saved; the file was not overwritten.",
                500,
            ) from exc
        self._prune([*report["items"], {**info, "id": record.name}])

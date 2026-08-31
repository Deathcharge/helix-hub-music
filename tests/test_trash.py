"""Recovery durability, quotas, collision handling, and private-store boundaries."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from samsarix_workspace.shell import VirtualShell
from samsarix_workspace.trash import MAX_METADATA_BYTES, TRASH_NAME, TrashStore
from samsarix_workspace.workspace import Workspace, WorkspaceError


def code(value: str) -> pytest.RaisesExc[WorkspaceError]:
    return pytest.raises(WorkspaceError, check=lambda error: error.code == value)


def archived(workspace: Workspace, path: str = "note.txt", text: str = "keep this") -> dict:
    workspace.write_file(path, text)
    item = workspace.delete(path)
    assert item is not None
    return item


def test_file_recovery_persists_across_restart_and_is_private(workspace: Workspace) -> None:
    item = archived(workspace)
    assert not (workspace.root / "note.txt").exists()
    assert workspace.list_entries(recursive=True) == []
    assert workspace.search_text("keep").matches == ()
    assert workspace.usage_bytes() == 0
    assert workspace.summary()["entries"] == 0
    assert VirtualShell(workspace).execute("ls -a").output == ""
    restarted = Workspace(workspace.root)
    report = restarted.trash_report()
    assert report["items"][0]["id"] == item["id"]
    assert report["usage_bytes"] == 9
    restored = restarted.restore(item["id"])
    assert restored["entry"]["path"] == "note.txt"
    assert not restored["trash_retained"]
    assert restarted.read_file("note.txt").content == "keep this"
    assert restarted.trash_report()["items"] == []


def test_folder_recovery_preserves_binary_data_empty_dirs_and_modified_time(
    workspace: Workspace,
) -> None:
    workspace.make_directory("bundle")
    workspace.make_directory("bundle/empty")
    binary = workspace.root / "bundle" / "binary.dat"
    binary.write_bytes(b"\xff\x00\xfe" * 100)
    os.utime(binary, (1_700_000_000, 1_700_000_001))
    with code("directory_not_empty"):
        workspace.delete("bundle")
    item = workspace.delete("bundle", recursive=True)
    assert item and item["entries"] == 3 and item["bytes"] == 300
    workspace.restore(item["id"])
    assert binary.read_bytes() == b"\xff\x00\xfe" * 100
    assert binary.stat().st_mtime == 1_700_000_001
    assert (workspace.root / "bundle" / "empty").is_dir()


def test_restore_collision_and_alternate_path_never_overwrite(workspace: Workspace) -> None:
    item = archived(workspace)
    workspace.write_file("note.txt", "new live content")
    with code("already_exists"):
        workspace.restore(item["id"])
    assert workspace.read_file("note.txt").content == "new live content"
    assert workspace.trash_report()["items"][0]["id"] == item["id"]
    with code("not_found"):
        workspace.restore(item["id"], "missing/restore.txt")
    workspace.restore(item["id"], "recovered.txt")
    assert workspace.read_file("recovered.txt").content == "keep this"
    assert workspace.read_file("note.txt").content == "new live content"


@pytest.mark.parametrize(
    "path",
    [
        TRASH_NAME,
        f"{TRASH_NAME}/owner.json",
        f"folder/{TRASH_NAME}/x",
        ".SAMSARIX-TRASH. /payload",
        f"{TRASH_NAME}:stream",
    ],
)
def test_private_names_and_windows_aliases_are_rejected(workspace: Workspace, path: str) -> None:
    archived(workspace)
    for operation in [
        workspace.read_file,
        workspace.list_entries,
        workspace.delete,
        workspace.make_directory,
    ]:
        with code("reserved_path"):
            operation(path)
    with code("reserved_path"):
        workspace.write_file(path, "no")
    with code("reserved_path"):
        workspace.delete(path, permanent=True)
    assert (workspace.root / TRASH_NAME / "owner.json").exists()


@pytest.mark.parametrize(
    "trash_id", ["..", "../elsewhere", "A" * 32, "0" * 31, "x" * 32, "/absolute"]
)
def test_recovery_ids_cannot_be_paths(workspace: Workspace, trash_id: str) -> None:
    for operation in [workspace.restore, workspace.purge]:
        with code("invalid_trash_id"):
            operation(trash_id)
    with code("not_found"):
        workspace.restore("0" * 32)


@pytest.mark.parametrize(
    "destination,expected",
    [("", "root_not_allowed"), ("../outside", "invalid_path"), (TRASH_NAME, "reserved_path")],
)
def test_restore_destination_validation(
    workspace: Workspace, destination: str, expected: str
) -> None:
    item = archived(workspace)
    with code(expected):
        workspace.restore(item["id"], destination)
    assert workspace.trash_report()["items"]


def test_trash_limits_refuse_deletion_without_eviction(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "root", max_trash_bytes=3, max_trash_items=1)
    first = archived(workspace, "first.txt", "one")
    workspace.write_file("second.txt", "two")
    with code("trash_full"):
        workspace.delete("second.txt")
    assert workspace.read_file("second.txt").content == "two"
    assert workspace.trash_report()["items"][0]["id"] == first["id"]
    workspace.purge(first["id"])
    assert workspace.delete("second.txt")
    with code("not_found"):
        workspace.purge(first["id"])


def test_byte_and_entry_budgets(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "root", max_trash_bytes=2, max_trash_entries=2)
    workspace.write_file("too-big.txt", "123")
    with code("trash_full"):
        workspace.delete("too-big.txt")
    workspace.make_directory("folder")
    workspace.write_file("folder/a", "")
    workspace.write_file("folder/b", "")
    with code("trash_entry_limit"):
        workspace.delete("folder", recursive=True)
    assert (workspace.root / "folder" / "b").exists()
    assert workspace.trash_report()["items"] == []


def test_restore_respects_active_storage_and_entry_quotas(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "root", max_total_bytes=10, max_entries=1)
    item = archived(workspace, text="123456")
    workspace.write_file("other.txt", "12345")
    with code("workspace_quota_exceeded"):
        workspace.restore(item["id"])
    workspace.write_file("other.txt", "1")
    with code("entry_limit_exceeded"):
        workspace.restore(item["id"])
    assert workspace.trash_report()["items"]


def test_delete_checks_editor_etag_and_permanent_delete_is_explicit(workspace: Workspace) -> None:
    initial = workspace.write_file("file", "initial")
    workspace.write_file("file", "changed")
    with code("edit_conflict"):
        workspace.delete("file", expected_etag=initial.etag)
    with code("edit_conflict"):
        workspace.delete("file", permanent=True, expected_etag=initial.etag)
    assert workspace.trash_report()["items"] == []
    assert workspace.delete("file", permanent=True) is None
    assert not (workspace.root / "file").exists()
    assert workspace.trash_report()["items"] == []


def test_failed_move_retains_source_and_cleans_empty_record(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace.write_file("note", "safe")

    def fail(_source: Path, _target: Path) -> None:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(Path, "rename", fail)
    with code("trash_failed"):
        workspace.delete("note")
    assert workspace.read_file("note").content == "safe"
    assert workspace.trash_report()["items"] == []


def test_error_after_move_retains_recoverable_metadata(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace.write_file("note", "safe")
    original = Path.rename

    def fail_after(source: Path, target: Path) -> None:
        original(source, target)
        raise OSError("simulated acknowledgement failure")

    monkeypatch.setattr(Path, "rename", fail_after)
    with code("trash_failed"):
        workspace.delete("note")
    restarted = Workspace(workspace.root)
    item = restarted.trash_report()["items"][0]
    assert item["state"] == "ready"
    restarted.restore(item["id"])
    assert restarted.read_file("note").content == "safe"


def test_failed_restore_retains_archive_and_partial_destination(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = archived(workspace)

    def fail(_node: object, destination: Path) -> None:
        destination.write_bytes(b"partial")
        raise OSError("simulated disk full")

    monkeypatch.setattr(TrashStore, "_copy_file", staticmethod(fail))
    with code("restore_failed"):
        workspace.restore(item["id"])
    assert workspace.read_file("note.txt").content == "partial"
    assert workspace.trash_report()["items"][0]["state"] == "ready"
    assert (workspace.root / TRASH_NAME / item["id"] / "payload").read_text() == "keep this"


def test_racing_restore_destination_is_not_overwritten(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = archived(workspace)
    original = TrashStore._copy_file

    def race(node: object, destination: Path) -> None:
        destination.write_text("racing writer")
        original(node, destination)

    monkeypatch.setattr(TrashStore, "_copy_file", staticmethod(race))
    with code("already_exists"):
        workspace.restore(item["id"])
    assert workspace.read_file("note.txt").content == "racing writer"
    assert workspace.trash_report()["items"]


def test_purge_failure_is_visible_and_restore_reports_retained_copy(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = archived(workspace)

    def fail(_path: Path) -> None:
        raise OSError("simulated permission failure")

    monkeypatch.setattr(shutil, "rmtree", fail)
    with code("purge_failed"):
        workspace.purge(item["id"])
    result = workspace.restore(item["id"])
    assert result["trash_retained"] is True
    assert workspace.read_file("note.txt").content == "keep this"


def test_corrupt_metadata_is_not_executed_and_can_be_purged(workspace: Workspace) -> None:
    item = archived(workspace)
    record = workspace.root / TRASH_NAME / item["id"]
    info = json.loads((record / "info.json").read_text())
    info["path"] = "../outside.txt"
    (record / "info.json").write_text(json.dumps(info))
    report = workspace.trash_report()
    assert report["unavailable_items"] == 1
    assert report["items"][0]["path"] is None
    with code("trash_unavailable"):
        workspace.restore(item["id"])
    workspace.write_file("live", "retained")
    with code("trash_unavailable"):
        workspace.delete("live")
    workspace.purge(item["id"])
    assert workspace.trash_report()["items"] == []


def test_incomplete_record_is_visible_after_restart(workspace: Workspace) -> None:
    item = archived(workspace)
    record = workspace.root / TRASH_NAME / item["id"]
    (record / "payload").rename(workspace.root / "note.txt")
    restarted = Workspace(workspace.root)
    assert restarted.trash_report()["items"][0]["state"] == "incomplete"
    with code("trash_unavailable"):
        restarted.restore(item["id"])
    restarted.purge(item["id"])
    assert restarted.read_file("note.txt").content == "keep this"


def test_unowned_store_collision_preserves_existing_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    collision = root / TRASH_NAME
    collision.mkdir(parents=True)
    (collision / "mine.txt").write_text("not app data")
    with code("trash_unavailable"):
        Workspace(root)
    assert (collision / "mine.txt").read_text() == "not app data"


def test_links_in_source_or_archive_are_never_followed(
    workspace: Workspace, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    workspace.make_directory("folder")
    link = workspace.root / "folder" / "linked"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation unavailable")
    with code("recovery_unsupported"):
        workspace.delete("folder", recursive=True)
    assert link.is_symlink()
    workspace.delete("folder/linked", permanent=True)
    item = archived(workspace)
    payload = workspace.root / TRASH_NAME / item["id"] / "payload"
    payload.unlink()
    payload.symlink_to(outside)
    assert workspace.trash_report()["items"][0]["state"] == "unavailable"
    with code("recovery_unsupported"):
        workspace.restore(item["id"])
    workspace.purge(item["id"])
    assert outside.read_text() == "outside"


def test_virtual_shell_recovery_and_explicit_purge(workspace: Workspace) -> None:
    shell = VirtualShell(workspace)
    assert shell.execute("trash").output == "Trash is empty."
    item = archived(workspace)
    assert item["id"] in shell.execute("trash").output
    assert shell.execute(f"restore {item['id']} copy.txt").exit_code == 0
    assert workspace.read_file("copy.txt").content == "keep this"
    assert shell.execute("rm --permanent copy.txt").exit_code == 0
    item = archived(workspace)
    assert shell.execute(f"purge {item['id']}").exit_code == 1
    assert shell.execute(f"purge {item['id']} --confirm").exit_code == 0
    assert shell.execute("restore").exit_code == 1
    assert shell.execute("trash extra").exit_code == 1


def test_nested_recovery_store_is_not_archived(workspace: Workspace) -> None:
    workspace.make_directory("nested")
    (workspace.root / "nested" / TRASH_NAME).mkdir()
    with code("reserved_path"):
        workspace.delete("nested", recursive=True)
    assert workspace.list_entries("nested", recursive=True) == []


@pytest.mark.parametrize(
    "setting,value", [("max_trash_bytes", -1), ("max_trash_items", 0), ("max_trash_entries", 0)]
)
def test_invalid_trash_limits_rejected(tmp_path: Path, setting: str, value: int) -> None:
    with pytest.raises(ValueError, match="Trash limits"):
        Workspace(tmp_path / "root", **{setting: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("extra", True),
        ("version", True),
        ("path", 123),
        ("path", "x" * 513),
        ("kind", "link"),
        ("kind", []),
        ("deleted_at", 123),
        ("deleted_at", "2026-01-01T00:00:00"),
        ("deleted_at", "invalid"),
    ],
)
def test_invalid_metadata_fields_are_unavailable(
    workspace: Workspace, field: str, value: object
) -> None:
    item = archived(workspace)
    document = workspace.root / TRASH_NAME / item["id"] / "info.json"
    info = json.loads(document.read_text())
    info[field] = value
    document.write_text(json.dumps(info))
    assert workspace.trash_report()["items"][0]["state"] == "unavailable"
    with code("trash_unavailable"):
        workspace.restore(item["id"])


@pytest.mark.parametrize("content", [b"[]", b"not-json", b"x" * (MAX_METADATA_BYTES + 1)])
def test_invalid_metadata_documents_fail_closed(workspace: Workspace, content: bytes) -> None:
    item = archived(workspace)
    (workspace.root / TRASH_NAME / item["id"] / "info.json").write_bytes(content)
    assert workspace.trash_report()["unavailable_items"] == 1


def test_changed_archive_type_and_reduced_limits_fail_closed(workspace: Workspace) -> None:
    item = archived(workspace)
    payload = workspace.root / TRASH_NAME / item["id"] / "payload"
    payload.unlink()
    payload.mkdir()
    assert workspace.trash_report()["unavailable_items"] == 1
    with code("trash_unavailable"):
        workspace.restore(item["id"])
    workspace.purge(item["id"])
    first = archived(workspace, "first")
    archived(workspace, "second")
    narrowed = Workspace(workspace.root, max_trash_entries=1)
    assert narrowed.trash_report()["unavailable_items"] == 1
    narrowed = Workspace(workspace.root, max_trash_items=1)
    with code("trash_item_limit"):
        narrowed.trash_report()
    narrowed.purge(first["id"])
    assert len(narrowed.trash_report()["items"]) == 1


@pytest.mark.parametrize("replacement", ["", "content grew"])
def test_archive_resize_during_copy_retains_source(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    item = archived(workspace, text="small")
    original = TrashStore._copy_file

    def resize(node: object, destination: Path) -> None:
        node.path.write_text(replacement)
        original(node, destination)

    monkeypatch.setattr(TrashStore, "_copy_file", staticmethod(resize))
    with code("restore_failed"):
        workspace.restore(item["id"])
    assert workspace.trash_report()["items"][0]["state"] == "ready"


def test_racing_child_does_not_overwrite_or_destroy_folder_archive(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace.make_directory("folder")
    workspace.write_file("folder/child", "original")
    item = workspace.delete("folder", recursive=True)
    original = TrashStore._copy_file

    def race(node: object, destination: Path) -> None:
        destination.write_text("other writer")
        original(node, destination)

    monkeypatch.setattr(TrashStore, "_copy_file", staticmethod(race))
    with code("restore_failed"):
        workspace.restore(item["id"])
    assert workspace.read_file("folder/child").content == "other writer"
    assert workspace.trash_report()["items"][0]["state"] == "ready"


def test_failed_owner_write_cleans_only_new_store(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace.write_file("note", "keep")

    def fail(_path: Path, _value: dict) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(TrashStore, "_write_json", staticmethod(fail))
    with code("trash_failed"):
        workspace.delete("note")
    assert not (workspace.root / TRASH_NAME).exists()
    assert workspace.read_file("note").content == "keep"


def test_hardlinked_metadata_and_archive_are_not_read(workspace: Workspace) -> None:
    item = archived(workspace)
    record = workspace.root / TRASH_NAME / item["id"]
    os.link(record / "info.json", workspace.root / "info-copy")
    with code("trash_unavailable"):
        workspace.restore(item["id"])
    (workspace.root / "info-copy").unlink()
    os.link(record / "payload", workspace.root / "payload-copy")
    with code("recovery_unsupported"):
        workspace.restore(item["id"])
    workspace.purge(item["id"])
    assert (workspace.root / "payload-copy").read_text() == "keep this"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_junction_is_blocked_but_leaf_can_be_removed(
    workspace: Workspace, tmp_path: Path
) -> None:
    import subprocess

    target = tmp_path / "outside"
    target.mkdir()
    (target / "keep").write_text("safe")
    junction = workspace.root / "junction"
    # No enumeration or deletion crosses shells: mklink only creates this exact test fixture.
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)], check=True)
    try:
        assert workspace.list_entries()[0].kind == "blocked_symlink"
        assert workspace.list_entries(recursive=True)[0].path == "junction"
        with code("symlink_not_allowed"):
            workspace.delete("junction")
        with code("symlink_not_allowed"):
            workspace.read_file("junction/keep")
        workspace.delete("junction", permanent=True)
        assert not os.path.lexists(junction)
        assert (target / "keep").read_text() == "safe"
    finally:
        if os.path.lexists(junction):
            junction.rmdir()

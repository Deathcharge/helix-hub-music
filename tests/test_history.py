"""Saved-version recovery and checkpoint-before-overwrite failure boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from samsarix_workspace.api import AppSettings, create_app
from samsarix_workspace.history import HISTORY_NAME, HistoryStore
from samsarix_workspace.shell import VirtualShell
from samsarix_workspace.workspace import Workspace, WorkspaceError


def code(value: str) -> pytest.RaisesExc[WorkspaceError]:
    return pytest.raises(WorkspaceError, check=lambda error: error.code == value)


def saved(workspace: Workspace) -> dict:
    workspace.write_file("note.txt", "original\r\nλ")
    workspace.write_file("note.txt", "edited")
    return workspace.history_report()["items"][0]


def test_snapshot_before_overwrite_restart_noop_and_guarded_restore(workspace: Workspace) -> None:
    assert workspace.history_report()["items"] == []
    workspace.write_file("note.txt", "first")
    assert not (workspace.root / HISTORY_NAME).exists()
    current = workspace.write_file("note.txt", "second")
    version = workspace.history_report("note.txt")["items"][0]
    assert workspace.read_version(version["id"])["content"] == "first"
    workspace.write_file("note.txt", "second")
    assert workspace.history_report()["total_items"] == 1
    restarted = Workspace(workspace.root)
    with code("already_exists"):
        restarted.restore_version(version["id"], "note.txt")
    with code("edit_conflict"):
        restarted.restore_version(version["id"], "note.txt", expected_etag="0" * 64)
    restored = restarted.restore_version(version["id"], "note.txt", expected_etag=current.etag)
    assert restored.content == "first"
    latest = restarted.history_report()["items"][0]
    assert restarted.read_version(latest["id"])["content"] == "second"
    assert restarted.restore_version(latest["id"], "copy.txt").content == "second"


def test_history_survives_move_and_deletion_with_original_paths(workspace: Workspace) -> None:
    version = saved(workspace)
    workspace.move("note.txt", "renamed.txt")
    workspace.delete("renamed.txt", permanent=True)
    assert workspace.history_report("renamed.txt")["items"] == []
    assert workspace.history_report("note.txt")["items"][0]["id"] == version["id"]
    assert workspace.restore_version(version["id"], "recovered.txt").content == "original\r\nλ"


@pytest.mark.parametrize("alias", [HISTORY_NAME, ".SAMSARIX-HISTORY. ", ".samsarix-history:stream"])
def test_private_history_is_excluded_from_public_paths(workspace: Workspace, alias: str) -> None:
    saved(workspace)
    assert [entry.path for entry in workspace.list_entries(recursive=True)] == ["note.txt"]
    assert workspace.usage_bytes() == len(b"edited")
    assert not workspace.search_text("original").matches
    for path in [f"{alias}/owner.json", f"nested/{alias}/info.json"]:
        with code("reserved_path"):
            workspace.read_file(path)
        with code("reserved_path"):
            workspace.write_file(path, "replace")


def test_retention_keeps_newest_by_path_and_global_budgets(tmp_path: Path) -> None:
    workspace = Workspace(
        tmp_path, max_history_bytes=8, max_history_items=3, max_history_per_file=2
    )
    for value in ["111", "222", "333", "444"]:
        workspace.write_file("a.txt", value)
    items = workspace.history_report()["items"]
    assert [workspace.read_version(item["id"])["content"] for item in items] == ["333", "222"]
    for value in ["bbb", "ccc"]:
        workspace.write_file("b.txt", value)
    report = workspace.history_report()
    assert report["usage_bytes"] == 6
    assert [workspace.read_version(item["id"])["content"] for item in report["items"]] == [
        "bbb",
        "333",
    ]
    workspace.write_file("empty.txt", "")
    workspace.write_file("empty.txt", "new")
    workspace.write_file("other.txt", "")
    workspace.write_file("other.txt", "new")
    assert workspace.history_report()["total_items"] == 3


def test_checkpoint_quota_refuses_overwrite(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path, max_history_bytes=2)
    workspace.write_file("note.txt", "large")
    with code("history_quota_exceeded"):
        workspace.write_file("note.txt", "tiny")
    assert workspace.read_file("note.txt").content == "large"


def test_unowned_store_never_adopted(tmp_path: Path) -> None:
    (tmp_path / HISTORY_NAME).mkdir()
    (tmp_path / HISTORY_NAME / "mine.txt").write_text("keep")
    with code("history_unavailable"):
        Workspace(tmp_path)
    assert (tmp_path / HISTORY_NAME / "mine.txt").read_text() == "keep"


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "../outside"),
        ("version", True),
        ("sequence", -1),
        ("etag", "bad"),
        ("size", False),
        ("saved_at", "2020-01-01"),
    ],
)
def test_bad_metadata_blocks_checkpoint_but_can_be_purged(
    workspace: Workspace, field: str, value: object
) -> None:
    version = saved(workspace)
    metadata = workspace.root / HISTORY_NAME / version["id"] / "info.json"
    info = json.loads(metadata.read_text())
    info[field] = value
    metadata.write_text(json.dumps(info))
    report = workspace.history_report()
    assert report["unavailable_items"] == 1
    assert report["items"][0]["path"] is None
    with code("history_unavailable"):
        workspace.read_version(version["id"])
    with code("history_unavailable"):
        workspace.write_file("note.txt", "would lose data")
    assert workspace.read_file("note.txt").content == "edited"
    workspace.purge_version(version["id"])
    workspace.write_file("note.txt", "works")


def test_checksum_and_link_guards(workspace: Workspace, tmp_path: Path) -> None:
    version = saved(workspace)
    payload = workspace.root / HISTORY_NAME / version["id"] / "content"
    old = payload.read_bytes()
    payload.write_bytes(b"x" * len(old))
    with code("history_unavailable"):
        workspace.read_version(version["id"])
    payload.unlink()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(old)
    os.link(outside, payload)
    assert workspace.history_report()["unavailable_items"] == 1
    with code("history_unavailable"):
        workspace.read_version(version["id"])
    workspace.purge_version(version["id"])
    assert outside.read_bytes() == old


@pytest.mark.parametrize("version_id", ["../outside", "a" * 31, "A" * 32, "a" * 32])
def test_invalid_or_missing_version(workspace: Workspace, version_id: str) -> None:
    expected = "not_found" if version_id == "a" * 32 else "invalid_version_id"
    with code(expected):
        workspace.read_version(version_id)
    with code(expected):
        workspace.purge_version(version_id)


def test_snapshot_io_failure_keeps_disk_and_bounds_retries(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace.write_file("note.txt", "keep")
    import samsarix_workspace.history as module

    real_write = module.write_json

    def fail_info(path: Path, value: dict) -> None:
        if path.name == "info.json":
            raise OSError("disk full")
        real_write(path, value)

    monkeypatch.setattr(module, "write_json", fail_info)
    with code("history_write_failed"):
        workspace.write_file("note.txt", "new")
    assert workspace.read_file("note.txt").content == "keep"
    assert workspace.history_report()["unavailable_items"] == 1
    with code("history_unavailable"):
        workspace.write_file("note.txt", "retry")
    assert workspace.history_report()["total_items"] == 1


def test_write_failure_retains_checkpoint_and_deduplicates_retry(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace.write_file("note.txt", "keep")
    with monkeypatch.context() as changes:
        changes.setattr(os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk failure")))
        with code("write_failed"):
            workspace.write_file("note.txt", "new")
    assert workspace.read_file("note.txt").content == "keep"
    workspace.write_file("note.txt", "new")
    assert workspace.history_report()["total_items"] == 1
    assert not list(workspace.root.glob(".samsarix-*.tmp"))


def test_intervening_disk_edit_during_checkpoint_is_not_overwritten(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = workspace.write_file("note.txt", "before")
    checkpoint = workspace._history.checkpoint

    def changed(path: str, content: bytes) -> None:
        checkpoint(path, content)
        (workspace.root / path).write_text("external change")

    monkeypatch.setattr(workspace._history, "checkpoint", changed)
    with code("edit_conflict"):
        workspace.write_file("note.txt", "overwrite", expected_etag=original.etag)
    assert workspace.read_file("note.txt").content == "external change"
    assert not list(workspace.root.glob(".samsarix-*.tmp"))


def test_history_api_auth_preview_restore_validation_and_purge(tmp_path: Path) -> None:
    app = create_app(AppSettings(workspace_root=tmp_path, token="test-token"))
    client = TestClient(app, base_url="http://localhost")
    for method, url, payload in [
        ("GET", "/api/v1/history", None),
        ("GET", "/api/v1/history/x", None),
        ("POST", "/api/v1/history/x/restore", {"destination": "file"}),
        ("DELETE", "/api/v1/history/x?confirm=true", None),
    ]:
        assert client.request(method, url, json=payload).status_code == 401
    client.headers["Authorization"] = "Bearer test-token"
    for content in ["first", "second"]:
        response = client.put("/api/v1/file", json={"path": "note", "content": content})
        assert response.status_code == 200
    etag = response.json()["file"]["etag"]
    version = client.get("/api/v1/history?path=note").json()["history"]["items"][0]
    url = f"/api/v1/history/{version['id']}"
    assert client.get(url).json()["version"]["content"] == "first"
    assert client.post(url + "/restore", json={"destination": "note"}).status_code == 409
    assert (
        client.post(
            url + "/restore", json={"destination": "note", "expected_etag": "bad"}
        ).status_code
        == 422
    )
    assert (
        client.post(url + "/restore", json={"destination": "note", "expected_etag": etag}).json()[
            "file"
        ]["content"]
        == "first"
    )
    assert client.delete(url).status_code == 400
    assert client.delete(url + "?confirm=true").status_code == 200
    assert client.get(url).status_code == 404


def test_virtual_history_preview_restore_and_purge(workspace: Workspace) -> None:
    version = saved(workspace)
    shell = VirtualShell(workspace)
    assert version["id"] in shell.execute("history note.txt").output
    assert shell.execute(f"version {version['id']}").output == "original\r\nλ"
    assert shell.execute(f"restore-version {version['id']} note.txt").exit_code == 1
    assert shell.execute(f"restore-version {version['id']} copy.txt").exit_code == 0
    assert shell.execute(f"purge-version {version['id']}").exit_code == 1
    assert shell.execute(f"purge-version {version['id']} --confirm").exit_code == 0
    assert shell.execute("history").output == "No saved versions."


@pytest.mark.parametrize("settings", [{"max_bytes": 0}, {"max_items": 0}, {"max_per_file": 201}])
def test_invalid_history_limits(workspace: Workspace, settings: dict) -> None:
    with pytest.raises(ValueError):
        HistoryStore(
            workspace, **{"max_bytes": 50, "max_items": 200, "max_per_file": 20, **settings}
        )


def test_retention_cleanup_failure_blocks_growth_without_losing_current_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import samsarix_workspace.history as module

    workspace = Workspace(tmp_path, max_history_items=1, max_history_per_file=1)
    workspace.write_file("note", "first")
    workspace.write_file("note", "second")
    with monkeypatch.context() as changes:
        changes.setattr(
            module.shutil, "rmtree", lambda *args: (_ for _ in ()).throw(OSError("denied"))
        )
        with code("history_purge_failed"):
            workspace.write_file("note", "third")
    assert workspace.read_file("note").content == "second"
    assert workspace.history_report()["total_items"] == 2
    with code("history_unavailable"):
        workspace.write_file("note", "retry")
    assert workspace.history_report()["total_items"] == 2
    workspace.purge_version(workspace.history_report()["items"][-1]["id"])
    workspace.write_file("note", "third")
    assert workspace.history_report()["total_items"] == 1


def test_new_target_race_never_overwrites_uncheckpointed_file(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_link = os.link

    def competing_link(source: str, target: Path) -> None:
        target.write_text("competing content")
        real_link(source, target)

    monkeypatch.setattr(os, "link", competing_link)
    with code("already_exists"):
        workspace.write_file("note.txt", "ours")
    assert workspace.read_file("note.txt").content == "competing content"
    assert not list(workspace.root.glob(".samsarix-*.tmp"))


def test_invalid_unicode_never_reaches_snapshot_or_disk(workspace: Workspace) -> None:
    workspace.write_file("note.txt", "original")
    with code("invalid_content"):
        workspace.write_file("note.txt", "\ud800")
    with code("invalid_path"):
        workspace.write_file("\ud800.txt", "valid")
    assert workspace.read_file("note.txt").content == "original"
    assert workspace.history_report()["total_items"] == 0


def test_history_inventory_and_record_link_are_bounded(
    workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import samsarix_workspace.history as module

    saved(workspace)
    workspace.write_file("note.txt", "third")
    with monkeypatch.context() as changes:
        changes.setattr(module, "MAX_RECORDS", 1)
        with code("history_item_limit"):
            workspace.history_report()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("private")
    link = workspace.root / HISTORY_NAME / ("f" * 32)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks unavailable on this filesystem")
    with code("history_unavailable"):
        workspace.read_version(link.name)
    with code("history_unavailable"):
        workspace.purge_version(link.name)
    assert (outside / "keep.txt").read_text() == "private"

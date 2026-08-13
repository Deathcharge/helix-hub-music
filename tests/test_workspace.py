from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from samsarix_workspace.workspace import Workspace, WorkspaceError


def raises_code(code: str) -> pytest.RaisesExc[WorkspaceError]:
    return pytest.raises(WorkspaceError, check=lambda exc: exc.code == code)


def test_primary_file_journey_and_summary(workspace: Workspace) -> None:
    folder = workspace.make_directory("notes")
    assert folder.kind == "directory"

    created = workspace.write_file("notes/idea.md", "first thought\n")
    assert created.path == "notes/idea.md"
    assert created.size == 14
    assert len(created.etag) == 64

    opened = workspace.read_file("notes/idea.md")
    saved = workspace.write_file(
        "notes/idea.md", opened.content + "second thought\n", expected_etag=opened.etag
    )
    assert saved.content.endswith("second thought\n")
    assert saved.etag != opened.etag

    entries = workspace.list_entries("", recursive=True)
    assert [(entry.path, entry.kind) for entry in entries] == [
        ("notes", "directory"),
        ("notes/idea.md", "file"),
    ]
    summary = workspace.summary()
    workspace_id = summary.pop("id")
    assert len(workspace_id) == 16
    assert int(workspace_id, 16) >= 0
    assert summary == {
        "name": "workspace",
        "entries": 2,
        "usage_bytes": 29,
        "limits": {
            "max_file_bytes": 256,
            "max_total_bytes": 1_024,
            "max_entries": 2_000,
        },
    }


def test_optimistic_concurrency_prevents_lost_updates(workspace: Workspace) -> None:
    original = workspace.write_file("draft.txt", "one")
    workspace.write_file("draft.txt", "two", expected_etag=original.etag)

    with raises_code("edit_conflict"):
        workspace.write_file("draft.txt", "stale", expected_etag=original.etag)
    with raises_code("edit_conflict"):
        workspace.write_file("missing.txt", "stale", expected_etag="0" * 64)
    with raises_code("already_exists"):
        workspace.write_file("draft.txt", "replacement", create_only=True)


def test_create_only_does_not_replace_a_racing_writer(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_link = os.link

    def racing_link(source: str, destination: str | Path) -> None:
        Path(destination).write_text("racing writer", encoding="utf-8")
        original_link(source, destination)

    monkeypatch.setattr(os, "link", racing_link)
    with raises_code("already_exists"):
        workspace.write_file("race.txt", "imported content", create_only=True)

    assert workspace.read_file("race.txt").content == "racing writer"
    assert not list(workspace.root.glob(".samsarix-*.tmp"))


def test_bounded_text_search_reports_matches_and_resource_use(workspace: Workspace) -> None:
    workspace.make_directory("docs")
    workspace.write_file("docs/alpha.md", "First needle\nsecond NEEDLE\n")
    workspace.write_file("docs/other.txt", "nothing here\n")
    (workspace.root / "docs" / "binary.bin").write_bytes(b"needle\xff")

    report = workspace.search_text("needle", "docs")
    assert [(match.path, match.line, match.column, match.length) for match in report.matches] == [
        ("docs/alpha.md", 1, 7, 6),
        ("docs/alpha.md", 2, 8, 6),
    ]
    assert report.scanned_files == 2
    assert report.skipped_files == 1
    assert report.scanned_bytes > 0
    assert report.truncated is False

    exact = workspace.search_text("NEEDLE", "docs", case_sensitive=True)
    assert [(match.path, match.line) for match in exact.matches] == [("docs/alpha.md", 2)]
    limited = workspace.search_text("needle", "docs", limit=1)
    assert len(limited.matches) == 1
    assert limited.truncated is True
    byte_limited = workspace.search_text("needle", "docs", max_scan_bytes=1)
    assert byte_limited.matches == ()
    assert byte_limited.truncated is True

    workspace.write_file("docs/unicode.txt", "Straße\n")
    unicode_match = workspace.search_text("SSE", "docs").matches[0]
    assert (unicode_match.column, unicode_match.length) == (5, 2)


def test_search_validation_and_preview_bounds(workspace: Workspace) -> None:
    search_workspace = Workspace(workspace.root / "search-preview", max_file_bytes=512)
    search_workspace.write_file("long.txt", ("p" * 200) + "needle" + ("s" * 200))
    report = search_workspace.search_text("needle")
    assert len(report.matches[0].preview) <= 242
    assert report.matches[0].preview.startswith("…")
    assert report.matches[0].preview.endswith("…")
    with raises_code("invalid_search"):
        search_workspace.search_text("")
    with raises_code("invalid_search"):
        search_workspace.search_text("x", limit=0)
    with raises_code("invalid_search"):
        search_workspace.search_text("x", max_scan_bytes=-1)


def test_search_read_is_bounded_when_entry_size_is_stale(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace.write_file("growing.txt", "needle beyond the byte budget")
    stale_entry = replace(workspace.list_entries()[0], size=1)
    monkeypatch.setattr(
        workspace,
        "list_entries",
        lambda _path="", *, recursive=False: [stale_entry],
    )

    report = workspace.search_text("needle", max_scan_bytes=5)

    assert report.matches == ()
    assert report.scanned_bytes == 6
    assert report.truncated is True


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("../outside", "invalid_path"),
        ("folder/../outside", "invalid_path"),
        ("/absolute", "invalid_path"),
        ("folder\\file", "invalid_path"),
        ("a/./b", "invalid_path"),
        ("", "root_not_allowed"),
    ],
)
def test_invalid_paths_are_rejected(workspace: Workspace, path: str, code: str) -> None:
    with raises_code(code):
        workspace.write_file(path, "no")


def test_root_cannot_be_moved_or_deleted(workspace: Workspace) -> None:
    with raises_code("root_not_allowed"):
        workspace.delete("")
    with raises_code("root_not_allowed"):
        workspace.move("", "elsewhere")


def test_symlink_escape_is_blocked_for_reads_writes_and_moves(
    workspace: Workspace, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside-secret", encoding="utf-8")
    link = workspace.root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available for this test user")

    with raises_code("symlink_not_allowed"):
        workspace.read_file("link/secret.txt")
    with raises_code("symlink_not_allowed"):
        workspace.write_file("link/created.txt", "escape")
    with raises_code("symlink_not_allowed"):
        workspace.move("link", "moved")
    workspace.delete("link")
    assert not link.exists()
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "outside-secret"


def test_broken_symlink_can_be_safely_removed(workspace: Workspace) -> None:
    link = workspace.root / "broken"
    try:
        link.symlink_to(workspace.root.parent / "absent")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available for this test user")
    workspace.delete("broken")
    assert not link.is_symlink()


def test_hardlink_escape_is_blocked_but_link_can_be_removed(
    workspace: Workspace, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-secret", encoding="utf-8")
    linked = workspace.root / "linked.txt"
    try:
        os.link(outside, linked)
    except OSError:
        pytest.skip("hard links are not available on this filesystem")

    entry = next(item for item in workspace.list_entries() if item.path == "linked.txt")
    assert entry.kind == "blocked_hardlink"
    with raises_code("hardlink_not_allowed"):
        workspace.read_file("linked.txt")
    with raises_code("hardlink_not_allowed"):
        workspace.write_file("linked.txt", "changed")
    with raises_code("hardlink_not_allowed"):
        workspace.move("linked.txt", "moved.txt")
    workspace.delete("linked.txt")
    assert outside.read_text(encoding="utf-8") == "outside-secret"
    assert not linked.exists()


def test_file_and_total_quotas_are_enforced(workspace: Workspace) -> None:
    with raises_code("file_too_large"):
        workspace.write_file("large.txt", "x" * 257)

    small_total = Workspace(workspace.root / "small", max_file_bytes=10, max_total_bytes=5)
    small_total.write_file("a.txt", "1234")
    with raises_code("workspace_quota_exceeded"):
        small_total.write_file("b.txt", "12")
    small_total.write_file("a.txt", "1")
    assert small_total.usage_bytes() == 1


def test_large_and_binary_files_cannot_be_opened(workspace: Workspace) -> None:
    (workspace.root / "large.bin").write_bytes(b"x" * 257)
    with raises_code("file_too_large"):
        workspace.read_file("large.bin")

    (workspace.root / "binary.bin").write_bytes(b"\xff\xfe")
    with raises_code("binary_file"):
        workspace.read_file("binary.bin")


def test_move_delete_and_conflict_behavior(workspace: Workspace) -> None:
    workspace.make_directory("from")
    workspace.write_file("from/a.txt", "a")
    workspace.make_directory("to")
    moved = workspace.move("from/a.txt", "to/b.txt")
    assert moved.path == "to/b.txt"

    workspace.write_file("to/existing.txt", "x")
    with raises_code("already_exists"):
        workspace.move("to/b.txt", "to/existing.txt")
    with raises_code("invalid_move"):
        workspace.move("to", "to/inside")
    with raises_code("directory_not_empty"):
        workspace.delete("to")
    workspace.delete("to", recursive=True)
    assert not (workspace.root / "to").exists()


def test_parent_and_type_errors_are_stable(workspace: Workspace) -> None:
    with raises_code("parent_not_found"):
        workspace.write_file("missing/a.txt", "a")
    with raises_code("parent_not_found"):
        workspace.make_directory("missing/folder")
    workspace.write_file("file.txt", "x")
    with raises_code("not_a_directory"):
        workspace.list_entries("file.txt")
    with raises_code("root_not_allowed"):
        workspace.read_file("")
    with raises_code("not_found"):
        workspace.read_file("absent.txt")
    with raises_code("already_exists"):
        workspace.make_directory("file.txt")
    with raises_code("not_a_directory"):
        workspace.assert_directory("file.txt")
    with raises_code("not_found"):
        workspace.assert_directory("missing")
    workspace.assert_directory("")


def test_listing_is_sorted_bounded_and_does_not_follow_symlinks(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "root", max_entries=2)
    workspace.write_file("b.txt", "b")
    workspace.write_file("A.txt", "a")
    assert [entry.path for entry in workspace.list_entries()] == ["A.txt", "b.txt"]
    workspace.write_file("c.txt", "c")
    with raises_code("entry_limit_exceeded"):
        workspace.list_entries()
    with raises_code("entry_limit_exceeded"):
        workspace.list_entries(recursive=True)


def test_special_file_is_identified_without_reading_on_posix(
    workspace: Workspace, tmp_path: Path
) -> None:
    if os.name == "nt":
        pytest.skip("FIFO files are POSIX-only")
    fifo = workspace.root / "events"
    os.mkfifo(fifo)
    entry = workspace.list_entries()[0]
    assert entry.kind == "blocked_special"

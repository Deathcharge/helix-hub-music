"""Recover real disk content through the UI, including ordinary failure and retry."""

import json

import pytest
from conftest import RunningWorkspace
from playwright.sync_api import Page, expect


def delete_alpha(page: Page) -> None:
    page.get_by_role("treeitem").filter(has_text="alpha.txt").click()
    page.get_by_role("button", name="Delete", exact=True).click()
    page.get_by_role("button", name="Move to Trash", exact=True).click()
    expect(page.get_by_role("heading", name="Choose a file", exact=True)).to_be_visible()


def test_delete_reload_restore_collision_and_explicit_purge(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    delete_alpha(page)
    assert not (live_workspace.root / "alpha.txt").exists()
    page.reload()
    page.get_by_role("button", name="Trash", exact=True).click()
    expect(page.get_by_role("dialog", name="Trash", exact=True)).to_be_visible()
    expect(page.locator("#trash-status")).to_contain_text("1 / 100 items")
    assert page.get_by_role("treeitem").filter(has_text=".samsarix-trash").count() == 0
    (live_workspace.root / "alpha.txt").write_text("new disk content", encoding="utf-8")
    page.get_by_role("button", name="Restore alpha.txt", exact=True).click()
    page.get_by_role("button", name="Restore", exact=True).click()
    expect(page.locator("#entry-error")).to_contain_text("already exists")
    assert (live_workspace.root / "alpha.txt").read_text() == "new disk content"
    page.get_by_role("textbox", name="Workspace path").fill("recovered.txt")
    page.get_by_role("button", name="Restore", exact=True).click()
    expect(page.get_by_role("treeitem").filter(has_text="recovered.txt")).to_be_visible()
    assert (live_workspace.root / "recovered.txt").read_text() == "alpha on disk\n"
    page.get_by_role("treeitem").filter(has_text="recovered.txt").click()
    page.get_by_role("button", name="Delete", exact=True).click()
    page.get_by_role("button", name="Move to Trash", exact=True).click()
    expect(page.get_by_role("heading", name="Choose a file", exact=True)).to_be_visible()
    page.get_by_role("button", name="Trash", exact=True).click()
    page.get_by_role("button", name="Permanently delete recovered.txt", exact=True).click()
    expect(page.get_by_role("dialog", name="Permanently delete recovery item?")).to_be_visible()
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(page.get_by_role("button", name="Restore recovered.txt", exact=True)).to_be_visible()
    page.get_by_role("button", name="Permanently delete recovered.txt", exact=True).click()
    page.get_by_role("button", name="Delete permanently", exact=True).click()
    expect(page.locator("#trash-items")).to_contain_text("Trash is empty.")
    expect(page.get_by_role("button", name="Refresh Trash", exact=True)).to_be_focused()
    page.reload()
    page.get_by_role("button", name="Trash", exact=True).click()
    expect(page.locator("#trash-items")).to_contain_text("Trash is empty.")


def test_delete_dirty_cancel_and_restore_preserves_other_editor(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    page.get_by_role("treeitem").filter(has_text="alpha.txt").click()
    editor = page.get_by_role("textbox", name="File editor")
    editor.fill("unsaved changes")
    page.get_by_role("button", name="Delete", exact=True).click()
    expect(page.locator("#confirm-message")).to_contain_text("only the disk version is kept")
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(editor).to_have_value("unsaved changes")
    assert (live_workspace.root / "alpha.txt").read_text() == "alpha on disk\n"
    page.get_by_role("button", name="Delete", exact=True).click()
    page.get_by_role("button", name="Move to Trash", exact=True).click()
    expect(page.get_by_role("heading", name="Choose a file", exact=True)).to_be_visible()
    page.get_by_role("treeitem").filter(has_text="beta.txt").click()
    editor.fill("keep beta draft")
    page.get_by_role("button", name="Trash", exact=True).click()
    page.get_by_role("button", name="Restore alpha.txt", exact=True).click()
    page.get_by_role("button", name="Restore", exact=True).click()
    expect(page.get_by_role("heading", name="beta.txt", exact=True)).to_be_visible()
    expect(editor).to_have_value("keep beta draft")
    expect(page.locator("#dirty-indicator")).to_be_visible()
    assert (live_workspace.root / "alpha.txt").read_text() == "alpha on disk\n"


@pytest.mark.parametrize("trash_bytes", [1], indirect=True)
def test_full_trash_error_is_inline_and_keeps_editor(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    page.get_by_role("treeitem").filter(has_text="alpha.txt").click()
    page.get_by_role("button", name="Delete", exact=True).click()
    page.get_by_role("button", name="Move to Trash", exact=True).click()
    expect(page.locator("#confirm-error")).to_contain_text("Trash is full")
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(page.get_by_role("textbox", name="File editor")).to_have_value("alpha on disk\n")
    assert (live_workspace.root / "alpha.txt").read_text() == "alpha on disk\n"
    page.get_by_role("button", name="Trash", exact=True).click()
    expect(page.locator("#trash-items")).to_contain_text("Trash is empty.")


def test_stale_editor_delete_rejected_until_reload(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    page.get_by_role("treeitem").filter(has_text="alpha.txt").click()
    (live_workspace.root / "alpha.txt").write_text("other writer", encoding="utf-8")
    page.get_by_role("button", name="Delete", exact=True).click()
    page.get_by_role("button", name="Move to Trash", exact=True).click()
    expect(page.locator("#confirm-error")).to_contain_text("file changed")
    page.get_by_role("button", name="Cancel", exact=True).click()
    assert (live_workspace.root / "alpha.txt").read_text() == "other writer"
    page.reload()
    delete_alpha(page)


def test_trash_load_failure_retry_unreadable_item_and_mobile(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    delete_alpha(page)
    record = next(
        path for path in (live_workspace.root / ".samsarix-trash").iterdir() if path.is_dir()
    )
    info_path = record / "info.json"
    info = json.loads(info_path.read_text())
    info["path"] = "../unsafe"
    info_path.write_text(json.dumps(info))
    page.route("**/api/v1/trash", lambda route: route.abort())
    page.get_by_role("button", name="Trash", exact=True).click()
    expect(page.locator("#trash-status")).to_have_text("Trash could not be loaded.")
    expect(page.locator("#trash-error")).not_to_be_empty()
    page.unroute("**/api/v1/trash")
    page.get_by_role("button", name="Refresh Trash", exact=True).click()
    expect(page.locator("#trash-error")).to_contain_text("Unreadable items block")
    expect(page.get_by_role("button", name=f"Restore {record.name}", exact=True)).to_be_disabled()
    expect(page.locator("#trash-items")).not_to_contain_text("../unsafe")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.locator("#trash-dialog").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.get_by_role("button", name=f"Permanently delete {record.name}", exact=True).click()
    page.get_by_role("button", name="Delete permanently", exact=True).click()
    expect(page.locator("#trash-items")).to_contain_text("Trash is empty.")


def test_virtual_terminal_recovery_flow(page: Page, live_workspace: RunningWorkspace) -> None:
    command = page.get_by_role("textbox", name="Virtual terminal command")
    command.fill("rm alpha.txt")
    page.get_by_role("button", name="Run", exact=True).click()
    expect(page.locator("#terminal-output")).to_contain_text("Moved to Trash: alpha.txt")
    record = next(
        path for path in (live_workspace.root / ".samsarix-trash").iterdir() if path.is_dir()
    )
    command.fill(f"restore {record.name} alternate.txt")
    page.get_by_role("button", name="Run", exact=True).click()
    expect(page.get_by_role("treeitem").filter(has_text="alternate.txt")).to_be_visible()
    assert (live_workspace.root / "alternate.txt").read_text() == "alpha on disk\n"

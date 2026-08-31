"""History previews and restores exercise the real API and persistent files."""

from __future__ import annotations

import json

import pytest
from conftest import RunningWorkspace
from playwright.sync_api import Page, expect


def save_alpha(page: Page, content: str = "saved second version") -> None:
    page.get_by_role("treeitem").filter(has_text="alpha.txt").click()
    page.get_by_role("textbox", name="File editor").fill(content)
    page.locator("#save-button").click()
    expect(page.locator("#dirty-indicator")).to_be_hidden()


def preview_first(page: Page) -> None:
    page.get_by_role("button", name="History", exact=True).click()
    page.get_by_role("button", name="Preview alpha.txt version 1", exact=True).click()
    expect(page.get_by_role("textbox", name="Saved version", exact=True)).to_be_visible()


def test_preview_copy_collision_and_persistence(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    save_alpha(page)
    page.reload()
    preview_first(page)
    expect(page.get_by_role("textbox", name="Saved version", exact=True)).to_have_value(
        "alpha on disk\n"
    )
    expect(page.get_by_role("textbox", name="Current disk file", exact=True)).to_have_value(
        "saved second version"
    )
    page.get_by_role("textbox", name="New copy path").fill("alpha.txt")
    page.get_by_role("button", name="Restore a new copy", exact=True).click()
    expect(page.locator("#history-error")).to_contain_text("already exists")
    assert (live_workspace.root / "alpha.txt").read_text() == "saved second version"
    page.get_by_role("textbox", name="New copy path").fill("recovered.txt")
    page.get_by_role("button", name="Restore a new copy", exact=True).click()
    expect(page.locator("#toast")).to_contain_text("Restored a new copy")
    assert (live_workspace.root / "recovered.txt").read_text() == "alpha on disk\n"
    page.get_by_role("button", name="Close", exact=True).click()
    expect(page.get_by_role("treeitem").filter(has_text="recovered.txt")).to_be_visible()


def test_replace_conflict_retry_and_reversible_current_version(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    save_alpha(page)
    preview_first(page)
    (live_workspace.root / "alpha.txt").write_text("external disk change")
    page.get_by_role("button", name="Replace current disk file", exact=True).click()
    page.get_by_role("button", name="Replace disk file", exact=True).click()
    expect(page.locator("#confirm-error")).to_contain_text("changed")
    assert (live_workspace.root / "alpha.txt").read_text() == "external disk change"
    page.get_by_role("button", name="Cancel", exact=True).click()
    page.get_by_role("button", name="Refresh history", exact=True).click()
    page.get_by_role("button", name="Preview alpha.txt version 1", exact=True).click()
    expect(page.get_by_role("textbox", name="Current disk file", exact=True)).to_have_value(
        "external disk change"
    )
    page.get_by_role("button", name="Replace current disk file", exact=True).click()
    page.get_by_role("button", name="Replace disk file", exact=True).click()
    expect(page.locator("#history-dialog")).not_to_be_visible()
    expect(page.get_by_role("textbox", name="File editor")).to_have_value("alpha on disk\n")
    assert (live_workspace.root / "alpha.txt").read_text() == "alpha on disk\n"
    page.get_by_role("button", name="History", exact=True).click()
    page.get_by_role("button", name="Preview alpha.txt version 2", exact=True).click()
    expect(page.get_by_role("textbox", name="Saved version", exact=True)).to_have_value(
        "external disk change"
    )


def test_replace_preserves_dirty_editor_and_its_original_etag(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    save_alpha(page)
    editor = page.get_by_role("textbox", name="File editor")
    editor.fill("keep this unsaved draft")
    preview_first(page)
    page.get_by_role("button", name="Replace current disk file", exact=True).click()
    page.get_by_role("button", name="Cancel", exact=True).click()
    assert (live_workspace.root / "alpha.txt").read_text() == "saved second version"
    page.get_by_role("button", name="Replace current disk file", exact=True).click()
    page.get_by_role("button", name="Replace disk file", exact=True).click()
    expect(page.locator("#history-dialog")).not_to_be_visible()
    expect(editor).to_have_value("keep this unsaved draft")
    expect(page.locator("#dirty-indicator")).to_be_visible()
    assert (live_workspace.root / "alpha.txt").read_text() == "alpha on disk\n"
    page.locator("#save-button").click()
    expect(page.locator("#conflict-dialog")).to_be_visible()
    assert (live_workspace.root / "alpha.txt").read_text() == "alpha on disk\n"


def test_empty_history_network_retry_and_deleted_file(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    page.get_by_role("button", name="History", exact=True).click()
    expect(page.locator("#history-items")).to_contain_text("No saved versions")
    page.get_by_role("button", name="Close", exact=True).click()
    save_alpha(page)
    (live_workspace.root / "alpha.txt").unlink()
    page.route("**/api/v1/history?*", lambda route: route.abort())
    page.get_by_role("button", name="History", exact=True).click()
    expect(page.locator("#history-status")).to_have_text("History could not be loaded.")
    page.unroute("**/api/v1/history?*")
    page.get_by_role("button", name="Refresh history", exact=True).click()
    page.get_by_role("button", name="Preview alpha.txt version 1", exact=True).click()
    expect(page.locator("#history-current-status")).to_contain_text("original path is absent")
    expect(
        page.get_by_role("button", name="Replace current disk file", exact=True)
    ).to_be_disabled()
    page.get_by_role("textbox", name="New copy path").fill("alpha.txt")
    page.get_by_role("button", name="Restore a new copy", exact=True).click()
    expect(page.locator("#toast")).to_contain_text("Restored a new copy")
    assert (live_workspace.root / "alpha.txt").read_text() == "alpha on disk\n"


def test_unavailable_version_purge_cancel_mobile_and_inert_preview(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    attack_text = '<img src=x onerror="window.historyXss=1">\n<script>window.historyXss=1</script>'
    save_alpha(page, attack_text)
    page.get_by_role("textbox", name="File editor").fill("safe current")
    page.locator("#save-button").click()
    expect(page.locator("#dirty-indicator")).to_be_hidden()
    page.get_by_role("button", name="History", exact=True).click()
    page.get_by_role("button", name="Preview alpha.txt version 2", exact=True).click()
    expect(page.get_by_role("textbox", name="Saved version", exact=True)).to_have_value(attack_text)
    assert page.evaluate("window.historyXss === undefined")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.locator("#history-dialog").evaluate("e => e.scrollWidth <= e.clientWidth")
    record = next(
        path for path in (live_workspace.root / ".samsarix-history").iterdir() if path.is_dir()
    )
    info = json.loads((record / "info.json").read_text())
    info["path"] = "../outside"
    (record / "info.json").write_text(json.dumps(info))
    page.get_by_role("button", name="Refresh history", exact=True).click()
    expect(page.locator("#history-error")).to_contain_text("Unavailable records block")
    page.get_by_role("button", name=f"Remove {record.name} version 0", exact=True).click()
    page.get_by_role("button", name="Cancel", exact=True).click()
    assert record.exists()
    page.get_by_role("button", name=f"Remove {record.name} version 0", exact=True).click()
    page.get_by_role("button", name="Remove version permanently", exact=True).click()
    expect(page.locator("#history-error")).to_be_empty()
    assert not record.exists()
    assert (live_workspace.root / "alpha.txt").read_text() == "safe current"


@pytest.mark.parametrize("history_bytes", [1], indirect=True)
def test_history_capacity_failure_keeps_disk_and_draft(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    page.get_by_role("treeitem").filter(has_text="alpha.txt").click()
    editor = page.get_by_role("textbox", name="File editor")
    editor.fill("a new draft")
    page.locator("#save-button").click()
    expect(page.locator("#toast")).to_contain_text("prior file cannot fit")
    expect(editor).to_have_value("a new draft")
    expect(page.locator("#dirty-indicator")).to_be_visible()
    assert (live_workspace.root / "alpha.txt").read_text() == "alpha on disk\n"

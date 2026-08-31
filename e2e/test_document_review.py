"""A complete user journey with real import, disk persistence, preview, and export."""

from pathlib import Path

from conftest import RunningWorkspace
from playwright.sync_api import Page, expect


def test_import_preview_search_save_download_and_mobile(
    page: Page, live_workspace: RunningWorkspace, tmp_path: Path
) -> None:
    text = "# Review\n\n😀 preceding\nalpha 😀 omega\n\n<script>window.injected=true</script>\n"
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="Import text files").click()
    chooser.value.set_files(
        {"name": "review.md", "mimeType": "text/markdown", "buffer": text.encode("utf-8")}
    )
    expect(page.get_by_role("heading", name="review.md", exact=True)).to_be_visible()
    assert (live_workspace.root / "review.md").read_text(encoding="utf-8") == text
    page.get_by_role("button", name="Preview", exact=True).click()
    expect(page.get_by_role("heading", name="Review", exact=True)).to_be_visible()
    expect(page.locator("#markdown-preview")).to_contain_text("<script>")
    assert page.locator("#markdown-preview script").count() == 0
    assert page.evaluate("window.injected === undefined")
    page.get_by_role("searchbox", name="Search file contents").fill("😀 omega")
    page.get_by_role("button", name="review.md:4:7 alpha 😀 omega", exact=True).click()
    editor = page.get_by_role("textbox", name="File editor")
    expect(editor).to_be_visible()
    assert editor.evaluate("e => e.value.slice(e.selectionStart, e.selectionEnd)") == "😀 omega"
    editor.fill(text + "Reviewed and ready.\n")
    page.locator("#save-button").click()
    expect(page.locator("#editor-message")).to_have_text("Saved")
    with page.expect_download() as download:
        page.get_by_role("button", name="Download", exact=True).click()
    target = tmp_path / download.value.suggested_filename
    download.value.save_as(target)
    assert target.read_text(encoding="utf-8") == text + "Reviewed and ready.\n"
    assert target.read_bytes() == (live_workspace.root / "review.md").read_bytes()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.get_by_role("button", name="Download", exact=True)).to_be_visible()


def test_create_rename_and_confirmed_delete(page: Page, live_workspace: RunningWorkspace) -> None:
    page.get_by_role("button", name="New file", exact=True).click()
    page.get_by_role("textbox", name="Workspace path").fill("new.txt")
    page.get_by_role("button", name="Create", exact=True).click()
    expect(page.get_by_role("heading", name="new.txt", exact=True)).to_be_visible()
    page.get_by_role("textbox", name="File editor").fill("keep through rename")
    page.locator("#save-button").click()
    expect(page.locator("#editor-message")).to_have_text("Saved")
    page.get_by_role("button", name="Rename", exact=True).click()
    page.get_by_role("textbox", name="Workspace path").fill("renamed.txt")
    page.get_by_role("button", name="Move", exact=True).click()
    expect(page.get_by_role("heading", name="renamed.txt", exact=True)).to_be_visible()
    assert not (live_workspace.root / "new.txt").exists()
    assert (live_workspace.root / "renamed.txt").read_text(
        encoding="utf-8"
    ) == "keep through rename"
    page.get_by_role("button", name="Delete", exact=True).click()
    expect(page.locator("#confirm-message")).to_contain_text("renamed.txt")
    page.get_by_role("button", name="Delete permanently", exact=True).click()
    expect(page.get_by_role("heading", name="Choose a file", exact=True)).to_be_visible()
    assert not (live_workspace.root / "renamed.txt").exists()

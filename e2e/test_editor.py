"""Browser-to-API-to-disk regressions; only response delivery is controlled."""

from __future__ import annotations

import json
import time

import pytest
from conftest import RunningWorkspace
from playwright.sync_api import Dialog, Page, Route, expect


def open_file(page: Page, path: str) -> None:
    page.get_by_role("treeitem").filter(has_text=path).click()
    expect(page.get_by_role("heading", name=path, exact=True)).to_be_visible()


class HeldRequests:
    """Hold matching browser requests until the test explicitly releases them."""

    def __init__(self, page: Page, method: str) -> None:
        self.page = page
        self.method = method
        self.pending: list[Route] = []
        self.count = 0
        page.route("**/api/v1/file?*" if method == "GET" else "**/api/v1/file", self.handle)

    def handle(self, route: Route) -> None:
        if route.request.method != self.method:
            route.continue_()
            return
        self.count += 1
        self.pending.append(route)

    def wait(self, count: int = 1) -> None:
        deadline = time.monotonic() + 5
        while len(self.pending) < count and time.monotonic() < deadline:
            self.page.wait_for_timeout(10)
        assert len(self.pending) >= count, "Expected request was not received"

    def release(self, index: int = 0) -> None:
        self.pending.pop(index).continue_()


def test_save_keeps_newer_edits_dirty_and_recoverable(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    open_file(page, "alpha.txt")
    editor = page.get_by_role("textbox", name="File editor")
    editor.fill("first save")
    held = HeldRequests(page, "PUT")
    page.keyboard.press("Control+s")
    held.wait()
    page.keyboard.press("Control+s")
    editor.fill("newer typing while saving")
    held.release()
    expect(page.locator("#editor-message")).to_have_text("Unsaved changes")
    expect(page.locator("#save-button")).to_be_enabled()
    assert held.count == 1
    assert (live_workspace.root / "alpha.txt").read_text(encoding="utf-8") == "first save"
    draft = page.evaluate("JSON.parse(sessionStorage.getItem('samsarix-workspace-draft'))")
    assert draft["content"] == "newer typing while saving"
    page.keyboard.press("Control+s")
    held.wait()
    held.release()
    expect(page.locator("#editor-message")).to_have_text("Saved")
    assert (live_workspace.root / "alpha.txt").read_text(encoding="utf-8") == draft["content"]


def test_pending_open_cannot_save_previous_text_into_new_path(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    open_file(page, "alpha.txt")
    held = HeldRequests(page, "GET")
    page.get_by_role("treeitem").filter(has_text="beta.txt").click()
    held.wait()
    expect(page.get_by_role("textbox", name="File editor")).to_have_attribute("readonly", "")
    page.keyboard.press("Control+s")
    held.release()
    expect(page.get_by_role("textbox", name="File editor")).to_have_value("beta on disk\n")
    assert (live_workspace.root / "alpha.txt").read_text(encoding="utf-8") == "alpha on disk\n"
    assert (live_workspace.root / "beta.txt").read_text(encoding="utf-8") == "beta on disk\n"


def test_latest_open_wins_when_responses_arrive_out_of_order(page: Page) -> None:
    held = HeldRequests(page, "GET")
    page.get_by_role("treeitem").filter(has_text="alpha.txt").click()
    page.get_by_role("treeitem").filter(has_text="beta.txt").click()
    held.wait(2)
    held.release(1)
    expect(page.get_by_role("textbox", name="File editor")).to_have_value("beta on disk\n")
    with page.expect_response(lambda response: "path=alpha.txt" in response.url) as response:
        held.release()
    response.value.finished()
    page.evaluate("() => new Promise(requestAnimationFrame)")
    expect(page.get_by_role("heading", name="beta.txt", exact=True)).to_be_visible()
    expect(page.get_by_role("textbox", name="File editor")).to_have_value("beta on disk\n")


def test_failed_open_preserves_previous_document_and_draft(page: Page) -> None:
    open_file(page, "alpha.txt")
    editor = page.get_by_role("textbox", name="File editor")
    editor.fill("keep this unsaved draft")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("treeitem").filter(has_text="binary.bin").click()
    expect(page.locator("#editor-message")).to_contain_text("Only UTF-8")
    expect(page.get_by_role("heading", name="alpha.txt", exact=True)).to_be_visible()
    expect(editor).to_have_value("keep this unsaved draft")
    expect(page.locator("#save-button")).to_be_enabled()
    page.wait_for_function("sessionStorage.getItem('samsarix-workspace-draft') !== null")
    assert page.evaluate("JSON.parse(sessionStorage.getItem('samsarix-workspace-draft')).path") == (
        "alpha.txt"
    )


def test_keep_editing_does_not_silently_authorize_conflict_overwrite(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    open_file(page, "alpha.txt")
    page.get_by_role("textbox", name="File editor").fill("my local edit")
    (live_workspace.root / "alpha.txt").write_text("external edit", encoding="utf-8")
    page.locator("#save-button").click()
    expect(page.locator("#conflict-dialog")).to_be_visible()
    page.get_by_role("button", name="Keep editing", exact=True).click()
    page.locator("#save-button").click()
    expect(page.locator("#conflict-dialog")).to_be_visible()
    assert (live_workspace.root / "alpha.txt").read_text(encoding="utf-8") == "external edit"
    page.get_by_role("button", name="Overwrite with my edit", exact=True).click()
    expect(page.locator("#editor-message")).to_have_text("Saved")
    assert (live_workspace.root / "alpha.txt").read_text(encoding="utf-8") == "my local edit"


def test_failed_save_is_retryable_without_losing_text(page: Page) -> None:
    open_file(page, "alpha.txt")
    editor = page.get_by_role("textbox", name="File editor")
    editor.fill("retry this text")
    page.route(
        "**/api/v1/file",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({"error": {"code": "unavailable", "message": "Try again"}}),
        ),
        times=1,
    )
    page.locator("#save-button").click()
    expect(page.locator("#editor-message")).to_have_text("Try again")
    expect(editor).to_have_value("retry this text")
    expect(page.locator("#save-button")).to_be_enabled()
    page.locator("#save-button").click()
    expect(page.locator("#editor-message")).to_have_text("Saved")


def test_draft_restore_does_not_bypass_external_change_guard(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    open_file(page, "alpha.txt")
    page.get_by_role("textbox", name="File editor").fill("recover me")
    page.once("dialog", lambda dialog: dialog.accept())
    page.reload()
    (live_workspace.root / "alpha.txt").write_text("external checkpoint", encoding="utf-8")
    open_file(page, "alpha.txt")
    expect(page.locator("#draft-dialog")).to_be_visible()
    page.get_by_role("button", name="Restore draft", exact=True).click()
    page.locator("#save-button").click()
    expect(page.locator("#conflict-dialog")).to_be_visible()
    assert (live_workspace.root / "alpha.txt").read_text(encoding="utf-8") == "external checkpoint"


def test_recreation_conflict_does_not_overwrite_a_new_external_file(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    open_file(page, "alpha.txt")
    page.get_by_role("textbox", name="File editor").fill("my recreation")
    (live_workspace.root / "alpha.txt").unlink()
    page.locator("#save-button").click()
    expect(page.locator("#conflict-dialog")).to_be_visible()
    (live_workspace.root / "alpha.txt").write_text("racing recreation", encoding="utf-8")
    page.get_by_role("button", name="Overwrite with my edit", exact=True).click()
    expect(page.locator("#conflict-dialog")).to_be_visible()
    assert (live_workspace.root / "alpha.txt").read_text(encoding="utf-8") == "racing recreation"


def test_new_file_cancel_preserves_unsaved_document(page: Page) -> None:
    open_file(page, "alpha.txt")
    page.get_by_role("textbox", name="File editor").fill("keep before creating")
    page.get_by_role("button", name="New file", exact=True).click()
    page.get_by_role("textbox", name="Workspace path").fill("new.txt")
    dialogs: list[str] = []

    def cancel_discard(dialog: Dialog) -> None:
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.once("dialog", cancel_discard)
    page.get_by_role("button", name="Create", exact=True).click()
    assert dialogs == ["Discard unsaved changes?"]
    expect(page.get_by_role("heading", name="alpha.txt", exact=True)).to_be_visible()
    expect(page.get_by_role("textbox", name="File editor")).to_have_value("keep before creating")


def test_pending_save_blocks_navigation_but_allows_typing(page: Page) -> None:
    open_file(page, "alpha.txt")
    editor = page.get_by_role("textbox", name="File editor")
    editor.fill("save alpha")
    held = HeldRequests(page, "PUT")
    page.locator("#save-button").click()
    held.wait()
    page.get_by_role("treeitem").filter(has_text="beta.txt").click()
    expect(page.get_by_role("heading", name="alpha.txt", exact=True)).to_be_visible()
    expect(page.locator("#toast")).to_have_text("Wait for the current file operation to finish.")
    editor.fill("continue alpha")
    held.release()
    expect(page.locator("#save-button")).to_be_enabled()
    expect(editor).to_have_value("continue alpha")


@pytest.mark.parametrize("clock_enabled", [True], indirect=True)
def test_save_timeout_releases_controls_and_retains_draft(page: Page) -> None:
    open_file(page, "alpha.txt")
    page.get_by_role("textbox", name="File editor").fill("retain after timeout")
    held = HeldRequests(page, "PUT")
    page.locator("#save-button").click()
    held.wait()
    page.clock.fast_forward(15_001)
    expect(page.locator("#editor-message")).to_contain_text("timed out")
    expect(page.locator("#save-button")).to_be_enabled()
    assert page.evaluate(
        "JSON.parse(sessionStorage.getItem('samsarix-workspace-draft')).content"
    ) == ("retain after timeout")


def test_failed_create_keeps_previous_draft_and_retry_succeeds(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    open_file(page, "alpha.txt")
    page.get_by_role("textbox", name="File editor").fill("draft before create")
    page.get_by_role("button", name="New file", exact=True).click()
    page.get_by_role("textbox", name="Workspace path").fill("beta.txt")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Create", exact=True).click()
    expect(page.locator("#toast")).to_contain_text("already exists")
    assert (live_workspace.root / "beta.txt").read_text(encoding="utf-8") == "beta on disk\n"
    expect(page.get_by_role("textbox", name="File editor")).to_have_value("draft before create")
    page.get_by_role("textbox", name="Workspace path").fill("new.txt")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Create", exact=True).click()
    expect(page.get_by_role("heading", name="new.txt", exact=True)).to_be_visible()
    expect(page.get_by_role("textbox", name="File editor")).to_have_value("")
    assert (live_workspace.root / "alpha.txt").read_text(encoding="utf-8") == "alpha on disk\n"
    assert page.evaluate("sessionStorage.getItem('samsarix-workspace-draft')") is None


@pytest.mark.parametrize("status", [200, 400, 401])
def test_non_json_save_response_keeps_draft_and_connection(page: Page, status: int) -> None:
    open_file(page, "alpha.txt")
    editor = page.locator("#editor")
    editor.fill("retain after invalid response")
    page.route(
        "**/api/v1/file",
        lambda route: route.fulfill(status=status, content_type="text/plain", body="Not JSON"),
        times=1,
    )
    page.locator("#save-button").click()
    expect(page.locator("#editor-message")).to_contain_text(
        "invalid response" if status == 200 else f"Request failed ({status})"
    )
    expect(page.locator("#health-dot")).to_have_class("health-dot online")
    expect(editor).to_have_value("retain after invalid response")
    assert (
        page.evaluate("JSON.parse(sessionStorage.getItem('samsarix-workspace-draft')).content")
        == "retain after invalid response"
    )
    if status == 401:
        expect(page.locator("#token-dialog")).to_be_visible()
    else:
        expect(page.locator("#save-button")).to_be_enabled()
        page.locator("#save-button").click()
        expect(page.locator("#editor-message")).to_have_text("Saved")
        assert page.evaluate("sessionStorage.getItem('samsarix-workspace-draft')") is None


def test_conflict_overwrite_includes_typing_during_save(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    open_file(page, "alpha.txt")
    editor = page.get_by_role("textbox", name="File editor")
    editor.fill("submitted version")
    held = HeldRequests(page, "PUT")
    page.locator("#save-button").click()
    held.wait()
    editor.fill("newer local version")
    (live_workspace.root / "alpha.txt").write_text("external version", encoding="utf-8")
    held.release()
    expect(page.locator("#conflict-dialog")).to_be_visible()
    page.get_by_role("button", name="Overwrite with my edit", exact=True).click()
    held.wait()
    held.release()
    expect(page.locator("#editor-message")).to_have_text("Saved")
    assert (live_workspace.root / "alpha.txt").read_text(encoding="utf-8") == "newer local version"


def test_created_file_open_failure_does_not_label_discarded_text_saved(
    page: Page, live_workspace: RunningWorkspace
) -> None:
    open_file(page, "alpha.txt")
    page.get_by_role("textbox", name="File editor").fill("discarded original draft")
    page.route("**/api/v1/file?path=new.txt", lambda route: route.abort())
    page.get_by_role("button", name="New file", exact=True).click()
    page.get_by_role("textbox", name="Workspace path").fill("new.txt")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Create", exact=True).click()
    expect(page.locator("#editor-message")).to_contain_text("unavailable")
    expect(page.get_by_role("heading", name="Choose a file", exact=True)).to_be_visible()
    expect(page.locator("#editor")).to_be_hidden()
    assert (live_workspace.root / "new.txt").read_text(encoding="utf-8") == ""
    assert (live_workspace.root / "alpha.txt").read_text(encoding="utf-8") == "alpha on disk\n"

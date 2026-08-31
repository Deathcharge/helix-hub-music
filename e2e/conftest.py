"""Real loopback server and temporary on-disk data for browser acceptance tests."""

from __future__ import annotations

import os
import socket
import sysconfig
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Page, expect

import samsarix_workspace
from samsarix_workspace.api import AppSettings, create_app


@dataclass(frozen=True)
class RunningWorkspace:
    url: str
    root: Path


@pytest.fixture
def trash_bytes(request: pytest.FixtureRequest) -> int:
    return int(getattr(request, "param", 52_428_800))


@pytest.fixture
def history_bytes(request: pytest.FixtureRequest) -> int:
    return int(getattr(request, "param", 52_428_800))


@pytest.fixture
def live_workspace(
    tmp_path: Path, trash_bytes: int, history_bytes: int
) -> Iterator[RunningWorkspace]:
    if os.environ.get("SAMSARIX_TEST_INSTALLED") == "1":
        module = Path(samsarix_workspace.__file__).resolve()
        assert module.is_relative_to(Path(sysconfig.get_path("purelib")).resolve()), (
            f"Browser acceptance must exercise the installed wheel, not source: {module}"
        )
    root = tmp_path / "documents"
    root.mkdir()
    (root / "alpha.txt").write_text("alpha on disk\n", encoding="utf-8")
    (root / "beta.txt").write_text("beta on disk\n", encoding="utf-8")
    (root / "binary.bin").write_bytes(b"\xff\xfe")
    app = create_app(
        AppSettings(
            workspace_root=root, max_trash_bytes=trash_bytes, max_history_bytes=history_bytes
        )
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and worker.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "The loopback test server did not start"
            yield RunningWorkspace(f"http://127.0.0.1:{listener.getsockname()[1]}", root)
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            assert not worker.is_alive(), "The loopback test server did not stop"


@pytest.fixture
def clock_enabled(request: pytest.FixtureRequest) -> bool:
    return bool(getattr(request, "param", False))


@pytest.fixture(autouse=True)
def open_workspace(
    page: Page, live_workspace: RunningWorkspace, clock_enabled: bool
) -> Iterator[None]:
    errors: list[str] = []
    page.set_default_timeout(5_000)
    page.on("pageerror", lambda error: errors.append(str(error)))
    if clock_enabled:
        page.clock.install()
    page.goto(live_workspace.url)
    expect(page.get_by_role("treeitem").filter(has_text="alpha.txt")).to_be_visible()
    yield
    assert errors == [], f"Unexpected browser JavaScript errors: {errors}"

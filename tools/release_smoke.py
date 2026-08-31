"""Exercise an installed wheel from an isolated interpreter, without test extras."""

from __future__ import annotations

import json
import socket
import sys
import sysconfig
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

import uvicorn

import samsarix_workspace
from samsarix_workspace.api import AppSettings, create_app
from samsarix_workspace.cli import main


def smoke(expected_version: str) -> dict[str, object]:
    """Run a real loopback API recovery journey against disposable documents."""
    module = Path(samsarix_workspace.__file__).resolve()
    assert module.is_relative_to(Path(sysconfig.get_path("purelib")).resolve())
    assert samsarix_workspace.__version__ == expected_version
    with tempfile.TemporaryDirectory(prefix="samsarix-release-smoke-") as directory:
        root = Path(directory) / "documents"
        assert main(["init", str(root)]) == 0
        original = (root / "WELCOME.md").read_text(encoding="utf-8")
        app = create_app(AppSettings(workspace_root=root))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
            worker = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            worker.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and worker.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert server.started, "Loopback server did not start"
                base = f"http://127.0.0.1:{listener.getsockname()[1]}"
                opener = build_opener(ProxyHandler({}))

                def request(route: str, method: str = "GET", **payload: object) -> object:
                    body = json.dumps(payload).encode() if payload else None
                    query = Request(
                        base + route,
                        data=body,
                        method=method,
                        headers={"Content-Type": "application/json"},
                    )
                    with opener.open(query, timeout=10) as response:
                        return json.loads(response.read())

                with opener.open(base, timeout=10) as response:
                    assert b"Samsarix Workspace" in response.read()
                current = request("/api/v1/file?path=WELCOME.md")
                assert isinstance(current, dict)
                request(
                    "/api/v1/file",
                    "PUT",
                    path="WELCOME.md",
                    content="pilot edit\n",
                    expected_etag=current["file"]["etag"],
                )
                history = request("/api/v1/history?path=WELCOME.md")
                assert isinstance(history, dict)
                version = history["history"]["items"][0]
                request(
                    f"/api/v1/history/{version['id']}/restore", "POST", destination="recovered.md"
                )
                assert (root / "recovered.md").read_text(encoding="utf-8") == original
                assert (root / "WELCOME.md").read_text(encoding="utf-8") == "pilot edit\n"
                deleted = request("/api/v1/entry?path=recovered.md", "DELETE")
                assert isinstance(deleted, dict)
                assert not (root / "recovered.md").exists()
                request(
                    f"/api/v1/trash/{deleted['trash_item']['id']}/restore",
                    "POST",
                    destination="restored.md",
                )
                assert (root / "restored.md").read_text(encoding="utf-8") == original
            finally:
                server.should_exit = True
                worker.join(timeout=10)
                assert not worker.is_alive(), "Loopback server did not stop"
    return {
        "version": expected_version,
        "installed_import": True,
        "loopback_ui": True,
        "guarded_save": True,
        "history_copy": True,
        "trash_restore": True,
    }


if __name__ == "__main__":
    print(json.dumps(smoke(sys.argv[1]), sort_keys=True))

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from samsarix_workspace.api import AppSettings, create_app


def client_for(tmp_path: Path, **overrides: object) -> TestClient:
    values: dict[str, object] = {"allowed_hosts": ("testserver",)}
    values.update(overrides)
    settings = AppSettings(  # type: ignore[arg-type]
        workspace_root=tmp_path / "workspace", **values
    )
    return TestClient(create_app(settings))


def test_health_static_ui_and_security_headers(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        health = client.get("/healthz")
        assert health.json()["status"] == "ok"
        index = client.get("/")
        assert index.status_code == 200
        assert "Samsarix Workspace" in index.text
        assert index.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in index.headers["content-security-policy"]
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/openapi.json").json()["info"]["title"] == "Samsarix Workspace API"


def test_api_primary_journey(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        assert client.post("/api/v1/folders", json={"path": "notes"}).status_code == 201
        created = client.put("/api/v1/file", json={"path": "notes/idea.md", "content": "hello"})
        assert created.status_code == 200
        etag = created.json()["file"]["etag"]
        opened = client.get("/api/v1/file", params={"path": "notes/idea.md"})
        assert opened.json()["file"]["content"] == "hello"
        saved = client.put(
            "/api/v1/file",
            json={"path": "notes/idea.md", "content": "hello again", "expected_etag": etag},
        )
        assert saved.status_code == 200
        listing = client.get("/api/v1/files", params={"recursive": True}).json()
        assert [entry["path"] for entry in listing["entries"]] == ["notes", "notes/idea.md"]
        moved = client.post(
            "/api/v1/move",
            json={"source": "notes/idea.md", "destination": "notes/final.md"},
        )
        assert moved.json()["entry"]["path"] == "notes/final.md"
        terminal = client.post("/api/v1/terminal/execute", json={"command": "cat notes/final.md"})
        assert terminal.json()["output"] == "hello again"
        session_id = terminal.json()["session_id"]
        second = client.post(
            "/api/v1/terminal/execute", json={"command": "cd notes", "session_id": session_id}
        )
        assert second.json()["cwd"] == "/notes"
        deleted = client.delete("/api/v1/entry", params={"path": "notes", "recursive": True})
        assert deleted.json() == {"deleted": True}


def test_token_authentication_uses_standard_error_contract(tmp_path: Path) -> None:
    with client_for(tmp_path, token="correct horse battery staple") as client:
        missing = client.get("/api/v1/workspace")
        assert missing.status_code == 401
        assert missing.json() == {
            "error": {
                "code": "authentication_required",
                "message": "A bearer token is required.",
            }
        }
        wrong = client.get("/api/v1/workspace", headers={"Authorization": "Bearer incorrect"})
        assert wrong.status_code == 401
        authorized = client.get(
            "/api/v1/workspace",
            headers={"Authorization": "Bearer correct horse battery staple"},
        )
        assert authorized.status_code == 200
        assert client.get("/healthz").status_code == 200


def test_host_header_is_validated_before_routes(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        rejected = client.get("/healthz", headers={"Host": "attacker.example"})
        assert rejected.status_code == 400
        assert rejected.text == "Invalid host header"


def test_non_ascii_bearer_token_configuration_is_rejected(tmp_path: Path) -> None:
    settings = AppSettings(
        workspace_root=tmp_path / "workspace",
        token="correct-horse-battery-staple-é",
    )
    with pytest.raises(ValueError, match="only ASCII"):
        create_app(settings)


def test_validation_and_workspace_errors_are_stable(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        invalid = client.put("/api/v1/file", json={"path": "x", "content": "", "extra": 1})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "invalid_request"
        missing = client.get("/api/v1/file", params={"path": "missing"})
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"


def test_request_body_limits_reject_declared_and_streamed_oversize(tmp_path: Path) -> None:
    with client_for(tmp_path, max_request_bytes=80) as client:
        declared = client.put(
            "/api/v1/file", content=b"x" * 81, headers={"Content-Type": "application/json"}
        )
        assert declared.status_code == 413
        assert declared.json()["error"]["code"] == "request_too_large"

        def chunks() -> object:
            yield b'{"path":"a","content":"'
            yield b"x" * 100
            yield b'"}'

        streamed = client.put(
            "/api/v1/file",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )
        assert streamed.status_code == 413


def test_terminal_sessions_are_server_issued_bounded_and_expiring(
    tmp_path: Path,
) -> None:
    ticks = iter([100.0, 104.0, 106.0])
    settings = AppSettings(
        workspace_root=tmp_path / "workspace",
        max_sessions=1,
        session_ttl_seconds=5,
        allowed_hosts=("testserver",),
    )
    with TestClient(create_app(settings, session_clock=lambda: next(ticks))) as client:
        first = client.post("/api/v1/terminal/execute", json={"command": "pwd"}).json()
        invalid = client.post(
            "/api/v1/terminal/execute",
            json={"command": "pwd", "session_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"},
        )
        assert invalid.status_code == 400
        expired = client.post(
            "/api/v1/terminal/execute",
            json={"command": "pwd", "session_id": first["session_id"]},
        )
        assert expired.status_code == 404
        assert expired.json()["error"]["code"] == "session_expired"


def test_lru_evicts_old_terminal_session(tmp_path: Path) -> None:
    with client_for(tmp_path, max_sessions=1) as client:
        first = client.post("/api/v1/terminal/execute", json={"command": "pwd"}).json()
        second = client.post("/api/v1/terminal/execute", json={"command": "pwd"}).json()
        assert first["session_id"] != second["session_id"]
        response = client.post(
            "/api/v1/terminal/execute",
            json={"command": "pwd", "session_id": first["session_id"]},
        )
        assert response.status_code == 404

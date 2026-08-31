"""FastAPI application for Samsarix Workspace."""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from samsarix_workspace import __version__
from samsarix_workspace.shell import ShellResult, VirtualShell
from samsarix_workspace.workspace import Workspace, WorkspaceError


def normalize_host_authority(authority: str) -> str | None:
    """Return a case-folded host without an optional authority port."""

    value = authority.strip()
    if not value or any(character.isspace() for character in value):
        return None
    if value.startswith("["):
        closing_bracket = value.find("]")
        if closing_bracket <= 1:
            return None
        host = value[1:closing_bracket]
        suffix = value[closing_bracket + 1 :]
        if suffix and (not suffix.startswith(":") or not suffix[1:].isdigit()):
            return None
        return host.casefold()
    if "[" in value or "]" in value:
        return None
    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        if not host or not port.isdigit():
            return None
        value = host
    return value.casefold()


def normalize_allowed_hosts(hosts: Iterable[str]) -> tuple[str, ...]:
    """Validate and deduplicate an explicit host allowlist."""

    normalized: list[str] = []
    for configured in hosts:
        value = configured.strip()
        if "*" in value:
            raise ValueError("Allowed hosts must be explicit; wildcard hosts are not supported.")
        host = normalize_host_authority(value)
        if host is None:
            raise ValueError(f"Invalid allowed host: {configured!r}.")
        if host not in normalized:
            normalized.append(host)
    if not normalized:
        raise ValueError("At least one explicit allowed host is required.")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Runtime settings supplied by the CLI or embedding application."""

    workspace_root: Path
    token: str | None = None
    max_file_bytes: int = 1_048_576
    max_total_bytes: int = 52_428_800
    max_entries: int = 2_000
    max_trash_bytes: int = 52_428_800
    max_trash_items: int = 100
    max_trash_entries: int = 2_000
    max_request_bytes: int = 1_310_720
    max_search_bytes: int = 10_485_760
    max_sessions: int = 128
    session_ttl_seconds: int = 21_600
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "::1")

    @classmethod
    def from_environment(cls) -> AppSettings:
        root = Path(os.environ.get("SAMSARIX_WORKSPACE_ROOT", "."))
        token = os.environ.get("SAMSARIX_WORKSPACE_TOKEN") or None
        configured_hosts = os.environ.get("SAMSARIX_WORKSPACE_ALLOWED_HOSTS", "")
        allowed_hosts = tuple(host.strip() for host in configured_hosts.split(",") if host.strip())
        return cls(
            workspace_root=root,
            token=token,
            allowed_hosts=normalize_allowed_hosts(
                allowed_hosts or ("localhost", "127.0.0.1", "::1")
            ),
        )


class ExplicitTrustedHostMiddleware:
    """Reject requests whose normalized Host is not explicitly allowed."""

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        self.allowed_hosts = frozenset(normalize_allowed_hosts(allowed_hosts))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        authorities: list[str] = []
        for key, value in scope.get("headers", []):
            if key.lower() == b"host":
                authorities.append(value.decode("latin-1"))
        if (
            len(authorities) != 1
            or normalize_host_authority(authorities[0]) not in self.allowed_hosts
        ):
            response = PlainTextResponse("Invalid host header", status_code=400)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP bodies while the ASGI server is still streaming them."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                declared = int(content_length)
            except ValueError:
                await self._reject(send, "invalid_content_length")
                return
            if declared > self.max_bytes:
                await self._reject(send, "request_too_large")
                return

        received = 0
        response_started = False
        too_large = False
        replacement_sent = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            if too_large:
                return {"type": "http.request", "body": b"", "more_body": False}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started, replacement_sent
            if too_large:
                if not replacement_sent:
                    await self._reject(send, "request_too_large")
                    replacement_sent = True
                    response_started = True
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, limited_receive, tracked_send)
        if too_large and not response_started:
            await self._reject(send, "request_too_large")

    @staticmethod
    async def _reject(send: Send, code: str) -> None:
        message = (
            "Content-Length must be a valid integer."
            if code == "invalid_content_length"
            else "The request body exceeds the configured limit."
        )
        body = json.dumps({"error": {"code": code, "message": message}}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 400 if code == "invalid_content_length" else 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WriteFileRequest(StrictModel):
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=1_048_576)
    expected_etag: str | None = Field(default=None, min_length=64, max_length=64)
    create_only: bool = False


class FolderRequest(StrictModel):
    path: str = Field(min_length=1, max_length=512)


class MoveRequest(StrictModel):
    source: str = Field(min_length=1, max_length=512)
    destination: str = Field(min_length=1, max_length=512)


class RestoreRequest(StrictModel):
    destination: str | None = Field(default=None, min_length=1, max_length=512)


class TerminalRequest(StrictModel):
    command: str = Field(max_length=2_048)
    session_id: str | None = Field(default=None, min_length=36, max_length=36)


class ShellSessions:
    """A bounded, expiring LRU of server-issued virtual-shell sessions."""

    def __init__(
        self,
        workspace: Workspace,
        max_sessions: int,
        ttl_seconds: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.workspace = workspace
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._sessions: OrderedDict[str, tuple[VirtualShell, float]] = OrderedDict()
        self._lock = threading.RLock()

    def _acquire(self, session_id: str | None) -> tuple[str, VirtualShell]:
        now = self._clock()
        expired = [
            key for key, (_, touched) in self._sessions.items() if now - touched > self.ttl_seconds
        ]
        for key in expired:
            self._sessions.pop(key, None)

        if session_id is not None:
            try:
                uuid.UUID(session_id)
            except ValueError as exc:
                raise WorkspaceError(
                    "invalid_session", "The terminal session ID is invalid."
                ) from exc
            existing = self._sessions.pop(session_id, None)
            if existing is None:
                raise WorkspaceError(
                    "session_expired", "The terminal session expired; start a new one.", 404
                )
            shell, _ = existing
            self._sessions[session_id] = (shell, now)
            return session_id, shell

        while len(self._sessions) >= self.max_sessions:
            self._sessions.popitem(last=False)
        new_id = str(uuid.uuid4())
        shell = VirtualShell(self.workspace)
        self._sessions[new_id] = (shell, now)
        return new_id, shell

    def execute(self, session_id: str | None, command: str) -> tuple[str, ShellResult]:
        """Acquire a session and serialize its state mutation with LRU updates."""

        with self._lock:
            resolved_id, shell = self._acquire(session_id)
            return resolved_id, shell.execute(command)


def create_app(
    settings: AppSettings | None = None,
    *,
    session_clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    """Create an isolated application instance for a workspace root."""

    resolved_settings = settings or AppSettings.from_environment()
    if resolved_settings.token is not None and not resolved_settings.token.isascii():
        raise ValueError("SAMSARIX_WORKSPACE_TOKEN must contain only ASCII characters")
    allowed_hosts = normalize_allowed_hosts(resolved_settings.allowed_hosts)
    workspace = Workspace(
        resolved_settings.workspace_root,
        max_file_bytes=resolved_settings.max_file_bytes,
        max_total_bytes=resolved_settings.max_total_bytes,
        max_entries=resolved_settings.max_entries,
        max_trash_bytes=resolved_settings.max_trash_bytes,
        max_trash_items=resolved_settings.max_trash_items,
        max_trash_entries=resolved_settings.max_trash_entries,
    )
    sessions = ShellSessions(
        workspace,
        resolved_settings.max_sessions,
        resolved_settings.session_ttl_seconds,
        clock=session_clock,
    )
    app = FastAPI(
        title="Samsarix Workspace API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
    )
    app.state.workspace = workspace
    app.state.settings = resolved_settings

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    # Both guards run outside request parsing. The host gate is added last so an
    # untrusted authority is rejected before the request body is consumed.
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=resolved_settings.max_request_bytes)
    app.add_middleware(
        ExplicitTrustedHostMiddleware,
        allowed_hosts=allowed_hosts,
    )

    @app.exception_handler(WorkspaceError)
    async def workspace_error_handler(_request: Request, exc: WorkspaceError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "The request did not match the API contract.",
                    "details": details,
                }
            },
            status_code=422,
        )

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = resolved_settings.token
        if expected is None:
            return
        prefix = "Bearer "
        if not authorization or not authorization.startswith(prefix):
            raise WorkspaceError("authentication_required", "A bearer token is required.", 401)
        supplied = authorization[len(prefix) :]
        if not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
            raise WorkspaceError("authentication_failed", "The bearer token is not valid.", 401)

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authorize)])

    @router.get("/workspace")
    def workspace_summary() -> dict[str, Any]:
        summary = workspace.summary()
        summary["limits"]["max_search_bytes"] = resolved_settings.max_search_bytes
        return {"workspace": summary, "version": __version__}

    @router.get("/files")
    def list_files(
        path: Annotated[str, Query(max_length=512)] = "",
        recursive: bool = False,
    ) -> dict[str, Any]:
        entries = workspace.list_entries(path, recursive=recursive)
        return {
            "path": workspace.normalize(path),
            "entries": [entry.to_dict() for entry in entries],
        }

    @router.get("/file")
    def read_file(path: Annotated[str, Query(min_length=1, max_length=512)]) -> dict[str, Any]:
        return {"file": workspace.read_file(path).to_dict()}

    @router.get("/search")
    def search_files(
        q: Annotated[str, Query(min_length=1, max_length=256)],
        path: Annotated[str, Query(max_length=512)] = "",
        case_sensitive: bool = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> dict[str, Any]:
        report = workspace.search_text(
            q,
            path,
            case_sensitive=case_sensitive,
            limit=limit,
            max_scan_bytes=resolved_settings.max_search_bytes,
        )
        return {"search": report.to_dict()}

    @router.put("/file")
    def write_file(payload: WriteFileRequest) -> dict[str, Any]:
        document = workspace.write_file(
            payload.path,
            payload.content,
            expected_etag=payload.expected_etag,
            create_only=payload.create_only,
        )
        return {"file": document.to_dict()}

    @router.post("/folders", status_code=201)
    def create_folder(payload: FolderRequest) -> dict[str, Any]:
        return {"entry": workspace.make_directory(payload.path).to_dict()}

    @router.post("/move")
    def move_entry(payload: MoveRequest) -> dict[str, Any]:
        return {"entry": workspace.move(payload.source, payload.destination).to_dict()}

    @router.delete("/entry")
    def delete_entry(
        path: Annotated[str, Query(min_length=1, max_length=512)],
        recursive: bool = False,
        permanent: bool = False,
        expected_etag: Annotated[str | None, Query(min_length=64, max_length=64)] = None,
    ) -> dict[str, Any]:
        item = workspace.delete(
            path, recursive=recursive, permanent=permanent, expected_etag=expected_etag
        )
        return {"deleted": True, "permanent": permanent, "trash_item": item}

    @router.get("/trash")
    def list_trash() -> dict[str, Any]:
        return {"trash": workspace.trash_report()}

    @router.post("/trash/{trash_id}/restore")
    def restore_item(trash_id: str, payload: RestoreRequest) -> dict[str, Any]:
        return workspace.restore(trash_id, payload.destination)

    @router.delete("/trash/{trash_id}")
    def purge_item(trash_id: str, confirm: bool = False) -> dict[str, bool]:
        if not confirm:
            raise WorkspaceError(
                "confirmation_required", "Confirm permanent deletion of this Trash item."
            )
        workspace.purge(trash_id)
        return {"purged": True}

    @router.post("/terminal/execute")
    def execute_terminal(payload: TerminalRequest) -> dict[str, Any]:
        session_id, result = sessions.execute(payload.session_id, payload.command)
        return {
            "session_id": session_id,
            "output": result.output,
            "cwd": "/" + result.cwd,
            "exit_code": result.exit_code,
            "clear": result.clear,
        }

    app.include_router(router)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "samsarix-workspace", "version": __version__}

    static_root = Path(__file__).with_name("static")
    app.mount("/assets", StaticFiles(directory=static_root), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_root / "index.html")

    return app

"""Command-line interface for Samsarix Workspace."""

from __future__ import annotations

import argparse
import ipaddress
import os
import sys
import threading
import webbrowser
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from samsarix_workspace import __version__
from samsarix_workspace.api import AppSettings, create_app

WELCOME = """# Welcome to Samsarix Workspace

This folder is yours. Create and edit UTF-8 text files in the browser, or use
the virtual terminal for bounded file operations. Run `help` in the terminal to
see its command allowlist.

The terminal does not execute operating-system commands.
"""


def _is_loopback(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="samsarix-workspace",
        description="A local-first browser workspace for text files and safe virtual commands.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init", help="Initialize a workspace folder")
    initialize.add_argument("path", nargs="?", default=".", help="Workspace folder (default: .)")

    serve = commands.add_parser("serve", help="Run the local browser application")
    serve.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("SAMSARIX_WORKSPACE_ROOT", "."),
        help="Workspace folder (default: SAMSARIX_WORKSPACE_ROOT or .)",
    )
    serve.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8765, help="TCP port (default: 8765)")
    serve.add_argument("--open", action="store_true", help="Open the workspace in a browser")
    serve.add_argument(
        "--log-level", choices=["critical", "error", "warning", "info"], default="info"
    )
    return parser


def _initialize(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        print(f"error: {path} is not a directory", file=sys.stderr)
        return 1
    welcome = path / "WELCOME.md"
    if welcome.exists():
        print(f"Workspace already initialized: {path.resolve()}")
        return 0
    welcome.write_text(WELCOME, encoding="utf-8")
    print(f"Initialized Samsarix Workspace: {path.resolve()}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return _initialize(Path(args.path).expanduser())

    token = os.environ.get("SAMSARIX_WORKSPACE_TOKEN") or None
    if not 1 <= args.port <= 65_535:
        parser.error("--port must be between 1 and 65535")
    if not _is_loopback(args.host):
        if token is None:
            parser.error(
                "non-loopback binding requires SAMSARIX_WORKSPACE_TOKEN; "
                "a reverse proxy with TLS is also strongly recommended"
            )
        if len(token) < 20:
            parser.error("SAMSARIX_WORKSPACE_TOKEN must contain at least 20 characters")

    root = Path(args.path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    app = create_app(AppSettings(workspace_root=root, token=token))
    url_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
    url = f"http://{url_host}:{args.port}"
    print(f"Samsarix Workspace: {url}")
    print(f"Workspace folder: {root}")
    if token:
        print("Bearer-token protection: enabled")
    else:
        print("Bearer-token protection: disabled (loopback only)")
    if args.open:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0

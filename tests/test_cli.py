from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from samsarix_workspace import cli


def test_init_is_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "project"
    assert cli.main(["init", str(target)]) == 0
    assert "Welcome to Samsarix Workspace" in (target / "WELCOME.md").read_text(encoding="utf-8")
    assert cli.main(["init", str(target)]) == 0
    assert "already initialized" in capsys.readouterr().out


def test_init_rejects_an_existing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "not-a-folder"
    target.write_text("content", encoding="utf-8")
    assert cli.main(["init", str(target)]) == 1
    assert "is not a directory" in capsys.readouterr().err


def test_init_preserves_a_file_created_during_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "project"
    target.mkdir()
    welcome = target / "WELCOME.md"
    original_exists = Path.exists
    inserted = False

    def concurrent_exists(path: Path) -> bool:
        nonlocal inserted
        if path == welcome and not inserted:
            inserted = True
            welcome.write_text("another writer's document", encoding="utf-8")
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", concurrent_exists)
    assert cli.main(["init", str(target)]) == 0
    assert inserted
    assert welcome.read_text(encoding="utf-8") == "another writer's document"
    assert "already initialized" in capsys.readouterr().out


def test_init_rejects_dangling_welcome_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "project"
    target.mkdir()
    outside = tmp_path / "outside.txt"
    welcome = target / "WELCOME.md"
    try:
        welcome.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available on this filesystem")
    assert cli.main(["init", str(target)]) == 1
    assert not outside.exists()
    assert welcome.is_symlink()
    assert "error:" in capsys.readouterr().err


def test_init_rejects_a_welcome_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "WELCOME.md").mkdir()
    assert cli.main(["init", str(tmp_path)]) == 1
    assert (tmp_path / "WELCOME.md").is_dir()
    assert "regular file" in capsys.readouterr().err


def test_init_handles_a_failed_flush_without_leaving_partial_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failed_sync(_fd: int) -> None:
        raise OSError("simulated full disk")

    monkeypatch.setattr(cli.os, "fsync", failed_sync)
    assert cli.main(["init", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []
    assert "error:" in capsys.readouterr().err


def test_init_refuses_unowned_recovery_storage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    private = tmp_path / ".samsarix-history"
    private.mkdir()
    assert cli.main(["init", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == [private]
    assert "error:" in capsys.readouterr().err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        cli.main(["--version"])
    assert "samsarix-workspace 0.4.1" in capsys.readouterr().out


@pytest.mark.parametrize("host", ["0.0.0.0", "example.test", "::"])
def test_remote_binding_requires_token(
    host: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SAMSARIX_WORKSPACE_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="2"):
        cli.main(["serve", "--host", host])
    assert "requires SAMSARIX_WORKSPACE_TOKEN" in capsys.readouterr().err


def test_remote_binding_requires_long_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SAMSARIX_WORKSPACE_TOKEN", "too-short")
    with pytest.raises(SystemExit, match="2"):
        cli.main(["serve", "--host", "192.0.2.4"])
    assert "at least 20 characters" in capsys.readouterr().err


def test_invalid_port_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        cli.main(["serve", "--port", "0"])
    assert "between 1 and 65535" in capsys.readouterr().err


def test_wildcard_binding_requires_an_allowed_host(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SAMSARIX_WORKSPACE_TOKEN", "a-secure-token-with-entropy")
    with pytest.raises(SystemExit, match="2"):
        cli.main(["serve", "--host", "0.0.0.0"])
    assert "requires at least one explicit --allowed-host" in capsys.readouterr().err


@pytest.mark.parametrize("allowed_host", ["*", "*.example.test"])
def test_wildcard_binding_rejects_wildcard_allowed_hosts(
    allowed_host: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SAMSARIX_WORKSPACE_TOKEN", "a-secure-token-with-entropy")
    with pytest.raises(SystemExit, match="2"):
        cli.main(["serve", "--host", "0.0.0.0", "--allowed-host", allowed_host])
    assert "wildcard hosts are not supported" in capsys.readouterr().err


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_serve_loopback_builds_app_and_runs(
    host: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[SimpleNamespace] = []

    def fake_run(app: object, **kwargs: object) -> None:
        calls.append(SimpleNamespace(app=app, kwargs=kwargs))

    monkeypatch.delenv("SAMSARIX_WORKSPACE_TOKEN", raising=False)
    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    assert cli.main(["serve", str(tmp_path), "--host", host, "--port", "9876"]) == 0
    assert calls[0].kwargs == {"host": host, "port": 9876, "log_level": "info"}
    assert "Bearer-token protection: disabled" in capsys.readouterr().out


def test_serve_remote_with_token_and_open_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[str] = []
    served_apps: list[object] = []
    monkeypatch.setenv("SAMSARIX_WORKSPACE_TOKEN", "a-secure-token-with-entropy")
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **_kwargs: served_apps.append(app))
    monkeypatch.setattr(
        cli.threading, "Timer", lambda _delay, fn, args: SimpleNamespace(start=lambda: fn(*args))
    )
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))
    assert (
        cli.main(
            [
                "serve",
                str(tmp_path),
                "--host",
                "0.0.0.0",
                "--allowed-host",
                "Workspace.Example",
                "--open",
            ]
        )
        == 0
    )
    assert opened == ["http://127.0.0.1:8765"]
    assert "workspace.example" in served_apps[0].state.settings.allowed_hosts
    assert "Bearer-token protection: enabled" in capsys.readouterr().out


def test_serve_refuses_unowned_recovery_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    private = tmp_path / ".samsarix-trash"
    private.mkdir()
    (private / "mine").write_text("keep")
    with pytest.raises(SystemExit, match="2"):
        cli.main(["serve", str(tmp_path)])
    assert "Inspect or rename it outside the app" in capsys.readouterr().err
    assert (private / "mine").read_text() == "keep"

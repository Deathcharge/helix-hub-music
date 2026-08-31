from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest

from tools import release_evidence as release


def bundle(path: Path) -> dict[str, Any]:
    (path / "artifact.txt").write_text("release bytes", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "kind": "unsigned-release-evidence",
        "artifacts": {"artifact.txt": release.file_digest(path / "artifact.txt")},
    }
    release.write_json(path / release.MANIFEST, manifest)
    return manifest


def rewrite_manifest(path: Path, manifest: dict[str, Any]) -> None:
    (path / release.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


def test_verify_reads_integrity_without_executing_artifacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = bundle(tmp_path)
    assert release.verify(tmp_path) == expected
    assert release.main(["verify", str(tmp_path)]) == 0
    assert "publisher identity is not authenticated" in capsys.readouterr().out


@pytest.mark.parametrize("mutation", ["changed", "missing", "extra-file", "extra-directory"])
def test_verify_rejects_modified_or_incomplete_bundles(tmp_path: Path, mutation: str) -> None:
    bundle(tmp_path)
    artifact = tmp_path / "artifact.txt"
    if mutation == "changed":
        artifact.write_text("changed bytes", encoding="utf-8")
    elif mutation == "missing":
        artifact.unlink()
    elif mutation == "extra-file":
        (tmp_path / "extra.txt").write_text("unlisted", encoding="utf-8")
    else:
        (tmp_path / "unlisted").mkdir()
    with pytest.raises((release.ReleaseError, OSError)):
        release.verify(tmp_path)


@pytest.mark.parametrize("name", ["../outside", "/absolute", "a\\b", "C:stream", release.MANIFEST])
def test_verify_rejects_nonlocal_artifact_names(tmp_path: Path, name: str) -> None:
    manifest = bundle(tmp_path)
    manifest["artifacts"] = {name: manifest["artifacts"]["artifact.txt"]}
    rewrite_manifest(tmp_path, manifest)
    with pytest.raises(release.ReleaseError, match="Invalid artifact"):
        release.verify(tmp_path)


@pytest.mark.parametrize("schema", [None, True, 1.0, 2, "1"])
def test_verify_requires_supported_integer_schema(tmp_path: Path, schema: object) -> None:
    manifest = bundle(tmp_path)
    manifest["schema_version"] = schema
    rewrite_manifest(tmp_path, manifest)
    with pytest.raises(release.ReleaseError, match="Unsupported"):
        release.verify(tmp_path)


@pytest.mark.parametrize("mode", ["symlink", "hardlink", "directory"])
def test_verify_rejects_linked_or_nonregular_artifacts(tmp_path: Path, mode: str) -> None:
    bundle(tmp_path)
    artifact = tmp_path / "artifact.txt"
    original = artifact.read_bytes()
    artifact.unlink()
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.write_bytes(original)
    try:
        if mode == "symlink":
            artifact.symlink_to(outside)
        elif mode == "hardlink":
            os.link(outside, artifact)
        else:
            artifact.mkdir()
    except OSError:
        pytest.skip("requested filesystem link is unavailable")
    with pytest.raises(release.ReleaseError, match="regular artifact"):
        release.verify(tmp_path)
    assert outside.read_bytes() == original


def test_json_and_artifact_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "large.json"
    target.write_text('{"data":"long value"}', encoding="utf-8")
    monkeypatch.setattr(release, "MAX_JSON_BYTES", 4)
    with pytest.raises(release.ReleaseError, match="JSON artifact is too large"):
        release.read_json(target)
    monkeypatch.setattr(release, "MAX_ARTIFACT_BYTES", 8)
    with pytest.raises(release.ReleaseError, match="bounded"):
        release.file_digest(target)


def test_json_requires_object_and_exclusive_output(tmp_path: Path) -> None:
    target = tmp_path / "list.json"
    target.write_text("[]", encoding="utf-8")
    with pytest.raises(release.ReleaseError, match="must be an object"):
        release.read_json(target)
    with pytest.raises(FileExistsError):
        release.write_json(target, {"overwrite": True})
    assert target.read_text() == "[]"


def installation_report() -> dict[str, Any]:
    return {
        "version": "1",
        "install": [
            {
                "metadata": {"name": name, "version": version},
                "download_info": {
                    "url": "file:///private/local/path.whl",
                    "archive_info": {"hashes": {"sha256": "a" * 64}},
                },
            }
            for name, version in [(release.PACKAGE, "0.4.1"), ("a_dependency", "1.0")]
        ],
    }


def test_runtime_inventory_omits_private_urls_and_normalizes_names() -> None:
    result = release.inventory(installation_report())
    assert result == {release.PACKAGE: ("0.4.1", "a" * 64), "a-dependency": ("1.0", "a" * 64)}
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("mutation", ["version", "digest", "duplicate", "missing", "name"])
def test_runtime_inventory_rejects_incomplete_or_ambiguous_evidence(mutation: str) -> None:
    report = installation_report()
    if mutation == "version":
        report["version"] = "future"
    elif mutation == "digest":
        report["install"][0]["download_info"]["archive_info"]["hashes"] = {}
    elif mutation == "duplicate":
        report["install"].append(report["install"][0])
    elif mutation == "missing":
        report["install"].pop(0)
    else:
        report["install"][0]["metadata"]["name"] = "bad\n--requirement evil"
    with pytest.raises(release.ReleaseError):
        release.inventory(report)


def valid_bom() -> dict[str, Any]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {"component": {"name": release.PACKAGE, "version": "0.4.1"}},
        "components": [{"name": "a-dependency", "version": "1.0"}],
    }


def test_bom_matches_only_the_installed_application_runtime() -> None:
    release.validate_bom(valid_bom(), release.inventory(installation_report()))


@pytest.mark.parametrize("mutation", ["root", "metadata", "missing", "extra", "duplicate", "shape"])
def test_bom_rejects_wrong_version_missing_dependencies_and_tool_contamination(
    mutation: str,
) -> None:
    bom = valid_bom()
    if mutation == "root":
        bom["metadata"]["component"]["version"] = "0.0.0"
    elif mutation == "metadata":
        bom["metadata"] = None
    elif mutation == "missing":
        bom["components"] = []
    elif mutation == "extra":
        bom["components"].append({"name": "pytest", "version": "9.0"})
    elif mutation == "duplicate":
        bom["components"].append(bom["components"][0])
    else:
        bom["components"] = [None]
    with pytest.raises(release.ReleaseError):
        release.validate_bom(bom, release.inventory(installation_report()))


def write_archive(path: Path, name: str, *, link: bool = False) -> None:
    with tarfile.open(path, "w") as archive:
        item = tarfile.TarInfo(name)
        if link:
            item.type = tarfile.SYMTYPE
            item.linkname = "../outside"
            archive.addfile(item)
        else:
            item.size = 4
            archive.addfile(item, io.BytesIO(b"data"))


@pytest.mark.parametrize("name", ["../outside", "/absolute", "a\\b", "C:stream"])
def test_source_archive_cannot_extract_outside_snapshot(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "source.tar"
    write_archive(archive, name)
    destination = tmp_path / "snapshot"
    destination.mkdir()
    with pytest.raises(release.ReleaseError, match="unsafe member"):
        release.safe_extract(archive, destination)
    assert list(destination.iterdir()) == []


def test_source_archive_rejects_links_and_extracts_regular_files(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar"
    destination = tmp_path / "snapshot"
    destination.mkdir()
    write_archive(archive, "link", link=True)
    with pytest.raises(release.ReleaseError, match="link"):
        release.safe_extract(archive, destination)
    write_archive(archive, "nested/file.txt")
    release.safe_extract(archive, destination)
    assert (destination / "nested/file.txt").read_bytes() == b"data"


def test_build_refuses_dirty_source_without_creating_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "run", lambda *_args, **_kwargs: " M source.py\n")
    with pytest.raises(release.ReleaseError, match="Commit or set aside"):
        release.build_bundle(tmp_path / "out", tmp_path)
    assert not (tmp_path / "out").exists()


def test_build_refuses_existing_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["", "a" * 40, "b" * 40, "1"])
    monkeypatch.setattr(release, "run", lambda *_args, **_kwargs: next(answers))
    (tmp_path / "mine.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        release.build_bundle(tmp_path, tmp_path)
    assert (tmp_path / "mine.txt").read_text() == "preserve"


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing"])
def test_child_failures_are_bounded_and_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def failed_run(*args: object, **kwargs: object) -> None:
        assert kwargs["timeout"] == 300
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["capture_output"] is True
        assert "shell" not in kwargs
        if failure == "exit":
            raise subprocess.CalledProcessError(1, "tool", stderr="simulated error")
        if failure == "timeout":
            raise subprocess.TimeoutExpired("tool", 300)
        raise FileNotFoundError("missing tool")

    monkeypatch.setattr(release.subprocess, "run", failed_run)
    with pytest.raises(release.ReleaseError):
        release.run(["tool", "literal;argument"], tmp_path)


def test_verify_failure_has_nonzero_cli_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert release.main(["verify", str(tmp_path)]) == 1
    assert "Release evidence failed" in capsys.readouterr().err

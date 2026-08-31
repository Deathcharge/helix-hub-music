"""Build unsigned release evidence, or verify bundle checksums without dependencies.

Maintainer build mode executes trusted repository code and fetches tools/dependencies
from PyPI. Verify mode only reads files; matching hashes do not authenticate a publisher.
"""

# The CLI may be copied beside untrusted bundle files. Only built-in sys may be
# imported before this check, including no __future__ import. Trusted in-process
# callers (tests/maintainer code) retain the normal importable helper interface.
import sys

if __name__ == "__main__" and not sys.flags.isolated:
    raise SystemExit(
        "Release evidence requires Python isolated mode (-I). "
        "Run: python -I <trusted-verifier.py> <build|verify> <directory>"
    )

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
import venv
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, TypedDict

PACKAGE = "samsarix-workspace"
MANIFEST = "release-manifest.json"
MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024


class ReleaseError(Exception):
    """An evidence gate failed; no successful release should be inferred."""


class ArtifactDigest(TypedDict):
    size: int
    sha256: str


def run(argv: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> str:
    """Run a fixed tool command without a shell or inherited stdin."""
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=300,
        )
    except subprocess.CalledProcessError as exc:
        raise ReleaseError(f"Tool failed: {argv[0]}\n{(exc.stderr or '')[-3000:]}") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseError(f"Tool unavailable or timed out: {argv[0]}") from exc
    return result.stdout


def normal_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def file_digest(path: Path) -> ArtifactDigest:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or getattr(metadata, "st_file_attributes", 0) & 0x400
        or metadata.st_size > MAX_ARTIFACT_BYTES
    ):
        raise ReleaseError(f"Not a bounded, unlinked regular artifact: {path.name}")
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    count = 0
    with os.fdopen(descriptor, "rb") as source:
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ReleaseError(f"Artifact changed type while opening: {path.name}")
        for block in iter(lambda: source.read(1024 * 1024), b""):
            count += len(block)
            if count > MAX_ARTIFACT_BYTES:
                raise ReleaseError(f"Artifact grew past size limit: {path.name}")
            digest.update(block)
    if count != metadata.st_size:
        raise ReleaseError(f"Artifact changed size while reading: {path.name}")
    return {"size": metadata.st_size, "sha256": digest.hexdigest()}


def read_json(path: Path) -> dict[str, Any]:
    info = file_digest(path)
    if info["size"] > MAX_JSON_BYTES:
        raise ReleaseError(f"JSON artifact is too large: {path.name}")
    with path.open("rb") as source:
        content = source.read(MAX_JSON_BYTES + 1)
    if len(content) > MAX_JSON_BYTES:
        raise ReleaseError(f"JSON artifact grew past size limit: {path.name}")
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ReleaseError(f"JSON artifact must be an object: {path.name}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as target:
        target.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n")


def safe_extract(archive: Path, destination: Path) -> None:
    """Only regular files/directories from the pinned Git archive may be extracted."""
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if len(members) > 10_000 or sum(item.size for item in members) > 1024**3:
            raise ReleaseError("Source snapshot exceeds release-tool bounds")
        for item in members:
            name = PurePosixPath(item.name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in item.name
                or ":" in item.name
                or not (item.isfile() or item.isdir())
            ):
                raise ReleaseError("Source snapshot contains a link or unsafe member")
        if not hasattr(tarfile, "data_filter"):
            raise ReleaseError("Release builds require Python 3.11.8+ or 3.12+")
        source.extractall(destination, members=members, filter="data")


def inventory(report: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Select only names, versions, and wheel hashes; omit URLs and host paths."""
    if report.get("version") != "1" or not isinstance(report.get("install"), list):
        raise ReleaseError("Unsupported pip installation report")
    result: dict[str, tuple[str, str]] = {}
    for item in report["install"]:
        try:
            name = normal_name(item["metadata"]["name"])
            version = item["metadata"]["version"]
            digest = item["download_info"]["archive_info"]["hashes"]["sha256"]
        except (KeyError, TypeError) as exc:
            raise ReleaseError("Incomplete installed-wheel evidence") from exc
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name)
            or not isinstance(version, str)
            or not re.fullmatch(r"[A-Za-z0-9.!+_-]+", version)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or name in result
        ):
            raise ReleaseError("Invalid or duplicate installed-wheel identity")
        result[name] = (version, digest)
    if PACKAGE not in result:
        raise ReleaseError("Runtime inventory does not contain Samsarix Workspace")
    return result


def validate_bom(bom: dict[str, Any], packages: dict[str, tuple[str, str]]) -> None:
    metadata = bom.get("metadata")
    root = metadata.get("component") if isinstance(metadata, dict) else None
    if (
        not isinstance(root, dict)
        or bom.get("bomFormat") != "CycloneDX"
        or bom.get("specVersion") != "1.6"
        or root.get("name") != PACKAGE
        or root.get("version") != packages[PACKAGE][0]
    ):
        raise ReleaseError("SBOM does not describe this application version")
    components = bom.get("components")
    if not isinstance(components, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not isinstance(item.get("version"), str)
        for item in components
    ):
        raise ReleaseError("Invalid SBOM component inventory")
    actual = {normal_name(item["name"]): item["version"] for item in components}
    expected = {name: value[0] for name, value in packages.items() if name != PACKAGE}
    if actual != expected or len(actual) != len(components):
        raise ReleaseError("SBOM components differ from the clean installed runtime")


def verify(directory: Path) -> dict[str, Any]:
    """Verify integrity only, never execute the bundle or trust its claimed identity."""
    manifest = read_json(directory / MANIFEST)
    if (
        type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
        or manifest.get("kind") != "unsigned-release-evidence"
    ):
        raise ReleaseError("Unsupported release manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not 1 <= len(artifacts) <= 20:
        raise ReleaseError("Invalid artifact inventory")
    for name, expected in artifacts.items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
            or name == MANIFEST
            or not isinstance(expected, dict)
            or type(expected.get("size")) is not int
            or not isinstance(expected.get("sha256"), str)
        ):
            raise ReleaseError("Invalid artifact name or digest")
        if file_digest(directory / name) != expected:
            raise ReleaseError(f"Artifact checksum/size mismatch: {name}")
    if {item.name for item in directory.iterdir()} != {*artifacts, MANIFEST}:
        raise ReleaseError("Bundle contains unlisted files or directories")
    return manifest


def build_bundle(directory: Path, repository: Path) -> dict[str, Any]:
    """Build an exact clean Git snapshot and produce a validated local evidence bundle."""
    if run(["git", "status", "--porcelain", "--untracked-files=normal"], repository).strip():
        raise ReleaseError("Commit or set aside changes before building release evidence")
    revision = run(["git", "rev-parse", "HEAD"], repository).strip()
    tree = run(["git", "rev-parse", "HEAD^{tree}"], repository).strip()
    epoch = run(["git", "show", "-s", "--format=%ct", revision], repository).strip()
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    # Ignore package-index environment/configuration for this public-PyPI workflow.
    env = {key: value for key, value in os.environ.items() if not key.startswith("PIP_")}
    env.update(
        {
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_INDEX_URL": "https://pypi.org/simple",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "SOURCE_DATE_EPOCH": epoch,
        }
    )
    with tempfile.TemporaryDirectory(prefix="samsarix-release-build-") as temporary:
        working = Path(temporary)
        archive = working / "source.tar"
        run(["git", "archive", revision, "--format=tar", "-o", str(archive)], repository)
        source = working / "source"
        source.mkdir()
        safe_extract(archive, source)
        with (source / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]
        version = str(project["version"])
        if project["name"] != PACKAGE or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", version):
            raise ReleaseError("Unexpected project identity or version")
        print(f"Building {PACKAGE} {version} from {revision}", flush=True)
        run(
            [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(directory)],
            source,
            env=env,
        )
        wheel = directory / f"samsarix_workspace-{version}-py3-none-any.whl"
        sdist = directory / f"samsarix_workspace-{version}.tar.gz"
        if {item.name for item in directory.iterdir()} != {wheel.name, sdist.name}:
            raise ReleaseError("Build did not produce exactly the expected wheel and sdist")
        run([sys.executable, "-m", "twine", "check", str(wheel), str(sdist)], working, env=env)
        runtime = working / "runtime"
        venv.EnvBuilder(with_pip=False).create(runtime)
        python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        pip = [sys.executable, "-m", "pip", "--python", str(python), "--isolated"]
        install_report = working / "install.json"
        print("Checking a clean installed runtime and recovery journey", flush=True)
        run(
            [*pip, "install", "--only-binary=:all:", "--report", str(install_report), str(wheel)],
            working,
            env=env,
        )
        run([*pip, "check"], working, env=env)
        packages = inventory(read_json(install_report))
        if packages[PACKAGE] != (version, file_digest(wheel)["sha256"]):
            raise ReleaseError("Installed application does not match the built wheel")
        smoke_output = run(
            [str(python), "-I", str(source / "tools/release_smoke.py"), version], working, env=env
        )
        smoke = json.loads(smoke_output.strip().splitlines()[-1])
        if smoke != {
            "version": version,
            "installed_import": True,
            "loopback_ui": True,
            "guarded_save": True,
            "history_copy": True,
            "trash_restore": True,
        }:
            raise ReleaseError("Installed runtime smoke checks did not all pass")
        write_json(directory / "smoke.json", smoke)
        requirements = directory / "runtime-requirements.txt"
        with requirements.open("x", encoding="utf-8", newline="\n") as target:
            target.write(
                "# Platform-specific resolved wheels; use --require-hashes and --find-links.\n"
            )
            for name, (release, digest) in sorted(packages.items()):
                target.write(f"{name}=={release} --hash=sha256:{digest}\n")
        # This checks that the generated lock can reproduce a clean installation.
        locked = working / "locked-runtime"
        venv.EnvBuilder(with_pip=False).create(locked)
        locked_python = locked / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        locked_pip = [sys.executable, "-m", "pip", "--python", str(locked_python), "--isolated"]
        run(
            [
                *locked_pip,
                "install",
                "--require-hashes",
                "--only-binary=:all:",
                "--find-links",
                str(directory),
                "-r",
                str(requirements),
            ],
            working,
            env=env,
        )
        run([*locked_pip, "check"], working, env=env)
        sbom = directory / "runtime.cdx.json"
        print("Generating and cross-checking CycloneDX dependency evidence", flush=True)
        command = [
            sys.executable,
            "-m",
            "cyclonedx_py",
            "environment",
            str(python),
            "--pyproject",
            str(source / "pyproject.toml"),
            "--output-reproducible",
            "--validate",
            "--short-PURLs",
            "--spec-version",
            "1.6",
            "--output-format",
            "JSON",
        ]
        run([*command, "--output-file", str(sbom)], working, env=env)
        validate_bom(read_json(sbom), packages)
        repeated = working / "repeated.cdx.json"
        run([*command, "--output-file", str(repeated)], working, env=env)
        if file_digest(sbom) != file_digest(repeated):
            raise ReleaseError("Repeated SBOM generation was not byte-identical")
        shutil.copyfile(source / "tools/release_evidence.py", directory / "verify_release.py")
        shutil.copyfile(source / "docs/EVALUATING.md", directory / "EVALUATING.md")
        evidence = {
            "schema_version": 1,
            "kind": "unsigned-release-evidence",
            "created_at": datetime.now(UTC).isoformat(),
            "package": {"name": PACKAGE, "version": version},
            "source": {"revision": revision, "tree": tree, "commit_epoch": int(epoch)},
            "runtime": {
                "python": platform.python_version(),
                "system": platform.system(),
                "machine": platform.machine(),
            },
            "tool_versions": dict(
                sorted(
                    (normal_name(item.metadata["Name"]), item.version)
                    for item in importlib.metadata.distributions()
                )
            ),
            "checks": {
                "build": True,
                "twine": True,
                "pip_check": True,
                "installed_smoke": True,
                "hash_locked_install": True,
                "sbom_schema": True,
                "sbom_runtime_parity": True,
                "sbom_repeatable": True,
            },
            "limitations": [
                "Unsigned integrity evidence, not publisher authentication or SLSA attestation",
                "Dependency lock describes this Python/platform, not every supported environment",
                "No vulnerability or license-compliance guarantee; review declared metadata",
                "No public publication, signing, or real-user acceptance was performed",
            ],
            "artifacts": {item.name: file_digest(item) for item in sorted(directory.iterdir())},
        }
        write_json(directory / MANIFEST, evidence)
    return verify(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "verify"])
    parser.add_argument(
        "directory", type=Path, help="New output directory, or existing bundle to verify"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            evidence = build_bundle(args.directory, Path(__file__).resolve().parents[1])
        else:
            evidence = verify(args.directory)
    except (ReleaseError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Release evidence failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Verified {len(evidence['artifacts'])} artifacts. "
        "Integrity only; publisher identity is not authenticated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

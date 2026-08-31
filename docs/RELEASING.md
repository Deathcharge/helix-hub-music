# Release evidence, without publication

This maintainer workflow prepares an evaluable local candidate. It does not publish packages, create tags/releases, contact users, sign artifacts, create attestations, or change credentials. Its output is **unsigned integrity evidence**, not SLSA provenance or proof of publisher identity.

## Prerequisites and trust

- A clean committed Git checkout, Git on PATH, and Python 3.11.8+ (or 3.12+) with venv support. Application runtime requirements remain Python 3.11+.
- Internet access to public PyPI for release-tool setup and runtime wheels. Build mode executes trusted repository code and dependencies; it is not a sandbox for an untrusted repository.
- A separate tool environment. Build/test/browser packages must not contaminate the runtime inventory.
- A new output directory. Existing output is never overwritten; failed runs can leave an incomplete directory without a valid completion manifest. Inspect it and choose another new path when retrying.

The workflow archives the exact Git revision into a disposable source directory, rejecting link/unsafe archive members. Ignored build outputs and untracked workspace data cannot enter the snapshot. It builds with the configured release environment and `SOURCE_DATE_EPOCH` from the commit. Top-level tool versions and the CycloneDX library are pinned; all resolved tool versions are recorded. This does **not** promise bit-identical package builds across future dependency/tool/platform changes.

## Build a candidate

Use a fresh environment outside the tracked tree (the following location is ignored):

```text
python -m venv output/releases/tools
```

Windows PowerShell:

```powershell
& output/releases/tools/Scripts/python.exe -m pip install -r tools/release-requirements.txt
& output/releases/tools/Scripts/python.exe -I tools/release_evidence.py build output/releases/candidate-windows
& output/releases/tools/Scripts/python.exe -I tools/release_evidence.py verify output/releases/candidate-windows
```

Linux/macOS shell:

```bash
output/releases/tools/bin/python -m pip install -r tools/release-requirements.txt
output/releases/tools/bin/python -I tools/release_evidence.py build output/releases/candidate-unix
output/releases/tools/bin/python -I tools/release_evidence.py verify output/releases/candidate-unix
```

Keep artifact generation separate from source changes: commit first, then build. The script rejects staged, unstaged, and untracked non-ignored changes. Build mode deliberately uses public PyPI and ignores pip index/config environment overrides; private-index workflows are not supported by this command. Each subprocess has a five-minute timeout, no shell interpolation, and no inherited stdin. Output files remain local until an explicitly configured CI upload or owner-authorized distribution.

Tool bootstrap and the separate pilot-install commands are ordinary pip invocations: they honor the evaluator's pip configuration and require a trusted index (public PyPI by default). The builder records its actual tool environment but does not enforce that the caller created the documented venv or installed the pinned requirements. Follow that setup before building; a successful checksum check does not certify the build environment.

Direct build, verify, and help invocations require `python -I`. Isolation prevents neighboring bundle files from becoming Python imports, including when the trusted verifier is copied into an untrusted directory. The startup guard uses only built-in `sys` before any filesystem-backed import. In-process helper imports are for trusted maintainer/tests only. A trusted interpreter and installed environment are still required: no script can undo startup hooks that ran before it. See [Python isolated mode](https://docs.python.org/3/using/cmdline.html#cmdoption-I).

## What the command verifies

1. Wheel and sdist build from the pinned clean Git snapshot; Twine checks distribution metadata.
2. A fresh venv **without pip or build/test tools** receives only the built wheel and its wheel-only dependencies. The maintainer's pip manages that target interpreter.
3. `pip check` succeeds and an isolated interpreter imports the installed package. A real temporary loopback server serves the UI and exercises guarded save → History copy → Trash delete/restore, checking actual disk contents and stopping the server afterward.
4. Pip's installation report supplies exact package versions and SHA-256 wheel hashes. A second empty runtime installs using the generated `--require-hashes` lock and passes dependency checks.
5. CycloneDX 1.6 JSON is generated and schema-validated. Its root version and complete dependency inventory must match the actual runtime. A second generation in the same environment must be byte-identical.
6. A manifest binds all output files by size/SHA-256. The standalone verifier checks bounded regular files, rejects links/unlisted entries, and never executes a bundle.

The bundle contains the wheel, sdist, `runtime.cdx.json`, `runtime-requirements.txt`, `smoke.json`, `verify_release.py`, `EVALUATING.md`, and finally `release-manifest.json`. Dependency URLs/installation locations are not copied from pip's raw report. No user workspace is inspected. Checksums protect integrity relative to a trusted manifest; replacing the manifest and files together defeats that check. Obtain the verifier from a trusted source before running it.

The runtime lock is Python/platform-specific, including native wheel hashes. It is not a universal lock or offline wheelhouse. The SBOM contains declared metadata; license interpretation, vulnerability assessment, and application security review remain separate. Repeated SBOM bytes are not a claim of reproducible binaries, signed attestations, or independent build verification.

## CI and remaining gates

The existing Linux/Windows Python 3.13 jobs run the complete evidence command and upload separate 14-day candidate artifacts. Python 3.11/3.13 unit checks and installed-wheel browser CI remain independent gates. Workflow permissions remain read-only; no OIDC/signing/publishing permission was added.

Before a public prerelease, the owner must confirm the package-index account/name and authorized publisher, select the source revision and platform artifacts, arrange consented pilot evaluation, decide signing/attestation and retention policy, and obtain any needed rights/commercial-license review. Then verify the proposed publication configuration and rollback path explicitly. Do not treat a source merge or CI artifact upload as authorization to publish. [Pilot instructions](EVALUATING.md) are packaged for local evaluation; no pilot has been claimed.

## Primary references

- [Pip installation reports](https://pip.pypa.io/en/stable/reference/installation-report/) supply resolved package metadata and archive hashes; they are not themselves lock files.
- [Managing a different interpreter](https://pip.pypa.io/en/stable/topics/python-option/) supports an empty runtime without installing pip into it.
- [CycloneDX Python CLI](https://cyclonedx-bom-tool.readthedocs.io/en/latest/usage.html) supports installed-environment inventory, schema validation, and repeatable output.
- [SLSA provenance](https://slsa.dev/spec/v1.2/provenance) describes a stronger provenance model; this local unsigned manifest makes no SLSA conformance claim.

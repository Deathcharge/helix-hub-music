# Productization record

Date: 2026-07-28

Baseline revision: `64ad942bbf9e7f006a6ac481933587559121f50b`

Product: Samsarix Workspace `0.1.0`

Owner: Samsarix LLC

## Executive finding

The legacy repository was not an independently runnable product. It contained a worthwhile core idea—a browser-facing file workspace and a virtual terminal—but no installable package, application assembly, reliable test coverage, or consistent license. Several Python modules depended on an unrelated globally installed private package, five TSX pages had no frontend manifest or required components, and the public documentation described features and maturity that the checkout could not demonstrate.

The strongest evidence-based product was not the claimed “web OS,” ecosystem hub, AI service, design studio, video editor, email client, or marketplace. It was a focused local browser workspace. This pass rebuilt that product around a single promise:

> Choose a local folder, edit persistent UTF-8 files in a browser, and perform common file operations through a safe virtual terminal that cannot execute operating-system commands.

## Forensic baseline

The worktree began clean on `main`, aligned with `origin/main`, with 25 tracked files and no repository-specific agent instructions. History showed a large extraction from a broader ecosystem followed by documentation and mock-test commits; the visible files never formed one application.

Baseline command evidence:

| Check | Baseline result |
| --- | --- |
| `python -m compileall -q src chat` | Passed syntax compilation |
| `python -c "import src"` | Passed only because a private `helix-unified` package happened to be installed globally; emitted a random JWT-secret warning |
| `python -m pytest` | 36 mock-only tests reported as passing, then the command failed because real implementation coverage was 0% against an 80% gate |
| Black check | Failed; six files required formatting |
| Flake8 | Failed with style errors and undefined `TokenManager`, `get_llm_engine`, and `unified_llm` names |
| Mypy | Did not complete in a reasonable baseline run |
| `pip check` | Failed due to unrelated conflicts in the shared global Python environment, demonstrating that it was not a valid clean-install check |

Documentation and legal contradictions included:

- README claimed production readiness, MIT licensing, CI, examples, and files that did not exist.
- `LICENSING.md` claimed Apache 2.0 plus proprietary licensing.
- `LICENSE` was a modified Business Source License text with stale Helix identities and did not match the standard BSL 1.1 parameters or the README.
- The changelog labeled an unassembled extraction as `1.0.0`.

## Product decision

### Target user and job

The primary user is an individual developer, writer, or agent operator who wants a lightweight browser surface over a specific local folder without installing a JavaScript toolchain or exposing a real shell. The core job is a short loop: start a server, open or create a text file, edit and save it safely, inspect or organize files, close the app, and find the files unchanged on disk later.

### Competitive boundary

Current official product documentation informed the boundary:

- [JupyterLab](https://jupyterlab.readthedocs.io/en/stable/getting_started/overview.html) combines notebooks, editors, terminals, kernels, rich formats, and extensions. Its [terminal documentation](https://jupyterlab.readthedocs.io/en/stable/user/terminal.html) explicitly provides full system shells with the server user's privileges.
- [code-server](https://coder.com/docs/code-server) runs VS Code in a browser and targets full remote development; its documented baseline expects a server with WebSockets and substantially broader compute authority.
- The [Python Packaging User Guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) defines `pyproject.toml`, build-system metadata, and `[project.scripts]` as the modern installable CLI path.

Samsarix Workspace therefore does not compete on IDE depth. Its differentiation is a small auditable dependency set, no frontend build, persistent plain files, and a non-shell terminal. A user who needs kernels, extensions, compilation, or a real terminal should choose JupyterLab, code-server, or a desktop editor.

### Product boundaries

Included in `0.1.0`:

- One filesystem root per process
- UTF-8 regular-file create, read, save, move, and delete
- Folder create, move, list, and explicitly recursive delete
- Manual editor save with SHA-256 optimistic concurrency
- Bounded virtual file commands with stateful server-issued sessions
- Browser UI, JSON API, CLI, package metadata, tests, CI, and operating documentation

Removed because they were unsupported fragments:

- Browser AI and private LLM imports
- Context-chat bridge and undefined token manager
- Unassembled Next.js pages for an app launcher, design studio, code editor, video editor, and email client
- Invented pricing, subscriptions, marketplace, provider routing, real-time collaboration, and production-readiness claims
- Mock-only tests and broad unpinned requirements files

Deferred deliberately:

- Binary preview and download/upload UX
- Autosave, recovery drafts, history, or version control
- Multi-user identity, authorization, tenant isolation, and audit logs
- Collaboration, cloud sync, deployment automation, and hosted operations
- A real shell, code execution, AI provider access, plugins, or extensions
- PyPI publication, signed artifacts, SBOM/provenance attestations, and automated release publishing

## Architecture

```text
Browser UI (static HTML/CSS/JS)
            │ same-origin JSON + optional bearer token
            ▼
FastAPI application
   ├── request-stream size gate
   ├── stable validation/error envelope
   ├── bounded server-issued shell-session LRU
   └── security response headers
            │
            ├── Workspace service ── atomic UTF-8 files under one root
            │
            └── VirtualShell ─────── direct allowlisted method dispatch
                                     (no subprocess or OS shell)
```

There is no database, queue, migration, external API, telemetry endpoint, or background worker. Files on disk are the durable data model.

## Security and privacy review

### Baseline threat model

Protected assets were tenant files, the host filesystem outside configured roots, process availability/memory, and optional paid LLM budget. Trust boundaries crossed from browser input into authenticated tenant selection, path handling, request buffering, and provider calls.

A complete pre-change security scan of all 25 tracked files produced seven reportable findings: two high and five medium.

| Baseline class | Evidence | Resolution in the productized design |
| --- | --- | --- |
| Lossy user-ID normalization (file and terminal workspaces) | Distinct IDs such as `a/b` and `a?b` mapped to one cache/root | Multi-user and external identity surfaces removed; one explicitly configured local root per process |
| Oversized upload buffered before validation | `await file.read()` occurred before size/quota checks | Upload route removed; global ASGI streaming body ceiling precedes JSON parsing |
| Oversized WebSocket JSON buffered before validation | `receive_json()` occurred before the advertised limit | WebSocket route removed; terminal uses bounded HTTP JSON |
| Symlink read/write escape | Focused reproductions read and wrote outside the configured root through an in-root link | Every public path is relative, raw traversal segments are rejected, and every existing path component is checked for symlinks before access; hard-linked files are blocked too |
| Anonymous demo limiter bypass / paid-provider amplification | Caller-controlled session IDs and forwarded IP values defeated the only limit | Anonymous AI/provider route and all provider credentials removed |

Security regression tests now cover path traversal, symlink escape, root deletion, request-stream limits, session issuance/expiry/eviction, token enforcement, quotas, stale-save conflicts, and the virtual terminal's lack of shell interpretation.

Residual assumptions and limitations:

- A malicious local process with permission to mutate the workspace concurrently may still attempt filesystem time-of-check/time-of-use races. This is a local convenience boundary, not an OS sandbox against another process running as the same user.
- The bearer token is a shared secret, not user identity. Non-loopback deployments still need TLS, network controls, and operational log handling.
- Static assets and health metadata are public by design so the unlock UI can load.
- Deletes are permanent; the application has no trash or version history.
- Browser drafts are not persisted before manual save.

No credentials, tracking pixels, analytics SDKs, or third-party browser assets are included. API responses do not reveal the absolute host root.

## Data lifecycle and failure behavior

- `init` creates only `WELCOME.md` and never overwrites it.
- A save validates UTF-8 byte size and projected total quota, writes a temporary sibling, flushes it, and uses `os.replace` for atomic replacement.
- Existing-file saves can include the last ETag. A stale or deleted target returns HTTP 409 rather than overwriting silently.
- Listing and regular-file accounting do not follow symlinks.
- The root path cannot be used as a mutation target.
- Non-empty folder deletion needs an explicit recursive flag and UI confirmation.
- Terminal sessions are created by the server, expire after inactivity, and are capped by an LRU ceiling.
- Oversized declared or streamed bodies receive HTTP 413 before application deserialization completes.

## Licensing decision

The repository is now `AGPL-3.0-only`, with the canonical GNU license text, `Samsarix LLC` copyright notice, and historical credit retained in Git history and `NOTICE`.

The GNU project's [license guidance](https://www.gnu.org/licenses/) describes AGPLv3 as adding a network-source provision and recommends it for software commonly run over a network. That matches a browser-server application better than a permissive license when the owner's goal is to preserve source availability and credit. The prior customized BSL was not retained: the [official BSL 1.1 text](https://mariadb.com/bsl11/) states that it is not an open-source license and permits only its named parameters to be changed.

There is no current proprietary dual-license promise. Selling proprietary exceptions later would require Samsarix LLC to confirm complete relicensing rights and adopt an appropriate contributor agreement before accepting code whose copyright it does not own. The repository instead requires contribution sign-off and licenses contributions under the same AGPL terms.

This record explains an engineering choice and is not legal advice.

## Release and verification gates

Required local gates:

```bash
python -m ruff check samsarix_workspace tests
python -m ruff format --check samsarix_workspace tests
python -m mypy samsarix_workspace
python -m pytest
node --check samsarix_workspace/static/app.js
python -m build
```

CI repeats lint, type, test, build, wheel-install, import, and CLI smoke checks on supported Python versions across Windows and Linux. The repository does not auto-publish packages or deploy a hosted service because no package index, domain, signing identity, or production environment has been configured.

### Final verification evidence

The final Windows/Python 3.11 release-candidate run produced:

| Gate | Result |
| --- | --- |
| Ruff lint and format check | Passed with no findings; 11 Python files formatted |
| Mypy strict package check | Passed; 6 source files checked |
| Pytest with branch coverage | 40 passed, 1 platform-specific FIFO test skipped; 92.70% total coverage |
| JavaScript syntax check | Passed with Node.js `--check` |
| Headed Chromium primary journey | Created, opened, edited, keyboard-saved, refreshed, and terminal-read a persistent file at desktop and 390×844 mobile sizes |
| Browser console | Zero errors and zero warnings after fixes |
| Python build | Created sdist and universal wheel successfully in isolated build environments |
| Twine metadata check | Passed for both distributions |
| Clean virtual-environment install | Wheel installed with current resolved dependencies; import, app factory, packaged static assets, AGPL metadata, CLI version, and `pip check` all passed |
| Runtime dependency audit | `pip-audit` found no known vulnerabilities in the resolved FastAPI/Uvicorn runtime graph |
| Adversarial sink search | No subprocess, dynamic-evaluation, unsafe deserialization, or outbound HTTP client sink remains in the application package |

The single skipped test covers POSIX FIFO classification and is expected on Windows; Windows hard-link and symlink regressions executed successfully. No test depends on the legacy globally installed `helix-unified` package.

## Next best work

The next release should favor reliability over breadth:

1. Add browser end-to-end tests to CI and a small visual regression fixture.
2. Add recoverable drafts or autosave with an explicit conflict/recovery model.
3. Add safe file download and bounded streaming upload without reintroducing pre-limit buffering.
4. Add a trash/recovery mechanism before expanding destructive operations.
5. If hosted multi-user use becomes a real requirement, design identity, authorization, per-tenant roots, audit logging, CSRF/origin controls, and deployment isolation as a separate security phase—not as a flag on the local app.
6. Before PyPI publication, reserve the package name, configure trusted publishing, generate provenance/SBOM artifacts, and document a rollback process.

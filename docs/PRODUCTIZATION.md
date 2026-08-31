# Productization record

Date: 2026-08-31

Baseline revision: `64ad942bbf9e7f006a6ac481933587559121f50b`

Product: Samsarix Workspace `0.2.1`

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

Deferred deliberately after `0.2.0`:

- Binary/rich-media preview, background autosave, recoverable trash, and version history
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
   ├── trusted Host allowlist
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

Security regression tests now cover path traversal, symlink and hard-link escape, root deletion, request-stream limits, session issuance/expiry/eviction, token and Host enforcement, quotas, stale-save conflicts, atomic create-only races, and the virtual terminal's lack of shell interpretation.

Residual assumptions and limitations:

- A malicious local process with permission to mutate the workspace concurrently may still attempt filesystem time-of-check/time-of-use races. This is a local convenience boundary, not an OS sandbox against another process running as the same user.
- The bearer token is a shared secret, not user identity. Non-loopback deployments still need TLS, network controls, and operational log handling.
- Static assets and health metadata are unauthenticated by design so the unlock UI can load; trusted-Host validation still applies.
- Deletes are permanent; the application has no trash or version history.
- One unsaved editor draft may be stored in tab-scoped browser `sessionStorage` for reload recovery. It is not sent to Samsarix LLC or a third party.

No credentials, tracking pixels, analytics SDKs, or third-party browser assets are included. API responses do not reveal the absolute host root.

## Data lifecycle and failure behavior

- `init` creates only `WELCOME.md` and never overwrites it.
- A save validates UTF-8 byte size and projected total quota, writes a temporary sibling, flushes it, and uses `os.replace` for atomic replacement.
- Existing-file saves can include the last ETag. A stale or deleted target returns HTTP 409 rather than overwriting silently.
- Create/import operations atomically claim a new destination without replacement. Replacing an existing import requires confirmation and an exact current ETag.
- Content search scans only bounded regular UTF-8 files and stops at its byte or result ceiling.
- Invalid UTF-8 and oversize browser imports are rejected before an API write; downloads contain the current editor text.
- Listing and regular-file accounting do not follow symlinks.
- The root path cannot be used as a mutation target.
- Non-empty folder deletion needs an explicit recursive flag and UI confirmation.
- Terminal sessions are created by the server, expire after inactivity, and are capped by an LRU ceiling.
- Oversized declared or streamed bodies receive HTTP 413 before application deserialization completes.

## `0.2.0` market evidence and product increment

Current official documentation shows a stable set of user expectations around browser file workspaces:

- [JupyterLab](https://jupyterlab.readthedocs.io/en/stable/user/interface.html) combines a file browser, document tabs, search, text editing, and terminals; its [terminal guide](https://jupyterlab.readthedocs.io/en/stable/user/terminal.html) makes clear that those terminals execute full system shells with the server user's privileges.
- [VS Code for the Web](https://code.visualstudio.com/docs/remote/vscode-web) positions zero-install browser editing and browser-sandboxed exploration as useful, while the [VS Code Server](https://code.visualstudio.com/docs/remote/vscode-server) provides a much broader remote-development system.
- [Nextcloud Files](https://docs.nextcloud.com/server/latest/user_manual/en/files/access_webgui.html) treats search, text preview, upload/download, recent files, deleted-file recovery, and version history as recognizable file-workspace jobs.
- [Obsidian's storage model](https://obsidian.md/help/Files%2Band%2Bfolders/How%2BObsidian%2Bstores%2Bdata) reinforces the value of ordinary local files rather than an opaque hosted data model.
- The [CommonMark specification](https://spec.commonmark.org/current/) defines a much broader Markdown grammar than this release claims. Samsarix therefore labels its dependency-free renderer “safe basic Markdown preview” rather than claiming full CommonMark conformance.
- Starlette's official [TrustedHostMiddleware documentation](https://www.starlette.io/middleware/#trustedhostmiddleware) identifies Host validation as the control for HTTP Host-header attacks. `0.2.0` applies an explicit equivalent before every route, with case-insensitive hostname comparison, bracketed-IPv6 handling, duplicate rejection, and no wildcard allowlists.

The selected real-world job is document and artifact review: import a small set of UTF-8 notes, logs, configuration, code, or AI-generated text artifacts into a chosen local folder; find relevant lines; inspect Markdown safely; edit with recoverable unsaved state and explicit external-change handling; then save or download the result. This expands the complete journey without introducing a real shell, code execution, cloud sync, accounts, a database, or a frontend dependency supply chain.

Implemented in `0.2.0`:

- Bounded cross-file content search with path/line navigation, result limits, byte limits, and scan accounting
- UTF-8 browser import, per-file size checks, create-only writes, collision confirmation, and current-document download
- Basic Markdown block/inline preview built only with DOM nodes and safe link protocols; raw HTML is displayed as text
- One tab-scoped unsaved draft with explicit restore/discard behavior
- Reload, keep-editing, or exact-checkpoint overwrite choices for external file changes or deletions
- Trusted Host validation, explicit allowed hosts for wildcard binds, ASCII bearer-token validation, and byte-wise constant-time comparison

This is still demand evidence from adjacent product behavior, not proof of product-market fit. A small external pilot remains required before stronger market claims.

## Licensing decision

The repository is now `AGPL-3.0-only`, with the canonical GNU license text, `Samsarix LLC` copyright notice, and historical credit retained in Git history and `NOTICE`.

The GNU project's [license guidance](https://www.gnu.org/licenses/) describes AGPLv3 as adding a network-source provision and recommends it for software commonly run over a network. That matches a browser-server application better than a permissive license when the owner's goal is to preserve source availability and credit. The prior customized BSL was not retained: the [official BSL 1.1 text](https://mariadb.com/bsl11/) states that it is not an open-source license and permits only its named parameters to be changed.

There is no current proprietary dual-license promise. Selling proprietary exceptions later would require Samsarix LLC to confirm complete relicensing rights and adopt an appropriate contributor agreement before accepting code whose copyright it does not own. The repository instead requires contribution sign-off and licenses contributions under the same AGPL terms.

This record explains an engineering choice and is not legal advice.

## Release and verification gates

Required local gates:

```bash
python -m ruff check samsarix_workspace tests e2e
python -m ruff format --check samsarix_workspace tests e2e
python -m mypy samsarix_workspace
python -m pytest
node --check samsarix_workspace/static/app.js
python -m build
```

CI repeats lint, type, test, build, wheel-install, import, and CLI smoke checks on supported Python versions across Windows and Linux. The repository does not auto-publish packages or deploy a hosted service because no package index, domain, signing identity, or production environment has been configured.

### Historical `0.2.0` verification evidence

The Windows/Python 3.11 `0.2.0` release-candidate run produced:

| Gate | Result |
| --- | --- |
| Ruff lint and format check | Passed with no findings; 11 Python files formatted |
| Mypy strict package check | Passed; 6 source files checked |
| Pytest with branch coverage | 56 passed, 1 platform-specific FIFO test skipped; 90.87% total coverage |
| JavaScript syntax check | Passed with Node.js `--check` |
| Headed Chromium document-review journey | Imported and saved a real UTF-8 file, rendered raw HTML inertly, navigated Unicode searches to exact source spans, verified astral-character selection at UTF-16 offsets 19–27, proved duplicate Ctrl+S input issued one PUT, downloaded a real file, and verified the 390×844 responsive layout without horizontal overflow |
| Accessibility sanity checks | Accessibility snapshot exposed labeled regions and controls; document language was `en`, with no duplicate IDs or unlabeled empty buttons |
| Browser console | Zero errors and zero warnings after fixes |
| Python build | Created sdist and universal wheel successfully in isolated build environments |
| Twine metadata check | Passed for both distributions |
| Clean virtual-environment install | Wheel installed with current resolved dependencies; import, app factory, packaged static assets, AGPL metadata, CLI version, and `pip check` all passed |
| Runtime dependency audit | `pip-audit 2.10.0` found no known vulnerabilities in the exact installed environment after disposable bootstrap tools were updated; the unpublished local package identity was skipped as expected |
| Adversarial sink search | No subprocess, dynamic-evaluation, unsafe deserialization, or outbound HTTP client sink remains in the application package |

Historical `0.2.0` artifact SHA-256 digests (not the current build):

- `samsarix_workspace-0.2.0-py3-none-any.whl`: `017a98819473d17b43d2a2f98b71a67406f2952d8735f1b05c37d681726c1111`
- `samsarix_workspace-0.2.0.tar.gz`: `77f169024ef7f3b3380e95bf8f6dba70159a74fa0d104e5d47aaf93d6be5c059`

The single skipped test covers POSIX FIFO classification and is expected on Windows; Windows hard-link and symlink regressions executed successfully. No test depends on the legacy globally installed `helix-unified` package.

## `0.2.1` editor-lifecycle reliability increment

Baseline: `e5a5330` on `main`, clean working tree, no open PRs, and green current cross-platform CI. The Python baseline remained 56 passed / one expected Windows FIFO skip with 90.87% branch coverage, Ruff and mypy passing.

The [VS Code editing guide](https://code.visualstudio.com/docs/editing/codebasics) documents preserving unsaved work as an ordinary editor expectation. This is adjacent-product evidence, not proof of Samsarix demand. Inspection and a new real-browser regression suite revealed eight reproducible failures before implementation: newer typing could be marked saved, pending/failed opens could corrupt editor identity or drafts, stale responses won selection, conflict continuation/restoration bypassed original ETags, recreation could overwrite an intervening file, and new-file creation bypassed discard confirmation. These were locally actionable P1 reliability defects, ahead of adding trash or history.

Implemented controls:

- Save responses acknowledge the submitted snapshot only; later typing stays dirty and the draft uses the acknowledged ETag.
- Opens commit the content/path/checkpoint together, use generation checks, and keep the old editor read-only until the latest request resolves.
- Save/mutation navigation guards and single-flight mutation controls preserve document identity throughout asynchronous operations.
- Draft restoration and conflict cancellation retain original ETags; only explicit reload/overwrite chooses a new checkpoint. Missing-file overwrite uses create-only semantics.
- New-file creation asks before discard and preserves the prior draft on failure.
- All browser API requests time out after 15 seconds without automatically replaying mutations.
- Browser tests use temporary files and a real loopback Uvicorn server; deterministic request holds reproduce races while writes still go through the production API to disk.

Following the [Playwright Python test-runner](https://playwright.dev/python/docs/test-runners) and [CI guidance](https://playwright.dev/python/docs/ci), browser tools are pinned in an optional extra, separate from runtime dependencies. The CI matrix adds Chromium on Windows/Linux and Firefox on Linux, with seven-day failure artifacts containing synthetic fixture data only. The Python unit/integration coverage gate remains independent and unchanged. No telemetry, hosted service, account system, paid API, or filesystem retention store was introduced.

### `0.2.1` local verification

Commands used the disposable Python 3.11 environment at `output/playwright/lifecycle-env` unless noted:

| Command / gate | Observed result |
| --- | --- |
| `python -m ruff check samsarix_workspace tests e2e` | Passed |
| `python -m ruff format --check samsarix_workspace tests e2e` | Passed; 14 files |
| `python -m mypy samsarix_workspace` | Passed; 6 source files |
| `python -m pytest` | 56 passed, one expected Windows FIFO skip; 90.87% branch-aware coverage |
| `node --check samsarix_workspace/static/app.js` | Passed |
| `python -m build` | Built sdist, then wheel from that sdist |
| `py -3.11 -m twine check dist/samsarix_workspace-0.2.1-py3-none-any.whl dist/samsarix_workspace-0.2.1.tar.gz` | Both passed |
| `python -m pytest` inside the extracted sdist | 56 passed, one expected Windows FIFO skip; 90.87% coverage; packaged fixtures are sufficient |
| Installed-wheel import, CLI `--version`, and `python -m pip check` | Version `0.2.1`; no broken requirements |
| `python -m pytest <absolute-checkout>/e2e -o addopts= --browser chromium --browser firefox --tracing retain-on-failure --screenshot only-on-failure --output <absolute-checkout>/output/playwright/wheel-final` from outside the checkout with `SAMSARIX_TEST_INSTALLED=1` | 32 passed in 133.00 seconds on Windows; Chromium and Firefox |
| `py -3.11 -m pip_audit --path output/playwright/lifecycle-env/Lib/site-packages --progress-spinner off` | No known dependency vulnerabilities after updating the disposable environment's pip/setuptools; unpublished `samsarix-workspace` skipped |
| Headed Chromium at 390×844 | Document open/preview works, no horizontal overflow, no console errors or warnings |

The current Starlette test client emits one upstream deprecation warning about its `httpx` integration; it does not fail these checks. No warning filter was added. Browser tests cover 16 scenarios per engine against real temporary files. The installed-wheel run starts outside the checkout and asserts that the server imports from `site-packages`, preventing a source checkout from masking packaging failures. Failure traces exposed a Firefox selection-test synchronization issue; the test now explicitly waits for the editor to be visible before inspecting its selected text.

Local artifact SHA-256 digests (build timestamps mean other builds may differ):

- `samsarix_workspace-0.2.1-py3-none-any.whl`: `feef8e938f0d71ffab4dfa365bff37f87b85198973d7482d3255418190ca1c09`
- `samsarix_workspace-0.2.1.tar.gz`: `47457666fc285d2c09d343020cec6a9d5ac4fc915d6a5ec6e1d3362cab1ee153`

Exact-head cross-platform CI and review evidence belong to the `0.2.1` pull request. WebKit, real mobile hardware, external pilot users, and public package publication have not been validated in this increment. The historical `0.2.0` artifacts above must not be presented as hashes of the new source.

## Next best work

The next release should favor reliability over breadth:

1. Add recoverable trash and bounded version checkpoints before expanding destructive operations.
2. Extend browser coverage to WebKit, preserving the existing lifecycle regression cases.
3. Run a small external pilot against the exact wheel and capture consented, privacy-preserving task success/support evidence.
4. If hosted multi-user use becomes a real requirement, design identity, authorization, per-tenant roots, audit logging, CSRF/origin controls, and deployment isolation as a separate security phase—not as a flag on the local app.
5. Before PyPI publication, reserve the package name, configure trusted publishing, generate provenance/SBOM artifacts, and document a rollback process.

# Productization record

Date: 2026-08-31

Baseline revision: `64ad942bbf9e7f006a6ac481933587559121f50b`

Product: Samsarix Workspace `0.4.1` candidate

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

Deferred deliberately after `0.4.0`:

- Binary/rich-media preview, background autosave, external-change monitoring, and file-identity/rename tracking
- Multi-user identity, authorization, tenant isolation, and audit logs
- Collaboration, cloud sync, deployment automation, and hosted operations
- A real shell, code execution, AI provider access, plugins, or extensions
- PyPI publication, signed artifacts, provenance attestations, and automated release publishing; unsigned local SBOM/build evidence is implemented in the `0.4.1` candidate

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
            │          ├── TrashStore ── bounded private deleted-content records
            │          └── HistoryStore ── bounded pre-overwrite text checkpoints
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
- Regular deletions move to local Trash. Explicit purge and `permanent=true` remove that copy; separate older saved-history checkpoints remain until removed or expired. History is bounded recovery, not an off-device backup.
- One unsaved editor draft may be stored in tab-scoped browser `sessionStorage` for reload recovery. It is not sent to Samsarix LLC or a third party.

No credentials, tracking pixels, analytics SDKs, or third-party browser assets are included. API responses do not reveal the absolute host root.

## Data lifecycle and failure behavior

- `init` creates only `WELCOME.md` and never overwrites it.
- A save validates UTF-8 byte size and projected total quota, checkpoints the prior content before a changed overwrite, writes a temporary sibling, flushes it, and rechecks disk contents before `os.replace`. Checkpoint retention can occur even if active replacement subsequently fails.
- Existing-file saves can include the last ETag. A stale or deleted target returns HTTP 409 rather than overwriting silently.
- Create/import operations atomically claim a new destination without replacement. Replacing an existing import requires confirmation and an exact current ETag.
- Content search scans only bounded regular UTF-8 files and stops at its byte or result ceiling.
- Invalid UTF-8 and oversize browser imports are rejected before an API write; downloads contain the current editor text.
- Listing and regular-file accounting do not follow symlinks.
- The root path cannot be used as a mutation target.
- Non-empty folder deletion needs an explicit recursive flag and UI confirmation.
- Deleted-content records are kept in reserved `.samsarix-trash`; saved versions use separate `.samsarix-history`. Both are excluded from active APIs/search/accounting. Trash restore never replaces an existing target; History permits replacement only with the current disk ETag.
- One server instance serializes reads and mutations with a reentrant lock. This does not coordinate multiple processes or constrain hostile same-permission OS writers.
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
| `python -m pytest <absolute-checkout>/e2e -o addopts= --browser chromium --browser firefox --tracing retain-on-failure --screenshot only-on-failure --output <absolute-checkout>/output/playwright/wheel-reviewed` from outside the checkout with `SAMSARIX_TEST_INSTALLED=1` | 38 passed in 140.61 seconds on Windows; Chromium and Firefox, including all review follow-ups |
| `py -3.11 -m pip_audit --path output/playwright/lifecycle-env/Lib/site-packages --progress-spinner off` | No known dependency vulnerabilities after updating the disposable environment's pip/setuptools; unpublished `samsarix-workspace` skipped |
| Headed Chromium at 390×844 | Document open/preview works, no horizontal overflow, no console errors or warnings |

The current Starlette test client emits one upstream deprecation warning about its `httpx` integration; it does not fail these checks. No warning filter was added. Browser tests cover 19 scenarios per engine against real temporary files. The installed-wheel run starts outside the checkout and asserts that the server imports from `site-packages`, preventing a source checkout from masking packaging failures. Failure traces exposed a Firefox selection-test synchronization issue; the test now explicitly waits for the editor to be visible before inspecting its selected text.

The [PR #12 review](https://github.com/Deathcharge/samsarix-workspace/pull/12) identified three minor follow-ups: an outdated roadmap milestone, clock setup after navigation, and non-JSON HTTP errors classified as network failures. The roadmap reference was corrected; an opt-in fixture installs the fake clock before navigation following the [official clock guidance](https://playwright.dev/python/docs/clock); and the API client preserves HTTP status/authentication recovery while distinguishing invalid success payloads from connection failures. Three new browser cases cover non-JSON 200/400/401 responses, retained drafts, online state, authentication prompts, and retry after non-authentication errors. No additional paid review was requested after the service reported its included-review quota exhausted.

Local artifact SHA-256 digests (build timestamps mean other builds may differ):

- `samsarix_workspace-0.2.1-py3-none-any.whl`: `e907f70682ef4a9c895590dd800fc61534cf3fd9e07ba78b84a7a373d3c09e24`
- `samsarix_workspace-0.2.1.tar.gz`: `221afe3cd76f1059dd6b0c28a1406c303872ab3092ae2960667bc4b8304a6762`

Exact-head cross-platform CI and review evidence belong to the `0.2.1` pull request. WebKit, real mobile hardware, external pilot users, and public package publication have not been validated in this increment. The historical `0.2.0` artifacts above must not be presented as hashes of the new source.

## `0.3.0` recoverable deletion

Baseline: clean merged `ab047426e56ba3c4f47c8cc30ecfcd3d6f904ce2`, with all seven jobs in [post-merge CI 33393698031](https://github.com/Deathcharge/samsarix-workspace/actions/runs/33393698031) successful. Local baseline: 56 Python tests passed, one Windows FIFO skip, 90.87% branch-aware coverage; Ruff and Mypy passed. Permanent-only deletion was the next locally actionable P1 reliability gap.

### Product decision and evidence

Official [Nextcloud deleted-file guidance](https://docs.nextcloud.com/server/latest/user_manual/en/files/deleted_file_management.html), checked 2026-08-31, documents recovery, original-path restoration, collision handling, separate quota accounting, and permanent removal. This supports recovery as a recognizable file-workspace job; it is not demand validation. Samsarix deliberately uses explicit collision resolution and refuses new deletion when full instead of implementing retention-based eviction. The freedesktop specification page was unavailable during verification, so no specification-compliance claim is made. The product uses its own portable store, not the operating system's Trash.

Completed implementation:

- [x] API/UI/virtual-command deletion defaults to recoverable Trash; explicit permanent bypass and confirmed single-item purge remain available.
- [x] Owned, opaque-ID records persist across process restarts; metadata files are flushed before same-filesystem rename, with no copy-and-delete fallback.
- [x] Separate 50 MiB/100-item/2,000-contained-entry default budgets; no auto-expiry or silent eviction.
- [x] Reserved paths, Windows reparse/junction handling, malformed metadata, links, active quotas, and stale-delete ETags are validated.
- [x] Restore exclusively creates files/folders; failed copies retain archives and may leave inspectable partial destinations; cleanup failures return an explicit retained-copy flag.
- [x] Browser recovery includes collision/error retry, unavailable records, cancellation, loading/empty states, and preserving other editor drafts.
- [x] Onboarding, API compatibility change, troubleshooting, changelog, and roadmap reflect the implemented behavior.

Risk and operating notes: recovery adds local disk usage, not a provider bill, runtime dependency, remote service, or telemetry. The private store contains original paths and content without encryption. File data/modes/modified times are preserved where supported, not arbitrary ACLs/ownership/alternate streams. One app process per root is supported. Ordinary interrupted operations are tested; arbitrary power loss, filesystem corruption, same-permission hostile writers, and network-filesystem guarantees are not claimed. Purge is normal removal, not secure erasure; external backups remain necessary. Python's [documented `rmtree` behavior](https://docs.python.org/3/library/shutil.html#shutil.rmtree) informs link handling, and a real Windows junction regression verifies target preservation.

### Verification and release acceptance

This increment must pass the unchanged 90% Python coverage gate, lint/format/type checks, JavaScript syntax, installed-wheel browser flows, distribution checks, and exact-head Windows/Linux CI before merge. Local evidence and artifact digests are recorded below as verification finishes. Public publication and external pilot validation remain separate owner gates; this is an alpha release candidate, not a hosted production claim.

Verified implementation commit: `f54d4cfd3cf916ffb3aed1a0ac9df9e6fd602991`, [PR #13](https://github.com/Deathcharge/samsarix-workspace/pull/13). Local Python commands used `output/playwright/lifecycle-env/Scripts/python.exe` (Python 3.11.9), except where a fresh runtime-only environment is named.

| Exact command / gate | Observed result |
| --- | --- |
| `python -m ruff check samsarix_workspace tests e2e` | Passed |
| `python -m ruff format --check samsarix_workspace tests e2e` | 18 files already formatted |
| `python -m mypy samsarix_workspace` | Passed, 8 source files |
| `python -m pytest --tb=short` | 113 passed, 1 Windows FIFO skip, 91.40% branch-aware coverage |
| `node --check samsarix_workspace/static/app.js` and `git diff --check` | Passed |
| `python -m pytest e2e -o addopts= --browser chromium --browser firefox --tracing retain-on-failure --screenshot only-on-failure --output output/playwright/recovery-source-all --tb=short` | 50 passed, 170.51 seconds |
| Same browser suite from `output/playwright/wheel-check`, with absolute `e2e` path, `SAMSARIX_TEST_INSTALLED=1`, and output `output/playwright/recovery-wheel` | 50 passed against installed wheel, 221.09 seconds |
| `python -m build --outdir output/playwright/recovery-dist` | Wheel and sdist built in isolated build environments |
| `py -3.11 -m twine check output/playwright/recovery-dist/samsarix_workspace-0.3.0-py3-none-any.whl output/playwright/recovery-dist/samsarix_workspace-0.3.0.tar.gz` | Both passed |
| Fresh `output/playwright/recovery-runtime` environment: wheel install, import outside checkout, `python -m samsarix_workspace --version`, `python -m pip check` | Version 0.3.0; installed-package path verified; no broken requirements |
| `py -3.11 -m pip_audit --path output/playwright/recovery-runtime/Lib/site-packages --skip-editable` | No known vulnerabilities after updating bootstrap tools; unpublished Samsarix package is not in PyPI advisory data |
| Headed Playwright CLI: delete → Trash → restore, desktop and 390×844 screenshots, browser console | Completed, restored file verified on disk; zero console warnings/errors |
| [CI 33398348961](https://github.com/Deathcharge/samsarix-workspace/actions/runs/33398348961) at `f54d4cf` | All seven jobs passed: Python 3.11/3.13 on Linux/Windows and 25 browser cases each on Chromium Linux/Windows and Firefox Linux |

Linux CI: 113 passed, 1 Windows-junction skip, 91.06% coverage. Windows CI: 113 passed, 1 FIFO skip, 91.40%. The upstream Starlette/httpx deprecation warning remains unsuppressed. Initial browser-test authoring failures were incorrect expected dialog/empty-state wording, corrected before the passing runs. The first runtime audit reported 14 advisory rows in the old venv-seeded `pip 24.0` / `setuptools 65.5.0`; upgrading those disposable-environment tools to `pip 26.2.1` / `setuptools 84.0.0` cleared the audit without changing application dependencies or ignoring advisories.

Local artifact SHA-256 (from the implementation snapshot; hashes identify these files, not future rebuilds):

- `samsarix_workspace-0.3.0-py3-none-any.whl`: `43c91923710657dbab624771890cd9abb72d1cb7578834bcaabb26e4ce00b9fe`
- `samsarix_workspace-0.3.0.tar.gz`: `9d4e1618fcc633e4b66eaba9badf5888305eff4957a8b1eccb1446284a4ee80f`

WebKit, macOS runtime, physical mobile hardware, external pilot users, public package publication, and arbitrary power-loss recovery were not validated. Screenshots and disposable test workspaces remain under ignored `output/playwright/`; no user content or production resource was changed by these checks.

### Final review follow-up and packaged acceptance

Final runtime/test revision: `9e1cae2d7bd026eb551a55d29b6bd73fbe214de4`. The external [PR #13 review](https://github.com/Deathcharge/samsarix-workspace/pull/13#pullrequestreview-5067295959) found an ordinary host-filesystem race: a directory removed after `os.walk` enumeration could raise an unwrapped metadata error. A shared classifier now skips vanished folders while retaining `WorkspaceError` for other failures; four unit cases cover missing/permission-denied folders in listing/accounting. A separate claimed empty-selection JavaScript failure was disproved by short-circuit analysis and a Chromium/Firefox regression. The reviewer acknowledged both resolutions. No additional paid review was requested after the included quota was exhausted.

Additional browser coverage verifies restoring a complete folder, including binary children and empty subfolders. The final suite has 27 scenarios per browser. The initial 25-case evidence above remains historical, not the final suite count.

| Final command / gate | Observed result |
| --- | --- |
| `python -m ruff check samsarix_workspace tests e2e` | Passed |
| `python -m ruff format --check samsarix_workspace tests e2e` | Passed, 18 files |
| `python -m mypy samsarix_workspace` | Passed, 8 source files |
| `python -m pytest --tb=short` in the checkout | 117 passed, 1 Windows FIFO skip; 91.49% branch coverage |
| `node --check samsarix_workspace/static/app.js` and `git diff --check` | Passed |
| `python -m build --outdir output/playwright/recovery-reviewed-dist` | sdist and wheel built successfully |
| `py -3.11 -m twine check output/playwright/recovery-reviewed-dist/samsarix_workspace-0.3.0-py3-none-any.whl output/playwright/recovery-reviewed-dist/samsarix_workspace-0.3.0.tar.gz` | Both passed |
| `python -m pytest --tb=short` from `output/playwright/recovery-reviewed-sdist/samsarix_workspace-0.3.0` after extracting that sdist | 117 passed, 1 Windows FIFO skip; 91.49% branch coverage, 25.23 seconds |
| `python -m pytest C:/Users/Andrew/Helix/helix-web-os/e2e -o addopts= --browser chromium --browser firefox --tracing retain-on-failure --screenshot only-on-failure --output C:/Users/Andrew/Helix/helix-web-os/output/playwright/recovery-reviewed-wheel --tb=short` | 54 passed, 215.37 seconds, from `output/playwright/wheel-check` with `SAMSARIX_TEST_INSTALLED=1`; fixture verifies site-packages import |
| Final wheel installed into `output/playwright/recovery-runtime`; import outside checkout, `python -m samsarix_workspace --version`, `python -m pip check` | Correct installed path, 0.3.0, no broken requirements |
| `py -3.11 -m pip_audit --path output/playwright/recovery-runtime/Lib/site-packages --skip-editable` | No known dependency vulnerabilities; unpublished Samsarix package excluded by advisory-index availability, not ignored findings |
| [CI 33400063011](https://github.com/Deathcharge/samsarix-workspace/actions/runs/33400063011) at `9e1cae2` | All seven jobs passed; Windows/Linux Python 3.11/3.13 and installed-wheel Chromium/Firefox jobs |

Final CI counts: 117 Python tests passed with one platform-specific skip on each matrix member; Linux branch coverage 91.15%, Windows 91.49%. Each of the three browser jobs passed 27 scenarios (81 total CI executions).

Final local artifacts at `output/playwright/recovery-reviewed-dist` (the subsequent evidence-only documentation commit does not change packaged files):

- Wheel SHA-256: `08a606e99ada9c0b604156a63488ff5b62cdcecacbcb85125f658edf0457ab6c`
- sdist SHA-256: `c8509bf41b2cb583571c17c218a74d9420431a8784b29f05e68fc39a7fb7b484`

Codex Security diff scan `f940220f-1a52-4cf9-aa54-78de76eec6b5` completed with no reportable findings for immutable `ab04742..f54d4cf`: all 14 generated source/config/browser-test review items plus the remaining 11 changed test/documentation files were accounted for. An independent architecture review supplied the source-cited trust model. This is scoped review evidence, not proof of universal security. Post-scan folder/empty-selection tests, the walker reliability fix, and final documentation were manually reviewed separately; the scan does not claim to cover later commits. The access/TAC connector was unavailable, but canonical local report finalization succeeded. No persistent security configuration was changed.

Logical commits: `f54d4cf` recovery implementation; `a930fee` packaged folder regression and release evidence; `9e1cae2` traversal reliability and empty-selection regression. Changed implementation surfaces are `trash.py`, `errors.py`, `workspace.py`, `api.py`, `cli.py`, `shell.py`, package/version metadata, and all three static browser files. Supporting changes cover the five Python test modules, browser fixture/document/recovery tests, README, API/onboarding docs, changelog, roadmap, and this record. The PR retains the exact final-head and post-merge CI evidence without implying that a source merge publishes a release.

Disposition: alpha release candidate for a single trusted local user, not a hosted service or externally validated offering. The permanent-only deletion P1 is closed; saved-version checkpoints remain the next local P1. WebKit/physical-device coverage is P2. No known locally actionable P0 remains in the reviewed core journey. Public package ownership/trusted publishing, provenance/signing decisions, legal review for commercial terms, and consented external pilot participation remain owner-controlled gates. No package publication, production deployment, paid service, or outreach was performed.

## `0.4.0` saved-version recovery

Baseline reverified: clean `main` at `6e5729c3b774d8467b1cd60600a999b870ec053e`, with [post-merge CI 33401420685](https://github.com/Deathcharge/samsarix-workspace/actions/runs/33401420685) and dependency graph successful. Local `python -m pytest --tb=short`: 117 passed, one Windows FIFO skip, 91.49% branch-aware coverage. Ruff and Mypy passed. The prior goal turn was concrete progress: Trash was implemented, reviewed, merged, and verified; saved-overwrite recovery remained the next P1.

### Product decision

The [Nextcloud version-control guide](https://docs.nextcloud.com/server/stable/user_manual/en/files/version_control.html) describes version restoration and bounded automatic expiration. The [VS Code history guide](https://code.visualstudio.com/docs/sourcecontrol/history) shows local saves alongside file history. Checked 2026-08-31: these support recoverable saves as an established workflow, not evidence of Samsarix demand or feature parity.

The chosen journey is **save → preview prior/current disk contents → restore a new copy or confirm guarded replacement → recover the replaced contents while retention permits**. It targets accidental overwrites in notes, drafts, Markdown, and small configuration files without requiring Git, a database, or external services.

Design and limits:

- A changed app overwrite checkpoints the prior bounded UTF-8 bytes before active replacement. Creation/no-op saves do not create versions. Disk contents are checked again after checkpoint I/O; a new target is created exclusively even without an explicit create-only flag.
- The owned `.samsarix-history` store contains immutable original paths, UTC checkpoint timestamps, sequence ordering, sizes, SHA-256 digests, and content. It shares bounded metadata/link guards with Trash but has independent retention: 50 MiB / 200 versions / 20 per original path by default.
- Oldest checkpoints expire after a new checkpoint is flushed. Staging may temporarily use one extra checkpoint plus metadata. Checkpoint/retention failure blocks the active write, and incomplete/excess records block repeated growth. A failed active write may still add a useful checkpoint and expire old ones; this is explicit, not an all-filesystem transaction claim.
- History is path-based provenance, not inferred file identity. Renames/deletions do not change recorded paths; **All files** keeps those versions discoverable. Reusing a path shares its history. No external writer monitoring, first-create snapshot, unsaved-keystroke capture, or folder timeline is promised.
- Preview verifies the content digest. Restore-as-copy requires an unused path; replacement requires the previewed current ETag and checkpoints the replaced contents first. Dirty editors keep their text and original ETag; clean editors reload the restored file. User confirmation precedes in-place replacement or version removal.
- History contains unencrypted prior content and names. Purging Trash or permanently removing an active file does not erase separate checkpoints. Retention is not secure erasure, encryption, or a backup. One trusted local user/process/root remains the boundary.

Implemented: storage, API, virtual commands, history browser panel with read-only comparison, inline failure/retry, copy collision handling, confirmation/cancellation, and draft preservation. No runtime dependency or provider cost was added. New tests cover persistence, quotas/retention, corruption/hash/link boundaries, failed checkpoint/write, stale restore, an intervening host edit, and the browser-to-disk journey.

Intermediate verification (not final release acceptance): Python 148 passed / one platform skip, 92.36% coverage; Ruff, Mypy, and JavaScript syntax checks passed. All 66 source browser executions passed in Chromium/Firefox, including 12 new history checks. Initial failures were the expected expanded command-allowlist assertion and a test client using an intentionally rejected Host; both test expectations/setup were corrected without relaxing production guards. Packaged-artifact, independent review, and exact-head CI checks remain required before merge. Final evidence will be added here and in the PR.

### Packaged acceptance and cross-browser follow-up

Runtime revision: `8c3f59c56595e37ed4804299c8378b1879c03789`, following history implementation `79c438ee0692c3e8fbd86f6be27fd6ef33d127d1`, in [PR #14](https://github.com/Deathcharge/samsarix-workspace/pull/14). The following commands use `output/playwright/lifecycle-env/Scripts/python.exe` (Python 3.11.9) unless another interpreter is specified. Browser fixtures assert that installed-wheel checks import from site-packages rather than this checkout.

| Command / gate | Observed result |
| --- | --- |
| `python -m ruff check samsarix_workspace tests e2e` | Passed |
| `python -m ruff format --check samsarix_workspace tests e2e` | Passed, 22 files |
| `python -m mypy samsarix_workspace` | Passed, 10 source files |
| `python -m pytest --tb=short` from the checkout | 148 passed, one Windows FIFO skip, 92.36% branch-aware coverage, 35.28 seconds |
| `node --check samsarix_workspace/static/app.js` and `git diff --check` | Passed |
| `python -m pytest e2e/test_editor.py -o addopts= --browser chromium --browser firefox --browser webkit -k non_json --tb=short` | 9 passed, 42 deselected, 30.88 seconds |
| `python -m build --outdir output/playwright/history-reviewed-dist` | Isolated sdist and wheel builds passed |
| `py -3.11 -m twine check output/playwright/history-reviewed-dist/samsarix_workspace-0.4.0-py3-none-any.whl output/playwright/history-reviewed-dist/samsarix_workspace-0.4.0.tar.gz` | Both passed |
| `python -m pytest --tb=short` from `output/playwright/history-reviewed-sdist/samsarix_workspace-0.4.0`, extracted from that sdist | 148 passed, one Windows FIFO skip, 92.36% branch-aware coverage, 36.26 seconds |
| `python -m pytest C:/Users/Andrew/Helix/helix-web-os/e2e -o addopts= --browser chromium --browser firefox --browser webkit --tracing retain-on-failure --screenshot only-on-failure --output C:/Users/Andrew/Helix/helix-web-os/output/playwright/history-reviewed-wheel --tb=short` from `output/playwright/wheel-check` with `SAMSARIX_TEST_INSTALLED=1` | 99 passed, 397.62 seconds; all three engines exercised the installed wheel |
| Wheel installed into clean runtime-only `output/playwright/history-runtime`; import from outside checkout, `python -m samsarix_workspace --version`, `python -m pip check` | Site-packages path verified, version 0.4.0, no broken requirements |
| `py -3.11 -m pip_audit --path output/playwright/history-runtime/Lib/site-packages --skip-editable` | No known dependency vulnerabilities; Samsarix is unavailable in the PyPI advisory index and cannot itself be audited there |
| [CI 33407552656](https://github.com/Deathcharge/samsarix-workspace/actions/runs/33407552656) at `8c3f59c` | All eight jobs passed: Python 3.11/3.13 on Linux/Windows and four installed-wheel browser jobs |

CI unit results are 148 passed / one platform skip per matrix member, with 92.07% Linux and 92.36% Windows branch coverage. Browser jobs each pass 33 scenarios (132 CI executions total). A read-only CI log request briefly timed out during its TLS handshake; retry retrieved the passing logs without rerunning or altering the jobs.

The exploratory WebKit run against the first wheel passed 30 scenarios and failed three non-JSON error-response cases. WebKit's `Response.json()` rejected malformed JSON with a DOMException named `SyntaxError`, not a JavaScript `SyntaxError` instance; the shared handler incorrectly classified HTTP/authentication errors as a network failure. Draft contents were retained. Parsing `await response.text()` with JavaScript `JSON.parse` now keeps syntax and transport failures distinct. All nine targeted cases pass across Chromium, Firefox, and WebKit. This was a reliability regression discovered by extending verification, not a claimed security finding. The new WebKit CI job runs the same 33 scenarios without loosening assertions. [Playwright's browser documentation](https://playwright.dev/python/docs/browsers) distinguishes its patched WebKit from branded Safari; macOS and physical Apple-device acceptance remain unperformed.

Headed Playwright verification also exercised save → prior/current preview → restore-as-copy and checked the real files: the original file retained the current edit, and the new copy contained the earlier bytes. Desktop 1280×900 and mobile 390×844 screenshots were inspected. Evidence remains in ignored `output/playwright/history-manual/history-desktop-final.png` and `history-mobile-final.png`. The dedicated browser session and identified test server were stopped; only disposable test workspaces were used. The upstream Starlette/httpx deprecation warning remains visible rather than suppressed.

Final local artifact SHA-256 in `output/playwright/history-reviewed-dist` (identifies these exact files, not future rebuilds):

- `samsarix_workspace-0.4.0-py3-none-any.whl`: `9519fa3ecae0326810d5ce5a11a2b26fa95f964d28d8ee08c9647a47b8287d58`
- `samsarix_workspace-0.4.0.tar.gz`: `900d8c5b0a5149f4d539c1ec5647cd66bb3a4817e78548f3129ed48664aa5b74`

Later evidence/rollback documentation changes do not change the packaged files. Backups and safe rollback are documented in [Getting started](GETTING_STARTED.md#backups-and-rollback): stop the server, retain complete protected copies, verify a disposable copy, and pair an older wheel with its matching pre-upgrade backup. In particular, do not point 0.3.0 at an upgraded live root because that version does not hide `.samsarix-history`.

### Review scope and disposition

Codex Security scan `09195769-0ab7-441f-8572-476ddf64cd81` sealed successfully for immutable `6e5729c..79c438e` with no reportable findings. Parent review accounted for all 13 generated source/config/browser items and nine additional changed test/documentation files. An independent fresh-context architecture review mapped 18 effective resources and verified 162 source citations. However, the completed tool artifact retained `coverage.completeness=partial` and an earlier architecture-reconciliation deferral despite accepting the final model and coverage surface. The sealed artifact is preserved unchanged: this evidence must not be called an unqualified complete-coverage sign-off. The access/TAC connector was unavailable. Later WebKit parsing/CI and documentation changes are outside that immutable scan; their diff and regressions were reviewed separately. No persistent security configuration was changed.

CodeRabbit acknowledged one included manual review request, but the latest status is a successful **review skipped** result for the repository's star threshold, with no submitted review or inline findings. A green status is not an external approval. No additional paid review was requested. Final exact-head and post-merge CI URLs belong in PR #14, avoiding a self-referential documentation commit.

Changed implementation surfaces: new `history.py` and shared `recovery.py`; `workspace.py`, `trash.py`, `api.py`, `shell.py`; package/version metadata; all three static browser files; and `.github/workflows/ci.yml`. Tests cover history, virtual commands, CLI version, and the browser journey. README, changelog, roadmap, API reference, onboarding, and this record describe the implemented limits. Logical commits are `79c438e` (saved-version recovery), `8c3f59c` (WebKit response handling and CI), followed by the evidence/rollback documentation commit.

Disposition: **alpha release candidate for one trusted local user**, with the saved-overwrite-recovery P1 implemented. It is not a hosted service, backup product, publicly published package, or externally validated competitive offering. No known locally actionable P0 remains in the exercised core journey. History consumes bounded additional local storage and retains unencrypted prior contents and names; normal purge is not secure erasure. No runtime dependency, provider bill, telemetry, public deployment, package publication, or outreach was added. CI now has one additional browser job. AGPL-3.0-only and Samsarix LLC/contact/support metadata are unchanged.

## `0.4.1` first-run reliability and pilot release evidence

Baseline reverified at clean `main` `2bebb9230b03551adb6aa60b5b0196b8c6fc8195`: all eight [post-merge CI jobs](https://github.com/Deathcharge/samsarix-workspace/actions/runs/33409490713) and the dependency graph passed, no open GitHub issues were returned, and local tests passed 148 / one Windows FIFO skip with 92.36% coverage. The preceding goal turn made concrete progress by merging saved-version recovery; it was not a no-progress or blocked turn.

The next user is an evaluator outside the developer checkout. The existing candidate had a usable recovery workflow, but artifact identity, dependency inventory, and installation acceptance were assembled manually. Official [pip installation reporting](https://pip.pypa.io/en/stable/reference/installation-report/), [separate-interpreter management](https://pip.pypa.io/en/stable/topics/python-option/), and [CycloneDX environment inventory](https://cyclonedx-bom-tool.readthedocs.io/en/latest/usage.html) support a small, maintainer-only evidence pipeline. These sources establish tooling capabilities, not user demand. [SLSA provenance](https://slsa.dev/spec/v1.2/provenance) is deliberately not claimed for this unsigned local evidence.

Adversarial first-run checks also reproduced an ordinary initialization race that overwrote a competing `WELCOME.md`, following a dangling welcome symlink, misleading success for a welcome directory, and an active-write flush failure that left a staged file behind. Six new regressions failed before the fix; two of those also establish the tightened initialization contract for flush and private-store validation. These are concrete reliability/path-behavior issues, not claims of remote exploitation by a hostile OS actor.

Implemented decisions:

- `init` now uses `Workspace.write_file(..., create_only=True)`, preserves a concurrent regular file, rejects blocked/nonregular welcome entries and unrecognized recovery stores, and returns a useful nonzero error. It shares normal quotas instead of having a separate unchecked write path.
- The workspace writer records its temporary filename before write/flush/fsync, so an ordinary failed flush can remove the stage. No arbitrary-power-loss transaction or hostile-local-writer guarantee was added.
- Maintainer release tooling operates on a clean pinned Git archive, excluding ignored build state and untracked documents. Build tools remain separate from the application and are never exposed through the virtual terminal/API.
- Two runtime-only venvs verify installation, exact wheel hashes, dependency closure, and a hash-locked reinstall. A real loopback smoke journey checks installed UI/save/History/Trash behavior against disposable files and shuts down afterward.
- CycloneDX 1.6 output is schema-validated, matched to the actual runtime inventory, and generated twice to check stable bytes in that environment. Raw pip URLs/private paths are not copied into the public evidence record.
- The bundle includes source/tool/runtime metadata, artifact sizes/hashes, a bounded standalone read-only verifier, and a consent-conscious evaluation guide. It is not a signature, publisher authentication, universal lock, vulnerability assessment, license-compliance proof, or public release.
- Linux/Windows Python 3.13 CI runs this pipeline using unchanged read-only permissions. Existing unit and browser gates remain. No credentials, hosted service, telemetry, runtime dependency, signing, public publication, or user outreach were added.

Initial verification: all 198 Python tests passed with one Windows FIFO skip and 92.54% application branch coverage; 44 of those exercise release-tool integrity/error contracts. Ruff passes for application/tests/browser/tools, all 26 Python files are formatted, Mypy passes 13 application/tool files, and JavaScript syntax/diff checks pass. The installed-runtime smoke prototype passed against the prior 0.4.0 wheel using only runtime dependencies. Exact 0.4.1 snapshot-build, lock/SBOM, installed-wheel/browser, review, and CI acceptance remain required before merge and will be recorded below.

## Next best work

The next release should favor reliability over breadth:

1. **P1 / owner coordination:** run a small external pilot against the exact wheel and capture consented, privacy-preserving task-success/support evidence; prioritize usability follow-ups from that evidence. No user contact or demand is invented.
2. **P1 / publication gate:** settle package-index ownership, trusted publishing, provenance/signing, and commercial-license legal review before authorizing a public prerelease. Locally prepared artifacts and source merges are not publication.
3. **P2:** verify macOS and physical Apple devices, then expand interruption/longer-running usage tests based on real pilot failures. The current Windows/Linux and three-engine checks do not replace those environments.
4. **P2:** evaluate stronger cross-build reproducibility and owner-authorized signed provenance. The implemented per-runtime SBOM/hash evidence is not a signed attestation. Preserve matching application/workspace backups and the documented rollback boundary.
5. If hosted multi-user use becomes a real requirement, design identity, authorization, per-tenant roots, audit logging, CSRF/origin controls, and deployment isolation as a separate security phase—not as a flag on the local app.

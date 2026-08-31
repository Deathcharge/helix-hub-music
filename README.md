# Samsarix Workspace

Samsarix Workspace is a small, local-first browser workspace for persistent text files and safe virtual commands. Point it at a folder, open the browser UI, and create, edit, rename, move, inspect, or delete files without giving the browser an operating-system shell.

This repository was previously named `helix-web-os`; that history remains in Git. The product and company identity are now **Samsarix Workspace** by **Samsarix LLC**.

> **Maturity:** `0.2.1` alpha release candidate. The primary local review workflow is implemented and tested. It is not a hosted multi-user IDE, an AI platform, or a replacement for a system terminal.

## What works

- Persistent, sandboxed file and folder operations under one configured root
- UTF-8 editor with bounded workspace content search, multi-file import, and current-document download
- Safe basic Markdown preview that renders through DOM text nodes and never executes raw document HTML
- Tab-scoped draft recovery plus an explicit reload-or-overwrite flow for disk conflicts
- Atomic writes, per-file and total-storage quotas, and bounded file listings
- A virtual terminal for `ls`, `cat`, `head`, `tail`, `wc`, `find`, `grep`, `mkdir`, `touch`, `mv`, and `rm`
- FastAPI JSON API with a stable error envelope and OpenAPI document
- Local-only binding by default; bearer-token requirement for non-loopback binding
- Responsive, keyboard-accessible browser UI with no frontend build step or third-party CDN
- Python 3.11–3.13 packaging, type checks, security regression tests, and CI

The virtual terminal dispatches an explicit in-process allowlist. It does **not** invoke PowerShell, Bash, `cmd.exe`, subprocesses, `eval`, environment expansion, or shell redirection.

## Quick start

Requirements: Python 3.11 or newer.

```bash
git clone https://github.com/Deathcharge/samsarix-workspace.git
cd samsarix-workspace
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS or Linux
source .venv/bin/activate
```

Install and initialize a separate workspace folder:

```bash
python -m pip install -e .
samsarix-workspace init ../my-workspace
samsarix-workspace serve ../my-workspace --open
```

Then open `http://127.0.0.1:8765`. Your files remain in `../my-workspace`; uninstalling the package does not remove them.

Use **Import** to bring one or more UTF-8 text files into the root (or a selected folder), search their contents from the sidebar, open a result at its matching line, preview Markdown, edit, and download the current document. Unsaved text is retained only in this browser tab for reload recovery; saving still requires an explicit action.

You can keep typing during a save: only the submitted text is acknowledged as saved, and newer edits remain unsaved. Opening another file waits for a save to finish. Failed opens preserve your current document, and conflict choices never silently authorize replacing external changes.

You can also run the module form:

```bash
python -m samsarix_workspace serve ../my-workspace
```

## Safe network use

The default listener is `127.0.0.1` and does not require a token. A non-loopback listener is refused unless `SAMSARIX_WORKSPACE_TOKEN` contains at least 20 characters:

```powershell
$env:SAMSARIX_WORKSPACE_TOKEN = "replace-with-a-long-random-secret"
samsarix-workspace serve ../my-workspace --host 0.0.0.0 --allowed-host workspace.example
```

```bash
export SAMSARIX_WORKSPACE_TOKEN="replace-with-a-long-random-secret"
samsarix-workspace serve ../my-workspace --host 0.0.0.0 --allowed-host workspace.example
```

Replace `workspace.example` with the hostname clients actually use; repeat `--allowed-host` for aliases. For any untrusted network, put the service behind a TLS reverse proxy and network access controls. The built-in token is a single-workspace gate, not multi-user identity or tenant isolation. Tokens are ASCII secrets read from the environment, never from a CLI argument, and the browser retains a submitted token only in tab-scoped session storage.

## Deliberate limits

Defaults are conservative:

| Limit | Default |
| --- | ---: |
| Individual UTF-8 file | 1 MiB |
| Workspace regular-file storage | 50 MiB |
| Listed entries | 2,000 |
| HTTP request body | 1.25 MiB |
| Text scanned per search | 10 MiB |
| Active virtual-terminal sessions | 128 |
| Session idle lifetime | 6 hours |

Symbolic links, hard-linked files, and special files are not followed or opened. File paths use forward slashes and cannot be absolute or contain `.` or `..` segments. The app does not upload files to Samsarix or any third party.

Current non-goals:

- Binary or rich-media editing
- Real operating-system command execution
- Code execution, kernels, language servers, Git UI, or package installation
- Cloud sync, collaboration, accounts, organizations, billing, or telemetry
- AI chat or model-provider integration
- Background autosave, trash, or version history

Those boundaries are part of the security model, not missing claims hidden behind marketing language.

## API

The OpenAPI document is available at `/openapi.json`. The versioned endpoints are:

- `GET /healthz`
- `GET /api/v1/workspace`
- `GET /api/v1/files`
- `GET /api/v1/search`
- `GET|PUT /api/v1/file`
- `POST /api/v1/folders`
- `POST /api/v1/move`
- `DELETE /api/v1/entry`
- `POST /api/v1/terminal/execute`

See the [API reference](https://github.com/Deathcharge/samsarix-workspace/blob/main/docs/API_REFERENCE.md) for payloads and errors.

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff check samsarix_workspace tests e2e
python -m ruff format --check samsarix_workspace tests e2e
python -m mypy samsarix_workspace
python -m pytest
python -m build
```

The test gate requires at least 90% branch-aware coverage of the Python package. See the [contribution guide](https://github.com/Deathcharge/samsarix-workspace/blob/main/CONTRIBUTING.md) for contribution and sign-off rules.

Browser acceptance tests run against a real loopback server and disposable files:

```bash
python -m pip install -e ".[dev,browser]"
python -m playwright install chromium firefox
python -m pytest e2e -o addopts= --browser chromium --browser firefox --tracing retain-on-failure --screenshot only-on-failure --output output/playwright/local
```

The separate browser suite does not replace or lower the Python coverage gate. CI runs Chromium on Windows/Linux and Firefox on Linux; no browser-testing dependencies are required to run the product.

## Product and security notes

- [Productization record](https://github.com/Deathcharge/samsarix-workspace/blob/main/docs/PRODUCTIZATION.md) — forensic baseline, product decision, threat model, completed work, and deferred backlog
- [Getting started](https://github.com/Deathcharge/samsarix-workspace/blob/main/docs/GETTING_STARTED.md) — installation and operating guide
- [Security policy](https://github.com/Deathcharge/samsarix-workspace/blob/main/SECURITY.md) — supported version, safe deployment, and private reporting
- [Licensing guide](https://github.com/Deathcharge/samsarix-workspace/blob/main/LICENSING.md) — practical AGPL explanation and credit expectations

## Support

- Product and business inquiries: [contact@samsarix.com](mailto:contact@samsarix.com)
- Support and security reports: [support@samsarix.com](mailto:support@samsarix.com)
- Bugs and feature requests: [GitHub Issues](https://github.com/Deathcharge/samsarix-workspace/issues)

## License

Copyright © 2026 Samsarix LLC.

Samsarix Workspace is licensed under the [GNU Affero General Public License v3.0 only](https://github.com/Deathcharge/samsarix-workspace/blob/main/LICENSE). If you modify it and let users interact with that version over a network, the AGPL generally requires offering those users the corresponding source. See the [licensing guide](https://github.com/Deathcharge/samsarix-workspace/blob/main/LICENSING.md); this summary is not legal advice.

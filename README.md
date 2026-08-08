# Samsarix Workspace

Samsarix Workspace is a small, local-first browser workspace for persistent text files and safe virtual commands. Point it at a folder, open the browser UI, and create, edit, rename, move, inspect, or delete files without giving the browser an operating-system shell.

This repository was previously named `helix-web-os`. The GitHub URL still uses that legacy name, but the product and company identity are now **Samsarix Workspace** by **Samsarix LLC**.

> **Maturity:** `0.1.0` alpha release candidate. The primary local workflow is implemented and tested. It is not a hosted multi-user IDE, an AI platform, or a replacement for a system terminal.

## What works

- Persistent, sandboxed file and folder operations under one configured root
- UTF-8 text editor with manual save, unsaved-state warning, and optimistic conflict detection
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
cd helix-web-os
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
| Active virtual-terminal sessions | 128 |
| Session idle lifetime | 6 hours |

Symbolic links, hard-linked files, and special files are not followed or opened. File paths use forward slashes and cannot be absolute or contain `.` or `..` segments. The app does not upload files to Samsarix or any third party.

Current non-goals:

- Binary or rich-media editing
- Real operating-system command execution
- Code execution, kernels, language servers, Git UI, or package installation
- Cloud sync, collaboration, accounts, organizations, billing, or telemetry
- AI chat or model-provider integration
- Autosave or version history

Those boundaries are part of the security model, not missing claims hidden behind marketing language.

## API

The OpenAPI document is available at `/openapi.json`. The versioned endpoints are:

- `GET /healthz`
- `GET /api/v1/workspace`
- `GET /api/v1/files`
- `GET|PUT /api/v1/file`
- `POST /api/v1/folders`
- `POST /api/v1/move`
- `DELETE /api/v1/entry`
- `POST /api/v1/terminal/execute`

See [docs/API_REFERENCE.md](docs/API_REFERENCE.md) for payloads and errors.

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff check samsarix_workspace tests
python -m ruff format --check samsarix_workspace tests
python -m mypy samsarix_workspace
python -m pytest
python -m build
```

The test gate requires at least 90% branch-aware coverage of the Python package. See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution and sign-off rules.

## Product and security notes

- [Productization record](docs/PRODUCTIZATION.md) — forensic baseline, product decision, threat model, completed work, and deferred backlog
- [Getting started](docs/GETTING_STARTED.md) — installation and operating guide
- [Security policy](SECURITY.md) — supported version, safe deployment, and private reporting
- [Licensing guide](LICENSING.md) — practical AGPL explanation and credit expectations

## Support

- Product and business inquiries: [contact@samsarix.com](mailto:contact@samsarix.com)
- Support and security reports: [support@samsarix.com](mailto:support@samsarix.com)
- Bugs and feature requests: [GitHub Issues](https://github.com/Deathcharge/samsarix-workspace/issues)

## License

Copyright © 2026 Samsarix LLC.

Samsarix Workspace is licensed under the [GNU Affero General Public License v3.0 only](LICENSE). If you modify it and let users interact with that version over a network, the AGPL generally requires offering those users the corresponding source. See [LICENSING.md](LICENSING.md); this summary is not legal advice.

# Getting started

## 1. Choose two folders

Keep the application checkout and your editable workspace separate. For example:

```text
projects/
├── helix-web-os/       # application checkout (legacy repository name)
└── my-workspace/       # files shown in Samsarix Workspace
```

The application only reads and writes below the workspace folder you pass to `serve`.

## 2. Install from this checkout

Python 3.11 or newer is required.

```bash
python -m venv .venv
python -m pip install -e .
```

Activate `.venv` before the install command if your system does not use the environment's Python automatically. For contributor tools, install `-e ".[dev]"` instead.

## 3. Initialize and run

```bash
samsarix-workspace init ../my-workspace
samsarix-workspace serve ../my-workspace --open
```

`init` creates `WELCOME.md` only when it does not already exist. `serve` creates the chosen directory if necessary and starts at `http://127.0.0.1:8765`.

Use `Ctrl+S` (or `Cmd+S`) to save the open document. The yellow dot means the editor differs from the saved file. If another process changed the file after it was opened, saving returns a conflict instead of overwriting the newer content.

## 4. Use the virtual terminal

Run `help` to see the current allowlist. Paths are relative to the workspace and `/` is its virtual root.

```text
/$ mkdir notes
/$ cd notes
/notes$ touch idea.md
/notes$ ls
idea.md
```

`echo hello > file.txt` prints the literal text; it does not redirect. Commands such as `python`, `bash`, `powershell`, `curl`, or `git` are intentionally unavailable.

## Configuration

| Environment variable | Purpose |
| --- | --- |
| `SAMSARIX_WORKSPACE_ROOT` | Default folder for `serve` when no path argument is supplied |
| `SAMSARIX_WORKSPACE_TOKEN` | Bearer token required by the API and UI; mandatory for non-loopback binds |

CLI options:

```text
samsarix-workspace serve [path] [--host HOST] [--port PORT] [--open]
```

The default host is `127.0.0.1`; the default port is `8765`. Use `--log-level warning` to reduce request logging.

## Recovery and data safety

- Files are stored directly in the selected folder, not in an application database.
- Saves write a temporary sibling file, flush it, and atomically replace the target.
- Unsaved editor text exists only in the browser tab. Copy it elsewhere before reloading after a server outage.
- Deletes are permanent. Folder deletion requires an explicit recursive confirmation in the UI or `rm -r` in the virtual terminal.
- The workspace root cannot be renamed or deleted through the API.
- Back up important folders with your normal backup or version-control workflow.

## Troubleshooting

### The browser asks for a token

Enter the exact value of `SAMSARIX_WORKSPACE_TOKEN` from the server environment. The value remains only in `sessionStorage` for the current tab.

### `edit_conflict` appears when saving

Another process changed or removed the file. Copy your unsaved text, refresh the file, reconcile the two versions, and save again.

### A file is blocked

The editor supports bounded UTF-8 regular files only. Binary files, files over 1 MiB, symbolic links, hard-linked files, and filesystem special files are not opened.

### The server refuses `--host 0.0.0.0`

Set a random `SAMSARIX_WORKSPACE_TOKEN` of at least 20 characters. For untrusted networks, also terminate TLS and restrict network access in a reverse proxy or tunnel.

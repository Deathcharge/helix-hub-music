# Getting started

## 1. Choose two folders

Keep the application checkout and your editable workspace separate. For example:

```text
projects/
├── samsarix-workspace/ # application checkout
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
| `SAMSARIX_WORKSPACE_ALLOWED_HOSTS` | Comma-separated accepted Host values when the app factory is configured from the environment |

## Review a set of documents

1. Choose **Import** in the file sidebar and select one or more UTF-8 text files. Selecting a folder first imports into that folder.
2. Type in **Search file contents**. Results show the file, line, column, and a bounded matching preview; choose one to open the exact location.
3. For `.md` or `.markdown` files, choose **Preview**. The built-in basic renderer does not execute raw HTML or load document-provided assets.
4. Edit and save explicitly. You can continue typing while saving; newer text remains unsaved and recoverable until the next save. Navigation and file mutations wait for the in-flight save. If another process changed the file, choose whether to reload the disk version, keep editing, or overwrite the exact newer checkpoint. **Keep editing** does not authorize an overwrite on the next save.
5. Choose **Download** to export the current editor text, including unsaved edits when present.

One unsaved draft is retained in this browser tab's `sessionStorage` so a page reload can offer recovery. Closing the tab clears normal session storage. Samsarix Workspace does not send drafts, file contents, or usage telemetry to Samsarix LLC.

While a document opens, the previous editor is read-only; only the latest successful open replaces it. A failed open leaves the previous text, path, and draft intact. Restoring a draft whose disk version changed still requires explicit conflict resolution when saving.

CLI options:

```text
samsarix-workspace serve [path] [--host HOST] [--allowed-host HOST] [--port PORT] [--open]
```

The default host is `127.0.0.1`; the default port is `8765`. Use `--log-level warning` to reduce request logging.

## Recovery and data safety

- Files are stored directly in the selected folder, not in an application database.
- Saves write a temporary sibling file, flush it, and atomically replace the target.
- Unsaved editor text exists only in the browser tab. Copy it elsewhere before reloading after a server outage.
- Requests time out after 15 seconds. A timed-out save may already have reached disk; retry normally so the ETag conflict guard checks the result. There is no automatic retry of writes.
- Normal deletion moves disk content to persistent local Trash. Folder deletion requires recursive confirmation in the UI or `rm -r` in the virtual terminal. Links/special entries cannot be archived; their explicit permanent removal has no recovery.
- The workspace root cannot be renamed or deleted through the API.
- Back up important folders with your normal backup or version-control workflow.

## Recover a deleted file

1. Select a file and choose **Delete → Move to Trash**. Cancel leaves both the editor and file untouched. Unsaved edits are discarded only after successful deletion; Trash retains the disk version.
2. Open **Trash** in the top toolbar. Items remain available after a page reload or server restart using the same root.
3. Choose **Restore**, check the prefilled original path, and submit. If it is occupied or its parent is missing, the dialog explains why; choose an unused path under an existing parent. Restoring another file keeps the current editor and its unsaved draft.
4. To discard an archived item permanently, choose **Delete permanently** and confirm. This cannot be undone through the app and is not secure erasure.

The same virtual-terminal journey uses the ID returned by `rm` or listed by `trash`:

```text
rm notes/idea.md
trash
restore <id> notes/recovered.md
```

Replace `<id>` with the actual 32-character ID, without angle brackets. `restore <id>` uses the original path. `purge <id> --confirm` permanently removes an archived item; `rm --permanent [-r] <path>` bypasses Trash explicitly. These are virtual commands, not shell commands.

Trash content is limited to 50 MiB, 100 deletion records, and 2,000 contained files/folders in addition to the active workspace limits. It never auto-expires or silently evicts an older deletion. If full, new deletion fails and the live file remains; restore or explicitly purge an item to make room. Embedding applications can set `AppSettings.max_trash_bytes`, `max_trash_items` (1–1,000), and `max_trash_entries` (1–10,000); the CLI uses the defaults.

The reserved `.samsarix-trash` folder is private to the app's file API, not encrypted against the OS user. It contains original filenames and content. Do not edit it while the server runs, place it in a publicly shared folder, or point multiple server processes at the same workspace. Include it in backups when deleted content matters; it is not your OS Recycle Bin and cannot recover earlier permanent deletions or saved edit versions. Basic content, file modes, and modified times are copied on restore where supported; ownership, ACLs, alternate data streams, and every extended filesystem attribute are not promised.

Deletion uses a same-filesystem rename after flushing the metadata file; restore copies exclusively before removing the archive. Ordinary operation failures and restarts are handled, but arbitrary power loss, disk corruption, hostile local processes, and network-filesystem durability are not guaranteed. Restoring requires free space for both copies during the operation.

If a request times out, **refresh active files and Trash before retrying**. If restore fails, Trash remains but a partial destination may exist: inspect it or choose another unused path. If restoration succeeds with a cleanup warning, verify the restored copy before purging the retained record. An `incomplete` or unreadable item cannot be restored through the UI; inspect a backup/offline copy if needed before permanently deleting it. An unrecognized `.samsarix-trash` folder causes startup to fail without changing it; stop other processes, back it up, and rename it outside the app before retrying.

## Troubleshooting

### The browser asks for a token

Enter the exact value of `SAMSARIX_WORKSPACE_TOKEN` from the server environment. The value remains only in `sessionStorage` for the current tab.

### `edit_conflict` appears when saving

Another process changed or removed the file. Copy your unsaved text, refresh the file, reconcile the two versions, and save again.

### A file is blocked

The editor supports bounded UTF-8 regular files only. Binary files, files over 1 MiB, symbolic links, hard-linked files, and filesystem special files are not opened.

### The server refuses `--host 0.0.0.0`

Set a random ASCII `SAMSARIX_WORKSPACE_TOKEN` of at least 20 characters and pass at least one `--allowed-host` naming the hostname clients will use. Repeat the option for aliases. For untrusted networks, also terminate TLS and restrict network access in a reverse proxy or tunnel.

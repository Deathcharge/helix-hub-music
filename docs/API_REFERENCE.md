# API reference

The API is versioned under `/api/v1`. JSON failures use one envelope:

```json
{
  "error": {
    "code": "not_found",
    "message": "The requested entry does not exist."
  }
}
```

Validation failures may add a `details` array. Every request must use an accepted HTTP Host value. When `SAMSARIX_WORKSPACE_TOKEN` is configured, send `Authorization: Bearer <token>` to all `/api/v1` endpoints. `/`, `/assets/*`, `/openapi.json`, and `/healthz` remain unauthenticated so a client can load and display the unlock prompt, but they are still protected by Host validation.

## Health

`GET /healthz`

Returns the service name, version, and `ok` status. It does not expose the host workspace path.

## Workspace summary

`GET /api/v1/workspace`

Returns an opaque per-process workspace ID, display name, entry count, storage use, configured limits, and application version. The random ID distinguishes tab-scoped recovery drafts during the current server process without exposing or hashing the absolute host path.

## List entries

`GET /api/v1/files?path=&recursive=false`

- `path` is a workspace-relative folder; an empty value means the root.
- `recursive=true` returns the bounded recursive inventory used by the browser tree.
- Entries have `path`, `name`, `kind`, `size`, `modified_at`, and optional `etag` fields.
- `kind` is `file`, `directory`, `blocked_symlink`, `blocked_hardlink`, or `blocked_special`.
- `.samsarix-trash` is a reserved private-store name, including nested and Windows alias spellings. It is excluded from normal listings, search, and active storage totals; ordinary path APIs cannot access it.

## Read a file

`GET /api/v1/file?path=notes/idea.md`

Returns a `file` object with UTF-8 `content`, byte `size`, timestamp, and SHA-256 `etag`.

## Search file contents

`GET /api/v1/search?q=decision&path=&case_sensitive=false&limit=100`

Search walks regular UTF-8 files beneath `path` without following links. Each match contains `path`, one-based `line` and `column`, source-character `length`, and a bounded plain-text `preview`. The explicit span keeps Unicode case-folded matches addressable in the editor. The report also returns `scanned_files`, `scanned_bytes`, `skipped_files`, and `truncated`. Searches stop at the configured byte ceiling or result limit rather than consuming unbounded local resources; a truncated read can include one extra detection byte in `scanned_bytes`.

## Create or save a file

`PUT /api/v1/file`

```json
{
  "path": "notes/idea.md",
  "content": "A durable thought.\n",
  "expected_etag": null,
  "create_only": true
}
```

Use `create_only: true` for creation so an existing path returns HTTP 409 instead of being overwritten. Guard precedence is deterministic: if the path exists, `create_only` returns `already_exists` before `expected_etag` is checked; if the path is missing, any non-null `expected_etag` returns `edit_conflict`. Send the exact 64-character ETag from the most recent read when saving an open file. A mismatch returns HTTP 409 with `edit_conflict`. An intentional replacement should first read the current file and then send its ETag; omitting both guards is supported for backwards compatibility but is not recommended.

## Create a folder

`POST /api/v1/folders`

```json
{ "path": "notes" }
```

The parent folder must already exist.

## Move or rename

`POST /api/v1/move`

```json
{
  "source": "notes/idea.md",
  "destination": "notes/decision.md"
}
```

The operation never overwrites an existing destination.

## Delete

`DELETE /api/v1/entry?path=notes/decision.md&recursive=false`

Since `0.3.0`, regular files and folders move to local Trash by default. Non-empty folders require `recursive=true`; the root is rejected. Optional `expected_etag=<64-character SHA-256>` protects an opened file against stale deletion (HTTP 409 `edit_conflict`).

The response is `{ "deleted": true, "permanent": false, "trash_item": { ... } }`. A Trash item contains an opaque 32-character lowercase hex `id`, workspace-relative original `path`, `kind`, UTC `deleted_at`, content `bytes`, contained `entries`, format `version`, and `state: "ready"`.

**Compatibility change:** clients requiring immediate permanent removal must explicitly send `permanent=true`. That response has `permanent: true` and `trash_item: null`; it cannot be restored. Blocked leaf links require this explicit mode and only the link is removed; unsupported reparse entries may still be refused. A tree containing links or special files cannot move to Trash.

Trash has separate byte, item, and contained-entry limits. A full store returns HTTP 413 `trash_full` and leaves the live source intact. No automatic eviction occurs. Disk/rename failures return `trash_failed`; inspect active files and Trash before retrying because a response may fail after the move succeeded.

## List Trash

`GET /api/v1/trash`

Returns `{ "trash": { "items": [...], "usage_bytes": 0, "entries": 0, "unavailable_items": 0, "limits": { "max_bytes": 52428800, "max_items": 100, "max_entries": 2000 } } }`.

Items are sorted newest first. `state` is `ready`, `incomplete` (metadata without content after interruption), or `unavailable`. Unavailable items have `path: null`, unknown size reported as zero, and a diagnostic `message`; aggregate size is a lower bound when any exist. Restore is unavailable for these entries and new deletion is blocked until inspected or purged. Invalid store ownership or structure fails closed instead of trusting arbitrary folders.

## Restore

`POST /api/v1/trash/{id}/restore`

Send `{}` to use the original path, or `{ "destination": "notes/recovered.md" }` to choose another. The parent must exist, active storage/entry quotas apply, and existing destinations return HTTP 409 `already_exists` without replacement. The result is `{ "entry": { ... }, "trash_retained": false }`.

Restore exclusively creates destination files/folders, retains Trash on copy failure, and consumes the item on success. Failed copies can leave a partial destination: inspect it or choose another path before retrying. If copying succeeds but archive cleanup fails, the response remains successful with `trash_retained: true`; the restored file is usable and the retained Trash record needs inspection. Repeating a completed restore normally returns 404 because the record was consumed. There is no automatic retry or overwrite mode.

## Permanently delete a Trash item

`DELETE /api/v1/trash/{id}?confirm=true`

Explicit confirmation is mandatory (`confirmation_required` otherwise). Success is `{ "purged": true }`; repeating it returns 404. Purge does not trust the metadata's original path and can remove unreadable/incomplete records. `purge_failed` means deletion may be partial: refresh before retrying. This is ordinary filesystem removal, not guaranteed secure erasure.

All three recovery routes use the same optional bearer authentication and mandatory Host validation as the other API routes. Trash persists across server restarts under the chosen workspace root; it is not tab-scoped draft storage or an OS Trash implementation.

## Execute a virtual command

`POST /api/v1/terminal/execute`

```json
{
  "command": "ls notes",
  "session_id": null
}
```

The first response includes a server-issued UUID `session_id`. Return it for later commands to retain the virtual current directory. Unknown, expired, or evicted IDs return `session_expired`; a client should retry once with `null`.

Response fields are `session_id`, `output`, `cwd`, integer `exit_code`, and boolean `clear`. Command input and output are bounded. No operating-system process is started.

## Common status codes

| Status | Meaning |
| ---: | --- |
| 200/201 | Success |
| 400 | Invalid path, command, session, or operation |
| 401 | Missing or invalid bearer token |
| 404 | Entry, parent folder, or session not found |
| 409 | Existing destination, non-empty folder, edit conflict, or unavailable recovery data |
| 413 | Request, file, listing, workspace, or Trash quota exceeded |
| 415 | File is not UTF-8 text |
| 422 | JSON does not match the request schema |
| 500 | Filesystem operation failed; inspect state before retrying |

The machine-readable contract at `/openapi.json` is authoritative for field types.

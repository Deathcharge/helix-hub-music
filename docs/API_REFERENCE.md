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

Non-empty folders require `recursive=true`. The root path is rejected. Deletes are permanent.

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
| 409 | Existing destination, non-empty folder, or edit conflict |
| 413 | Request, file, listing, or workspace quota exceeded |
| 415 | File is not UTF-8 text |
| 422 | JSON does not match the request schema |

The machine-readable contract at `/openapi.json` is authoritative for field types.

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

Validation failures may add a `details` array. When `SAMSARIX_WORKSPACE_TOKEN` is configured, send `Authorization: Bearer <token>` to all `/api/v1` endpoints. `/`, `/assets/*`, `/openapi.json`, and `/healthz` remain public so a client can load and display the unlock prompt.

## Health

`GET /healthz`

Returns the service name, version, and `ok` status. It does not expose the host workspace path.

## Workspace summary

`GET /api/v1/workspace`

Returns the workspace display name, entry count, storage use, configured limits, and application version.

## List entries

`GET /api/v1/files?path=&recursive=false`

- `path` is a workspace-relative folder; an empty value means the root.
- `recursive=true` returns the bounded recursive inventory used by the browser tree.
- Entries have `path`, `name`, `kind`, `size`, `modified_at`, and optional `etag` fields.
- `kind` is `file`, `directory`, `blocked_symlink`, `blocked_hardlink`, or `blocked_special`.

## Read a file

`GET /api/v1/file?path=notes/idea.md`

Returns a `file` object with UTF-8 `content`, byte `size`, timestamp, and SHA-256 `etag`.

## Create or save a file

`PUT /api/v1/file`

```json
{
  "path": "notes/idea.md",
  "content": "A durable thought.\n",
  "expected_etag": null
}
```

Omit or set `expected_etag` to `null` for creation. Send the exact 64-character ETag from the most recent read when saving an open file. A mismatch returns HTTP 409 with `edit_conflict`.

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

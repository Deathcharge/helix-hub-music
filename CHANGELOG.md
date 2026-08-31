# Changelog

Notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

No unreleased changes yet.

## [0.4.0] - 2026-08-31

### Added

- Persistent pre-overwrite UTF-8 checkpoints, bounded by separate global bytes/items and per-original-path retention
- History listing, content preview, restore-as-copy, ETag-guarded replacement, and confirmed single-version removal in the API and virtual terminal
- Browser comparison of saved/current disk contents, inline error/retry states, and restoration that preserves unsaved editor drafts
- Retention, restart, checksum, metadata/link boundary, failed checkpoint/write, and intervening disk-edit regressions

### Changed

- `.samsarix-history` is reserved alongside Trash; both stores share bounded metadata and filesystem guards
- Saves recheck the disk content after checkpoint creation; newly created targets use exclusive creation even without an explicit create-only flag
- Existing binary/oversized files cannot be overwritten through text saves because they cannot be safely checkpointed as bounded UTF-8 content
- History retention may run when preparing a save that subsequently fails; the current file remains unchanged and its checkpoint is retained

## [0.3.0] - 2026-08-31

### Added

- Persistent, bounded local Trash for regular files and complete folders, with restore to an unused original or alternate path
- Recovery UI with loading, empty, retry, collision, unavailable-item, quota, and explicit permanent-deletion states
- Authenticated Trash list/restore/purge API routes and virtual `trash`, `restore`, and confirmed `purge` commands
- Restart, interrupted move, partial restore, disk failure, byte/entry limits, private metadata, and Windows junction regression tests
- Browser-to-disk recovery acceptance cases, including dirty-editor preservation, stale deletion, and mobile layout

### Changed

- **Pre-1.0 API behavior change:** `DELETE /api/v1/entry`, `Workspace.delete`, and virtual `rm` now move regular entries to Trash by default; immediate deletion requires `permanent=true` or `rm --permanent`
- Open-file deletion includes an ETag guard; full Trash leaves live content intact and never evicts prior records
- `.samsarix-trash` is reserved and excluded from active browsing, content search, and usage totals
- In-process reads and mutations share a workspace lock; Windows junction/reparse points are blocked consistently
- Restore uses exclusive destination creation, retains archives on copy failure, and reports cleanup failures without discarding the restored result

### Fixed

- Recursive listing and quota accounting tolerate folders removed after enumeration; other folder metadata failures retain the structured error contract

## [0.2.1] - 2026-08-31

### Fixed

- Save acknowledgments no longer clear unsaved text typed during the request
- Pending or failed opens cannot pair the old editor text with a different path, and out-of-order responses cannot replace the latest selection
- Continuing or restoring a draft retains its original ETag instead of silently authorizing external-change replacement
- Explicit conflict overwrite includes the latest editor text; recreating a deleted file uses an atomic create-only guard
- Creating a file asks before discarding edits and preserves the old draft when creation fails
- In-flight file operations prevent conflicting navigation/mutations, and requests have a 15-second timeout with retryable recovery
- Non-JSON HTTP errors retain their status and authentication recovery instead of falsely reporting a disconnected server

### Added

- Repeatable browser-to-API-to-disk acceptance tests with controlled request delivery, temporary workspace isolation, and failure traces
- Chromium Windows/Linux and Firefox Linux CI jobs, independent of the Python coverage gate

## [0.2.0] - 2026-08-10

### Added

- Bounded full-workspace UTF-8 content search with matching line previews and resource accounting
- Browser multi-file import with fatal UTF-8 decoding, size checks, collision confirmation, and create-only writes
- Current-document download and dependency-free safe basic Markdown preview
- Tab-scoped unsaved-draft recovery and an explicit disk-conflict reload/overwrite dialog
- Host-header validation across every route and explicit allowed-host configuration for external serving

### Changed

- File creation is now create-only, preventing an existing document from being silently emptied
- Workspace summaries derive entry count and usage in one traversal; entry metadata uses one `lstat`
- Virtual command dispatch is persistent and introspectable, and tiny output ceilings are enforced exactly
- HTTP bearer tokens are restricted to ASCII and compared as constant-time byte strings
- Packaging metadata now requires the setuptools version that supports SPDX license expressions
- Unicode case-folded searches report exact source-character spans, including length-changing folds
- Create-only writes claim the destination atomically and workspace draft IDs no longer derive from host paths
- Package-index README links now resolve to canonical repository documentation

## [0.1.0] - 2026-07-28

### Added

- Installable `samsarix-workspace` Python package and CLI
- Persistent, sandboxed UTF-8 workspace with atomic writes, quotas, and ETag conflicts
- Responsive browser file tree, editor, explicit destructive confirmations, and status states
- Allowlisted virtual terminal with bounded server-issued sessions and no OS command execution
- FastAPI JSON API, stable errors, request-stream limits, and security headers
- Loopback-only default binding and mandatory bearer token for non-loopback binding
- Real unit and integration tests with a 90% branch-aware coverage gate
- Cross-platform GitHub Actions CI, wheel build, and installed-wheel smoke test
- Productization record, API guide, operating guide, security policy, and accurate limitations

### Changed

- Product and company identity migrated from Helix to Samsarix Workspace by Samsarix LLC
- License aligned to `AGPL-3.0-only`; stale MIT, Apache, proprietary, and customized BSL claims removed

### Removed

- Broken private `helix-unified` imports and unassembled chat bridge
- Orphan Next.js pages for unrelated prototype products
- Mock-only tests, inaccurate production claims, invented pricing, and broad requirements files

## Historical note

The former `1.0.0` tag predates a runnable standalone application and is not considered a Samsarix Workspace release. Git history remains the provenance record for that Helix-era material.

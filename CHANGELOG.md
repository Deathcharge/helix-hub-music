# Changelog

Notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

No unreleased changes yet.

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

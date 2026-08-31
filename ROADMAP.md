# Samsarix Workspace roadmap

This roadmap separates four gates: merge, release, publication, and flagship adoption. Passing one does not imply the next.

## Product boundary

Portfolio role: **standalone product candidate**. Develop this as a focused standalone product with its own distribution and support boundary. Integrate with the flagship through versioned contracts, not shared private source.
Planned repository identity: `Deathcharge/samsarix-workspace` (ready).

Current disposition: `0.2.0` document review and `0.2.1` editor reliability are merged in [PR #9](https://github.com/Deathcharge/samsarix-workspace/pull/9) and [PR #12](https://github.com/Deathcharge/samsarix-workspace/pull/12), with green cross-platform CI. The `0.3.0` local Trash increment adds recoverable deletion; publication and adoption remain separate gates. Exact verification belongs in the productization record and pull request.

## Stabilize the productized default

- Keep the default branch buildable from a clean checkout and preserve exact-head CI evidence.
- Keep Samsarix LLC branding, package identity, license metadata, and compatibility aliases internally consistent.
- Preserve the pre-productization default under a rollback ref before merging; do not delete legacy history.
- Release priority: preserve the reviewed source and cross-platform evidence, validate recovery with an external pilot, and complete distribution/signing decisions before a public prerelease.

## Release candidate

- Run a small user pilot against the exact packaged artifact.
- Instrument only truthful, privacy-respecting product signals and define support ownership.
- Promote from prerelease only after recovery, upgrade, and failure paths are demonstrated.

Current hardening backlog:

- No external user proof that a limited browser file workspace solves a recurring problem.
- Non-loopback bearer authentication is not a hosted or multiuser security design and lacks built-in TLS.
- OS-level race/path behavior and recursive deletion need adversarial validation on supported platforms.
- Public publication, signed provenance, and package-index ownership remain owner gates; local wheel/sdist builds and CI artifacts are implemented.
- Owner/legal review of provenance and commercial licensing terms remains prudent before publication; the repository's selected license is AGPL-3.0-only.

## Document review milestone (`0.2.0`)

- Bounded content search with path/line navigation and explicit scan accounting
- Safe browser import/download for UTF-8 artifacts
- Dependency-free basic Markdown preview with raw HTML treated as text
- Tab-scoped draft recovery and explicit external-edit conflict choices
- Host-header validation and create-only file creation
- Local gates passed: real-browser desktop/mobile and accessibility sanity checks, built-artifact installation, metadata validation, and dependency audit
- Merged in PR #9 at `bcafd5f`; exact-head Linux/Windows CI passed

## Editor reliability (`0.2.1`)

- Retain newer typing and draft content when an earlier save completes
- Make asynchronous open selection atomic; retain old content on failure
- Preserve ETag guards through draft restore and keep-editing conflict choices
- Exercise the full document-review journey and delayed-response failures in browser CI
- Bound stalled requests and retain manual, guarded retry behavior
- Merged at `ab04742`; all seven post-merge CI jobs passed

## Recoverable deletion (`0.3.0`)

- Persistent local Trash shared by UI, API, and virtual commands
- Restore to the original or an alternate unused path without overwriting
- Separate bounded recovery storage, no silent eviction, and explicit permanent purge
- Restart, interrupted-move, copy-failure, metadata-boundary, quota, and Windows junction coverage
- Inline failure/retry handling and preservation of other open editor drafts
- Honest limits: no saved-edit history, OS Trash integration, encryption, or backup guarantee

Next highest-value work is bounded saved-version checkpoints, then a small external pilot using the exact artifact and extended WebKit/real-device validation. Multi-user hosting, real shells, AI providers, and flagship integration remain separate designs rather than incremental toggles.

## Samsarix adoption

- Define a public API, event, schema, artifact, or deployment contract before connecting to Samsarix Unified.
- Add a consumer-owned contract fixture covering authentication, privacy, limits, errors, and version compatibility.
- Make one implementation canonical; remove or freeze duplicate behavior only after parity and rollback are proven.
- Record an owner, support level, compatibility window, and measurable adoption signal.

## Completion evidence

A milestone is complete only when its exact commit, commands and results, artifact digest, consumer or deployment, and rollback path are recorded in a pull request or release record. README claims must not exceed that evidence.

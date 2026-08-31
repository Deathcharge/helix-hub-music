# Samsarix Workspace roadmap

This roadmap separates four gates: merge, release, publication, and flagship adoption. Passing one does not imply the next.

## Product boundary

Portfolio role: **standalone product candidate**. Develop this as a focused standalone product with its own distribution and support boundary. Integrate with the flagship through versioned contracts, not shared private source.
Planned repository identity: `Deathcharge/samsarix-workspace` (ready).

Current disposition: `0.2.0` document review is merged in PR #9 with cross-platform CI. The `0.2.1` editor-lifecycle and browser-CI reliability increment is implemented; its exact-head review/merge, publication, and adoption remain separate gates.

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
- No release/publish path, immutable distribution, deployment profile, or operational telemetry.
- Brand and license change from baseline BSL to AGPL-3.0-only require owner/legal approval.

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
- Keep recoverable trash and version history as the next product increment; neither is implied by tab-scoped drafts

Next highest-value reliability work after `0.2.0` is recoverable trash/version checkpoints, then a small external user pilot. Multi-user hosting, real shells, AI providers, and flagship integration remain separate designs rather than incremental toggles.

## Samsarix adoption

- Define a public API, event, schema, artifact, or deployment contract before connecting to Samsarix Unified.
- Add a consumer-owned contract fixture covering authentication, privacy, limits, errors, and version compatibility.
- Make one implementation canonical; remove or freeze duplicate behavior only after parity and rollback are proven.
- Record an owner, support level, compatibility window, and measurable adoption signal.

## Completion evidence

A milestone is complete only when its exact commit, commands and results, artifact digest, consumer or deployment, and rollback path are recorded in a pull request or release record. README claims must not exceed that evidence.

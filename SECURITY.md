# Security policy

## Supported version

Samsarix Workspace is pre-1.0. Security fixes are provided on the latest commit of `main` and the latest published `0.1.x` release, if one exists. Older snapshots are not supported.

## Report a vulnerability

Email [support@samsarix.com](mailto:support@samsarix.com) with the subject `Samsarix Workspace security report`.

Please include the affected revision or version, operating system, configuration, reproduction steps, expected impact, and any proof-of-concept material. Avoid accessing other people's data, persistence, denial of service against shared systems, or public disclosure before Samsarix LLC has had a reasonable opportunity to investigate and coordinate a fix.

You should receive an acknowledgment when the report is reviewed. Response and remediation timing depends on severity and reproducibility; this project does not promise a fixed service-level agreement.

## Deployment boundary

The supported default is one trusted local user, one workspace root, and a listener on `127.0.0.1` or `::1`.

- Non-loopback binding requires `SAMSARIX_WORKSPACE_TOKEN` of at least 20 characters.
- Wildcard binding also requires an explicit `--allowed-host`; all routes reject unrecognized Host headers.
- Use TLS and network access controls for any untrusted network.
- The token is one shared secret, not user identity or tenant authorization.
- Do not expose a workspace containing secrets that the server process should not read.
- Run with the least-privileged operating-system account practical.
- The virtual terminal is not an OS sandbox; it is an allowlist that intentionally never starts processes.
- Symbolic links are rejected, but a hostile local process with the same filesystem permissions is outside the strong threat boundary.

See [docs/PRODUCTIZATION.md](docs/PRODUCTIZATION.md) for the full threat model and residual limitations.

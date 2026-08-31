# Contributing to Samsarix Workspace

Thank you for helping make the small local-workspace promise more reliable. Please keep proposals inside the product boundaries in [docs/PRODUCTIZATION.md](docs/PRODUCTIZATION.md), or open an issue before investing in a major scope change.

## Set up

```bash
git clone https://github.com/Deathcharge/samsarix-workspace.git
cd samsarix-workspace
python -m venv .venv
# Activate .venv with your shell before installing.
python -m pip install -e ".[dev]"
```

Create a focused branch and make the smallest coherent change. Do not commit workspace data, secrets, virtual environments, coverage output, or generated distributions.

## Required checks

```bash
python -m ruff check samsarix_workspace tests e2e
python -m ruff format --check samsarix_workspace tests e2e
python -m mypy samsarix_workspace
python -m pytest
node --check samsarix_workspace/static/app.js
python -m build
```

Tests must exercise the real implementation and keep branch-aware package coverage at or above 90%. UI changes should include a browser-flow check and screenshots in the pull request when appearance changes materially.

Run the browser-to-disk regressions for editor changes:

```bash
python -m pip install -e ".[dev,browser]"
python -m playwright install chromium firefox
python -m pytest e2e -o addopts= --browser chromium --browser firefox --tracing retain-on-failure --screenshot only-on-failure --output output/playwright/local
```

On Linux, use `python -m playwright install --with-deps chromium firefox` to install required system libraries too. Browser tests use a fresh loopback port and temporary workspace per test; they never point at your documents. Use `--headed` for interactive diagnosis. Keep the browser tools pinned together and refresh the managed browsers after dependency updates. CI retains failure traces and screenshots for seven days; fixtures must not contain private data or credentials.

Security-sensitive changes need regression coverage. Treat path resolution, symlinks, request sizes, token handling, file quotas, atomic writes, delete confirmation, ETags, and virtual-terminal commands as security boundaries. Do not add subprocess execution or a system shell under the “virtual terminal” name.

## Pull requests

Describe:

- The user problem and chosen scope
- Behavior before and after
- Failure and recovery behavior
- Security or privacy impact
- Commands run and their results
- Any intentionally deferred work

Use clear commit messages such as `fix: reject symlink parents during writes` or `feat: add bounded text search`.

## Developer Certificate of Origin

Every commit must include a `Signed-off-by` trailer:

```bash
git commit -s -m "fix: describe the change"
```

By signing off, you certify that you wrote the contribution or otherwise have the right to submit it under the project's `AGPL-3.0-only` license, and that you understand the contribution and sign-off are public. This is a certificate of origin, not a copyright assignment.

Maintainers may ask you to re-sign commits that lack a valid trailer.

## Conduct and reporting

Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Report suspected vulnerabilities privately using [SECURITY.md](SECURITY.md), not in a public issue.

Questions: [support@samsarix.com](mailto:support@samsarix.com)

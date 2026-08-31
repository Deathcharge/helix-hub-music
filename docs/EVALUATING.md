# Evaluate a Samsarix Workspace candidate

This is a local, single-user pilot, not a hosted service. Use synthetic or non-sensitive documents in a new disposable workspace. Do not use your only copy of important files. Nothing in this process sends your documents or feedback to Samsarix LLC automatically.

## Check what you received

Obtain the candidate and verifier from a source you trust. A manifest and its files can be replaced together: matching checksums do **not** authenticate the publisher. The included `verify_release.py` is a convenience copy; obtain the verifier independently from the trusted repository if you do not already trust the bundle. Do not execute an unknown verifier to decide whether it is trustworthy.

From the bundle directory, using trusted Python 3.11 or newer:

```text
python verify_release.py verify .
```

This reads files only and needs no third-party package or network. It rejects changed, missing, linked, or unlisted files. Keep the bundle unchanged; put environments, notes, and documents outside it. `release-manifest.json` records the source revision, Python/platform, tool versions, artifact hashes, and completed build checks. `runtime.cdx.json` contains the declared dependency/license inventory, not a vulnerability or legal-compliance certificate.

Use the Python major/minor version, operating system, and architecture matching `runtime` in the manifest. The hash lock selects wheels resolved for that environment; it is not a universal cross-platform lock. Linux and Windows CI bundles are separate. A different interpreter/platform can correctly fail installation because its wheel has a different hash.

## Install into a separate environment

Use the matching interpreter as `python` below. Installation downloads exact hash-locked application dependencies from PyPI and finds Samsarix's wheel in the bundle; network access is required. The environment's installer is not an application dependency covered by this lock.

```text
python -m venv ../samsarix-pilot-env
```

Windows PowerShell, still in the bundle directory:

```powershell
& ../samsarix-pilot-env/Scripts/python.exe -m pip install --require-hashes --only-binary=:all: --find-links . -r runtime-requirements.txt
& ../samsarix-pilot-env/Scripts/python.exe -m samsarix_workspace init ../samsarix-pilot-documents
& ../samsarix-pilot-env/Scripts/python.exe -m samsarix_workspace serve ../samsarix-pilot-documents --open
```

Linux/macOS shell (macOS needs a separately built matching candidate; CI currently produces Linux/Windows bundles):

```bash
../samsarix-pilot-env/bin/python -m pip install --require-hashes --only-binary=:all: --find-links . -r runtime-requirements.txt
../samsarix-pilot-env/bin/python -m samsarix_workspace init ../samsarix-pilot-documents
../samsarix-pilot-env/bin/python -m samsarix_workspace serve ../samsarix-pilot-documents --open
```

Open `http://127.0.0.1:8765` if the browser does not open. Keep the default loopback listener. Stop the server with Ctrl+C when finished. If installation fails, retain the error and environment versions; do not disable hash checks or install into a shared global environment to bypass the failure.

## Try the actual job

Without maintainer coaching, try these tasks in order. Record where you needed help; a scripted maintainer test is not user-validation evidence.

1. Open `WELCOME.md`, add a short paragraph, save it, and reload the page. Confirm the saved text remains.
2. Import a small UTF-8 Markdown draft, find a phrase with content search, and open its preview. Edit and save twice.
3. Open History, preview the earlier text, and restore it under a new filename. Confirm the current draft is unchanged and the new copy contains the earlier text.
4. Preview a saved version again and try the confirmed replacement action. Confirm the prior current contents remain recoverable while retention permits.
5. Delete a saved copy into Trash, then restore it. Restart the server with the same root and confirm the recovered files are still present.

History stores prior app-overwrite text locally, unencrypted, with automatic bounded expiration. Trash is separately bounded and does not auto-expire. Neither replaces backups or provides secure erasure. An unsaved draft is tab-scoped; it is not durable history. Use one server per root.

## Optional feedback, under your control

Record the candidate revision and artifact hash, OS, Python/browser versions, whether each task succeeded unaided, confusing wording, and reproducible errors. Timing is optional; do not infer demand or performance from one attempt. Do not include document contents, absolute private paths, tokens, or screenshots with sensitive data.

Only share feedback if you consent. Use the repository's Issues page for sanitized non-sensitive defects or `support@samsarix.com` for private support/security reports. No participants have been contacted and no successful pilot, testimonial, or demand is implied by this checklist.

For upgrade/rollback, stop the server, preserve a complete protected workspace copy including both private recovery folders, and verify a disposable backup with its matching application version. Do not point 0.3.0 at a 0.4.x live root: it does not hide `.samsarix-history`. Check the repository's Getting Started guide before moving real data.

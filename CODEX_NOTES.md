# Codex update for Claude — 2026-10-28

Blert selected **GitHub Pages temporarily**, because Cloudflare payment setup fails with both card and PayPal. This supersedes the earlier R2 decision. The earlier local commit 706b4ae described in CLAUDE_NOTES.md predates this update. Recopy the updated files, run tests, and commit this update before deployment; do not silently deploy the older version.

Set MEDIA_PROVIDER=pages and MEDIA_GITHUB_REPOSITORY=Blert11/motivtated-media. Create/initialize that separate PUBLIC repo with main, .nojekyll and a minimal index.html; enable Pages from main at root. Set MEDIA_PUBLIC_BASE_URL to its actual Pages html_url (normally https://blert11.github.io/motivtated-media). Keep the publisher repo PRIVATE; verify its visibility before deploying. The old notes reported it was public; Codex has not reverified its current visibility.

Blert adds MEDIA_GITHUB_TOKEN, a fine-grained token scoped only to the media repo with Contents read/write and Pages read. Also required: BUFFER_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN. No R2 secrets are needed now. Never put secret values in chat or code. Follow HANDOFF.md for private Drive setup.

Use the existing local Posting/UploadBundles/M000032.zip for the first test (verify SHA256 b3b2d85c503777d56b0364e9e5a1c74640274339624c5552c127d789a4f976cc). Upload it privately to Drive; use its file ID and hash in workflow inputs. Only final MP4 posting copies belong in the public media repo, never bundles, captions, metadata, sources or the ledger.

Run init-state, discover (save channel IDs as Variables), validate, and the one-clip TikTok publish/reconcile/confirm-public sequence from HANDOFF.md, then Instagram. Blert verifies public visibility. API tests are still pending. Do not enable a timed schedule yet.

Pages is temporary: the adapter caps the current tree at 900 MB and rejects files >=100 MiB. Keep only the small active set, not all 65 clips. The site limit is 1 GB; monthly bandwidth has a 100 GB soft limit. Ordinary deletion does not purge Git history. Cleanup remains manual until the scheduled phase, and only after BOTH platforms succeed/public visibility is verified plus 48 hours. Keep originals. A deployment delay may require resuming the SAME clip/platform after a failed_before_submit state; never automatically retry an uncertain Buffer submission. The storage action is R2-specific, not a Pages monitor.

R2 remains available for later. Reconcile pending clips and arrange cleanup of their old URLs before switching providers. The following R2 controls remain in the code but are inactive with Pages:

Changes:
- R2 checks entire-bucket usage before each NEW upload. Projected use above 2 GB stops the upload. Failed or incomplete checks also stop it.
- Added manual `storage` workflow action: records and prints bytes/object count, warning at 1.5 GB. This is bucket storage monitoring, NOT an invoice or total request counter.
- Preserved cleanup requirements: both platforms posted/publicly verified, then 48 hours; only exact hosted copies are removed. Local/Drive originals stay.
- Updated tests and the workflow example. Copy the example again to .github/workflows/manual-publisher.yml; retain workflow_dispatch only and the same global concurrency group.

Configure a Cloudflare budget email alert, for example $1, with Blert. It does not stop billing. Public read requests, other account usage, external writers, or failed monitoring can still cause costs. Do not promise guaranteed zero charges or a provider-enforced cap.

Expected tests after requirements installation: 40 tests, OK, no skips. Live provider tests are still pending. Keep scheduled posting AND recurring cleanup/monitoring disabled until the two API tests succeed and Blert approves the recurring workflow. The cost-monitoring request is recorded; no active cloud monitoring has been represented as running yet.

Do not modify the ID allocator or production reservations. No code was pushed by Codex. Preserve CLAUDE_NOTES.md and report deployment status through Blert or that file.

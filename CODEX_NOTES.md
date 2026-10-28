# Agent-owned transfers — 2026-10-28

Blert asked Codex to do all package transfers. Google Drive uploads are no longer a required user step. Upload validated ZIPs to the private Blert11/motivtated release posting-inputs using upload_bundles.py. It verifies private visibility, local receipts, and the uploaded SHA256/size; it never overwrites existing assets and never publishes anything.

Use manual workflow bundle_source=github-release, clip_id and bundle_sha256. No Drive file ID is needed. The runner uses its generated GITHUB_TOKEN through gh to download the exact package, verifies hashes, and publishes only the MP4 publicly through Pages. No new secrets are needed. Drive is still supported as an optional source.

User authorized posting Tate #6 (M000006) to both platforms now and preparing #7–31 without scheduling. Videos 1–5 are explicitly excluded. M000032 was reported as previously posted; it has completed ledger records and must not be submitted again. No deletion of existing social posts was requested.

Both initial M000032 API tests passed and Blert confirmed both public. Instagram confirmation was recorded by successful workflow 40692285315. The per-clip Instagram gate now accepts an already completed two-platform milestone on the configured Instagram channel, so future authorized clips do not require repeated manual public checks before cross-posting. Duplicate checks and per-platform durable intent remain unchanged. Public confirmation still gates cleanup.

54 offline tests pass, no skips. The workflow remains workflow_dispatch only, with 10 inputs and the same global concurrency group. No timed schedule, automatic backlog drain or local folder watcher is installed. Agents run the reusable uploader for prepared clips; after transfer, GitHub can post with the PC off. The private release inputs are separate from the temporary public Pages media.

Private package source: https://github.com/Blert11/motivtated/releases/tag/posting-inputs
Docs: https://cli.github.com/manual/gh_release_download

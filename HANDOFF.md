# Deployment handoff to Claude — manual milestone

Prepared 2026-10-28. Deploy into **Blert11/motivtated**, which must be PRIVATE. Codex has not pushed code, added credentials, uploaded public media, or published posts. Buffer's browser tests succeeded according to Blert; API publishing has not yet been tested live.

## Ownership and scope

Copy the CONTENTS of `C:\Users\Blert\Desktop\photoshop projects\motivtated\Posting\Publisher` into the repository root. Preserve this implementation; report required logic changes through Blert or local `CLAUDE_NOTES.md`. Never copy Staging, Control, UploadBundles, source videos, ZIPs, or credentials into Git.

Only manual `workflow_dispatch` runs are authorized. No schedule, push trigger, automatic backlog drain, or overnight loop. The example lives outside `.github` deliberately. After reviewing it, install `deployment/manual-workflow.example.yml` as `.github/workflows/manual-publisher.yml`. Keep the single global concurrency group and `cancel-in-progress: false`. Use `main` for runs. Do not run a second publisher concurrently on another PC/repository.

First milestone: one fresh clip on TikTok, verify it is public, then the same clip as an Instagram Reel. No automatic scheduler until both succeed and Blert approves.

## Files and entry points

| File | Purpose |
| --- | --- |
| `publisher/__main__.py` | `python -m publisher` CLI and workflow inputs |
| `publisher/bundles.py` | Private Drive download; local packaging; file/hash/caption/ffprobe checks |
| `publisher/github.py` | GitHub REST and durable ledger with compare-and-swap writes |
| `publisher/buffer.py` | Current Buffer GraphQL queries and one createPost mutation |
| `publisher/media.py` | Interchangeable GitHub Pages / R2 upload, public verification, cleanup |
| `publisher/engine.py` | Per-platform state, duplicate blocking, recovery, public confirmation |
| `tests/test_publisher.py`, `tests/test_r2_sdk.py` | Offline regression suite and real SDK model checks; no live credentials needed |
| `requirements.txt` | boto3 dependency for R2; other code uses the Python standard library |
| `deployment/manual-workflow.example.yml` | Manual-only workflow for Claude to install |

Python version: **3.12**. `ffprobe` from FFmpeg must be on PATH locally and in Actions. `requirements.txt` pins the tested boto3 1.43.120 and its dependencies; the supplied workflow installs them for either provider. Run `python -m pip check` after installation. No AI API/model subscription is used by the publisher.

## Exact GitHub repository SECRET names

Blert enters values at repository Settings → Secrets and variables → Actions → Secrets. Do not print, paste into chat, commit, or upload them as artifacts.

| Secret | Required for | Value |
| --- | --- | --- |
| `BUFFER_API_KEY` | Buffer discovery / posting / reconciliation | Key created in Buffer API settings |
| `GOOGLE_CLIENT_ID` | Cloud bundle download | Own Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Cloud bundle download | Matching OAuth client secret |
| `GOOGLE_REFRESH_TOKEN` | Cloud bundle download | Offline refresh token from the Google account holding the private bundle |
| `MEDIA_GITHUB_TOKEN` | Pages ONLY | Fine-grained token scoped to the public media repo, Contents read/write and Pages read; default Actions token cannot write a second repo |
| `R2_ACCESS_KEY_ID` | R2 ONLY | Bucket-scoped S3 access key |
| `R2_SECRET_ACCESS_KEY` | R2 ONLY | Matching S3 secret |

`GITHUB_TOKEN` is supplied by `${{ github.token }}` at run time; do NOT ask Blert to create a secret with this name. `GITHUB_REPOSITORY` is supplied by Actions. Workflow `permissions: contents: write` is needed for the private ledger branch. Restrict who can dispatch workflows and edit code with these secrets.

## Exact GitHub repository VARIABLE names (non-secret settings)

| Variable | Value |
| --- | --- |
| `MEDIA_PROVIDER` | `pages` OR `r2`, only after Blert chooses |
| `MEDIA_PUBLIC_BASE_URL` | Stable HTTPS media site origin/path, no credentials/query string/trailing slash required |
| `MEDIA_GITHUB_REPOSITORY` | Pages only: `Blert11/motivtated-media` (separate PUBLIC repository) |
| `R2_ACCOUNT_ID` | R2 only: Cloudflare account ID |
| `R2_BUCKET` | R2 only: exact bucket name |
| `BUFFER_TIKTOK_CHANNEL_ID` | TikTok ID returned by `discover`; not the account username |
| `BUFFER_INSTAGRAM_CHANNEL_ID` | Instagram ID returned by `discover` |

## Media-host setup — decision still open

**GitHub Pages:** create a separate public repository only if Blert chooses it. Initialize `main`, add `.nojekyll` and a minimal `index.html`; enable Pages from `main` at `/` in repository settings. Set the public base URL to the exact `html_url` from GitHub Pages (usually `https://blert11.github.io/motivtated-media`). Grant the media token access only to that repo. No Pages hosting on the private publisher repo.

MP4s use immutable names containing their ID and full SHA256. The adapter refuses >=100 MiB files and caps the current site tree at 900 MB. The provider limit is a 1 GB published site and 100 GB/month soft bandwidth limit. Your current 65 clips average about 38 MB; roughly 26 average clips fill 1 GB, so retain fewer. Pages is not unlimited video hosting. Deleting from the current tree does not purge Git history; routine cleanup alone will not stop repository growth. There is no destructive history rewriting in this publisher. Confirm suitability with GitHub if using it as an ongoing media delivery service.

A new Pages commit can take time to deploy. If a manual publish run stops at public URL verification, inspect that it remains `failed_before_submit`. Wait for the Pages deployment, then rerun the SAME clip/platform with resume=true. Do not change IDs. The existing immutable file is reused. The publisher does not wait indefinitely or guess that HTTP 200 means a valid video.

**R2:** Blert enables billing himself. Use a dedicated bucket and bucket-scoped object read/write credentials. Enable public access only for posting copies. A development `r2.dev` URL can serve the initial test, but Cloudflare describes it as rate-limited/non-production; configure a public custom domain before recurring production use. Do not protect these video URLs with login, expiring signatures, or bot challenges. Free allowance is not a spending guarantee. No Hostinger storage is used.

Do not switch providers while a clip is pending on either platform without reconciling its retained URLs first. Retain media until both platforms finish. Cleanup checks the saved destination against current settings.

## Private input upload for this milestone

This version intentionally selects ONE bundle by Drive file ID. It does not scan or move Ready/Posted yet. Original clips remain in Staging and the shared allocator remains untouched.

1. Enable the Google Drive API in Blert's Google Cloud project. Obtain a Google OAuth client and offline refresh token for his account using Google's documented flow / OAuth Playground with his own client credentials. Use the read-only Drive scope `https://www.googleapis.com/auth/drive.readonly`; use a dedicated account/folder if desired. Keep all values private and add the three Google secrets above. The code only refreshes this token and downloads the selected file; it does not implement the interactive consent flow.
2. External OAuth apps left in Testing commonly issue refresh tokens that expire after seven days for Drive scopes. Resolve publishing status / applicable verification requirements before unattended production; a short-lived test token is not a permanent deployment.
3. Run `prepare` locally to create the ZIP; upload it to a PRIVATE Google Drive folder accessible to that authorized account. Do not make it public. Keep its Drive file ID and printed bundle SHA256 for the workflow inputs.
4. No raw Drive share link is passed to Buffer. The agent downloads with Google authorization, then uploads only the MP4 to the chosen public media host. Captions, metadata, and source paths remain private.

Local example (run from Posting\Publisher, replace output if it already exists):

```powershell
& 'C:\Users\Blert\Desktop\photoshop projects\Spreht\motivtated-batch-4\venv\Scripts\python.exe' -m publisher prepare --root 'C:\Users\Blert\Desktop\photoshop projects\motivtated\Posting' --clip-id M000032 --output 'C:\Users\Blert\Desktop\photoshop projects\motivtated\Posting\UploadBundles\M000032.zip'
```

Packaging requires validated video/caption/metadata SHA256 values and the original source file's SHA256 in the registry. The original source is rehashed locally; the cloud verifies the signed-off bundle digest and contained hashes, not the full long source video. Any intentional caption/media change requires revalidation and a new bundle. UTF-8 CRLF is supported. The required hashtag is exactly `#motivtated`, with one final 👑, 🥇, or 🏆.

M000001 is held because it was offered for earlier manual tests. Verify which other clips Blert has already posted. Confirm `confirm_unposted=true` only after checking the selected clip on the chosen platform. Exact byte duplicates under other IDs are blocked by the ledger; semantic duplicates or re-encoded copies require editorial/source-range checks.

## Test command and expected result

From the Publisher/repository root:

```sh
python -m unittest discover -s tests -v
```

Expected after installing requirements: **34 tests**, no skips or failures, ending with `OK`, exit code 0. These tests exercise failure paths with fake services and botocore's real service model; they do NOT prove live provider credentials, Pages builds, R2 networking, or Buffer's current account behavior. Without boto3 installed, the two SDK tests skip. A separate real bundle round-trip is also checked locally before handoff.

## Manual workflow sequence

1. **init-state** once. Requires private repo and generated GitHub token only. Creates `publisher-state` branch and `publisher-state.json` if absent; never resets existing state.
2. **discover** after `BUFFER_API_KEY` exists. Returns channel IDs and connection flags. Copy the intended IDs into repository Variables. No posts are created.
3. **validate** with clip_id, bundle_file_id, and bundle_sha256. Confirms private Drive download, all hashes, caption, metadata, and ffprobe. No public upload and no Buffer post.
4. **publish**, platform=tiktok, the same bundle inputs, confirm_unposted=true. Creates at most ONE post with automatic publishing and shareNow. The selected clip should be new to that platform. Public URL availability is verified before the mutation. A successful request may still be `sending`/`scheduled`; that is not publication confirmation.
5. **reconcile** with clip_id and platform=tiktok until state is `posted` and a post_url is returned. It reads the saved Buffer post ID; it never creates another post. No bundle is needed.
6. Blert opens the post and verifies public visibility. Run **confirm-public** with clip_id, platform=tiktok, and the exact returned post_url. This records his observation; it does not programmatically certify TikTok privacy. The current Buffer schema has no TikTok privacy input, so no invented privacy field is sent.
7. Repeat publish/reconcile/confirm-public for **instagram**, using the same clip and bundle. Instagram is explicitly a Reel. Code blocks this milestone until that clip's TikTok publication has been confirmed public.
8. Report both Buffer IDs, platform links, run links, and results through Blert or CLAUDE_NOTES.md. Do not add an hourly schedule. Both live tests plus Blert's approval are required before building/enabling automatic queue refill.

For CLI use, equivalent commands are `python -m publisher run --action ACTION ...`; `python -m publisher run --help` lists flags. Workflow inputs are mapped to environment variables, never interpolated into shell commands.

## Recovery and durable state

The local registry allocates IDs; it is NOT the publishing ledger. The remote ledger lives on `publisher-state`, independently of runner disks and expiring artifacts. Every write uses the previous GitHub blob SHA. A competing writer or uncertain state-write result stops before the next Buffer request. All Buffer calls have a preceding durable event; createPost additionally has a `submit_intent` with request fingerprint and per-platform state.

| Saved state | Action |
| --- | --- |
| `preparing` / `failed_before_submit` | Correct channel/media setup; rerun same bundle with resume=true. No createPost was reached in the durable protocol. |
| `submit_intent` with no Buffer ID | Outcome may be unknown. Inspect Buffer. If found, reconcile with post_id; the code checks channel, caption, and original media URL. NEVER automatically resubmit, clear state, or allocate a fresh ID to bypass this. |
| `submitted` | Reconcile the saved ID; do not publish again. |
| `failed_at_buffer` | Correct the issue and retry the EXISTING post through Buffer if appropriate, then reconcile. No fresh createPost in this milestone. |
| `posted` | Publication confirmed by Buffer; public visibility still needs user confirmation. |
| `needs_attention` | Unexpected draft/approval/status; investigate the existing post. |

An ambiguous attempt where no post can be located intentionally stays blocked. This conservative behavior avoids an unsafe retry; it does not claim a distributed exactly-once guarantee. If Buffer transforms the asset source URL and an unknown attempt cannot be matched strictly, return to Codex for investigation. Never reset the ledger or delete its branch to fix a failure.

TikTok and Instagram records are separate; an Instagram failure never resubmits TikTok. `confirm-public` refreshes status before recording the user observation. Keep `cancel-in-progress: false` and do not cancel an active publish run to start another.

## Cleanup and later phase

`cleanup` is also manual. It deletes only the exact hosted copies after BOTH platforms are posted/publicly verified and at least 48 hours past BOTH sent timestamps. It never deletes local files, private Drive bundles, source videos, or registry entries. Pages deletion changes the current site, not Git history. Do not add a time-based bucket lifecycle that can delete still-pending media.

Automatic cleanup can be called by the later approved scheduler with these same guards. Daily 5–6 cross-posts, ordered folder intake, readiness markers, queue refill, retention, alerts, and unresolved-reservation handling are the NEXT phase after the two API tests. They are not enabled or represented as finished in this manual milestone.

## References checked for this implementation

- Buffer schema and video requests: https://developers.buffer.com/reference.html and https://developers.buffer.com/examples/create-video-post.html
- Direct media requirements: https://developers.buffer.com/guides/hosting-media.html
- GitHub Pages limits: https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
- Git file/history limits: https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github
- Google OAuth lifetime: https://developers.google.com/identity/protocols/oauth2
- R2 public access: https://developers.cloudflare.com/r2/buckets/public-buckets/

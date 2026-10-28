# Validation record — 2026-10-28

## Completed locally

- All 65 staged clip pairs checked against their metadata hashes, caption format, ffprobe video/audio format, source range bounds, and original source file SHA256. Registry next_id remains 66. Claude's M000032–M000065 are now staged. This is technical validation, not a new listening/editorial review.
- Python 3.12: 46 offline tests passed, no skips. Tests include mutation timeout ambiguity, durable-intent save failure, failure after a post response, duplicate content under another ID, channel disconnect/recovery, partial-platform state, unknown-post reconciliation, cleanup guards, incomplete/changed bundles, malformed captions, Pages capacity/immutability, and botocore SDK request validation.
- Latest update: R2 usage pagination, warning threshold, projected 2 GB upload ceiling, and fail-closed handling of unmeasurable/incomplete storage passed regression tests. The workflow remains manual only, with an added storage action.
- Dependency versions in requirements.txt were installed into an isolated scratch folder and used for the SDK tests.
- M000032 was packaged and validated again through the real CLI with ffprobe. Bundle SHA256: `b3b2d85c503777d56b0364e9e5a1c74640274339624c5552c127d789a4f976cc`.
- Workflow example parsed as YAML and checked to contain only workflow_dispatch, a global concurrency group with cancel-in-progress false, and contents write permission for durable state.

## Current deployment validation

- Live inspection: main ea7be6f contains Claude's git-push upload fix; its actual 55,178,411-byte M000032 upload succeeded. TikTok ledger is posted with Buffer status sent. Blert confirmed the linked TikTok is public.
- Preserved that deployed upload implementation. Merged credential-redacted bounded GitHub error messages and a pre-upload local SHA256 check. 46 offline tests passed with no skips.
- The previous local Git Data API implementation and its mocked 55 MiB tests are superseded. See CODEX_NOTES.md for the deployment decision and existing post ID.
- Instagram publication and public visibility remain to be confirmed. No timed schedule or automatic cleanup is enabled.

## Direct GitHub transfer update

54 tests passed. Added exact private release selection, remote/local hash verification, malformed/oversized download rejection, credential-safe subprocess errors, the completed-integration gate, and exclusions for Tate 1–5. M000006 package uploaded and verified against the GitHub asset digest.

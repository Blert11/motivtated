# Validation record — 2026-10-28

## Completed locally

- All 65 staged clip pairs checked against their metadata hashes, caption format, ffprobe video/audio format, source range bounds, and original source file SHA256. Registry next_id remains 66. Claude's M000032–M000065 are now staged. This is technical validation, not a new listening/editorial review.
- Python 3.12: 34 offline tests passed, no skips. Tests include mutation timeout ambiguity, durable-intent save failure, failure after a post response, duplicate content under another ID, channel disconnect/recovery, partial-platform state, unknown-post reconciliation, cleanup guards, incomplete/changed bundles, malformed captions, Pages capacity/immutability, and botocore SDK request validation.
- Dependency versions in requirements.txt were installed into an isolated scratch folder and used for the SDK tests.
- M000032 was packaged and validated again through the real CLI with ffprobe. Bundle SHA256: `b3b2d85c503777d56b0364e9e5a1c74640274339624c5552c127d789a4f976cc`.
- Workflow example parsed as YAML and checked to contain only workflow_dispatch, a global concurrency group with cancel-in-progress false, and contents write permission for durable state.

## Not yet run

- No GitHub push or deployed workflow run by Codex.
- No authenticated Google Drive, Pages, R2, or Buffer API integration call.
- No public media upload, actual publication, or cleanup by this publisher.
- No timed scheduler, automatic queue refill, or Ready/Posted intake enabled.

The manual live tests in HANDOFF.md are still required. Media host selection, repository privacy, and credentials remain deployment prerequisites. The previously successful browser tests do not substitute for the API tests.

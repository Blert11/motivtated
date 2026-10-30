# Video preview correction

New TikTok and Instagram posts select the frame at 1000 milliseconds using
`assets[].video.metadata.thumbnailOffset`. This avoids the old exports' black
opening fade. Buffer's API rejects custom thumbnail image URLs; none are sent.
Reference: https://developers.buffer.com/reference (VideoMetadataInput).

The manual **Repair scheduled video covers** workflow updates existing future
posts only, using the same Buffer post ID, caption, source URL, and due time.
It skips published posts and posts due within ten minutes. It cannot publish a
new post. It shares the publisher's concurrency group and writes intent to the
existing ledger before editing. An uncertain edit is never blindly repeated;
rerunning only reconciles it if the requested offset is visible in readback.

No new secrets. Uses existing `BUFFER_API_KEY` and automatic `GITHUB_TOKEN`.
Entry point: `python -m publisher.repair_covers`.
Regression tests: `python -m unittest discover -s tests -v` (84 tests).

Already-published Instagram covers are not changed by this workflow. Those need
an Instagram-side cover edit. Never delete or repost a live Reel to fix a cover.

Local batch 5 export correction removes the startup black fade while preserving
all speech timing and the encoded audio. Its 42 staged IDs are unchanged and
are not added to the live posting schedule by this correction.

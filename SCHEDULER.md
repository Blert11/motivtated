# Active cloud schedule

Blert authorized scheduled posting starting at Tate video 10 on 2026-10-28. This supersedes the earlier manual-only milestone restriction. Videos 1-9 and M000032 are excluded. Nothing already published is resubmitted.

posting-schedule.json contains the original 22-clip plan (M000010-M000031), followed by the 42 corrected batch-5 clips (M000066-M000107), authorized on October 30. All 64 IDs and package hashes are explicit. Ten slots per full day, Europe/Budapest: 09:00, 10:30, 12:00, 13:30, 15:00, 16:30, 18:00, 19:30, 21:00, 22:30. The first clip is October 28 at 21:00; video 31 is October 31 at 09:00. The new batch begins October 31 at 10:30 and finishes November 4 at 12:00. Both platforms use the same slots and order.

The scheduled-publisher.yml workflow runs at minute 17 each hour plus manual dispatch. It shares the manual publisher's single-writer concurrency group and never cancels an in-flight run. GitHub may delay scheduled workflow starts; Buffer receives explicit future dueAt times, so its existing scheduled queue publishes independently of GitHub and the PC. At most ten pending posts per channel are filled; external pending/draft posts count toward that conservative limit. Failed or ambiguous mutations are never automatically resubmitted. A missing scheduling window stops instead of posting a late backlog in a burst.

Run python -m publisher.scheduler --dry-run to validate the plan without API calls. Run python -m publisher.scheduler in Actions to reconcile due posts, clean old media, and refill. 89 offline tests pass. New dependency: tzdata==2026.6. No new user secrets; the cloud runner uses its generated GITHUB_TOKEN and existing Buffer/media keys.

Input bundles are already uploaded to the private posting-inputs release. Agents use upload_bundles.py for future transfers. Only final MP4 copies are hosted publicly in the separate Pages media repo. The queue is finite: no files outside this explicit approved plan are automatically picked up.

The worker cleans only this queue's hosted MP4 copies after BOTH platforms report sent with post links and the configured two-hour grace has passed after BOTH sent times. The engine retains its 48-hour default for other callers; this approved plan explicitly uses cleanup_grace_hours=2 to fit the temporary Pages host. It refreshes both Buffer statuses before deletion. It records cleanup_basis=buffer_sent_both_platforms; it does not falsely mark human public verification. Private bundles and PC originals remain. Failed/pending posts retain media. At most four clips are cleaned per run. A read-only storage preflight defers new uploads when the whole Pages site would exceed 900 MB, without creating any reservation or Buffer post; the next hourly run checks again after cleanup. The upload itself retains the same hard cap. Git history is not purged by deleting hosted files.

Once all 64 clips are sent and their hosted copies cleaned, the workflow disables itself using its Actions write permission. The manual workflow remains available. Failures are visible in GitHub Actions and its job summary; GitHub notification delivery depends on the account's notification settings.

To pause future refills: disable the scheduled publisher workflow or set enabled=false in posting-schedule.json. Buffer posts already scheduled still publish unless paused/cancelled in Buffer. Never reset publisher-state or delete saved post IDs to recover a failure. Any schedule change for an existing Buffer ID needs an explicit update of that post, not a new submission.

Latest pace authorization: ten posts daily starting October 29. M000010 is already sent and retains its original time. Existing future IDs are edited in place using editPost with the existing ID, new time, and preserved caption, video and Reel settings. The plan records previous_due_at; durable reschedule_intent is saved before editing. After an ambiguous response, a later run only accepts a verified new time and never blindly repeats the edit. Each run uploads at most six new clips to stay inside the workflow time budget; the total waiting queue is capped at ten per platform.

## Revision 2026-11-01 (Claude, authorized by Blert)

Clips 20-42 of the Tate batch (M000085-M000107) are replaced by Claude's louder-music versions (voice isolated from the source, new BG bed, video stream unchanged) with new captions, and post at seven per day from November 2: 09:00, 11:00, 13:30, 16:00, 18:30, 20:30, 22:30 Europe/Budapest, ending November 5 at 11:00. Earlier rows keep their ten-slot times.

- `pace_changes` in posting-schedule.json switches posts per day from a local date onward; each row is validated against the slots of its own day.
- Revised packages are separate release assets named `<ID>.r2.zip` (row field `asset_name`); the original `<ID>.zip` assets are kept, never deleted or overwritten. `previous_bundle_sha256` records the replaced digest.
- None of these IDs had a Buffer post or ledger record when the plan changed, so no existing post is edited.
- Revised packages are uploaded by the manual `Upload revised private bundles` workflow from the `claude-bundles` branch; it verifies each digest and refuses to overwrite an existing asset.

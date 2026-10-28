# Active cloud schedule

Blert authorized scheduled posting starting at Tate video 10 on 2026-10-28. This supersedes the earlier manual-only milestone restriction. Videos 1-9 and M000032 are excluded. Nothing already published is resubmitted.

posting-schedule.json contains the explicit 22-clip plan (M000010-M000031) and approved package hashes. Five slots per full day, Europe/Budapest: 09:00, 12:00, 15:00, 18:00, 21:00. The first clip is October 28 at 21:00; the last is November 2 at 09:00. Both platforms use the same slots and order.

The scheduled-publisher.yml workflow runs at minute 17 each hour plus manual dispatch. It shares the manual publisher's single-writer concurrency group and never cancels an in-flight run. GitHub may delay scheduled workflow starts; Buffer receives explicit future dueAt times, so its existing scheduled queue publishes independently of GitHub and the PC. At most six pending posts per channel are filled; external pending/draft posts count toward that conservative limit. Failed or ambiguous mutations are never automatically resubmitted. A missing scheduling window stops instead of posting a late backlog in a burst.

Run python -m publisher.scheduler --dry-run to validate the plan without API calls. Run python -m publisher.scheduler in Actions to reconcile due posts, clean old media, and refill. 68 offline tests pass. New dependency: tzdata==2026.6. No new user secrets; the cloud runner uses its generated GITHUB_TOKEN and existing Buffer/media keys.

Input bundles are already uploaded to the private posting-inputs release. Agents use upload_bundles.py for future transfers. Only final MP4 copies are hosted publicly in the separate Pages media repo. The queue is finite: no files outside this explicit approved plan are automatically picked up.

The worker cleans only this queue's hosted MP4 copies after BOTH platforms report sent with post links and at least 48 hours have passed after BOTH sent times. It refreshes both Buffer statuses before deletion. It records cleanup_basis=buffer_sent_both_platforms; it does not falsely mark human public verification. Private bundles and PC originals remain. Failed/pending posts retain media. At most two clips are cleaned per run; the existing 900 MB Pages guard remains. Git history is not purged by deleting hosted files.

Once all 22 clips are sent and their hosted copies cleaned, the workflow disables itself using its Actions write permission. The manual workflow remains available. Failures are visible in GitHub Actions and its job summary; GitHub notification delivery depends on the account's notification settings.

To pause future refills: disable the scheduled publisher workflow or set enabled=false in posting-schedule.json. Buffer posts already scheduled still publish unless paused/cancelled in Buffer. Never reset publisher-state or delete saved post IDs to recover a failure. Any schedule change for an existing Buffer ID needs an explicit update of that post, not a new submission.

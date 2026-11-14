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

## Revision 2026-11-05 (Claude, authorized by Blert)

After the last two Tate posts (Nov 5 09:00 and 11:00), the plan continues with a mix of non-Tate clips at seven per day, Nov 5 13:30 to Nov 15 11:00: batch 4 Limitless Drive M000033-M000065 (already staged, never posted) interleaved with batch 6 M000108-M000144 (McConaughey, Jack Ma, Dan Pena, 4 AM; IDs reserved in Control/registry.json). Batch 6's three 4:3 compilations are not scheduled (publisher requires 1080x1920).

- validate_plan accepts further unique IDs after the approved Tate order when `additional_authorized_on` is set.
- Packages are `<ID>.zip` release assets uploaded from the `claude-bundles-b6` branch by the upload workflow (input `ref`).

## Facebook (2026-11-06, Claude, authorized by Blert)

Every row due at or after `facebook_from` (Nov 6 09:00) is also scheduled to the Facebook page as a Reel, same caption and time. The channel ID comes from the optional `BUFFER_FACEBOOK_CHANNEL_ID` variable, otherwise it is discovered once (the single connected, unlocked Facebook channel) and saved in the ledger. Facebook is isolated: any Facebook failure records `facebook_paused` in the ledger and only Facebook stops; TikTok/Instagram continue. A Buffer request rejected by schema validation (GraphQL errors without data, or HTTP 400) is recorded as `failed_before_submit` with the error text, since nothing was created. Media cleanup waits for Facebook too when it has a post for that clip.

## Revision 2026-11-06b (Claude, authorized by Blert)

After Nov 15 11:00 the plan continues Nov 15 13:30 to Nov 24 16:00 at seven per day on TikTok, Instagram and Facebook: the new Tate batch 7 (M000145-M000174, B-roll only) alternating with batch 5 clips 17-51 remixed with louder music (M000175-M000209; voice isolated from the delivered clips, video unchanged). Batch 7's three 4:3 compilations are not scheduled. Packages uploaded from `claude-bundles-b7`.

## Revision: media host compaction and longer public check (2026-11-06)
- The media hosting repo (Blert11/motivtated-media) had grown to ~3.45 GB of git history although only 12 files (~360 MB) were live, so Pages deploys lagged past the 3-minute public check and runs failed with `failed_before_submit` (nothing was submitted to Buffer).
- Its `main` was replaced by a single orphan commit holding exactly the current tree (same paths and file contents, so every ledger media URL is unchanged).
- `wait_for_public` now retries for about 12 minutes (49 × 15 s) and the workflow timeout is 60 minutes.

## Lane 2: YouTube Shorts + X on the second Buffer account (2026-11-07, Claude, authorized by Blert)

A separate scheduler (`publisher/lane2.py`, workflow `lane2-publisher.yml`, hourly at minute 47) posts through the SECOND Buffer account (secret `BUFFER_API_KEY_2`). It does not touch the TikTok/Instagram/Facebook scheduler, its plan or its ledger.

- Plan: `lane2-schedule.json`. 4 posts a day per page at 10:00, 14:00, 18:00, 21:30 Europe/Budapest from Nov 8.
  - Motivtated: every clip in the `posting-inputs` release (M000006-M000209, revised `.r2` packages where they exist), Tate alternating with the other speakers, to YouTube Shorts and X. Ends Dec 28.
  - Imanivated: 30 vertical clips (batch 2 plus batch 1 clips 15-19) as `I000001`-`I000030` packages in the private `imanivated-inputs` release, to YouTube Shorts only. Ends Nov 15.
- YouTube posts carry `metadata.youtube` with a title (topic | speaker, max 100 chars), category 22 and madeForKids=false; the caption is the description.
- Ledger: `lane2-state.json` on `publisher-state` (records, channels, `last_run`). Channels are discovered once: the YouTube channel whose name contains "iman" is Imanivated, the other YouTube channel and the X channel are Motivtated.
- Queue: at most 6 pending per channel, at most 4 new clips per run. A missed slot is recorded as `skipped_missed`, never posted late. A create is never retried; Buffer refusals are recorded as `failed_before_submit`.
- Media: uploaded as assets of the public `lane2-media` release in the media repo (public as soon as the upload returns, no Pages deploy wait or hourly build limit), deleted 2 h after all of the row's platforms have sent. The first clips (Nov 7) were hosted under `media2/` on Pages and are cleaned the same way.
- Pause: set `enabled` to false in `lane2-schedule.json` or disable the workflow. Push any commit to branch `lane2-kick` to run it immediately.

### Lane 2 pace change (2026-11-07, authorized by Blert)
Motivtated (YouTube + X) moves to 6 posts a day at 10:00, 12:00, 14:00, 16:00, 18:00, 21:30 from Nov 8, ending Dec 11. The six posts already in Buffer keep their times; the other clips fill the free slots in the same order. Imanivated stays at 4 a day. The lane-2 queue now holds up to 10 posts per channel (Buffer free maximum).

### Lane 2: Imanivated batch 3 (2026-11-11, authorized by Blert)
47 new Akhi Ayman clips (I000031-I000077, private `imanivated-inputs` release) go to Imanivated YouTube Shorts at 5 a day (10:00, 12:00, 14:00, 18:00, 21:30), from Nov 15 18:00 to Nov 24. Imanivated clips may run up to 90 s (YouTube Shorts limit is 3 min); Motivtated keeps the 76 s check.

## Revision 2026-11-12 (Claude, authorized by Blert)
- Batch 8 (M000210-M000331, 122 vertical clips: Denzel Washington, Arnold Schwarzenegger, Admiral McRaven, Robert Kiyosaki, BE THAT 1% / YOU GOTTA WORK compilations and four B-roll-only videos) follows the existing plan: TikTok/Instagram/Facebook at 7 a day after Nov 24 (to Dec 12), YouTube Shorts + X on lane 2 at 6 a day after Dec 11 (to Jan 1). The five 4:3 compilations are not scheduled. Packages come from the `claude-bundles-b8-*` branches.
- Owner rule: one speaker's name never appears in anything posted. Lane-2 titles no longer carry that name, and `Lane2.retitle()` edits the YouTube titles of posts already waiting in Buffer (only those due more than 20 minutes ahead; a refusal is recorded as `retitle_error` and not retried). Already-published YouTube titles have to be changed in YouTube Studio.
- 2026-11-13: Motivtated YouTube Shorts + X raised from 6 to 7 a day (slots 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 21:30); posts already in Buffer keep their times, the rest were re-timed and now end Dec 25.

## Revision 2026-11-14 (Claude, authorized by Blert)
- TikTok/Instagram/Facebook stopped scheduling after Nov 12: Buffer reported an error on M000055 Instagram (the reel was rejected, nothing posted), and the scheduler refused to continue while that record was `failed_at_buffer`. Nov 13 therefore had no posts.
- `Scheduler.auto_skip()` now records such a post as `skipped` (`skip_reason: buffer_reported_error`, event `auto_skipped_after_buffer_error`) and keeps the queue moving. It is never resubmitted; the other platforms of that clip are unaffected.
- The 204 rows without any Buffer record were re-timed from Nov 14 09:00 at 7 a day (order unchanged); the plan now ends Dec 13.
- Keep-going rule, all pages (TikTok/Instagram/Facebook lane and the YouTube/X lane for @motivtated and @imanivated): one failing post never stops other posts, on other platforms or on the same platform.
  - Rejected by the network after scheduling (`failed_at_buffer`), uncertain create (`submit_intent`/`needs_attention`) or an unexpected Buffer status: recorded as `skipped` with a `skip_reason`, never resubmitted (no duplicates).
  - Failed before anything reached Buffer (package, media hosting, channel check, Buffer refusal): retried on the next runs, at most 3 attempts, then `skipped` (`failed_before_submit`). Facebook is not retried and no longer pauses the whole Facebook channel.
  - Missed slots are recorded as `skipped` (`missed_slot`) instead of stopping, still never posted late in a burst. A full Buffer queue only defers that platform.
  - Manual schedule edits (`previous_due_at`) keep their strict checks.

## Lane 3: Pinterest on the third Buffer account (2026-11-14, Claude, authorized by Blert)

A third scheduler (`publisher/lane3.py`, workflow `lane3-publisher.yml`, hourly at minute 23) posts video pins through the THIRD Buffer account (secret `BUFFER_API_KEY_3`). It reuses lane 2's code and safety rules but has its own plan, ledger and media release, and does not touch lanes 1 or 2.

- Plan: `lane3-schedule.json`. Every Motivtated clip (M000006-M000331, same order and titles as lane 2) and every Imanivated clip (I000001-I000077), 7 pins a day per page at 09:00, 11:00, 13:00, 15:00, 17:00, 19:00, 21:00 Europe/Budapest from Nov 15. Motivtated ends Dec 31, Imanivated Nov 25.
- Each pin: title = the lane-2 title (no title names one speaker), description = the clip caption, destination link = the page's TikTok profile, board = picked by keywords from the page's boards, otherwise rotated across all of them. Boards are read from the channel each run.
- Channels discovered once: the Pinterest channel whose name contains "iman" is Imanivated, the one containing "moti" is Motivtated.
- Ledger: `lane3-state.json` on `publisher-state`. Media: public release `lane3-media` in the media repo, removed 2 h after the pin is sent.
- Without the `BUFFER_API_KEY_3` secret the workflow does nothing. Pause: set `enabled` to false in `lane3-schedule.json`. Push any commit to branch `lane3-kick` to run it immediately.
- 2026-11-14: GitHub was starting the hourly workflows only every few hours, so each lane-3 run now fills each Pinterest queue up to 10 pins (up to 20 clips per run) instead of 4.
- 2026-11-14: Pins showed the clip's black opening frame. Each pin now sets a cover frame (`thumbnailOffset`): the earliest frame from 2 s on that is about as bright as the clip gets (checked with ffmpeg), default 3 s. `Lane3.fix_covers()` edits pins already waiting in Buffer (same post ID, caption, video, board and time; only those due more than 20 minutes ahead; a refusal is recorded as `cover_error` and not retried).

# Current posting status - 2026-10-28

The hourly cloud scheduler is enabled for Tate videos 10-31 (M000010-M000031), following Blert's latest authorization. Videos 1-9 and M000032 are excluded. Both platforms use ten slots per full day in Europe/Budapest: 09:00, 10:30, 12:00, 13:30, 15:00, 16:30, 18:00, 19:30, 21:00, 22:30. Video 10 starts October 28 at 21:00; video 31 ends October 31 at 09:00.

Ten-daily migration deployed in 249510e, Actions run 40783742476. All ten required edits (M000012-M000016 on both platforms) were confirmed by readback at 22:58 UTC, retaining the existing Buffer IDs. M000011 already had the correct 09:00 slot. M000010 is sent on both platforms. No unresolved edit intents remain. The worker is now uploading M000017-M000020 to fill ten pending posts per channel; final refill verification is pending.

All packages are already in the private posting-inputs release. Agents handle transfers; no manual Drive upload is required. The workflow maintains at most ten pending posts per channel and refills hourly. It runs with the PC off and consumes no Codex or Claude tokens. No local folder watcher is installed.

Hosted copies are deleted only after BOTH platforms report sent with links and 48 hours have passed. Private bundles and PC originals remain. The finite batch workflow disables itself after publication and cleanup finish. See SCHEDULER.md and posting-schedule.json.

M000006 was already sent on both platforms and must not be resubmitted:
- TikTok: https://tiktok.com/@motivtated/video/7701705913308056846
- Instagram: https://www.instagram.com/reel/DfC9ZN4BP7i/

M000032 integration milestones were publicly confirmed by Blert. No human public confirmation was recorded for M000006; its Buffer sent status was verified. Shared IDs and source hashes remain unchanged. Captions use #motivtated and end with a motivation emoji.

78 offline tests passed locally. Live time edits are verified; the refill run is in progress. The former manual-only restriction is superseded for the approved videos 10-31. Do not automatically add other videos to this queue.

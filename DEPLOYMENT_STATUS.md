# Current posting status - 2026-10-28

The hourly cloud scheduler is enabled for Tate videos 10-31 (M000010-M000031), following Blert's latest authorization. Videos 1-9 and M000032 are excluded. Both platforms use five slots per full day in Europe/Budapest: 09:00, 12:00, 15:00, 18:00, 21:00. Video 10 starts October 28 at 21:00; video 31 ends November 2 at 09:00.

Initial refill: Actions run 40737305385, code commit 2878275. Buffer confirmed videos 10-15 scheduled on BOTH platforms, with all 12 submissions saved by 17:58:32 UTC. The first rolling queue is filled; videos 16-31 remain in the dated plan for automatic refill. Read the private publisher-state branch for authoritative current status. A planned time alone does not prove scheduling or publication.

All packages are already in the private posting-inputs release. Agents handle transfers; no manual Drive upload is required. The workflow maintains at most six pending posts per channel and refills hourly. It runs with the PC off and consumes no Codex or Claude tokens. No local folder watcher is installed.

Hosted copies are deleted only after BOTH platforms report sent with links and 48 hours have passed. Private bundles and PC originals remain. The finite batch workflow disables itself after publication and cleanup finish. See SCHEDULER.md and posting-schedule.json.

M000006 was already sent on both platforms and must not be resubmitted:
- TikTok: https://tiktok.com/@motivtated/video/7701705913308056846
- Instagram: https://www.instagram.com/reel/DfC9ZN4BP7i/

M000032 integration milestones were publicly confirmed by Blert. No human public confirmation was recorded for M000006; its Buffer sent status was verified. Shared IDs and source hashes remain unchanged. Captions use #motivtated and end with a motivation emoji.

68 offline tests passed locally and in Actions. The former manual-only restriction is superseded for the approved videos 10-31. Do not automatically add other videos to this queue.

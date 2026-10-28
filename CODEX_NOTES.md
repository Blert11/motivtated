# Current authorization — 2026-10-28

Blert authorized enabling the complete cloud schedule starting at Tate video 10. This supersedes all earlier manual-only and prepared-only instructions for M000010-M000031. M000007-M000009 remain excluded, as do earlier IDs and M000032.

Read SCHEDULER.md and posting-schedule.json. All 22 inputs are already in the private posting-inputs release with verified hashes. The worker fills ten future Buffer posts per channel, checks due posts hourly, preserves uncertain outcomes, and cleans only hosted copies after both sent + 48 hours. It stops itself after this finite batch and cleanup complete. No local folder watcher is installed.

Do not reallocate IDs or modify registry.json. Do not reset publisher-state. Approved time changes use Engine.reschedule on the existing Buffer ID with a durable edit intent and readback; never recreate a scheduled post. User does not need to upload packages to Drive. Both Codex and Claude can run the reusable uploader against validated receipts with their authorized GitHub access.

78 offline tests passed. The scheduling API uses mode=customScheduled and dueAt; no invented scheduledAt field. Public confirmation still exists for manual use; autonomous cleanup uses explicit Buffer-sent evidence and records that basis separately.

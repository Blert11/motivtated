# Deployment update — 2026-10-28

Blert authorized Codex to take over deployment because Claude usage was exhausted. Live inspection found main ea7be6f053a8a43455b470e3abd881438ac6caea already contained Claude's git-push uploader fix, and M000032:tiktok was posted (Buffer sent). Do not publish it again.

TikTok: https://www.tiktok.com/@motivtated/video/7701549303701015821
Buffer post ID: 6ae1664d4ee0f35758d9d0ef
Blert confirmed this TikTok is publicly visible in chat. Next: record confirm-public, then publish the same M000032 bundle to Instagram and reconcile its existing Buffer post ID.

The working git-push upload is preserved, including large-file object metadata lookup. It uploaded the actual 55,178,411-byte MP4 in the live workflow. The alternative Git Data API implementation from the previous local handoff is superseded to avoid replacing the working deployment. HTTP errors now use the bounded, sanitized GitHub message handler with credential/token/URL redaction, and the local video SHA256 is checked before upload. No mutation retries were added.

46 offline tests pass, no skips (41 deployed tests plus 5 error-diagnostic tests). The reduction from the previous local 51 reflects retaining the deployed upload implementation and its tests. GitHub Pages is still temporary. No workflow triggers or dependencies changed. Scheduled posting remains disabled until both API milestones pass and Blert approves recurring execution.

Keep the same Drive bundle file ID 1ZvVf8RLCPktkg2DPmOZZUQCrVIfl66kc and bundle SHA256 b3b2d85c503777d56b0364e9e5a1c74640274339624c5552c127d789a4f976cc. Inspect the ledger before every live action. Existing post IDs must be reconciled, never resubmitted. Keep the shared allocator untouched. Preserve CLAUDE_NOTES.md as historical evidence.

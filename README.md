# MOTIVTATED manual publisher

Publish one validated clip to one platform through Buffer. Python 3.12, ffprobe, optional R2 SDK in requirements.txt. Deployment belongs to Claude; operational credentials belong to Blert.

Read HANDOFF.md before deployment. No timed scheduler or folder watcher is enabled in this milestone. Ready/Posted folders and the local ID allocator are not modified.

R2 is selected. New R2 uploads stop if projected bucket storage exceeds 2 GB or usage cannot be measured. The manual `storage` action reports usage and warns at 1.5 GB. These are application checks, not a Cloudflare billing cap; budget alerts must also be configured in Cloudflare. Read CODEX_NOTES.md before updating an earlier deployment.

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m publisher --help
```

State is persisted to the private repository's publisher-state branch before each Buffer call. Creating a post is never automatically retried. An uncertain result blocks resubmission until an existing post is found and reconciled. This favors avoiding duplicates over automatically recovering every failure; it is not an exactly-once guarantee from Buffer.

The cloud runner downloads a private, hash-verified ZIP from Drive, validates its video/caption/metadata, uploads only the MP4 to the selected public host, verifies the public copy byte-for-byte, and submits to Buffer. After a post ID is saved, reconcile only reads that existing post. A human confirms public visibility separately.

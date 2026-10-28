# MOTIVTATED publisher

Active cloud schedule for Tate videos 10-31, five daily slots per platform in Europe/Budapest. Read SCHEDULER.md for current operations and posting-schedule.json for exact dates.

Agents transfer private validated packages with upload_bundles.py; no manual Drive upload is required. GitHub Actions keeps a bounded queue in Buffer. Buffer publishes with the PC off. Explicit per-platform intent and IDs prevent automatic resubmission of uncertain posts.

python -m unittest discover -s tests -v: 68 tests, no skips after dependency installation. python -m publisher.scheduler --dry-run validates the plan without posting. Manual one-clip tools remain available.

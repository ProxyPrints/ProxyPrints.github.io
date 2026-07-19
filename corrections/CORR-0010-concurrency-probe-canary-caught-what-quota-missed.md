# CORR-0010: a concurrency-raise probe judged on remote quota alone would have shipped a live-site latency regression

- **Date**: 2026-07-19
- **Trigger / wrong premise**: task #165's concurrency-raise probe
  stepped `GOOGLE_IMAGE.max_concurrency` 3→6→10 (rate held fixed) to
  find the real throughput ceiling. Had pass/fail rested on the remote
  quota signal alone, concurrency=10 would have shipped: it measured
  the highest raw throughput (9.59/s) with **zero** Google 429/403
  events across the entire step — a clean read on the one signal that
  kind of probe usually trusts.
- **How caught**: an independent, unthrottled canary thread, running
  separately from the probe's own traffic and sampling real live-site
  Worker-path image latency every 15s. It showed concurrency=10's p95
  latency at 1.97s — a 2.43x regression over the concurrency=3
  baseline's 0.81s — on the same Worker path the harvest shares with
  live PDF export/bulk download. concurrency=6 (8.116/s achieved) was
  clean on both signals: zero lockout/backoff events AND a canary p95
  of 0.39s, better than baseline.
- **Blast radius**: would have degraded live-site image serving
  (shared Google lh3/lh4 path via image-cdn's Worker) at bulk-harvest
  volume had concurrency=10 been chosen and shipped. Caught before any
  config change landed — the probe itself, not production, absorbed
  the regression. Zero actual live-site impact.
- **Systemic fix**: the chosen config
  (`MPCAutofill/cardpicker/harvest_fetch_limiter.py`'s `GOOGLE_IMAGE`,
  this PR) is rate_per_sec=8.0/max_concurrency=6 — the highest step
  that stayed clean on BOTH the quota signal and the canary, not the
  higher-throughput step that only stayed clean on quota. Generalized
  as a standing rule in `docs/lessons.md` ("A load probe that only
  watches the remote quota signal can still ship a config that
  degrades the live site"): every future load probe against a
  destination shared with the live site carries an independent,
  user-facing canary as a first-class stop condition, not the remote
  quota signal alone.
- **Disposition**: `prose` (`docs/lessons.md` entry + this ledger row)
  — no automated gate exists yet that would block a future probe
  script from omitting a canary; a future promotion candidate if this
  pattern recurs (see `docs/lessons.md`'s own triage note).

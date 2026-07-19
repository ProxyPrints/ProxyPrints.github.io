# CORR-0008: ramp-probe instrument serialized latency, could never reach target rate

- **Date**: 2026-07-19
- **Trigger / wrong premise**: the ramp-probe instrument (task #163)
  serialized latency and its own pacing gap — request N+1 waited on
  request N's full round-trip plus the pacing delay, rather than the
  two overlapping — so the probe could never actually reach its target
  request rate regardless of how the rate parameter was set.
- **How caught**: owner-relayed live probe output plus the session's
  own self-diagnosis against that output. No commit-level evidence:
  the fix iterated inside the running container, not as a discrete,
  separately-committed change — **source for this entry is the
  session's own report, not a SHA**. This establishes the ledger rule:
  entries MAY cite a report as evidence when no commit SHA exists; the
  correction is the fact being recorded, and a commit is one kind of
  evidence for it, not the only kind.
- **Blast radius**: every ramp-probe run before the fix under-measured
  true throughput/latency at any target rate above whatever the
  serialized path could sustain — a systematic instrument bias, not
  random noise, so any prior probe result compared against a rate
  target should be treated as suspect until re-run post-fix.
- **Systemic fix**: replaced the serialized request/pace loop with a
  worker-thread pool sized to match production concurrency, so
  requests genuinely overlap instead of queuing behind each other's
  full latency.
- **Disposition**: `gate` (the instrument itself is the fix — a future
  probe run structurally can't regress to serialized pacing without
  someone deliberately reverting the thread-pool change).

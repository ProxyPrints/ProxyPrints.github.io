# Stage C full-catalog extraction — completion record (2026-07-26)

Full re-extraction of the entire card catalog under the decoupled
fetch/compute architecture, superseding all prior Stage C runs (canaries,
20k cohort, and the Jul 21–22 remainder leg). Preceded by
[`2026-07-20-decoupled-canary-confirm.md`](2026-07-20-decoupled-canary-confirm.md)
and
[`2026-07-21-stagec-20k-extraction.md`](2026-07-21-stagec-20k-extraction.md).

This session did not execute the extraction — it records the result against
the live DB (`mpcautofill_django`) as of 2026-07-27. All figures below come
from `SELECT`/`count()` queries; no writes were made.

## Run parameters

| run_id                                  | last write | rows (last-writer) |
| --------------------------------------- | ---------- | -----------------: |
| `pass-pilot-20260725`                   | 2026-07-25 |                100 |
| `stage-e-stream-20260725T233633221123Z` | 2026-07-25 |                 22 |
| `stage-e-stream-20260725T233633687349Z` | 2026-07-25 |                 23 |
| `pass-full-20260725`                    | 2026-07-26 |            194,831 |
| `pass-full-20260725-r2`                 | 2026-07-26 |             23,132 |
| **Total**                               |            |        **218,108** |

A 100-card pilot (`pass-pilot-20260725`) preceded the main legs. Two
`stage-e-stream-*` entries represent Stage E streaming activity on 45 cards
total. The two main legs (`pass-full-20260725` + `-r2`) together cover
217,963 cards.

The `pass-full-20260725` pair is a **full re-extraction**: every prior
last-writer row (`stagec-remainder-0721`, `stagec-20k-20260721T0227Z`,
`ntx-0721`, and the two Jul-20 canaries) has been replaced — none of those
run_ids appear as last-writer for any `ImageEvidence` row in the current
DB. The Stage C run history table in
[`../pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md) §6 reflects
this updated state.

## Coverage

- Total cards in DB: **218,516**
- Cards with any `ImageEvidence` row: **218,108** (99.8%)
- Cards with no `ImageEvidence` row: **408** (0.2%) — all `GOOGLE_DRIVE`-sourced

Of the 218,108 cards with evidence:

- `fetch_ok=True`: 216,494 (99.3% of those with evidence — successfully extracted)
- `fetch_ok=False`: 1,614 (0.7% — fetch attempted, image unavailable, evidence row
  written with failure recorded)

The 408 cards with no evidence at all were never successfully started during any
pass; all are `GOOGLE_DRIVE`-sourced.

## Fetch-failure rate vs. prior runs

| run                                                           |       cards | fetch_ok=False |      rate |
| ------------------------------------------------------------- | ----------: | -------------: | --------: |
| Bundled canary (`stagec-canary-20260720T1659Z`)               |         400 |              0 |      0.0% |
| Decoupled canary (`stagec-canary-decoupled-20260720T235127Z`) |         400 |              6 |      1.5% |
| 20k cohort (`stagec-20k-20260721T0227Z`)                      |      20,000 |            105 |     0.53% |
| **Full catalog (`pass-full-20260725` + r2)**                  | **218,108** |      **1,614** | **0.74%** |

The full-catalog failure rate (0.74%) is higher than the 20k cohort's 0.525%.
This is consistent with broader catalog coverage: the 20k cohort used
edhrec_rank-ascending ordering (popular cards first, cold tail deferred), while
the full pass covered the entire cold tail — where per-file breakage across
independent Drive folders is more prevalent.

## No-pixels invariant

Not re-checked in this session — the schema inspection in
[`2026-07-21-stagec-20k-extraction.md`](2026-07-21-stagec-20k-extraction.md)
applies unchanged. `ImageEvidence` holds hashes, measurements, classification
strings, OCR text, and pixel coordinates; no field is capable of holding image
bytes.

## Stage completion

Stage C extraction is at **99.8% catalog coverage** (218,108 / 218,516).
The original compute profile
([`2026-07-20-pipeline-compute-profile.md`](2026-07-20-pipeline-compute-profile.md))
projected 116.2h single-threaded against a 6.2h reference budget (BLOCKING).
The decoupled fetch/compute architecture resolved that gap; this record
confirms the full catalog has now been extracted under that architecture in
production.

## Open items

1. The 408 cards with no `ImageEvidence` are unreachable by Stage D unless a
   targeted re-extraction pass succeeds for them. No such pass is scheduled;
   they are expected to remain unresolved unless their Drive sources are
   repaired or re-indexed. All are Google Drive — no other source type
   contributes to the gap.

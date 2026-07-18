As of: 2026-07-18
Task: item 3 — Dawid-Skene readiness re-check (analysis-only, no code)
Branch/worktree: catalog-completion-part2

## What "readiness" means here

The referenced block is `docs/theory.md` §6 ("Sybil/bad-actor
unification") + its "Relation to Dawid-Skene reliability estimation"
subsection, and the mirrored addendum in
`docs/features/catalog-completion-plan.md` Part 6 item 6 (added
2026-07-16). Both state their own trigger explicitly: "nothing built
until there's an observed attack or real resolution volume." This
re-check evaluates that trigger against real current production data,
not against assumption — the question is whether the four proposed
detectors (per-`anonymous_id` disagreement rate, cluster-consistency
contradiction check, cohort revocation by `created_at` window, trust
tiers) are now justified.

## Real numbers (live production DB, read-only query, 2026-07-18)

| Table           | Total  | ocr    | deduction | user (human) |
| --------------- | ------ | ------ | --------- | ------------ |
| CardPrintingTag | 88,185 | 60,034 | 28,112    | 39           |
| CardArtistVote  | 7,137  | 7,131  | —         | 6            |
| CardTagVote     | 60,138 | 60,111 | —         | 27           |

Human (`user`-sourced) `CardPrintingTag` rows: **39 total, across only
4 distinct `anonymous_id`s** (22, 15, 1, 1 votes each). Artist/tag
human votes are smaller still (6 and 27).

## Verdict: not ready, and the reason is a category mismatch

Total row counts across the three tables now exceed 155,000 — on its
face, "real resolution volume." But that volume is overwhelmingly
machine-cast by this session's own trusted pilot engines (`ocr`,
`deduction` — a handful of known, audited `anonymous_id`s: the
printing-tag pilot, the LANDS module, the name-frequency engine,
etc.), not by a large or diverse population of untrusted human voters.

The addendum's detectors are specifically an **integrity layer against
human bad actors** — per-`anonymous_id` disagreement rate needs enough
votes _per human source_ to distinguish a real behavioral pattern from
noise; cohort revocation by `created_at` window needs an actual
suspect population to scope. With only 4 distinct human voters and 22
being the largest single contribution, any such detector would not be
detecting a _pattern_ — it would just be re-identifying one of four
individuals. That's not a meaningful reliability estimate, it's
deanonymization with extra steps. Volume grew enormously this session,
but on the wrong axis: pipeline throughput, not human participation.

The other trigger condition — "an observed attack" — also remains
unmet. Nothing in this session's work (or any prior session) surfaced
adversarial behavior, coordinated bad-faith voting, or any contradiction
pattern worth investigating.

**Conclusion: still not ready by the addendum's own stated bar.**
Re-check again once real human vote participation (not machine pilot
throughput) grows materially past today's 4 distinct voters, or if an
actual contradiction/attack is observed.

## One nuance: the cluster-consistency detector doesn't need this gate

Of the four proposed detectors, "cluster consistency as a free
contradiction detector" (`d=0` cluster members resolving to _different_
printings) is structurally different from the other three — it's a
data-integrity check over the existing clustering output, not a
population-based Sybil/reliability estimate. It needs no human-voter
volume to be meaningful; a single contradiction is already a real bug
signal regardless of how many people have voted. It could reasonably be
built as a report-only check independent of this readiness question.
Not built here — flagging it as the one item in the addendum that isn't
actually gated by the same condition as the other three, in case
whoever picks this up next wants to split it out.

## Verification

Read-only ORM query (`manage.py shell -c`) executed inside the
already-running `mpcautofill_django` live-serving container via
`docker compose exec` (not `run --rm` — this was a read, no image
rebuild or restart needed, and no writes were issued). Live serving
containers were not restarted or otherwise touched. Numbers are exact
counts from the query output, not extrapolated or estimated.

## Open items / decisions needed

1. None requiring action now — this is a "not yet" verdict per the
   addendum's own stated gate, not a new decision to make.
2. Whether to split out the cluster-consistency detector as a
   standalone report-only check (unblocked by the human-volume gate) is
   a real option for whoever next touches this, not decided here.

## Live state

Nothing written, nothing built, matching the addendum's own "analysis
only" framing. No code changes in this task.

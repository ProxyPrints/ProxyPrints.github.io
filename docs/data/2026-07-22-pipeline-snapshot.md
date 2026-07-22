# Pipeline data snapshot — 2026-07-22

Sibling of [`2026-07-22-pipeline-snapshot.json`](2026-07-22-pipeline-snapshot.json).
Point-in-time record, same convention as `docs/reports/` — a query re-run
even an hour later will read different numbers on any group that's still
actively growing (vote pool, tag-status persistence, distinct artist
names). Every group below states whether it's expected to be stable
(a completed, historical run) or live (grows continuously as the pipeline
keeps running).

**Intended eventual consumer**: the homepage panel's reserved-not-built
catalog-stats chart slot (`HomepagePanel.tsx`, see
[`../features/homepage-panel.md`](../features/homepage-panel.md)) — no
chart consumes this file yet. Snapshots accumulate one file per date,
same schema (`schemaVersion: 1` in the JSON), so a future chart-generation
step can glob `docs/data/*-pipeline-snapshot.json` and read a time series
without per-file special-casing. Don't rename group `id`s or restructure
`series` shape in a later snapshot without also bumping `schemaVersion`
and noting the break here.

## Provenance, group by group

All queries run 2026-07-22 via
`sudo docker exec mpcautofill_django python manage.py shell -c "..."`
against the live production Postgres (read-only; no writes performed by
any query below). Model names are `cardpicker.models.*`.

- **`catalog-scale`** (live, grows continuously):
  - Total cards / distinct sources: `Card.objects.count()`,
    `Card.objects.values('source').distinct().count()`.
  - Cards with a current ImageEvidence row: `ImageEvidence.objects.count()`
    (one row per (card, content_hash) currently live per card — see
    `ImageEvidence`'s own docstring on why this isn't 1:1 with `Card.objects.count()`
    if any card's image changed after its first extraction).
  - Distinct OCR'd artist names: `ImageEvidence.objects.exclude(artist_ocr_name='').values('artist_ocr_name').distinct().count()`.
    **Re-queried number is 3,550**, not the 3,047 quoted earlier the same
    day — this field grows as Stage C extraction keeps running; re-query
    before citing, don't trust a same-day number that's more than an hour
    or two old.
- **`extraction-run-stagec-remainder-0721`** (historical, frozen — this
  run has completed and its stats are never re-derivable from the DB):
  cards-processed/fetch-failures/short-circuited are in-memory counters
  the run itself accumulates and prints in its own completion summary
  line (`_CohortStats` in `management/commands/run_image_evidence_cohort.py`)
  — by design they are **never persisted onto `ImageEvidence`** (that
  model docstring is explicit: `run_id` is a last-writer field, not an
  append-only per-run ledger). These three figures are therefore taken
  from that run's own completion log as relayed by the owner, not
  re-derived by a query in this session — there is no DB query that could
  reproduce them after the fact.
- **`image-evidence-by-run`** (mixed: historical runs, but the row counts
  are a live re-derivable query today): `ImageEvidence.objects.exclude(run_id__isnull=True).values('run_id').annotate(c=Count('id'))`.
  Note this counts **current last-writer rows per run_id**, not
  "cards processed by that run" — a card processed by an earlier run and
  never re-extracted since keeps that earlier run_id as its last writer,
  while a card re-extracted by a later run silently moves its row's
  run_id attribution forward. `stagec-remainder-0721`'s 197,470 here is
  larger than that run's own 141,369-processed figure above for exactly
  this reason (it's also currently the last writer for cards originally
  touched by earlier, now-superseded extraction passes).
- **`vote-pool-printing` / `-tag` / `-artist`** (live, grows continuously
  — vote counts documented in the task brief as "aging by the hour," all
  re-queried fresh rather than trusted): `CardPrintingTag.objects.count()`
  / `.values_list('source').annotate(Count('id'))`, same shape for
  `CardTagVote` and `CardArtistVote`. All three re-queried numbers matched
  the brief's same-day figures exactly (101,105 / 61,334 / 7,137 total),
  confirming no drift occurred between the brief being written and this
  query running.
- **`status-printing-tag` / `status-artist-vote`**: `Card.objects.values_list('printing_tag_status').annotate(Count('id'))`
  and the same for `artist_vote_status` — both are per-`Card` denormalized
  cache fields (`models.py`'s `PrintingTagStatus`/`ArtistVoteStatus`
  `TextChoices`), not per-vote-pair statuses.
- **`status-tag-vote-persisted`**: `Card.tag_vote_statuses` is a
  **per-`Card` JSONField** keyed by tag name (`{tag_name: TagVoteStatus}`),
  not a plain model field — there is no single-column `annotate` for it.
  Queried by iterating `Card.objects.exclude(tag_vote_statuses={})` and
  tallying a `collections.Counter` over each dict's values
  (7,310 cards currently carry at least one entry; 12,125 total
  (card, tag) entries tallied across them). This number is **smaller**
  than the impact-report group's 61,328 tag pairs checked below — that's
  expected, not a discrepancy: most vote pairs the resolver can already
  see have never had their status **materialized** onto `tag_vote_statuses`
  yet (a separate, not-yet-run recompute step), which is exactly what the
  impact report's `None->unresolved: 49207` line is counting.
- **`impact-report-dry-run`** (frozen at today's dry-run instant, but
  fully re-derivable at any time via the same command): fresh run of
  `python manage.py consensus_impact_report --sample-limit 5` (zero
  writes — the command DRY-RUNS the ratified resolver against every
  printing/artist/tag pair with a recorded vote, per its own `--help`
  text). Re-running today reproduced the brief's exact figures: printing
  92,368 pairs / 0 transitions, artist 7,130 pairs / 0 transitions, tag
  61,328 pairs with 49,207 `None->unresolved` materializations still
  pending an actual (separately owner-gated) recompute pass. "Zero
  transitions" on printing/artist means the ratified resolver's answer
  already matches every currently-persisted printing/artist status
  exactly — nothing would change if recompute ran on those two paths
  today.

## Relationship to the pipeline-fidelity gate

This snapshot is the Part A verification source for the pipeline-fidelity
gate's data (GitHub issue #154) — the `impact-report-dry-run`,
`image-evidence-by-run`, and `vote-pool-*` groups above are cited
directly by [`../pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md),
which is the gate's canonical status page. This file stays the raw,
dated data record; the hub owns the gate's status and open decisions.

## Relationship to the ratification this snapshot follows

This file is a data checkpoint taken the same day the vote-weight
ratification (`docs/reference/vote-weight-matrix.md`, implemented in
PR #325) landed — the `impact-report-dry-run` group above is measuring
that ratified resolver's behavior against the live vote pool, not the
pre-ratification resolver. It is not itself part of the ratification
record; see `docs/theory.md`'s §4/§7a and
`docs/identification-pipeline.md`'s g5 paragraph for the narrative
explanation of what changed and why.

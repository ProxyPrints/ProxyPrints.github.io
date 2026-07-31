# Pipeline batching rework + md5 verdict transfer

Two independent work streams, spec'd together per owner direction. Neither depends on the other;
both target `run_pipeline.py` (the monolith) and/or `stage_e_dispatch.py` (the streaming conveyor).

---

## Work stream A — Sequential per-chunk C→D (Option B)

### What breaks

The monolith currently runs Stage C as one subprocess over the whole catalogue, then Stage D in bulk
over the whole catalogue, then Stage C+ (cluster propagation) as a separate pass:

```
call_command("run_image_evidence_cohort", ..., limit=WHOLE_CATALOGUE_LIMIT)
...
_run_stage_d(batch_ids=None, ...)          # bulk: ALL eligible cards
...
_propagate_cluster_votes(...)               # separate fixup pass
```

That means D never starts until C finishes every single card (~230k at ~561ms/card = ~36h for the
fetch-bound bulk). The autoscaler (`stage_e_batch_sizing`) is designed for the STREAMING conveyor's
`_run_stage_c` (sequential per-card, one fetch-ahead thread), not for the pooled
`run_image_evidence_cohort` subprocess.

**The fix: the monolith drives the same `dispatch_micro_batch` call `stream_full_catalog` already
drives**, replacing the subprocess+bulk-D structure entirely. Streaming is the default and only
mode — the current subprocess approach is removed (it does not interleave C and D, which is
required).

### What it becomes

```
for chunk in keyset_paginated_chunks(batch_size=250):
    dispatch_micro_batch(card_ids=chunk, ...)   # runs C then D over chunk
# after all chunks:
_propagate_cluster_votes(...)                    # still needed for phash tier;
                                                 # md5 tier becomes redundant (stream B)
_env_re_sample()
_fidelity_gate()
_channel_report()
```

### Where the change lives

**`run_pipeline.py`:** Replace the sequential stages (`_run_stage_c` subprocess → `_run_stage_d_bulk`)
with a loop that drives `dispatch_micro_batch` per chunk. The loop is the same pattern
`stream_full_catalog` already uses (keyset-paginated, batch-sized, envelope-gated per dispatch).

The envelope sentry (`_EnvelopeSentry`) already re-samples between stages; `dispatch_micro_batch`'s
own envelope gate covers per-chunk sampling, so the sentry's mid-pass checks happen naturally at
each dispatch boundary.

**The autoscaler already covers this case.** `stage_e_batch_sizing.SATURATION_BATCH_SIZE = 250` is
measured against the streaming C's serial fetch floor, and the duration term bounds at `~300s`.
D completes in seconds per chunk, so it doesn't shift the sizing.

### What stays unchanged

- The four calculators + three chips in `_run_stage_d` — called per-chunk exactly as
  `dispatch_micro_batch` already does.
- Stage 0 (Scryfall refresh) — once, at the front.
- Stage C+ cluster propagation — still runs after the loop, still covers phash tier.
- Fidelity gate, channel report — unchanged.
- Envelope preflight + re-sampling — `_EnvelopeSentry` handles seam checks, `dispatch_micro_batch`
  handles per-chunk envelope gates.
- `--skip-stage-c`, `--skip-stage-d`, `--dry-run` — all forwarded; `--skip-stage-c` skips the
  per-chunk loop entirely.

### CLI flags added to `run_pipeline`

```
--batch-size N       chunk size (default: autoscaled SATURATION_BATCH_SIZE=250)
--max-batches N      stop after N chunks (default: whole catalogue)
```

### Dry-run interaction

`--dry-run`: first chunk dispatched (proves the mechanism), then plan printed for the remainder.

---

## Work Stream B — md5 verdict transfer (D-level short-circuit)

### What breaks

`evidence_transfer` already saves a fetch (Stage C) for md5 siblings. But those siblings still go
through Stage D independently — all four calculators + three chips, with copied evidence. Two
md5-identical cards from different sources often carry DIFFERENT `Card.name`s and DIFFERENT
eligibility, so they routinely reach DIFFERENT Stage D conclusions (monolith docstring §650-656).
Stage C+ (cluster propagation) then has to fix up the md5 group afterward by propagating the
correct verdict from whichever member has it — which is a post-hoc repair, not a prevention.

### What it becomes

The **first** card with md5=X to emerge from C in this run is the **rep**. It goes through Stage D
normally. Every subsequent card with md5=X in the same run **skips D entirely** — its verdict is
propagated from the rep's recorded votes immediately after the rep's D batch completes (or at the
latest when the propagation queue drains).

The rep's verdict is cached per-run by md5. The cache is written after the rep completes D, and
checked before each card would enter D.

### Implementation

**A. Verdict check: DB query, not in-memory cache scoped to rep**

The rep (the "first" card with a given md5 to get a Stage D verdict) is extremely likely to have
been measured in a PREVIOUS batch of this run, or not to be in the current batch at all. A
per-rep in-memory cache misses that case. The check must be a DB query: "does ANY card with this
md5 already have a Stage D printing verdict under the current run_id?"

Pre-fetched once per batch, before the D gate:

```python
md5s_in_batch = set(
    Card.objects.filter(pk__in=batch_ids, md5_checksum__isnull=False)
    .exclude(md5_checksum="")
    .values_list("md5_checksum", flat=True)
)
if md5s_in_batch:
    md5s_with_votes = set(
        CardPrintingTag.objects.filter(
            card__md5_checksum__in=md5s_in_batch,
            run_id=run_id,
            is_no_match=False,
            printing_id__isnull=False,
        ).values_list("card__md5_checksum", flat=True).distinct()
    )
else:
    md5s_with_votes = set()
```

Cards whose md5 is in `md5s_with_votes` → propagation queue (skip D). Cards not in it → D batch
(this card becomes the rep for this md5 in this run).

Cross-batch win: batch 1's rep finishes D → its vote is written to `CardPrintingTag` under
`run_id` R → batch 47's md5 sibling queries `CardPrintingTag` by md5 + `run_id` → finds batch 1's
vote → skips D.

Across runs: a fresh `run_id` starts with an empty verdict pool. The first card in each md5 group
enters D and becomes this run's rep. Subsequent siblings (in later batches) find the just-written
vote via the DB query and skip D. This is correct by design — a fresh run_id reconsiders everything.

On a resumed run (same `run_id` re-passed): the DB query finds votes from the previous invocation's
batches, so resume batches immediately skip D for all md5s already resolved.

**B. Propagation queue**

Cards whose md5 has an existing verdict are added to a list, not processed through D. After D
completes for the current batch's reps, the queue is drained: each queued card gets
`build_propagated_cluster_votes(...)` called with the rep's verdict data, then the rows are written
via the existing `purge_and_write_votes`.

The source votes are read from `CardPrintingTag` for the known md5 groups — the same pre-fetch
query above can also return the actual vote rows. Since `build_propagated_cluster_votes` already
handles eligibility (skips resolved cards, canonical cards, tokens, custom-art, non-english), the
propagation is safe to call on any card.

**C. Integration point**

In the **streaming conveyor** (`dispatch_micro_batch`): the verdict gate sits between `_run_stage_c`
and `_run_stage_d`. After C completes for the batch, partition cards via the pre-fetch query above:

- **Unresolved md5s** → D batch (these cards become reps)
- **Resolved md5s** → propagation queue

After D completes, drain the propagation queue — near-instant (one query + one bulk write per md5
identity group).

In the **monolith** (same gate, inside the per-chunk loop from stream A): identical logic.

**D. C skip already exists**

The evidence transfer inside `_run_stage_c` already handles the C-level skip. Siblings that share
md5 with an already-fetched card get `transfer_evidence` called and never reach the fetch-ahead
thread. The md5 verdict gate thus sees md5 siblings that ALREADY have evidence — it only decides
whether to skip D.

### What stays unchanged

- `_run_stage_d` — still called once per batch for the unresolved-md5 cards. The function itself
  doesn't change.
- `build_propagated_cluster_votes` — called as-is for each md5 identity group in the queue.
- `purge_and_write_votes` — unchanged.
- Stage C+ cluster propagation — still runs for the phash tier. The md5 tier becomes redundant
  (the verdict gate already propagated votes inline). The monolith's `_propagate_over_groups` skips
  md5 groups that have zero new work (already-voted check).

### Monolith Stage C+ interaction

The monolith's `_propagate_cluster_votes` currently runs md5+phash tiers as a separate stage. With
verdict transfer inline, the md5 tier finds nothing to do (all md5 siblings already got their votes
propagated) and skips immediately. The phash tier still runs.

Removing the md5 tier from C+ entirely is a future cleanup (post-verdict-transfer-verify) — kept
for one cycle to prove the inline propagation matches.

### Envelope interaction

The propagation queue drain is near-instant (one query + one bulk write per md5 identity group,
pure Python otherwise). It runs after D completes, so it doesn't delay envelope re-sampling.

### Crash safety

A card whose rep was in a batch that CRASHED (D never completed for that rep) has no votes in the DB
for this run_id, so the DB query returns False for that md5. The card enters D as the rep —
correctly.

Duplicate propagation guards: `purge_and_write_votes` carries `ignore_conflicts=True` on the bulk
create, so re-propagating to an already-propagated card is a counted no-op.

---

## Interaction between the two streams

They are independent and can be merged in any order. Stream A changes the monolith's driver loop;
Stream B adds the verdict gate, which works identically whether D is called per-chunk or in bulk.

Recommended order:

1. **Stream B first** — verdict transfer works in the current bulk-D structure. Proves the
   mechanism, no driver change.
2. **Stream A second** — per-chunk C→D in the monolith, reusing the streaming conveyor's
   `dispatch_micro_batch`. The verdict gate from Stream B integrates naturally.

---

## Files changed

| File                             | Stream A                                                                                 | Stream B                                                                         |
| -------------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `run_pipeline.py`                | New `_run_streaming_stages` method, `--batch-size`, `--max-batches`, `--streaming` flags | Verdict cache, propagation queue, verdict gate in driver loop                    |
| `stage_e_dispatch.py`            | — (reused as-is)                                                                         | Verdict gate between `_run_stage_c` and `_run_stage_d` in `dispatch_micro_batch` |
| `stage_e_batch_sizing.py`        | Verify autoscaler accounts for D time in full-cycle measurement                          | —                                                                                |
| `tests/test_run_pipeline.py`     | Streaming mode test                                                                      | Verdict gate unit test                                                           |
| `tests/test_stage_e_dispatch.py` | —                                                                                        | Verdict gate unit test (propagation queue drain)                                 |

As of: 2026-07-18
What this is: survey + HOLD proposal for a public `/stats` transparency page — single-instance now, federation panel designed but not built.
HOLD — build not started. Queued after Proposal E, per the approved order.

## Summary

Every number this page would show already has a real, populated field to draw from — the gap everywhere is aggregation, not data. **No existing code currently computes any of the 7 aggregates below**; each is a genuinely new query, small in every case (the model fields, indexes, and enums already exist). One existing endpoint (`GET 2/contributions/`) already does the closest live equivalent of what the whole page should become: a periodic, cached artifact instead of a live query.

Proposing **7 charts** (within the 6-8 budget), a `stats.json` schema with an explicit dormant `federation` slot, and a new management command following this codebase's own existing "compute a stats dict, then report it" pattern (seen in `import_scryfall_printing_metadata.py`) — just writing JSON instead of printing.

## Constraints, confirmed against the survey

- **Aggregate-only, no visitor tracking.** Every data source below is server-side catalog/moderation state — nothing here is a page view, a session, or an IP. Advertising "zero-telemetry" is itself a page section (see mock, below).
- **Static JSON, generated on a schedule, zero live aggregate queries from public traffic.** This is the one clear architectural decision this repo doesn't already answer: the frontend is a GitHub Pages static export with no server of its own, so `stats.json` needs to be _served_ from somewhere reachable by static pages — most likely the same R2 bucket already fronting the image CDN (`docs/features/image-cdn.md`), or a Django route that only ever serves the last-generated file with a long cache header (never re-runs the aggregation on request). Flagged as an open decision below, not assumed.
- **Mobile-first, solid-color utilitarian style.** No gradients, no decorative chrome — matches this page's own subject (raw operational transparency) rather than a marketing treatment.

## Survey: what exists today, source by source

### 1. `PilotRunLedger` — run history

`MPCAutofill/cardpicker/models.py:973-1002`. One row per pilot-command invocation (`local_identify_printing_tags`, `local_name_frequency_elimination`): `run_id`, `command`, `dry_run`, `status` (running/completed/failed), `git_sha`, `started_at`, `finished_at`, `votes_written`, `purged_at`. Written only by those two commands; read only by `purge_machine_votes.py` (single-row lookup) and the Django admin changelist (per-row, no aggregation). **Nothing aggregates this today** — run counts, average duration, total votes-written-across-all-runs are all new queries (`.count()`, `Avg(F('finished_at')-F('started_at'))`, `Sum('votes_written')`).

### 2. `CardScanLog.skip_reason` — abstention census

`MPCAutofill/cardpicker/models.py:1005-1042`. One row per (card, engine) the engine looked at and declined to vote on. `skip_reason` is free-text (no DB-level enum); 11 distinct values observed across the OCR/phash/fallback engines (`unfetchable-image`, `parsed-but-no-match`, `no-text`, `no-hashable-candidates`, `no-clear-winner`, `too-many-candidates`, `no-evidence`, `eliminated`, `ambiguous`, `disagreement-with-other-engine`, `frame-mismatch`). A breakdown table exists exactly once — hand-run and pasted into `docs/theory.md:129-135` for one specific `run_id`, not a reusable query. **No management command or admin view reproduces this live.** New query: `CardScanLog.objects.values('skip_reason').annotate(count=Count('id'))`, optionally grouped by `anonymous_id` (engine) to match the doc precedent's shape.

### 3. `question_feed.py` — resolution-progress counts

`get_remaining_estimate()` (`question_feed.py:216-290`) already computes `total`/`confirmable`/`contested`/`fresh` as 4 independent `.distinct().count()` queries over `Card.printing_tag_status`/`artist_vote_status`/`tag_vote_statuses`, reusing two shared helper ID-sets (`get_contested_card_ids()`, a Python-side tag-status scan) so the whole thing costs 6 queries, no per-card loop. This is tagging-flow-specific (gates on `anonymousId`) and already documented at `docs/features/printing-tags.md:100-122`, but the underlying query shape is exactly a public "N cards resolved / N contested / N fresh" chart — same fields, same enums, no `anonymousId` needed for a public aggregate.

### 4. Vote counts by `source` + `vote_surface`

`AbstractWeightedVote` (`models.py:570-623`) backs `CardPrintingTag`/`CardArtistVote`/`CardTagVote`. `source` (`VoteSource`: USER/ADMIN/DEDUCTION/OCR/FEDERATED) and `vote_surface` (free-text, added migration 0064, currently populated by exactly 3 human-vote endpoints — printing tag, artist vote, tag vote — never by machine votes) are both real, populated, queryable columns. **`vote_surface` is write-only today** — grepping the whole app for reads outside `models.py`/`views.py`/tests returns nothing. The only existing `.values().annotate()` aggregations in the vote modules are per-card consensus-resolution grouping (`vote_consensus.py:173`, `tag_consensus.py`), not app-wide breakdowns. New query: `.values('vote_surface', 'source').annotate(count=Count('id'))`, bucketed by `created_at` for the "confirmations over time" chart.

### 5. `content_phash` coverage

`Card.content_phash` (`BigIntegerField`, nullable — `NULL` means "not yet computed," migration 0062). Backfilled by `local_backfill_content_phash.py` → `run_content_phash_backfill()` (`local_phash.py:207-325`), which prints `Hashed N/total_candidates` per invocation — but `total_candidates` there is _that run's own remaining backlog_, not the full catalog, so it can't be read as a standing coverage percentage. **The only coverage number that exists anywhere is a single hand-checked snapshot in a planning doc**: `docs/features/catalog-completion-plan.md:426-428`, "0/218,152 populated" as of 2026-07-16. New query: `Card.objects.filter(content_phash__isnull=False).count()` vs. `Card.objects.count()`.

### 6. Management-command precedent

No existing command writes JSON. Closest shapes to build on: `import_scryfall_printing_metadata.py` (computes a `stats` dict from a helper function, then reports it — the cleanest pattern to extend into `json.dump`), `db_image_size.py` (a single `.aggregate(Sum(...))` reported as one summary line), `export_sources.py` (the only command that writes any file to disk today, though CSV with a hardcoded path, not a JSON-and-schedule pattern).

### 7. Existing public aggregate surface

`GET 2/contributions/` (`views.py:538-554`) is the one already-public, unauthenticated, catalog-wide aggregate endpoint — raw SQL (`summarise_contributions()`, `models.py:225`) joining source/card, grouped by source, live on every request. This is the exact query this proposal's "catalog composition by source" chart would reuse, just moved from a live per-request query to a periodic one baked into `stats.json`.

## Proposal (hold): 7 charts

| #   | Chart                               | Data source                                                                                                     | New aggregation needed                                                         |
| --- | ----------------------------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| 1   | Catalog resolution progress         | `Card.printing_tag_status`/`artist_vote_status`/`tag_vote_statuses`, same enums `question_feed.py` already uses | Yes — public reframing of §3's per-user tier counts as a catalog-wide snapshot |
| 2   | Confirmations over time, by surface | `AbstractWeightedVote.vote_surface` + `created_at`, all 3 vote tables                                           | Yes — `vote_surface` is currently write-only                                   |
| 3   | Machine-vote yield by engine        | `PilotRunLedger.votes_written` + `CardScanLog` grouped by `anonymous_id` (engine)                               | Yes — pairs §1 and §2's raw fields, no existing join                           |
| 4   | Scan-log skip breakdown             | `CardScanLog.skip_reason`, grouped by reason (+ engine)                                                         | Yes — one precedent exists as a hand-run doc table, not code                   |
| 5   | Backfill / hash coverage            | `Card.content_phash` null-vs-populated count                                                                    | Yes — only a single manual snapshot exists today                               |
| 6   | Run history                         | `PilotRunLedger`, one row per invocation, status/duration/votes_written over time                               | Yes — admin changelist only, no aggregation                                    |
| 7   | Catalog composition by source       | `GET 2/contributions/`'s existing `summarise_contributions()`                                                   | No new query — reuse verbatim, just cache instead of live-query                |

Chart 7 is the cheapest of the seven for exactly that reason — it's the one place this proposal replaces a live public query with a cached one, rather than adding a new aggregation from scratch.

## Federation panel — slots designed, nothing built

Deferred until a peer node actually exists (per `docs/federation-v1.md`), but the schema reserves its shape now so the eventual build is additive, not a redesign:

```
federation: {
  enabled: false,
  peers: [],           // populated once verdict-exchange (federation-v1.md) has a live peer
  metrics: {
    peerCount: null,
    crossNodeConsensusOverlap: null,   // % of resolved printings agreeing across peers
    federatedVoteCount: null           // VoteSource.FEDERATED rows, once non-zero
  }
}
```

Rendered today as a dimmed, disabled panel with "Federation: not yet active — coming when a peer node exists," never hidden entirely (the page should say this is coming, not silently omit it).

## `stats.json` schema (proposed)

```jsonc
{
  "generatedAt": "2026-07-18T00:00:00Z",
  "resolutionProgress": {
    "totalCards": 218152,
    "printing": { "resolved": 0, "contested": 0, "unresolved": 0 },
    "artist": { "resolved": 0, "contested": 0, "unresolved": 0 },
    "tags": { "resolved": 0, "contested": 0, "unresolved": 0 }
  },
  "confirmationsOverTime": {
    "bucketDays": 7,
    "series": [
      {
        "weekStart": "2026-07-06",
        "bySurface": { "question-feed": 0, "deckbuilder": 0, "unlabeled": 0 }
      }
    ]
  },
  "machineVoteYield": {
    "byEngine": [
      { "engine": "ocr", "votesWritten": 0, "skipped": 0 },
      { "engine": "phash", "votesWritten": 0, "skipped": 0 },
      { "engine": "deduction", "votesWritten": 0, "skipped": 0 },
      { "engine": "fallback", "votesWritten": 0, "skipped": 0 }
    ]
  },
  "scanLogSkipBreakdown": {
    "byReason": [{ "reason": "no-clear-winner", "count": 0 }]
  },
  "hashCoverage": {
    "totalCards": 218152,
    "hashed": 0
  },
  "runHistory": {
    "recent": [
      {
        "runId": "...",
        "command": "local_identify_printing_tags",
        "status": "completed",
        "startedAt": "...",
        "finishedAt": "...",
        "votesWritten": 0
      }
    ]
  },
  "catalogComposition": {
    "cardCountByType": { "card": 0, "cardback": 0, "token": 0 },
    "totalDatabaseSizeBytes": 0,
    "bySource": [{ "name": "...", "qtyCards": 0, "avgDpi": 0 }]
  },
  "federation": {
    "enabled": false,
    "peers": [],
    "metrics": {
      "peerCount": null,
      "crossNodeConsensusOverlap": null,
      "federatedVoteCount": null
    }
  }
}
```

## Mock — mobile-first, solid-color, one screen's worth described

```
┌─────────────────────────────┐
│  /stats                     │
│  Zero visitor tracking —    │
│  every number below is      │
│  catalog/moderation state,  │
│  nothing about you.         │
├─────────────────────────────┤
│ ▉▉▉▉▉▉▉▉▉░░░░░  62%         │  ← resolution progress, solid fill bar
│  Printing resolution         │
├─────────────────────────────┤
│ ▉ question-feed  ▉ deck-    │  ← stacked bar, one color per surface
│ builder  ▉ unlabeled         │
│  Confirmations, last 8 wks   │
├─────────────────────────────┤
│  OCR    ▉▉▉▉▉▉  12,401       │  ← horizontal bars, one per engine
│  phash  ▉▉▉      6,218       │
│  dedn.  ▉▉▉▉▉▉▉▉ 18,004      │
├─────────────────────────────┤
│  no-clear-winner    ▉▉▉▉     │  ← skip-reason breakdown, sorted desc
│  too-many-cand.     ▉▉       │
├─────────────────────────────┤
│ ▉▉▉▉▉▉▉▉▉▉▉▉░░░  0 / 218,152│  ← hash coverage bar
├─────────────────────────────┤
│  Run history (last 10)       │
│  ✓ completed  ✓ completed    │  ← status dots, chronological list
│  ✗ failed     ✓ completed    │
├─────────────────────────────┤
│  Catalog by source            │
│  ▉▉▉▉▉▉▉ Source A  4,201      │
│  ▉▉▉ Source B      1,890      │
├─────────────────────────────┤
│  Federation  (dimmed)         │
│  Not yet active — coming     │
│  when a peer node exists.    │
│  Generated 2026-07-18 00:00   │
└─────────────────────────────┘
```

Single column at every width (no responsive multi-column reflow needed — this is the mobile layout at all breakpoints, per "mobile-first, solid-color utilitarian"). Every section is a solid fill (bars, dots), no gradients, no decorative imagery.

## Effort estimate

| Piece                                                                                      | Estimate     | Why                                                                                                                                        |
| ------------------------------------------------------------------------------------------ | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| New `generate_public_stats` management command (7 queries + JSON write)                    | Medium       | Every query is new but small (§1-6); follows an existing in-repo shape (`import_scryfall_printing_metadata.py`'s stats-dict pattern)       |
| Chart 7 (catalog composition)                                                              | Small        | Reuses `summarise_contributions()` verbatim — the only chart with zero new query logic                                                     |
| Schedule wiring (cron / management-command trigger)                                        | Small-Medium | Depends on the open hosting decision below — a Django-served route vs. an R2-bucket write changes what "on a schedule" means operationally |
| Frontend `/stats` page (7 static charts + federation-dimmed panel + zero-telemetry banner) | Medium       | Pure read of one JSON file, no live queries — mobile-first solid-color per constraint, no new interaction patterns to invent               |
| Federation panel (schema slot + dimmed UI only)                                            | Small        | Explicitly not building the underlying federation metrics — just the reserved shape + disabled-state UI                                    |

## Open decisions for the HOLD

1. **Where does `stats.json` live once generated?** The R2 bucket already fronting the image CDN, or a Django route serving only the last-written file with a long cache header (never re-aggregating on request). Both satisfy "zero live aggregate queries from public traffic" — this is a hosting choice, not a correctness one.
2. **Schedule mechanism** — cron on the same host as the pilot commands, a `django_q` scheduled task (already used elsewhere per `import_sources.py`'s async source-scan kickoff), or a GitHub Action hitting an authenticated trigger endpoint. Not resolved here.
3. **`vote_surface` label vocabulary** — currently free-text with exactly one real value in the wild (`"question-feed"`). Chart 2 needs a stable, finite label set to chart meaningfully; either enumerate expected surfaces now or bucket anything unrecognized as `"unlabeled"` (reflected in the schema above).

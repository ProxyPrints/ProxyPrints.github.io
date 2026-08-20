# Printing-aware card tagging ("What's That Card?" vote queue)

_Current-state reference, as of 2026-07-17._ Full stage-by-stage build
history (Stages 1–7 below): `git log e4eb6cb3 -- docs/features/printing-tags.md`
and earlier commits — that SHA is the last commit before this file was
rewritten from a linear changelog into this reference.

**Stage 8 onward (local/zero-API-cost printing-ID backfill, a.k.a. the
"catalog-completion" package) is still in active development and not yet
migrated into this file** — for its current status, architecture, and
known gaps, see [[catalog-completion-plan.md]] (that file is the live
source of truth for it) and this file's own tail section below the "Stage
8" heading, kept as-is until that work reaches a hold.

## What it does

Additive, upstream-pitchable feature letting users/admins tag which
Scryfall printing a `Card` (catalog image) depicts, with a
weighted-consensus mechanism to auto-resolve uncontested cases. A single
unified question feed (`GET 2/questionFeed/`) now drives voting for
printings, artists, tags, and moderation from one screen.

## Backend architecture

- **Data model**: `CanonicalCard` (`cardpicker/models.py`) is already a
  per-printing model (`identifier` = Scryfall printing UUID, unique on
  `(expansion, collector_number)`) — no separate `CanonicalPrinting` model
  was added. `CanonicalPrintingMetadata` (OneToOne) holds the
  Scryfall fields `CanonicalCard` doesn't (full*art, border_color, frame,
  frame_effects, promo_types, edhrec_rank, released_at, lang), populated by
  `cardpicker/printing_metadata_import.py` +
  `import_scryfall_printing_metadata`. It also holds one field that is
  **not** Scryfall data: `catalogued_printings_count` counts how many
  `CanonicalCard` rows \_we* hold per oracle id, computed by that same
  importer as a `Counter` over our own table. It says nothing about how
  many printings Scryfall publishes, and cannot detect that our catalogue
  is missing printings, because it is derived from the catalogue itself.
  It was called `printings_count` until 2026-07-29 (migration 0099), and
  this document described it as Scryfall printing data — that was false.
  `CardPrintingTag.printing` FKs directly to `CanonicalCard`.
- **Artwork identity, per face**: the same model carries `art_crop_url`
  and two illustration columns at **different grains**, and consumers must
  pick deliberately. `illustration_id` is a **scalar, front-face-only**
  value — for a multi-faced row it is `card_faces[0].illustration_id`, so
  the back face's own artwork is not addressable through it.
  `face_illustrations` (JSON list, migration 0095) retains **every** face's
  own `illustration_id` paired with that face's own name, in `card_faces`
  order, so index 0 is the front and index 1 is the back. The scalar is
  unchanged and still front-face — the list is purely additive. Two
  properties of the list are load-bearing, and are pinned by
  `TestFaceIllustrations` in
  `cardpicker/tests/test_printing_metadata_import.py`:
  - It is **`[]` for anything that is not a genuine double-faced card**,
    gated on the `DOUBLE_FACED_LAYOUTS` allowlist (`transform`,
    `modal_dfc`, `double_faced_token`, `battle`, `reversible_card`) — the
    same allowlist `get_back_face_names` uses.
    `split`/`adventure`/`flip`/`aftermath`/`mutate`/`prototype` also nest
    several named modes under `card_faces`, but those modes are printed on
    **one** physical face; giving "Stomp" its own entry would assert a
    second scannable side of "Bonecrusher Giant" that does not exist, and
    would let a scan of the creature be attributed to the adventure's
    artwork. `meld` is out of scope by construction — meld pieces carry no
    `card_faces` of their own in this bulk data.
  - A face that Scryfall publishes no `illustration_id` for records
    **`None` rather than being dropped**, so the list's index keeps
    corresponding to the face's position — a consumer walking
    `card_faces[1]` must not have the list silently shift under it.
- **How this column refreshes** (it is not a one-off backfill):
  `import_scryfall_printing_metadata` is a **full-set, value-diffing
  upsert**, not insert-only and not a last-modified diff. Every run
  re-derives the desired row for every printing in the `default_cards`
  bulk file and compares it field-by-field against the stored row, joined
  on `canonical_card_id`: no match → CREATE, any `_METADATA_SYNC_FIELDS`
  member differs → UPDATE, all equal → SKIP, stored key absent from the
  desired set → DELETE. `face_illustrations` **is** in
  `_METADATA_SYNC_FIELDS`, and that membership is what makes an ordinary
  run populate rows that already exist — so this needs **no backfill
  command and no flag**; running the importer is the backfill. That
  membership is the whole load-bearing bit: `bulk_create` writes every
  column regardless, so had the field been omitted from
  `_METADATA_SYNC_FIELDS`, newly-seen printings would still have populated
  while every already-stored row stayed `[]` forever. The column therefore
  reads `[]` on every row imported before the field existed, until the
  next import run.
- **Expected coverage — a mostly-`[]` column is correct, not a bug.**
  Measured against the on-disk `default_cards` bulk file and production on
  2026-07-30: of **116,254** bulk rows, **1,594** carry a genuine
  double-faced layout with two or more faces, and all 1,594 join to a
  `CanonicalCard` that already has a `CanonicalPrintingMetadata` row. So a
  first import populates **1,594 of 113,224 rows (1.4%)** — 1,534 of them
  with a real `illustration_id` on every face, exposing **1,534**
  back-face illustrations the scalar column cannot address, and 60 with
  name-only entries whose `illustration_id` is `None` because Scryfall
  publishes no artwork id for those faces. The remaining ~111,630 rows are
  single-faced and **correctly** stay `[]`.
- **Card payload — machine-suggested printing + tag vote status** (Proposal H
  §4.4′, issue #184, PR #195; consumed by the Select Version section, issue
  #167 — see [[grid-selector.md]]'s own "Select Version section" entry):
  `Card.serialise()` (`cardpicker/models.py`) takes
  a keyword-only `include_suggested_printing: bool = False` argument.
  When `True`, `SerialisedCard.suggestedCanonicalCard` is populated with the
  printing named by a machine-cast (`VoteSource.DEDUCTION`/`OCR`)
  `CardPrintingTag` vote — mirroring `question_feed.py`'s
  `_confirm_suggestion_item` `ai_vote` lookup exactly (same filter, same
  "first" ordering) so the two surfaces can't drift on what counts as
  "machine-suggested" — but only while `printing_tag_status != RESOLVED`
  (never redundant with the already-resolved `canonicalCard`). Deliberately
  does **not** reuse `get_ranked_printing_candidates()` (Levenshtein-ranked
  candidate search) here — that's a distinct, much more expensive mechanism,
  fine per-slot-on-demand but not for a bulk result set. The flag defaults
  `False` (a zero-cost no-op) everywhere except the two bulk endpoints that
  actually need it — `post_cards`/`post_explore_search` in `views.py`, both
  paired with `models.suggested_printing_votes_prefetch()` on their queryset
  (a `Prefetch("printing_tags", ...)` filtered to machine votes, ordered by
  `pk`) so populating this field across a page of results costs **one extra
  query total, not one per card**. `_suggested_canonical_card()` reads that
  prefetch cache and, if the instance wasn't prefetched (e.g. a one-off
  shell/test lookup), falls back to a single bounded per-instance query
  rather than silently returning stale data — but any new bulk call site
  MUST attach the prefetch itself; the method will never do it for you, by
  design, so a forgotten prefetch fails safe (quietly `None`-heavy) rather
  than silently reintroducing an N+1 across a whole page.

  Separately, `SerialisedCard.tagVoteStatuses` (always populated, no flag,
  zero extra query cost — it's just `Card.tag_vote_statuses`, an
  already-loaded JSONField) collapses that field's 5-way DB status
  (`resolved_apply`/`resolved_reject`/`contested`/`unresolved`/
  `pending_approval`) down to the 2-way `"resolved"`/`"suggested"`
  distinction the frontend needs for the "Looks retro-frame? ✓" inline
  confirm-chip moment: `resolved_apply`/`resolved_reject` → `"resolved"`,
  `contested`/`unresolved` → `"suggested"`. `pending_approval` tags are
  **excluded from the object entirely** (never bucketed either way) — same
  reason they're excluded from `Card.tags` today: they're gated behind the
  sensitive-tag co-sign queue ([[moderation.md]]) and must not leak to
  ordinary users ahead of that review. A tag absent from the object has zero
  votes cast against it at all, same convention as the DB field it derives
  from. Schema source: `schemas/schemas/Card.json`'s `suggestedCanonicalCard`
  (references `CanonicalCard.json`, same shape as `canonicalCard`) and
  `tagVoteStatuses` (references the new `TagVoteDisplayStatus.json` enum) —
  both purely additive, no existing field renamed or removed.

- **Run-scoped eligibility + the vote archive** (2026-07-29, owner
  directive: _"prior runs must not suppress work in a new run; the CURRENT
  run's own output must, so a killed run resumes rather than redoing
  completed batches"_). Every Stage D printing-channel calculator used to
  ask _"have I EVER voted on / abstained on this card?"_, so a calculator's
  own history permanently narrowed every future run of it — a repaired
  engine could never re-examine anything the broken one had answered, which
  is why `stage-d-illustration` had to be version-bumped v1→v2 purely to
  escape its own scan-log rows. Both self-suppressing excludes
  (`.exclude(printing_tags__anonymous_id=…)` and the non-rescannable
  `CardScanLog` exclusion) now additionally match on the CURRENT `run_id`
  in `local_calculate_verdicts._eligible_cards_queryset` /
  `_slow_path_eligible_cards_queryset`,
  `local_illustration._eligible_illustration_cards_queryset` and
  `local_identify_printing_tags._eligible_base_queryset` (opt-in there;
  only lands passes a run_id today). `run_id=None` keeps the old behaviour
  for callers that genuinely mean "anything this identity has never
  touched" — `stream_backstop_sweep.verify_chunk` is the live one.

  Two things make this safe rather than a churn machine:

  - **The pre-write split compares the VALUE, not just the key.**
    `local_calculate_verdicts._split_new_printing_tag_votes` now compares
    the whole set of `(printing_id, is_no_match)` a batch proposes for a
    `(card, anonymous_id)` group against what is stored — the shape
    `local_illustration._split_new_illustration_votes` has always had. An
    unchanged verdict is still skipped (so a re-run over a converged
    catalogue writes nothing), and a CHANGED verdict now reaches the
    delete-then-insert instead of being dropped before it. Without this,
    un-suppressing eligibility buys nothing at all: the calculator
    recomputes the verdict and throws it away, and because the purge is
    scoped to the rows being written, a dropped row purges nothing and the
    stale vote survives verbatim.
  - **A superseded vote is ARCHIVED, not destroyed.**
    `models.purge_stale_machine_votes` copies every row it is about to
    delete into `ArchivedCardPrintingTag` first, stamped with the run that
    overwrote it. A separate table rather than retained generations in the
    live one because **nine of the thirteen modules that read
    `CardPrintingTag` bypass `resolve_vote_weight` entirely** — a
    zero-weight-by-run_id rule would not stop a retained generation being
    displayed by `views.py`, counted by `catalog_stats.py`, or treated as
    "already voted" by the eligibility query this work exists to
    un-suppress. Nothing in the pipeline reads the archive; the only
    consumer is the opt-in `manage.py local_calculate_verdicts --generation-diff <path>` debug report (generation-diffing is a debug
    flag, never a default write path — owner ruling). Retention is issue
    #575's janitor's ("keep the N most recent runs, sweep the oldest,
    never delete wholesale"), which is why both `run_id` and
    `superseded_by_run_id` are indexed.

  **Order within a batch is a CORRECTNESS constraint, not a performance
  one**: `fallback`, `illustration` and `slow-path` all select POSITIVELY
  from join-key's output, so "purge everything, then run them in parallel"
  gives three of the four an EMPTY eligible set — a silent near-no-op that
  looks like it worked. Required order stays join-key → fallback →
  illustration → slow-path. The upstream populations those three select
  from, and slow-path's fallback-voted exclusion, are deliberately NOT
  run-scoped: a converged upstream calculator writes no rows under a fresh
  run_id, so a run-scoped version of them is empty on every re-run.
  `cardpicker/tests/test_run_scoped_eligibility.py` pins all of the above,
  including the out-of-order empty-set failure.

- **Consensus**: `cardpicker/printing_consensus.py::resolve_printing(card)`
  — weighted-vote formula, weight by source (user 1, admin
  `PRINTING_TAG_ADMIN_WEIGHT` default 5, machine (deduction/OCR)
  `PRINTING_TAG_MACHINE_WEIGHT` default 0.5; settings in
  `MPCAutofill/MPCAutofill/settings.py`), resolved per-vote via
  `vote_consensus.resolve_vote_weight(source, anonymous_id, run_id)` rather
  than a bare source-keyed lookup — the one override it applies: the
  28,112 votes cast by the 2026-07-14 deductive-name-backfill **run**
  (`source=deduction`, `anonymous_id="deductive-backfill-v1"`, and
  `run_id=vote_consensus.DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID` — the stamp
  migration `0097_freeze_deductive_backfill_zero_weight_cohort` put on
  exactly those rows) carry weight **0**, permanently, per the 2026-07-23
  owner ruling (see [`theory.md`](../theory.md)'s soundness section and
  [`pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md)'s §3 item 3).
  **Scoped to that cohort, not to the method (owner clarification,
  2026-07-29):** the cohort is zeroed so it can serve as a measurement
  control; name-matching deductive inference is not disqualified, so a vote
  cast by that same calculator in future carries the ordinary
  `PRINTING_TAG_MACHINE_WEIGHT`. Every other `deduction`/`ocr` vote is
  likewise unaffected. `PRINTING_TAG_MIN_VOTES` compares against
  _summed weight_, not row count. A winning group also needs
  `PRINTING_TAG_MIN_SHARE` (default 0.6) of total weight **and** at least
  one non-machine vote — `vote_consensus.is_human_backed_source()` is the one
  place that knows which `VoteSource` values are machine-derived, so no
  volume of machine-only votes can resolve a card alone. The shared core
  (`vote_consensus.resolve_weighted_consensus`, used by printing/artist/tag
  alike) additionally implements two owner-ratified mechanisms from the
  2026-07-22 vote-weight scenario matrix (owner-ratified 2026-07-22, PR
  #325; raw ratification record: [`docs/reference/vote-weight-matrix.md`](../reference/vote-weight-matrix.md)
  — see that function's own docstring for the exact arithmetic):
  - <a id="human-contest-machine-weight-drop"></a>**No machine tipping of
    a human-vs-human contest** (formerly labeled _D1_ in this document):
    if two or more outcome groups each carry SOME human-backed
    weight (a genuine human-vs-human disagreement), every group's
    non-human-backed weight (machine/implicit alike) is dropped entirely
    for both winner-selection and the gate checks — machine/implicit
    weight can pool an already-agreeing human side's total, but can never
    be the deciding weight in an actual human-vs-human contest it isn't
    part of.
  - <a id="machine-dissent-never-de-resolves"></a>**Machine dissent never
    de-resolves an already-quorum-valid human winner** (formerly labeled
    _D4_ in this document): if the [no-machine-tipping
    mechanism](#human-contest-machine-weight-drop) above didn't trigger and
    the winner's own human-backed weight
    alone already clears `PRINTING_TAG_MIN_VOTES`, the share computation
    is recomputed from human-backed weight only across every group — so a
    pile of machine/implicit dissent elsewhere can't drag an
    already-quorum-valid human winner's share below `PRINTING_TAG_MIN_SHARE`
    and silently de-resolve it (the single highest-impact fact the
    matrix's Stage D arithmetic table flagged: at 28k+ deduction-vote
    scale, 3+ machine dissent votes against a 2-user RESOLVED printing
    used to flip it back to UNRESOLVED with no CONTESTED status to signal
    it — this is fixed, not merely documented). Promotion (a lone human
    vote plus agreeing machine weight resolving a previously-UNRESOLVED
    pair) is unaffected by either mechanism — that's Stage D's own purpose
    and neither mechanism's trigger condition is met in that shape.
  - **Tag-path-only**: dissent whose only weight is machine/implicit-
    derived no longer classifies a `CardTagVote` pair's persisted status
    as `contested` (`tag_consensus.py::resolve_and_persist_tag_votes`) —
    `contested` now requires more than one polarity backed by an actual
    human-backed vote. Such a pair still stays in `get_tag_review_queue_pairs`'s
    candidate set (it still needs a human tiebreak), just filed
    `unresolved` rather than `contested` — de-escalated, not removed, so a
    real 23k+-scale deduction-dissent pile doesn't flood the review queue
    with false "genuinely contested" signals. Printing/artist paths are
    unchanged here (no persisted `CONTESTED` status exists for printing;
    artist's own CONTESTED-vs-UNRESOLVED split is a separate, untouched
    raw-outcome-count heuristic).
- <a id="md5-identity-group-pooling"></a>**identity-group pooling (md5 ∪
  phash-d0)** (issue #473 PR-3, owner-ratified 2026-07-25, md5-only;
  widened to union in artbox-phash distance-0 by issue #661/PR #695,
  2026-08-05; soundness statement in
  [`theory.md`](../theory.md)'s §4 item 3): cards sharing a non-null
  `Card.md5_checksum` index the **same image file** and are ONE
  identification target, so printing consensus tallies them together — and,
  since PR #695, so do cards sharing a CURRENT `ImageEvidence.artbox_phash`
  at exact (distance-0) equality, the same sound-entailment tier
  `docs/theory.md`'s two-threshold split already reserves for phash; a card
  with neither is a group of one. `printing_consensus.identity_group_card_ids()`
  expands a card to its combined group (`md5_group_card_ids()` /
  `phash_group_card_ids()` are its two direct components, still separately
  named); `build_group_printing_vote_tuples()` builds the group's tally and
  `vote_consensus.pool_group_votes()` collapses it by **casting
  `anonymous_id`, for every vote — human-backed included**: one agent's
  agreeing votes across members become ONE vote (a person answering the
  same image under two of its identifiers is one answer; a machine
  agent's verdict about identical bytes is one verdict), and an agent
  whose votes across members **disagree** with each other is withheld
  from the tally entirely (it has contradicted itself about identical
  bytes, so it is evidence for neither side — the same
  withhold-never-manufacture rule the `g₄` cross-checks follow). What
  sums is **distinct agents**: two different people voting on two
  different members are two votes, and that is the intended multiplier.
  Both rules were tightened at the 2026-07-25 gate on PR #482 — human
  votes were originally left unkeyed (which let ONE person reach quorum
  by answering two siblings) and self-contradiction originally kept the
  max-weight side (which, at equal weights, let `card_id` order decide
  which outcome an agent appeared to support). The pooled tally then runs
  through the UNCHANGED
  `resolve_weighted_consensus` — same weights, same thresholds, same two
  mechanisms above, same human-backed gate, applied once per group
  instead of once per member. `resolve_and_persist_printing()` writes the
  outcome (`inferred_canonical_card` + `printing_tag_status`) to **every**
  member, in pk order, reindexing only the members whose indexed printing
  actually changed — so members cannot diverge while that shared path is
  the only writer, though a change in group MEMBERSHIP (checksum
  backfill, re-upload) needs a `consensus_recompute` pass for the
  affected group; `consensus_recompute` walks each group once;
  `question_feed` classifies likely-resolve on the group tally and never
  serves a second member of a group a voter has already answered. A card
  with neither a checksum nor a current phash is a **group of one**, for
  which all of
  the above is provably the pre-#473 behavior — which is also every
  card until #473's PR-1
  populates the column (`LOCAL_FILE` and other checksum-less sources stay
  null permanently).

  **The phash-d0 union is narrower in scope than it looks.** It replaces
  md5-alone in exactly the callers named above (`group_printing_votes`/
  `resolve_printing`/`resolve_and_persist_printing`,
  `question_feed.py`'s four answered-set widening helpers,
  `consensus_recompute.py`'s printing loop) and nowhere else. It does not
  touch the human-backed gate itself, and it does not extend to
  illustration or artist consensus — `illustration_consensus.py` and
  `stage_e_dispatch.py`'s own separately-inlined md5 grouping, and Stage
  C+'s own phash-d0 vote-propagation tier
  ([`identification-pipeline.md`'s "Stage C+"
  section](../identification-pipeline.md#stage-c--the-md5-group-behaves-as-one-unit)),
  are deliberately untouched — different consumers, different mechanisms.
  A single union of a card's md5 group and its own phash-d0 group, not an
  iterative transitive closure, is already the full connected component,
  because `artbox_phash` is a deterministic function of the image bytes
  (see `identity_group_card_ids`'s own docstring for the argument).
  Measured against production 2026-08-05: **19,065** phash-d0 groups of
  size >1 covering **40,493** cards; **22,454** cards reachable by a
  phash-d0 sibling their md5 group alone would not reach; **1,492** cards
  with no printing vote of their own that gain access to one through the
  union.

- **Frontend consumer (funnel round, docs/features/grid-selector.md's
  "art-picker FUNNEL" section)**: the two endpoints below are called
  from the `/display` rail's Select Version FUNNEL
  (`SelectVersionResults.tsx`'s `layout="stacked"` branch), not
  `/editor` — the funnel's per-axis chips are the filter-chip surface
  this section describes generically. The frontend request types
  (`CastImplicitVoteRequest`/`RetractImplicitVoteRequest`,
  `frontend/src/common/schema_types.ts`) and
  `APICastImplicitVote`/`APIRetractImplicitVote`
  (`frontend/src/store/api.ts`) were added as part of that round — PR
  #325 (below) shipped the backend contract with the frontend half
  explicitly deferred. **`SerialisedCard.suggestedFilterTagNames` IS now
  the funnel's SUGGESTED-chip data source** (fixed during PR #329
  review, owner-ratified condition 6): an earlier draft of the funnel
  read `card.tagVoteStatuses` instead, which is a source-agnostic
  collapse (CONTESTED and UNRESOLVED both read `"suggested"`, no
  implicit-vote exclusion, no weight floor) — since a SUGGESTED chip
  also drives F4b's implicit-vote cast-on-pick, that let an
  already-implicit-only signal seed MORE implicit votes for itself, the
  self-seeding loop condition 6 forbids. `suggestedFilterTagNames`'s own
  implicit-exclusion and non-implicit-weight floor (below) close that
  loop — see grid-selector.md's own "Compliance fix" note for the full
  before/after. The endpoint payload for the field being `null`/absent
  (the backend serializer wiring that actually POPULATES this field for
  the `/display` rail's card-fetch endpoint is a parallel, not-yet-landed
  PR) degrades to "no suggested chips" on the frontend, never a crash.
- **Implicit votes** (`VoteSource.IMPLICIT`, owner-ratified 2026-07-22
  vote-weight scenario matrix): a passive, low-weight signal cast when a
  person picks a candidate card on the `/display` funnel (see above)
  while one or more filter chips are active — the pick implicitly
  endorses those tags for that card, at `PRINTING_TAG_IMPLICIT_WEIGHT`
  (default 0.25) per vote, well
  below a real `USER` vote. Never human-backed, never privileged, and the
  SUM of implicit weight per (card, tag, polarity) outcome group is hard-
  capped at `PRINTING_TAG_IMPLICIT_CAP` (default 1.0, strictly below
  `PRINTING_TAG_MIN_VOTES`) — a pile of implicit votes can never form
  quorum alone, decide a live human-vs-human contest (the [no-machine-tipping
  mechanism](#human-contest-machine-weight-drop) above), or veto
  an already-quorum-valid human win (the [machine-dissent-never-de-resolves
  mechanism](#machine-dissent-never-de-resolves) above). Lifecycle: one implicit
  vote per (anonymous identity, card, tag) — `views.py::_cast_implicit_vote_and_resolve`
  supersedes (via `update_or_create`) a stale implicit vote from the same
  identity, and refuses (silent no-op) to touch a row that's already a
  REAL vote from that identity — the `(card, tag, anonymous_id)`
  uniqueness constraint (`models.py`'s `cardtagvote_unique_vote`) is
  shared across every source, so an implicit cast may only ever create a
  fresh row or update a row that's already implicit, never silently
  downgrade a deliberate vote. `views.py::_retract_implicit_vote_and_resolve`
  is the deselect path (only ever deletes a row whose `source == IMPLICIT`).
  Write-side guards: refused entirely for `SENSITIVE`-class tags and for
  any (card, tag) pair already `RESOLVED_APPLY`/`RESOLVED_REJECT`/
  `PENDING_APPROVAL`; every implicit vote is stamped `vote_surface= "display-editor-filter"` (`views.IMPLICIT_VOTE_SURFACE`). Rate-limited
  separately from real tag votes via `PRINTING_TAG_IMPLICIT_SUBMISSION_RATE`
  (default 60/h — tighter than `PRINTING_TAG_SUBMISSION_RATE`'s 300/h,
  since browsing candidates under active filters generates implicit votes
  at a much higher natural cadence than deliberate tapping). Endpoints:
  `POST 2/castImplicitVote/` (`{identifier, tagNames, anonymousId}` — one
  call per candidate pick, casting/superseding an implicit vote for every
  named tag; unknown/guarded tag names are silently skipped, never an
  error) and `POST 2/retractImplicitVote/` (`{identifier, tagName, anonymousId}` — the deselect path). `cardpicker.vote_consensus.VoteTuple.is_implicit`
  is the flag the shared resolver core keys its cap and its two
  human-contest-protection mechanisms off of
  — set by `tag_consensus.py`'s wrappers, never inferred from `source`
  inside the resolver itself (same "caller decides" convention
  `is_human_backed` already used).
- **Question-feed candidate-pick auto-tag votes are also `VoteSource.IMPLICIT`**
  (issue #790, fixed after being reopened once a narrower write-side fix
  in #791 didn't reach the common untouched-chip-panel case): `QuestionFeed.tsx`'s `selectCandidate` derives one positive `CardTagVote`
  per attribute the picked candidate's own Scryfall metadata carries true
  (`attributeChips.ts`'s `getAutoTagChips`) and casts it on the voter's
  behalf. The voter's click asserted "this is the printing," not "this
  printing is black-bordered" — the second claim is a machine inference
  read off the CANONICAL PRINTING, not an assertion about the physical
  card, so it must not carry the voter's human-backed weight. Routed
  through `views._cast_auto_derived_tag_vote_and_resolve` (shares its
  guards with `_cast_implicit_vote_and_resolve` via the common
  `_cast_implicit_sourced_vote_and_resolve`), stamped with
  `vote_surface="question-feed-auto-tag"` (`views.AUTO_DERIVED_TAG_VOTE_SURFACE`) — deliberately distinct from `IMPLICIT_VOTE_SURFACE`
  above even though both cast `VoteSource.IMPLICIT`, since the two are
  different mechanisms (a filter-chip pick-under-active-filter signal vs.
  a candidate pick's derived attribute chips) and must stay separable in
  the vote history. `post_submit_tag_vote` decides the source
  server-side from a fixed comparison against this constant — the client
  can only ever downgrade its own vote to `IMPLICIT` by sending this exact
  surface string, never claim a stronger source than `USER`. A voter's
  own direct answer to a tag question (`BorderColorQuestion.tsx`, Level 3
  exclusion-group picks, the "custom-art" no-match reason) is unaffected
  and still casts `VoteSource.USER` under the existing `"question-feed"`
  surface. Historical rows cast before this fix are `VoteSource.USER`
  with `vote_surface="question-feed"`, indistinguishable from a genuine
  tag-question answer — that contamination is not retroactively
  correctable and is a known, unresolved consequence of the defect
  window, not of this fix.
- <a id="suggestedness-excludes-implicit"></a>**Suggested filter tags /
  suggestedness excludes implicit** (owner-ratified 2026-07-22, PR #325;
  formerly labeled decision _D6_ in this document; raw ratification
  record: [`docs/reference/vote-weight-matrix.md`](../reference/vote-weight-matrix.md)):
  `tag_consensus.py::get_tag_net_polarity` (the questionFeed
  confidence-fill scalar) EXCLUDES `VoteSource.IMPLICIT` weight entirely —
  an implicit vote is a passive selection by-product, not independent
  evidence, so it must never color a chip's confidence fill or let a
  person's own earlier pick "explain itself" back to them. Separately,
  `tag_consensus.py::get_suggested_filter_tags_overlay(card_ids)` (batched,
  mirrors `get_resolved_tag_overlay`'s shape) computes which tags qualify
  as a suggested `/editor` filter chip for a card: the APPLY side's
  non-implicit weight is >= 1.0 and not exceeded by the NOT_APPLICABLE
  side's own non-implicit weight, the pair's persisted status isn't
  already `RESOLVED_APPLY`/`RESOLVED_REJECT`/`CONTESTED`/`PENDING_APPROVAL`,
  and the tag isn't `SENSITIVE`. Exposed as `Card.serialise`'s
  `include_suggested_filter_tags` kwarg → `SerialisedCard.suggestedFilterTagNames`
  (`schemas/schemas/Card.json`), same opt-in-per-endpoint,
  zero-cost-when-unused pattern as `suggestedCanonicalCard`/
  `include_suggested_printing` above — defaults `False` everywhere except
  `post_cards` in `views.py` (the endpoint feeding the /display
  grid-selector candidate list, `SelectVersionResults.tsx` via
  `cardDocumentsSlice`), which now enables it and pairs it with
  `models.attach_suggested_filter_tags_overlay(cards)` called once on the
  fully-realized `cards` list BEFORE any `.serialise(...)` call — one
  `get_suggested_filter_tags_overlay()` call (two queries total, see that
  function's own docstring) for the whole response, not one per card. The
  precomputed result is stamped onto each instance via
  `SUGGESTED_FILTER_TAG_NAMES_ATTR` (mirroring `SUGGESTED_PRINTING_VOTES_ATTR`'s
  shape above, though this one isn't `Prefetch`-shaped so it's a plain
  call-then-stamp helper rather than a `Prefetch` object);
  `_suggested_filter_tag_names()` reads that attribute first and only falls
  back to a single bounded per-instance query when it's absent (a one-off
  shell/test lookup, never the code path a bulk endpoint should exercise).
  `post_explore_search` (catalog browse, a different surface) does not
  enable this field yet — a future bulk endpoint doing so should follow the
  same `attach_suggested_filter_tags_overlay()` call, never invoke
  `serialise(include_suggested_filter_tags=True)` per card in a loop.
- **Search consumption**: `printing_consensus.py::get_resolved_printings(identifiers)`
  is the single shared gate (`printing_tag_status == RESOLVED` only) that
  both the search re-rank (`search_functions.py::retrieve_card_identifiers`,
  a stable-sort boost after the existing ES hard filter, never a new query
  path) and the opt-in Full Art/Borderless attribute filters
  (`ResolvedAttributeFilter.tsx`) consult, so they can't drift on what
  counts as "resolved." `Card.get_expansion_code`/`get_collector_number`
  (models.py) fall back to `inferred_canonical_card` when RESOLVED, so
  community-tagged cards (which mostly lack `canonical_card`) are actually
  reachable by the boost/filter, not just ingestion-time-matched ones.
  `Card.printingTagStatus` + `getPrintingMatchLabel` drive the frontend's
  match-indicator icon. **Known gap**: client-side (local-folder/Drive,
  Orama-indexed) search has no ES/DB access and gets no re-rank/filter/
  indicator parity.
- **Reindex on vote transition**: `documents.py::reindex_card_safely(card)`
  is the shared, failure-isolated ES push (never raises — Postgres is
  truth, ES is a projection) that `resolve_and_persist_printing` and
  `tag_consensus.py::resolve_and_persist_tag_votes` call when a card's
  _effective indexed_ printing/tags actually change, so a vote that just
  resolved consensus is searchable immediately rather than waiting for the
  next scheduled `update_database` scan.
- **No-match reason tags**: seven `Tag` rows (`custom-art`, `altered-frame`,
  `upscaled`, `ai-art`, `no-collector-line`, `non-english`, `external-ip`)
  seeded by `manage.py seed_no_match_reason_tags` (a management command,
  **not** a migration — see [[../lessons.md]]'s data-migration-vs-command-seeding
  entry). **These exact strings are a federation interchange contract**
  (other instances consuming our vote export expect them) — renaming any
  of them is a breaking change. Deliberately a separate taxonomy from
  `DEFAULT_TAGS` even where concepts overlap (`upscaled` vs `Upscaled`
  etc.), since one is cast at upload-time from filename parsing and the
  other is a human's queue-time judgment — kept exact-string-distinct so
  the two vote populations don't silently merge. `external-ip` (added
  2026-07-28, WTC artist question re-frame) is the string
  `reason_tags.EXTERNAL_IP_TAG_NAME` — a convergence contract, not just a
  row in the list: the human no-match reason and any machine channel that
  ever derives external-IP-ness must write one `Tag.name`, so
  `tag:external-ip` is a single predicate over the catalog rather than two
  names that permanently fragment it. The constant lived in
  `management/commands/import_external_ip_tags.py` until that command was
  retired on 2026-07-29 (see the retirement record below) and moved to
  `reason_tags.py` so the contract outlives the code that used to honour
  it. Not named after the official "Universes Beyond" Wizards product line:
  that name covers OFFICIAL Magic printings, so a custom proxy bearing
  e.g. Warhammer or Lord of the Rings art isn't one of those — it's
  non-official art drawn from an external IP.
  **Two-axis split (WTC phase B, 2026-07-28)**: the seven tags above
  answer two different questions, not one, and
  `NoMatchReasonStrip.tsx`'s exported `NO_MATCH_REASON_TAG_GROUPS`
  (mirrored in `reason_tags.py`'s docstring so both sides agree without
  either re-deriving it from the other) is the single source of truth
  for the split, presented in the UI as two labelled chip groups instead
  of one flat wall:

  - _not-official-printing_ (`altered-frame`, `upscaled`,
    `no-collector-line`, `non-english`) — the artwork is genuine, the
    physical card is not; the artwork question stays answerable.
  - _not-official-art_ (`custom-art`, `ai-art`, `external-ip`) — the
    artwork itself isn't from any official card; the artwork question is
    unanswerable.

  Exhaustive over the taxonomy (asserted by a frontend test) so a future
  tag added here without a matching entry on either side of
  `NO_MATCH_REASON_TAG_GROUPS` fails loudly instead of silently missing
  from the UI. This split is presentational plus a shared routing
  constant only — it makes no funnel/selection decision itself; the
  illustration funnel (WTC phase C) is the intended consumer of it as a
  routing signal (not-official-printing cards stay in the funnel,
  not-official-art cards drop out).

- **Tag identity vs. presentation**: `Tag.name` is the immutable machine
  key (votes, `Card.tags`, filename-bracket matching, federation);
  `Tag.display_name` (nullable, additive) is freely-editable presentation
  text, admin-editable, looked up frontend-wide via
  `frontend/src/common/tagDisplayNames.ts::useTagDisplayName()`. The
  filename tag-extraction pipeline (`cardpicker/tags.py`) only ever reads
  `name`, never `display_name` — presentation changes can never affect
  ingestion-time matching.
- **Deductive backfill**: `cardpicker/deductive_backfill.py` +
  `manage.py deductive_backfill_printing_tags` casts `source=deduction`
  votes (weight `PRINTING_TAG_MACHINE_WEIGHT`) for cards whose printing is
  logically entailed by data already in the catalog — D1 (name matches
  exactly one `CanonicalCard` row in our catalogue) and D2 (name +
  `Card.expansion_hint` narrows to exactly one row) tiers.
  Idempotent/resumable (the "no existing vote"
  eligibility check doubles as the checkpoint). `VoteSource.DEDUCTION`
  (pure logical inference) and `VoteSource.OCR` (Stage 8, image-inspecting)
  are a label split of what was originally one `VoteSource.AI` value —
  same weight/gate treatment for both, see `models.py`'s `VoteSource`
  docstring. Production run: 28,112 votes written, 0/28,112 later
  resolved a card on their own (human-backed gate verified at scale).

  **The first tier is not cross-verified against Scryfall, and never
  was** (corrected 2026-07-29). This entry used to say D1 was "cross-verified against
  Scryfall's own `printings_count`". No such verification exists. The
  column that claim referred to counts our own `CanonicalCard` rows (see
  the Data model entry above), so the condition it feeds restates the
  name-uniqueness test that immediately precedes it and excludes nothing —
  measured against the live catalogue on 2026-07-29, 137 D1 candidates
  before the condition and 137 after, and all 14,893 uniquely-named
  `CanonicalCard` rows in the catalogue carry a count of exactly 1. The
  condition is left in the code, labelled as entailed rather than deleted,
  so the gap stays visible; **issue #600** tracks what a real external
  check would be. D1's actual claim is the one it can support: the name
  matches exactly one row _in our catalogue_.

- **External-IP tag import (Scryfall Tagger) — RETIRED 2026-07-29,
  together with `PrintingTagVote`.** Owner ruling: _"i am willing to not
  need the printing tag. i am happy to reduce things to the minimum that
  gives us our expected results."_ This entry is the durable record of
  what was removed, why, and what any rebuild must carry — the code is
  gone, so this is the only place the knowledge survives. Full evidence:
  **PR #599**, whose report lands under `docs/reports/` as
  `2026-07-29-printing-vs-illustration-tag-grain.md` when it merges (it was
  still open when this was written, which is why the path is spelled out
  rather than linked).

  **What was removed.** `PrintingTagVote` (model + table, migration
  `0101_delete_printingtagvote`), `POST 2/submitPrintingTagVote/` and its
  URL route, the Django admin registration,
  `manage.py import_external_ip_tags` (579 lines) and its tests, and the
  `PrintingTagVote` arm of `manage.py purge_machine_votes` (including
  `PurgeResult.printing_tag_votes_deleted` — the purge report enumerates
  three vote tables now, not four). The last commit carrying the deleted
  files is `e6c6429a`; read them with
  `git show e6c6429a:MPCAutofill/cardpicker/management/commands/import_external_ip_tags.py`.
  **Not touched, despite the adjacent names**: `CardPrintingTag`
  (167,229 rows, the entire Stage D printing channel) and `CardTagVote`
  (223,999 rows, resolves into `Card.tags`). Nor
  `PRINTING_TAG_MIN_VOTES` / `PRINTING_TAG_IMPLICIT_CAP` /
  `PRINTING_TAG_MACHINE_WEIGHT`, which are the app-wide consensus weights,
  nor `_split_new_printing_tag_votes`, which is a `CardPrintingTag`
  collision guard.

  **Why.** Measured against production on 2026-07-29: **0 rows, 0 of them
  human, 0 ever resolved.** There was **no consensus resolver** — the
  `printing_tag_consensus.py` that two docstrings forward-referenced never
  existed on any branch in the repo's history — **no reader** outside the
  Django admin, and **no frontend caller** of the submit endpoint. The
  importer, its only machine writer, never ran once (`PilotRunLedger` has
  zero rows for it, and it writes its ledger row before branching on
  dry-run, so even a dry run would have left a trace). Underneath all of
  that sits the design principle that makes it unsalvageable rather than
  merely unused: **an imported Scryfall fact is not a disputable claim, so
  it must not be modelled as a vote.** `resolve_weighted_consensus`'s
  `has_human_backed` gate is absolute and independent of the weight sum, so
  a machine-only channel returns `None` at any volume (verified by
  execution at n=1…1000). Automatic Scryfall-derived tagging could never
  have displayed anything through the vote system, at any grain, at any
  threshold. That gate is the invariant this project is built on, working
  correctly; the mistake was routing an indisputable fact through it.

  **What serves the use case instead, today, with no new machinery.**
  `CanonicalPrintingMetadata.promo_types` already carries Scryfall's
  `universesbeyond` token on **10,407 of 113,224 printings**, at 100%
  per-set recall on every dedicated UB set and correct partial behaviour on
  mixed sets (`sld`, `clu`) — it has been ingested all along and nothing
  read it for this. **3,450 catalogue images already resolve to a UB
  printing** through the existing ingestion-time `Card.canonical_card`
  link. For custom/proxy images — which have no Scryfall printing and no
  `illustration_id` at all, so no Scryfall-derived tag can reach them by
  construction — the channel is `CardTagVote` on the `external-ip` `Tag`,
  which already resolves through `tag_consensus` into `Card.tags` and is
  already Elasticsearch-indexed. Both converge on one `Tag.name` by design.

  **The algorithm, for whoever rebuilds it.** The reusable core was ~150
  lines and is worth restating rather than re-derived. Scryfall's Tagger
  publishes an `art_tags` bulk entry (`scryfall_bulk_data.ART_TAGS`, still
  defined and still tested against the live endpoint although nothing
  consumes it today); its `jsonl_download_uri` is ~12 MB gzipped.
  Pass 1 indexes every tag row's `id -> (slug, child_ids)`, finds the tag
  whose slug is `external-ip`, and BFS-closes its `child_ids` **to a
  fixpoint** — not the one level the original plan called for, because the
  hierarchy can deepen; only leaf tags carry taggings, per Scryfall's own
  documentation, and slugs are explicitly not permanent identifiers, so a
  missing slug must fail LOUD rather than import zero rows. Pass 2 re-reads
  the file collecting `taggings[].illustration_id` for tags in the subtree
  (kept separate from pass 1 so the much larger taggings payload is never
  held alongside the tag index). Pass 3 builds
  `illustration_id -> {scryfall card id}` from the already-on-disk
  `default_cards` bulk data — top-level `illustration_id` on single-faced
  rows, one entry per face under `card_faces` for double-faced rows — and
  joins straight onto `CanonicalCard.identifier`. Measured 2026-07-29
  against the live feed: the subtree closes over **2,799 tags / 8,332
  distinct illustrations**, reaching **~13,166** of our printings — about
  **2,759 more than `promo_types`**, because `art:external-ip` marks the
  _artwork's IP origin_ while `promo_types` marks Wizards' _product line_.
  **What that ~2,759 consists of is not established**, and characterising a
  sample of it is the cheapest thing that would decide whether the Tagger
  dependency is worth carrying at all.

  **What a rebuild must NOT carry.** (1) Votes — store it as an imported
  attribute, readable directly, with no threshold and no resolver.
  (2) The negative pass: the removed command voted `NOT_APPLICABLE` on
  every confirmed printing outside the positive set, so a `--write` run
  would have inserted ~13k `APPLY` plus ~100k negative rows into a table
  nothing read. An attribute expresses absence by being absent. (3) The
  vote-system plumbing that went with it — `source=DEDUCTION`,
  `anonymous_id="scryfall-tagger-v1"`, `run_id` stamping,
  `purge_machine_votes` integration — which also correctly drops that
  identity off the calculator roster, since it was never a calculator.
  (4) `security_stamp` as a UB signal: issue #437's own Phase-1 research
  established it is not deterministic (`stamp:triangle` 2,413 vs
  `is:universesbeyond` 4,415; LotR, Avatar, Final Fantasy and Assassin's
  Creed carry oval or null stamps). Grain note: **UB-ness travels with the
  artwork** — of 50,828 distinct stored `illustration_id` values, **0**
  appear on both a UB and a non-UB printing, despite 25,381 being reprinted
  and 20,542 crossing set boundaries — so an illustration-keyed column is
  the right shape, not a printing-keyed one, and not a vote either way.
  Owner direction: fold this into the unified Scryfall importer rather than
  resurrect a standalone command.

- **Moderation layer**: builds on the same consensus system — see
  [[moderation.md]] for the sensitive-tag taxonomy, privileged-approval
  gate, and its own Reports/Drives review surface.
- **Unified question feed**: `GET 2/questionFeed/` replaces the old
  printing/artist/tag/moderation tab switcher with one typed, prioritized
  stream (`confirm_suggestion` → contested pairs → `moderation` → fresh
  unresolved; "dumb ranked union," no cross-tier scoring, with three
  deliberate selection-layer policies on top: the mix-composition policy
  below, the evidence-gated confirmation policy immediately after it, and
  the information-gain question-scoring policy after that).
  Full rationale in `journal/2026-07-14-queue-question-feed-design.md`
  (gitignored, local-only). At current volume tier 1 (`confirm_suggestion`,
  110,130 cards carrying a machine printing vote, measured 2026-08-11)
  dwarfs the contested/cold pools (500-entry cap each) — a voter working
  only this feed used to not reach the other question kinds until tier 1
  was personally exhausted, originally flagged as a known v1 property. A
  weighted rotation (2026-08-10) fixed that for one release; the evidence
  gate below (2026-08-11, issue #766) replaces it, since gating tier 1
  removes almost all of that volume from the confirm lane in the first
  place — see that policy's own entry for the measured effect. Every tier
  excludes `(card, tag)` pairs the requesting `anonymous_id` already voted
  on.
- **Materialised candidate pools** (issue #727, `cardpicker/question_feed_pools.py`):
  the request path never scans the four tiers' own live queries - a
  scheduled warm (per-lane cadence, `settings.QUESTION_FEED_POOL_WARM_MINUTES_*`)
  materialises up to `settings.QUESTION_FEED_POOL_SIZE` (500) candidates per
  lane onto the shared cache, and `get_next_question_feed_item` only ever
  reads from that cache. A cache miss (never warmed, evicted, or the
  `"shared"` backend unavailable) means that lane has no supply for this
  request - it is never a trigger to build the pool live, which would
  reintroduce the unindexed `date_created`-sorted Parallel Seq Scan this
  mechanism exists to move off the request path (2.4-4.7s typical, up to
  47.8s observed on a single-gunicorn deployment). Each draw scores at most
  `question_feed._CANDIDATE_SCORING_WINDOW` (50) candidates, taken from a
  random offset into the pool so different voters spread across a large
  pool's full breadth rather than converging on the cards nearest the
  front - see "Information-gain question scoring" below for what the score
  is. Within that bounded window, printing candidates are tried entirely
  before artist, before tag (the same structural precedence the live tiers
  encode), and a tied score falls back to the pool's own warm-time SQL
  ordering rather than the random draw's rotation, so the `-vote_count`/
  quick-negative/`-date_created` tiebreak chain stays deterministic across
  requests even though which window gets scored is not.
- **Mix-composition policy** (2026-07-24, `cardpicker/question_feed.py`,
  owner-ratified per the WTC vote-queue data brief's OWNER ADDENDUM —
  that brief was a read-only diagnostic session with no committed doc of
  its own, so its raw finding isn't independently citable; the durable
  soundness citation is [`theory.md`](../theory.md) §10 "Streaming and
  continuous operation," which names this exact served-mix/human-vote-
  quality surface and explicitly invites folding in a mix-logging
  mechanism once one lands — this policy, and its `QuestionFeedServedLog`
  below, is that mechanism, noted in place in §10's own text): the feed
  serves ≥`settings.QUESTION_FEED_LIKELY_RESOLVE_MIX_RATIO` (default
  `0.51`) of a session's questions from the **LIKELY-RESOLVE pool** —
  printing questions one more agreeing human vote would actually resolve
  under the real resolver — whenever that pool has supply for the
  requesting voter, falling back to the three-tier ranked union otherwise.
  **Classification** (`question_feed.is_likely_resolve_printing`): finds
  a card's current highest-weighted printing outcome group, adds one
  hypothetical `VoteSource.USER`-weight vote to that group, and re-runs
  the real `vote_consensus.resolve_weighted_consensus` (never a
  reimplementation of its weight/threshold arithmetic) to check whether
  that group now wins — the same exact-code simulation approach the data
  brief used to derive its 46,310-card LIKELY-RESOLVE SUPPLY figure
  (45,154 single-candidate + 1,156 multi-candidate near-threshold cards).
  Compute-per-serve, no caching layer: `_likely_resolve_printing_card`
  pre-filters to cards carrying ≥1 `CardPrintingTag` row (~97k of 218k at
  the brief's snapshot, not the full unresolved population) then scans in
  `date_created` order via `.iterator()` until the first match — the same
  bounded "scan in priority order, stop at first hit" shape tier 1 already
  uses, accepted as a v1 cost like tier 1's own starvation-risk property
  above, not solved with a materialized index. **Remainder ordering**:
  within tier 4, cards whose latest Stage D join-key/fallback
  `CardScanLog.skip_reason` is a "quick-negative" reason
  (`question_feed.QUICK_NEGATIVE_SKIP_REASONS` —
  `unknown-set-code`/`eliminated`/`border-mismatch`/`frame-mismatch`) are
  now prioritized (as a secondary tiebreak, after the pre-existing
  `-vote_count` "closest to resolving" ordering, never ahead of it) over
  the harder/open-ended remainder — `"ambiguous"` is deliberately
  excluded from that set despite being nominally answerable, since the
  brief ranks it as blocked on the `CardScanLog.survivor_pks` gap (see
  that field's own docstring), not free supply today. **Soundness**: this
  is a selection-layer policy only — it makes zero change to
  `vote_consensus.resolve_weighted_consensus`'s weights,
  `PRINTING_TAG_MIN_VOTES`/`MIN_SHARE` thresholds, or the D1/D4
  human-backed-priority mechanisms (see that function's own docstring);
  `is_likely_resolve_printing` only ever calls it, never reimplements it.
  The brief's own SOUNDNESS NOTE flags a presentation-bias risk this
  policy doesn't eliminate on its own: serving a mix skewed hard toward
  machine-agreeing "easy" questions could habituate reflexive
  confirmation, eroding the vote-weight model's independence assumption
  even though no vote's weight ever changes — the same failure _category_
  (a UI's own suggestion signal contaminating what looks like independent
  confirmation) the implicit-vote weight's exclusion from suggestedness
  and IMPLICIT's human-backed exclusion already guard against elsewhere.
  **Mix logging**: every served item (either pool) is recorded in
  `QuestionFeedServedLog` (`anonymous_id`, `pool`, `question_type`,
  `origin_reason`, `served_at`) — the bias-conditioning record the
  SOUNDNESS NOTE calls for, so a future audit can correlate click
  latency/agreement-rate against a session's easy-question exposure;
  `question_feed._served_mix_ratio` reads it back as two cheap indexed
  `COUNT`s, never a per-row scan. Append-only, same convention as
  `CardScanLog` — never read by any consensus computation.
- **Evidence-gated confirmation policy** (2026-08-11, `cardpicker/ question_feed.py`, `_evidence_justifies_confirmation`, issue #766,
  replaces the 2026-08-10 remainder mix rotation described in the git
  history of this section; tightened to read the vote itself by issue #797,
  2026-08-13): [`wtc-question-model.md`](wtc-question-model.md)
  §2/§3 (ratified 2026-08-11) holds there is no lane RATIO to tune for
  confirm/contested/cold — a printing confirmation is either justified by
  the machine's own recorded evidence for that specific card, or it isn't,
  so `QUESTION_FEED_CONFIRM_MIX_WEIGHT`/`_CONTESTED_MIX_WEIGHT`/
  `_COLD_MIX_WEIGHT` (defaults `3`/`2`/`1`, never measured — see that
  ratified doc's §3) are deleted rather than retuned. **Mechanism**: the
  gate sits at `confirm_suggestion`'s one construction site,
  `_confirm_suggestion_item` — a `CardPrintingTag` vote is offered as a
  confirmation only when its own `evidence_types_used` (a field on the vote
  itself, not on `CardScanLog` — see below) covers every type the fallback
  calculator can record (`border`/`artist`/`symbol` — the ratified doc's
  own text names a fourth, "collector line", that the calculator never
  actually produces; see `_KNOWN_EVIDENCE_TYPES`'s own comment and that
  doc's correction note). A card with several machine votes filters to only
  the gate-admitted ones before elimination consensus is applied, so
  different votes on the same card can pass or fail independently. Every
  card with no gate-admitted vote, including one the machine already
  suggested a printing for, is simply not constructible as
  `confirm_suggestion` and falls through to whichever of tier 2 or tier 4
  already claims it, served as `identify_printing` instead — the question
  that presupposes nothing, safe to ask regardless of which element (if
  any) the evidence check failed on. **Issue #797 (2026-08-13):** at
  ratification the gate read `CardScanLog.evidence_types_used` instead,
  scoped to the fallback calculator's own writer id — but a MATCH (the
  fallback calculator's own outcome that produces the `CardPrintingTag`
  vote this gate exists to judge) never writes a `CardScanLog` row at all
  (only a SKIP does), so that reader was structurally unreachable for the
  population it governed: measured 2026-08-11, 0 of 110,130
  confirm-eligible cards cleared the gate. The fix moved
  `evidence_types_used` onto `CardPrintingTag` itself, populated by
  `run_fallback_calculator` on a match exactly as the skip branch already
  populated the sibling `CardScanLog` field, and pointed the gate at that
  column — the skip path's own `CardScanLog` write is unchanged. Historical
  votes (cast before this field existed, and every join-key/deductive-
  backfill vote, which share no evidence vocabulary with the fallback
  calculator) carry `evidence_types_used=null` and fail the gate exactly
  like an empty list does, until a future backfill pass populates them.
  Before the #797 fix, `QuestionFeedServedLog` showed confirm_suggestion at
  507 of 516 remainder-pool serves (98.3%); after the #766 gate landed
  (before #797's correction), that population was absorbed by tier 4's
  non-contested printing pool (222,105 cards) as `identify_printing`
  instead — no starvation, a question-type shift only. The now-gated tier 1
  no longer needs a per-session rebalancing policy, so the remainder
  waterfall (`_REMAINDER_LANE_ORDER`) is a plain, fixed confirm → contested
  → cold order — restored, not reinvented; see this module's own docstring
  for the full mechanism. **Soundness**: SELECTION-LAYER only, same
  boundary the mix-composition and information-gain policies state for
  themselves — it decides whether tier 1 is even constructible for a
  given card, never how any lane's candidate set is built, how a vote
  resolves, or the LIKELY-RESOLVE pool's own precedence above it.
- **Information-gain question scoring** (2026-08-09, issue #716,
  `cardpicker/question_feed.py`, the same file as the mix-composition
  policy above): where each remainder tier used to serve the first
  candidate of a fixed queryset, the tiers now score their candidates by
  expected information gain and serve the highest-scoring one within a
  bounded window. **What is scored**: the entropy of the existing vote
  distribution across the question's own dimension, per kind.
  `_printing_question_score` runs `_shannon_entropy` over the weighted
  printing-outcome distribution across the card's md5 identity group (the
  same pooled tuples `is_likely_resolve_printing` reads; see
  `_printing_vote_tuples`). `_artist_question_score` runs it over the
  weighted artist-outcome distribution (one outcome per distinct
  `CanonicalArtist`, plus the unknown-artist sentinel for an `is_unknown`
  vote). `_tag_question_score(card, tag_name)` runs it over the weighted
  polarity distribution for that `(card, tag)` pair, IMPLICIT votes
  excluded, mirroring `get_tag_net_polarity`'s weighting convention. A
  question whose evidence is evenly split (entropy at its maximum) is the
  highest-value question to serve next; a unanimous or absent distribution
  (entropy 0.0) carries nothing left to learn. **Cold start**: a printing
  question with no votes yet has no distribution to be uncertain about, so
  `_printing_question_score` falls back to `_ATTRIBUTE_VARIANCE_SCALE`
  (0.25) times `_attribute_variance` (the standard deviation of the card's
  machine-derived attribute-chip net-polarity vector,
  `ATTRIBUTE_CHIP_TAG_NAMES`, IMPLICIT excluded, the same per-chip values
  `_tag_confidence` computes for the served item's confidence overlay): a
  card whose own derived picture is internally inconsistent is where a
  human vote resolves the most. Tier 1 (`confirm_suggestion`) re-ranks on
  this attribute-variance dimension alone, since every tier-1 candidate
  carries exactly one machine-sourced suggestion and its printing-vote
  entropy is identically zero. **Bounded window**:
  `_CANDIDATE_SCORING_WINDOW` (50) caps how many candidates a live tier
  scores per serve, per kind: each tier slices its pre-ranked queryset to
  the first 50 and scores only those via `_max_scored_candidate`, and the
  tag lanes collect `(card, tag)` pairs from
  `get_tag_review_queue_pairs()` up to the same bound. The window is a
  candidate horizon, not a loss: the next serve draws a fresh window from
  the same pre-ranked queryset, and the materialised pools (issue #727)
  remain the long-horizon layer this re-rank refines on the pool-miss
  fallback path. **Priority over the static waterfall**: the highest-
  scoring candidate in the window is served first within its tier;
  `_max_scored_candidate` is a STABLE argmax (Python's `max` returns the
  first maximal element), so the tier's pre-ranking, which encodes every
  existing selection rule (`-vote_count` "closest to resolving" in tier 4,
  the quick-negative secondary tiebreak, `-date_created`, kind
  precedence), is the tiebreak whenever two candidates score equally.
  Tier 4's `-vote_count` heuristic survives folded into that tiebreak
  chain rather than standing alone. Tier 1's windowed scan still skips
  candidates that fail to build a suggestion and falls through to the
  unchanged full scan, so it never returns `None` where the old code
  returned a card. **Soundness**: this is a SELECTION-LAYER policy only,
  the direct successor to tier 4's old `-vote_count` heuristic. It
  re-ranks WHICH candidate a tier serves and changes nothing else: every
  request-scoped exclusion set (answered/hidden/`not_official_art` per
  tier, widened to md5 identity groups per issue #473) still applies
  unchanged, the `_served_mix_ratio` mix-composition path above is
  untouched (this policy re-ranks only the remainder tiers, never the
  LIKELY-RESOLVE pool), no tier's candidate set is built differently, and
  `vote_consensus.resolve_weighted_consensus` still weighs and resolves
  every vote exactly as before, the same boundary the mix-composition
  policy states for itself.
- **"Not sure" abstention** (issue #712): Level 1's "Yes"/"No, different
  printing" both cast a real vote (see `selectCandidate`/`rejectSuggestion`
  in `QuestionFeed.tsx`); "Not sure" and "Skip" used to be indistinguishable
  no-ops — neither wrote anything. They are now split: "Not sure" means the
  voter engaged and found the image genuinely ambiguous, real information
  about the CARD, so it POSTs `2/submitQuestionAbstention/` and is recorded
  in `CardQuestionAbstention` (`card`, `anonymous_id`, `question_type`,
  unique together, `get_or_create`-idempotent per repeat tap) before the
  same `setStage("level2")` transition it always did. "Skip" carries no
  signal about the card at all and still writes nothing anywhere — that
  stays a deliberate no-op, not a bug. `CardQuestionAbstention` is the
  HUMAN counterpart to `CardScanLog`'s MACHINE abstention (see that
  model's own docstring for why they're separate tables) and is, like it,
  NOT an `AbstractWeightedVote` subclass — an abstention never enters
  `vote_consensus`. A future exclusion query (issue #713, not built by
  this addition) reads it back as a single indexed equality lookup:
  `CardQuestionAbstention.objects.filter(card_id=..., anonymous_id=..., question_type=...).exists()`.
- **Remaining-work count**: `get_remaining_estimate()` returns
  `QuestionFeedCounts` (`schemas/schemas/QuestionFeedCounts.json`), not a
  single number. `total` is a `.distinct().count()` union across
  printing/artist/tag categories, bounded by catalogue size - the
  non-overlapping "cards needing review in any category" figure.
  `confirmable`/`contested`/`fresh` mirror the feed's own three tiers and
  are independent metrics, **not** a partition of `total` - a card can
  count toward more than one bucket (e.g. machine-suggested-but-unconfirmed
  printing plus a still-fresh artist question). A fresh, untouched card
  defaults to `UNRESOLVED` on both `printing_tag_status` and
  `artist_vote_status` simultaneously, which is why a flat sum of the
  three category counts (the pre-fix implementation) over-counted every
  such card 2-3x. `QuestionFeed.tsx` surfaces all three via a single small,
  muted stats line ("N ready · N in catalog · N contested",
  `question-feed-stats`) tucked at the bottom of the question column - a
  fix round on the quiz-reveal hero (PR #305/#308's owner review) retired
  the old standalone headline/subcounts text that used to sit above the
  question and eat into the vertical space needed to keep the answer
  buttons above the fold.

## Frontend architecture

**SUPERSEDED (WTC rebuild, 2026-07-24,
[`docs/proposals/mockups/wtc-rebuild/SPEC-wtc-rebuild.md`](../proposals/mockups/wtc-rebuild/SPEC-wtc-rebuild.md),
owner rulings on that spec's three open questions — see PR #446)** — `/whatsthat`'s
visual/layout tree was rebuilt from scratch onto the
Tokyo-11 theme's ruled token layer (page-private `--wtc-*` tokens derived from `--accent`/
`--body`/`--conf`, defined in `whatsthat.tsx`'s `WtcTokenScope`), replacing the bespoke gold/
navy/starburst-blue/deep-blue-field identity the many "quiz-reveal hero" (issue #305) bullets
below describe. The old dual-layout mechanism (`HeroGrid`'s 768px `grid-template-areas` swap,
`MobileButtonRow`/`MobileCandidateScroller`/`MobileChipRow`'s horizontal scrollers,
`Level2NarrowGrid`'s narrow-only 2x2 action grid, `WideWordmark`/`NarrowWordmark`'s CSS-display
fork) is retired in favour of ONE `@container`-driven hero (`WtcHero`/`Subject`/`QPanel` in
`QuestionFeed.tsx`) that folds continuously via flex-wrap + `clamp()` + `auto-fill`/`auto-fit`
grids — no viewport breakpoint drives sizing (container-first policy, WTC = first consumer).
Also retired: `BurstSvg`/`HoverBurst`/`useStarburstFrame` (the starburst animation, owner
ruling — the token-derived `--wtc-reveal-glow` field glow replaces it; reveal reads through the
mystery-card flip only), `CardPulseWrapper`/the sliced WHAT'S/THAT/CARD? pop sequence
(`WhatsThatWords.tsx` is now a plain, static, single-tree `<h1>`), the `PageColumn`
`100dvh`-bounded hero + "portrait static top block" hack (the page is an ordinary scrolling
document now). Added: the quiet "N tagged this session" affordance (the only reward surface —
no streak/score/confetti) and the seven question-shapes-as-visually-distinct-modes framing
(confirm/shortlist/quick-negative/open-ended/artist/tag/follow-up) `SPEC-wtc-rebuild.md`
section 2 originally defined (that section is itself now superseded — see below). **Withdrawn
(2026-08-11):** this paragraph used to claim the Level 1/2/3 flow was unchanged by the WTC
rebuild. That is false — issue #728 removed the fixed ladder, and `QuestionFeed.tsx` says so at
its own file header and at more than a dozen inline call sites (e.g. "The de-laddered feed
(issue #728) has no fixed level1 -> level2 -> level3 sequence"). The governing question-type
and composition model, replacing both the Level 1/2/3 ladder and
[`SPEC-wtc-rebuild.md`](../proposals/mockups/wtc-rebuild/SPEC-wtc-rebuild.md) §2, now lives in
[`wtc-question-model.md`](wtc-question-model.md). The rest of the parenthetical
(`getAutoTagChips`, no-re-presentation, the singleton-NO terminal vote, per-item state reset,
the rate-limit banner) is unaffected by that withdrawal and remains accurate — those are
mechanics the ladder's removal did not touch. The detailed "quiz-reveal hero"/starburst/
gold-button narrative below is kept
for history (this doc's own established convention — see the `cardPanel.tsx` bullet's own prior
"SUPERSEDED" marker two bullets down) but no longer describes the current rendering; read it as
"how we got here," not "what's live."

- `frontend/src/pages/whatsthat.tsx` (renamed from `printingQueue.tsx`) +
  `QuestionFeed.tsx` render the single unified feed; the old standalone
  `PrintingTagQueue.tsx`/`GenericVoteQueue.tsx`/`ModerationQueue.tsx` tab
  switcher was deleted, its mechanics extracted into `cardPanel.tsx` and
  reused directly.
- **Per-question local state (`chipStates`/`revealed`/`filterExpanded`/etc)
  resets inside the same `.then()` as `setItem(...)`**, not via a separate
  `useEffect` keyed on `[item?.card.identifier, item?.type]` — that
  dependency array silently skips the reset whenever two consecutive feed
  items share both values (the same card can carry more than one pending
  question, or the same question can be re-served), leaving a chip left
  "positive" from the previous card filtering the new card's candidate
  grid against an unrelated attribute — observed as the grid rendering
  empty until the user happened to touch a chip themselves (the only
  other thing that ever updated `chipStates`). Resetting unconditionally
  alongside `setItem` removes the dependency array (and the class of bug
  it enables) entirely, rather than trying to compute a "definitely always
  changes" key.
- `starburstShape.ts` — seeded PRNG (mulberry32) generates the animated
  starburst background, 5 precomputed frames per layer; skipped under
  `prefers-reduced-motion` (checked once via `matchMedia`).
- `cardPanel.tsx` — **SUPERSEDED (quiz-reveal hero redesign, issue #305,
  see the dedicated bullet below): `CardPanel`/`StaticCardPanel` are now
  both a plain `position: relative; z-index: 0;` at every width** — the
  `position: sticky`-at-`md`-and-up-only mechanism this bullet used to
  describe (via a `useStickyTop` hook, since removed as dead code) is
  gone. The redesign's `HeroGrid` bounds the whole hero to one viewport-
  height row at `md`+ instead, so the card's own grid cell never scrolls
  in the first place and sticky has nothing left to do; below `md`,
  `HeroCardArea` (`QuestionFeed.tsx`) applies its own compact
  `position: sticky` bar directly, not `CardPanel`. The `z-index: 0` (not
  left at `auto`) still matters unchanged from before — it's what gives
  `CardPanel`/`StaticCardPanel` their own local stacking context, so
  `BurstSvg`'s `z-index: -1` stays contained to just this panel instead of
  escaping to the nearest ancestor stacking context and painting behind
  unrelated page content.
- Chip-ring era layout reconciliation: `AttributeChipPanel.tsx`'s
  `ChipRing` (the PR #21-era 3-column ring — chips flanking the card left/
  right, reachable via Level 2's opt-in "Filter by attribute" disclosure)
  had no responsive behavior at all — its flanking columns were always
  `auto`-sized to their own chip content while the card's own column was
  the only flexible one, so at narrow widths the card was squeezed
  narrower to make room for the chip columns rather than the chips
  reflowing. Below `sm` (576px) the ring now collapses to a single
  vertical stack (top chips, then the card at its own full natural width,
  then the two exclusion groups below it as ordinary flowing rows) instead
  of forming a ring at all — the ring visual survives only at widths wide
  enough to contain it without squeezing the card.
- `frontend/src/features/attributeChips/` — tri-state chips
  (untouched → positive → negative), fill color renders weighted net
  polarity (`tag_consensus.get_tag_net_polarity`). Two exclusion groups
  (Border Color, Frame Style) are frontend-only styling/filtering
  concerns — the vote write path treats every chip independently.
  Picking a printing candidate auto-casts one positive vote per
  attribute the candidate itself derives — every standalone boolean,
  plus whichever exclusion-group chip actually matches
  (`getAutoTagChips`; PrintingCandidate carries `borderColor`/`frame`
  directly, so a group value is exactly as derivable as the standalone
  ones). `getOpenExclusionGroups` flags the rarer case where a
  candidate's own value falls outside the taxonomy entirely (e.g.
  `borderColor: "borderless"` isn't Black/White/Silver) — that's what
  gates Level 3 below.
- `frontend/src/common/tagDisplayNames.ts` — shared `name -> displayName`
  lookup, built off the already-cached tags query (no new fetch per
  consumer).
- Candidate buttons carry the card DOM API's data attributes — see
  [[card-dom-api.md]].
- **Confirmation-flow UX pass** (frontend-polish package, PR-A,
  2026-07-17), presentation/interaction only — none of it touches
  `question_feed.py` or tier ordering:
  - A genuine `GET 2/questionFeed/` fetch failure now renders a distinct
    `question-feed-error` state (a "something went wrong" message plus a
    retry button) instead of being folded into the same `caughtUp` state
    as a real empty queue — the old code made a backend outage look
    exactly like "you've finished," so a user could walk away thinking
    there was nothing left to do.
  - The candidate-type layout (`confirm_suggestion`/`identify_printing`)
    put the card being asked about first in DOM order via Bootstrap's
    `order`/`order-md-*` utilities — at `md` and up this was a no-op (same
    candidates-left/card-right arrangement as before), but at mobile
    widths, where the two columns stacked, the mystery card used to render
    _after_ every answer option, so a voter had to scroll past all the
    candidates before seeing what they were even being asked about.
    **SUPERSEDED by the quiz-reveal hero redesign (issue #305, below)**:
    the `order`/`order-md-*` utilities and the two-`Col` layout they
    applied to are gone, replaced by `HeroGrid`'s grid-area map — the
    card-before-questions guarantee on mobile is now a property of the
    grid areas themselves ("words" / "card" / "questions" top-to-bottom),
    not a Bootstrap order utility.
  - Tapping a candidate now shows a small spinner on that specific
    candidate's own art box while the vote submits, instead of uniformly
    dimming every button — previously there was no way to tell, under any
    real latency, whether the button you tapped actually registered.
  - Candidate-type items now show a small badge ("Suggested match" for
    `confirm_suggestion`, "Needs identification" for `identify_printing`)
    above the candidate grid.
- **Mobile funnel redesign** (frontend-polish package, PR-E follow-on),
  again presentation/interaction only — `question_feed.py`/tier ordering
  untouched. Real-device evidence (3 screenshots, `proxyprints.ca/whatsthat`)
  found the old always-on chip ring wedging the ~90px card thumbnail
  between two flanking chip columns and burying it below a full screen of
  chips before the question was even visible; see the held funnel-proposal
  artifact (linked from PR #47's body) for the full findings/mocks this
  implements. `QuestionFeed.tsx`'s candidate branch now runs three stages
  instead of one grid screen:

  - **Level 1** — `confirm_suggestion` items with a `suggestedPrinting`
    land here: the suggested printing alone, YES / NOT SURE / NO / SKIP,
    no grid. YES casts the same vote Level 2's tap does; NOT SURE and NO
    both drop to Level 2 with no vote cast (per the state diagram, they're
    intentionally identical transitions — "an honest skip beats a coerced
    guess"), but NO additionally records the rejected candidate's
    identifier client-side (`rejectedCandidateIds` — never NOT SURE, which
    is genuine uncertainty, not a rejection) so Level 2 retains it as a
    de-emphasised, re-selectable tile — see the no-re-presentation rule
    below. `identify_printing` items (and
    `confirm_suggestion` items without a `suggestedPrinting`) skip Level 1
    entirely.
  - **Level 2** — the candidate grid. The attribute-chip ring is now an
    opt-in, collapsed-by-default "Filter by attribute" disclosure instead
    of always-on chrome — selecting a candidate ignores filter state
    entirely (filters are navigation, never votes). Two classified exits
    sit below the grid: "None of these" (unchanged, still followed by
    `NoMatchReasonStrip`) and "Art matches, not an official printing" (one
    tap: an `isNoMatch` printing vote plus a positive `custom-art` tag
    vote, reusing `reason_tags.py`'s existing seeded tag — no reason strip,
    since the tap already said why). The old gate that disabled "No
    match" until a chip was explicitly set is gone — it existed only to
    force a description before a now-superseded flow, and directly
    conflicted with the filter panel defaulting to collapsed.
  - **Illustration grouping** (issue #503, WTC phase C1): the Level 2 grid
    now clusters candidates that share a Scryfall illustration — printings
    that are visually near-identical, so asking a voter to pick between
    them in a flat grid mostly produced a guess. `PrintingCandidate` gained
    an optional, nullable `illustrationId` (backend:
    `CanonicalCard.serialise_as_printing_candidate`, sourced from
    `CanonicalPrintingMetadata.illustration_id`); `QuestionFeed.tsx` groups
    `visibleCandidates` by that field into `>= 2`-member clusters, each
    rendered as its own labelled `CandidateGrid` inside an
    `IllustrationGroup` wrapper
    (`data-testid="question-feed-illustration-group"`). `illustration_id`
    is nullable and frequently absent (see
    `local_illustration.py`'s `illustration_id__isnull=False` filter) —
    a candidate with no illustration, or a candidate whose illustration has
    no other member, is never dropped: it renders in a flat "ungrouped"
    `CandidateGrid` below the clusters, visually identical to Level 2's
    pre-grouping grid. Ungrouped candidates still call `selectCandidate`
    with that exact `PrintingCandidate` through the unchanged
    `/2/submitPrintingTag/` path. Clustered tiles render the candidate's
    `artCropUrl` (`PrintingCandidate.artCropUrl`, added for this purpose —
    `schema_types.py`/`schema_types.ts`, sourced from
    `CanonicalPrintingMetadata.art_crop_url`) in place of
    `mediumThumbnailUrl`, falling back to the printing scan when a
    candidate's metadata sidecar has no crop — since the vote this cluster
    casts is illustration-level, the border/frame/language a full scan
    shows is information the vote itself doesn't record. Ungrouped tiles
    keep the full scan unconditionally: identifying one specific printing
    (the vote `selectCandidate` casts) does need that detail.
  - **Illustration voting** (issue #503, WTC phase C2; `CardIllustrationVote`
    itself is #524/#531): tapping a tile inside an illustration cluster now
    calls `selectIllustrationGroup` instead of `selectCandidate` — it sends
    ONE `illustrationId` (never a printing list) to the new
    `POST /2/submitIllustrationVote/` endpoint
    (`views.post_submit_illustration_vote`,
    `cardpicker/illustration_vote.py`'s `cast_illustration_vote`). That one
    call performs up to three writes in a single `transaction.atomic()`
    block: `CardIllustrationVote` is always written
    (`update_or_create(card=, anonymous_id=)`, since that model's
    `(card, anonymous_id)` uniqueness is unconditional — see the model's own
    docstring, issue #525); `CardPrintingTag` is written only when the
    illustration resolves, against LIVE data at write time, to exactly one
    candidate printing for this card (`printings_for_card_and_illustration`
    — N>1 casts nothing on the printing channel, matching #526's machine-side
    rule; `question_feed._voter_answered_printing_card_ids` reads
    `CardIllustrationVote` as well as `CardPrintingTag` so an N>1 answer still
    excludes the card from the printing tiers, issue #713); and a
    `CardArtistVote` is derived (`source=USER`,
    `vote_surface="illustration_vote_derived_artist"`) whenever the
    resolved artist's name doesn't indicate a combined credit (tests for
    `' & '` only — see the module's own census comment) and no
    `CardArtistVote` already exists for `(card, anonymous_id)` — an
    existing vote, explicit or previously derived, is left untouched (the
    "never override" precedence rule; see `illustration_vote.py`'s
    docstring for the full TOCTOU/stale-snapshot rationale and its relation
    to issue #483). Because the endpoint never reveals which single
    printing (if any) was resolved, `selectIllustrationGroup` skips the
    auto-tag-chip/Level 3 attribute-exclusion flow and advances straight to
    the next item. Request/response types
    (`SubmitIllustrationVoteRequest`/`Response`) are hand-integrated into
    both `schema_types.py`/`schema_types.ts` from real JSON schema sources
    in `schemas/schemas/endpoints/` — the generator itself was NOT run (see
    issue #332: it destroys the hand-added `CastImplicitVoteRequest`/
    `RetractImplicitVoteRequest` types).
  - **Illustration elimination — "Not this art"** (the negative counterpart
    to illustration voting above; `docs/features/wtc-question-model.md`
    §7.1's `confirm_suggestion` answer of the same name). `CardIllustrationVote`'s
    `(card, anonymous_id)` unique constraint is unconditional — one identity
    holds AT MOST ONE illustration opinion per card (issue #525) — so a
    rejection cannot share that model or that constraint: consuming the
    same slot to reject one artwork would block ever affirming a different
    one, backwards from the intent. `CardIllustrationRejection` is therefore
    a SEPARATE model, keyed on `(card, anonymous_id, illustration_id)` — one
    identity may reject many artworks for one card, and a rejection never
    touches the `CardIllustrationVote` row. The human path
    (`POST /2/submitIllustrationRejection/`, `views.post_submit_illustration_rejection`,
    `illustration_vote.cast_illustration_rejection`) always names a concrete
    `illustrationId` (no `isUnknown` branch — rejecting "unknown" is not a
    meaningful claim) and writes nothing on the printing or artist channels:
    a rejected ARTWORK implies nothing about which PRINTINGS share it, the
    same "narrowing stays a read" posture `printings_for_illustration`
    already enforces for the affirmative side.

    The MACHINE side (`local_illustration.run_illustration_calculator`)
    casts eliminations alongside every `CardIllustrationVote` it writes: one
    resolved positive implies a rejection for every OTHER `illustration_id`
    among `get_ranked_printing_candidates(card, None)` — the same
    name-ranked candidate space `illustration_vote. printings_for_card_and_illustration` already reads for the human 1:1
    check, not the narrower artist+name index the positive itself came from
    (that index holds exactly one surviving illustration by construction
    whenever a vote is cast, so it has nothing left to reject). Measured
    live against production data (300-card sample, cards with a machine
    `CardIllustrationVote`): mean 2.79 distinct illustrations among a
    card's ranked candidates (so ~1.79 eliminations per card among the
    ~50% of cards with any other candidate at all — the other ~50% have a
    unique illustration among their candidates and produce zero
    eliminations), median 2, p90 6, max 35. Eliminations are written with
    `source=VoteSource.DEDUCTION` through the same `resolve_vote_weight`
    machinery every machine vote uses — no separate rejection weight scale
    exists. Retraction (a later run resolving a DIFFERENT illustration)
    goes through the same `purge_stale_machine_votes` family-scoped purge
    every other Stage D write uses: eliminations are recomputed from
    scratch and rewritten only for cards whose positive actually changed
    this run (`_split_new_illustration_votes`'s own scope), so a genuine
    no-op re-run writes zero rows here too.

    **Consumption is a read, never a materialisation** — narrows a candidate
    SET, never elects a winner. `illustration_consensus. eliminated_illustration_ids(card)` judges each `illustration_id`
    independently against only its own rejection rows, reusing
    `vote_consensus.resolve_weighted_consensus` with a single possible
    outcome (so `min_share` is trivially satisfied and the call reduces to
    the ordinary weighted-quorum-plus-human-backed-gate every other vote
    type already applies — no volume of machine eliminations alone can
    eliminate anything). It never touches `resolve_illustration`'s own
    affirmative tally. The one consumer wired in this PR:
    `question_feed._confirm_suggestion_item` skips an AI-suggested printing
    whose artwork has reached elimination consensus and falls through to
    the next machine vote for the card, so a suggestion the group has
    already rejected is not re-served to a different voter as if it were
    new.

  - **No-re-presentation rule** (owner-directed fix, was a real live bug:
    Level 1 "Is it M21 203?" → NO → Level 2 grid containing only M21 203
    again): within a single question item's flow, the suggested candidate
    is asked about exactly once, in its own slot, and is never
    re-presented as a grid tile while that slot is still asking —
    `gridCandidates` keeps it out (`candidate.identifier !== suggestedCandidateId`), so the old asked-twice shape cannot recur.
    A candidate the user has explicitly REJECTED at the suggestion slot
    is the deliberate exception (issue #748): the slot collapses to a
    contextual "Got it — not that one. Is it any official printing at
    all?" plus a "You said: not M21 203" context line, and the rejected
    candidate STAYS in the grid as a de-emphasised, fully re-selectable
    tile — `data-rejected="true"` with a "you said no · tap to
    reconsider" note — the recover path for a mis-tap, where tapping the
    tile casts it as a real pick. `gridCandidates` is therefore every
    candidate with `rejectedCandidateIds.has(id) || id !== suggestedCandidateId`: the rejected set is INCLUDED, not subtracted,
    and the grid still runs through the attribute-chip filter separately
    (a rejection is a `gridCandidates` decision, chip hiding a
    `visibleCandidates` one), so "N hidden by your tags" never conflates
    the two. A rejected candidate never joins an illustration cluster —
    a cluster renders only one representative tile, which would silently
    bury the reconsider path — so it always renders standalone as a
    de-emphasised, ungrouped tile. The "none left" state
    (`suggestionRejectedWithNoneLeft`) is decided by candidate count, not
    grid count — no candidate OTHER than the rejected suggestion, since
    the rejected one is now a grid member: in that state the grid is just
    the single de-emphasised tile, the question was already resolved by
    the terminal vote (next paragraph), and the filter panel and bottom
    action row stay hidden while the reason strip carries the flow.
    `rejectedCandidateIds` is per-item state, reset alongside every other
    per-question field in the same fetch effect (see the module's own
    comment on why that reset can't be a separate dependency-keyed
    effect).

    **Singleton "No" now casts the terminal vote immediately** (owner-
    reported "dedup doesn't work" bug, fixed after this bullet originally
    shipped): the vote-semantics claim this bullet used to make — "Level
    1's NO never casts a vote, only `rejectSuggestion` changes what's
    displayed" — was itself the bug for the singleton case. When rejecting
    the suggestion leaves zero remaining candidates, there is nothing else
    this "No" could mean, so `rejectSuggestion` now calls the same
    `selectCandidate(undefined, true)` "None of these" itself calls,
    casting the `isNoMatch` vote at the moment "No" is tapped rather than
    waiting for a further explicit tap on the classified-exit screen. Before
    this fix, a voter who read "No" as final (or tapped the generic "Skip"
    on that follow-up screen instead of "None of these") never produced a
    `CardPrintingTag` row at all — `question_feed.py`'s tier-1 exclusion
    (`.exclude(printing_tags__anonymous_id=...)`) is and always was correct
    (see `test_tier_1_excludes_cards_this_voter_already_voted_on` /
    `test_tier_1_excludes_a_confirm_suggestion_card_after_a_no_match_vote`
    in `test_question_feed.py`), it simply had no vote to exclude on, so
    the identical `confirm_suggestion` question resurfaced on the voter's
    next feed fetch. The multi-candidate case is unaffected: rejecting one
    of several candidates still only changes what's displayed, same as
    before — the one real negative vote for those items still only happens
    at the eventual "None of these"/custom-art/skip tap. Audited as clean
    for the same re-presentation pattern:
    Level 0 below (NO opens the deckbuilder's general grid-selector
    browse UI, a different paradigm from a guided funnel step — showing
    the current image among many search results there is normal browse
    behavior, not a re-ask) and Level 3 (only ever asks about attribute
    groups `getOpenExclusionGroups` finds genuinely open on the _selected_
    candidate — inherently already excludes anything already answered).

  - **Level 3** — conditional, not a standard stage. Selecting a candidate
    auto-tags everything derivable from it (see above); Level 3 only
    renders when `getOpenExclusionGroups` finds a genuinely open group,
    presenting just that group as a real single-select lock (picking one
    deselects its alternates) — distinct from Level 2's filter panel, which
    keeps the usual independent tri-state cycling. With the current
    taxonomy this is a real but infrequent case (an out-of-taxonomy
    `borderColor`/`frame` value), not a hypothetical one — see
    `printingCandidate2`'s test fixture (`borderColor: "borderless"`).

- **Known schema gap surfaced by the badge above, not fixed here**: tier 2
  (contested) and tier 4 (fresh) — `_tier_2_contested`/`_tier_4_fresh` in
  `question_feed.py` — both call `_identify_printing_item`, producing the
  exact same `type: "identify_printing"` payload shape with no field
  distinguishing one from the other. The frontend badge above can only
  tell confirmable apart from everything else; a true three-way
  confirmable/contested/fresh split would need a new field on
  `QuestionFeedItem` (a schema + `question_feed.py` change), which is
  outside this pass's presentation-only scope.
- **Level 0 — in-context deckbuilder confirmation** (frontend-polish
  package, second funnel PR), a different surface entirely from the
  `/whatsthat` funnel above: `frontend/src/features/card/ DeckbuilderConfirmAffordance.tsx`, mounted from `CardSlot.tsx` right
  after the card image. Shows a small, inert badge under a slot whose
  search query names a specific printing (`expansionCode`/
  `collectorNumber`) that isn't yet the human-resolved consensus for the
  currently selected image — the gate reuses `getPrintingMatchLabel`'s
  own logic, inverted, rather than a new condition. Hover (desktop) or
  tap (touch, since click fires on both) pins the reference printing's
  thumbnail near the badge and enables Y/N, which stay disabled until
  that compare has fired once (misclick protection for what's otherwise
  a one-tap vote). YES casts a real `submitPrintingTag` vote for the
  imported printing; NO opens the slot's existing
  `showGridSelector`/`setShowGridSelector` state (no new plumbing) with
  **no vote cast** — `CardPrintingTag` (`models.py`) has no schema
  concept of "this specific candidate is wrong," only a positive vote
  for one printing or a global `is_no_match=True` ("no known printing
  matches this card at all"), and the latter would misrepresent what NO
  actually means here. Density (v1): no cap on how many slots show the
  badge at once, but each is genuinely inert until touched, and once
  explicitly resolved (YES or NO) never reappears for that specific
  image this session — tracked in a module-level, non-persisted
  `Set<identifier>`, not Redux, since it only needs to survive this
  browser session, not a reload. No banners, no counters, no review
  mode.
- **Item (c) — requested-printing badge on editor slots** (frontend-
  polish package), a sibling of Level 0 above but a distinct concept:
  where Level 0 shows the _resolved canonical_ printing (confirm/deny
  what indexing found), this badge shows the _requested_ printing —
  the expansion code + collector number the slot's own search query
  actually asked for (e.g. `MID 245`), which otherwise gets visually
  "sanitized away" the moment an image is selected, with no at-a-glance
  way to tell which specific printing was requested short of opening
  the change-query modal. Not the resolved `canonicalCard`, and not
  printing-tag consensus status. Originally built inline for Proposal
  H Step 2 PR 2b's `/display` rail header; extracted into its own
  `frontend/src/features/card/RequestedPrintingBadge.tsx` component so
  both surfaces — the `/display` rail header and `CardSlot.tsx`'s own
  editor slots — mount the exact same badge, one place the degraded-
  style logic lives so the two can't drift apart. Gate: the slot's
  query names a specific printing (`searchQuery.expansionCode != null`)
  — always-visible when that's true (no hover gating; the point is
  at-a-glance), nothing when it isn't. Style: normal (`bg-secondary`)
  when resolved cleanly, degraded (`bg-warning`, warning-triangle icon,
  hover tooltip) when the backend's `EditorSearchResponse.degradedQueries`
  flagged this exact query — i.e. the printing-specific search found
  nothing and the backend retried unfiltered, so what's shown is the
  closest available match, not a guaranteed exact hit (see
  `selectIsSearchQueryDegraded` in `searchResultsSlice.ts`). Unlike
  Level 0 (gated on a _selected image_ existing to compare against),
  this badge is independent of whether an image has been selected yet
  — it's about what was asked for, not what's currently shown.
- **Post-export contribution prompt** (issue #166, Proposal H milestone) —
  another entry point INTO this same `/whatsthat` funnel, not a parallel
  one: a small, dismissible `Alert` shown once per session immediately
  after a genuinely successful PDF export (either "Generate PDF" or "Save
  PDF to Google Drive"), linking straight to `/whatsthat` via the exact
  same route `Navbar.tsx`/`HomepagePanel.tsx` already use. Mounted from
  `PDFGenerator.tsx` itself (so the classic "Print!" tab / standalone
  `pages/print.tsx` (issue #275) / `PDFGeneratorModal.tsx` / `ProjectEditor.tsx`
  mounts all get it, since they render the same component) — one
  `usePostExportContributionPrompt`/`PostExportContributionPrompt.tsx`
  pair (`frontend/src/features/export/`), not two copies. This used to
  ALSO be mounted from `DisplayPage.tsx`'s own inline export (Proposal H,
  item 2) — issue #275 retired that pipeline entirely, so PDF generation
  (and this prompt) now lives solely on the Print page, reached from
  `/display`'s Finish footer via a pre-print save gate. "Never repeats
  within a session" (this is the "separate post-export contribution
  toast, task #31" the unified-display-page proposal's own §4.4′ footnote
  references) — a `sessionStorage` flag set the moment the prompt is
  shown, mirroring `chunkErrorRecovery.ts`'s existing session-scoped-flag
  precedent; deliberately not `localStorage`, since this must not survive
  a "clear site data"/incognito test. Does not fire when an export is
  cancelled (e.g. the image-fetch-failure confirm modal's Cancel path) —
  see `postExportContributionPrompt.ts`'s `wasMostRecentCardsPdfDownloadSuccessful`
  for the success-detection logic (the download path reads the
  `fileDownloads` redux slice the download manager already populates,
  since `useDownloadPDF`'s own return value is swallowed to `void`
  elsewhere; the Save-to-Drive path reads `useSaveToDrivePDF`'s resolved
  promise value directly). No backend change, no new API data.
- **Vote provenance (`voteSurface`)**: `AbstractWeightedVote.vote_surface`
  (backend PR #48, nullable additive field, already on
  `SubmitPrintingTagRequest`/`SubmitArtistVoteRequest`/
  `SubmitTagVoteRequest` in `schema_types.ts`) is now sent by every vote
  call in the `/whatsthat` funnel (`"question-feed"`) and by Level 0's
  own vote (`"deckbuilder"`). `ArtistVotePicker.tsx` — shared between the
  funnel and every mount of `AttributeVotingPanel` (the card-detail-modal's,
  `CardDetailedViewBody.tsx`, and — since the rail-delegacy round, PR
  #413, 2026-07-24 — the `/editor` rail's own D14-anchored `IdentifyPanel`,
  which wraps `PrintingTagPicker` + a conditional `AttributeVotingPanel`
  verbatim, opened on demand rather than living in its own grey rail
  accordion; see [`grid-selector.md`](grid-selector.md)'s RD1/RD4 note for
  the sibling change to the funnel chips this same round shipped) — takes
  an optional `voteSurface` prop rather than hardcoding it, same pattern as
  its existing `onRateLimited` prop: the funnel passes
  `"question-feed"`, every `AttributeVotingPanel` mount passes nothing
  (unchanged).
  Every other voting surface (`PrintingTagPicker.tsx`, `TagVotePicker.tsx`,
  `ReportsPanel.tsx`) is untouched — `voteSurface` stays `undefined`
  there, not a guessed value. A fourth value, `"select-version"`, was
  added (issue #167, the unified display page's Select Version section —
  see `docs/features/grid-selector.md`) for the confirm chip a user can
  tap while browsing/filtering that section's candidate grid — see that
  doc's own entry for the exact gating logic.
- **Branding integration** (frontend-polish package). **PARTIALLY
  SUPERSEDED by the quiz-reveal hero redesign (issue #305, below)**: the
  visible page title is no longer the `whatsthat-composite.svg` mark+
  wordmark lockup image — it's `WhatsThatWords`, three cropped `<svg>`
  slices of `whatsthat-wordmark.svg` alone (see the redesign bullet for
  why). `whatsthat-composite.svg` itself is unused now but still checked
  in (not deleted — no cleanup pass has touched it); a real, visually-
  hidden `<h1>What's That Card?</h1>` (`whatsthat.tsx`'s
  `VisuallyHiddenHeading`) replaces it for the page's semantic heading/
  accessible name, the same guarantee the old wrapped-`<h1>` lockup gave.
  Source assets (`question-mark.svg`/mark, `wordmark.svg`/word,
  `composite.svg`/lockup — gradient ids `wtc-grad-mark`/`wtc-grad-word`/
  `wtc-grad-comp` pre-namespaced so more than one could coexist on a page
  without id collision) came from the `assets/whatsthat-branding` branch,
  copied into `frontend/public/` as `whatsthat-{mark,wordmark,composite}.svg`
  (renamed from the generic source names to avoid colliding with this
  repo's existing flat `public/*.svg` namespace — see `flags.tsx`'s
  identical `<img src="/...">` pattern). `whatsthat-mark.svg` is used by
  the PWA icons bullet below; `whatsthat-wordmark.svg` is now inlined
  (not `<img src>`'d) by `WhatsThatWords.tsx` specifically so each of its
  three instances can set its own `viewBox` crop — an externally-loaded
  SVG document's viewBox can't be retargeted from the referencing `<img>`.
- **Mobile funnel pass: thumb-native tap targets** (frontend-polish
  package). Audited via real Playwright screenshots + `boundingBox()`
  measurements at 390px, not assumption: Bootstrap's own default `.btn`
  height (~38px, measured) and the attribute chips' original padding
  (~30px, measured) both fell short of the 44px minimum both Apple's HIG
  and WCAG 2.5.5 (Target Size, AA) call for — the "Filter by attribute"
  toggle was worse still (`variant="link" className="p-0"`, ~26px, since
  `p-0` zeroes Bootstrap's own padding entirely). Fixed via two new
  `QuestionFeed.tsx` styled wrappers around react-bootstrap's `Button` —
  `ThumbButton` (`min-height: 44px`, flex-centered, for every stacked
  full-width action across Level 1/2/3: YES/NOT SURE/NO/SKIP, None of
  these/Art matches/Skip, Confirm & continue/Skip, plus the artist
  question's Skip and the fetch-error retry) and `FilterToggleButton`
  (same floor, `padding: 0.5rem 0` restoring a real hit area without
  looking like a filled button — its own `p-0` had to be removed, not
  just supplemented, since Bootstrap's utility class carries `!important`
  and would otherwise silently win over any styled-component override) —
  and one change to the shared `Chip` styled-button (`min-height`/
  `min-width: 44px`, flex-centered — originally defined in
  `AttributeChipPanel.tsx`, later extracted into `attributeChipRender.tsx`
  alongside the chip-render/vote-submission logic so the display page's
  rail Attributes section could reuse the exact same chip, per the
  left-panel-unification pass — see
  `docs/proposals/proposal-h-unified-display-page.md` (historical doc —
  see its own banner)). Level 3's
  Confirm/Skip pair also gained `flex-column flex-sm-row` (previously
  always side-by-side, squeezed to half-width each on a phone) to match
  the stacking-to-full-width pattern every other level already used.
  Regression coverage: `tests/QuestionFeedResponsive.spec.ts` (formerly
  `QuestionFeedTapTargets.spec.ts`) asserts
  real measured heights (not just that a CSS rule exists) at 390px.
  Chip-ring reflow itself (the single-column stack below `sm` - see
  `AttributeChipPanel.tsx`'s own "MOBILE OVERRIDE" comment) was audited
  and found already correct; not touched.
- **`/whatsthat` PWA installability** (frontend-polish package). A
  manifest + icon set scoped to `/whatsthat` alone — `start_url`/`scope`
  both `"/whatsthat"` in `frontend/public/whatsthat-manifest.json` — not
  a site-wide manifest on `_document.tsx`: the game is the installable
  "app" here, not the whole catalog/editor. Linked from `whatsthat.tsx`'s
  own `next/head` `<Head>` (`<link rel="manifest">`, a `theme-color` meta,
  and an `apple-touch-icon`) — under `output: "export"`'s per-page static
  HTML, that `<Head>` content lands only in `whatsthat.html`'s own
  generated markup, confirmed via `tests/WhatsThatPWA.spec.ts`'s negative
  assertion on a different page. Icons (`whatsthat-icon-192.png`/`-512.png`,
  Chrome's own minimum installability sizes) rasterized from
  `whatsthat-mark.svg` (the branding integration's source asset) centered
  on the page's own background color via a one-off Playwright screenshot
  script - not a new build-time asset pipeline, the PNGs are checked in
  directly like the SVGs themselves. No service worker/offline caching
  added - explicitly out of scope per the owner's brief ("no offline
  scope beyond the default"); Chrome's own install-prompt heuristics may
  want one for the full native "Add to Home Screen" banner in the
  strictest case, a gap noted here rather than silently built around.
  **Retinted (issue #305/W6)**: `theme-color`/`whatsthat-manifest.json`'s
  `background_color`/`theme_color` and both icon PNGs moved from the
  retired `#ff4719` orange to `#123a6b` (`HERO_FIELD_BLUE_DEEP`,
  `whatsthat.tsx`) — the mark itself (the "?" glyph) is unchanged, only
  its background swapped, rasterized the same way as the original pass
  (a one-off, not-committed Playwright screenshot script).
- **Quiz-reveal hero redesign** (issue #305, 2026-07-21, designer round
  `wtc-redesign-spec.md` + `wtc-mockup.html`, owner-approved before
  implementation). Flips the page's axis: the subject card + a large
  blue/white starburst are now the **left hero column**; every question
  surface (L1 confirm, L2 grid, L3 attributes, artist, tags, rate-limit
  banner, moderator switch) renders to the **right** — reversing the
  pre-#305 candidates-left/card-right arrangement (see the two
  "SUPERSEDED" notes above). Every question-render unit itself is
  reused unforked, just repositioned.
  - **Layout**: `QuestionFeed.tsx`'s `HeroGrid` is a single CSS
    `grid-template-areas` map (not nested `Row`/`Col`) with three named
    areas — `card` (spans two rows on the left at `md`+), `words`, and
    `questions` — collapsing to a `words` / `card` / `questions` top-to-
    bottom stack below `md`. One markup tree drives both breakpoints, so
    the card is reachable near the top of a phone screen without a
    separate re-nested layout (the first design pass's own caught-and-
    fixed bug: nesting words+questions in one column with the card as the
    other buried the card _below_ every question on phone).
  - **Sliced words**: `WhatsThatWords.tsx` inlines
    `whatsthat-wordmark.svg`'s path data (not `<img src>`, so each
    instance can set its own `viewBox`) and renders three crops — WHAT'S
    (`-40 150 1030 340`), THAT (`990 150 695 340`), CARD? (`1685 150 905 340`) — measured off the wordmark's own letter-start x-coordinates.
    Each word pops (scale 1 → 1.34 → 1, 480ms
    `cubic-bezier(0.34,1.45,0.64,1)`, `both` fill) staggered 0/240/480ms
    for a continuous left-to-right ripple, re-armed by keying the whole
    words container on the current item's card identifier (a React
    remount, not a class toggle) so every new card replays the sequence
    from WHAT'S. `prefers-reduced-motion: reduce` disables the pop
    entirely (words render statically at rest size/tilt) via the same
    CSS custom-property-driven rest transform the animation itself uses,
    so there's no flash-of-unanimated-content either way. **Real
    pitfall hit and fixed**: a root-level `<svg>` (unlike one nested
    inside another `<svg>`) defaults to `overflow: visible` per spec,
    and a `flex-direction: column` parent's default `align-items: stretch` overrides a replaced element's own intrinsic
    (aspect-ratio-derived) width — either alone silently broke the
    `viewBox` crop, each word rendering the _entire_ wordmark instead of
    its own band. Fixed with an explicit `overflow: hidden` on the `Word`
    styled-component plus `align-items: flex-start` on its flex parent
    (verified via isolated Playwright reproductions before landing, not
    just visual inspection).
  - **Hero card pulse** (owner addendum, not in the original spec): the
    reference card itself pulses in lockstep with the THAT word — same
    easing/duration/240ms delay as `wtcWordPop`, but a separate, much
    smaller-amplitude keyframe (`wtcCardPulse`, scale 1 → 1.1 → 1 vs. the
    word's 1.34 peak — a full-size card "breathing" at the word's peak
    would read as violent, not playful) on `CardPulseWrapper`
    (`cardPanel.tsx`), wrapping whichever card node is active for every
    item type uniformly (not stage-special-cased) and re-armed the same
    way as the words (keyed on the card identifier). Also disabled under
    `prefers-reduced-motion`.
  - **Palette** (W6/W7): the page's old `#ff4719` orange full-bleed field
    — kept as "the page's deliberate identity" by a 2026-07-18 decision
    — is **superseded**: `StarburstBackground` (`whatsthat.tsx`) is now a
    deep-blue field, reconciling with issue #302's sitewide orange retheme
    instead of clashing with it (two similar oranges were _less_
    distinguishable than the old blue-on-orange pairing this page shipped
    with originally). The page-scoped `ACCENT_NAVY` override (buttons/
    links/pills recolored so they'd clear AA against the orange field) is
    removed entirely — off that field and onto the standard dark body,
    the sitewide accent `#df6919` already clears AA (4.61:1) with no
    override needed. The starburst's own two identity colors (outer blue
    `#4d8ddf`, inner white `#ffffff`, `starburstShape.ts`) are unchanged —
    only the field _behind_ it moved. A fix round on the owner's live
    review (PR #305/#308) flattened the original three-stop radial
    (`#1a4f8a` → `#123a6b` → body `#0f2537`, a pronounced vignette that
    "felt unnatural") to a two-stop `#1d4d82` → `#123a6b` gradient with no
    third, darker stop at all — a small highlight around the starburst
    that settles into a flat deep blue well before the edges, instead of
    fading further toward near-black.
  - **Enlarged hero starburst**: `BurstSvg` (`cardPanel.tsx`) gained an
    additive, default-off `$hero` prop (`width: 230%` of the card box vs.
    the existing `55%`, at `md`+) so it dominates the hero's left column
    per the reference aesthetic — deliberately sized past the card's own
    box (bleeding into the hero field or partway behind the words/
    questions columns is on-aesthetic; `CardPanel`'s own `z-index: 0`
    stacking context, see above, keeps it from ever painting over the
    neighbouring columns' actual text).
    - **Fix round (owner live-review, "no starburst visible on mobile
      portrait")**: the mobile value below `md` used to be `90%` — a
      literal CSS width SMALLER than the card's own box (100% of the
      same `CardPanel`), which `aspect-ratio: 1` makes a perfect square
      besides. Centered on a full-width, taller-than-wide portrait card,
      a burst narrower AND shallower than that box is fully eclipsed by
      the (opaque) card art in every direction, by construction — no
      value `<= 100%` can ever be visible here, confirmed live via a
      real Pixel 7 portrait screenshot + `getBoundingClientRect()` diff
      (the burst rendered at `opacity: 1`/`width` ~108px, sitting
      entirely inside the card's own ~120px box). `90%` read as a
      scale-DOWN-from-desktop INTENT ("back off to a modest size on
      phone") rather than a literal container-width instruction that was
      ever checked against actually being bigger than the card — raised
      to `200%` (`230% * ~0.9`, rounded — the same "back off a bit from
      desktop" ratio, just applied to a value that's actually large
      enough to bleed past the card's own edges like every other
      breakpoint here already does). Below `md` the card now sits in its
      own compact grid column beside the questions (see the pinning
      bullet below), not overlaid on top of them, so a bigger bleed
      lands in the row's own gap/blue field rather than on scrolled-
      under text — the exact risk the old `90%` was guarding against no
      longer applies the way it used to.
  - **Reference-card pinning** (owner addendum): the card must stay fully
    visible while the user works through the questions. At `md`+, the
    whole `HeroGrid` is bounded to one viewport-height row and only
    `HeroQuestionsArea` scrolls internally (`overflow-y: auto`, a subtle
    themed scrollbar via `scrollbar-color`/`::-webkit-scrollbar-thumb`,
    not default browser chrome) — the card's own grid cell never scrolls,
    so the old sticky-plus-negative-z-index mechanism (see the superseded
    `cardPanel.tsx` bullet above) has nothing left to do and was removed.
    Below `md`, `HeroCardArea` renders ABOVE `HeroQuestionsArea` in a
    single-column stack (`HeroGrid`'s `grid-template-areas: "words" "card" "questions"`) — see the two SUPERSEDED bullets and the "portrait
    static top block" bullet immediately below them for the two prior
    mobile designs this one replaced, and why. Verified via
    `QuestionFeedResponsive.spec.ts`'s scroll-then-reread-`boundingBox()`
    assertion (full equality, not just visibility) on desktop.
    - **SUPERSEDED mobile design #1 (owner live-review, "the card covers
      the questions on scroll")**: below `md` originally collapsed to a
      SINGLE column (`"words" "card" "questions"` stacked top-to-bottom),
      with `HeroCardArea` becoming a `position: sticky; z-index: 5`
      compact bar (shrunk via `max-width: 7.5rem`) riding on top of
      `HeroQuestionsArea` as the page scrolled — the phone-shaped
      interpretation of "keep the reference comparable" the original
      redesign shipped with. This shared the same horizontal space as
      the questions by construction, so the sticky card was always going
      to end up geometrically nested inside the questions box's own
      bounds once scrolled — confirmed live via a real Pixel 7 portrait
      screenshot + `getBoundingClientRect()` diff (post-scroll, the
      card's box `[146, 50, w120, h236]` sat fully inside the questions
      box's own `[24, -366, w364, h1376]`), not a rare edge case. Replaced
      with SUPERSEDED mobile design #2's disjoint-grid-column layout
      below (owner's own live-review layout proposal) — the card and
      questions structurally cannot overlap regardless of scroll position
      or either one's own height, mirroring the invariant `md`+ already
      had via its bounded one-row hero.
    - **SUPERSEDED mobile design #2 (owner live-review, "wastes space and
      clips question text behind the card")**: replaced design #1 above
      with `HeroCardArea` sitting BESIDE `HeroQuestionsArea` in its own
      compact grid COLUMN (`minmax(0, 7.5rem) minmax(0, 1fr)`) instead of
      stacking, with Level 1's full-width buttons/Level 2's candidate
      grid/Level 3's exclusion chips each rendering in a single
      horizontally-scrollable row beside the card (`MobileButtonRow`/
      `MobileCandidateScroller`/`MobileChipRow`, `QuestionFeed.tsx`) —
      genuinely fixed the overlap bug design #1 had (card/questions
      structurally can't share the same space in a column split), but a
      FOLLOW-UP owner review of that fix found the ~7.5rem card column
      left most of a phone screen's width empty below the tiny card, and
      squeezing the question prompt/badge into the narrow remaining
      column let it clip behind the card at some viewport widths. See
      "portrait static top block" immediately below for the design that
      replaced this one. `MobileButtonRow`/`MobileCandidateScroller`/
      `MobileChipRow` themselves survive into the current design
      (unchanged mechanism, just no longer sitting beside the card) —
      only `HeroCardArea`'s own beside-vs-above relationship to the
      questions column changed.
    - **Portrait static top block (owner live-review, current design)**:
      below `md`, the reference card is height-capped (`CardPanel`/
      `StaticCardPanel` in `cardPanel.tsx`, `max-width: min(100%, calc(32vh * 63 / 88))` — a max-WIDTH expressed in terms of a target
      HEIGHT, so the existing width-driven `<img>` sizing — `width: 100%; aspect-ratio: 63 / 88` — doesn't need to change at all) and renders
      as a STATIC (non-scrolling) block together with its name, the
      "Suggested match"/"Needs identification" badge, the question prompt,
      and a compact 2×2 grid of the Level 2 action buttons (Filter by
      attribute / None of these / Art matches / Skip) — all reachable
      with zero scrolling, one tap. Only the candidate grid below that
      block scrolls (horizontally, `MobileCandidateScroller`, unchanged
      mechanism from design #2). Implementation (`QuestionFeed.tsx`):
      - `Level2NarrowGrid` — Level 2's OWN narrow-width restructuring,
        `display: grid` with named areas (`text` / `filter`+`none-of-these`
        / `art-matches`+`skip` / `reason` / `options`) entirely inside
        `@media (max-width: 767.98px)` with no unguarded base rule, so at
        `>= md` it's a plain unstyled `<div>` and desktop's existing
        block-flow layout (DOM order still exactly as before) is
        byte-for-byte unaffected. `grid-area` (not flex `order`) is the
        mechanism specifically because the filter-toggle button and the
        three exit buttons are non-adjacent DOM siblings kept in their
        EXISTING desktop position/order (`order` only reorders within a
        shared flex axis, not across independently-wrapped siblings a
        grid-area can place anywhere regardless of DOM position). A real
        2×2 grid for the four action buttons — NOT a first-pass "filter
        alone in a left column, all three exits stacked in a right
        column" split, which a live Playwright measurement (Pixel 7, this
        task's own report) found forced the row's height to whichever
        column was TALLEST (~166px for three stacked buttons), leaving
        the candidate row only 69–105px of its own ~176px natural height
        even after every other budget trim below — a proper 2×2 grid caps
        each row at the taller of just ITS OWN two buttons instead
        (~44px/~62px), roughly half the height for the same four buttons.
        Level1/Level3/artist/tag question types are NOT restructured this
        way (deliberately, per the same owner review) — none of them has
        a genuinely scrollable grid the way Level 2 does, so they simply
        render below the (now non-sticky, stacked) card via the existing
        `HeroQuestionsArea`, unchanged beyond inheriting the shared
        `HeroGrid`/`HeroCardArea` fixes (no more sticky, card stacks
        above).
      - Narrow-only Bootstrap-margin cancellation: the four action-button
        wrappers' own `mb-2`/`mt-2`/`mt-3` classNames (needed at `>= md`,
        where they carry no CSS of their own and margin is the only
        thing spacing one button from the next) DOUBLE `Level2NarrowGrid`'s
        own `gap: 0.5rem` at narrow — `margin: 0 !important` on each
        wrapper (Bootstrap's own spacing utilities are `!important`, so
        an unmarked override can't win) cancels that redundant spacing
        specifically below `md`.
      - `NarrowOptionsArea`/`MobileCandidateScroller` — a hard vertical
        clip boundary (`overflow-y: hidden`, default `align-items: stretch`
        rather than the first pass's `center`) matching what
        `overflow-x: auto` already is horizontally, so a tile row that
        comes out even a few px taller than its own allotted grid row is
        clipped rather than bleeding out top-and-bottom (`align-items: center`'s own behavior) and reintroducing scroll via
        `HeroQuestionsArea`'s defensive `overflow-y: auto` fallback (own
        bullet below).
      - Candidate tile width trimmed `6.5rem` → `5.5rem` below `md`
        specifically (proportionally shorter too, via `ArtPlaceholder`'s
        own aspect-ratio) — still comfortably above the 44px WCAG 2.5.5/
        Apple HIG floor for the tap target itself (the whole button, not
        just the art).
      - The "N ready / N in catalog / N contested" stats line
        (`question-feed-stats`) is hidden below `md` (`StatsLine`) — a
        nice-to-have info line, not part of the answer funnel, and real
        measurement found it was the last few px keeping the
        `overflow-y: auto` fallback engaged even after every other trim
        above. Unchanged at `>= md`.
      - **Wordmark**: below `md`, the sliced/stacked WHAT'S/THAT/CARD?
        teaser (`WhatsThatWords.tsx`) alone burned ~15% of the viewport as
        a three-line column — replaced with `whatsthat-composite.svg`
        (the mark+wordmark lockup — the ORIGINAL one-line horizontal
        wordmark this page shipped with before issue #305's sliced/
        stacked treatment, sourced from PR #114's "branding integration"
        and still on disk, just unused since #305). `NarrowWordmark`/
        `WideWordmark` (`QuestionFeed.tsx`) toggle via plain CSS
        `display` (both always mounted — no conditional render, no
        hydration-mismatch risk, and `WhatsThatWords`' own pop/pulse
        timing is gated on `imageLoaded`/`$playing` regardless of whether
        its container is visible). Unchanged at `>= md` (still the
        sliced, per-card-animated version). Regression coverage:
        `WhatsThatWordsAnimation.spec.ts`'s "narrow-width wordmark swap"
        describe block asserts visibility (not just DOM presence) of
        each version at its own breakpoint.
      - **Starburst readability**: the hero's own `$hero`-enlarged
        `BurstSvg` (200% below `md`) now bleeds into exactly the space the
        card's name/badge/question text occupy (they moved from beside
        the card to directly under it). Rather than shrinking the burst
        back down (the owner's own earlier, separate ask keeps it visible
        at 200% bleed on mobile — see that fix round's own bullet above),
        a bottom-fade `mask-image`/`-webkit-mask-image` linear gradient
        (opaque 0–55%, fading to transparent by 88%, `$hero`-only) keeps
        the top/sides fully visible (nothing competes with those) while
        fading the lower spikes so they don't fight the text below for
        contrast.
      - **No `position: sticky` anywhere** (this codebase's own sticky/
        overflow lesson, [[../lessons.md]], plus the task's own explicit
        ask) — `HeroCardArea` is plain, unstyled beyond flex-centering at
        every width now; nothing needs pinning since PageColumn/
        StarburstBackground (`whatsthat.tsx`, next bullet) bound the WHOLE
        hero to the viewport at every width, the same invariant `>= md`
        has always had.
      - **PageColumn/StarburstBackground now bound height below `md` too**
        (`whatsthat.tsx`) — previously `>= md`-only (below `md` the whole
        page scrolled normally, matching design #2's sticky-adjacent
        mobile intent); the static-top-block/scrollable-candidate-row
        split needs the same bounded-viewport chain FeedRoot/HeroGrid
        already had `>= md` at every width. `StarburstBackground` also
        gained a below-`md`-only `min-height: 100%` — `Footer.tsx`'s own
        responsive layout stacks its columns vertically below `md`,
        running much taller there than at `>= md` (confirmed empirically:
        without this, a real Playwright run crushed the WHOLE hero to
        ~4px tall, `Footer` claiming its full natural height instead,
        since `Footer` has no `min-height: 0` of its own to let it shrink
        the way `StarburstBackground`'s own `min-height: 0` lets IT
        shrink — flexbox drew the entire deficit from the box that could
        actually give). `min-height: 100%` restores the correct priority:
        the hero claims PageColumn's full height first, and `Footer`,
        if it doesn't fit, is pushed below PageColumn's own bottom edge —
        still fully reachable, just via the page's own ordinary scroll
        (`Layout.tsx`'s `ContentContainer`), the same way any long page's
        footer normally is. Unchanged at `>= md` (Footer is compact there,
        genuinely shares the fixed budget with the hero, fully visible
        with no scroll needed, as before).
      - Regression coverage: `QuestionFeedResponsive.spec.ts`'s "portrait
        static top block" describe block (real, genuinely-loaded CDN
        image via route interception — the empty-`mediumThumbnailUrl`
        fixture convention every other test in that file uses renders at
        a small intrinsic fallback size regardless of CSS, which would
        never exercise the height-cap math at all) asserts, at Pixel 7's
        own 412×839 CSS viewport: zero page-level scroll AND zero
        `HeroQuestionsArea`-internal scroll; the static action row renders
        fully above the candidate row's own top edge; the question badge/
        prompt render entirely below the card's own bottom edge (never
        occluded by it or its starburst).
    - **Owner review round 2 (live device follow-up on the block above)**:
      three asks — a "?" motif on every blue "unrevealed" card, fading
      with the blue as it reveals; dropping the narrow-width standalone
      "?" if one exists distinct from the wordmark's own glyph; and a
      golden treatment for every quiz action button, since Bootstrap's
      per-variant colours (grey/red/green/blue) were designed against the
      site's neutral background, not this page's own deep-blue field.
      - **"?" motif**: already implemented going into this round —
        `RevealOverlay` (`cardPanel.tsx`) has always rendered `?` as its
        own child text, so the blue field and the "?" fade together via
        the SAME parent `opacity` animation (`revealAnimation`); the
        candidate grid's `ArtPlaceholder` "mystery card" tiles carry the
        same glyph via a CSS `::before { content: "?" }`, at every
        viewport. Confirmed via real (non-empty-src) Playwright
        measurements at both Pixel 7 (412×839) and desktop (1280×900) —
        an earlier apparent desktop "collapse" (the reveal overlay
        rendering as a thin, mostly-clipped sliver) turned out to be an
        artifact of a manually-started dev server missing the
        `NEXT_PUBLIC_IMAGE_WORKER_URL` env var used by Playwright's own
        `webServer` config, not a real product bug — reproducing it
        against a correctly-configured server showed a full-height,
        fully-legible "?" at both viewports. New regression coverage
        (`QuestionFeedResponsive.spec.ts`'s "question-mark motif + golden
        action buttons" describe block): the overlay's own text content is
        asserted at both viewports, and `ArtPlaceholder`'s pseudo-element
        `content` is asserted directly (Playwright's own mechanism for a
        CSS-generated-content assertion, since it isn't real DOM text);
        `QuestionFeed.test.tsx`'s shared `revealCard()` jest helper also
        asserts the overlay's text content before dispatching the
        animation-end event every existing jest test already relies on.
      - **Standalone "?" (mobile)**: NOT removed. The narrow-width
        wordmark (`whatsthat-composite.svg`, see the "portrait static top
        block" bullet above) bakes its own "?" mascot glyph directly into
        the same flattened image as the "WHAT'S THAT CARD?" text (its own
        path data is a scaled/repositioned copy of `whatsthat-mark.svg`'s
        "?"-only mark, confirmed by inspecting both SVGs directly) — there
        is no separate, distinct "?" DOM element at narrow widths to drop
        without altering the wordmark image itself. This is the exact
        ambiguity the task's own fallback anticipated, so it's left
        untouched here and reported instead (see this PR's own body).
      - **Golden action buttons**: `ThumbButton` (Level 1's Yes/Not sure/
        No/Skip, Level 2's None of these/Art matches/Skip, Level 3's
        Confirm & continue/Skip), `FilterToggleButton` ("Filter by
        attribute"), and `ThumbChip` (Level 3's attribute picker) — all
        three styled components local to `QuestionFeed.tsx` — now share
        one gold treatment (`#f8d42b`, `whatsthat-mark.svg`'s own top
        gradient stop; `#124063`, that same SVG's dark-navy stroke)
        instead of each Bootstrap variant's own semantic colour
        (success/outline-danger/outline-secondary/link/primary). Measured
        contrast (WCAG's standard relative-luminance formula): the
        pre-existing default grey `outline-secondary` text/border against
        the field's deep-blue stop (`#123a6b`) was ~2.4:1, under AA's
        4.5:1 text floor (and its 3:1 UI-component floor) — the "hard to
        read" the owner reported live; gold text against that same stop is
        7.84:1, against the field's lighter highlight stop (`#1d4d82`) is
        5.93:1, and dark-navy text on filled gold is 7.45:1 — all past AA,
        most past AAA. Bordered/filled variants (`ThumbButton`'s non-
        `.btn-link` cases) get gold outline/text at rest, filling solid
        gold with dark-navy text on hover/focus/press; `.btn-link` (the
        Skip buttons, `FilterToggleButton`) gets a colour-only swap (no
        border/fill added, preserving the existing plain-text-link look);
        `ThumbChip` reuses its own existing selected/unselected variant
        split (`primary`/`outline-secondary`) to make a selected chip
        PERSISTENTLY filled gold rather than only on hover. `&&` (Emotion's
        specificity-doubling trick) on every override, so it reliably wins
        over Bootstrap's own single-class variant rules regardless of CSS
        injection order. Page-scoped: only these three styled components
        are touched; `ChipCard.tsx` (the no-match-reason chips, shared with
        `ReportCardPanel.tsx` on a different page) is deliberately left
        alone, and the sitewide orange theme is untouched. New regression
        coverage (same describe block as above): computed `color` on the
        filter toggle and "None of these"; computed `color`/
        `background-color` on a selected vs. unselected Level 3 chip.
    - **Owner review round 3 (ruling on round 2's open items)**: three
      further asks — remove the narrow-width standalone "?" mascot;
      slow the wordmark's 3-stage pop animation down "a bit"; and build
      ONE shared blue-card-with-"?" composition used in every blue-card
      slot on the page, replacing round 2's two independent
      implementations.
      - **Narrow-width "?" removal**: `whatsthat-composite.svg` (the
        narrow wordmark asset, own bullet above) bakes its "?" mascot
        into the same flattened image as the "WHAT'S THAT CARD?" text —
        confirmed by inspecting both that file and `whatsthat-mark.svg`
        (the standalone mascot) directly, their path data for the "?" is
        an identical shape, just scaled/repositioned. `whatsthat- wordmark.svg` — the SAME text with no separate mascot at all,
        already on disk (`WhatsThatWords.tsx` already slices this exact
        file into its three animated words) — is exactly the pre-
        cropped, text-only asset the owner asked to check for, so
        `NarrowWordmark`'s `<img src>` was simply swapped to it; no new
        art or manual SVG surgery was needed. `WideWordmark`
        (`WhatsThatWords`) was never affected either way — it has always
        rendered from this same `whatsthat-wordmark.svg` source, never
        the composite. Regression coverage:
        `WhatsThatWordsAnimation.spec.ts`'s existing narrow/wide
        visibility test now also asserts the narrow `<img>`'s own `src`.
      - **Pop animation slowdown**: `WhatsThatWords.tsx`'s `Word`
        component (duration 480ms → 640ms) and its `WORDS` array's own
        delay stagger (0/240/480ms → 0/320/640ms) both scaled by the same
        4/3 (33.3%) factor — within the owner's own "25-40% longer per
        stage" target, and a clean fraction that preserves the EXISTING
        duration:stagger ratio exactly (240ms was already precisely half
        of 480ms; 320ms is precisely half of 640ms) — "keep the stage
        ordering/feel identical" means the ripple's own overlap shape has
        to scale in lockstep with the duration, not just the duration
        alone. `CardPulseWrapper` (`cardPanel.tsx`) moves in lockstep by
        the same factor (640ms/320ms delay) since it must stay frame-for-
        frame synced to THAT's own timing (its own long-standing
        comment). The hero reveal fade itself (0.8s) is untouched — out
        of scope, the owner's ask was specifically the wordmark's pop-in.
        Regression coverage: `WhatsThatWordsAnimation.spec.ts`'s computed-
        style assertions updated to the new duration/delay values (see
        [[../lessons.md]]'s cyclic-animation-sampling entry — these
        assert declarative CSS animation properties directly, not a
        single sampled frame, so they're not subject to that lesson's own
        failure mode, but the same "don't trust one point-in-time read"
        discipline applies to any human eyeballing the new timing live).
      - **One shared blue mystery card**: `RevealOverlay` (the hero
        reveal cover, plain `?` text) and `ArtPlaceholder`'s own CSS
        `::before { content: "?" }` (the candidate-grid/no-match
        placeholders) — round 2's own two independent implementations of
        the same idea, sharing only their `STARBURST_OUTER_COLOR`
        constant — are now ONE component, `MysteryCard`/`MysteryCardFace`
        (`cardPanel.tsx`). The owner read the large hero card and the
        small candidate cards as visibly different shades of blue;
        measured via computed `background-color` on both, they were
        already byte-identical (`rgb(77, 141, 223)`) — the perceived
        difference was a context/contrast effect from the hero's own
        starburst bleed behind the large card, not a real colour
        mismatch. Consolidating onto one shared component makes any
        future drift between the two structurally impossible regardless
        of whether today's colours already matched, which is the actual
        "so future changes are one place" ask. The "?" itself is now
        `whatsthat-mark.svg`'s own gold-gradient mascot (not plain text),
        sized via `height: 66.6667%` on the glyph `<img>` (2/3 of
        `MysteryCardFace`'s own height — a `position: absolute; inset: 0`
        box over a definite-height containing block IS itself a definite
        height, so a percentage-height child resolves normally) rather
        than a fixed rem value, so the same component reads correctly at
        both the large hero card and the much smaller candidate tiles.
        `$playing`/`onAnimationEnd` are optional on `MysteryCard` — only
        the hero reveal slot passes them (fading away in lockstep with
        the blue, exactly as `RevealOverlay` did); every candidate-grid/
        no-match slot omits them and gets the SAME component, just
        permanently static (falls back to `animation-play-state: paused`
        forever) — the exact behaviour `ArtPlaceholder`'s old `::before`
        had, just as a real element instead of generated content.
        Existing regression tests rewritten against the new structure:
        the reveal-overlay "?" assertions (jest's `revealCard()` helper,
        Playwright's "question-mark motif" describe block) now check the
        glyph `<img>`'s own `src` instead of text content/pseudo-element
        `content`; two pre-existing Playwright tests that queried a
        candidate tile's own `<img>` generically (Level 1's reference-
        image test, the hover-zoom edge-clipping test) had to be narrowed
        (`getByRole("img")`/`img:not([alt=""])`) since `MysteryCard`'s own
        `alt=""` glyph is now a SECOND `<img>` in the same container,
        ahead of the real thumbnail in DOM order — a bare `.locator("img" ).first()` silently resolved to the non-interactive glyph instead
        after this change, which would have quietly broken those tests'
        own intent (measuring the wrong element) without failing outright.
        New regression coverage: the glyph's own height-to-card-height
        ratio (both the hero card and a candidate tile, asserting it's
        relative sizing rather than a fixed value that happens to work
        for both); every blue card on the page rendering the identical
        `whatsthat-mark.svg` glyph asset.
    - **Fix round (PR #305/#308 owner review)**: the original
      `HeroGrid { max-height: calc(100dvh - NavbarHeight - 2rem) }`
      passed CI but let the whole page scroll live — the flat `2rem`
      guess never accounted for `StarburstBackground`'s real
      padding/margin (4.5rem, not 2rem) or `Footer`'s entire height below
      it, so total page content routinely exceeded
      `Layout.tsx`'s `ContentContainer` and forced its own outer
      scrollbar to activate, moving the "pinned" card along with
      everything else. Replaced with pure flex sizing instead of a
      hand-maintained calc: `whatsthat.tsx`'s `PageColumn` (flex column,
      height locked to `calc(100dvh - navbarHeight)` at `md`+ via the new
      `useNavbarHeight()` hook — see below) wraps `StarburstBackground` +
      `Footer`, `StarburstBackground` takes `flex: 1 1 auto; min-height: 0` (whatever's left after `Footer`'s natural size), and
      that flex chain propagates down through `StarburstContent` →
      `QuestionFeed.tsx`'s own `FeedRoot` → `HeroGrid` (now
      `flex: 1; min-height: 0` instead of its old `max-height` calc) — it
      structurally can't drift out of sync with `Footer`'s real height
      again. Deliberately NOT extended through the moderator
      `Tab.Container`/`Tab.Content`/`Tab.Pane` switcher (a small,
      privileged audience) — that branch keeps its previous natural/auto
      height, unchanged, rather than wiring three more react-bootstrap
      wrappers into the flex chain. `useNavbarHeight()`
      (`frontend/src/common/useNavbarHeight.ts`) replaces the hardcoded
      `NavbarHeight` constant (issue #250 — confirmed 64-88px real vs the
      constant's 50px in some auth/nav-link states, see
      `docs/troubleshooting.md`) with a `ResizeObserver`-measured value,
      for `Layout.tsx`'s `ContentContainer` (sitewide — this is what was
      hiding the first several px of top-of-page content, including this
      page's hero title and `/display`'s own toolbar, behind the real
      navbar in a taller-navbar state) and this page's `PageColumn`.
      Scoped, not a blanket swap — every other `NavbarHeight` consumer
      (`Explore.tsx`, `ProjectEditor.tsx`, `FinishedMyProject.tsx`) is
      unchanged, and #250 stays open for that broader decision (the hook
      also doesn't yet handle the navbar's own crowded-state wrapping to
      a second, taller row — only the single-row height mismatch).
      Strengthened `QuestionFeedResponsive.spec.ts`'s own pinning
      assertion with a real `page.mouse.wheel()` scroll (not just
      `el.scrollTop` on the inner questions box) plus a
      `content-container` testid check — that gap (never exercising the
      outer container) is exactly what let the original bug pass CI.
  - **Hover-zoom/hover-burst edge clipping** (fix round, PR #305/#308
    owner review): `ZoomableThumbnail`'s hover-zoom and `HoverBurst`'s
    glow (`cardPanel.tsx`) were both deliberately built with no
    `overflow: hidden` of their own so the enlarged art/glow could pop out
    uncropped — the pinning fix above's `overflow-y: auto` on
    `HeroQuestionsArea` forces `overflow-x: auto` too (CSS's own "visible
    computes to auto once the other axis isn't visible" rule), silently
    re-clipping both right at that box's left/right edges, worst on the
    left where the first column in every row sits flush against it with
    no buffer. Two-part fix: `HeroQuestionsArea` itself gets `margin: 0 -2.5rem` + matching `padding` (bleeds its own clip boundary 2.5rem
    into the real empty space already there — the grid's own column gap
    on the left, the page's outer margin on the right — with zero visible
    resting-layout shift, verified via `boundingBox()` diff); `HoverBurst`
    gained an additive `$edge` prop that shrinks its 331.2% bloom to 150%
    for the first/last column specifically (`index % 4 === 0 || index % 4 === 3`, the two columns still short on room even with the added
    bleed) — interior columns keep the full-size, unmodified glow.
    Regression coverage: `QuestionFeedResponsive.spec.ts`'s new
    horizontal-only containment check (vertical clipping at the top/
    bottom of this box is its intended scroll behaviour; only left/right
    clipping is the bug).
  - **One hero card slot per item type, not per stage**: Level 3 dropped
    its old inline 48px thumbnail+name row (the shared hero card already
    shows the same art, one persistent slot across every stage per the
    mockup's own stage-switcher demo); artist/tag items' plain reference
    `<img>` (no burst/reveal — "reposition, don't redesign") just moved
    into the same shared `card` grid area instead of its own `Col`.
  - **Fix round (owner live blocker, post-#310): word-stack sizing +
    animation choreography sync**. Two independent owner-reported bugs
    found on the live site after #310 landed:
    - **Question box too small for its content**: the word stack
      (`Word` in `WhatsThatWords.tsx`) rendered at a fixed `3.75rem`/
      `4.5rem` per word (~220px total for all three, measured) — about
      1.4x `wtc-mockup.html`'s own approved proportion (164px, measured
      directly off that file with its demo-only scale transform
      removed) — and since #310 bounded the whole hero to one viewport-
      height row, every extra pixel the words claimed came straight out
      of `HeroQuestionsArea`'s own budget (`HeroGrid`'s `auto` row sizes
      to the words' content height, subtracting directly from the
      `questions` row's `1fr` share). At 1400×900 this left even Level 1
      (suggested-match card + all four answer controls, no candidate
      grid to scroll) short by ~140px, forcing an internal scroll that
      clipped the card mid-view. Fixed by shrinking `Word`'s height to a
      `clamp()` of the viewport height (not a flat rem guess, so it
      can't silently regress on a shorter viewport than was checked) —
      deliberately smaller than even the mockup's own absolute number,
      since the mockup was never height-constrained the way the pinned
      hero now is. `HeroGrid`'s row-gap and `StarburstBackground`'s own
      padding/margin (whatsthat.tsx) were also trimmed at `md`+ (never
      approved content, pure chrome spacing that was also coming
      straight out of the same budget), and the Level 1 reference
      thumbnail's `maxWidth` was cut as a smaller, separately-named
      lever once the above alone still left only a single-digit-px
      margin. All of this was re-measured and re-tuned again on rebase
      onto #313's three-tier `Footer` redesign, which is substantially
      taller than the single-tier footer this fix's own first pass was
      built against and ate further into the same budget — see
      `WhatsThatWords.tsx`'s `Word` component and `QuestionFeed.tsx`'s
      `HeroGrid`/reference-thumbnail comments for the exact before/after
      numbers at each pass. New hard regression guard:
      `QuestionFeedResponsive.spec.ts` asserts at 1400×900 that Level
      1's `HeroQuestionsArea` never overflows (`scrollHeight <= clientHeight`) and all four answer controls are fully within the
      viewport, not merely `toBeVisible()` (which only requires a
      non-zero intersection, not full containment) — confirmed to fail
      on the pre-fix code with the exact expected numbers before the fix
      landed.
    - **Pulse/pop desynced from a still-loading card**: the reveal
      fade (`RevealOverlay`), the word-pop sequence
      (`WhatsThatWords`), and the hero card pulse
      (`CardPulseWrapper`) all used to start counting the moment their
      own elements mounted, independent of whether the subject card's
      `<img>` had actually finished loading — on a slow connection this
      could reveal, pop, or pulse against a still-loading or half-
      painted image. Owner's redesign of the choreography: the card
      slot shows the blue cover state and holds it until the image's
      `load` event fires, then the entire sequence (cover fade off +
      word pops + card pulse, all still frame-for-frame in sync with
      each other) runs as one queue anchored to that single moment.
      Implemented via a shared `imageLoaded` boolean
      (`QuestionFeed.tsx`) threaded into each of the three animated
      components' own `$playing`/`playing` prop, which gates each
      one's CSS `animation-play-state` (`paused` until told otherwise,
      `running` once `imageLoaded` flips) — the timeline, delay
      included, doesn't advance at all while paused, so flipping all
      three at once genuinely starts them in lockstep rather than
      merely un-pausing three independently-drifted clocks. A failed
      load (`onError`, non-empty configured URL) keeps the cover up
      permanently with no animation at all (no legitimate "reveal"
      moment to sync to), while `revealed` still flips true so the rest
      of the question UI isn't stranded behind it; reduced motion skips
      the whole animated queue and jumps straight to `revealed` on
      load, matching the owner's "swap to the image without pops,
      immediately on load" instruction. A genuinely empty configured
      URL (this test suite's own fixture convention — real cards always
      carry a real CDN URL) is treated as trivially settled rather than
      a failure, resolved synchronously in the fetch handler rather
      than waiting on any browser event — an `<img src="">` resolves
      its empty `src` against the _current page's own URL_ (confirmed
      empirically, the URL spec's own "empty string" case) and
      predictably fails to decode that as an image, so relying on the
      resulting real `onError` event as the _only_ settle signal for
      this specific case proved flaky under dev-server load.
      **Real bug found and fixed during this pass, not just the
      intended one**: the settle logic's own catch-up effect was
      initially keyed on the card's identifier, which can legitimately
      repeat between two consecutive feed items (documented already,
      for different state, in the fetch handler's own comment) — a
      repeat resolution resets `imageLoaded`/`revealed` unconditionally
      but doesn't change the identifier, so an identifier-keyed effect
      silently skips re-running and permanently strands the UI on
      "Loading...". Fixed by keying that effect on a generation counter
      bumped unconditionally in the same reset block instead — see
      `docs/troubleshooting.md`'s dedicated entry for the full
      symptom/cause/fix writeup. New regression coverage:
      `WhatsThatWordsAnimation.spec.ts` gained a test that holds a real
      (route-intercepted) image response and asserts every one of the
      three animations is genuinely `animation-play-state: paused`
      before the response resolves and `running` once released —
      confirmed to fail on the pre-fix code.
  - **Fix round (owner live-review, mobile /whatsthat pass)**: two more
    owner-reported issues, found once the `imageLoaded` gate above was
    confirmed genuinely deployed and working.
    - **Fade felt delayed even though the gate was working**:
      `revealAnimation` (`cardPanel.tsx`) held at full opacity for the
      first 55% of its 1.8s run before this fix round — a leftover from
      BEFORE the `imageLoaded` gate existed, when the hold bought the
      network a moment to catch up before the cover started fading at
      mount time regardless of load state. Once gated on the real load
      event, that hold became pure redundant lag layered on top of the
      real wait: by the time `$playing` is ever allowed to flip to
      `running`, the image is already there, so holding at opacity 1 for
      another ~1s just reads as "nothing happened yet". Collapsed to a
      plain two-stop fade (`from`/`to`, no hold checkpoint) and shortened
      1.8s ease-in → 0.8s ease-out, so the drop starts the instant
      playback resumes and is visibly moving immediately rather than
      creeping through ease-in's own "slow start" for its first chunk.
      Timings: `WhatsThatWords`' pop sequence (0/0.24s/0.48s delay, 0.48s
      duration each — ends 0.48s/0.72s/0.96s) and `CardPulseWrapper`'s
      pulse (0.24s delay, 0.48s duration — ends 0.72s) now land across
      the fade's own 0-0.8s run instead of only starting after it had
      long finished, so the pops visibly overlap the fade's tail as
      intended.
    - **Subject card bypassed the image CDN entirely**: the hero `<img>`
      rendered `item.card.mediumThumbnailUrl` directly — a raw backend
      field that (`cardpicker/sources/source_types.py`'s
      `GoogleDrive.get_medium_thumbnail_url`) resolves straight to
      `drive.google.com/thumbnail?...`, bypassing `cdn.proxyprints.ca`
      (the R2-cached image-CDN Worker every other card surface — `Card.tsx`, `SharedDeckViewer.tsx`, `downloadImages.ts` — already
      prefers) entirely. Confirmed live via a real Network-tab capture:
      the hero request landed on `drive.google.com`, not
      `cdn.proxyprints.ca`. Now resolves through `getWorkerImageURL`
      (`common/image.ts`) first, at the `"small"` (400px) tier — this
      hero caps at 320px CSS width even on desktop, and far less in the
      mobile compact column, so `"small"` comfortably covers a >2x-
      retina render at that size — falling back to the raw
      `smallThumbnailUrl` field only when the worker genuinely isn't
      configured for this source type (the same fallback chain
      `Card.tsx`'s own `useImageSrc` uses). Guarded on the raw
      `mediumThumbnailUrl` field being non-empty (not on whether
      `getWorkerImageURL` returned something) so the test suite's
      "empty `mediumThumbnailUrl` means nothing to load, skip to the
      settled fast-path" fixture convention keeps working —
      `getWorkerImageURL` would otherwise happily build a real-looking
      (but bogus) CDN URL for any `GoogleDrive`-sourceType fixture
      regardless of whether either thumbnail field is genuinely
      configured. `WhatsThatWordsAnimation.spec.ts`'s route-intercepted-
      image test was updated to intercept the actual CDN worker URL
      (computed via the same `getWorkerImageURL` helper, not hand-
      constructed) instead of an arbitrary same-origin path — it
      silently kept "passing" against the CDN swap by racing a real,
      unmocked outbound network call to `cdn.proxyprints.ca` before this
      fix, which is exactly the kind of drift this task's own report
      flagged rather than left in place.
  - Regression coverage: `QuestionFeedResponsive.spec.ts`'s desktop-axis
    test now asserts card-left-of-questions (was candidates-left-of-card
    pre-#305); `WhatsThatWordsAnimation.spec.ts` (new) asserts computed
    CSS animation properties (`animation-name`/`-duration`/`-delay`/
    `-timing-function`), not mid-frame screenshots (the sheet-position-pill
    flake lesson, `docs/troubleshooting.md`) — Playwright's project-wide
    `reducedMotion: "reduce"` default means every _other_ existing spec
    never has to account for this animation at all; this file explicitly
    overrides it per-test where it needs the animation actually running.
- **Artist write-in with autocomplete** (backend only this pass — frontend
  ships separately). Lets a voter on `/whatsthat`'s artist question and
  `/display`'s Artist sidebar suggest an artist not in the candidate list,
  for when `ArtistVotePicker.tsx`'s existing ranked-candidates/typeahead
  modes (`post_artist_candidates`, exact-name `SubmitArtistVoteRequest`)
  come up empty. Two new endpoints, both additive — no change to
  `cardpicker.artist_consensus` (PROTECTED CORE) or to
  `post_artist_candidates`/`post_submit_artist_vote`, which are untouched:
  - `POST 2/artistAutocomplete/` (`ArtistAutocompleteRequest{query}` ->
    `ArtistAutocompleteResponse{results: [{id, name}]}`) — unscoped (no
    card `identifier`), catalogue-wide, case-insensitive, prefix-then-
    substring name search, capped at `ARTIST_AUTOCOMPLETE_PAGE_SIZE` (10)
    results. Unauthenticated-OK (public, read-only data, no
    `reject_untrusted_origin`) but rate-limited per-IP
    (`ARTIST_AUTOCOMPLETE_RATE`, default `120/m`) since it's expected to
    fire on every keystroke. Returns an `id` (unlike
    `post_artist_candidates`'s bare-name results) so the cast endpoint
    below can be called unambiguously.
  - `POST 2/submitArtistWriteInVote/`
    (`SubmitArtistWriteInVoteRequest{identifier, anonymousId, artistId?, freeText?, voteSurface?}` -> `SubmitArtistWriteInVoteResponse` — the
    same consensus shape as `ArtistConsensusResponse` plus `castArtist`
    and `createdNewArtist`). Exactly one of `artistId` (the autocomplete-
    pick path, the PRIMARY normalization route) or `freeText` is
    required. `freeText` is control-character-stripped, whitespace-
    collapsed, length-capped (`ARTIST_WRITEIN_NAME_MAX_LENGTH`, 100), then
    matched case-insensitively against existing `CanonicalArtist.name`
    values — a match REUSES that row (no twin of an existing artist under
    a different casing); only a genuinely new normalized name creates a
    new row. Either way the vote that gets cast is a completely ordinary
    USER-source `CardArtistVote`, through the exact same
    `resolve_and_persist_artist` path as `post_submit_artist_vote` — same
    weight, same gates, same rate budget (shares
    `PRINTING_TAG_SUBMISSION_RATE` via the existing
    `_printing_tag_rate_limit_key`/`_rate`, not a separate budget) —
    write-ins get no special treatment in consensus. Guarded with
    `reject_untrusted_origin`, same as every other vote-casting endpoint.
    No guard against an already-RESOLVED card (mirrors
    `post_submit_artist_vote`/`post_submit_printing_tag`, neither of
    which gate on that either).
  - No new `CanonicalArtist` field for write-in provenance: a write-in-
    created row is indistinguishable from any catalog-imported one by
    design (per spec, it gets no special consensus treatment), and an
    unreferenced write-in row (name created, vote later retracted/
    superseded) is judged harmless to persist — a `CanonicalArtist` row
    is a few bytes of text, not image data, and the admin panel already
    supports a manual rename/merge if one ever needs cleaning up.
  - KNOWN LIMITATION, flagged rather than silently fixed: the write-in
    reuse match is case-insensitive, but the Scryfall/MTG catalog sync
    path (`integrations/game/mtg.py`'s `artists_by_name` dict) dedupes
    existing `CanonicalArtist` rows by EXACT, case-sensitive name. A
    write-in stored with unconventional casing that's later confirmed by
    an official Scryfall entry under different casing will still produce
    a duplicate row at the next sync — deferred, not eliminated. Fixing
    that touches the catalog sync integration, not the vote/consensus
    system this task targets, so it's out of scope here.

## Key files (Stages 1–7; Stage 8+ files are in [[catalog-completion-plan.md]])

- Backend: `cardpicker/printing_consensus.py`,
  `cardpicker/printing_metadata_import.py`,
  `cardpicker/integrations/game/mtg.py`, `cardpicker/models.py`,
  `cardpicker/search/search_functions.py`, `cardpicker/documents.py`,
  `cardpicker/tag_consensus.py`, `cardpicker/reason_tags.py`,
  `cardpicker/default_tags.py`,
  `cardpicker/management/commands/seed_no_match_reason_tags.py`,
  `cardpicker/deductive_backfill.py` +
  `deductive_backfill_printing_tags` management command,
  `cardpicker/question_feed.py`, `cardpicker/attribute_tags.py` +
  `seed_attribute_tags` management command.
- Frontend: `frontend/src/features/printingTags/`
  (`PrintingTagPicker.tsx`, `starburstShape.ts` — kept only for its
  `STARBURST_OUTER_COLOR` constant, `ChipCard.tsx`'s default/pre-rebuild
  frame; `cardPanel.tsx` — WTC-rebuild-retinted, `BurstSvg`/`HoverBurst`/
  `useStarburstFrame`/`CardPulseWrapper` deleted),
  `frontend/src/features/questionFeed/WhatsThatWords.tsx` (WTC rebuild:
  now a plain, static, token-coloured `<h1>` wordmark — no more sliced-
  word pop sequence),
  `frontend/src/features/filters/ResolvedAttributeFilter.tsx`,
  `frontend/src/common/processing.ts::getPrintingMatchLabel`,
  `frontend/src/features/attributeVoting/` (`ChipCard.tsx`,
  `NoMatchReasonStrip.tsx`, `QueueTagQuestion.tsx`,
  `ArtistVotePicker.tsx`), `frontend/src/common/tagDisplayNames.ts`,
  `frontend/src/features/attributeChips/`,
  `frontend/src/features/questionFeed/QuestionFeed.tsx`,
  `frontend/src/pages/whatsthat.tsx`.
- Docs: `docs/upstreaming/vote-system.md` (upstream cherry-pick
  classification — flags that the starburst theming is interleaved with
  real vote-queue logic across many commits and shouldn't be cherry-picked
  commit-by-commit), `docs/federation-v1.md` (`name` vs `display_name`
  interchange-key note).

## Known gaps

- Client-side (local-folder/Google Drive) search gets no re-rank/filter/
  match-indicator parity — no ES/DB access on that path.
- The starburst/card/chip-ring layout was hand-tuned via iterative
  screenshot review, not built against a formal design system — flagged
  for a `/dataviz`-skill pass.
- Ranked-union v1 has a known starvation property (see above);
  interleaved/weighted scheduling is a future v2, not built.
- Stage 8+ (local printing-ID backfill / catalog-completion) gaps: see
  [[catalog-completion-plan.md]].

## Related docs

- [[moderation.md]] — sensitive-tag moderation layer
- [[card-dom-api.md]] — printing-candidate DOM attribute wiring
- [[catalog-completion-plan.md]] — Stage 8+ (active development)
- `../upstreaming/vote-system.md` — upstream cherry-pick manifest
- `../federation-v1.md` — federation verdict exchange format
- [[../lessons.md]] — sticky/overflow CSS, testid collisions, cyclic-
  animation sampling, and data-migration-vs-command-seeding gotchas
  surfaced while building this

## Stage 8: local (zero-API-cost) printing-identification backfill pilot

**Status: built and pilot-run against live production** (2026-07-15,
`worktree-local-printing-id-pilot`, PR #22). Code + tests merged; a real
`--limit 300 --engine both --nice` invocation ran against the live DB and
its full results are summarized below. **Full-catalog run explicitly NOT
executed** - see "Real pilot run results" below for why (a ~13-day
single-process projection). See
`journal/2026-07-15-local-printing-id-pilot.md` (machine-local, not
committed) for the complete data dump this summary is drawn from.

Sibling to Stage 6's deductive backfill, same non-negotiable principle
(a vote is always just a vote, never a direct resolve - the human-backed
gate in `vote_consensus.resolve_weighted_consensus` still applies), but
sourced from actually looking at the card image instead of pure logical
deduction from existing structured data - two independent local (no paid
API calls) pass-1 engines, plus a pass-2 fallback for cards pass 1 can't
reach at all:

- **L1, OCR**: Tesseract on a cropped, preprocessed collector-line region
  (bottom-left corner, grayscale/upscaled/thresholded). Parses candidate
  (set code, collector number) pairs from the raw text and only casts a
  **positive** vote when the parse matches **exactly one** of the card's
  own name-candidates - weak OCR is made safe by this validation rail, not
  by trusting the OCR output itself. Also casts a real `is_no_match=True`
  vote for its own distinct **"parsed-but-no-match"** outcome (a
  syntactically valid parse that matches none of the card's candidates) -
  see "Negative-vote wiring" below for why this one skip_reason (of
  several) is treated as genuine whole-candidate-set evidence rather than
  a mere abstention. **OCR engine seam (issue #423, 2026-07-25 spike)**:
  `cardpicker/local_ocr.py` dispatches between two Tesseract bindings
  behind `settings.OCR_ENGINE` - `"pytesseract"` (the OLD default,
  process-per-call behavior) or `"tesserocr"` (a persistent in-process
  `PyTessBaseAPI`, ~5.7x faster per the spike's real-OCR-call
  measurement, since it eliminates pytesseract's own ~97ms/call
  tesseract-process-spawn floor).
  `cardpicker/management/commands/ocr_engine_ab.py` is the read-only
  real-image A/B validation tool any flip decision is gated on (per-image
  byte-identity, parse-level agreement, stored-vs-fresh drift detection,
  confidence deltas, and latency for both engines - writes nothing, per
  this doc's own "index, don't store" discipline). Its
  `--disagreements-detail` flag classifies every parse-level disagreement
  further - each engine's parse checked against the real
  `known_set_codes()` lexicon and `validate_against_candidates`
  candidate-matcher (same checks the real join-key calculator uses, not
  reimplemented) - into
  `tesserocr_only_valid`/`pytesseract_only_valid`/`both_valid_different`/
  `neither_valid` buckets, also recorded on the run's own ledger row.

  **THE FLIP (issue #480's combined whole-catalog pass, held in a PR that
  merges only on the owner's own A/B GO - see that PR's own description,
  not a standalone decision)**: `settings.OCR_ENGINE` now defaults to
  `"tesserocr"`, bundled in the SAME change as the OCR-derived extractor
  version bump (`COLLECTOR_LINE_OCR`/`ARTIST_OCR`/`COLLECTOR_LINE_TSV`/
  `LEGAL_LINE_EXTRACTOR_VERSION`, v1 -> v2 in `image_evidence.py`) -
  tesserocr's wheel vendors a different compiled tesseract/leptonica build
  than the apt package pytesseract shells out to, so the swap is real
  output drift, not a transparent speed-up, and issue #480's own
  correction comment forbids an engine swap without a version bump
  (untracked drift under one provenance label). `OCR_ENGINE=pytesseract`
  in the environment is the instant rollback. That same PR also landed
  issue #487's three pre-flip fixes found by the Tron gate on PR #486:
  `_tesserocr_available` widened to catch `Exception` (not just
  `ImportError`), the TSV read+parse moved inside the crash-guarded
  region (a malformed row degrades to the pytesseract fallback instead of
  raising), and a `threading.Lock` serializing the process-global
  `PyTessBaseAPI`'s SetImage/Recognize/read sequence.

- **L2, perceptual hash**: art-region phash comparison against each
  name-candidate's Scryfall art crop, voting only when there's a clear
  single best match (distance threshold + margin over the second-best,
  recalibrated from real production data - see the journal for the
  calibration history). `CanonicalCard.image_hash` (`models.py`) already
  exists as a `BigIntegerField` for exactly this - added when
  `import_canonical_card_data` first shipped ("CanonicalCard population
  fix" above) but never computed in production (`--skip-image-hash` was
  used for the real import) - so this pilot is the first thing to
  actually populate it, lazily, only for candidates it needs. Capped at
  12 candidates per name (basic lands/staples can have hundreds - see
  "Real pilot run results" for how often this cap fires). Never writes
  `is_no_match` - a "no-clear-winner" outcome is evidence against ONE
  candidate falling short of the bar, not against the whole set (see
  "Negative-vote wiring" below).
- **Pass 2, fallback** (`local_fallback.py`, `local-fallback-v1`): fires
  only when pass 1 (either engine) produced no accepted vote for a card -
  the old-border-frame case (no collector line printed on the card face
  at all, just an "Illus. `<artist>`" credit). Evidence-combination model
  across border-color sample, artist-name OCR fuzzy match, and set-symbol
  phash (found unreliable in practice, kept but effectively disabled via
  a strict threshold - see `local_fallback.py`'s module docstring for the
  full negative finding): a **positive** vote is cast only when the
  intersection of every sub-check that produced a reading narrows to
  exactly one candidate. Also casts a real `is_no_match=True` vote for its
  own distinct **"eliminated"** outcome (the intersection narrowed to
  ZERO candidates) - see "Negative-vote wiring" below.
- Border-color sampling and frame-style classification (OCR-collector-
  line-present vs. Illus.-anchor-present) run for **every** processed
  card regardless of printing-vote success, casting standalone
  attribute-chip votes (Black/White/Silver Border, Borderless, Old/Modern
  Border) - and, when a printing vote **is** confirmed for that card this
  run, preferring ground truth from that printing's own
  `CanonicalPrintingMetadata` (Scryfall `border_color`/`frame`) over the
  heuristic estimate. The same heuristic reading also feeds a
  **consistency check**: if a card's observed frame class contradicts its
  matched printing's real frame value, the printing vote itself is
  withheld (kept as a frame-vote-only outcome) rather than trusting an
  art/OCR match that likely landed on the wrong printing.
- All engines vote under `VoteSource.OCR` (the 2026-07-15 split of the
  old single `VoteSource.AI` value into `DEDUCTION`/`OCR` - see
  `models.py`'s `VoteSource` docstring; same weight/gate treatment as
  before, individual technique still distinguishable via `anonymous_id`)
  - when OCR and phash both vote on the same card and agree, both votes
    stand as independent evidence; on disagreement, **neither** is written
    (logged instead - see the journal's disagreement examples).

**Environment**: resolved via a host-side venv pointed at the
already-`127.0.0.1`-exposed Postgres/Elasticsearch ports (zero
Docker/container change) - `tesseract-ocr` installed via host apt,
`pytesseract`/`ImageHash`/`Pillow` via the venv's `requirements.txt`
install. No Dockerfile change made. (A future full-catalog run, if one
ever happens, should revisit baking `tesseract-ocr` into
`docker/django/Dockerfile` instead, per the original tradeoff writeup.)

### Negative-vote wiring (2026-07-20, issue #207)

Owner-approved, diagnostic-backed follow-up closing the implementation
gap `docs/theory.md` §4 always assumed existed: machine engines can cast
a real `is_no_match=True` `CardPrintingTag` vote, not only a positive
one, for the two skip_reasons that carry genuine evidence against the
**whole** candidate set (not just one candidate) - OCR's
`"parsed-but-no-match"` and fallback's `"eliminated"`. Every other
skip_reason (a pure abstention, or evidence against a single
candidate/pair rather than the set) is unaffected and still casts no
vote at all. Same non-negotiable principle as every other engine in this
doc: still just a vote (`VoteSource.OCR`, machine weight `0.5` by
default) - the human-backed gate
(`vote_consensus.resolve_weighted_consensus`) means a lone machine
`is_no_match` vote can never resolve a card to `NO_MATCH` by itself
(`PRINTING_TAG_MIN_VOTES=2` can't clear on weight `0.5` alone). Effect at
current weights: advisory only - it surfaces the card as `CONTESTED` if
a printing vote already exists or is cast later
(`printing_consensus.get_contested_card_ids` already treats "a printing
vote + a no-match vote on the same card" as contested, unchanged by this
work), giving a reviewer a genuine negative signal instead of the prior
silence.

**PREREQUISITE - the ambiguous/no-match split**: `local_ocr. validate_against_candidates` already returned a distinct `"ambiguous"`
outcome (a collector-number-only match against more than one candidate -
possible when a name spans multiple sets sharing a number) separately
from `"parsed-but-no-match"` (matches none), but `run_ocr_for_card` used
to discard that distinction - it only ever inspected the matched
candidate, never the skip reason, on a miss, silently folding both into
`"parsed-but-no-match"`. Fixed first, since casting `is_no_match` on the
now-corrected `"parsed-but-no-match"` would otherwise have miscast an
ambiguous (evidence-FOR-more-than-one-candidate) read as
whole-set-no-match evidence. Tracked across every preprocessing variant
tried (not just the last), with `"ambiguous"` taking priority if any
variant produced it.

**What does NOT cast `is_no_match`**, deliberately: frame-mismatch (a
vote WAS produced but withheld by the consistency check - evidence
against the ONE candidate it landed on, not the set),
engine-disagreement (OCR and phash each finding a DIFFERENT candidate -
evidence FOR two candidates), and every pure-abstention reason (OCR's
`"no-text"`/`"ambiguous"`; phash's `"too-many-candidates"`/
`"no-hashable-candidates"`/`"no-clear-winner-distance"`/
`"no-clear-winner-margin"`; fallback's `"no-evidence"`/`"ambiguous"`).
Casting a whole-set no-match vote from any of these would misrepresent
what the engine actually found.

**Instrumentation for a future ranked-vote decision** (code-only, no new
fetches, no ranked-vote schema built here - `docs/theory.md`'s
Dawid-Skene addendum is the eventual consumer): `CardScanLog` gained two
additive fields, `evidence_types_used` and `survivor_pks` (never for an
OCR/phash row, which have no sub-check concept of their own).
`evidence_types_used` is always available (already threaded through as
`CardOutcome.fallback_evidence_types`, just never persisted before this
change). phash's own `"no-clear-winner"` skip_reason is similarly split
into two distinct sub-cases, `"no-clear-winner-distance"` (best distance
over threshold) and `"no-clear-winner-margin"` (runner-up too close
behind it) - re-derived in the caller via a pure Hamming-distance
recompute over the exact same inputs `local_phash.find_best_match`
itself used (verified empirically to match `imagehash.ImageHash`'s own
subtraction before use), never by editing that function's own decision
logic.

**Two distinct fallback mechanisms, not one** - easy to conflate since
both port the same evidence-combination model: `local_fallback.py`'s
`run_fallback_for_card`/`FallbackOutcome` is the LIVE PILOT engine
(PROTECTED CORE, runs against a fresh per-invocation image fetch);
`local_calculate_verdicts.calculate_fallback_verdict` is Stage D's own
independent port, operating entirely off already-persisted
`ImageEvidence` fields. The latter calls `local_fallback.py`'s
`filter_by_border_color`/`match_artist` directly (PROTECTED CORE
functions, called not reimplemented) and reimplements only the symbol
sub-check's pure Hamming-distance arithmetic - never `FallbackOutcome`
itself, so its own `survivors` set was never gated on that class
exposing anything.

**`survivor_pks` now populated for Stage D's own fallback rows** (issue
#433): `calculate_fallback_verdict` already builds `survivors` to pick
its own skip_reason in the first place - the "no protected-core
reimplementation" analysis above applies unchanged, since this only
persists a set that calculator already held via functions it was already
calling. Populated for all three skip reasons that calculator returns:
the full candidate set for `"no-sub-check-evidence"` (nothing filtered
anything), `[]` for `"eliminated"`, the actual shortlist for
`"ambiguous"`. **Still `null`** for the LIVE PILOT engine's own fallback
rows - recovering ITS survivor set still means either reimplementing
`local_fallback.py`'s sub-checks a second time in that caller or having
`FallbackOutcome` expose `survivors` directly, and the latter still
touches protected core. **Open item, not built**: exposing `survivors`
on `FallbackOutcome` remains the clean fix for the live pilot engine's
own rows, needs owner sign-off per the absorption-adjacent
protected-core review convention.

**Known gap, not built**: `is_no_match` votes do not propagate to
cluster (identical-image) members the way positive votes do via
`propagate_cluster_vote` - unscoped by issue #207, and extending that
function to accept an `Optional[printing_pk]` is real surface area
nobody asked for. A representative card's no-match conclusion is
currently NOT mirrored onto its absorbed duplicates.

**Side effect on abstention-aware ordering, worth being explicit about**:
`_compute_hard_names` demotes a name to the back of the queue once it
has `>= HARD_NAME_MIN_ATTEMPTS` non-rescannable scan-log rows and zero
votes, "one real vote disqualifies the name permanently" (see that
function's own docstring). Since `"parsed-but-no-match"`/`"eliminated"`
now cast a real vote instead of a scan-log row, cards that used to count
toward hard-name demotion no longer do, the moment they get a genuine
`is_no_match` conclusion. Judged correct, not a regression: a no-match
vote is a real conclusion (the engine successfully determined "not this
set"), not a failure-to-conclude - the demotion mechanism exists to
deprioritize names an engine keeps failing to say anything about, and
this is the opposite of that.

### Real pilot run results (2026-07-15, `--limit 300 --engine both --nice`)

**32m4.6s wall-clock, 19m36s user + 4m37s sys CPU (≈76% avg utilization of
one core on this 2-CPU box), exit 0.** `--nice` confirmed actually
throttling (process niceness observed alternating 5↔19 during the run).

| Engine    | Attempted | Votes written | Yield |
| --------- | --------- | ------------- | ----- |
| OCR       | 300       | 77            | 25.7% |
| Phash     | 300       | 13            | 4.3%  |
| Fallback  | 210       | 4             | 1.9%  |
| **Total** | —         | **94**        | —     |

**Gate check: 0/94 affected cards resolved** - the human-backed gate held
perfectly at this scale, same result as Stage 6's 0/28,112.

Largest skip bucket by far: OCR's "parsed-but-no-match" at 176/300
(58.7%) - a syntactically valid collector line that didn't match any of
the card's own candidates. Not investigated further in this pilot (out of
scope), but the single most promising lead for improving yield before any
larger run - see the journal for the plausible-causes breakdown.

Attribute votes: border `{black: 280, borderless: 17, white: 3}` (91 from
ground truth, 209 from the pixel heuristic); frame `{modern: 258, old: 14}`, 28 abstains (91 from ground truth, 181 from the OCR/Illus.-anchor
heuristic); **6 frame-mismatches** (printing vote withheld by the
consistency check) - see the journal for all 10 sampled examples and the
per-case reasoning.

**Full-catalog projection: ~171,800 eligible cards remain (of 179,002 raw
eligible pool) → naive linear projection ≈ 306 hours ≈ 12.8 days of
continuous single-process runtime.** This is the key number for any
future decision to scale up - not attempted in this pilot, and not
practical as a single uninterrupted process. Before attempting it:
parallelizing across multiple processes/pk-range partitions (raised, not
yet implemented - see the pre-scale program's scaling proposal below).

### Checkpointing (2026-07-15, pre-scale program item 2)

`run_pilot` no longer does one giant `bulk_create` at the very end -
matches `deductive_backfill.py`'s periodic-flush precedent (`--batch-size`,
default 25 cards - much smaller than `deductive_backfill`'s 2000, since
each card here costs a real image fetch plus OCR/phash CPU work, not just
a DB write). A killed/interrupted run keeps whatever it already flushed;
a plain re-invocation resumes cleanly with no separate checkpoint file,
via the same `select_candidates` idempotence mechanism `--resume` already
relied on. Verified live in tests (`TestCheckpointing`, not just
plausible): flushes happen every `--batch-size` cards, a simulated kill
mid-run leaves the already-flushed cards durably committed and a
follow-up invocation completes exactly the remainder with no duplicates.

**One deliberate deviation from `deductive_backfill`'s pattern**: the gate
check (`verify_zero_resolutions`) now runs after every flush, not once at
the end. `deductive_backfill`'s votes are provably exact by construction
(a violation there is structurally impossible, so one end-of-run check is
belt-and-suspenders); this pilot's OCR/phash/fallback votes are explicitly
weaker, lower-confidence signal where a real violation is more plausible,
and a kill is now an _expected_ event for a multi-day run - a violation in
an already-flushed batch must not sit undetected in the DB indefinitely
just because the process died before reaching a final check that may
never come.

5-vote spot check, 20-vote random admin-link sample, 3 disagreement
examples, and the filename tag-gap census (1,097 unresolved cards with an
unmatchable `expansion_hint`) are all in the journal, not duplicated here.

**Pilot discipline honored**: `--limit 300`, no full-catalog run attempted
per the original hold.

### Phase timing (2026-07-15, pre-scale program item 3a)

Measured against real production data (read-only, no writes) via two
instrumented 30-card samples run through the actual pipeline functions,
not simulated. First sample (OCR + phash only) undercounted real cost -
`run_pilot` also runs border/frame classification and pass-2 fallback for
every card with an image, regardless of pass-1 outcome. Second sample
matched `run_pilot`'s real per-card call sequence exactly:

| phase                           | mean/card | share of measured total |
| ------------------------------- | --------: | ----------------------: |
| `detect_illus_anchor`           |    1.466s |                   33.0% |
| pass-2 fallback (fires ~70%)    |  1.474s\* |                   23.2% |
| `fetch_card_image`              |    1.187s |                   26.6% |
| OCR (crop+preprocess+tesseract) |    0.602s |                   13.5% |
| `classify_border_color`         |    0.159s |                    3.6% |
| phash (hash+compare)            |    0.011s |                    0.2% |

\*mean over the 21/30 cards it actually fired on; contributes 0 for the
other 9.

**Measured total: 4.46s/card** (sum of the above), against the real
300-card pilot run's **observed 6.42s/card** (32m4.6s / 300) - a ~2s/card
gap not fully attributed by this instrumented sample, plausibly per-card
DB queries this sample didn't isolate (the frame-mismatch consistency
check and ground-truth-metadata lookup each re-query `CanonicalCard` once
per confirmed vote) and/or run-to-run network/cache variance (different
selection window, different Scryfall/CDN load). Treat 6.42s/card as the
trustworthy full-pipeline number and the phase breakdown above as
directional (which phases dominate), not a component-by-component
reconciliation.

**`detect_illus_anchor` is the single largest cost, and it's partly
redundant with the main OCR pass**: when pass 1's OCR text doesn't
already contain the "Illus." artist credit, it runs its OWN
crop+preprocess+tesseract pass (a second full OCR call per card, on a
different crop) purely to extract the artist name for pass-2 evidence
and the frame-style classifier's illus-anchor signal. This is a real
optimization target flagged for a future pass, not fixed here - the
addendum ledger closed on ideas beyond items 1-8, and this wasn't one of
them.

### CDN fetching + Worker quota (2026-07-15, pre-scale program item 3b)

**The premise "CDN-first fetching" was built on turned out to be wrong,
checked against the actual Worker source (`image-cdn/src/handler/image.ts`,
`R2Service.ts`) before implementing anything.** The pilot's
`get_worker_image_url` requests the `full` tier (matching the PDF export
path, for print-quality output) - and the `full` tier is a **pure
passthrough**: `fetch(url)` straight to Google Drive, every single
request, with zero R2 involvement. Only the `small`/`large` tiers go
through `R2Service.getThumbnail`'s cache-check-then-populate-on-miss
logic. There is no bucket to be "first" about in the pilot's current flow

- it was never touching one.

**Checked whether switching tiers would help anyway - real measurement,
not assumption.** If the pilot switched to the `large` tier (800px,
R2-cacheable), would it benefit from a warm cache? Fetched 20 real
pilot-candidate images through both `full` and `large` Worker endpoints:
**0/20 `large`-tier requests showed a cache hit** (`cf-cache-status: DYNAMIC` on every one; `large` mean 0.881s vs. `full` mean 0.983s -
within noise, both dominated by Google Drive origin latency, not R2 read
time). This isn't surprising in hindsight: the pilot's candidate pool is
specifically the tail of the catalog needing backfill - by definition
these are exactly the cards NOT recently popular enough to have been
browsed (and thus cached) by real users. **Verdict: switching tiers would
not reduce fetch latency or add caching benefit for this workload - stay
on `full` tier, already in use, gives the best-quality image for OCR.**
This also makes addendum item 6's original framing ("OCR resolution floor
re-measured at the CDN's delivered pixel size") moot - the delivered
pixel size doesn't change, since no tier switch is happening.

**Checked a real cache-key gap while in the Worker source, cleared it -
not applicable today.** `R2Service.getImageKey` doesn't include
`jpgQuality` in the cache key (`${imageIdentifier}-${imageSize}-${imageType}`)

- whichever quality first populated an entry is what every later request
  gets, silently. Checked every call site across `frontend/src/` that
  requests `small`/`large`: all either omit `jpgQuality` (defaulting to

100. or pass 100 explicitly - no call site requests a different quality
     today, so this can't currently produce a mismatched-quality cache hit.
     Worth remembering if a quality-tunable thumbnail path is ever added, but
     not an active risk to the pilot (or anything else) as the code stands.

**What the real constraint actually is, and what got built for it**: every
image fetch is one request against the Worker's daily request quota,
which is **shared with live site traffic** regardless of which tier is
requested (a cache hit still counts as a Worker request, just a cheaper
one to serve) - this part of the original concern was correct, just not
for the "bucket-first" reason originally assumed. Implemented
`--fetch-budget` (`run_pilot(fetch_budget=...)`): caps the number of
image fetches a single invocation will make; on exhaustion the run stops
cleanly mid-selection, whatever was already flushed stays committed, and
every card not yet reached is left completely untouched (no vote, no
skip-reason recorded) so the next invocation's ordinary idempotent
selection just picks them up - no special resume handling needed, same
mechanism `--resume`/checkpointing already relies on. Verified in tests
(`TestFetchBudget`): stops exactly at the budget, and a follow-up
invocation with no budget completes the untouched remainder with no
duplicates.

**Quota math**: ~171,800 eligible cards remain, each fetched at most once
(idempotent selection - no repeat fetches across invocations). Spread
across the ~13-day naive full-catalog projection (see wall-clock section
below), that's roughly 13,000/day if evenly sliced - well under the
Worker's 100,000/day shared limit on its own. The real risk isn't the
pilot in isolation, it's concentration: heavy parallelization (item 3d)
compressing the same total fetch count into fewer, busier days, stacked
on top of live traffic's own share of the same quota on those days.
`--fetch-budget` is the safety valve for that scenario - a conservative
per-invocation cap (a specific number is a scaling-proposal decision, not
fixed here) leaves headroom for live traffic regardless of how
aggressively a given slice is scheduled.

**Amendment (same day, owner review): the "shared Worker request quota"
framing above was the wrong quota.** The real question is whether
`lh4.googleusercontent.com` itself (the domain the `full` tier's
passthrough actually fetches from - the Worker's own 100k/day request
quota was never the binding constraint) can take sustained pilot-scale
load without degrading for live traffic. That domain is genuinely shared

- `frontend/src/features/pdf/pdfImage.ts` (PDF export) and
  `frontend/src/features/download/downloadImages.ts` (bulk image download)
  both request the `full` tier already - but had **no rate limiting of any
  kind**, unlike the real Drive API (`GoogleDriveService.executeCall`,
  guarded by the existing `GOOGLE_DRIVE_RATE_LIMITER` binding - a
  DIFFERENT Google domain the `full`-tier image fetch never touches).
  Fixed with a real enforced limiter (`image-cdn`, separate PR ahead of
  this one): a new `IMAGE_FULL_TIER_RATE_LIMITER` Cloudflare rate-limiting
  binding (3 req/s sustained, `wrangler.toml`), wired into `image.ts`'s
  `full`-tier handler via a new `fetchWithRateLimit` helper
  (`src/utils.ts`) that mirrors `GoogleDriveService.executeCall`'s
  check-then-backoff-then-retry pattern - checked-in-limit, delay-and-retry
  on denial, plus a defensive retry on an upstream 429. This is now the
  **primary** protection, shared by all three callers (pilot, PDF export,
  bulk download); `--fetch-budget` is defense-in-depth on the pilot's own
  pacing, not the main safeguard the earlier paragraphs implied. Lands and
  deploys independently of this pilot's own branch, ahead of any
  full-catalog run.

### Resolution floor + payload reduction (2026-07-15, same review)

**`lh4.googleusercontent.com`'s size-suffix parameter genuinely
re-encodes a smaller image - verified directly, not assumed**: fetched
one real card at `=h200`/`=h400`/`=h800`/native and confirmed real,
progressively smaller dimensions and byte counts each time (native
1146x1600 @ 3.29MB → `=h800` 573x800 @ 892KB → `=h400` 287x400 @ 218KB).
The image CDN Worker already exposes this via the `full` tier's existing
`dpi` query param (`height = dpi * 1110 / 300`, `image-cdn/src/url.ts`)

- the pilot just never passed one, so every fetch requested the
  uncapped native original.

**Empirical resolution floor**, a real 6-way sweep (dpi 100/150/200/250/
300/native) against the same 30-card sample used to validate the
tightened crop box, applying that same tightened box and the production
OCR pipeline at each size:

| dpi           | matched/30 | mean payload |
| ------------- | ---------: | -----------: |
| 100           |          3 |        144KB |
| 150           |          7 |        298KB |
| 200           |         12 |        495KB |
| 250           |         10 |        728KB |
| 300           |          9 |        997KB |
| native (none) |          8 |       1.84MB |

dpi≤150 clearly degrades yield below the native baseline; dpi≥200
matches or **exceeds** it despite a 2-4x smaller payload (plausibly a
smaller re-encoded JPEG rendering small text more cleanly than a full-res
original in some cases - 30 cards is too small a sample to fully explain
the exact ranking, but the floor itself - "150 is unsafe, 200+ is safe" -
is a clear, robust signal). Adopted `DEFAULT_FETCH_DPI = 250` in
`local_identify_printing_tags.py` (a `--fetch-dpi` CLI flag, `0` for
uncapped) - a margin above the empirically-best 200, hedging against
small-sample noise while keeping most of the win (728KB vs. 1.84MB
native, 2.5x smaller). **Pilot-only**: `pdfImage.ts`/`downloadImages.ts`
are untouched and still request full print-quality resolution by design.

### Crop tightening (2026-07-15, pre-scale program item 3c / addendum item 6b)

Tesseract's TSV bbox output, sampled across the same 30-card sample
(both preprocessing polarities), showed every observed collector-number-
shaped text line landing within the top 41.2% / right-hand 74.4% of the
existing crop's own area - meaning the bottom ~59% and left ~26% were
dead space. Tightened `local_ocr.DEFAULT_CROP_BOX` from
`(0.0, 0.90, 0.35, 1.0)` to `(0.06, 0.90, 0.35, 0.965)`, applying a
safety margin over the observed range (not cutting exactly to it, per
the addendum's explicit bleed-variance caution) and leaving the right
edge untouched (text was observed touching that boundary already -
trimming it would risk clipping, not save anything). **Validated, not
just derived**: re-ran OCR with both the old and new box against the
same 30 cards - identical match count (8/30 both) AND identical card-
level match set (same 8 card pks matched both ways) - zero yield
regression on this sample. See `local_ocr.py`'s `DEFAULT_CROP_BOX`
comment for the full derivation.

### Bleed-edge tagging (2026-07-15, addendum item 7)

**Checked whether a bleed tag already existed before proposing anything
new, per the addendum's explicit gate**: `appropriate-bleed` already
exists (`sensitive_tags.py`, 0 cards tagged) - but as a
`TagModerationClass.SENSITIVE` tag, the same category as `low-res`/NSFW,
with its own code comment: _"Sensitive because that verification is
exactly a moderator's co-sign."_ It was designed for human-only
verification. Surfaced this to the owner before building anything -
decision: proceed, cast machine votes on the existing tag anyway (a
SENSITIVE tag still requires a moderator co-sign to resolve either way,
so a vote alone can't misuse it - it's one more signal moderators see,
not an override).

**Detection design, owner-directed**: measure the image's own aspect
ratio against chilli_axe's two known reference card sizes
(`frontend/src/common/constants.ts`'s `CardWidthMM`/`CardHeightMM` =
63x88mm trim; +1/8" bleed per edge = 69.35x94.35mm) rather than any
pixel-color heuristic - purely geometric, so it's inherently
DPI/resolution-independent (verified: 0/15 mismatches between native and
`--fetch-dpi=250`-scaled classification of the same real cards - Google's
resize preserves aspect ratio) and unaffected by whether the card's own
border is visually a normal frame or a borderless full-art printing
(both follow the same file-dimension convention regardless of what's
visible).

- `TRIM_ASPECT_RATIO = 63/88 ≈ 0.7159`
- `BLEED_ASPECT_RATIO = 69.35/94.35 ≈ 0.7350`

**Validated against a real, source-diverse sample** (one card per
distinct source, 40 sources, not the earlier 30-card OCR-selection
sample - this needed source diversity, not OCR-selection-order
diversity): a clean, well-separated bimodal signal. Every source but one
clustered tightly at ratio 0.7325-0.7393 (bleed present); the one
exception measured 0.7163, matching the theoretical trim ratio almost
exactly. Nothing observed in the gap between clusters. Classification:
nearest-reference-ratio, abstaining (no vote) when the ratio is more
than 0.03 from BOTH references (`classify_bleed_edge`,
`local_fallback.py`) - comfortably covers the observed real spread on
either side while still abstaining on a genuinely non-standard image
(a DFC composite scan, a token, a corrupted fetch).

**Wired into `run_pilot`**: fires for every card with a fetched image,
independent of printing-vote success (same "double duty" convention as
border/frame attribute votes) - classification is censused
(`AttributeReport.bleed_votes_by_class`) for every card regardless, but
see the negative-only voting change below for what actually gets
written. `VoteSource.OCR`, confidence 0.7 (`BLEED_EDGE_VOTE_CONFIDENCE`).
No ground-truth counterpart to prefer - unlike border/frame, Scryfall
doesn't encode this at all.

**Negative-only voting (2026-07-16, consolidated respec item 4b -
supersedes the original both-directions design above)**: a vote is now
cast ONLY for a `trimmed` reading (`NOT_APPLICABLE`) - a `bleed` reading
(the ~97.5% common case per the 40-source validation) still counts
toward the census but writes NO `CardTagVote` at all. **Absence of any
vote is the documented convention for "presumed normal bleed"** -
updated in `sensitive_tags.py`'s `SENSITIVE_TAGS` comment alongside this
doc, since the tag's _original_ design comment said the opposite
("absence just means not yet verified") from before this pilot existed.
Rationale: `appropriate-bleed` is `SENSITIVE` and needs a moderator
co-sign regardless of machine votes - voting `APPLY` on the routine 97.5%
case would flood moderation with confirmations of normalcy instead of
surfacing the rare real exception, which is what a SENSITIVE tag is for.
Confidence unchanged (0.7). No new tag seeded - the existing-tag check
(`Tag.objects.filter(name=...).first()`, degrades to no vote if absent)
was already in place before this change.

### Who actually casts the attribute chips (2026-07-30, updated 2026-08-19)

**This replaces the pilot as the answer.** Five channels — covering border
colour, frame style, bleed edge, uploader-declared filename treatments, and
extended-art continuity — are cast by **evidence-reading casters that fetch
no images**, wired into the streaming conveyor through two different
dispatch steps: the first four rows below run inside
`stage_e_dispatch._run_attribute_chip_casters`, and `art-edge-continuity-v1`
runs inside the separate `stage_e_dispatch._run_evidence_only_calculators`
— both are called from `_run_stage_d`:

| chip family                                                                                           | module                        | identity                       |
| ----------------------------------------------------------------------------------------------------- | ----------------------------- | ------------------------------ |
| Black/White/Silver Border, Borderless                                                                 | `local_layout_class_cast`     | `layout-class-cast-v1`         |
| Old Border, Modern Border                                                                             | `local_attribute_chip_cast`   | `frame-style-cast-v1`          |
| appropriate-bleed                                                                                     | `local_bleed_calculator`      | `bleed-calculator-cast-v1`     |
| Extended, Showcase, Full Art, Etched, Old Border, Future Frame, Black/White/Silver Border, Borderless | `local_filename_declarations` | `filename-declaration-cast-v1` |
| Extended                                                                                              | `local_art_edge`              | `art-edge-continuity-v1`       |

The old single-signal bleed caster (`bleed-edge-cast-v1`, same module as
frame style, NEW 2026-07-30) is **RETIRED 2026-08-15**: it is the SOLE
machine channel that no longer runs, not a second channel alongside the
calculator — see the cross-checked section below for why running both would
defeat the calculator's abstention. Each surviving caster also has a
standalone `--write`-gated management command of the same name. Frame style
and bleed edge get **separate identities** because the bleed chip is
negative-only: under one shared identity a card's frame vote would read as
"handled" and permanently strand its bleed chip.

**Why this exists.** `local_fallback`'s three `cast_*_vote` functions were
reachable only from `local_identify_printing_tags.run_pilot` (which
FETCHES every image, and has one completed run in its history) and from
`image_evidence.extract_card_evidence`, which had **zero production
callers** — both engines call `compute_card_evidence`/`persist_evidence`
directly. So neither engine could cast any chip. After the 2026-07-29
purge, `Old Border`, `Modern Border` and `appropriate-bleed` sat at zero
machine rows with nothing able to re-derive them; border colour survived
only because `local_layout_class_cast` independently computes the same
thing. `extract_card_evidence` is now
`fetch_and_compute_card_evidence_for_tests`, named for what it is, and
casts nothing. The pilot's own casters are unchanged and still fire on a
pilot run; they are simply no longer the only path.

**Zero image fetches, and that is the point.** Every input is already
stored on `ImageEvidence`: `classify_frame_style` reads
`collector_line_collector_number` and `illus_anchor_fired`; the bleed
calculator reads `bleed_diff_mm` (Method A) and, where a canonical exists,
the pinline-ruler measurement (Method B). Re-deriving these through the
pilot would have meant re-fetching ~220,000 images to recompute facts
already in the database. Derivable populations, measured read-only
2026-07-29: `Modern Border` 133,627, `Old Border` 9,006,
`appropriate-bleed` 2,786 (the retired single-signal caster's figure; the
calculator covers the same population with a stricter abstention).

**The frame chip gates on `artist_ocr`, not only on `collector_line_ocr`.**
`illus_anchor_fired` is nullable and `bool(None)` is `False`, which is
indistinguishable from "the extractor ran and found no anchor" — so
without that gate every card missing `artist_ocr` would read `modern`.
That is a manufactured vote from evidence that does not exist, and it is
the same failure mode that lets a genuine old-frame card be vetoed
`frame-mismatch` in Stage D.

### A second, evidence-free channel: filename declarations (`local_filename_declarations`, 2026-08-19)

Proxy artists name their own renders, and those names routinely declare
the treatment ("Snapcaster Mage Extended.png"). `local_filename_declarations`
parses `Card.name` for those declarations and casts the matching chip vote
at `source=VoteSource.DEDUCTION` (pure inference from already-trusted
structured data, per that enum's own docstring — filename parsing inspects
no pixel) rather than `OCR`. Unlike every caster above it needs no
`ImageEvidence` row at all: the input is present and immutable from the
moment a card is created. A single card can cast several tags at once
(Extended and Borderless are not exclusive); the four border-colour tags
are the one mutually-exclusive axis and abstain as a group, recording
`border-axis-contradiction`, when a name declares more than one of them.

This channel never gates, skips, or is gated by any pixel-based
calculator above — the two kinds of evidence are read independently, and
their disagreement is itself useful: on the Extended chip, the stored
`ImageEvidence.art_edge_class` pixel classifier independently agrees with
the filename declaration 90.7% of the time (measured read-only against
production, 2026-08-19, 235,912 cards), so the remaining 9.3% is exactly
the population worth a human's attention rather than either channel's
alone. Measured population that same pass: 20,629 distinct cards across
109 sources declare a treatment this way, three chips (Full Art, Etched,
Future Frame) with no other machine coverage at all.

### A third channel, wired separately: extended-art continuity (`local_art_edge`, 2026-08-19)

`local_art_edge.run_art_edge_continuity_cast` casts the pre-existing
"Extended" chip from `ImageEvidence.art_edge_class`, a column Stage C's
evidence extraction already populates by comparing three regions of the
same image (the strip beside the art crop against two independent border
references — see `classify_art_edge_continuity`'s own docstring for the
geometry). The cast function itself fetches no image; it only reads that
already-stored column, the same "reads stored evidence, fetches nothing"
shape the four casters above share.

It is wired into a different dispatch step from the other four, though:
`stage_e_dispatch._run_evidence_only_calculators`, not
`_run_attribute_chip_casters` — it was added in a separate wiring pass
(2026-08-19), behind its own validation precondition (issue #721), after
the other four were already live.

Only the `extended` reading casts a vote (`VotePolarity.APPLY` on
"Extended", `source=VoteSource.OCR`, since the underlying classification
reads pixels even though the cast step itself does not); `framed` and
`mixed` abstain deliberately rather than casting a negative — a negative
vote from an unvalidated class would be a claim, not an abstention, and
`mixed` is by definition the reading this classifier is least sure of.
Validated against human votes on the pre-existing "Extended" chip: recall
87.0% (20/23), 0.0% false positives (0/10), precision 100% (20/20), n=33
cards / 5 voters, 0 disputed — corroborated at much larger scale by the
filename channel above, which independently agrees with this classifier
90.7% of the time over 13,117 cards.

### The bleed calculator: two independent methods, cross-checked (`local_bleed_calculator`)

The retired single-signal `bleed-edge-cast-v1` classified bleed from one signal - the image's own
aspect ratio against the two known reference ratios. `local_bleed_calculator` REPLACES it: it adds
a second, independent way to measure the same physical quantity and votes only when the two agree,
giving `appropriate-bleed` a single cross-checked machine channel rather than two parallel ones
that would double-count one signal (see the "Negative-only" paragraph below for why running both
would defeat the abstention).

**Method A - closed form from aspect ratio.** For symmetric bleed `b` on a 63x88mm card, the
image's own aspect `a = width/height` satisfies `a = (63 + 2b) / (88 + 2b)`, so `b = (88a - 63) / (2 - 2a)`. This is exactly `local_fallback.compute_bleed_diff_mm`'s own formula, already computed
and stored on every card's `ImageEvidence.bleed_diff_mm` at Stage C - this module reads that stored
value back into a bleed figure (`3.175mm - bleed_diff_mm`) rather than deriving the formula a
second time. It needs only the image's own pixel dimensions, so it applies to every card with a
fetched, non-degenerate image - no canonical, no metadata, no frame class. Its blind spot: it
assumes bleed is symmetric on all four edges, so it can't see an off-centre crop or one edge
trimmed more than another.

**Method B - the pinline ruler.** `local_pinline_inset.measure_pinline_inset` measures, per edge,
the distance from the image's own edge inward to the first sustained colour transition - on a
bordered card, that transition is the pinline where the printed border gives way to the card
frame, not the upload's own canvas boundary (see that module's own docstring for the colour-scan
mechanics and the two guards - the uniformity gate and the black-on-black abstention - that keep it
from mistaking a borderless card's artwork, or a black margin against a black border, for a
transition). Subtracting a calibrated trim-to-pinline constant (this module's
`CALIBRATED_PINLINE_INSET_MM`, keyed by the card's `border_color`/`frame` era from
`CanonicalPrintingMetadata`) from that pinline position yields a per-edge bleed. Because the
constant is keyed by frame era and border colour is only resolvable together with era on a
canonical-linked card, Method B is available on roughly a tenth of the catalogue - the cards with a
resolved canonical printing - not on every card the way Method A is. Its blind spot is the mirror
image of Method A's: a border printed thicker than the calibration expects reads as extra bleed,
because the scan cannot tell "long border" from "border, then more bleed."

**No pooled constant across frame eras.** A card whose border colour is known but whose era isn't
(the common case - both live on the same canonical-linked 10% of the catalogue) could in principle
use a constant pooled across eras for that colour. Measured: `black_2003`'s and `black_2015`'s
per-edge medians differ by 0.42-0.51mm on top/left/right - technically under the calibration's own
usability ceiling (~1.5mm spread), but 2-3x the ~0.24mm agreement floor every genuinely usable class
in the calibration table sits at. Pooling would spend most of Method B's whole reason for existing

- finer precision than Method A - on a case where the era-split constant is directly selectable
  instead. So no pooled entry exists: an unresolved or era-unknown card falls back to Method A alone.

**The abstain gate.** When both methods produce a number and they disagree by more than
`METHOD_DISAGREEMENT_ABSTAIN_THRESHOLD_MM` (2.0mm, a named constant, not a literal at either call
site), this module votes nothing and records `method-disagreement` instead of picking a side. The
two methods fail in different, uncorrelated ways - a thick border fools Method B but not Method A -
so a gap this large means at least one of them is wrong for this specific card, and the honest
output is "this needs a human," which is exactly what a machine vote on a SENSITIVE tag exists to
request, not to resolve. Measured cost, re-run against the 68-card catalogue geometry sample: 1
card triggered the gate.

**Confidence tiers, not a consensus-weight input.** `vote_consensus.resolve_vote_weight`'s own
docstring is explicit that a vote's weight comes from `source` (who cast it, by what method), never
from its self-reported `confidence` - so this module does not invent a number to express "the two
methods agreed." It reuses the same two-tier split `local_fallback.py` already draws for its own
multi-evidence-vs-single-evidence distinction: `FALLBACK_CONFIDENCE_MULTI_EVIDENCE` (0.8) when both
methods produced a number within the gate, `FALLBACK_CONFIDENCE_SINGLE_EVIDENCE` (0.7) when only
Method A was available (Method B unresolved, structurally abstained for borderless, or flagged
unusable for this card's specific frame/edge combination). The value is stored on the vote row, the
same as every other machine caster here - informational, not read by consensus weighting.

**Negative-only, same convention the retired `bleed-edge-cast-v1` followed**: a vote fires only
when this module's own reading agrees the card's Stage C `bleed_class` is `trimmed`,
`NOT_APPLICABLE` polarity, own identity `bleed-calculator-cast-v1` so it stays independently
purgeable/re-runnable and can never read a plain frame-chip vote as "handled" for its own
eligibility. Its reason for existing over the single-signal caster it replaces is narrow and
specific: withholding the vote on the ~1.5% of cases where Method B's independent, per-edge
geometry contradicts the aspect-ratio-only "trimmed" call past the gate. That abstention is why
`bleed-edge-cast-v1` was RETIRED rather than run alongside it — the old caster voted on exactly
those cards, so a concurrent pass would re-cast the very votes the calculator was built to
withhold. Zero image fetches - every input is already in the database.

### DPI-tag audit (2026-07-15, addendum item 8 - report only)

Live, read-only cross-reference of `Card.dpi` (computed once at import
time, `update_database.py`) against both places tag state lives -
`Card.tags` (resolved/baked) and `CardTagVote` (raw votes, including
anything pending a moderator co-sign) - for the `low-res` SENSITIVE tag
specifically. No votes cast, no code changed; report only, per the
addendum's own scope, and `low-res` itself stays untouched by this item
(distinct from `appropriate-bleed` above - see the "Future work" note
below for a follow-up idea that WOULD vote on it, deliberately deferred).

**Findings (218,152 cards, live 2026-07-15):**

| dpi bucket |  count | resolved `low-res` | pending vote | neither |
| ---------- | -----: | -----------------: | -----------: | ------: |
| 0 (unset)  |      4 |                  0 |            0 |       4 |
| 1-99       |      7 |                  0 |            0 |       7 |
| 100-149    |      9 |                  0 |            0 |       9 |
| 150-199    |      3 |                  0 |            0 |       3 |
| 200-299    |     40 |                  0 |            0 |      40 |
| 300+       | 218089 |                  0 |            0 |  218089 |

**Query mechanics sanity-checked before trusting an all-zero result**:
the same `resolved`/`pending` query pattern run against tags known to
have real production data - `NSFW` (339 resolved, via filename-bracket
import tagging, not the vote flow), and `custom-art`/`AI-Generated`/
`Borderless` (1, 1, 13 genuinely pending via the exact same
`tag_votes__tag__name=...` pattern used above) - all returned correct
nonzero counts. The `low-res` all-zero result is a real finding, not a
broken query.

Two things worth flagging, neither actionable within this item's scope:

- **99.97% of cards already report full 300dpi** - `Card.dpi` isn't a
  useful prioritization signal on its own; the sub-300 tail is 63 cards
  total across the whole catalog.
- **The `low-res` tag has never been used, anywhere, by anyone** - 0
  resolved, 0 pending, independent of dpi bucket. The report-flow
  (`CardReportReason.LOW_QUALITY` -> `low-res` `CardTagVote`,
  `sensitive_tags.REPORT_REASON_TO_TAG_NAME`) exists in code and has
  never actually been exercised in production. Not a bug - just means
  there's no existing signal to reconcile against yet, and any future
  automated low-res detection (see below) would be establishing this
  tag's first real usage, not correcting drift from manual reports.

**Future work: art-crop-specific DPI check + Scryfall comparison
(2026-07-15, flagged by owner during this item, deliberately deferred -
not built).** `Card.dpi` measures the FULL card image's resolution, which
this audit shows is essentially always fine (99.97% at 300dpi) - but a
proxy can have a perfectly fine full-image dpi while still having a
genuinely blurry/undersized ART specifically (upscaled source, a bad
crop-and-stretch, etc.), which `Card.dpi` can't see. Sketched design,
explicitly NOT built this pass:

- Reuse `local_phash.ART_CROP_BOX` (already the art-region fraction used
  for phash matching - one definition, not a second one) to crop the art
  region out of the pilot's own fetched image.
- Reuse the just-built `classify_bleed_edge` result to pick the correct
  physical reference height per card (trim 88mm vs. bleed-inclusive
  94.35mm - see the bleed-edge section above) before converting the
  crop's pixel height to a real DPI number, rather than assuming one.
- Cross-check against Scryfall's own official `art_crop` image for the
  same printing (`local_phash._fetch_scryfall_art_crop_url` already
  fetches this, reused not reinvented) as a second, comparative signal -
  independent of the absolute-DPI estimate, catches "much smaller than
  the official art for this exact card" even if the physical-mm math has
  slack in it.
- **This is additive, not a replacement for `Card.dpi`** - `Card.dpi`
  stays as the whole-image import-time measurement it already is; this
  would be a second, art-specific signal alongside it, for a different
  failure mode `Card.dpi` structurally can't catch.
- **Goes straight to the moderation pipeline when built** - `low-res` is
  `TagModerationClass.SENSITIVE` (same property established for
  `appropriate-bleed` above: a moderator co-sign is required to resolve
  either way, so a machine vote alone can't misuse it), so this would
  cast real `CardTagVote`s, not just report - unlike this item's
  DB-audit scope, which deliberately doesn't.
- Deferred rather than built now because it needs its own validation
  pass (a real sample, Scryfall-vs-source comparison, a derived
  threshold with a safety margin - the same discipline every other
  detector in this pilot got) before casting anything real, and this
  item's own scope was report-only.

### Bleed-first crop normalization (2026-07-15, owner-directed, folded into item 3d)

**Owner's question mid-item-8**: since bleed classification is cheap and
purely geometric, should it run FIRST, ahead of everything else, so its
result can normalize every OTHER fixed-fraction crop box in the pipeline?
Investigated rather than assumed: `local_ocr.DEFAULT_CROP_BOX`,
`local_phash.ART_CROP_BOX`, `local_fallback.ARTIST_CROP_BOX`,
`local_fallback.SYMBOL_STRIP_BOX`, and `local_fallback._BORDER_SAMPLE_BANDS`
are all fixed-fraction boxes empirically tuned against real fetched images -
which are ~97.5% bleed-inclusive (the 40-source bleed sample above). That
means they're already correctly calibrated for the bleed-inclusive
majority; the ~2.5% TRIMMED minority is the one case where a box tuned
against a bleed-inclusive image lands in the wrong place, since removing
the bleed margin shifts where the same physical card position falls as a
fraction of the (now smaller) full image.

**`local_fallback.normalize_crop_box(box, bleed_class)`**: a no-op for
`'bleed'` or `None` (abstain); for `'trimmed'`, rescales each fraction by
the same margin-fraction math derived from the bleed-edge section's own
reference geometry (`_WIDTH_MARGIN_FRACTION = 3.175 / 69.35 ≈ 4.58%`,
`_HEIGHT_MARGIN_FRACTION = 3.175 / 94.35 ≈ 3.37%` per edge). Threaded
through all five crop sites via a new `bleed_class` parameter on
`classify_border_color`, `detect_illus_anchor`, `find_symbol_matches`,
`run_ocr_for_card`, and `local_phash.compute_card_art_hash`.

**The border-sample bands got a real empirical check, not just the
derivation, before being included** - their sample position sits close to
where the bleed margin lives (0.03-0.05 fraction from each edge, inside
the ~3.4-4.6% margin), which could in principle mean the EXISTING
(unmodified) bands were already misreading bleed-inclusive images, not
just needing a trimmed-image fix. Sampled 15 real bleed-classified cards
with and without the remap applied: solid-color borders (the common case,
most sources) read IDENTICAL RGB regardless of exact sample position -
border color extends uniformly through the bleed margin in real print
prep. Confirms the existing bands are correct for the majority as-is, and
normalizing is safe to apply unconditionally (a no-op there anyway, since
it only activates for `'trimmed'`).

`run_pilot`'s per-card processing now classifies bleed FIRST (before
OCR/phash/border/frame/symbol/artist), immediately after image fetch -
see `_compute_card`'s docstring.

### Pipeline concurrency (2026-07-15, pre-scale program item 3d)

**Measured the real constraint before designing anything**: this box has
2 CPU cores total, shared with 5 live production containers (Django,
worker, nginx, Postgres, Elasticsearch) - not an abstract "how many
threads" question, a genuine resource-contention one. Also found (while
setting up the measurement) that `mpcautofill_django` doesn't have
tesseract installed at all - confirms the real pilot run's host-venv
execution path is the ONLY one that currently works, not just how it
happened to be run (relevant to item 4's install-path decision).

**Live-contention test, not a synthetic benchmark**: 10 real candidate
cards, dry, fetch+OCR+phash only, run against the live production DB
while a separate probe hit the live API's `2/languages/` endpoint
locally (bypassing Cloudflare) every ~0.3s, comparing latency across
three conditions:

| condition                     | mean latency | p95 latency | wall clock (10 cards) |
| ----------------------------- | -----------: | ----------: | --------------------: |
| idle (no pilot load)          |       79.8ms |      94.7ms |                     - |
| sequential (today's behavior) |       88.7ms |     126.1ms |                13.42s |
| 2-worker concurrent           |       93.9ms |     135.7ms |                 6.34s |

Only ~5ms extra mean latency for 2 workers over the ALREADY-EXISTING
single-threaded impact, for a near-ideal ~2.1x wall-clock speedup
matching the core count exactly - tesseract's subprocess-based OCR
genuinely parallelizes here (the GIL releases during the subprocess
wait). `DEFAULT_WORKERS = 2` adopted as the new default.

**Design: split compute from writes, not a full concurrent rewrite.**
`_compute_card` (new) does the parallelizable half - fetch, bleed
classification (first), OCR, phash, border/frame classification, pass-2
fallback - as a pure function with no DB writes and no shared/nonlocal
state, safe to run via `ThreadPoolExecutor.map()` (which preserves
submission order in its results regardless of completion order).
`run_pilot`'s own loop - votes_batch/tag_votes_batch staging,
disagreement bookkeeping, the ground-truth-preferred attribute override,
the frame-mismatch consistency check, flush/gate-check - stays
single-threaded and in selection order, completely UNCHANGED from
before this split; only where its input comes from changed. Chunked at
`batch_size` granularity (reusing checkpointing's existing boundary,
item 2) rather than a second batching concept - each chunk's compute
pool completes before that chunk's writes are staged and flushed.

`OMP_THREAD_LIMIT=1` set (via `os.environ.setdefault`, respects an
operator's own override) whenever `workers > 1` - without it, N
concurrent tesseract subprocesses could each ALSO try to multi-thread
themselves internally, oversubscribing this box's 2 real cores well
beyond `workers`.

**Fetch budget is now checked between chunks, not per-card** - a chunk
already in flight always completes once started, so the real bound on
an overshoot is one chunk's worth of fetches (`<= batch_size`), not
zero. Consistent with the belt-and-suspenders framing already
established for `--fetch-budget` (item 3b) - the real enforcement is the
Worker's own `IMAGE_FULL_TIER_RATE_LIMITER`, not this counter.

**A real threading bug found and fixed while writing the tests, not
just a design risk avoided in the abstract**: `run_fallback_for_card`'s
own `CanonicalCard.objects.filter(...)` query, executed from a worker
thread, silently returned empty under pytest-django's default
(non-transactional) `db` fixture - a worker thread opens its own DB
connection, which can't see an uncommitted test transaction only the
original connection is inside. Exact same root cause and fix
(`transactional_db`, real commits, TRUNCATE-based cleanup) as
`test_sources.py`'s pre-existing `test_all_sources_scanned_concurrently_local_file`
for `update_database()`'s own worker threads - this is a known, already-
established pattern in this codebase, not a new problem. Not a
production concern (committed data is visible across connections/threads
fine); a test-fixture-only issue, but a real one - the failing assertion
caught it, not a code review guess. New `TestConcurrency` test class
(`transactional_db`-based) validates workers>1 finds a real cross-thread
DB match, workers=1 and workers=4 agree on the same input, and
`OMP_THREAD_LIMIT` is set/unset correctly.

`--workers` CLI flag added (default `DEFAULT_WORKERS = 2`, `--workers=1`
disables concurrency entirely).

### Re-projected full-catalog wall-clock (2026-07-15, pre-scale program item 3e)

**Explicit correction from the owner, applied here**: the original
projection couldn't reuse item 3a's phase-timing numbers unmodified -
those were measured against NATIVE-resolution fetches, and `--fetch-dpi`
didn't exist yet. Re-measured directly rather than assumed:

- **Fetch latency at the real default (`dpi=250`)**: 20 real direct
  fetches against the live CDN Worker, mean **0.509s** (vs. item 3a's
  native-resolution mean of 1.187s - a real, not assumed, 57% reduction).
- **Full per-card compute cost** (fetch + bleed-first + OCR + phash +
  border/frame + pass-2 fallback, everything `_compute_card` does) on 15
  real candidate cards: **2.520s/card sequential, 1.568s/card at
  2 workers (1.61x speedup)** - notably LOWER than the 2.1x seen in item
  3d's own narrower fetch+OCR+phash-only benchmark, because
  `detect_illus_anchor` and pass-2 fallback (item 3a's two LARGEST cost
  components, 33% and 23.2% respectively) also make their own DB queries
  and tesseract calls, which don't parallelize quite as cleanly as pure
  fetch+OCR+phash did. **1.61x, not 2.1x, is the correct real figure for
  a full-catalog projection** - flagging this discrepancy explicitly
  rather than letting the earlier item-3d number stand uncorrected.
- **A real 300-card (`--limit 300`, 392 candidates processed - both
  engines' selections union) dry-run** at the CURRENT code (dpi=250,
  bleed-first, crop-tightened, 2 workers), timed end-to-end via the
  actual management command: **12m10s / 392 = 1.863s/card** for
  compute + the frame-mismatch consistency check + ground-truth-metadata
  lookup (dry-run skips `bulk_create`/the gate check entirely - can't
  measure that component this way). A genuine write-enabled run was
  attempted first and correctly blocked by the auto-mode classifier -
  HOLD #2 gates scaled DB-writing runs, and a fresh 300-card write wasn't
  pre-cleared for this specific measurement; pivoted to `--dry-run`
  instead, which still exercises real fetch/compute/consistency-check
  cost.

**Reconciling the three measurements**: `1.863 - 1.568 = 0.295s/card` is
the consistency-check + ground-truth-lookup overhead alone, at 2 workers

- and since that portion runs single-threaded in the main loop
  regardless of `workers` (only the compute half is parallelized), it's a
  `workers`-invariant constant. The one component with NO fresh
  measurement is `bulk_create`/`verify_zero_resolutions`'s gate-check cost
  (write-path code, untouched by items 3b/3c/3d) - reusing item 3a's own
  residual (old real total 6.42s/card minus old compute-only 4.46s/card
  minus this same 0.295s/card consistency-check estimate = **~1.665s/card**
  inferred write-path cost). Two independently-derived estimates cross-
  validate within 0.1%:

| projection            | compute | consistency-check | write-path (inferred) |  total |
| --------------------- | ------: | ----------------: | --------------------: | -----: |
| single-threaded (now) |  2.520s |            0.295s |                1.665s | 4.480s |
| 2 workers (now)       |  1.568s |            0.295s |                1.665s | 3.528s |
| single-threaded (OLD) |      -- |                -- |                    -- |  6.42s |

**Full-catalog projection** (171,853 cards - the live union of both
engines' eligible pools, fresh count 2026-07-15, up from the ~171,878
figure quoted earlier in this doc - natural drift as votes accumulate):

| scenario                                  |    s/card |    wall clock |
| ----------------------------------------- | --------: | ------------: |
| OLD (native fetch, single-threaded)       |     6.42s |    ~12.8 days |
| NEW (dpi=250+bleed+crop, single-threaded) |     4.48s |     ~8.9 days |
| **NEW (dpi=250+bleed+crop, 2 workers)**   | **3.53s** | **~7.0 days** |

**~45% wall-clock reduction from items 3b/3c/3d combined** (12.8 → 7.0
days) - real, substantial, and cross-validated by two independent
derivations. **Still a full week of continuous host-process runtime** -
this is the single most consequential number for item 4's scheduling
decision (chunked scheduler slices vs. one continuous screen'd process):
a naive one-shot week-long run on a box that also serves live production
traffic is a real operational risk regardless of `--nice` throttling
(no natural checkpoint against an OS update, a reboot, a multi-hour
network blip - though item 2's checkpointing does bound how much work
any single interruption loses). The one inferred (not freshly
re-measured) component - write-path cost - should be validated with a
real, HOLD #2-cleared write run before this projection is treated as
final; the write-path code itself is unchanged by any of this session's
work, so reusing the old measurement is a reasonable but not yet
re-confirmed assumption.

### Phash yield investigation (2026-07-15, pre-scale program item 4)

**A wrong hypothesis, tested and rejected before it reached this doc.**
The item 3e dry-run showed phash yield collapse to 0/300 (0%), down from
the baseline run's 13/300 (4.3%) - and the skip-count redistribution
looked suspiciously exact (13 fewer votes, +8 `no-clear-winner`,
+5 `too-many-candidates`, exactly 13). The obvious suspect: `--fetch-dpi =250` was only ever validated against OCR yield (item 6/3c's sweep
explicitly used "the production OCR pipeline" at each dpi) - never
against phash, which hashes the SAME fetched image. **Tested directly
rather than trusted the correlation**: computed phash match outcomes at
native vs. `dpi=250` resolution for 12 real current-pool multi-candidate
cards - **zero difference in outcome on any of them**. The dpi
hypothesis is rejected.

More likely explanation: the candidate POOL itself shifted between the
two runs - the baseline run wrote 94 real votes (including 13 phash
matches), which are now excluded from selection (idempotence), so the
"next 300" cards by the selection ordering are a genuinely different
set than the original 300. Phash's yield is small enough (4.3% at best)
that which specific 300 cards happen to be sampled plausibly explains
more of the swing than any code change does. Not fully resolved - flagged
honestly as unexplained sample volatility, not asserted as a solved
mystery.

**Verdict: keep phash as-is, no further tuning.** Real but small
contribution (13/300 in the one sample with a nonzero count), zero
false-positive risk (the distance+margin gate is strict - a wrong-but-
confident vote has never been observed), and negligible cost (item 3a:
0.011s/card, 0.2% of total time) - there's no strong case for either
investing more tuning effort or dropping it. Its abstention rate is
simply the honest floor for this signal at pilot scale.

### Scaling proposal + install path (2026-07-15, pre-scale program item 4)

**The real constraint driving this decision**: item 3e's ~7.0-day
(2 workers) / ~8.9-day (single-threaded) full-catalog projection is a
multi-day-to-week continuous workload on a box that also serves live
production traffic. Two scheduling shapes were compared, not assumed -
checked against what actually exists in this codebase before proposing
anything new.

**A real, load-bearing tension found while checking, not assumed away**:
django-q2 infrastructure already exists here (`Q_CLUSTER` in
`settings.py`, an already-running `mpcautofill_worker` container whose
entire job is `python3 manage.py qcluster`, an existing daily
`update_database` schedule seeded via migrations `0043`/`0048`). Its
`Q_CLUSTER` config sets `cpu_affinity: 1` - a deliberate reservation
(alongside `timeout: 12 hours, "extreme upper limit"`) that reads as
intentionally protecting this box's OTHER core for live traffic, not an
arbitrary default. **That directly conflicts with item 3d's validated
`--workers=2` default** - scheduling the pilot through the EXISTING
cluster would effectively cap it at 1 core, meaning the real achievable
rate under that path is the ~8.9-day single-threaded projection, not the
~7.0-day one, unless a second, dedicated cluster/queue with different
affinity is stood up specifically for this workload (more infrastructure
complexity, not evaluated further here - the addendum's own scope is
"a decision," not a second scheduler).

**Option A - screen'd host process, `--workers=2` (recommended)**:

- Works TODAY with zero infrastructure changes - tesseract is already
  installed on the host (`/usr/bin/tesseract`, confirmed while measuring
  item 3d), and the host venv used for every real run in this session
  already proves the path works against the live DB.
- Gets the full validated ~7.0-day projection - the only option that
  does, since it isn't constrained by the existing cluster's
  `cpu_affinity=1`.
- No new Dockerfile/image rebuild, no new `Schedule`/queue
  infrastructure to build and validate.
- **Real gap, not glossed over**: the live-latency-contention
  measurement (item 3d) that justified `--workers=2` as safe was a
  10-card, ~20-second burst test - it validates "briefly safe," not
  "safe sustained for a full week." A longer soak measurement (a few
  hours, not 20 seconds) against live traffic latency is a reasonable
  ask before actually launching a multi-day run, and is flagged here as
  a residual open item for the HOLD #2 package, not resolved by this
  proposal.
- Lifecycle is manual (`screen`, not django-q's built-in retry/crash
  handling) - partially mitigated by item 2's checkpointing (a kill
  loses at most one `--batch-size` worth of unflushed work and resumes
  cleanly on restart), but still needs a human or a `cron` re-invocation
  after a real crash, not automatic retry.

**Option B - chunked django-q nightly slices, existing cluster**:

- Reuses established, already-working infrastructure - the exact
  `Schedule.objects.create(func="django.core.management.call_command", args="'local_identify_printing_tags', '--limit', 'N', ...", schedule_type="D")` pattern already seeds `update_database`/
  `import_canonical_card_data` today (migrations `0043`/`0048`) - a new
  migration doing the same for this command is a small, low-risk,
  precedented change.
- Gets django-q's existing retry/crash-recovery machinery for free.
- **Requires a Dockerfile change**: `mpcautofill_worker` builds from the
  same `docker/django/Dockerfile` `builder` stage as `mpcautofill_django`
  (confirmed by reading it) - neither has tesseract; adding
  `tesseract-ocr` to that stage's `apt-get install` line and rebuilding
  both images is a real, concrete requirement, not a formality.
- Bound by `cpu_affinity=1` unless a second cluster is built (see
  above) - realistically the ~8.9-day single-threaded rate, spread
  across many nights at whatever `--limit` fits comfortably inside a
  night's window (well under the cluster's 12-hour task timeout, to
  leave real margin - a nightly `--limit` sized for ~2-4 hours, not 12,
  is the safer target).

**Recommendation: Option A for the eventual full-catalog run** - it's
faster, needs no new infrastructure, and the pilot's own checkpointing
already covers most of what django-q's retry machinery would otherwise
buy. Revisit Option B only if the longer soak-test flagged above turns
up a real sustained-load problem Option A can't tolerate.

**Host-venv disposition - a real, currently-open gap**: every real run
in this session used
`/home/ubuntu/.claude/jobs/4495614d/tmp/venv` - a job-scoped path that
is cleaned up when this Claude Code job ends. Whichever option is
eventually chosen, a permanent venv needs to live somewhere stable and
documented (`docs/infrastructure.md`) before an unattended host-process
run is launched for real - this doesn't block anything in this pre-scale
program itself (every measurement in this doc was already real, run
against the live DB), but it's a genuine loose end for whoever actually
launches the full-catalog run.

### Dockerized execution, host-venv retired (2026-07-15, closes the item 4 gap above)

Closes the "host-venv disposition" gap flagged in the scaling proposal
above: `docker/django/Dockerfile`'s shared `builder` stage now installs
`tesseract-ocr tesseract-ocr-eng` alongside the existing
`dos2unix gcc netcat-traditional curl libpq-dev` line - both the
`webserver` and `worker` targets inherit it since they both `FROM builder`. Verified end-to-end, not just "image builds": rebuilt the
`worker` image and ran
`python3 manage.py local_identify_printing_tags --dry-run --limit 3 --skip-checks`
inside a one-off `docker compose run --rm worker ...` container against
the real live DB - tesseract resolved (`/usr/bin/tesseract`, v5.5.0),
OCR/phash/fallback/attribute voting all executed and reported real
(dry-run) output. The job-scoped host venv
(`~/.claude/jobs/4495614d/tmp/venv`) used for every prior measurement in
this doc is now retired - no job dependency for this recurring task
lives outside the image anymore.

Build-context note: `docker/django/check_client_secrets.sh` and
`check_drives.sh` require `MPCAutofill/client_secrets.json` and
`MPCAutofill/drives.csv` to exist in the build context (both gitignored,
real content only on-disk per `CLAUDE.md`) - a fresh worktree doesn't
have them by default, since worktrees share git history but not
untracked files. Verifying this Dockerfile change from a worktree
required temporarily copying those two files plus `docker/.env` (needed
at container-run time for `SECRET_KEY`/DB config) in from the main
checkout, with explicit user go-ahead for each, and deleting all three
immediately after the verification container run completed. This is a
one-time verification cost, not a recurring one - normal builds/deploys
happen from the main checkout, where these files already live natively.

This does not change the Option A vs. B scheduling recommendation above
(still Option A, screen'd host process) - it only changes _how_ the
command executes (containerized instead of a host venv) once a
scheduling shape is chosen, and removes one of Option B's stated
requirements ("Dockerfile change...adding `tesseract-ocr`") since that
part is now already done regardless of which scheduling path is picked.

### Coverage-gap + demand ordering, skip-before-fetch (2026-07-15, addendum items 1/3/4)

Full respecification from the owner, superseding the earlier AskUserQuestion-confirmed
interpretations - implemented verbatim, not re-derived.

**Item 1 - coverage-gap prioritization**: `select_candidates`'s ordering is now a full 5-key
tuple, REPLACING the old "multi-candidate names first" primary split entirely (that split is now
only tiebreak #4, "fewer candidates"): (1) names with zero covered printings first, (2)
descending count of uncovered printings, (3) demand rank (item 3), (4) fewer candidates, (5) pk.
"Covered" (`compute_covered_printing_pks`): a printing has >=1 `Card` with `canonical_card`
pointing at it (a confirmed indexing match, no RESOLVED gate needed - already a direct,
non-vote-based signal) OR `inferred_canonical_card` pointing at it with
`printing_tag_status=RESOLVED` - gated on RESOLVED specifically so a machine vote pending human
confirmation does NOT count as coverage, per the owner's explicit clarification. Computed fresh
on every `run_pilot` call (never cached across invocations), so a nightly slice's ordering
reflects human confirmations made in the queue since the previous slice. Fully-covered names
still process, just LAST - redundant identifications add real value (image choice per printing,
coverage-independent border/frame attribute votes). New report metric,
`AttributeReport.uncovered_printings_closed`: of the printings in scope this run that were
uncovered at the start, how many are covered by the end - the run's real progress metric per the
owner ("that number, not raw votes"). Almost always 0 for a machine-only run BY DESIGN, not a
bug: a pilot vote is never a direct resolve (the gate check asserts this structurally), and
"covered" explicitly excludes unresolved machine votes - a printing only counts as closed once a
human confirms it in the queue, which is what item 5 (follow-up) is for.

**Item 3 - demand order via `edhrec_rank`**: already existed as a schema field
(`CanonicalPrintingMetadata.edhrec_rank`, populated by the existing `printing_metadata_import`
Scryfall bulk-data import) - checked live before assuming it needed adding: 101,133/113,224 rows
(89.3%) genuinely populated. `CandidatePrinting` now carries `edhrec_rank` (fetched via
`CandidateNameIndex`'s existing single query, `select_related("printing_metadata")` - zero extra
queries). A name's demand rank is the MINIMUM `edhrec_rank` across its candidates (its most
popular printing, not an average) - missing ranks (~10.7% of rows) sort LAST via a large
sentinel, not first, so "no demand signal" never masquerades as highest-priority. Public Scryfall
data, zero user tracking - explicitly the zero-telemetry-policy-clean substitute for a previously
-parked export-popularity-ordering idea.

**Item 4 - skip-before-fetch**: `RESOLUTION_FLOOR_DPI = 200` (the actual empirical floor from the
6-way dpi sweep above - NOT `DEFAULT_FETCH_DPI = 250`, which is a safety margin above it) applied
against `Card.dpi` (computed once at catalog-import time from the source image's own pixel
height) directly in `select_candidates`' selection query (`.exclude(dpi__lt=...)`) - a source
image already below the floor is never fetched at all, not just never OCR'd. `Card.size` (raw
file bytes) is deliberately NOT used as a second condition despite the addendum's "dpi/size"
phrasing: it's a compression-dependent proxy with no empirical calibration behind it, unlike
dpi's direct, validated sweep - an unvalidated byte threshold would violate this pilot's own
"measure, don't assume" discipline. New `PilotResult.skipped_below_resolution_floor` counter
(`count_below_resolution_floor`, a separate COUNT query, cheap at full-catalog scale) - its own
report line, not folded into the existing `skip_counts` dict (which is populated downstream of a
fetch attempt; a selection-time skip never reaches that loop).

Sequencing note (owner-directed): items 3/4/1 ship together with item 2a (cluster dedup, no
schema change) as one PR. Item 2b (persisting `content_hash` for federation) and item 5
(questionFeed ordering mirror) are deferred, logged as follow-ups, not built here.

Verified: 82/82 pilot tests pass (15 new: `TestCoveragePriority`, `TestDemandRank`,
`TestResolutionFloor`, `TestUncoveredPrintingsClosed`), including a coverage-tier test that
specifically distinguishes "zero-covered" from "most uncovered" (a partially-covered name with
MORE absolute uncovered printings than a zero-covered name must still sort after it) and an
`inferred_canonical_card`-without-`RESOLVED` test (confirms an unconfirmed machine vote doesn't
count as coverage). mypy clean (`MPCAutofill/`, whole-package invocation). `black`/`prettier`
clean.

### Cluster dedup, run-scoped (2026-07-15, addendum item 2a)

Before slicing, `compute_own_image_clusters` phashes OUR OWN eligible images (local only - no
candidate/Scryfall downloads) via the same `local_phash.compute_card_art_hash` the phash engine
already uses, and collapses distance-0 (EXACT 64-bit hash match) groups to one representative
(lowest pk, for determinism) - only representatives reach `_compute_card`; absorbed members never
run their own OCR/phash/border/frame/fallback at all. "One read answers N cards": an accepted
vote on the representative propagates as an identical `CardPrintingTag` (same anonymous*id,
printing, confidence, source) to every absorbed member. Sound by construction: a distance-0 match
among OUR OWN uploaded images most plausibly means a duplicate/shared-source image, not
independent depictions that coincidentally look alike (that's the \_candidate* art-crop clustering
problem the phash engine already handles separately via `DEFAULT_DISTANCE_THRESHOLD=20`, a much
looser bar than 0) - identical image genuinely entails identical printing. Costs one extra fetch
per selected card (the clustering pass itself) to save the far more expensive per-card compute
pipeline on every absorbed duplicate.

Scoped to the printing-identification vote only, not border/frame/bleed attribute votes -
absorbed members never get their own image classified, so there's nothing of theirs to
propagate for those; a documented limitation, not a silent gap. Run-scoped only, no schema
change: no `content_hash` persisted anywhere (that's item 2b, deferred as a standalone future
task for federation-v1's content_hash groundwork). New `AttributeReport.cluster_count`/
`cards_absorbed_into_clusters` report fields.

**A real idempotence gap found and fixed before landing, not just anticipated**: a cluster
member can reach clustering via one engine's independent eligibility (e.g. phash) while already
carrying a vote from a DIFFERENT engine's `anonymous_id` from a prior invocation (the exact
reason it was excluded from that OTHER engine's selection this run). Propagating a same-
`anonymous_id` vote to it anyway would violate `CardPrintingTag`'s own
`(card, printing, anonymous_id)` uniqueness constraint - checked once per run (a single query
across all cluster members, not re-queried per propagation call) and skipped, not attempted.
`ocr_selected_ids`/`phash_selected_ids` also get absorbed into the representative's own
eligibility (a representative must run an engine if EITHER it or any absorbed member was
independently selected for that engine), so clustering can't silently drop an engine's
eligibility just because the specific card that became the representative wasn't itself
originally selected for it.

Verified: 96/96 pilot tests pass (7 new: `TestClusterDedup`), including a test that caught a
genuine test-fixture bug during development (two different solid-color images accidentally
hashed identically - imagehash's DCT-based `phash` has zero frequency content on any uniform
fill regardless of color, so distinguishable synthetic fixtures need actual drawn shapes, not
just a different fill color; the production clustering logic was working correctly the whole
time), a test proving the double-vote/overwrite gap above is actually fixed (not just that some
vote exists), and a test proving the efficiency win itself (an absorbed member's card id is
never passed to `run_ocr_for_card`, not just that it ends up with a vote). mypy clean.
`black`/`prettier` clean.

### Bottleneck split, current pipeline state (2026-07-16, throughput track item 2a)

Re-measured phase timing against the CURRENT code (post items 1/2a/3/4/4b) rather than trusting
item 3a's original breakdown, which predates dpi=250, crop tightening, bleed-first
classification, and clustering entirely. Real instrumented run, 50 selected candidates
(representative-only, post-clustering), against the live DB/API - not simulated:

| phase                                 | mean/card | share (uncorrected) |
| ------------------------------------- | --------: | ------------------: |
| `fetch_card_image`                    |    0.450s |               13.4% |
| `classify_bleed_edge`                 |   ~0.000s |               ~0.0% |
| OCR (crop+preprocess+tesseract)       |    0.478s |               14.3% |
| phash (hash+compare)                  |   ~0.000s |               ~0.0% |
| border/frame (`detect_illus_anchor`+) |    1.206s |               36.0% |
| pass-2 fallback                       |    1.218s |               36.3% |

**Measurement caveat, stated plainly**: this run called fallback unconditionally for every
representative (not gated on pass-1's real accept/reject outcome), so its 36.3% share is
inflated relative to real `run_pilot` behavior (item 3a's original sample: fallback fires
~70% of the time). Corrected estimate using that same 70% rate:
`0.450 + 0.478 + 1.206 + (1.218 × 0.7) ≈ 2.99s/card` sequential, for cards that reach full
compute (clustering representatives only).

**Bonus real data point from the same sample**: 13/50 selected cards (26%) were absorbed into
10 clusters by item 2a's dedup - a materially higher rate than assumed, though from one
50-card sample, not a claim about the full-catalog rate.

**The clear finding: this is CPU-bound, not I/O-bound.** `fetch_card_image` is ~13% of
per-card cost; `detect_illus_anchor`-plus-border-classification and pass-2 fallback together
are ~72% (uncorrected) / ~65% (corrected). This directly answers throughput track item 2a's own
question: **the "6-8 fetch threads, I/O-bound, no core needed" idea does not currently exist as
a mechanism** - `_compute_card`'s single `ThreadPoolExecutor(max_workers=workers)` runs fetch
AND OCR AND phash AND fallback all in the SAME worker, sized for CPU-bound work
(`DEFAULT_WORKERS=2`, matching this box's core count). Decoupling fetch into its own larger pool
would only ever attack the ~13% fetch share - a real potential improvement, but not the
dominant cost, and not built in this pass. This bottleneck split is the evidence that makes
manifest mode (item 2c) and a core-count resize (item 2b) the higher-leverage levers, not a
larger fetch pool.

**Current instance shape** (checked via the cloud provider's own instance-metadata endpoint,
no auth needed - exact shape/region kept out of this public doc, see CLAUDE.local.md/journal
for the specific values): core count matches `DEFAULT_WORKERS=2`'s own derivation (item 3d)
exactly - this box has never had spare cores for a bigger pool without a resize.

### Soak test at the current box, PRE-RESIZE baseline (2026-07-16, throughput track item 2d)

**This measurement is at the box's PRE-RESIZE core count (`--workers 2`) - it is the pre-resize
baseline, NOT the workers=3 post-resize number the resize decision is waiting on.** A separate
post-resize soak test (same 250-card window, same selection/dedup) at a higher `--workers` count
on the resized shape is required before comparing - see the entry below once that lands. Do not
conflate the two numbers. (Exact shape/OCPU/RAM values kept out of this public doc - see
CLAUDE.local.md/journal.)

Real 250-card `--dry-run --workers 2` run (not a burst - the prior `--workers=2` safety
validation was only ~20 seconds/10 cards) against the live DB/API with live services running
normally. Clustering (item 2a) absorbed 70/250 selected candidates (28%) into 59 clusters before
the main loop even started, leaving 180 representatives actually processed - closely matching
the bottleneck-split sample's independently-observed 26% (13/50) absorption rate, two samples
now agreeing rather than one small anecdote. Total wall-clock ~400s (00:16:10 start to 00:22:50
log-file mtime), including container startup/migrate/collectstatic overhead (~45-60s fixed cost,
not pilot processing) - effective throughput **≈1.94s/card** across the 180 processed
representatives, consistent with the previously-established top-down 1.863s/card figure from
the original 392-candidate real run. **Caveat, stated plainly**: this run's progress markers
(50/100/150-candidate checkpoints) weren't individually timestamped, so this confirms
AGGREGATE throughput held up over a real multi-hundred-card window (not just a burst) but
doesn't give intra-run stability granularity (e.g. whether the first 50 cards processed at a
different rate than the last 50) - a finer-grained timing pass would be needed for that
specific claim, not done here.

### Token exclusion + post-resize soak comparison (2026-07-16)

**A real correctness gap found and fixed before trusting any throughput number from this
window**: the first several 250-card soak-test runs at both pre- and post-resize core counts
showed 0/250 OCR votes - a stark regression from the original 94/300 baseline. Diagnosed live
by sampling real OCR output against real candidates for the first 8 selected cards: all 8 were
generic "Beast" tokens (source-uploaded images with `card_type=TOKEN`) with ~90 candidate
printings each across token-only sets. A token's printed collector line reads its PARENT set's
code (e.g. "MM3"), while its `CanonicalCard` candidates use token-specific set codes (e.g.
"tm3c") that never match - structural, not a parsing bug. Item 1's "descending uncovered count"
ordering was front-loading this near-0%-matchable cohort (huge candidate counts, near-zero
coverage) to the very front of every real selection. Fixed: `_eligible_base_queryset` now
filters to `card_type=CARD` only (excludes tokens and cardbacks) - confirmed via a fresh
eligible-pool count, 172,494 cards (the pilot's own real filtered count, not a naive
unfiltered query). Future work (not built): a token-aware matching path using Scryfall's own
token detection to search collector info or the set icon instead of the parent-set text tokens
don't reliably print.

**Corrected before/after comparison**, same 250-card window, re-run after the fix - OCR yield
now healthy and consistent at both core counts (56/198 votes, 28.3%, matching the original
94/300 baseline):

| config (pre-resize vs. post-resize core count) | wall-clock | processing-only rate |
| ---------------------------------------------- | ---------: | -------------------: |
| lower core count (`--workers 2`)               |       456s |          2.051s/card |
| higher core count (`--workers 7`)              |       230s |          0.914s/card |

**Speedup: 2.24x** (up from an earlier token-contaminated measurement's 2.03x - the sequential
clustering pre-pass, still unparallelized, see below, is a smaller share of a longer, more
representative run). Full-catalog re-projection (172,494 eligible pool):

|                   |   raw (naive) | cluster-dedup-adjusted (incl. ~21.6h sequential clustering pre-pass) |
| ----------------- | ------------: | -------------------------------------------------------------------: |
| lower core count  |     4.09 days |                                                            4.14 days |
| higher core count | **1.82 days** |                                                        **2.34 days** |

The sequential clustering pre-pass (`compute_own_image_clusters`, confirmed via code inspection
AND a live `docker stats` capture showing a single-core-only ~100% CPU plateau during that
phase) is ~21.6h fixed regardless of core count - ~38% of total time at the higher core count.
Parallelizing that one loop (flagged as a follow-up, not built) remains the highest-leverage
lever to push below ~2.3 days. Verified via direct `docker stats` sampling (not just aggregate
system `top`) that the compute phase itself DOES achieve real multi-core parallelism (a peak of
~625% CPU observed, consistent with most of a 7-worker pool active simultaneously) once past the
pre-pass - an earlier read of aggregate `top` data alone had incorrectly suggested a GIL-bound
compute phase; the direct per-process measurement corrected that.

### No-match autopsy (2026-07-15, post-merge Hold #1 of the pre-scale program)

Classified all 176 OCR "parsed-but-no-match" cases from the pilot run
(reconstructed via selection-order stability, since the CLI doesn't
persist per-card raw text - a real gap, see the journal). Two real,
contained parser bugs found, both now fixed in `local_ocr.py`:

- **Set-code token position**: `parse_collector_line`'s set-code search
  took the FIRST plausible 3-5 char token in the line, which is virtually
  always leading noise (a watermark, a rarity-letter glyph merging with a
  stray digit into something code-shaped) rather than the real set code
  that always follows the collector number in a genuine card layout. Fixed
  to search the text AFTER the number first, falling back to before only
  if nothing plausible follows.
- **Collector-number leading zeros**: OCR frequently reads a spurious
  leading zero ("0093" for a real "93") that literal string comparison
  silently rejected. Fixed via `_normalize_collector_number` (strip
  leading zeros, keep any trailing variant letter) applied symmetrically
  to both the parsed reading and every candidate's stored value.

**Yield delta, precisely measured** (re-parsing the exact same 176 raw
texts with both the old and new logic, isolating exactly this cohort from
the 3 cards that already matched under the old parser): **47/176 (26.7%)
now match.** Projected full-engine impact: OCR yield 77/300 (25.7%) →
~124/300 (41.3%), a ~60% relative improvement, from a small parser fix.
Confirmed live via a real (non-simulated) `--dry-run` afterward: 62/250
votes on a fresh selection window, consistent with the isolated measurement.

**Yield reconciliation, old logic vs. new logic on that same 250-card
window** (no new OCR work run for this - reusing already-known numbers):
selection-order stability means the 250-card window is the 223-card
reconstructed cohort above (still eligible - no vote was ever cast on a
skip) plus 27 cards never seen in the original 300-card pilot run at all.
Old-logic yield on the 223 known cards is **measured, not estimated**: 3
(the "already-matching" cards, unaffected by the fix) out of 223 - the
other 220 are old-logic non-matches by definition of how they were
classified as skips. Old-logic yield on the 27 unseen cards is **not
measured** - no new work was done to classify them - and is instead
estimated by applying the original pilot's overall old-logic OCR base
rate (77/300, 25.7%) to that count: 27 × 0.257 ≈ 7. Combined old-logic
estimate: (3 + ~7)/250 ≈ 10/250 ≈ **4.0%**, against the confirmed
new-logic **24.8%** (62/250) on the identical window - roughly a 6x
relative lift here, well above the pilot-set's ~1.6x (60% relative)
projection, because this window is disproportionately drawn from cards
that were old-logic failures by construction (the 223-card skip cohort),
not a representative sample of the full catalog. Treat the 24.8%-vs-4.0%
comparison as the honest floor-to-floor number on hard cases, and the
41.3%-vs-25.7% pilot-set figures as the representative full-run
projection - they are not the same statistic and should not be quoted
interchangeably.

Of the 129 cases still unfixed: only 2/176 (1.1%) are genuinely-missing
printings (the parsed set code is real, but no `CanonicalCard` row exists
for that (set, number) at all); the remaining 127/176 (72.2%) are true
OCR garbage with no salvageable signal - a meaningful fraction of which
traces to one specific custom-frame Drive source
(`Source pk=1, "WilfordGrimley"`, "Custom Cardbacks and alternate frames
with Upscaled images") whose non-standard branding text sits inside the
collector-line crop region and defeats OCR outright; not something a
parsing fix can address.

**Cross-check against the filename tag-gap census (1,097 unresolved cards
with an unmatchable `expansion_hint`, from the pre-pilot addendum): NOT
the same root cause.** All 1,097 have a fully _recognized_
`CanonicalExpansion` code (0 unknown) - the gap is a name-matching problem
(many are `(Front)`/`(Back)` filename-parsing artifacts on basic lands),
unrelated to the OCR token-position bug above. Two separate fixes, not
one parser fix arriving twice - the D2.5 deterministic tier is **not**
implied by this OCR fix and was not built.

## Key files (Stage 8 era, historical)

- Backend: `cardpicker/printing_consensus.py`,
  `cardpicker/printing_metadata_import.py`,
  `cardpicker/integrations/game/mtg.py`, `cardpicker/models.py` (migration
  `0050_canonicalprintingmetadata_cardprintingtag_and_more.py`;
  `display_name` — migration `0056_tag_display_name.py`, Stage 5),
  `cardpicker/search/search_functions.py` (Stage 3 re-rank/filter),
  `cardpicker/documents.py` (Stage 3 widened indexing; Stage 3.5
  `reindex_card_safely`), `cardpicker/tag_consensus.py` (Stage 3.5),
  `cardpicker/reason_tags.py`, `cardpicker/default_tags.py`,
  `cardpicker/management/commands/seed_no_match_reason_tags.py` (Stage 4,
  display_name seeding Stage 5),
  `cardpicker/deductive_backfill.py` + management command
  `deductive_backfill_printing_tags` (Stage 6),
  `cardpicker/question_feed.py`, `cardpicker/attribute_tags.py` +
  management command `seed_attribute_tags` (Stage 7)
- Frontend: `frontend/src/features/printingTags/` (`PrintingTagPicker.tsx`,
  `starburstShape.ts`, `cardPanel.tsx` — the extracted sticky/starburst/
  reveal/candidate-grid mechanics, Stage 7),
  `frontend/src/features/filters/ResolvedAttributeFilter.tsx` (Stage 3),
  `frontend/src/common/processing.ts::getPrintingMatchLabel` (Stage 3),
  `frontend/src/features/attributeVoting/` (`ChipCard.tsx`,
  `NoMatchReasonStrip.tsx` — Stage 4; `QueueTagQuestion.tsx`,
  `ArtistVotePicker.tsx` — reused directly by Stage 7),
  `frontend/src/common/tagDisplayNames.ts` (Stage 5),
  `frontend/src/features/attributeChips/`, `frontend/src/features/ questionFeed/QuestionFeed.tsx`, `frontend/src/pages/whatsthat.tsx`
  (renamed from `printingQueue.tsx` — Stage 7)
- `docs/upstreaming/vote-system.md`, `docs/federation-v1.md` (`name` vs.
  `display_name` interchange-key note, Stage 5)
- `docs/features/catalog-completion-plan.md` (iteration safety - Part 1
  detail), `cardpicker/utils.py` (`find_stale_applied_migrations`,
  `get_baked_git_sha`), `cardpicker/management/commands/purge_machine_votes.py`,
  migration `0061_pilotrunledger_cardartistvote_run_id_and_more.py`
- `cardpicker/local_layout_class_cast.py` + management command
  `local_layout_class_cast` (public issue #369, "the Hidden Courtyard should
  register as borderless") - closes the gap between Stage C's
  `ImageEvidence.layout_class` (issue #148's geometry-group extractor) and an
  actual `CardTagVote`: any card whose Stage C evidence carries a confident
  border-color reading but never got a border-attribute vote cast by the
  live pilot/fallback engine (e.g. extracted before that engine ran, or
  whose printing resolved before reaching the fallback stage) is picked up
  by this standalone, zero-image-fetch caster instead. See that module's own
  docstring for the full mapping/anonymous-id/confidence-tier rationale -
  not duplicated here.

## Known gaps (Stage 8 era, historical)

- The Stage 7 layout (starburst/card/chip-ring composition) was hand-tuned
  via iterative screenshot review, not built against a real design system -
  owner has flagged that this needs a proper pass with the `/dataviz` skill
  in the future rather than further ad hoc CSS tuning.
- `CanonicalCard.image_hash` was bootstrapped to `0` for every row
  (`--skip-image-hash`) at import time; Stage 8's phash engine is the
  first thing to actually populate it, lazily and only for rows it
  needs - most of the table (any candidate no pilot run has hashed yet)
  is still at the placeholder `0`.
- Client-side (Orama) search has no Stage 3 parity — see above.
- Upstreaming this feature is deprioritized — see
  [[../infrastructure.md]]'s Upstreaming section.
- Tier-1 `confirm_suggestion` volume (28,112) is confirmed via a direct
  live query, not the _live-usage_ starvation impact - whether it actually
  swamps tiers 2-4 in practice (vs. just in raw candidate-set size) is a
  server follow-up.
- `netPolarity`'s optimistic client-side update (set to the tapped
  direction's extreme immediately, reconciled with the server's real
  value once the response lands) isn't linear in vote count once machine/admin
  weights are involved - can't fully verify the two never visibly diverge
  against MSW mocks alone.
- Border Color's v1 chip set omits gold/yellow `border_color` values, and
  the frame_effects chip set omits `legendary`/`inverted` despite higher
  raw counts than the chips that made the cut - both flagged as judgment
  calls in Stage 7 above, worth revisiting with real moderator/voter
  feedback.
- Stage numbering: Stage 4 (no-match reason tags, merged as PR #12),
  Stage 5 (tag identity/presentation decoupling via `Tag.display_name`,
  merged as PR #14), and Stage 6 (deductive printing-tag backfill) reflect
  three concurrently-developed
  branches sharing this one doc file, numbered in landing order to avoid
  collisions.
- **Future work: anonymous_id trust scoring via honeypot questions**
  (2026-07-15, raised during Stage 8's pilot run). Idea: periodically
  serve a voter a card whose printing is already known with very high
  confidence — ideally an already-`RESOLVED` card (real human-backed
  consensus), Stage 6's D1 tier as a fallback pool (0 false positives
  across 27,424 live cards, but still machine-derived, not independently
  human-verified, so using it as "trusted" ground truth to police other
  submissions has a circularity worth being honest about) — without
  telling the voter it's a check, and score their `anonymous_id` based on
  whether they answer correctly. Deprioritize/downweight low-scoring
  anonymous_ids to make data poisoning more costly. Same crowdsourcing
  pattern as reCAPTCHA/Mechanical-Turk gold-standard questions. Known
  limitation before this is worth building: `anonymous_id` is a
  client-generated, trivially rotatable value
  (`frontend/src/common/cookies.ts`) with no persisted identity —
  a trust score raises the cost of poisoning (a fresh ID needed per
  abuse attempt) but doesn't stop a determined actor, so it's a speed
  bump, not a hard Sybil defense. Also a genuinely new subsystem, not a
  small addition: a honeypot-injection point in `question_feed.py`
  (nothing currently interrupts the three-tier ranked union with a
  planted question), somewhere to persist per-`anonymous_id` trust state
  (no such model exists today), and a way to feed that score back into
  `vote_consensus`'s per-source weighting — worth its own design pass
  rather than bolting onto an existing stage.
- **Future work: `(Front)`/`(Back)` name-matching fix for the
  `expansion_hint` census gap** (2026-07-15, deferred out of the pre-scale
  program by owner decision — deterministic parser fix, not part of
  Stage 8's OCR/phash engines). The 1,097-card filename tag-gap census
  (cards with an unmatchable `expansion_hint`, all with a fully
  _recognized_ `CanonicalExpansion` code) was cross-checked against the
  Stage 8 no-match autopsy above and confirmed to be a **different root
  cause** — a name-matching problem, not the OCR set-code-position/
  leading-zero bugs the autopsy fixed. Many of the 1,097 are
  `(Front)`/`(Back)` filename-parsing artifacts on basic lands (a
  double-faced-card naming convention this catalog's name-matching
  doesn't strip before comparing against `CanonicalCard.name`). Belongs
  with `cardpicker.deductive_backfill`'s deterministic tiers (D1/D2), not
  Stage 8's visual-disambiguation engines — explicitly not the "D2.5
  arriving for free" the autopsy's cross-check ruled out.
  **Now tracked with real sizing**, not just this note: issue #386
  (2026-07-23, found live while investigating issue #372's own "Malakir
  Rebirth" sub-question) confirms the specific mechanism — `DFCPair` rows
  are correct and complete (this is NOT a missing-data gap), but neither
  `deductive_backfill.CanonicalNameIndex` nor
  `local_identify_printing_tags.CandidateNameIndex` consult `DFCPair` at
  all, so a card uploaded under just one MDFC face's name (with or
  without an explicit `(Front)`/`(Back)` literal tag) never matches the
  combined `"Front // Back"` `CanonicalCard.name` either index keys on.
  34 confirmed live in #372's own 135-card cohort alone (not the full
  catalog count). Deliberately left untouched by #372's own fix (a
  same-index, narrowly-scoped de-concatenation fallback for
  space-stripped filenames) — MDFC face names are correctly space-
  delimited already, so that fallback's own gate never fires for them.
- **`deductive_backfill.py`'s own votes don't carry `run_id` yet** (2026-07-16,
  iteration-safety Part 1's explicit scoping decision, not an oversight) —
  the `run_id` threading in this section only covers
  `local_identify_printing_tags.py`/`local_fallback.py`'s engines.
  `deductive_backfill.run_backfill()` would benefit from the same
  revocability property but wasn't in scope for this pass.

## HOLD #2: full package report (2026-07-16)

Synthesizing deliverable gating full-catalog run authorization. Everything below is either
already-linked from earlier in this doc or newly summarized here; nothing in this section is a
new claim not otherwise sourced above.

**Infrastructure prerequisites - all landed:**

- Rate limiter (PR #25): merged to master. Deploy confirmed live via direct requests against
  `cdn.proxyprints.ca`'s full tier (4 real requests, all HTTP 200, 0.46-1.67s latency, no 429s)
  - the underlying fetch path PDF export and bulk download both depend on is healthy
    post-merge. (CI's "Publish image CDN" job shows red on every run, before and after this
    merge - a separate, pre-existing, unrelated failure in a `thumbnail-refresh` Cloudflare
    Workflow trigger, not the image-serving route itself; logged as its own follow-up, task
    #111, not a gate.)
- Tesseract dockerized (`docker/django/Dockerfile`'s shared `builder` stage) - verified
  end-to-end via a real `--dry-run --limit 3` inside the rebuilt container. Host venv retired.
- Container boot-recovery hardened: `restart: unless-stopped` on all 5 services plus a
  `mpcautofill-docker-compose.service` systemd unit as belt-and-suspenders - verified with a
  real `sudo reboot`, not simulated (all containers back up unattended within minutes, site
  returned 200 on both domains).
- Batch-flush checkpointing (item 2): a kill loses at most one `--batch-size` (default 25)
  worth of unflushed work; a plain re-invocation resumes cleanly via the existing idempotent
  selection query. Verified with a simulated-kill test.

**Throughput, real and corrected:**

A real correctness gap was found and fixed before trusting any number from this window: the
first several soak-test runs showed 0/250 OCR votes (vs. an original 94/300 baseline) - traced
to generic multi-set token names (e.g. "Beast", ~90 candidates each, essentially 0% coverage)
being front-loaded by item 1's coverage-gap ordering into a cohort that's structurally
unmatchable by OCR (a token's printed collector line reads its parent set's code; its DB
candidates use token-specific codes that never match). Fixed by excluding `card_type=TOKEN`/
`CARDBACK` from selection. Post-fix, OCR yield is healthy and consistent (56/198 votes, 28.3%,
matching the original baseline) at every core count tested.

Corrected same-window (250-card) before/after comparison, real `docker stats`-verified multi-core
parallelism (not just inferred from noisy aggregate `top`):

| core count | wall-clock | processing-only rate |
| ---------- | ---------: | -------------------: |
| lower      |       456s |          2.051s/card |
| higher     |       230s |          0.914s/card |

**Speedup: 2.24x.** Full-catalog re-projection (172,494 eligible pool, freshly counted with the
token/cardback fix applied):

|                   |   raw (naive) | cluster-dedup-adjusted |
| ----------------- | ------------: | ---------------------: |
| lower core count  |     4.09 days |              4.14 days |
| higher core count | **1.82 days** |          **2.34 days** |

The instance is now running at its higher core count as the standing configuration (not a
temporary state for this measurement alone) - not reverting to the lower count, though not
treated as permanently fixed either; revisit whenever convenient, no urgency either way.

**Cluster + coverage census:** clustering (item 2a) absorbed ~21% of selected candidates into
representatives in the corrected (token-excluded) sample - down from an earlier ~26-28% observed
in the token-contaminated sample, consistent with tokens/generic images being more prone to
visual duplication. The sequential clustering pre-pass (`compute_own_image_clusters`, confirmed
via code inspection and a live `docker stats` capture showing a single-core ~100% CPU plateau
during that phase specifically) is ~21.6h fixed regardless of core count - ~38% of total time at
the higher core count. Logged as task #108, held as an available future optimization, not built
now - the current projection is already a good number for a background job.

**Track 4 (pilot-quality items):**

- Bleed tag: negative-only voting shipped (item 4b) - votes only on a detected `trimmed`
  reading, absence of any vote is the documented convention for "presumed normal bleed" (updated
  in both this doc and `sensitive_tags.py`'s own comment, which previously documented the
  opposite pre-pilot convention). The existing-tag check (`Tag.objects.filter(...).first()`,
  degrades to no vote if the tag isn't seeded) was already in place before this change - no new
  tag seeded, matching the "wait for owner ok" instruction by construction. The underlying
  aspect-ratio classification itself was validated against a real 40-source diverse sample
  (Bleed-edge tagging section above) - the negative-only voting change is a polarity/gating
  change on top of that already-validated classification, not a new detection algorithm needing
  its own separate validation pass.
- DPI-tag audit (item 8, report only): 99.97% of the catalog already at 300+dpi - not a useful
  prioritization signal on its own. `low-res` SENSITIVE tag has never been used in production
  (0 resolved, 0 pending) - stays untouched, human-judgment/moderation-gated as designed. Both
  tag stores checked (`Card.tags` resolved/baked array and `CardTagVote` raw votes).

**Git/branch audit:** clean. This session's branch (`worktree-pilot-prescale`, PR #24) is
in sync with origin, mergeable. PR #25 merged (rate limiter). PR #20 (unrelated frontend fix)
merged at the owner's request, reviewed and confirmed by the owner before merging. PR #19
(unrelated docs-only Playwright-flake note) remains open with a trivial, keep-both `docs/lessons.md`
conflict against master - not a dependency of anything in this program, disposition left to the
owner's convenience. Several other worktree branches exist but are either already merged or have
zero unique diff against master (content already landed via a different commit path) - no lost
work found anywhere in the audit.

**Scaling recommendation, updated for the shorter true runtime:** the original Option A
(screen'd process) vs. Option B (django-q nightly slices) decision assumed a ~7-day run,
where crash-recovery and unattended multi-night scheduling mattered enough to weigh a full
scheduler infrastructure investment. At the now-real ~1.8-2.3 day full-catalog runtime, **a
single continuous run is the right shape - chunked nightly slicing is not needed.** Item 2's
own batch-flush checkpointing already provides crash-resilience within that single run (a kill
loses at most one batch, a plain re-invocation resumes cleanly), which is the main protection
django-q's scheduler infrastructure would otherwise buy - not worth the added complexity for a
run this short. Execution is via the now-dockerized image (`docker compose run`, matching every
verification run this session), not a host venv - a `screen`/`tmux`-wrapped single invocation is
sufficient; no new infrastructure to build.

**Open, non-blocking items** (logged, not gates): item 2b (persist `content_hash` for
federation, deferred), item 5 (questionFeed ordering mirror, separate follow-up PR), task #108
(parallelize the clustering pre-pass), task #109's future-work note (token-aware matching via
Scryfall's own token detection), task #111 (unrelated CI noise in the thumbnail-refresh
trigger), PR #19's disposition (owner's convenience).

**Full-catalog run: since fired and completed** (see `catalog-completion-plan.md`'s Status
section for final numbers). This report was the synthesizing deliverable requested before
that authorization.

## Two fast-follows, built after HOLD #2 (2026-07-16)

Both researched and sized before building (see the HOLD #2 section above and this doc's earlier
feasibility notes) - neither required schema changes, both reuse already-existing, already-
populated data.

### `expansion_hint` candidate narrowing

`_narrow_candidates_by_expansion_hint` (`local_identify_printing_tags.py`) narrows the
candidate list every engine considers, using `Card.expansion_hint` - a field that already
existed and is already populated at import time by `cardpicker.tags.Tags.extract` (a lone
set-code bracket token in the filename that didn't resolve a direct match, e.g. `[UNF]` with no
collector number). Not a new signal - just newly wired into the pilot; `deductive_backfill`'s
own D2 tier already trusts this same field for direct resolution when it narrows to exactly
one candidate.

A confidence PRIOR, not an entailment: narrows the list passed to `run_ocr_for_card`/
`run_phash_for_card`/`run_fallback_for_card` inside `_compute_card` only - never touches
`select_candidates`'s ordering, `compute_covered_printing_pks`, or the
`uncovered_printings_closed` metric, all of which need the true, unnarrowed candidate set to
stay correct. Never narrows to empty: if the hint matches zero of the name's real candidates (a
real, measured ~9% data-quality case - the hint may be stale or mismatched), the full list is
used instead.

**Real yield, measured live**: of 2,466 pilot-eligible cards with a real `expansion_hint`, 645
currently get skipped by phash outright (`too-many-candidates`) - narrowing brings 407 of those
back under `PHASH_MAX_CANDIDATES`, giving phash a real shot where it currently never runs.
OCR's own exact-match logic doesn't benefit (a smaller candidate list doesn't change whether a
parsed code+number is in it) - this is a phash-only unlock in practice.

### Name-frequency elimination

`run_name_frequency_elimination` (new function, new management command
`local_name_frequency_elimination`) - for a NAME where exactly one printing remains uncovered
AND exactly one pilot-eligible card is unresolved for that name, the match is deducible by
elimination alone: no image fetch, no OCR/phash, no visual disambiguation at all.

**The safety gate is the whole point, not a refinement.** A name can have exactly one uncovered
printing while SEVERAL unresolved cards share that name - in that case elimination does NOT
tell you WHICH card is the missing one (any of the others could just as easily be a redundant
depiction of an already-covered printing uploaded by a different source). The naive version
(gate on "one uncovered printing" alone) was the original researched number; adding "and
exactly one unresolved card too" is what makes the deduction airtight. Measured live against
the full catalog (not a sample), 2026-07-16: 2,076 names have exactly one uncovered printing;
only 1,678 of those also have exactly one unresolved eligible card - the naive version would
have voted incorrectly, on average, for the other ~400 names' multiple candidate cards.

Confidence deliberately modest (0.6, vs. OCR/phash's 0.85/0.75/0.8) - a purely structural
deduction is weaker evidence than an engine that actually looked at the image, even with the
1:1 gate making it sound. Still just a vote (`NAME_FREQUENCY_ANONYMOUS_ID`), never a direct
resolve - same consensus/gate-check discipline as every other engine in this module, same
batch-flush checkpointing pattern as `run_pilot`.

#### The counting gate was not sufficient on its own (2026-07-30)

Owner ruling: _"just because a card was printed exactly once doesn't mean that the image in our
catalogue is an accurate depiction of that card, it may have a different border or another
issue."_

Everything the 1:1 gate checks is a **count**. Counting establishes that _if_ this card is a
depiction of one of the name's printings, _then_ it must be the uncovered one. It establishes
nothing about the antecedent, and the only filters that spoke to it at all were the **declared**
`custom-art` and non-English tags — so an altered border, a custom frame, or a misnamed upload
that nobody had tagged yet passed the gate and received a full-confidence structural vote.

"It is only a vote" is a weaker defence than it sounds. Issue #593 established that a machine
vote is what the question feed renders as _the suggestion to confirm_, and a human's click
returns as a full-weight USER vote — so a visually-unverified deduction becomes a one-click
rubber stamp, and the human-backed consensus gate is the mechanism that launders it.

**The missing conjunct is now required**: the card's already-stored evidence must be consistent
with the candidate printing — border class and frame style, via
`local_identify_printing_tags.printing_attribute_disagreement`, which is the _same_ check the
Stage D join-key channel has always applied, now shared between the two callers rather than
re-derived. No image fetch and no new extraction: every input is a field already sitting on the
card's current `ImageEvidence` row. Sharing it also inherits PR #656's gate for free — the frame
half is skipped entirely unless `artist_ocr` actually ran, because `illus_anchor_fired` is
nullable and `bool(None)` is indistinguishable from "ran and found no anchor".

**No stored evidence means abstain, not proceed.** If the card has never been extracted, we have
never looked at the image, so the antecedent is exactly as unestablished as before. This is the
one place where this module's usual "missing data is not evidence" rule points the other way, and
deliberately so: that rule protects a match from being _vetoed_ by silence, whereas here silence
is being asked to _establish_ something. The two abstention populations are reported separately
(`abstained_no_evidence`, `abstained_attribute_mismatch`) so the cost of the gate is legible on
the first run rather than inferred from a smaller total.

The tier was **not** dropped, although it could have been cleanly: it has never run in production
(zero `PilotRunLedger` rows for `local_name_frequency_elimination`, ever), so nothing is
contaminated and no retraction was needed. It is kept because the deduction is genuinely sound
once the antecedent is established, and elimination reaches a population the image-based channels
structurally cannot — a name whose single uncovered printing has no distinguishing collector line
to read. Deleting a sound tier for want of a guard is a worse trade than adding the guard.

#### The census was leaking (2026-07-30)

Separately from soundness, the 1:1 gate was counting over a population it was itself permanently
shrinking. `_eligible_base_queryset` was called with **no `run_id`**, so its exclusion of cards
already carrying this calculator's vote was **lifetime** rather than per-run:

- **run 1** — a name has one unresolved eligible card and one uncovered printing. Sound; it votes.
- **later** — a second upload of that name arrives from another source, the ordinary way this
  catalogue grows.
- **run 2** — the run-1 card is excluded _forever_ by its own vote, so the name presents as having
  exactly one unresolved card again and votes for the new one. Correctly, the pool is two cards
  and the gate should abstain.

That is a **fresh wrong positive**, not a stale or missed vote: nothing about the second card
changed, only the size of the population the gate counts. The fix is to pass this run's `run_id`,
which narrows the self-suppressing excludes to rows _this_ run wrote. Within-run resume is
unaffected — re-invoking with the same `run_id` still skips cards this run already voted on.

`compute_covered_printing_pks()` stays catalogue-wide and un-scoped, deliberately: "covered" is a
fact about the world (a confirmed `canonical_card`, or a RESOLVED `inferred_canonical_card`), not
about this calculator's progress, and run-scoping it would make every run treat every printing as
uncovered. The two halves of the gate are scoped differently on purpose.

`run_pilot`'s own `select_candidates` and `count_below_resolution_floor` are **left unscoped** —
neither gates on a count over the returned population (the pilot's predicate is per-card and its
selection is a fetch-budget ordering; the floor count is a report metric), so neither has this
defect.

## Incident: per-chunk thread pool leaked Postgres connections, crashed the live run (2026-07-16)

The second full-catalog relaunch (post cluster-dedup removal) died ~3 minutes in with
`psycopg2.OperationalError: FATAL: sorry, too many clients already`. Root cause: pipeline
concurrency's `ThreadPoolExecutor` (item 3d above) was constructed **inside** the chunk `while`
loop, once per chunk, instead of once for the whole run. Django DB connections are thread-local
and nothing closes a connection when its owning thread is torn down, so every chunk's disposable
`ThreadPoolExecutor` leaked up to `workers` Postgres connections that were never coming back.
At `DEFAULT_BATCH_SIZE=25` and `workers=7`, against `max_connections=100` with ~10 already in
use by live traffic, the math works out to roughly a dozen chunks (~300 cards) before
exhaustion - consistent with the observed crash timing at workers=7's measured throughput.

Production site itself was never affected (confirmed 200s on both domains, and Postgres
recovered to its normal ~8 connections once the crashed process released its leaked slots) -
this was a background management-command process, not user-facing traffic.

**Fix**: hoist the `with ThreadPoolExecutor(...)` (falling back to `contextlib.nullcontext()`
for `workers==1`) to wrap the entire chunk loop, so the same pool - and therefore the same
`workers` threads, and therefore each thread's single DB connection - is reused across every
chunk instead of recreated. Zero behavior change to write ordering or chunking semantics (see
the code comment at the fix site); regression test
`TestConcurrency::test_thread_pool_is_created_once_for_the_whole_run_not_per_chunk` asserts
pool construction count stays at 1 across multiple real chunks of work, not just that votes
still get written.

## Prior-art read: phash calibration in other MTG card-ID projects (2026-07-16)

Timeboxed (~1hr) research task, ahead of designing the two-threshold clustering (item 3) and
art-region hash variant (item 4) follow-ups. Examined
[`tmikonen/magic_card_detector`](https://github.com/tmikonen/magic_card_detector) and
[`freeall/mtg-card-detector`](https://github.com/freeall/mtg-card-detector), both MIT-licensed
(copyright Timo Ikonen). **These are not two independent implementations** - freeall's repo is
an explicit fork of tmikonen's; the core hashing/matching code (`magic_card_detector.py`) is
essentially unmodified between them, freeall's changes being CLI ergonomics and a filename
convention for carrying Scryfall IDs through. Credit: threshold/matching approach below is
tmikonen's original work, referenced here as prior art per project attribution policy - no code
adopted verbatim, MIT terms would apply if that changes.

**Their "threshold" is not directly reusable as a Hamming-distance number.** They use
`imagehash.phash(hash_size=32)` (a 32x32/1024-bit hash, far larger than imagehash's 8x8 default),
but the match decision isn't a flat distance cutoff - it's a per-query statistical outlier test:
the best (smallest) Hamming distance among all candidates is compared to the _mean and standard
deviation of the distances to every other candidate_, and accepted only if it's more than 4
standard deviations below that mean. Reusing "4" as if it were a raw phash bit-distance (the way
this pilot's own d=0/d<=2 tiers are expressed) would be a category error - the two numbers aren't
on the same scale. The transferable idea, if any, is the _method_: validating a distance
threshold against the population's own distance distribution rather than picking a fixed cutoff
in isolation - a possible cross-check for calibrating d<=2, not a value to copy.

**No working art-region hash code exists in either project.** tmikonen's own blog post
(tmikonen.github.io) names hashing a separate art-only reference image as future work, never
implemented in either repo. Nothing to borrow beyond "someone else independently considered this
useful," which is a weak signal, not a design.

Other notes: both preprocess with CLAHE histogram equalization and hash at all 4 rotations
(a "photo of a physical card" concern from unknown-orientation scans - doesn't apply to this
pilot's Scryfall-sourced digital images, which are already upright). Neither repo touches the
Scryfall API directly; both assume a pre-populated local image folder, matched by brute-force
linear scan against every reference hash (no indexing/bucketing) - not a scale precedent worth
following at 172k+ cards regardless of threshold source.

## Phash accuracy at small CDN sizes (2026-07-16)

Investigated whether the disabled cluster-dedup pre-pass (`compute_own_image_clusters`, see the
disablement entry above) could be cheaply re-added by hashing small CDN-resized images instead
of full resolution. There's only one fetch path in the whole module
(`fetch_card_image`/`get_worker_image_url`) - OCR, the main phash engine, and clustering all go
through it identically, so a smaller size needs no new plumbing, just a smaller `fetch_dpi`.
**Gotcha**: the CDN's dpi-to-pixel-height conversion isn't rounded - a `dpi` not a multiple of
10 produces a non-integer height param that Google's `lh4` endpoint flat-out rejects with a 400.
Usable small sizes confirmed: `dpi=40` (148px), `dpi=50` (185px).

Measured on 150 real cards (11,175 pairs), hashed at full res (250dpi/~925px) and both small
sizes with the exact production hash function:

- **Zero false merges** for the clustering pre-pass's actual exact-match (distance-0) criterion,
  across ~11k confirmed-different pairs - minimum observed distance at small size was 16-18,
  nowhere near 0.
- **False splits**: only 2 true-duplicate pairs existed in the sample; one survived at small
  size, one drifted to distance 2 at both small sizes and would no longer cluster. 1/2 is a real
  signal but too thin (n=2) to call this proven safe - would need a larger duplicate-focused
  sample before trusting it for a real re-add.
- Separately (not the clustering path, but relevant): checked against the _other_ phash engine's
  own match threshold (`DEFAULT_DISTANCE_THRESHOLD=20`) - 1.0% of confirmed-different pairs fell
  ≤20 at 148px vs 0.56% at 185px, a real erosion of that engine's already-tight margin. Not
  itself a reason to change that engine (it doesn't use small images), but a caution against
  assuming small-size hashing is free of cost everywhere it might get reused.
- **Fetch time**: real ~2-2.5x speedup (not the ~6x pixel-count reduction would suggest - cost is
  dominated by network/proxy round-trip overhead, not payload size). At full-catalog scale this
  still leaves roughly 9-11h of _fixed sequential_ pre-pass cost, down from ~21.6h - a real
  improvement, but likely not enough alone to justify re-adding a separate pre-pass fetch.

**Conclusion**: small-size hashing looks safe for the clustering pre-pass's specific use case,
with the false-split evidence still too thin to call proven. Even if proven, the bigger lever is
avoiding a _separate_ pre-pass fetch entirely - reusing the image OCR/phash already fetches per
card, rather than shrinking a redundant one. That reframes task #108/#118 more than resolving
task #117 on its own does.

## Hash-at-ingest + two-threshold clustering (2026-07-16)

Built on `worktree-hash-at-ingest` as the coherent follow-on the research above pointed at:
hash ONCE at ingest, store, never recompute corpus-wide - absorbing deferred item 2b and making
cluster dedup a per-run DB query at zero fetch cost, so the standalone pre-pass (disabled above)
never needs to exist again in any form. Built while the fast-follow-enabled full-catalog run
(PR #26) continued unattended - this work does not touch that run, it's the next-run
architecture.

### Schema: `Card.content_phash`

`Card.image_hash` (migration 0046) turned out to already exist as a dead field - added
alongside `expansion_hint`'s era, always written as a literal `0` placeholder by
`update_database`, never read anywhere (confirmed: zero references outside `models.py` and that
one write site). Rather than add a second, confusingly-similar hash field next to a dead one on
the same model, migration 0061 renames it to `content_phash`, makes it nullable (existing `0`
rows migrated to `NULL` - none of them were ever real hashes), and indexes it. Dual consumer:
this pilot's own clustering, and federation-v1's reserved `content_hash` field (see
`docs/federation-v1.md`) - one field, two consumers. Algorithm/params documented as a
cross-instance interchange contract in the field's own docstring: `imagehash.phash`,
`hash_size=8` (64-bit) - the library default, inherited from `CanonicalCard.image_hash`'s
pre-existing convention rather than deliberately chosen; changing it later is a re-hash
migration, not a config flip, since federation peers would need to agree on the same params.

### Fetch-path extraction

`get_worker_image_url`/`fetch_card_image` moved from `local_identify_printing_tags.py` to a new
`cardpicker/image_cdn_fetch.py` - a second, non-pilot caller (`update_database`'s ingest hook)
needed the identical fetch, and the core ingest pipeline shouldn't depend on the pilot
orchestration module for something this foundational.

### Hash at ingest - a real cost, not a free byproduct

The task brief's premise here needed a correction, found before building anything wrong:
`update_database`'s per-card path (`transform_image_into_object`) builds a `Card` row purely
from Google Drive folder-listing metadata (id/name/size/height/timestamps) - it never touches
image bytes. There was no existing fetch to piggyback on. `hash_newly_created_cards`
(`cardpicker/sources/update_database.py`) is therefore genuine new cost: one small-CDN-size
fetch per newly-created card, threaded (`MAX_WORKERS=5`, matching this module's own Drive-scan
concurrency), called right before `bulk_create`. Best-effort - a fetch/hash failure just leaves
`content_phash` NULL for the backfill command to retry, never blocks a sync.

**Scoped to CREATED cards only, not UPDATED ones - a deliberate narrowing of the brief's literal
"new/changed cards" wording, flagged explicitly rather than silently assumed:** `content_phash`
was never in `bulk_sync_objects`'s `bulk_update` field whitelist (confirmed - the whitelist's own
comment claims "every field except identifier," which was already inaccurate before this
change), so there is nothing to persist for an updated card even if it were re-hashed - the
write would be silently discarded. A genuinely changed image at the same Drive file id (rare -
Drive normally assigns a new id on real content replacement) isn't detected or corrected here;
the standalone backfill command's NULL-only filter is the correction path if that's ever
suspected for a specific card. Building real change-detection for that rare case was judged out
of proportion to the risk - logged here rather than built.

### Backfill command

`local_backfill_content_phash` (new management command, `local_phash.run_content_phash_backfill`)
hashes every existing `content_phash IS NULL` row. Idempotent and resumable by construction (the
NULL filter IS the checkpoint - no separate `--resume` flag or state file), batched
(fetch+hash `batch_size` cards concurrently, one `bulk_update` per batch - a kill loses at most
one in-flight batch), `--nice` by default matching `run_pilot`'s convention.

### Two-threshold clustering (`cardpicker/local_clustering.py`)

Replaces the disabled fetch-based pre-pass entirely - `run_pilot`'s cluster_result call site now
reads `Card.content_phash` (already loaded via `select_candidates`'s `.only()`) instead of
fetching. Restores the representative-only filtering the original (pre-disablement)
implementation had (`all_selected_by_card_id` narrowed to non-absorbed cards before the compute
loop) - the disabled no-op version had dropped this line since it was a no-op with an
always-empty `members_by_representative`; re-enabling clustering without restoring it would have
silently run full OCR/phash/fallback compute on absorbed members AND propagated a redundant
vote to them.

Two tiers, two trust levels: **d=0** (exact hash match) propagates votes exactly as the old
pre-pass did - sound entailment, unchanged semantics. **0 < d <= 2** is a narrowing PRIOR only
(never auto-votes) - required, not optional, given small-size hashing is in use (the earlier
"Phash accuracy at small CDN sizes" section found a real true-duplicate pair landing at exactly
d=2). The d<=2 narrowing HINT is computed (`near_duplicate_ids_by_card_id`) but **not yet wired
into `_compute_card`'s actual candidate-narrowing chain** - flagged explicitly as a scoped-out
fast-follow, not silently half-built: wiring it into the hot per-card compute path under a
`ThreadPoolExecutor` needed more careful threading verification than this pass's effort budget
allowed, and the d=0 propagation win stands on its own without it.

**Performance, benchmarked before trusting the design, not assumed:** the two tiers are computed
as independent steps (advisor review caught this before it shipped as one coupled pass) - d=0 is
a plain dict grouping, measured 0.13s at N=166,422 real-scale synthetic hashes. The d<=2 tier
(chunked numpy XOR + `numpy.bitwise_count` popcount, never a Python pairwise loop or an
all-at-once O(N^2) allocation) measured ~2-3 minutes at the same N (contended with this box's
own concurrently-running full-catalog job at benchmark time), and it's pure in-memory compute,
so it doesn't compete for the shared CDN request budget the old pre-pass did.

**Correcting an overstated comparison (caught when the owner asked "are we sure this is
legitimate" rather than accepting the headline number)**: the naive "~500-650x win over the
disabled pre-pass's ~21.6h" comparison is misleading on two counts, not a fair apples-to-apples
claim. First, it's comparing two different operations - 21.6h was a recurring per-run network
fetch, 2-3 min is a one-time-amortized in-memory read that only works AFTER the separate ~2.8h
backfill has populated `content_phash` (see below) - not "the same work, done faster." Second,
the 21.6h baseline was never threaded (`--workers` had no effect on the fetch loop, which is
WHY it was disabled) - a fair comparison should be against what a THREADED fetch pre-pass could
have achieved (~21.6h / 7 workers ≈ ~3h), not the unoptimized sequential baseline. Against that
fairer baseline, the real improvement is closer to **~60-90x** (~3h / ~2.5min), not 500-650x.
The underlying design is still a genuine, large win - eliminating a recurring network-bound cost
in favor of a one-time investment plus a fast in-memory read - but the specific multiplier
quoted needs to be the honest one, not the most dramatic one available. Wrapped in a try/except:
a failure in the d<=2 scan falls back to "no near-duplicate hints this run," never taking down
d=0's already-proven propagation.

### Validation against real production data (not the earlier n=2 sample)

The original "Phash accuracy at small CDN sizes" research flagged its own weakness: only 2 true
duplicates existed in that 150-card sample, too thin to trust. The live full-catalog run
(running throughout this work) provided a much better source: **harvested 300 real pairs of
different Card rows that received a vote for the SAME printing** from the run's own OCR/phash
engines (1,771 such pairs existed at harvest time), plus 300 pairs voted for different
printings (false-merge check), via a read-only query against the live production DB.

**A ground-truth correction made before trusting the numbers**: "voted for the same printing"
is NOT the same claim as "the same uploaded image" - two community members can scan/photograph
the same real card differently, and the clustering feature's own definition of "true duplicate"
(from its original docstring) is full-resolution hash distance-0, not "same printing." Computed
full-resolution hashes for the same-printing sample too, and partitioned by that ground truth
before drawing any conclusion:

- **79 pairs were true duplicates** (full-res distance=0, i.e. really the same uploaded image):
  100% landed at small-size distance<=2 (73 at exactly 0, 6 at 2) - **zero false splits**,
  directly confirming the d<=2 threshold is the correct one for small-size hashing, at 40x the
  sample size of the original n=2 test.
- **162 pairs were different photos of the same real printing** (full-res distance>0) - correctly
  did NOT cluster in the vast majority (mean small-size distance 17.8, ranging 0-38); 19/162
  (11.7%) coincidentally landed at d<=2 anyway. Noted as a real but benign effect: since the
  underlying printing genuinely is the same, an incorrect "same upload" assumption still
  propagates a factually correct vote - not a correctness risk, just a documented imprecision in
  the "distance-0 means duplicate upload" model.
- **269 different-printing pairs** (false-merge check): **zero** landed at distance<=2 - minimum
  observed distance was 6, comfortably clear of the threshold.

### Projected wall-clock for the next full run

This run's own live numbers (no clustering active - PR #26's code, not this branch, is what's
actually running): ~2.65 candidates/sec observed, projecting **~0.73 days** for the full
166,422-candidate catalog. Bottleneck-split measurement (earlier in this doc) found 26-28%
cluster absorption in real samples; applying that reduction to the compute-bound majority of the
pipeline projects **~0.52-0.54 days (~12.6-12.9h)** for the next run, once `content_phash` is
backfilled - clustering as a zero-fetch DB read rather than a competing sequential pre-pass.
The one-time backfill itself (166,422 cards, small-size fetch, 5 concurrent workers) projects to
roughly **~2.8 hours** - a one-time investment, not a recurring cost; the ingest hook keeps
future new cards hashed automatically at near-zero marginal cost going forward.

### Out of scope this pass (logged, not built)

Art-region second hash (needs the frame-mismatch census's own value estimate first - separate
task, #119), multi-hash ensembles, deep-embedding dedup (violates the cheap-deterministic
discipline this whole engine is built on), `hash_size` re-tuning (parked until the art-hash
question is taken up), and wiring the d<=2 narrowing hint into `_compute_card`'s live candidate
matching (computed and tested, not yet consumed - see above).

## Iteration safety: run_id, purge, staleness guard (2026-07-16)

Full design/build detail lives in
[`docs/features/catalog-completion-plan.md`](catalog-completion-plan.md)'s Part 1 - this section
is the pointer from the pilot's own doc, stating the complete safety-property set this module
now guarantees, since Part 1 completes it rather than replacing anything below.

**Four properties, three pre-existing and one new:**

1. **Machine votes can never resolve a card by themselves** (pre-existing, unchanged) -
   `vote_consensus.resolve_weighted_consensus`'s human-backed gate: no matter how many
   `VoteSource.OCR`/`VoteSource.DEDUCTION` votes pile up, a card only reaches `RESOLVED` with at
   least one human-backed vote behind the winning outcome. This is the foundational invariant
   every stage of this project is built on - see the module's own opening paragraph.
2. **A killed/interrupted run is restart-safe** (pre-existing, unchanged) - the NULL-filter/
   `anonymous_id`-exclusion idempotence in `_eligible_base_queryset`, plus batch-flush
   checkpointing (see "Checkpointing" above): a plain re-invocation resumes cleanly, never
   double-votes, loses at most one in-flight batch on a kill.
3. **Revocability** (new, Part 1) - every machine vote now carries a `run_id` (a separate,
   nullable, indexed field on `AbstractWeightedVote` - `anonymous_id` itself is untouched, its
   exact-match reuse across invocations is what property 2 above depends on, so it could never
   be safely repurposed as a per-run stamp). `manage.py purge_machine_votes --run-id <id>` deletes
   exactly one invocation's votes and re-resolves every affected card, so a bad iteration can be
   cleaned up surgically without touching any other run's votes.
4. **Staleness guard** (new, Part 1) - every pilot command refuses to start if the DB has
   migrations applied that the running image's own code doesn't know about
   (`cardpicker.utils.find_stale_applied_migrations`) - automates the PR #24/#26 lesson (a
   `docker compose build` can report success while a BuildKit caching bug ships old code
   underneath) instead of relying on someone remembering to check image timestamps.

**Updated rebuild command, now required** (adds the git-SHA build-info bake - best-effort
visibility, logged at each command's startup, never itself the gate):

```bash
GIT_SHA=$(git rev-parse --short HEAD) docker compose -f docker/docker-compose.prod.yml build
```

**The post-purge invariant, stated precisely** (this is the safety property revocability rests
on - "corrected" without the exact statement isn't reviewable, so here it is verbatim against
the actual implementation, `cardpicker.management.commands.purge_machine_votes. verify_no_machine_only_resolutions`): after a real (non-dry-run) purge, every affected card is
**re-resolved from scratch** via the persisting consensus resolvers
(`resolve_and_persist_printing`/`resolve_and_persist_artist`/`resolve_and_persist_tag_votes`),
using whatever votes actually remain after the purge - not a diff against pre-purge state. The
command then asserts: for every affected card whose `printing_tag_status` is `RESOLVED`, at
least one of its surviving `CardPrintingTag` votes for that resolved printing has a human-backed
`source` (not `VoteSource.DEDUCTION`/`VoteSource.OCR`); identically for `artist_vote_status`
against the resolved artist, and for each individual tag whose `tag_vote_statuses` entry is
`RESOLVED_APPLY`/`RESOLVED_REJECT` against that specific tag's own surviving votes. **A card is
NOT required to return to its pre-purge status** - un-resolving as a consequence of losing
machine-only weight is the expected, correct outcome, reported separately
(`cards_unresolved_by_purge`), never a violation. Only a `RESOLVED` outcome with zero surviving
human-backed votes behind it is a violation - `resolve_weighted_consensus`'s own human-backed
gate should make that structurally impossible, so if it ever happens it means something upstream
broke, not that the purge did anything wrong.

**Cohort convention**: `run_id IS NULL` identifies the **pre-crash cohort** - every vote from
every invocation of this pilot before 2026-07-16 15:39 UTC. Any `run_id` value identifies the
**post-crash cohort** - stamped, individually purgeable, `PilotRunLedger`-tracked, from that
timestamp onward. The dividing line is that specific crash, not a "run completes naturally, then
stamping begins" boundary - see [[../troubleshooting.md]]'s "Entrypoint + migrate composition
traps" entry for what happened and why. Properties 1/2 above were never conditional on `run_id`
existing, so the crash changed nothing about correctness, only when stamping started - a
strictly better state than waiting for a natural completion that was never guaranteed to arrive
first.

**What the staleness guard does and doesn't catch**: it blocks a restart from an image older
than the DB's applied migrations (property 4) - the guard doing its job. It does NOT catch a
non-additive migration landing via `docker compose up` while a _different_, already-running
container is still on the old code, since that container never restarts and so never re-checks.
See the troubleshooting.md entry above for the operational rule this established.

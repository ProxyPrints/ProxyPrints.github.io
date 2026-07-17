# Printing-aware card tagging ("What's That Card?" vote queue)

_Current-state reference, as of 2026-07-16._ Full stage-by-stage build
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
  was added. `CanonicalPrintingMetadata` (OneToOne) holds only the
  Scryfall fields `CanonicalCard` doesn't (full_art, border_color, frame,
  frame_effects, promo_types, edhrec_rank, printings_count, released_at,
  lang), populated by `cardpicker/printing_metadata_import.py` +
  `import_scryfall_printing_metadata`. `CardPrintingTag.printing` FKs
  directly to `CanonicalCard`.
- **Consensus**: `cardpicker/printing_consensus.py::resolve_printing(card)`
  — weighted-vote formula, weight by source (user 1, admin
  `PRINTING_TAG_ADMIN_WEIGHT` default 5, AI/deduction/OCR
  `PRINTING_TAG_AI_WEIGHT` default 0.5; settings in
  `MPCAutofill/settings.py`). `PRINTING_TAG_MIN_VOTES` compares against
  _summed weight_, not row count. A winning group also needs
  `PRINTING_TAG_MIN_SHARE` (default 0.6) of total weight **and** at least
  one non-AI vote — `vote_consensus.is_human_backed_source()` is the one
  place that knows which `VoteSource` values are machine-derived, so no
  volume of AI-only votes can resolve a card alone.
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
- **No-match reason tags**: six `Tag` rows (`custom-art`, `altered-frame`,
  `upscaled`, `ai-art`, `no-collector-line`, `non-english`) seeded by
  `manage.py seed_no_match_reason_tags` (a management command, **not** a
  migration — see [[../lessons.md]]'s data-migration-vs-command-seeding
  entry). **These exact strings are a federation interchange contract**
  (other instances consuming our vote export expect them) — renaming any
  of them is a breaking change. Deliberately a separate taxonomy from
  `DEFAULT_TAGS` even where concepts overlap (`upscaled` vs `Upscaled`
  etc.), since one is cast at upload-time from filename parsing and the
  other is a human's queue-time judgment — kept exact-string-distinct so
  the two vote populations don't silently merge.
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
  votes (weight `PRINTING_TAG_AI_WEIGHT`) for cards whose printing is
  logically entailed by data already in the catalog — D1 (name matches
  exactly one `CanonicalCard`, cross-verified against Scryfall's own
  `printings_count`) and D2 (name + `Card.expansion_hint` narrows to
  exactly one row) tiers. Idempotent/resumable (the "no existing vote"
  eligibility check doubles as the checkpoint). `VoteSource.DEDUCTION`
  (pure logical inference) and `VoteSource.OCR` (Stage 8, image-inspecting)
  are a label split of what was originally one `VoteSource.AI` value —
  same weight/gate treatment for both, see `models.py`'s `VoteSource`
  docstring. Production run: 28,112 votes written, 0/28,112 later
  resolved a card on their own (human-backed gate verified at scale).
- **Moderation layer**: builds on the same consensus system — see
  [[moderation.md]] for the sensitive-tag taxonomy, privileged-approval
  gate, and its own Reports/Drives review surface.
- **Unified question feed**: `GET 2/questionFeed/` replaces the old
  printing/artist/tag/moderation tab switcher with one typed, prioritized
  stream (`confirm_suggestion` → contested pairs → `moderation` → fresh
  unresolved; "dumb ranked union," no cross-tier scoring). Full rationale
  in `journal/2026-07-14-queue-question-feed-design.md` (gitignored,
  local-only). **Known v1 property, not a bug**: at current volume a
  voter only sees tier-1 (`confirm_suggestion`) questions until all
  ~28k are exhausted — an interleaved/weighted union is the likely v2
  fix, out of scope for v1. Every tier excludes `(card, tag)` pairs the
  requesting `anonymous_id` already voted on.
- **Remaining-work count**: `get_remaining_estimate()` returns
  `QuestionFeedCounts` (`schemas/schemas/QuestionFeedCounts.json`), not a
  single number. `total` is a `.distinct().count()` union across
  printing/artist/tag categories, bounded by catalogue size - the
  non-overlapping "cards needing review in any category" figure.
  `confirmable`/`contested`/`fresh` mirror the feed's own three tiers and
  are independent metrics, **not** a partition of `total` - a card can
  count toward more than one bucket (e.g. AI-suggested-but-unconfirmed
  printing plus a still-fresh artist question). A fresh, untouched card
  defaults to `UNRESOLVED` on both `printing_tag_status` and
  `artist_vote_status` simultaneously, which is why a flat sum of the
  three category counts (the pre-fix implementation) over-counted every
  such card 2-3x. `QuestionFeed.tsx`'s headline leads with `confirmable`
  ("N quick confirmations ready") when non-zero, falling back to `total`
  once nothing quick remains.

## Frontend architecture

- `frontend/src/pages/whatsthat.tsx` (renamed from `printingQueue.tsx`) +
  `QuestionFeed.tsx` render the single unified feed; the old standalone
  `PrintingTagQueue.tsx`/`GenericVoteQueue.tsx`/`ModerationQueue.tsx` tab
  switcher was deleted, its mechanics extracted into `cardPanel.tsx` and
  reused directly.
- `starburstShape.ts` — seeded PRNG (mulberry32) generates the animated
  starburst background, 5 precomputed frames per layer; skipped under
  `prefers-reduced-motion` (checked once via `matchMedia`).
- `cardPanel.tsx` — `position: sticky` (via `useStickyTop`, not a hardcoded
  navbar constant), full-bleeds to the viewport. Needs its own local
  stacking context (`position: relative` **and** an explicit non-`auto`
  `z-index`, together) on its wrapping `Col` — `position: relative` alone
  does not establish one, and the card's own `z-index: -1` otherwise
  escapes all the way to the page root and makes its interactive content
  unclickable at the hit-testing layer.
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
    now puts the card being asked about first in DOM order via Bootstrap's
    `order`/`order-md-*` utilities — at `md` and up this is a no-op (same
    candidates-left/card-right arrangement as before), but at mobile
    widths, where the two columns stack, the mystery card used to render
    _after_ every answer option, so a voter had to scroll past all the
    candidates before seeing what they were even being asked about.
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
    guess"). `identify_printing` items (and `confirm_suggestion` items
    without a `suggestedPrinting`) skip Level 1 entirely.
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
  `/whatsthat` funnel above: `frontend/src/features/card/
  DeckbuilderConfirmAffordance.tsx`, mounted from `CardSlot.tsx` right
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
- **Vote provenance (`voteSurface`)**: `AbstractWeightedVote.vote_surface`
  (backend PR #48, nullable additive field, already on
  `SubmitPrintingTagRequest`/`SubmitArtistVoteRequest`/
  `SubmitTagVoteRequest` in `schema_types.ts`) is now sent by every vote
  call in the `/whatsthat` funnel (`"question-feed"`) and by Level 0's
  own vote (`"deckbuilder"`). `ArtistVotePicker.tsx` — shared between the
  funnel and the card-detail-modal's `AttributeVotingPanel` — takes an
  optional `voteSurface` prop rather than hardcoding it, same pattern as
  its existing `onRateLimited` prop: the funnel passes
  `"question-feed"`, `AttributeVotingPanel` passes nothing (unchanged).
  Every other voting surface (`PrintingTagPicker.tsx`, `TagVotePicker.tsx`,
  `ReportsPanel.tsx`) is untouched — `voteSurface` stays `undefined`
  there, not a guessed value.

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
  (`PrintingTagPicker.tsx`, `starburstShape.ts`, `cardPanel.tsx`),
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
  vote when the parse matches **exactly one** of the card's own
  name-candidates - weak OCR is made safe by this validation rail, not by
  trusting the OCR output itself. Never writes `is_no_match`.
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
  "Real pilot run results" for how often this cap fires).
- **Pass 2, fallback** (`local_fallback.py`, `local-fallback-v1`): fires
  only when pass 1 (either engine) produced no accepted vote for a card -
  the old-border-frame case (no collector line printed on the card face
  at all, just an "Illus. `<artist>`" credit). Evidence-combination model
  across border-color sample, artist-name OCR fuzzy match, and set-symbol
  phash (found unreliable in practice, kept but effectively disabled via
  a strict threshold - see `local_fallback.py`'s module docstring for the
  full negative finding): a vote is cast only when the intersection of
  every sub-check that produced a reading narrows to exactly one
  candidate.
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

## Key files

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

## Known gaps

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
  value once the response lands) isn't linear in vote count once AI/admin
  weights are involved - can't fully verify the two never visibly diverge
  against MSW mocks alone.
- Border Color's v1 chip set omits gold/yellow `border_color` values, and
  the frame_effects chip set omits `legendary`/`inverted` despite higher
  raw counts than the chips that made the cut - both flagged as judgment
  calls in Stage 7 above, worth revisiting with real moderator/voter
  feedback.
- Stage numbering: Stage 4 (no-match reason tags, merged as PR #12),
  Stage 5 (tag identity/presentation decoupling via `Tag.display_name`,
  merged as PR #14), and Stage 6 (this document's current stage —
  deductive printing-tag backfill) reflect three concurrently-developed
  branches sharing this one doc file, numbered in landing order to avoid
  collisions.
- **Future work: anonymous_id trust scoring via honeypot questions**
  (2026-07-15, raised during Stage 8's pilot run). Idea: periodically
  serve a voter a card whose printing is already known with very high
  confidence — ideally an already-`RESOLVED` card (real human-backed
  consensus), Stage 6's D1 tier as a fallback pool (0 false positives
  across 27,424 live cards, but still AI-derived, not independently
  human-verified, so using it as "trusted" ground truth to police other
  submissions has a circularity worth being honest about) — without
  telling the voter it's a check, and score their `anonymous_id` based on
  whether they answer correctly. Deprioritize/downweight low-scoring
  anonymous_ids to make data poisoning more costly. Same crowdsourcing
  pattern as reCAPTCHA/Mechanical-Turk gold-standard questions. Known
  limitation before this is worth building: `anonymous_id` is a
  client-generated, trivially rotatable value
  (`frontend/src/common/anonymousId.ts`) with no persisted identity —
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

**Full-catalog run: not yet fired.** This report is the synthesizing deliverable requested
before that authorization - awaiting explicit owner go-ahead.

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

# What's That Card — question model, selection, and composition

**Status: RATIFIED 2026-08-11.** The governing document for `/whatsthat` — its
question model, selection policy and composition contract.

## 0. Precedence — what this replaces, what survives

Replaces, and the replaced text becomes historical:

| Document                                                                                                              | What it loses                                                                                                                                       |
| --------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`proposals/mockups/wtc-rebuild/SPEC-wtc-rebuild.md`](../proposals/mockups/wtc-rebuild/SPEC-wtc-rebuild.md) §2        | The seven-shape inventory and its Level 1/2/3 interaction prose. The ladder it describes was removed by #728 and its file:line citations are stale. |
| [`proposals/mockups/wtc-rebuild/SPEC-wtc-rebuild.md`](../proposals/mockups/wtc-rebuild/SPEC-wtc-rebuild.md) ANNEX B   | The "degrade shape b to shape d" stopgap. Superseded by §3 below.                                                                                   |
| [`proposals/mockups/wtc-rebuild/DESIGN-REPASS-2026-08.md`](../proposals/mockups/wtc-rebuild/DESIGN-REPASS-2026-08.md) | Folded in whole. Its six rules survive as §5 and §7; its roadmap table was never updated and is discarded.                                          |
| [`proposals/mockups/wtc-rebuild/wtc-mockup.html`](../proposals/mockups/wtc-rebuild/wtc-mockup.html) (2026-07-24)      | Ceases to be the visual authority. It predates amendments A13/A16/A17 and shows a page structure this document contradicts.                         |
| [`printing-tags.md`](printing-tags.md) "Frontend architecture"                                                        | Its claim that "the interaction contract is unchanged" is false and is withdrawn.                                                                   |

Survives, still binding, not re-transcribed here:

- [`SPEC-wtc-rebuild.md`](../proposals/mockups/wtc-rebuild/SPEC-wtc-rebuild.md) §1 — the token table and per-element sizing/colour values.
- [`SPEC-wtc-rebuild.md`](../proposals/mockups/wtc-rebuild/SPEC-wtc-rebuild.md) §3 — the container-first layout policy: components style against
  their container, the layout folds by flex-wrap and `clamp()`, viewport breakpoints are for
  structural reordering only. Restated as §8.
- [`SPEC-wtc-rebuild.md`](../proposals/mockups/wtc-rebuild/SPEC-wtc-rebuild.md) §4 — react-bootstrap primitives, no new dependencies.
- The chip taxonomy as corrected against the catalogue (PR #767, #768). Restated as §7.

## 1. The principle

**Ask the cheap, reliable question first. Let the expensive one fall out.**

Illustration and frame are easy to establish and hard to get wrong. A printing confirmation
asks the user to vouch for border, artist credit, set symbol, collector line and finish at
once. It is the most expensive question available and the one that pollutes data when wrong.

The evidence for this is in our own corpus. Of scans humans have declared not-an-official
printing, **altered-frame is 6,165 cards against custom-art's 198** — thirty to one. Those
are scans where the art matches and the frame does not. The feed currently offers no way to
say that, so the user skips and we learn nothing, or confirms and we record a printing that
is not true.

## 2. What the machine must have matched before we ask for a printing

All four: **border, artist credit, set symbol, collector line.** Recorded, never inferred —
`CardScanLog.evidence_types_used` is the field, and it must be populated for the claim to be
made. The four values it can carry are `"border"`, `"artist"`, `"symbol"`, `"collector_line"`
(`cardpicker.local_calculate_verdicts.calculate_fallback_verdict`, 2026-08-11). The first
three FILTER `CandidatePrinting` survivors as well as being recorded; `collector_line` is
RECORDED ONLY — "present" means `ImageEvidence.collector_line_collector_number` is non-empty
(a set code with no number is a much weaker read, matching every printing in the set, so it
does not count) — and it never filters, never changes a `skip_reason`, and never changes a
`CardPrintingTag` confidence. That asymmetry is deliberate: folding it into the same filter as
the other three would change which candidates a machine vote can survive against, and no
change to machine votes was in scope for adding it.

- All four matched → a printing confirmation may be offered. It must still carry escapes
  that produce better data rather than a bare skip.
- Any element unmatched → do not ask for a printing at all. Ask the question that fills the
  gap. Every such question is cheaper, more reliable, and narrows the printing for free.

**Correction (PR implementing §3's selection, 2026-08-11):** `CardScanLog.evidence_types_used`
does not carry a "collector line" value and cannot — the fallback calculator that populates it
(`local_calculate_verdicts.calculate_fallback_verdict`) records only its own three sub-checks,
`border`/`artist`/`symbol`; the collector line is the precondition that gets the calculator
running at all, not one of its recorded outcomes, so a fourth value was never produced by any
code path. The gate this PR ships checks the three that actually exist. Measured live the same
day: 0 of 110,130 confirm-eligible cards carry a `CardScanLog` row with all three recorded, and
the field is essentially unpopulated for the confirm-eligible population specifically regardless
of vocabulary size — a MATCHING calculator run never writes a `CardScanLog` row at all (only a
skip does), so the population this gate governs almost never has a row to read in the first
place. See `cardpicker.question_feed._KNOWN_EVIDENCE_TYPES` for the vocabulary and this PR's own
report for the measurement.

**Resolved (§10 ruling 3):** three-of-four gets no special tier. The gap names the
question — if the collector line is the unmatched element, ask about the collector line.
Route to the gap, no extra tier: a tier earns its place only if it changes what we ask.

## 3. Selection — which question this image gets

Selection is driven by **which evidence this image is missing**, not by a lane ratio and not
by a fixed tier order.

Pools remain the serving mechanism and the pooling substrate is unchanged — scheduled warms,
shared cache, read-time staleness re-check, per-voter exclusion. What changes is the
partitioning: pools are organised by missing-evidence dimension rather than by the four
tier-named lanes.

The lane-share mix rotation merged in #763 (`QUESTION_FEED_CONFIRM_MIX_WEIGHT` and siblings,
defaults 3/2/1) is **interim**. Those weights were chosen by an implementing worker, never
measured, and flagged as such. Under this model there is no lane ratio to tune; the rotation
and its weights are deleted. Tracked in #766.

**Implemented (#766, 2026-08-11):** the four lanes (confirm/contested/cold/likely-resolve) are
NOT renamed to evidence dimensions — `TypeEnum` has exactly four servable question types
(`confirm_suggestion`/`identify_printing`/`artist`/`tag`), and there is no per-element type a
missing border, symbol or collector-line reading could route to on its own; inventing one is
frontend + schema work outside a backend-only selection change. What ships instead is a GATE at
`confirm_suggestion`'s one construction site: a card is built as `confirm_suggestion` only when
its evidence is complete (§2), and every other card — including a card with a machine printing
suggestion but incomplete or absent evidence — falls through to the SAME `identify_printing`
question its tier already produces for a card with no suggestion at all, which is the closest
existing "ask the question that fills the gap" available without a new type: it presupposes
nothing and narrows the printing regardless of which element is missing. The confirm/contested/
cold LANE structure and their pools are otherwise unchanged; only tier 1's gate and the (now
fixed, no-longer-weighted) waterfall order changed. See `cardpicker.question_feed`'s own
"Evidence-gated printing-confirmation policy" docstring for the mechanism and this PR's report
for the measured before/after served mix.

A candidate grid is only a shortlist when the machine actually narrowed it. That requires
`CardScanLog.survivor_pks`, which is populated on 0 of 4,435,119 rows today. Until it is,
"every printing matching the name" is not a shortlist: measured live, an ambiguous card is
served a mean of 13.6 candidates and up to 50.

## 4. Diversity — a pool is not a slice

Measured 2026-08-10: all 500 entries of the confirm pool shared a single `date_created` day,
because `_build_pool_confirm` orders by `date_created` and takes the head. The feed held
137,050 review-queue cards and was serving the same 500 from one 2021 import batch to
everyone, indefinitely. Every pool builder must **sample its population, never take its
head.**

## 5. Composition — the page is one tree that composes itself

The page renders exactly what the current question needs. An answer may summon the next
element. Nothing renders "just in case".

Removing the Level 1/2/3 ladder (#728) meant _there is no fixed sequence — the page composes
per question._ It was implemented as _render every element on every question_, which is the
opposite, and is why a one-tap confirm currently ships a chip panel and a full candidate grid
alongside it.

Rules:

1. Render only what the current question needs.
2. An answer may summon the next element; elements do not pre-render awaiting an answer.
3. Anything contradicted by a vote disappears rather than dimming.
4. The subject card is the anchor and is always present.
5. Never ask for a claim the user has not been shown the evidence to make.

## 6. Answer symmetry

**Confirming and correcting must cost the same.** "Is it borderless? Yes / No" is acceptable
only if "no — it's a black-bordered extended art" is also one interaction. When the negative
is more expensive than the positive, people reflex-confirm, and the result is exactly the
polluted data §1 exists to prevent.

**Yes and Skip are present on every confirmation.** Abstaining is never harder than
answering.

A non-confirmation must bounce us into collecting more data, never into nothing.

## 7. Question types

Each voting axis is a first-class question. Chips are the answer surface for an axis, not a
filter panel parked on a question with nothing to narrow.

### confirm_suggestion — offered only under §2

Renders: subject card, the suggested printing, the answer set. No chip panel, no candidate
grid.

| Answer             | Casts                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Yes**            | The printing.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **Same art, but…** | The illustration vote — and therefore the artist vote (§7.2). Summons the frame/border chips to narrow what actually differs. This is the productive branch, not a rejection.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **Not this art**   | Casts a `CardIllustrationRejection` for the suggested printing's `illustration_id` (`2/submitIllustrationRejection/`, `illustration_vote.cast_illustration_rejection`) - a negative signal on the suggested illustration, recorded rather than discarded. Routes to identification, not to the frame chips. Retained deliberately (owner ruling, 2026-08-11): it is the only answer distinguishing "wrong details" from "wrong picture", and the two lead to different next questions. Without it a user looking at entirely wrong artwork could only Skip, discarding usable evidence. See `docs/features/printing-tags.md`'s illustration-elimination section for the full mechanism (separate model from `CardIllustrationVote`, one positive machine vote implies rejections for every other name-matched candidate artwork, elimination consensus narrows what `confirm_suggestion` re-serves). |
| **Skip**           | Nothing. Records an abstention.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |

**"Same art, but…" casts the illustration vote on tap** (owner ruling, 2026-08-11), and
therefore the artist vote with it. The claim is independently true regardless of what the
frame turns out to be, so it is recorded whether or not the user completes the follow-up.

### illustration — the cheap, reliable question

**Renders:** art crops only, never framed card renders. Casts an illustration vote via
`2/submitIllustrationVote/` or rejection via `2/submitIllustrationRejection/`.

**An illustration vote is an artist vote.** `illustration_id → artist` is functional, and
`illustration_vote.py` already derives it through `DERIVED_ARTIST_VOTE_SURFACE`, with a guard
for combined-credit strings.

**It never casts a printing vote, whatever the group size.** The `>= 2` cluster rule is
deleted, not tuned: group size is orthogonal to which question to ask. An illustration
printed once in Scryfall is not a printing match, because the thing being identified is a
proxy scan which may be an unofficial variant of that illustration — and per §1 the most
common unofficial variant in our corpus is precisely an altered frame.

**Candidates are grouped by unique `illustration_id`.** The illustration question deduplicates
candidates that share the same artwork identity, so one artwork is asked about once per card,
not per printing. Backend builder: `_illustration_item()` in `question_feed.py`. Frontend
component: `IllustrationQuestion.tsx`. Routing (§3): served first in the remainder tier,
before printing questions, because it is the cheapest answerable and one answer settles the
artist for free.

### identify_printing — search-led

Renders: contextual search, custom art as a first-class option, mark-unidentifiable, Skip.

The search field states its own scope, and the scope follows the question — printings for
this card, artist for this card, or a different card entirely. `post_printing_candidates`
already accepts a `query` and ranks by name similarity with expansion-hint boosting;
`APIGetPrintingCandidates` already sends one, and `PrintingTagPicker` already uses it. **No
new backend is required.** The comment in `QuestionFeed.tsx` claiming no search endpoint
exists is false and is withdrawn.

A candidate grid appears only when there is a genuinely narrowed shortlist to show (§3).

### frame / attribute narrowing

Summoned by a question that needs them, never standing open. Axes, measured against the
catalogue (113,224 printings):

- **Border, exclusive**: Black / White / Silver / **Borderless**. Scryfall stores borderless
  in `border_color`; it is a border value, not a treatment.
- **Frame era, exclusive**: Old / Modern / Future.
- **Treatment**: Showcase XOR Extended Art. **Full Art is independent** and combines freely
  with either and with any border colour.

Only exclusions the data supports are encoded. Borderless and full art co-occur on 4,902
printings — 82% of all borderless printings. Cathars' Crusade (INR 483) is full art, showcase
and borderless at once.

### artist — kept for one case

When the illustration cannot be identified but the credit line is legible. Renders the picker
alone.

### tag — kept

A single attribute asked cold, with no printing context. Retained for the contexts where we
genuinely need one attribute answered on its own.

### border — asked cold (2026-08-11, per-element question types)

The border colour axis asked on its own: renders the plain scan with the four
`BORDER_COLOR_GROUP` chips as the entire answer surface (Black / White / Silver / Borderless,
additive-only scope - no new vote model, endpoint, or schema shape beyond the `border`
question-type value). Built as `_border_item` in `question_feed.py` + `BorderColorQuestion.tsx`
(votes through the same `useTagVoting` path as the narrowing chips, §5 rule 1: only what the
current question needs). No reveal treatment - a non-candidate question like artist/tag.

**Symbol is not built as a question type; the collector-line question is deferred to its own
PR** (2026-08-11, same scope; the deferral is the owner's ruling). These are different
outcomes. The set symbol has no vote target - nothing in the vote system records a
set/expansion judgement - and reading one by sight is expert knowledge a lay user cannot
reliably give, so a `symbol` question would harvest guesses rather than votes; it stays a
gap - documented, not built. The collector line is NOT ruled out: a collector number
identifies a printing. `CanonicalCard` carries a unique constraint on `(expansion, collector_number)` (`canonicalcard_unique_expansion_collector_number`, `models.py:118`), so
a set code plus a collector number resolves to exactly one printing by construction - the
pipeline already resolves printings this way internally (`local_calculate_verdicts.py:950`,
`local_lands_identify.py:468`). A collector-line answer therefore casts an ordinary
`CardPrintingTag` - no new vote model is needed. The first version needs no typing or
search: where candidates exist, present their collector numbers as the options and let the
user pick the one printed on their card; each option is a printing, so the pick casts a
printing vote. Its phrasing must make clear the user is confirming the whole printing
(frame, artist credit and all), because a printing vote is the expensive full claim.

## 8. Layout technique (restated from SPEC §3, unchanged)

Container-first. Components style against their container via `@container`, never the
viewport. The layout folds continuously through flex-wrap, `clamp()` and auto-fill/minmax.
Viewport breakpoints are reserved for structural reordering only, and exactly one is
permitted on this page. No horizontal scrollers. No fixed per-breakpoint font sizes. **A
fixed-pixel width on a layout column or rail is a defect** — the `.wtc-panel` 640px centre
column and 360px `.wtc-context` rail that appeared in a task directive were never in any
spec, and contradict this section.

## 9. What must change in the current build

- `confirm_suggestion` stops rendering the chip panel and the candidate grid (§5).
- The `>= 2` illustration-cluster rule is deleted (§7.2).
- Singletons render as illustrations and cast illustration votes (§7.2).
- Pools sample rather than take the head (§4), and re-partition by missing evidence (§3).
- The interim mix rotation and its weights are removed (§3, #766).
- `survivor_pks` and `evidence_types_used` are backfilled, on the streaming conveyor.
- Shape (d)'s search is wired to the endpoint that already exists (§7.3).

## 10. Rulings ledger

All items ruled 2026-08-11. Nothing in this document is awaiting a decision.

1. **"Not this art" is retained** as a distinct `confirm_suggestion` answer (§7.1). The
   governing reason, in the owner's words: whichever question gets the most data. Skip
   discards evidence; a negative illustration signal does not.
2. **"Same art, but…" casts its illustration vote on tap** (§7.1), and therefore the artist
   vote with it.
3. **Three-of-four evidence gets no special tier** (§2). The gap names the question: if the
   collector line is the unmatched element, ask about the collector line. "Route to the gap"
   and "ask about the missing element" are the same rule. A printing confirmation is not
   offered until all four elements match.
4. **`border` becomes a first-class question type; `symbol` is ruled out, `collector_line`
   is deferred to its own PR** (§7.7). Border adds the `border` question-type value, the
   `_border_item` feed builder, and the `BorderColorQuestion` render branch - the answer
   surface is the four `BORDER_COLOR_GROUP` chips, casting real `CardTagVote`s through the
   existing chip machinery, so no new vote model or endpoint is required. Symbol is ruled
   out against §5: set symbols by sight are expert knowledge, so the question would harvest
   guesses, not votes. Collector line is deferred, not ruled out (owner's ruling, same
   date): a collector number identifies a printing - `CanonicalCard`'s unique constraint on
   `(expansion, collector_number)` (`canonicalcard_unique_expansion_collector_number`,
   `models.py:118`) resolves set code plus collector number to exactly one printing by
   construction, as the pipeline already does internally (`local_calculate_verdicts.py:950`,
   `local_lands_identify.py:468`) - so a collector-line answer casts an ordinary
   `CardPrintingTag`, no new vote model. First version needs no typing or search: where
   candidates exist, present their collector numbers as the options and let the user pick
   the one printed on their card; each option is a printing, phrased as a whole-printing
   confirmation (frame, artist credit and all), since a printing vote is the expensive
   full claim. Symbol stays unbuilt; the collector-line question is a documented next PR.

Earlier rulings folded into the body above: illustration votes never imply a printing
whatever the group size; each voting axis is a first-class question; confirming and
correcting cost the same; Yes and Skip present on every confirmation; the standalone artist
question survives for legible-credit-but-unidentified-illustration; the standalone tag
question survives for asking one attribute cold; borderless is a border colour; pools sample
rather than take the head; no standalone calculators, and the monolith is the streaming
monolith.

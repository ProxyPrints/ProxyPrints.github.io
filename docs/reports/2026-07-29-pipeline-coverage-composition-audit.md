# Pipeline coverage — the composition audit (2026-07-29)

Read-only audit. No write, no management command, no migration, no deploy.
Every live figure was queried against production Postgres via
`docker exec mpcautofill_django python manage.py shell -c "..."` on
2026-07-29; the query behind each number is given inline.

**The question this answers**, put by the owner: _"have we verified that with
all of our deletions that the pipeline actually still catches all that it aims
to? do we need to do any more reordering or culling? readd anything we
dropped?"_ Every change of the last three days was verified in isolation.
Nothing had checked them **in composition**. This does.

**Commits.** Production runs a build carrying `stage-d-illustration-v2`
(PR #565, `85d88bfe`) and `JOIN_KEY_ARTIST_MISMATCH_SKIP_REASON` (PR #563)
but **not** `local_fallback`'s skip-reason constants (PR #584, `d0442239`) and
**not** evidence-transfer `run_id` stamping (PR #603, `e6c6429a`) — verified by
importing the modules inside the running container, not inferred. So production
sits between `d4b53b4d`/`a250329a` and `48cccce8`. `origin/master` is
`e6c6429a`. Findings are marked **LIVE** (true of the deployed build) or
**LATENT** (true of master, not yet deployed).

**Baseline.** `origin/master` at `e6c6429a`. Twenty PRs were open at audit
time; where one changes a finding it is named. None of the top four findings
below is touched by any open PR.

---

## 1. Answer to the owner's three questions

### Q1 — does the pipeline still catch everything it aims to?

**No.** Three channels are down, and one of them is down for a reason nobody
has recorded.

1. **Frame-style chips (`Old Border` / `Modern Border`) — 0 machine rows, no
   substitute, unreachable from either engine.** The 2026-07-29 purge deleted
   them; nothing re-derives them; and the only code path that ever cast them is
   not wired into the pooled runner or the conveyor. **142,633 votes are
   re-derivable from stored evidence today with zero image fetches.**
2. **Bleed-edge chips (`appropriate-bleed`) — 0 machine rows**, same three
   reasons. **2,786 re-derivable**, also with zero fetches.
3. **Border chips survived only by accident of duplication.** They were cast
   under two identities computing the same thing from the same classifier. The
   purge took one (`local-fallback-v1`, 0 rows); the other
   (`layout-class-cast-v1`, 216,476 rows) is what the catalogue still has. Had
   the duplication been culled first, the purge would have zeroed border colour
   too.

The **known hole is smaller than 53,966 and differently shaped**. Of the
destroyed chips, the border share is fully covered by a surviving channel; the
frame and bleed shares are not covered by anything. The residual gap is not
53,966 rows of loss — it is **145,419 votes that stored evidence can produce
right now and no code path will produce**.

Everything else the pipeline aims to produce, it still produces. All eleven
Stage C extractors are at 220,579/220,579 coverage and reachable from both
engines. Stage D's four calculators all write. No skip reason declared in
`docs/reference/skip-reasons.md` was found to be falsely claimed live.

### Q2 — is more reordering or culling needed?

**Reordering: yes, one real defect and one class of missing guard.**

- **The illustration calculator has no exclusion in the slow-path queryset.**
  `_slow_path_eligible_cards_queryset` excludes cards the _fallback_ calculator
  voted on, and nothing else. `local_calculate_verdicts.py`'s own comment admits
  the wiring is absent — "the slow-path queryset **would need an additional
  exclusion** for this identity's votes". So a card the illustration calculator
  resolves in a run is still routed to a human reviewer in the same run. PR #604
  does not close this. **LIVE and LATENT.** Consequence is bounded today only
  because `stage-d-illustration-v2` has never run; the read-only replay recorded
  in `docs/pipeline-fidelity-gate.md` projects ~3,233 printing votes, so this
  fires on the first `-v2` run.
- **Four Stage D readers gate on one extractor key and then read six
  extractors' fields.** Every printing-channel calculator filters
  `extractor_versions__has_key="collector_line_ocr"` and then reads
  `layout_class`, `illus_anchor_fired`, `legal_line_*`, `artist_ocr_name`,
  `symbol_phash` and `image_is_truncated` ungated. Two of those degrade in the
  **strict** direction — a missing `artist_ocr` makes `illus_anchor_fired` read
  `False`, which classifies every frame as `modern` and can veto a genuine
  old-frame card as `frame-mismatch`, a skip reason deliberately **not**
  rescannable, so the wrong conclusion is permanent for that content hash. The
  correct pattern exists three times in the same codebase
  (`local_detect_ai_art.py`, `local_lands_identify.py`,
  `local_layout_class_cast.py` all declare and check `REQUIRED_EXTRACTOR_KEYS`)
  and was simply not applied to `local_calculate_verdicts.py`. This is the same
  bug class as the `stage-d-illustration-v1` gate that went undetected for
  weeks.
- Stage C's internal order is fine **today** and mostly crash-enforced (a
  reorder raises `UnboundLocalError`), with one exception noted in §5.

**Culling: yes, one clear cull and two questions to settle.**

- **Cull `image_evidence.extract_card_evidence`'s vote cast, or wire the
  function.** `extract_card_evidence` has **zero production callers** — only
  `cardpicker/tests/test_image_evidence.py`. It is the only non-pilot caller of
  `cast_border_attribute_vote`. Both engines bypass it and call
  `compute_card_evidence` directly.
- **`local-name-frequency-v1`: retire.** It has never been invoked — zero
  `PilotRunLedger` rows for `local_name_frequency_elimination`, ever. The
  fidelity gate calls it "under diagnosis"; the diagnosis is that nobody has run
  it. That is a decision to make, not a bug to find.
- **`PrintingTagVote`: 0 rows, and its only machine writer has never run.**
  Confirmed as the brief predicted. PR #599 is the decision doc.

### Q3 — what must be re-added?

Ranked by consequence:

1. **Frame-style chips — 142,633 votes** (133,627 `Modern Border` + 9,006
   `Old Border`), derivable from `ImageEvidence` with no image fetch.
2. **Bleed-edge chips — 2,786 votes** (`appropriate-bleed`, polarity
   `NOT_APPLICABLE`), likewise.
3. **Border chips for the ~2,648-card arrears** since `local_layout_class_cast`
   last ran (2026-07-24): 219,124 readings stored, 216,476 cast.
4. **Nothing else.** No other purge removed something nothing re-derives; the
   `local-fallback-v1` printing votes were retired by ratified ruling and their
   replacement (`stage-d-fallback-v1`) has 30,299 rows; the 114,239 `CardScanLog`
   rows were a deliberate purge of a retired engine's history.

**The re-derivation is a WRITE and this audit did not perform it.** It needs an
owner authorisation. It also needs a caster that does not exist yet: the only
code that casts these two chips is inside the live-fetch pilot, so re-deriving
them through the existing path would mean re-fetching ~220,000 images to
recompute facts already sitting in the database.

---

## 2. The per-channel table

`Y`/`N` = reachable from that engine. **POOLED** =
`run_image_evidence_cohort`; **CONVEYOR** = `stage_e_dispatch`; **CMD** = the
standalone management command that is the channel's only other entry point.

### 2a. Vote channels

| #   | channel (`anonymous_id`)          | produces                                                       |                   live rows | POOLED | CONVEYOR | CMD                                | state                                         | next action                                         |
| --- | --------------------------------- | -------------------------------------------------------------- | --------------------------: | :----: | :------: | ---------------------------------- | --------------------------------------------- | --------------------------------------------------- |
| 1   | `stage-d-join-key-v1`             | `CardPrintingTag`                                              |                      57,947 |   N    |    Y     | `local_calculate_verdicts`         | HEALTHY                                       | none                                                |
| 2   | `stage-d-fallback-v1`             | `CardPrintingTag`                                              |                      30,299 |   N    |    Y     | `local_calculate_verdicts`         | HEALTHY                                       | none                                                |
| 3   | `stage-d-slow-path-v1`            | `CardScanLog` `to-review` (router, votes by design = 0)        |                     135,293 |   N    |    Y     | `local_calculate_verdicts`         | HEALTHY                                       | add the illustration exclusion (§1 Q2)              |
| 4   | `stage-d-illustration-v2`         | `CardIllustrationVote` + `CardPrintingTag`                     | **0** (`-v1` legacy: 3 + 1) |   N    |    Y     | `local_calculate_verdicts`         | NEVER RUN AT `-v2`                            | run it; fix slow-path exclusion first               |
| 5   | `local-ocr-v1`                    | `CardPrintingTag`                                              |                      40,968 |   N    |    N     | `local_identify_printing_tags`     | FROZEN (last real run 2026-07-16)             | decide: redundant with `stage-d-join-key-v1`?       |
| 6   | `local-phash-v1`                  | `CardPrintingTag`                                              |                       8,270 |   N    |    N     | `local_identify_printing_tags`     | FROZEN (same run)                             | as above                                            |
| 7   | `local-name-frequency-v1`         | `CardPrintingTag` + `CardScanLog`                              |                       **0** |   N    |    N     | `local_name_frequency_elimination` | **NEVER RUN** — 0 ledger rows ever            | retire or run once                                  |
| 8   | `local-fallback-v1` (printing)    | `CardPrintingTag`                                              |                       **0** |   N    |    N     | none                               | RETIRED BY RULING — correct                   | none                                                |
| 9   | `local-fallback-v1` (border chip) | `CardTagVote` Black/White/Silver/Borderless                    |                       **0** |   N    |    N     | `local_identify_printing_tags`     | DESTROYED + UNWIRED, **superseded** by #12    | cull the caster                                     |
| 10  | `local-fallback-v1` (frame chip)  | `CardTagVote` Old/Modern Border                                |                       **0** |   N    |    N     | `local_identify_printing_tags`     | **DESTROYED + UNWIRED, NO SUBSTITUTE**        | build an evidence-reading caster; 142,633 derivable |
| 11  | `local-fallback-v1` (bleed chip)  | `CardTagVote` `appropriate-bleed` (`NOT_APPLICABLE` only)      |                       **0** |   N    |    N     | `local_identify_printing_tags`     | **DESTROYED + UNWIRED, NO SUBSTITUTE**        | same caster; 2,786 derivable                        |
| 12  | `layout-class-cast-v1`            | `CardTagVote` border chips                                     |                     216,476 |   N    |    N     | `local_layout_class_cast`          | HEALTHY, ~2,648 in arrears                    | re-run after the next Stage C pass                  |
| 13  | `residual-classify-v1`            | `CardArtistVote` 6,144 + `CardTagVote` `altered-frame` 6,144   |                      12,288 |   N    |    N     | `local_residual_classify`          | HEALTHY (frozen since 2026-07-18)             | none                                                |
| 14  | `art-hash-artist-v1`              | `CardArtistVote`                                               |                         981 |   N    |    N     | `local_residual_classify`          | HEALTHY                                       | none                                                |
| 15  | `ai-art-detector-v1`              | `CardTagVote` `AI-Generated`                                   |                       1,183 |   N    |    N     | `local_detect_ai_art`              | HEALTHY                                       | none                                                |
| 16  | `deductive-backfill-v1`           | `CardPrintingTag`                                              |                      28,109 |   N    |    N     | `deductive_backfill_printing_tags` | HEALTHY                                       | none                                                |
| 17  | `lands-artist-decomp-v1`          | `CardPrintingTag` 1,487 + `LandsAmbiguousResidue` 12,824       |                      14,311 |   N    |    N     | `local_lands_identify`             | HEALTHY                                       | none                                                |
| 18  | `scryfall-tagger-v1`              | `PrintingTagVote`                                              |                       **0** |   N    |    N     | `import_external_ip_tags`          | **NEVER RUN**; invisible to the roster tether | settle PR #599; PR #588 fixes the tether            |
| 19  | `evidence-transfer-v1`            | `CardScanLog` only (no votes, by design)                       |                          12 | **Y**  |  **Y**   | —                                  | HEALTHY                                       | none                                                |
| 20  | human (`user` UUIDs)              | `CardPrintingTag` 125 / `CardTagVote` 106 / `CardArtistVote` 6 |                         237 |   N    |    N     | HTTP views                         | HEALTHY                                       | none                                                |
| 21  | `cast_illustration_vote` (human)  | `CardIllustrationVote`                                         |                       **0** |   N    |    N     | `views.py` only                    | never exercised                               | none — a UI surface, not a calculator               |

Only **one** vote-writing channel out of twenty-one is reachable from the
pooled runner, and it writes no votes.

### 2b. Stage C extractor channels

All eleven live inside `compute_card_evidence`, which **both** engines call
directly. All at full coverage.

| extractor key        | version                 | rows carrying the key | POOLED | CONVEYOR | state                           |
| -------------------- | ----------------------- | --------------------: | :----: | :------: | ------------------------------- |
| `fetch_health`       | `fetch-health-v2`       |               220,579 |   Y    |    Y     | HEALTHY                         |
| `geometry_bleed`     | `geometry-bleed-v1`     |               220,579 |   Y    |    Y     | HEALTHY                         |
| `layout_class`       | `layout-class-v1`       |               220,579 |   Y    |    Y     | HEALTHY                         |
| `crop_coordinates`   | `crop-coordinates-v1`   |               220,579 |   Y    |    Y     | HEALTHY                         |
| `collector_line_ocr` | `collector-line-ocr-v2` |               220,579 |   Y    |    Y     | HEALTHY                         |
| `collector_line_tsv` | `collector-line-tsv-v2` |               220,579 |   Y    |    Y     | HEALTHY                         |
| `artist_ocr`         | `artist-ocr-v2`         |               220,579 |   Y    |    Y     | HEALTHY                         |
| `artbox_phash`       | `artbox-phash-v1`       |               220,579 |   Y    |    Y     | HEALTHY                         |
| `symbol_region`      | `symbol-region-v1`      |               220,579 |   Y    |    Y     | HEALTHY                         |
| `legal_line`         | `legal-line-v2`         |               220,579 |   Y    |    Y     | HEALTHY                         |
| `quality_signals`    | `quality-signals-v1`    |               220,579 |   Y    |    Y     | HEALTHY                         |
| `color_profile`      | _retired 2026-07-27_    |               218,025 |   —    |    —     | RETIRED, historical rows remain |

**Coverage gap, separate from any of the above**: 230,706 `Card` rows,
220,579 with an evidence row, **10,127 with none at all** (17 of which have no
`content_phash`, so nothing can key an evidence row for them). Every evidence
row that exists is CURRENT (`content_hash == card.content_phash` for all
220,579).

---

## 3. The four zero-row categories, kept apart

The brief asked that a zero not be reported as one undifferentiated fact. Every
zero above falls into exactly one of these.

**(a) Ran and was later purged, nothing re-derives it.** Channels 10 and 11.
This is the real hole.

**(b) Ran and was later purged, but a surviving channel covers the same
ground.** Channel 9. Loss is nominal; the duplication that made it survivable is
itself the finding.

**(c) Wired but never run.** Channels 7 (`local-name-frequency-v1`) and 18
(`scryfall-tagger-v1`) — each has a working management command and zero
`PilotRunLedger` rows for it, ever. Channel 4 (`stage-d-illustration-v2`) — the
code is deployed, the conveyor calls it, but no dispatch has run since the
`-v2` build went live at ~12:55 today (last `stage_e_streaming_dispatch` ledger
row: 04:02).

**(d) Retired deliberately, correctly, and the replacement is working.**
Channel 8. `local-fallback-v1`'s printing votes went to zero because a ratified
redundancy ruling stopped the caster;
`local_identify_printing_tags.RETIRED_PRINTING_VOTE_FAMILIES` enforces it by
_family_, not by literal, so a `-v2` rename cannot silently un-retire it. That
is the one deletion in this whole set that was done to a standard the others
were not.

**No channel was found in a fifth state — "code exists, nothing ever called
it" — except `extract_card_evidence`**, which is not a channel but the function
that was supposed to host one.

---

## 4. The wiring defect, stated precisely

This is the finding that generalises the artist-recovery defect PR #581 fixed,
and it is worse than that one was.

`image_evidence.extract_card_evidence` is a fetch-then-compute wrapper. Its
last act before returning is to cast the border-attribute chip. **It has no
production caller.** Both engines skip it:

- `run_image_evidence_cohort` splits fetch and compute across two pools and
  calls `compute_card_evidence` + `persist_evidence` directly.
- `stage_e_dispatch._run_stage_c` does the same.

Every reference to `extract_card_evidence` outside its own definition is a
docstring, a comment, or a test. So the vote cast it contains is unreachable —
and the three chip casters in `local_fallback.py` are reachable **only** from
`local_identify_printing_tags.run_pilot`, whose sole caller is its own
management command, which has completed exactly one real run in its history
(2026-07-16, `PilotRunLedger` id 2).

`local_fallback.py`'s module docstring states that these casters "still cast
their `CardTagVote` attribute chips under `local-fallback-v1`". That is true of
the pilot command and false of both pipeline engines — the same shape of claim
issue #577 was raised about: the string appears, the claim is not true.

A second consequence, easy to miss: **the pooled runner writes no votes at
all.** It writes `ImageEvidence`, per-extractor `CardScanLog` skips, and
`evidence-transfer-v1` anomaly rows. Every Stage D identity is conveyor-only.
A "full run" built on the pooled engine is a Stage C run; Stage D has to be
invoked separately, or the conveyor has to pick the work up. In production
`STAGE_E_STREAMING_ENABLED` is **True** (master's default is `False`), and the
pooled runner's `persist_evidence` writes are deliberately _not_ echo-suppressed
— only `_run_stage_c`'s are — so each pooled persist enqueues a conveyor
dispatch. **Not established**: whether the planned full run intends to rely on
that echo or to invoke Stage D explicitly. It matters, because the echo path
runs Stage D one micro-batch at a time under the streaming envelope.

---

## 5. Ordering — what nothing enforces

PR #604 (open) establishes the Stage D order as a correctness constraint —
join-key → fallback → illustration → slow-path — and adds the first tests that
construct the wrong order deliberately. It also establishes the asymmetry the
owner should keep: `run_id` narrows _a calculator's own progress_; it must never
narrow _an upstream verdict_, because a converged catalogue re-derives unchanged
upstream verdicts and writes nothing, so a run-scoped upstream predicate is
empty on every run and the downstream pass is a silent no-op that reports
success.

What #604 does **not** cover, and nothing else does either:

| dependency                                                                      | why it matters                                                                                                                                         | enforced by                                                                                  | failure direction                                                                                        |
| ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| illustration → slow-path                                                        | a card illustration resolves is still routed to a human                                                                                                | **NOTHING** — the exclusion is absent, and the code comment says so                          | wrong human work; not a no-op                                                                            |
| Stage C `artist_ocr` → join-key frame veto                                      | `bool(None)` ⇒ "anchor did not fire" ⇒ every frame reads `modern` ⇒ a real old-frame card can be vetoed `frame-mismatch`, which is **not** rescannable | **NOTHING**                                                                                  | permanent wrong skip                                                                                     |
| Stage C `artist_ocr` → illustration calculator                                  | its sole input is `artist_ocr_name`; a blank read writes a permanent `no-artist-ocr` row                                                               | **NOTHING**                                                                                  | permanent wrong conclusion                                                                               |
| Stage C `quality_signals` → join-key truncation veto                            | `image_is_truncated` null ⇒ falsy ⇒ the hard veto silently never fires                                                                                 | **NOTHING**                                                                                  | permissive; votes on a truncated image                                                                   |
| Stage C `layout_class` → border veto / border filter                            | `""` default is indistinguishable from "extractor abstained"                                                                                           | **NOTHING**                                                                                  | permissive                                                                                               |
| Stage C `legal_line` → copyright-year check, artist veto                        | blank reads as "nothing to compare"                                                                                                                    | **NOTHING**                                                                                  | permissive                                                                                               |
| manifest keys/versions ↔ `compute_card_evidence`                                | a version bump without a manifest edit leaves the resume filter skipping stale rows forever                                                            | comment only (_"Keep this set in sync"_)                                                     | silent; PR #590 tethers the keys                                                                         |
| `_split_new_printing_tag_votes` → `purge_and_write_votes`                       | `rows` is simultaneously purge scope and insert payload                                                                                                | docstring only                                                                               | stale row survives verbatim                                                                              |
| Stage C extractor order (`geometry_bleed` first, `crop_coordinates` before OCR) | downstream blocks read locals `geometry_bleed` assigns                                                                                                 | Python name scoping — a reorder raises `UnboundLocalError`                                   | loud crash; acceptable                                                                                   |
| `legal_line` compute before the OCR group                                       | the untruncated legal-line read is what feeds `artist_ocr_name` recovery                                                                               | **a real test** (`test_the_untruncated_legal_line_read_is_what_gets_stored`, with a control) | the best-enforced ordering in Stage C                                                                    |
| OCR group before `artbox_phash`                                                 | `artbox_phash` reads `collector_line_collector_number` / `illus_anchor_fired` via `.get()` with implicit `None`                                        | **NOTHING** — currently correct by position only                                             | if reordered: every frame classified identically, a real `artbox_frame_class` written, no skip, no error |

A structural note worth acting on: every Stage D reader gates with
`extractor_versions__has_key=...`, never `__contains={key: version}`. Only the
cohort resume filter, the dispatch filter, and `evidence_transfer` compare
versions. So a Stage D calculator consumes a `collector-line-ocr-v1` row exactly
as readily as a `v2` one — which is the mechanism by which an extractor version
bump fails to invalidate the conclusions drawn from the old version.

---

## 6. Culling and duplication

- **Border colour is computed twice from the same classifier.**
  `local_fallback.classify_border_color` backs both `cast_border_attribute_vote`
  (identity `local-fallback-v1`) and `local_layout_class_cast` (identity
  `layout-class-cast-v1`, which re-implements the vote construction rather than
  calling the caster, deliberately). One of the two is now unreachable from
  every engine. Cull it.
- **`local-ocr-v1` / `local-phash-v1` versus `stage-d-join-key-v1` /
  `stage-d-fallback-v1`.** The fallback pair was already ruled redundant and
  retired on exactly this reasoning — same decision model, same three readings,
  measured 11,825/11,825 agreement. The OCR pair is the same shape: a live-fetch
  engine and an evidence-reading calculator both parsing the collector line. The
  live-fetch pair has not run since 2026-07-16 and holds 49,238 rows between
  them. This is **not established** as redundant — no equivalent measurement has
  been done — but it is the obvious next application of the same doctrine, and
  it is the difference between a full run that fetches every image twice and one
  that does not.
- **`local-name-frequency-v1`** — the open retire-or-keep question. New fact:
  zero invocations, ever. It is not abstaining; it has never been asked.
- **`extract_card_evidence`** — either delete the vote cast inside it and let it
  be a test-only convenience wrapper (naming it as such), or delete the function
  and move its tests onto `compute_card_evidence`. Leaving a vote cast in an
  uncalled function is what made this hole invisible.

---

## 7. Verification — the numbers and the queries behind them

All queries run 2026-07-29 against production Postgres, read-only.

**Row counts per model.**
`for m in [...]: m.objects.count()` —
`Card` 230,706 · `CanonicalPrintingMetadata` 113,224 ·
`CardPrintingTag` 167,206 · `CardTagVote` 223,909 · `CardArtistVote` 7,131 ·
`CardIllustrationVote` 3 · `PrintingTagVote` **0** · `Tag` 31 ·
`CardScanLog` 2,616,031 · `ImageEvidence` 220,579 ·
`LandsAmbiguousResidue` 12,824 · `PilotRunLedger` 995.

**Per-identity vote counts.**
`m.objects.values("anonymous_id","source").annotate(n=Count("id")).order_by("-n")`
over each of the five vote models — the source of every "live rows" figure in
§2a. `local-fallback-v1` returns **no row in any of the five**.

**The purge delta.** `docs/pipeline-fidelity-gate.md`'s 2026-07-26 snapshot
records `local-fallback-v1` at 11,947 `CardPrintingTag` and 53,966
`CardTagVote`; both are 0 today. Every other identity in that snapshot is
within a few hundred rows of its 2026-07-26 value (`layout-class-cast-v1`
216,802 → 216,476; `local-ocr-v1` 41,023 → 40,968; `residual-classify-v1` and
`ai-art-detector-v1` unchanged). The purge was identity-scoped and hit exactly
one identity across two models.

**Per-tag machine votes.**
`CardTagVote.objects.exclude(source="user").values("tag__name","anonymous_id").annotate(k=Count("id"))`:

| tag                   | identity               |                       rows |
| --------------------- | ---------------------- | -------------------------: |
| Black Border          | `layout-class-cast-v1` |                    137,496 |
| Borderless            | `layout-class-cast-v1` |                     71,101 |
| White Border          | `layout-class-cast-v1` |                      7,472 |
| Silver Border         | `layout-class-cast-v1` |                        407 |
| altered-frame         | `residual-classify-v1` |                      6,144 |
| AI-Generated          | `ai-art-detector-v1`   |                      1,183 |
| **Old Border**        | —                      |                      **0** |
| **Modern Border**     | —                      | **0** (4 human votes only) |
| **appropriate-bleed** | —                      |                      **0** |

Of the eleven-tag attribute-chip taxonomy in `MPCAutofill/cardpicker/attribute_tags.py`,
**four** have a live machine channel, **two** are the destroyed-and-unwired
pair, and **five** (`Full Art`, `Showcase`, `Extended`, `Etched`,
`Future Frame`) have no machine caster at all — the first four by design (human
chips), `Future Frame` because `FRAME_VALUE_TO_CLASS` documents it as
unreachable from the classifier's signal set.

**Re-derivable populations** — the basis for every "derivable" figure in §1 Q3.
`classify_frame_style(parsed_a_collector_number, illus_anchor_fired)` evaluated
against stored `ImageEvidence`:

| derivation                           | query                                                                  |    rows |
| ------------------------------------ | ---------------------------------------------------------------------- | ------: |
| `Modern Border`                      | `.exclude(collector_line_collector_number="")`                         | 133,627 |
| `Old Border`                         | `.filter(collector_line_collector_number="", illus_anchor_fired=True)` |   9,006 |
| abstain (no reading)                 | remainder                                                              |  77,946 |
| `appropriate-bleed` `NOT_APPLICABLE` | `.filter(bleed_class="trimmed")`                                       |   2,786 |
| border chips available               | `.exclude(layout_class="")`                                            | 219,124 |
| border chips already cast            | `CardTagVote.objects.filter(anonymous_id="layout-class-cast-v1")`      | 216,476 |

Cross-check: `ImageEvidence.artbox_frame_class` — an _already stored_ frame-style
reading written by the `artbox_phash` extractor — holds `modern` 133,473 /
`old` 8,996 = 142,469, against the 142,633 the classifier derives from raw
fields. The 164-row gap is the `artbox_phash` extractor's own fetch-failure
skips. Either column supports the re-derivation; neither requires a fetch.

**Skip reasons.** 23 distinct values live, largest first: `no-text` 1,213,629 ·
`no-evidence` 700,295 · `ambiguous` 187,851 · `to-review` 135,293 ·
`no-clear-winner` 116,761 · `parsed-but-no-match` 47,693 · `unknown-set-code`
46,088 · `no-sub-check-evidence` 43,302 · `too-many-candidates` 39,150 ·
`fetch_failed` 37,975 · `no-marker-hit` 19,573 · `border-mismatch` 15,393 ·
`frame-mismatch` 7,455 · `multi-faced-v1` 3,408 ·
`disagreement-with-other-engine` 1,914 · `eliminated` 150 ·
`copyright-year-mismatch` 40 · `unfetchable-image` 31 · `no-artist-ocr` 14 ·
`transfer-content-hash-mismatch` 12 · `multiple-printings-one-illustration` 2 ·
`no-candidate-match` 1 · `no-hashable-candidates` 1.

`docs/reference/skip-reasons.md` was checked value by value against this.
**It holds.** Every value it marks retired has zero new rows; every value it
marks "Live, no rows yet" has zero rows (`incomplete-evidence` ×2,
`unmapped-layout-class`, `no-illustration-index-entry`,
`multiple-illustrations`, `transfer-sha256-mismatch`, `artist-mismatch`,
`truncated-image`, `proxy-marker-veto`, `no-clear-winner-distance`,
`no-clear-winner-margin`); no value reaches the column that the roster does not
list. This is the one roster in the audit that survived contact with production
unchanged. Note `local-fallback-v1` has **zero** `CardScanLog` rows, consistent
with the deliberate 114,239-row purge.

**Scan-log rows by identity** (top): `stage-d-join-key-v1` 646,799 ·
`artist_ocr` 493,914 · `legal_line` 349,187 · `collector_line_ocr` 227,030 ·
`ai-art-detector-v1` 216,715 · `local-phash-v1` 157,864 ·
`stage-d-slow-path-v1` 135,293 · `stage-d-fallback-v1` 131,660 ·
`local-ocr-v1` 126,375 · `artbox_phash` 96,797 · `layout_class` 6,494 ·
`stage-d-illustration-v1` 3,425 · six extractors at 3,256 each ·
`layout-class-cast-v1` 1,519 · `evidence-transfer-v1` 12.

**Run history.**
`PilotRunLedger.objects.values("command").annotate(k=Count("id"))` —
`stage_e_streaming_dispatch` 877 · `reparse_collector_evidence` 31 ·
`local_calculate_verdicts` 23 · `run_image_evidence_cohort` 18 ·
`consensus_recompute` 11 · `local_lands_identify` 10 ·
`local_residual_classify` 4 · `local_layout_class_cast` 3 ·
`reparse_legal_line_proxy_marker` 3 · `backfill_modern_artist_names` 3 ·
seven more at ≤2. **Absent entirely: `local_name_frequency_elimination`,
`import_external_ip_tags`** — the direct evidence for their "never run"
classification. `local_identify_printing_tags` appears twice, one `running`
(2026-07-16 15:51, never finished) and one `completed` (2026-07-16 19:34,
43,426 votes). That single completed run is the entire provenance of the chips
the purge destroyed.

**Consensus state**, for context on what any of these votes currently move:
`printing_tag_status` — `unresolved` 230,680 / `no_match` 22 / `resolved` 4;
`artist_vote_status` — `unresolved` 230,706. Machine votes do not tip
consensus by design (the vote-weight gate); this is not a defect and no finding
above depends on it.

**Deferred, and why.** No re-extraction, no re-derivation, no counterfactual
run: all are writes, and this audit had no authorisation to write. The
142,633 + 2,786 figures are therefore _derivable populations computed from
stored fields_, not the output of a dry run of a caster that does not yet exist.

---

## Related

- [`../pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md) — the
  calculator roster and the 2026-07-26 pre-purge vote snapshot this audit
  measures the delta against.
- [`../reference/skip-reasons.md`](../reference/skip-reasons.md) — the
  skip-reason roster, verified value by value here.
- [`2026-07-29-fidelity-gate-recheck.md`](2026-07-29-fidelity-gate-recheck.md) —
  the same day's re-check of the gate's artifact 2; this report is the
  composition audit that one's scope excluded.
- [`../features/printing-tags.md`](../features/printing-tags.md) — the chip
  taxonomy and Stage 8 attribute-vote conventions.

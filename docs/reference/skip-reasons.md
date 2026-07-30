# Skip-reason roster

The complete set of values any calculator in this pipeline writes to
`CardScanLog.skip_reason`, plus the report-only skip strings that never
reach the database. **Code is the source of truth for this list**, and a
lint rule enforces that — see "How this doc is tethered" below.

Reference only: this doc says what each string MEANS and who emits it. It
does not decide anything. The behaviour of each outcome lives in the
emitting module's own docstring, cited per section.

## Why this doc exists

`docs/pipeline-fidelity-gate.md` fired as an audit partly on the
precondition that "every empirically-derived constant / threshold /
override / **skip-reason** [is] mapped to its home in the new pipeline, or
flagged missing."

That claim could never have been tested, because the skip reasons could
not be **enumerated**. Roughly thirty distinct values existed; about eleven
were declared as `*_SKIP_REASON` constants and the rest were bare inline
string literals, several of them reaching the database through a dynamic
pass-through (`skip_reason=outcome.ocr_skip_reason`,
`skip_reason=verdict.skip_reason`, `skip_reason=skip_reason`). No static
analysis could produce a complete roster, so the audit checked itself
against an incomplete list. Twelve values appeared nowhere in `docs/` at
all.

Two places asserted a specific, wrong count — "~11 distinct reasons
observed in production", in `docs/features/catalog-stats.md` and in
`MPCAutofill/cardpicker/catalog_stats.py` — while the code declared roughly
thirty and production actually held 23. Both now point here instead of
restating a number; see "Counts" below for why no number is asserted
anywhere in code or prose any more.

The 2026-07-29 declaration-convention sweep fixed the code side. Every
value written to `CardScanLog.skip_reason` now originates from a
module-level `*_SKIP_REASON` constant, in the same spirit as
`*_ANONYMOUS_ID`. **No string value changed** in that sweep: a
`CardScanLog` row written after it is byte-identical to one written before,
and `MPCAutofill/cardpicker/tests/test_skip_reason_roster.py` pins every
declared value against an explicit expected set so a future rename cannot
silently alter production data.

That sweep is also where
[`constant-rename-equivalence.md`](constant-rename-equivalence.md) came
from: the rename half of it collided with a concurrently-merged PR that had
added new code using an old constant name, and git auto-merged the two with
no conflict into a tree that raised `ImportError` at module-import time.
Run `.github/scripts/constant_rename_equivalence.py` on any branch that
renames, extracts or retires a `*_SKIP_REASON` — the roster tether above
checks that a value is DOCUMENTED, which is a different question from
whether the code still resolves and still evaluates to the same string.

## How this doc is tethered

`check_skip_reason_roster_tether()` in `.github/scripts/docs_lint.py`
derives the roster by scanning the non-test modules under
`MPCAutofill/cardpicker` for column-0 `*_SKIP_REASON = "<literal>"`
declarations, and hard-fails CI with an `::error::` on THIS FILE for any
declared value that has no entry here. It is the same mechanism, structure
and error style as `check_calculator_roster_tether()` (PR #562), which
tethers `docs/pipeline-fidelity-gate.md`'s calculator list to the
`*_ANONYMOUS_ID` declarations.

Matching is on the **literal value**, not the constant name. That is the
opposite choice from the calculator tether (which matches the full
versioned identity rather than the version-stripped family) for a
different reason rather than an inconsistent one: here the string IS the
production datum — millions of `CardScanLog` rows key on it — while the
constant name is an internal handle a refactor may legitimately change.
Renaming `FRAME_MISMATCH_SKIP_REASON` breaks nothing and should not fail
lint; changing its VALUE orphans every historical row and must fail loudly.

Exclusions go in `SKIP_REASON_ROSTER_ALLOWLIST` with a per-entry reason.
It is **empty today, deliberately**: every declared value has a real entry
below, including the retired ones and the report-only ones, because "this
string exists but nothing writes it any more" is exactly the fact an
enumeration is prone to lose.

## Counts

Neither this doc nor any code comment asserts a hardcoded count. That
assertion is what rotted last time: two files claimed "~11" while the code
declared ~30 and production held 23, and nothing could have caught the
drift because nothing derived either number.

To get the live figure, group the column:

```sql
SELECT skip_reason, count(*) FROM cardpicker_cardscanlog GROUP BY 1 ORDER BY 2 DESC;
```

`compute_skip_breakdown()` in `MPCAutofill/cardpicker/catalog_stats.py`
already serves exactly that aggregation to the stats page — it is a plain
`GROUP BY` and makes no assumption about the number of distinct values.

To get the declared figure, run the linter's own derivation
(`_declared_skip_reasons()` in `.github/scripts/docs_lint.py`); that is the
roster this document is checked against, so the two are the same list by
construction.

The counts quoted in the tables below are a **2026-07-29 measurement**,
included as evidence of live/dormant status, not as a claim that stays
true.

---

## Stage C evidence extraction — `MPCAutofill/cardpicker/image_evidence.py`

`persist_evidence()` writes one row per entry in
`ExtractionResult.skip_reasons`, tagged with `anonymous_id=<extractor name>` (`collector_line_ocr`, `artist_ocr`, `legal_line`, `artbox_phash`,
`symbol_region`, `layout_class`, `geometry_bleed`, `crop_coordinates`,
`fetch_health`, `quality_signals`, `collector_line_tsv`) rather than a
calculator identity. Three values total.

| Reason         | Constant                             | Means                                                                                                                                                          | Status             |
| -------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| `fetch_failed` | `EXTRACTOR_FETCH_FAILED_SKIP_REASON` | The card image could not be fetched, so this extractor never got to look. Transient (CDN/network), not a conclusion about the card.                            | Live (~38k rows)   |
| `ambiguous`    | `EXTRACTOR_AMBIGUOUS_SKIP_REASON`    | The extractor ran and produced a reading it cannot commit to — no confident single value (e.g. an art-box hash with no stable crop, an unclassifiable border). | Live (~98k rows)   |
| `no-text`      | `EXTRACTOR_NO_TEXT_SKIP_REASON`      | An OCR extractor ran and parsed nothing usable out of its crop.                                                                                                | Live (~1.06M rows) |

`fetch_failed` is the ONE value in the whole roster that uses an
underscore instead of the hyphen convention every other value follows.
Kept verbatim on purpose: tens of thousands of production rows carry it,
and normalising it would be a data change, not a refactor.

Historical rows also exist under a `color_profile` extractor name that no
longer exists in the code; it wrote `fetch_failed` like the rest.

## OCR + phash engines — `MPCAutofill/cardpicker/local_identify_printing_tags.py`

`anonymous_id` is `local-ocr-v1` (`OCR_ANONYMOUS_ID`) or `local-phash-v1`
(`PHASH_ANONYMOUS_ID`). Rescannability is governed by that module's
`RESCANNABLE_SKIP_REASONS`.

| Reason                           | Constant                                     | Emitted by       | Means                                                                                                                                                                                                                                                    | Status                                                                                                             |
| -------------------------------- | -------------------------------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `unfetchable-image`              | `UNFETCHABLE_IMAGE_SKIP_REASON`              | both             | No image to work from. **Rescannable** — a transient CDN/network condition, worth retrying.                                                                                                                                                              | Live (~31 rows)                                                                                                    |
| `frame-mismatch`                 | `FRAME_MISMATCH_SKIP_REASON`                 | both             | The engine matched a printing, but the observed frame style contradicts that printing's own frame value, so the printing vote is withheld. **Rescannable** by design, so the artist-extraction consumer still revisits these cards.                      | Live (~6.2k rows)                                                                                                  |
| `disagreement-with-other-engine` | `DISAGREEMENT_WITH_OTHER_ENGINE_SKIP_REASON` | both             | OCR and phash both voted and named different printings; neither vote is cast. Written once per engine, so these rows come in pairs.                                                                                                                      | Live (~1.9k rows)                                                                                                  |
| `ambiguous`                      | `OCR_AMBIGUOUS_SKIP_REASON`                  | `local-ocr-v1`   | A collector-line read matched MORE than one of this card's candidates (evidence FOR several, not against the set).                                                                                                                                       | Live                                                                                                               |
| `no-text`                        | `OCR_NO_TEXT_SKIP_REASON`                    | `local-ocr-v1`   | No preprocessing variant parsed a collector number at all.                                                                                                                                                                                               | Live (~73k rows)                                                                                                   |
| `unknown-set-code`               | `OCR_UNKNOWN_SET_CODE_SKIP_REASON`           | `local-ocr-v1`   | Every `parsed-but-no-match` outcome carried a set code matching no real expansion — un-parsed noise shaped like a set code. A named abstention, not a confident negative. Same string, same meaning as the join-key calculator's own `unknown-set-code`. | Live (rows land under `stage-d-join-key-v1`)                                                                       |
| `parsed-but-no-match`            | `PARSED_BUT_NO_MATCH_SKIP_REASON`            | `local-ocr-v1`   | A syntactically valid collector-line read that matches NONE of this card's candidates.                                                                                                                                                                   | **No longer written.** Since issue #207 this casts a real `is_no_match` vote instead; ~48k historical rows remain. |
| `too-many-candidates`            | `PHASH_TOO_MANY_CANDIDATES_SKIP_REASON`      | `local-phash-v1` | The candidate pool exceeds the engine's cap, checked before any candidate hash is fetched (basic lands and staple commons hit this).                                                                                                                     | Live (~39k rows)                                                                                                   |
| `no-hashable-candidates`         | `PHASH_NO_HASHABLE_CANDIDATES_SKIP_REASON`   | `local-phash-v1` | Every candidate failed to fetch or hash, so there was nothing to compare against.                                                                                                                                                                        | Live but near-dormant (1 row ever)                                                                                 |
| `no-clear-winner`                | `PHASH_NO_CLEAR_WINNER_SKIP_REASON`          | `local-phash-v1` | Best distance over threshold OR runner-up too close — the undifferentiated form of the two below.                                                                                                                                                        | **No longer written.** Refined into the two variants below; ~117k historical rows remain.                          |
| `no-clear-winner-distance`       | `PHASH_NO_CLEAR_WINNER_DISTANCE_SKIP_REASON` | `local-phash-v1` | The best candidate's distance missed the threshold outright.                                                                                                                                                                                             | Live                                                                                                               |
| `no-clear-winner-margin`         | `PHASH_NO_CLEAR_WINNER_MARGIN_SKIP_REASON`   | `local-phash-v1` | A candidate cleared the threshold, but the runner-up was too close behind it.                                                                                                                                                                            | Live                                                                                                               |

`no-hashable-candidates` and `no-clear-winner` are the two values whose
strings physically originate inside `MPCAutofill/cardpicker/local_phash.py`
(`find_best_match`), and that is where their constants are **declared** —
not in this section's own module. That file is PROTECTED CORE
(`docs/upstreaming/license-provenance.md` section 2); the two declarations
sit there under the narrow owner exception granted 2026-07-29 and recorded
in that section. They were briefly mirrored in
`local_identify_printing_tags.py`, while that file was the only editable
one; the mirror is gone, so every roster value now has exactly one
declaration and it is co-located with its origin.
`local_identify_printing_tags` imports `PHASH_NO_CLEAR_WINNER_SKIP_REASON`
from `local_phash` for its `_classify_no_clear_winner` refinement test.

## Local-fallback pilot engine — `MPCAutofill/cardpicker/local_fallback.py`

`anonymous_id` is `local-fallback-v1` (`FALLBACK_ANONYMOUS_ID`). The pilot's
pass 2: border / artist / symbol sub-checks intersected against the card's
own name-candidates, run against a fresh per-invocation image fetch.
`run_fallback_for_card` puts one of these three on
`FallbackOutcome.skip_reason`.

| Reason        | Constant                                 | Means                                                                 | Status                 |
| ------------- | ---------------------------------------- | --------------------------------------------------------------------- | ---------------------- |
| `no-evidence` | `LOCAL_FALLBACK_NO_EVIDENCE_SKIP_REASON` | Not one sub-check (border, artist, symbol) produced a reading at all. | **Latent — see below** |
| `eliminated`  | `LOCAL_FALLBACK_ELIMINATED_SKIP_REASON`  | Sub-checks ran and ruled out every candidate — zero survivors.        | **Latent — see below** |
| `ambiguous`   | `LOCAL_FALLBACK_AMBIGUOUS_SKIP_REASON`   | More than one candidate survived the sub-check intersection.          | **Latent — see below** |

**Latent, not live, and that is the reason they are declared.** Nothing
persists these three today. This module's own printing-vote / `CardScanLog`
write branch was retired on 2026-07-29 (redundancy doctrine — see the
module's docstring), and its one non-test caller,
`local_residual_classify.recover_frame_mismatch_printing_via_fallback_refetch`,
reads `outcome.printing_pk` and discards `skip_reason`. The existing
`local-fallback-v1` rows in `CardScanLog` are historical. They go live the
moment anything persists this outcome — which is why they had to become
enumerable **before** that happens rather than after: the tether cannot
enumerate a literal it cannot see, so a fourth reason added inside
`run_fallback_for_card` plus one new write would have reached the column
with no lint failure anywhere.

`local_fallback.py` is PROTECTED CORE
(`docs/upstreaming/license-provenance.md` section 2). The three declarations
sit there under a second narrow owner exception, granted 2026-07-29 and
recorded in section 2.1 alongside the `local_phash.py` one. The exception
covers skip-reason constants in that one file; the file remains protected.

**Not the same constants as the Stage D fallback calculator's, on purpose.**
The `FALLBACK_*_SKIP_REASON` family two sections below belongs to
`stage-d-fallback-v1` in `local_calculate_verdicts.py` — a different
calculator, a different population of rows, its own vocabulary. It shares
`eliminated` and `ambiguous` verbatim with this engine (same meaning, no
rename needed) and deliberately renames this engine's `no-evidence` to
`no-sub-check-evidence` to avoid colliding with Stage D's own established
`no-evidence`. Those are parallel declarations, not mirrors of these, and
collapsing them would erase a real distinction between two row populations —
exactly the "one prefixed constant per calculator per value" shape
`no-evidence` already has five times over. The `LOCAL_FALLBACK_` prefix here
keeps the two families legible.

## Stage D join-key calculator — `MPCAutofill/cardpicker/local_calculate_verdicts.py`

`anonymous_id` is `stage-d-join-key-v1` (`JOIN_KEY_ANONYMOUS_ID`). Several
of these strings are also emitted by other calculators with a different
meaning, which is why each carries a `JOIN_KEY_` prefixed constant rather
than sharing one.

| Reason                    | Constant                                       | Means                                                                                                                                                                              | Status                                                                                                                                                                                                                |
| ------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `no-evidence`             | `JOIN_KEY_NO_EVIDENCE_SKIP_REASON`             | No current `ImageEvidence` row exists for this card yet. **Rescannable** — a transient state, not a conclusion.                                                                    | Live (~503k rows, the largest single cohort)                                                                                                                                                                          |
| `no-text`                 | `JOIN_KEY_NO_TEXT_SKIP_REASON`                 | The stored collector-line evidence parsed no collector number.                                                                                                                     | Live (~81k rows)                                                                                                                                                                                                      |
| `ambiguous`               | `JOIN_KEY_AMBIGUOUS_SKIP_REASON`               | The parsed join key matches more than one candidate printing.                                                                                                                      | Live (~154 rows)                                                                                                                                                                                                      |
| `unknown-set-code`        | `JOIN_KEY_UNKNOWN_SET_CODE_SKIP_REASON`        | The set-code lexicon gate: a parsed `set_code` matching no `CanonicalExpansion.code`. A permanent conclusion, deliberately NOT rescannable.                                        | Live (~46k rows)                                                                                                                                                                                                      |
| `artist-mismatch`         | `JOIN_KEY_ARTIST_MISMATCH_SKIP_REASON`         | The collector-line artist gate: the printing the join key resolves to has an artist incompatible with the one printed on the card, so the parse contradicts its own source string. | Live (shipped 2026-07-29, no rows yet at measurement time)                                                                                                                                                            |
| `border-mismatch`         | `JOIN_KEY_BORDER_MISMATCH_SKIP_REASON`         | The corroboration layer: observed border colour contradicts the matched printing's own border value; the vote is withheld.                                                         | Live (~15k rows)                                                                                                                                                                                                      |
| `frame-mismatch`          | `JOIN_KEY_FRAME_MISMATCH_SKIP_REASON`          | As above, for frame style.                                                                                                                                                         | Live (~1.3k rows)                                                                                                                                                                                                     |
| `truncated-image`         | `JOIN_KEY_TRUNCATED_IMAGE_SKIP_REASON`         | The source image is truncated, so the evidence underneath the join key cannot be trusted.                                                                                          | Live                                                                                                                                                                                                                  |
| `copyright-year-mismatch` | `JOIN_KEY_COPYRIGHT_YEAR_MISMATCH_SKIP_REASON` | The legal line's copyright year contradicts the matched printing's release.                                                                                                        | Live (~40 rows)                                                                                                                                                                                                       |
| `proxy-marker-veto`       | `JOIN_KEY_PROXY_MARKER_VETO_SKIP_REASON`       | A moderator proxy-marker flag vetoed an otherwise clean join-key match.                                                                                                            | **Retired 2026-07-21.** Nothing writes it; kept declared and kept in `JOIN_KEY_NO_HIT_SKIP_REASONS` so historical rows still route to review. Retract with `reparse_collector_evidence --selector proxy-marker-veto`. |

`transferred-interim-guard` (`TRANSFERRED_INTERIM_GUARD_SKIP_REASON`) is
declared in the same module and belongs to both this calculator and the
fallback one. **Retired 2026-07-25** (issue #473 PR-3): no code path writes
a new row with it. It stays declared, and stays a member of both
calculators' rescannable sets, purely so a historical row written by a
pre-PR-3 run still reads sensibly and still marks its card eligible for
reselection.

## Stage D fallback calculator — `MPCAutofill/cardpicker/local_calculate_verdicts.py`

`anonymous_id` is `stage-d-fallback-v1` (`STAGE_D_FALLBACK_ANONYMOUS_ID`).
Border / artist / symbol sub-checks intersected against the candidate pool.
A port of the pilot engine's decision model onto stored `ImageEvidence`; its
constants are its own, **not** mirrors of the pilot's `LOCAL_FALLBACK_*`
three — see the Local-fallback pilot engine section above for why the two
families are kept separate.

| Reason                  | Constant                                     | Means                                                                                                                                                                                | Status           |
| ----------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------- |
| `no-evidence`           | `FALLBACK_NO_EVIDENCE_SKIP_REASON`           | No current `ImageEvidence` row for this card. Same meaning as the join-key calculator's identical string, different `anonymous_id` scope. **Rescannable**.                           | Live             |
| `no-sub-check-evidence` | `FALLBACK_NO_SUB_CHECK_EVIDENCE_SKIP_REASON` | An evidence row exists, but not one sub-check (border, artist, symbol) produced a reading. Deliberately NOT called `no-evidence`, which already means something else one line above. | Live (~43k rows) |
| `eliminated`            | `FALLBACK_ELIMINATED_SKIP_REASON`            | Sub-checks ran and ruled out every candidate — zero survivors.                                                                                                                       | Live (~150 rows) |
| `ambiguous`             | `FALLBACK_AMBIGUOUS_SKIP_REASON`             | More than one candidate survived the sub-check intersection.                                                                                                                         | Live (~88k rows) |

## Stage D slow path — `MPCAutofill/cardpicker/local_calculate_verdicts.py`

| Reason      | Constant                          | Means                                                                                                                                                                                                                                 | Status            |
| ----------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| `to-review` | `SLOW_PATH_TO_REVIEW_SKIP_REASON` | **Not an abstention at all** — a durable routing marker under `anonymous_id=stage-d-slow-path-v1` meaning "this card was routed to human review, carrying partial evidence". It reuses this column rather than inventing new storage. | Live (~135k rows) |

## Illustration calculator — `MPCAutofill/cardpicker/local_illustration.py`

`anonymous_id` is `stage-d-illustration-v1` (`ILLUSTRATION_ANONYMOUS_ID`).
Every value here was already a declared constant before the sweep.

| Reason                                | Constant                                  | Means                                                                                                                                                                                                                                                                  | Status                                                                                                                                                                                                                                                                                                             |
| ------------------------------------- | ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `no-evidence`                         | `NO_EVIDENCE_SKIP_REASON`                 | No current `ImageEvidence` row. **Rescannable** (this calculator's whole rescannable set).                                                                                                                                                                             | Live                                                                                                                                                                                                                                                                                                               |
| `no-artist-ocr`                       | `NO_ARTIST_OCR_SKIP_REASON`               | Evidence exists but carries no artist-OCR name, which this calculator needs to narrow illustrations.                                                                                                                                                                   | Live (~14 rows)                                                                                                                                                                                                                                                                                                    |
| `multi-faced-v1`                      | _(none — constant deleted by #565)_       | The card is multi-faced and this calculator's v1 handled single-faced cards only. The value names the VERSION that abstained, not a defect.                                                                                                                            | **Retired 2026-07-29** (#565 deleted the border-colour "multi-faced" gate and deliberately did NOT replace `SINGLE_FACED_ONLY_SKIP_REASON`; `stage-d-illustration-v2` never emits it). Listed because ~3,409 historical `CardScanLog` rows still carry it — the one value in this roster with no live declaration. |
| `no-candidate-match`                  | `NO_CANDIDATE_MATCH_SKIP_REASON`          | The artist name matched none of this card's candidate printings.                                                                                                                                                                                                       | Live (1 row)                                                                                                                                                                                                                                                                                                       |
| `no-illustration-index-entry`         | `NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON` | Candidates matched, but none has an entry in the in-memory illustration index.                                                                                                                                                                                         | Live, no rows yet                                                                                                                                                                                                                                                                                                  |
| `multiple-illustrations`              | `MULTIPLE_ILLUSTRATIONS_SKIP_REASON`      | The 1:1 rule, N>1 branch: several distinct illustrations survived, so no single illustration identity exists to record.                                                                                                                                                | Live, no rows yet                                                                                                                                                                                                                                                                                                  |
| `multiple-printings-one-illustration` | `MULTIPLE_PRINTINGS_SKIP_REASON`          | The 1:1 rule, other branch: exactly one illustration survived but it maps to several printings — the illustration IS known, only the printing choice is undetermined. Deliberately a separate string so the recoverable population is selectable with a plain `WHERE`. | Live (2 rows)                                                                                                                                                                                                                                                                                                      |

## AI-art detector — `MPCAutofill/cardpicker/local_detect_ai_art.py`

`anonymous_id` is `ai-art-detector-v1` (`AI_ART_ANONYMOUS_ID`).

| Reason                | Constant                                 | Means                                                                                                                                           | Status            |
| --------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| `no-evidence`         | `AI_ART_NO_EVIDENCE_SKIP_REASON`         | No current `ImageEvidence` row. **Rescannable**.                                                                                                | Live (~197k rows) |
| `incomplete-evidence` | `AI_ART_INCOMPLETE_EVIDENCE_SKIP_REASON` | An evidence row exists but is missing one of this detector's required extractor keys. **Rescannable**.                                          | Live, no rows yet |
| `no-marker-hit`       | `AI_ART_NO_MARKER_HIT_SKIP_REASON`       | The detector ran and found no marker. Recorded as a row purely so the same resume/idempotence machinery applies to a negative as to a positive. | Live (~20k rows)  |

## Layout-class cast — `MPCAutofill/cardpicker/local_layout_class_cast.py`

`anonymous_id` is `layout-class-cast-v1` (`LAYOUT_CLASS_CAST_ANONYMOUS_ID`).

| Reason                  | Constant                                       | Means                                                                                 | Status            |
| ----------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------- | ----------------- |
| `no-evidence`           | `LAYOUT_CLASS_NO_EVIDENCE_SKIP_REASON`         | No current `ImageEvidence` row. **Rescannable**.                                      | Live (~61 rows)   |
| `incomplete-evidence`   | `LAYOUT_CLASS_INCOMPLETE_EVIDENCE_SKIP_REASON` | Evidence row present but missing a required extractor key. **Rescannable**.           | Live, no rows yet |
| `ambiguous`             | `LAYOUT_CLASS_AMBIGUOUS_SKIP_REASON`           | The verdict produced no layout class at all.                                          | Live (~1.5k rows) |
| `unmapped-layout-class` | `LAYOUT_CLASS_UNMAPPED_SKIP_REASON`            | A layout class WAS read, but it has no tag mapped to it, so there is no vote to cast. | Live, no rows yet |

## Attribute-chip caster — `MPCAutofill/cardpicker/local_attribute_chip_cast.py`

Two `anonymous_id`s, both writing from one pass and sharing this
vocabulary: `frame-style-cast-v1` (`FRAME_STYLE_CAST_ANONYMOUS_ID`, Old
Border / Modern Border) and `bleed-edge-cast-v1`
(`BLEED_EDGE_CAST_ANONYMOUS_ID`, appropriate-bleed). New 2026-07-30 —
before it, both chip families had no evidence-reading caster at all and
sat at zero rows.

| Reason                 | Constant                               | Means                                                                                                                                                                                                         | Status            |
| ---------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| `no-evidence`          | `CHIP_NO_EVIDENCE_SKIP_REASON`         | No current `ImageEvidence` row. **Rescannable**.                                                                                                                                                              | Live, no rows yet |
| `incomplete-evidence`  | `CHIP_INCOMPLETE_EVIDENCE_SKIP_REASON` | The chip family's own required extractor key is absent. **Rescannable**. Load-bearing on the frame side, not defensive: without it a missing `artist_ocr` reads `illus_anchor_fired` as a real `False`.       | Live, no rows yet |
| `ambiguous`            | `CHIP_ABSTAINED_SKIP_REASON`           | Frame: neither signal fired. Bleed: the reading was not `trimmed` — which includes the ordinary ~97.5% `bleed` case, since this chip is negative-only and absence of a vote IS the "normal bleed" convention. | Live, no rows yet |
| `unmapped-frame-class` | `CHIP_UNMAPPED_SKIP_REASON`            | A frame class WAS read but has no tag mapped to it. Unreachable against the current closed taxonomy; exercised in tests only.                                                                                 | Live, no rows yet |

## Evidence transfer — `MPCAutofill/cardpicker/evidence_transfer.py`

`anonymous_id` is `evidence-transfer-v1` (`EVIDENCE_TRANSFER_ANONYMOUS_ID`).
This module casts NO votes of any kind; a `CardScanLog` skip row is its
entire database footprint, which is why it sits on the calculator roster's
own allowlist in `.github/scripts/docs_lint.py`. Both values were already
declared constants before the sweep.

| Reason                           | Constant                                              | Means                                                                                            | Status            |
| -------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ----------------- |
| `transfer-sha256-mismatch`       | `EVIDENCE_TRANSFER_SHA256_MISMATCH_SKIP_REASON`       | The donor and recipient cards' byte-level SHA-256 disagree, so the evidence was not copied.      | Live, no rows yet |
| `transfer-content-hash-mismatch` | `EVIDENCE_TRANSFER_CONTENT_HASH_MISMATCH_SKIP_REASON` | The donor and recipient cards' perceptual content hash disagree, so the evidence was not copied. | Live (12 rows)    |

## Lands artist decomposition — `MPCAutofill/cardpicker/local_lands_identify.py`

**REPORT-ONLY. None of these ever reaches the database.** This module
writes `CardPrintingTag` votes and `LandsAmbiguousResidue` routing rows,
never a `CardScanLog` row; these values live only on `LandIdentifyOutcome`,
an in-memory run report.

They are declared and documented anyway because they were the largest
cluster of skip-reason strings in the codebase with no named home and no
way to enumerate them — precisely the defect this roster exists to close.
If this module ever grows a `CardScanLog` write, these become real
persisted values with no further work.

| Reason                   | Constant                                   | Means                                                                                   |
| ------------------------ | ------------------------------------------ | --------------------------------------------------------------------------------------- |
| `no-artist-extracted`    | `LANDS_NO_ARTIST_EXTRACTED_SKIP_REASON`    | Neither stored evidence nor a live OCR pass produced an artist name to narrow on.       |
| `artist-no-match`        | `LANDS_ARTIST_NO_MATCH_SKIP_REASON`        | An artist name was extracted but matched none of this card's candidate printings.       |
| `no-content-phash`       | `LANDS_NO_CONTENT_PHASH_SKIP_REASON`       | The card has no stable content hash, so there is nothing to key the phash tie-break on. |
| `fetch-budget-exhausted` | `LANDS_FETCH_BUDGET_EXHAUSTED_SKIP_REASON` | The run's live-fetch budget ran out before this card, which was not evidence-backed.    |
| `unfetchable-image`      | `LANDS_UNFETCHABLE_IMAGE_SKIP_REASON`      | A live fetch was attempted within budget and failed.                                    |

## The values that are not declared at their origin

Stated explicitly rather than forced, per the sweep's own brief.

**`local_phash.find_best_match`'s two return values — CLOSED 2026-07-29.**
`no-hashable-candidates` and `no-clear-winner` were the sweep's one
exception: they are produced inside
`MPCAutofill/cardpicker/local_phash.py`, which is PROTECTED CORE
(`docs/upstreaming/license-provenance.md` section 2), so the sweep could
not declare them at source and mirrored them in the consuming module
instead. That left a real hole — a NEW literal added inside
`find_best_match` would have reached `CardScanLog` without the tether ever
seeing it, because the tether cannot enumerate literals it cannot see.
The owner granted a narrow exception on 2026-07-29 (recorded in
`license-provenance.md` section 2, which also states its limits): the two
constants are now declared in `local_phash.py` itself, the mirror in
`local_identify_printing_tags.py` is removed, and the tether reports
`local_phash.py` as the declaration site. The exception covers skip-reason
constants in that one file only; the file remains protected.

**`local_fallback.run_fallback_for_card`'s three return values — CLOSED
2026-07-29.** `no-evidence`, `eliminated` and `ambiguous` were bare inline
literals inside `MPCAutofill/cardpicker/local_fallback.py`, PROTECTED CORE
under the same section 2, for the same reason. The defect was **latent**,
not live: this module's own write branch was retired the same day and its
one non-test caller discards `skip_reason` (see the Local-fallback pilot
engine section above), so nothing reached `CardScanLog`. That made it
cheaper to close, not less necessary to — the invisibility is a property of
the literals, and it would have become a live hole the instant anything
persisted the outcome, with no lint failure to mark the moment. The owner
granted a second narrow exception on 2026-07-29 (recorded in
`license-provenance.md` section 2.1, which also states its limits, and which
is a per-change log rather than a precedent): the three constants are now
declared in `local_fallback.py` itself as
`LOCAL_FALLBACK_NO_EVIDENCE_SKIP_REASON` /
`LOCAL_FALLBACK_ELIMINATED_SKIP_REASON` /
`LOCAL_FALLBACK_AMBIGUOUS_SKIP_REASON`, and the tether reports
`local_fallback.py` as their declaration site. There was no mirror to
remove: unlike the phash pair, these values were never re-declared for this
engine anywhere else, because its one caller never reads them. **Every
roster value is now declared where it is produced.**

**The lands module's phash-branch composition.** That module reports
`f"{LANDS_PHASH_SKIP_REASON_PREFIX}{reason}"` — a `phash-` prefix
concatenated onto whatever `find_best_match` returned. The prefix is a
constant and the routing test reads it, but the composed value is still not
a declared string — the concatenation is what the tether cannot see, and
that is true regardless of the two `find_best_match` returns now being
named constants. This is harmless today precisely because nothing in that
module is persisted; the constant's own comment records that a
`CardScanLog` write
must not be added there until the composition is replaced with explicit
per-outcome constants.

**Not in scope, and why.** `local_ocr.validate_against_candidates` returns
skip-reason-shaped strings as inline literals. They do not reach
`CardScanLog`: all three are consumed as control flow and re-expressed by
the caller's own declared constants, which is a different situation from an
undeclared value flowing through to the column.

This paragraph previously also listed `local_fallback` here, under the
function name `compute_fallback_outcome` — a name that does not exist in the
code; the function is `run_fallback_for_card`. Both the wrong name and the
"not in scope" classification are corrected: those three values are now
declared at their origin (see the entry above and the Local-fallback pilot
engine section) and are ordinary roster members, latent rather than live.

## Related

- `docs/pipeline-fidelity-gate.md` — the audit whose skip-reason
  precondition this roster makes testable, and the calculator roster this
  one is modelled on.
- `docs/features/catalog-stats.md` — the `skipBreakdown` panel that
  aggregates this column.
- `docs/documentation-process.md` — the general "roster tethers" rule: any
  document that enumerates a set actually defined in code must be tethered
  to that code by a lint rule, with code as the source of truth.

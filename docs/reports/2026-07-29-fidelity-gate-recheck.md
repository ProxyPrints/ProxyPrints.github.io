# Pipeline-fidelity gate — artifact-2 re-check and verdict re-test (2026-07-29)

> **PARTLY SUPERSEDED, same day.** Everything this report says about
> `PrintingTagVote`, `scryfall-tagger-v1` and
> `management/commands/import_external_ip_tags.py` was accurate when measured
> and is now history: the owner ruled that day to retire `PrintingTagVote`, and
> the model, its table, its submit endpoint and that command were all removed
> (migration `0101_delete_printingtagvote`). This report's own finding — 0 rows,
> nothing ever resolved, an identity the roster tether could not see — is part
> of what motivated the removal, so it is left standing rather than rewritten.
> `scryfall-tagger-v1` is no longer a calculator identity at all and should not
> be expected on any roster. The retirement record, including the import
> algorithm deleted with the command, is the External-IP entry in
> [`../features/printing-tags.md`](../features/printing-tags.md). Nothing else
> in this report is affected.

Read-only audit. No writes, no management command, no migration, no deploy.
Every live figure below was queried against production Postgres via
`sudo docker exec mpcautofill_django python manage.py shell` on 2026-07-29.

**Commits measured.** Production runs `85d88bfe` (verified against the running
container's own source, not inferred). `origin/master` is `6bc3e166`. Code
claims are stated against master unless marked otherwise; every DB figure is
production. The two differ for docs and CI only in the areas this audit
touches (`docs/reference/skip-reasons.md` and the two roster tethers are on
master and not yet deployed — they are lint-only and have no runtime effect).

## Why this re-check exists

`docs/pipeline-fidelity-gate.md` §2 records **Gate verdict: FIRED** on two
artifacts. Artifact 2 (the knowledge-inventory sweep,
[`2026-07-22-knowledge-inventory.md`](2026-07-22-knowledge-inventory.md)) was
certified DONE against a precondition that included "every empirically-derived
constant / threshold / override / **skip-reason** mapped to its home in the new
pipeline, or flagged missing." At certification time the skip-reason roster was
not enumerable, so that clause could not have been tested. PR #567 closed the
enumeration gap. This report redoes artifact 2's mapping against what code
actually declares today, and re-tests the verdict.

**The distinction this report holds to throughout: a claim certified against an
incomplete list is not thereby false — it was untested.** Each finding below is
graded UNTESTED→HOLDS, UNTESTED→FAILS, or STILL UNTESTABLE.

---

## 1. What the original sweep could not have checked

### 1a. The skip-reason clause, structurally

At 2026-07-22 roughly thirty distinct skip-reason values existed, ~11 as named
constants and the rest as bare inline literals, several reaching the database
through a dynamic pass-through. No static analysis could produce the roster, so
the "mapped or flagged missing" clause had nothing to be checked against. The
sweep's own inventory tables contain no skip-reason enumeration — they map five
values (`no-text`, `parsed-but-no-match`, `ambiguous`, `unfetchable-image`,
`frame-mismatch`) reached incidentally through the constants they were tracking,
and its closing sentence ("No other pilot-era constant, threshold, crop box,
regex, or **skip-reason** was found with genuinely no current home") asserts
completeness over a set it could not enumerate.

### 1b. Four vote-casting modules that did not exist at certification

| module                                                                  | first commit      | in the sweep? |
| ----------------------------------------------------------------------- | ----------------- | ------------- |
| `local_layout_class_cast.py` (`layout-class-cast-v1`)                   | 2026-07-23 (#375) | could not be  |
| `evidence_transfer.py` (`evidence-transfer-v1`)                         | 2026-07-25 (#484) | could not be  |
| `management/commands/import_external_ip_tags.py` (`scryfall-tagger-v1`) | 2026-07-27 (#497) | could not be  |
| `local_illustration.py` (`stage-d-illustration-v1/v2`)                  | 2026-07-28 (#509) | could not be  |

The gate fired 2026-07-23/24. Three of these four landed **after the fire**.
Artifact 2 is a snapshot certification of a pipeline that has since grown four
new vote-casting or scan-log-writing identities, none of them inventoried.

### 1c. Three modules that existed and were nonetheless out of scope

`local_lands_identify.py` (2026-07-18, `lands-artist-decomp-v1`, casts
**printing** votes), `local_detect_ai_art.py` (2026-07-21, `ai-art-detector-v1`)
and `local_residual_classify.py` (2026-07-18, `residual-classify-v1`) all
predate the sweep. The sweep mentions `local_residual_classify` twice in
passing and the other two not at all. This is a scope choice, not an
impossibility — the sweep scoped itself to the pilot's own files plus Stage C/D,
while the gate's precondition is written over "the new pipeline."

### 1d. A vote family the gate has never named

`PrintingTagVote` (models.py:1256, PR #497) votes a descriptor tag onto a
**`CanonicalCard` printing**, distinct from both `CardPrintingTag` (which
printing does this image depict) and `CardTagVote` (per-image tag). The string
`PrintingTagVote` appears **zero** times in `docs/pipeline-fidelity-gate.md` and
zero times in `docs/theory.md`. Its only machine identity is
`scryfall-tagger-v1`. Live count: **0 rows** — it has never run.

---

## 2. What is now verified and HOLDS

### 2a. The skip-reason roster is now genuinely complete — UNTESTED → HOLDS

Derived the roster from master exactly as `.github/scripts/docs_lint.py` does
(37 distinct declared values across 51 `*_SKIP_REASON` constants) and grouped
the live column:

```sql
SELECT skip_reason, count(*) FROM cardpicker_cardscanlog GROUP BY 1 ORDER BY 2 DESC;
-- 23 distinct values
```

- Live values with no declaration: **exactly one**, `multi-faced-v1` (3,409
  rows), and `docs/reference/skip-reasons.md` names it explicitly as the one
  value with no live declaration. No silent orphans.
- Declared values with no live rows: 15, all of them documented as such or as
  retired.
- Both tethers run clean on master: `check_calculator_roster_tether()` → 0
  findings, `check_skip_reason_roster_tether()` → 0 findings.

The clause artifact 2 could not test is now testable, and on today's code it
passes. This is the single largest thing PR #567 bought.

### 2b. The three §3 MISSING constants, on the calculators the gate audited — HOLDS

`RESOLUTION_FLOOR_DPI = 200` and `EXCLUDED_RESOLVED_TAGS` are present and applied
in `local_calculate_verdicts._eligible_cards_queryset` (lines 1145–1147), which
is shared by the join-key, fallback and slow-path calculators, and independently
re-declared and applied in `local_illustration` (lines 164–165, 605–607).
Live sizing: **23 cards catalog-wide sit below the dpi floor**; 9 of them carry
a printing vote and all 9 are `deductive-backfill-v1` rows predating the fix.
The §3 item-3 deductive-backfill exclusion remains deliberately not restored, as
ruled.

### 2c. The resolution-level soundness property — HOLDS, and holds against the new adverse data

`vote_consensus`'s `winner.has_human_backed` is a hard gate; no volume of
machine weight resolves anything. Tested against the worst population available:
**all 1,261 cards in the artist-contradiction census read
`printing_tag_status=unresolved`.** Catalog-wide: 230,744 unresolved / 22
no_match / **4 resolved**. `theory.md` §7b's "resolution-level false accept = 0,
structurally" survives every finding in this report intact. This is the load-
bearing soundness claim and it is undamaged.

### 2d. Two of the three calculators the gate never inventoried are correctly out of scope — HOLDS

`local_detect_ai_art._eligible_cards_queryset` and
`local_layout_class_cast._eligible_cards_queryset` both omit the dpi floor and
the custom-art/non-english exclusions **with an in-code reason**: border-colour
and AI-art classification are orthogonal to printing identification, so a card
whose printing-identification precondition is falsified still has a truthfully
classifiable border. That is a "deliberately changed, reasoned in-code" status
in the sweep's own taxonomy. Never inventoried, but not a defect.

### 2e. The three established 2026-07-29 findings the brief asked me to re-verify — all HOLD

| claim                                                                                  | re-measured                                                                                                                                                                                                                               |
| -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `local-name-frequency-v1` has produced zero output and is never called                 | 0 `CardPrintingTag`, 0 `CardScanLog`, 0 of 995 `PilotRunLedger` rows. Confirmed. It **does** have a management command (`local_name_frequency_elimination`), so it is invokable — it has simply never been invoked.                       |
| `local-ocr-v1` and `stage-d-join-key-v1` agree on 33,622 of 33,749 with zero conflicts | Re-measured on positive votes only: overlap **33,622**, identical printing set on **33,622**, **0** conflicts. Confirmed.                                                                                                                 |
| `local-ocr-v1` / `local-phash-v1` 2,309 of 2,309                                       | Overlap **2,309**, agree **2,309**, conflict **0**. Confirmed.                                                                                                                                                                            |
| Stage D backlogs drained; total remaining yield 3,412                                  | The 2026-07-29T15:03Z read-only dry run at `git_sha 85d88bfe` reports join-key considered=28, fallback considered=0, slow-path considered=0, illustration considered=12,460 / would_cast 3,401; `total_votes=would_cast=3412`. Confirmed. |

Two corrections to the brief's own framing, from the running container's source:
PR #563 and PR #565 **are deployed** — the container declares
`ILLUSTRATION_ANONYMOUS_ID = "stage-d-illustration-v2"` and carries
`JOIN_KEY_ARTIST_MISMATCH_SKIP_REASON`. And `local-fallback-v1` no longer holds
**any** `CardPrintingTag` row (0, down from 11,947 at the 2026-07-26 topline),
so the "11,825 of 11,825, zero conflicts" pair can no longer be measured.

---

## 3. What is now verified and does NOT hold

### 3a. Artifact 1's "OCR-channel agreement" is a self-comparison. UNTESTED → FAILS as evidence of correctness

`pipeline-fidelity-gate.md` §4 frames the replay as "a **cross-method** verdict
diff" and reports **83.2% OCR-channel agreement** over the 28,456 cards whose
pilot vote used `local-ocr-v1`. The cross-method framing is correct for the full
41,586-card cohort — but the 83.2% headline is computed on precisely the subset
where it is **not** true. Both sides of that subset are the same decoder:
`stage-d-join-key-v1` reads a collector line through `local_ocr`'s own
`DEFAULT_CROP_BOX`, `_SET_CODE_RE`, `_COLLECTOR_NUMBER_RE` and
`_normalize_collector_number`, resolves against the same `CandidateNameIndex`,
and (per artifact 2's own table) carries `JOIN_KEY_CONFIDENCE_BOTH`/
`_COLLECTOR_ONLY` as literal copies of the OCR engine's tiers. Artifact 1
compares an implementation to a copy of itself running on re-extracted inputs.

That makes it a good **port-fidelity** check and no kind of correctness check.
The structural consequence is now measurable: on the 33,622 cards where both
identities hold a positive vote today, they name the identical printing
**33,622 / 33,622**, zero conflicts. A pair that cannot disagree cannot corroborate.

**Direct demonstration that agreement includes wrong votes.** Of the 1,261
positive `stage-d-join-key-v1` votes in the artist-contradiction census
(`~/.local/share/proxyprints-daemon/measurements/artist-contradiction-census-20260729.json`;
1,261 of 41,129 examined = 3.07%, or 3.35% of the 37,589 with a readable printed
artist), **1,072 also carry a `local-ocr-v1` positive vote, and on all 1,072 the
two channels name the same printing — the artist-contradicted one.** Zero name a
different one. Those 1,072 cards are agreements. They are inside the 83.2%.

So `theory.md` §7c's "zero of the full 17,793 was a case where this chain
committed to a wrong printing that the pilot's own recorded vote contradicts" is
**true and vacuous**: wrongness was operationalised as "contradicts the pilot's
vote", and the pilot's vote is the same decoder's output. The measurement cannot
return any other answer.

### 3b. The owner ruling's "zero false-accept risk" conflates two different quantities. UNTESTED → FAILS

`theory.md` §7b carefully separates **resolution-level** false accept (0,
structurally — see §2c above, still true) from **suggestion-level** false accept
(a wrong printing surfaced to a reviewer), which it calls "bounded but not
calibrated". §4's owner ruling accepts artifact 1 on the words "the gate's
intent (no confidently-wrong verdicts at scale) is satisfied — **zero
false-accept risk**". "No confidently-wrong verdicts" is a suggestion-level
statement, and it is now measurably false.

The suggestion-level term now has a first measurement, and it is not small:
**≥1,261 wrong printing suggestions, 3.07% of positive join-key votes.** These
reach users — `models.suggested_printing_votes_prefetch()` selects
`source in (DEDUCTION, OCR)`, `is_no_match=False`, ordered by pk, to populate
`suggestedCanonicalCard`. For 183 of the 1,261 the join-key vote is itself the
first machine vote by pk; for 1,072 of the rest the first vote is the
`local-ocr-v1` row naming the _same_ contradicted printing. Essentially all
1,261 surface a contradicted printing.

Master's own code agrees these are votes that should not have been cast:
`JOIN_KEY_ARTIST_MISMATCH_SKIP_REASON` ("the parse contradicts its own source
string") was shipped 2026-07-29 to withhold exactly this class. The mechanism is
benign in origin — proxies templated with the mainline collector number while
carrying alternate art, 87.8% having an artist-consistent sibling printing of
the same name — but the vote is a claim about what the image depicts, and it is
contradicted by the image's own printed artist line.

### 3c. `stage-d-fallback-v1` — 30,311 votes, never compared against anything, and it loses 90% of the adjudicable disagreements. UNTESTED → FAILS

Artifact 1 excluded the fallback channel by construction (its bucket d, 13,026
cards, "pilot engine has no Stage D analogue"), and §12 records that at gate time
`stage-d-fallback-v1` had **never cast a vote in production**. Its first
production execution was the gate's own fire (29,710 votes,
`pilot-write-20260723T1202Z`). So the gate's parity replay covered **zero** of a
channel that today holds **30,311** positive printing votes — 18% of the entire
printing pool — and no later artifact measured it either.

Measured now:

| pair                                             |   overlap |  agree |          conflict |
| ------------------------------------------------ | --------: | -----: | ----------------: |
| `local-ocr-v1` × `stage-d-join-key-v1`           |    33,622 | 33,622 |             **0** |
| `local-ocr-v1` × `local-phash-v1`                |     2,309 |  2,309 |             **0** |
| `local-phash-v1` × `stage-d-join-key-v1`         |     2,061 |  2,016 |                45 |
| `stage-d-join-key-v1` × `deductive-backfill-v1`  |     5,047 |  5,044 |                 3 |
| `stage-d-fallback-v1` × `deductive-backfill-v1`  |    15,085 | 15,022 |                63 |
| `local-phash-v1` × `stage-d-fallback-v1`         |     1,299 |    763 |               536 |
| `stage-d-fallback-v1` × `lands-artist-decomp-v1` |       234 |    138 |                96 |
| **`local-ocr-v1` × `stage-d-fallback-v1`**       | **1,203** | **15** | **1,188 (98.8%)** |

All 1,188 conflicts are two different printings **of the same card name** — a
sibling-printing disagreement, which is the exact question the pipeline exists to
answer.

**Adjudication.** For each conflict I tested whether the card's own
uploader-supplied name string contains the artist of the printing each channel
voted for. (This deliberately does not use `CanonicalCard` as ground truth: the
artist name is only the label of the printing the vote itself names, and the
discriminator is the catalog card's own name.)

- card name names the **OCR**-voted printing's artist only: **362**
- card name names the **fallback**-voted printing's artist only: **40**
- names both: 6 — names neither (undecidable): 780

On the 402 decisive conflicts, **`stage-d-fallback-v1` is wrong 362 times
(90.0%)**. Representative rows: card 137236 "Rancor (Extended Kev Walker)" —
OCR `ulg 110 / Kev Walker`, fallback `mar 82 / Marie Severin`; card 141315
"Darkness (Extended Daarken)" — OCR `40k 197 / Daarken`, fallback
`spg 124 / Wojtek Łebski`.

Stated honestly: 402 of 1,188 is a biased subsample — it selects cards whose
uploader named the artist, which is exactly the alt-art/extended-art population
where a border/artist/symbol intersection is most likely to mis-select. **This is
not an estimate of the fallback channel's catalog-wide error rate.** It is proof
that a large, never-audited disagreement population exists and that its error
direction is one-sided.

### 3d. `local-ocr-v1` × `local-phash-v1`'s perfect agreement is manufactured, not observed. UNTESTED → FAILS as corroboration

The 2,309/2,309 zero-conflict figure cannot come out any other way. When the two
legacy engines name different printings, `disagreement-with-other-engine` fires
and **neither vote is cast** (`docs/reference/skip-reasons.md`, OCR+phash
section; 1,914 such rows live = 957 suppressed disagreements). The pair's
disagreements are deleted at write time, so the surviving population is agreement
by construction. Any reading of "two independent engines agree on 2,309 cards" as
corroboration is unavailable.

### 3e. The pilot-era `d ≤ 2` printing-vote propagation is now confirmed dead. OPEN ITEM → FAILS

The sweep listed `local_clustering.compute_two_threshold_clusters`
(`NEAR_DUPLICATE_MAX_DISTANCE = 2`) as an open item, "not confirmed absent by
exhaustive search". Confirmed now: its only non-test caller anywhere in the tree
is `local_identify_printing_tags.run_pilot` (line 1289), and the legacy engine's
last production `CardScanLog` write was **2026-07-17** (`local-phash-v1`
14:18:19Z, `local-ocr-v1` 13:14:43Z). Stage D has no analogue. The capability is
not merely unported — it has not executed in twelve days and nothing schedules it.

### 3f. `lands-artist-decomp-v1` casts printing votes with no resolution floor. UNTESTED → FAILS on code, benign in data

`_land_pool_selected_cards` calls `local_identify_printing_tags._eligible_base_queryset`
directly. That helper carries the `custom-art`/`non-english` excludes and the
deductive-backfill exclude, but **not** the dpi floor — `select_candidates`
applies `.exclude(dpi__lt=RESOLUTION_FLOOR_DPI)` separately, and the lands path
does not (its own docstring says so: "filtered to `is_lands_target` rather than
`select_candidates`' engine-specific dpi-floor-only filter"). So §3 item 1, the
ruling's _highest-severity_ MUST-FIX, is absent from a printing-vote calculator.

Live impact is nil: 23 sub-floor cards exist catalog-wide and **0** carry a lands
vote. Graded as a code-invariant gap with no data consequence — worth closing for
consistency, not a fire concern.

### 3g. Three roster/status assertions in `skip-reasons.md` that production contradicts

Minor but they are the same species of defect the roster exists to prevent:
`no-clear-winner-distance` and `no-clear-winner-margin` (issue #207's refinement)
are marked **Live** and have **0 rows** — the legacy phash engine has not run
since 2026-07-17, so the refinement has never executed in production;
`truncated-image` is marked Live with 0 rows; `proxy-marker-veto`'s entry implies
surviving historical rows and there are **0**. Separately, `color_profile`'s
"historical rows also exist" note undersells it — 3,256 rows, all `fetch_failed`,
most recent **2026-07-26**, for an extractor retired 2026-07-27.

### 3h. The calculator tether has a one-directory hole, and a real identity falls through it

`_declared_calculator_identities()` and `_declared_skip_reasons()` both use a
**non-recursive** `src_dir.glob("*.py")` over `MPCAutofill/cardpicker`, so
`management/commands/` is not scanned. `SCRYFALL_TAGGER_ANONYMOUS_ID = "scryfall-tagger-v1"` lives at
`MPCAutofill/cardpicker/management/commands/import_external_ip_tags.py:91` and
writes real `PrintingTagVote` rows with `source=DEDUCTION`. It is therefore:
absent from the tether's derived set (16 identities, verified by running the
linter), absent from `docs/pipeline-fidelity-gate.md`, absent from the
allowlist — and dormant in production (0 rows). That is precisely the
configuration §14's own "the three identities this page omitted" note describes
as the failure a coverage audit cannot surface. The mechanism built to stop it
recurring does not reach one directory deeper than the modules it was built from.

---

## 4. What remains unverifiable, and why

1. **Artifact 1 cannot be re-run or re-scored.** Its 2026-07-22 cohort no longer
   exists: 52,349 join-key votes were retracted by the lexicon-gate pass, the
   whole catalog was re-extracted 2026-07-25/26, and `local-fallback-v1`'s entire
   printing-vote population has since been removed (11,947 → 0). §8's
   owner ruling already declares it closed history. Everything in §3a/§3b above
   is therefore an argument about **what the number could ever have meant**,
   demonstrated on today's equivalent populations — not a re-scoring.
2. **The fallback channel's true catalog-wide error rate.** 780 of the 1,188
   conflicts are undecidable by the card's own name, and there is no
   image-independent ground truth in the database. Owner ruling stands that
   `CanonicalCard`/`CanonicalPrintingMetadata` is imported reference data, not
   truth, with no import timestamp anywhere. Measuring this needs a human-audited
   sample, not another query.
3. **Whether the 1,261 artist contradictions are "wrong votes" or "correctly
   decoded votes on mislabelled proxies"** is a semantics question for the owner,
   not a measurement. What is not in question: master's own
   `artist-mismatch` gate withholds them going forward, and the pipeline's own
   definition of `CardPrintingTag` ("a vote that a given Card depicts a specific
   Scryfall printing") makes them false as depiction claims.
4. **`stage-d-illustration-v2`'s real yield.** 0 votes, 0 `CardScanLog` rows, 0
   `PilotRunLedger` rows — never run in production. The 2026-07-29 dry run
   projects 3,401 votes. Projection only.
5. **`PrintingTagVote` / `scryfall-tagger-v1` behaviour.** 0 rows. Nothing to
   audit yet; the finding is that nothing would have told anyone when there was.

---

## 5. Recommendation on the verdict

**Artifact 1 stands as what it actually is, and must be relabelled.** It is a
port-fidelity check — did the reimplementation reproduce the recorded pilot run
— and as that it passes, decisively: the two identities now agree 33,622/33,622
with zero conflicts. It does not depend on any doc roster, so PR #567 does not
touch it. What does not survive is §4's description of the 83.2% as a
"**cross-method**" figure and the owner ruling's inference from it to "**zero
false-accept risk**". Both should be corrected in place. The gate should not be
re-fired on artifact 1's account.

**Artifact 2's certification does not survive, but its findings do.** Every
constant it actually mapped still maps (§2b). What fails is the completeness
claim: the clause it could not test is now testable and passes on today's code
(§2a), but the sweep's scope never covered three vote-casting modules that
already existed (§1c), four more have landed since — three of them after the fire
(§1b) — and an entire vote family has appeared that the gate has never named
(§1d). Artifact 2 should be re-marked **DONE (2026-07-22 snapshot; superseded)**
with this report as its successor, not left reading DONE against a precondition
written in the present tense.

**The verdict "FIRED" should be QUALIFIED, not re-fired.** The reasoning:

- The property the fire actually turned on — no machine-only resolution — is
  intact and re-verified against the worst population available (§2c). Four
  resolved cards catalog-wide, none of them contested.
- The defects found are **suggestion-level**, not resolution-level: ~1,261 wrong
  printing suggestions from the join-key channel (§3b) and a 30,311-vote channel
  that was never compared to anything and loses 90% of its adjudicable
  disagreements (§3c). Both are real, both reach users through
  `suggestedCanonicalCard`, and neither can resolve a card.
- Re-firing the whole gate would re-run a sequence whose backlogs are drained
  (28 / 0 / 0 considered) and would not measure any of this. The gate's own
  instrument is blind to §3a–§3d by construction; running it again produces the
  same blindness.

So: keep FIRED, add a qualification recording that the gate's soundness argument
covers the resolution layer only, that the suggestion layer now has a measured
non-zero false-accept population, and that one channel holding 18% of the
printing pool entered production inside the fire itself without ever being
compared against a second witness.

**Numbered items for the owner are in the parent task's report, not restated
here.**

---

## Appendix — production snapshot, 2026-07-29

Catalog 230,770 cards (`printing_tag_status`: unresolved 230,744 / no_match 22 /
resolved 4).

`CardPrintingTag` 167,229 · `CardTagVote` 223,999 · `CardArtistVote` 7,132 ·
`PrintingTagVote` 0 · `PilotRunLedger` 995 rows.

| `anonymous_id` (`CardPrintingTag`)                                         |   rows | positive-vote cards |
| -------------------------------------------------------------------------- | -----: | ------------------: |
| `stage-d-join-key-v1`                                                      | 57,949 |              41,129 |
| `local-ocr-v1`                                                             | 40,969 |              40,969 |
| `stage-d-fallback-v1`                                                      | 30,311 |              30,311 |
| `deductive-backfill-v1`                                                    | 28,112 |              28,112 |
| `local-phash-v1`                                                           |  8,274 |               8,274 |
| `lands-artist-decomp-v1`                                                   |  1,488 |               1,488 |
| user UUIDs                                                                 |    128 |                   — |
| `stage-d-illustration-v1`                                                  |      1 |                   1 |
| `local-fallback-v1`                                                        |  **0** |                   0 |
| `stage-d-illustration-v2`, `local-name-frequency-v1`, `scryfall-tagger-v1` |      0 |                   0 |

`CardScanLog` skip-reason column: 23 distinct live values; 37 distinct declared
in code across 51 constants.

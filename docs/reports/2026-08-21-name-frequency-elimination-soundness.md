# `local-name-frequency-v1`: measuring the structural double gate's actual soundness (2026-08-21)

## Task

`collector_line_artist.py` asserted, twice, that `local-name-frequency-v1`
(`run_name_frequency_elimination`) is "79.8% unsound," once attributing that
number to a specific cause: a private second name normaliser splitting one
predicate across two name spaces. A repo-wide search turns up no report,
probe script, data record, or linked issue backing either the number or the
mechanism — the two sentences in `collector_line_artist.py` are the only
places `79.8%` appears in that context anywhere in the codebase (the same
digits appear twice elsewhere, as a **latency** figure in milliseconds —
`local_identify_printing_tags.py`'s tier-timing comment and
`docs/features/printing-tags.md`'s performance table — a coincidence this
report does not rely on or explain). This report measures the calculator's
actual soundness, read-only, against production data, and states honestly
what is and isn't checkable on this catalogue.

## What's actually being measured

`run_name_frequency_elimination`'s gate (`local_identify_printing_tags.py`)
votes for a card only when, for that card's exact `name` string, **both**
halves hold catalogue-wide:

1. exactly one candidate printing of that name is _uncovered_
   (`compute_covered_printing_pks`, unscoped by this measurement's own
   design — see Method); and
2. exactly one unresolved, pilot-eligible card shares that name
   (`_eligible_base_queryset(NAME_FREQUENCY_ANONYMOUS_ID)`).

The module's own docstring already measures how often that double gate
_fires at all_, catalogue-wide, as of 2026-07-16: 2,076 names have exactly
one uncovered printing, and only 1,678 of those also have exactly one
unresolved eligible card. That is a **firing-frequency** count, not a
**precision** measurement — it says nothing about whether the vote the gate
would cast is actually correct. This report measures precision: of the
votes the double gate would cast, how many match the truth.

This report does **not** touch the separate 2026-07-30 image-evidence
conjunct (`printing_attribute_disagreement`) the calculator now also
requires before voting — that is out of this task's scope, and since the
conjunct can only ever turn a `fires` into an `abstains` (never the
reverse), excluding it makes this report's precision figure a **lower
bound** on the precision of the calculator as it actually runs today, not
an overstatement of it.

## Method

Read-only, via `sudo docker exec -i mpcautofill_django python manage.py shell`, against the live production database. No write, no management
command invoked.

**Ground truth.** 23,203 `Card` rows with a confirmed `canonical_card`
(`card_type=CARD`, no resolved `custom-art`/`non-english` tag) — a human or
the exact-by-construction deductive backfill has already confirmed which
real printing each of these depicts. This is the only ground truth this
catalogue supports for this question; `inferred_canonical_card` (a
vote-derived, unconfirmed guess) is deliberately excluded from the truth
set to avoid grading the calculator against other calculators' guesses.

**Simulating "this card was still unresolved."** For each ground-truth card
`C` (name `N`, confirmed printing `P`):

- **Eligible-count**: computed with the _real_ `_eligible_base_queryset`
  (the exact function the calculator itself calls), grouped by raw
  `Card.name` — i.e., "how many OTHER unresolved eligible cards share this
  name today." `C` itself is resolved, so it never appears in this count;
  adding it back in gives "eligible count if `C` alone were still
  unresolved."
- **Coverage without `C`'s own contribution**: `compute_covered_printing_pks`
  is a union of (a) cards with a confirmed `canonical_card` and (b) cards
  with a _resolved_ `inferred_canonical_card`. This report precomputes, per
  printing, the **count** of distinct confirming cards (not just the set),
  so `C`'s own confirmation of `P` can be subtracted back out — `P` is
  "covered without `C`" only if some _other_ card also confirms it.
- **Candidates**: `CandidateNameIndex.candidates_for(N)` — the real,
  three-tier normaliser the calculator itself uses, unmodified.

The gate "fires" on `C` when eligible-count (excluding `C`) is 0 (so `C`
would be the sole eligible card) **and** exactly one candidate is uncovered
once `C`'s own contribution is removed. When it fires, the predicted
printing is compared against `C`'s real confirmed `canonical_card_id`.

**Known limitation, stated rather than hidden**: this cannot recover
_resolution order_. If two cards of the same name were both eventually
resolved, this method (correctly) treats whichever one isn't `C` as "already
resolved" at simulation time, which is only exactly right if that other
card really was resolved first. There is no timestamp trail cheap enough to
reconstruct true historical resolution order from current state, so this
is an approximation the sample size is large enough to absorb but not
eliminate.

## Result

```
ground_truth_total                    23,203
  no_candidates (name -> 0 printings)     910   (3.9%)
  not_sole_eligible                       394   (1.7%)
  gate_would_not_fire (uncovered != 1) 18,903  (81.5%)
  gate_fires                            2,996  (12.9%)
    correct                             1,051  (35.1% of fires)
    wrong                               1,945  (64.9% of fires)

PRECISION = 1,051 / 2,996 = 35.1%
```

So: **the structural double gate is genuinely unsound** on this checkable
population — wrong on roughly two out of every three votes it would cast,
not one in five as "79.8% unsound" implies (79.8% unsound would mean ~20.2%
correct; the measured figure is 35.1% correct). The direction of the
original claim ("this calculator is unsound") holds; the specific number
does not, and this report's 64.9% replaces it as the supported figure.

A bracket-annotation confound was checked and ruled out: 2,987 of the 2,996
firings (99.7%) are on names carrying a `[SET]`/`(variant)`-style suffix in
the raw `Card.name` (which `to_searchable` strips before matching) — but
that is simply how nearly all of this ground-truth population is named, not
a differentiator; the tiny bracket-free residue (9 firings, 2 correct) is
too small to draw a separate conclusion from and is reported only so it
isn't silently dropped.

Ten of the wrong predictions, and five of the correct ones, are recorded in
this report's companion probe output for spot-checking; card/printing pks
are internal database identifiers, not published here as they carry no
independent meaning outside this database.

## The claimed mechanism doesn't match the code or the calculator's history

The specific causal claim in `collector_line_artist.py` — that a private
second normaliser splitting one predicate across two name spaces is "exactly
what made `local-name-frequency-v1` unsound" — does not match what the code
does or what its own commit history documents as its actual defects.
`run_name_frequency_elimination` has never had a private second normaliser:
it calls the same `CandidateNameIndex.candidates_for` (the shared
`to_searchable`-based three-tier normaliser) that `NameArtistLookup` itself
delegates to. Its two documented, _fixed_ defects (PR #665, 2026-07-30) were
(a) no image-evidence cross-check before voting, and (b) a lifetime
self-suppression census leak across runs — neither is a name-space
mismatch.

There is a real, present, and different name-space split in the calculator
worth naming honestly: it groups its eligible-card count by the **raw**
`Card.name` string, while it resolves candidate printings through the
**normalised** `to_searchable` key. Two raw name variants that normalise to
the same key (a trailing `(1)`, differing whitespace, a duplicate-upload
suffix) are counted as separate eligible-card groups even though
`candidates_for` would resolve them to the identical candidate set — the
same shape of hazard the original comment describes, just not proven here
to be the dominant cause of the 64.9% figure above (most of the traced
wrong predictions instead come from a printing being covered by an
entirely different, unrelated `Card` row of a different name — see Method).

## Bounds on generalising this measurement

Two catalogue-wide facts bound how far this figure travels:

- measured 2026-08-21, read-only, against production, via `to_searchable`
  (the same normaliser `CandidateNameIndex` itself uses) checked for an
  exact match against `CanonicalCard.name`: of 227,473 `card_type='CARD'`
  rows, 220,170 (96.8%) match; counted by distinct normalised name instead
  of by row, 29,716 of 32,416 (91.7%) match. Two independent measurement
  paths (a raw set-membership test and `CandidateNameIndex.candidates_for`
  itself) reached the identical figures. (An earlier version of this bullet
  claimed ~48% match with no supporting measurement; both denominators
  above refute it.)
- upstream illustration/printing metadata exists for ~28% of distinct names
  (34,869 of 124,052).

This report's ground-truth population (23,203 confirmed-match cases) is, by
construction, the subset of the catalogue that _already_ resolved
successfully — that much is measured and holds on its own terms, independent
of the bullet above. What the corrected figures do NOT support is a
direction for how the 35.1%/64.9% split would move on the ~204,000
still-unresolved cards: the argument this section previously built for
"structurally worse, likely worse" rested on the wrong 48% figure and does
not survive its correction. No measurement here establishes whether the
still-unresolved population's precision would be better, worse, or the same.
The split above should be read as measured on this ground-truth slice only,
with no claim about which direction it would move elsewhere.

## Conclusion

`local-name-frequency-v1`'s structural double gate is unsound: wrong on
64.9% of its 2,996 checkable simulated firings (1,945/2,996), not 79.8%.
The design argument `collector_line_artist.py` makes for keeping
`NameArtistLookup` free of a private normaliser stands on its own
engineering merits regardless of this number; the specific number and its
specific attributed cause did not, and are corrected in that file to cite
this report instead.

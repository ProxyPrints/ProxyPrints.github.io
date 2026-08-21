# Art-edge continuity retune: within-image relative comparison — result: does not clear the bar, not persisted

2026-08-06. `local_art_edge.classify_art_edge_continuity` retuned from an ABSOLUTE per-band
pixel-variance test (`local_fallback._BORDER_UNIFORMITY_STD_THRESHOLD`, tuned for
`classify_border_color`'s different question) to a WITHIN-IMAGE relative colour comparison: does
the band beside the art crop match the border colour this same image's `layout_class`
(`classify_border_color`'s own output) already says it has? Validated against Scryfall's own
images for three real cohorts before any persistence decision. Result: does not clear the stated
bar. No `ImageEvidence` field added, no migration, no Stage C wiring, no `EXTRACTOR_OWNERSHIP`
entry. `classify_art_edge_continuity` stays evidence-only, called from nowhere but its own tests,
exactly as before this change.

## The defect this retune targets

Measured on 467 real catalogue images (prior session, report filed in the separate
`proxyprints-orchestration` repository, not this one — "art-edge-continuity-gate", 2026-08-06):
the pre-retune classifier's `extended`
reading fired on 7 of 467 images, and every one of those 7 edge-band samples read RGB like
`(14,13,26)` — dark artwork, not a border. The absolute variance threshold (18.0 std) cannot
distinguish "flat because it is a painted border" from "flat because it is dark, and dark content
has a compressed pixel-value range by construction" — it was measuring darkness and reporting it
as border uniformity.

Confirmed by hand in this session before writing any new code (`/tmp/opencode/scratch_art_edge/probe3.py`,
not committed — synthetic images with an exact, controlled per-band colour): a card with a genuine
flat black border (RGB ~(5,5,5), std 4) and a dark, TEXTURED, off-hue navy strip beside the art
crop (RGB ~(10,10,40), std 140 — real variance, not flat) read `extended` under the pre-retune
code. The adjacent band's real texture cleared the old "not flat" bar; the edge band's own flat
darkness cleared the "border" bar; neither check ever compared the two bands' actual colours
against each other.

## The retune

`classify_art_edge_continuity` now takes a `layout_class` argument (the caller's own
already-computed `classify_border_color` result for this same image, not recomputed here):

- `layout_class == "borderless"` → `open`, decided from the stored classification alone. No
  border exists to compare against, and a borderless card cannot be extended-art by definition.
  No pixel sampling happens on this path (pinned by
  `test_borderless_layout_class_short_circuits_to_open_without_sampling`, which monkeypatches
  `_sample_band` to raise if it is ever called).
- `layout_class is None` (`classify_border_color`'s own "uniform but not a colour this taxonomy
  covers" abstention) → abstain (`None`). No colour to compare against.
- otherwise (`black`/`white`/`silver`) → sample the edge band (`_BORDER_SAMPLE_BANDS`, the same
  bands `classify_border_color` already samples) for its mean RGB — the border colour THIS image
  actually has, not an archetype — and the art-adjacent band (unchanged geometry from the
  pre-retune code) for its own mean RGB. Euclidean RGB distance between the two: `< 70.0` →
  `framed`; otherwise → `extended`.

No new pixel extraction: both bands already went through `local_fallback._sample_band`, which
already computes mean RGB — the pre-retune code discarded that field and used only the returned
std. The retune consumes the mean instead of (in the edge band's case) in addition to consuming
it a second way. `_BORDER_UNIFORMITY_STD_THRESHOLD` and the edge band's own uniformity test are no
longer read anywhere in this module — `layout_class` already being non-`None`/non-`borderless`
already means `classify_border_color` found that same band uniform enough to name a colour on its
own, already-validated threshold; re-testing the same pixels' variance a second time here would
pay for one measurement twice without adding information.

Colour-distance measure and its threshold are justified in the code itself
(`local_art_edge.py`'s `_ART_EDGE_COLOR_DISTANCE_THRESHOLD` comment): plain Euclidean RGB, chosen
because it needs no new colour-space conversion beyond the mean-RGB triple `_sample_band` already
returns, at the acknowledged cost of being weakest exactly where two colours are both desaturated
(a grey/neutral patch of artwork beside a silver border) — a case this pass's cohorts did not
specifically exercise (Scryfall silver-bordered printings are a small, mostly funny-set
population; not drawn as a dedicated fourth cohort). 70.0 was chosen from the same synthetic-image
probe that reproduced the pre-retune bug: a genuine dark-navy-vs-black-border case measured
distance ~36 (must read `framed` — this is the ambiguous-but-not-clearly-different case the retune
exists to stop calling `extended`), a genuine vivid-artwork-vs-black-border case measured distance
~116 (must read `extended`); 70.0 sits with margin on both sides of that gap.

## Validation — Scryfall's own images, not catalogue name-matched uploads

The catalogue-cohort measurement this retune's brief brief was built against was already known to
be confounded: `canonical_card` is a filename/tag match made at ingestion, never a pixel-content
check, so an image "confirmed" against an `extendedart` printing may not actually depict that
printing's real artwork (see the prior session's report, "systematic pattern" section, for the
two failure signatures — pure-black-canvas sources and full-bleed-to-edge sources — this produced
in the pre-retune measurement). Scryfall's own image of a Scryfall-labelled printing has no such
gap: the label (`frame_effects`/`border_color`) and the pixels come from the same authoritative
source, by construction.

**Cohorts** (Scryfall search API, `order:name` for reproducibility, first N results, `image_uris. normal` — 488×680, no bleed margin):

- `extended`: `q=is:extendedart`, n=30.
- `borderless`: `q=is:borderless`, n=20.
- `framed` (ordinary, negative control): `q=border:black -is:extendedart -is:borderless -is:fullart -is:showcase`, n=20.

**Fetch discipline**: `cardpicker.harvest_fetch_limiter.SCRYFALL_REST` (search) and `SCRYFALL_CDN`
(images) — the same rate limiters `local_phash._fetch_scryfall_art_crop_url`/`_fetch_and_hash`
already use for Scryfall traffic, not a new pacing scheme. **No image pixels persisted**: every
fetched image lived only in the fetching process's memory for the duration of one classification
call, was never written to disk (including for debugging — the one hand-inspection of a single
card's sampled RGB values, below, printed numeric tuples only, no image file), and was discarded
(`image.close(); del image`) immediately after. No corpus, no fixture, no cache — a one-off run,
not a standing artefact (issue #697 stays deferred).

For each fetched image: `bleed_class = classify_bleed_edge(image)` (always `trimmed` for
Scryfall's images — no bleed margin, matching real print dimensions exactly), `layout_class = classify_border_color(image, bleed_class)`, `art_crop_px` derived the same way
`image_evidence._crop_box_to_pixels` derives it in production, then both the pre-retune classifier
(reproduced verbatim in the throwaway probe script, not committed — this PR replaces the only
copy that lived in the repo) and the retuned one were run against the identical inputs.

## The numbers

| cohort     |   n | truth        | OLD → `extended` | NEW → `extended` |
| ---------- | --: | ------------ | ---------------: | ---------------: |
| extended   |  30 | extended     |         1 (3.3%) |     **0 (0.0%)** |
| borderless |  20 | not extended |         0 (0.0%) |         0 (0.0%) |
| framed     |  20 | not extended |         0 (0.0%) |         0 (0.0%) |

**The bar** (stated in the brief before measuring): correctly call Scryfall's own extended-art
images `extended`, without calling Scryfall's own ordinary framed images `extended`, at a rate
useful as a discriminator. **Not cleared.** The retuned classifier's recall on genuine
extended-art images is 0/30 — worse than the pre-retune classifier's already-poor 1/30 on the same
images. Neither version produces a false positive on either negative cohort (0/20 and 0/20 both
ways), so the retune has not made anything worse for the negative case — but a discriminator with
zero recall on its positive class and a low, uninformative false-positive rate born from almost
never firing at all is not evidence of precision (the same caveat the prior session's report
raised about the pre-retune numbers).

## Root cause of the retune's own shortfall

Traced by hand-inspecting the one case where the pre-retune classifier got a genuine extended-art
card right and the retune did not ("Academic Probation", Strixhaven `stx`,
`/tmp/opencode/scratch_art_edge/debug_one.py`, not committed): `layout_class` correctly read
`black` for this card, but the sampled border RGB (~(36, 39, 40)) and the sampled art-adjacent RGB
(~(40, 45, 48)) were only ~10 Euclidean units apart — both readings landing on genuinely dark,
similarly-toned pixels, not a clean black-border-vs-vivid-art contrast.

Two compounding causes, both upstream of anything this PR's scope reaches:

1. **`classify_border_color`'s own catch-all reads 20 of the 30 (66.7%) genuine extended-art
   Scryfall images as `borderless`**, not `black` — the pre-existing, explicitly out-of-scope
   defect this module's own docstring already documented against the catalogue population
   (54.9% there; higher here, plausibly because Scryfall's crisper official scans show MORE
   genuine edge-band variance than an average proxy upload, making the "not uniform → borderless"
   catch-all fire more often, not less). `layout_class == "borderless"` short-circuits this
   retune straight to `open` — correctly, given what `layout_class` says, but `layout_class`
   itself is wrong for these 20 rows.
2. **For the remaining 10 where `layout_class` correctly reads `black`, the edge band geometry
   itself is too thin to sample reliably on a Scryfall image.** `_BORDER_SAMPLE_BANDS`' raw
   fractions (tuned against a bleed-inclusive image) pass through `normalize_crop_box(band, "trimmed")` for every Scryfall image (Scryfall images are always geometrically trimmed — no
   bleed margin). Measured directly for "Academic Probation": the left edge band's remapped
   fraction range is `(0.0, 0.0046)` — roughly 2 pixels wide on a 488px-wide image. A 2-pixel
   sample sits at the exact image boundary, where antialiasing and JPEG blur dominate over any
   real border colour, and is not a reliable colour reference regardless of which comparison is
   built on top of it. This is a `normalize_crop_box`/`_BORDER_SAMPLE_BANDS` geometry property
   (`local_fallback.py`, PROTECTED CORE), shared by `classify_border_color` itself on any trimmed
   image — not something introduced by, or fixable within, this PR's scope
   (`local_art_edge.py` only).

Both causes sit entirely upstream of the comparison this PR was scoped to change. The specific
bug this retune targeted — dark, textured artwork being read as a border because it is flat and
dark rather than because it is a border — IS fixed, confirmed by the synthetic reproduction above
and pinned by `test_dark_off_hue_artwork_beside_a_black_border_does_not_read_extended`. It is not
sufficient on its own to make this classifier a useful discriminator against real images, because
the majority of its failures trace to `layout_class`/`normalize_crop_box` inputs it correctly
trusts but that are themselves unreliable for this specific input population.

## Tests

`MPCAutofill/cardpicker/tests/test_local_art_edge.py`, fully rewritten for the new signature and
comparison. Per-test mutation checks (each confirmed to fail when the behaviour it asserts is
removed):

- `test_adjacent_matching_black_border_reads_framed` /
  `test_adjacent_matching_white_border_reads_framed` — border-colour match reads `framed`.
  Fails if the comparison direction is inverted (would fail if a match were classified `extended`).
- `test_dark_off_hue_artwork_beside_a_black_border_does_not_read_extended` — THE defect
  reproduction: dark, textured, off-hue navy beside a real black border. The pre-retune code
  (confirmed by hand, see "Confirmed by hand" above) returns `extended` for this exact
  construction; the retuned code returns `framed`. Fails if the retune regresses to the old
  behaviour.
- `test_vivid_artwork_beside_a_black_border_reads_extended` — the genuine positive, colour clearly
  far from the border. Fails if the threshold is set so high nothing ever reads `extended`.
- `test_borderless_layout_class_short_circuits_to_open_without_sampling` — monkeypatches
  `_sample_band` to raise; fails (loudly, via the injected exception) if the borderless
  short-circuit is ever removed and sampling runs anyway.
- `test_ambiguous_layout_class_abstains` — fails if a `None` `layout_class` is ever treated as a
  real border to compare against.
- `test_mutating_the_distance_comparison_collapses_every_case_together` (parametrized, both
  directions) — MUTATION PROOF: monkeypatches `_ART_EDGE_COLOR_DISTANCE_THRESHOLD` to a value
  that makes every distance read as a match, then to a value that makes no distance read as a
  match, and asserts a genuine match case and a genuine mismatch case collapse to the SAME answer
  in each direction. Fails if the threshold comparison is bypassed by anything else in the
  function.
- `test_trimmed_image_reads_the_art_adjacent_strip_in_its_own_frame` /
  `test_double_remapping_the_art_crop_would_change_the_answer` — the pre-existing
  coordinate-frame asymmetry (edge band remapped, `art_crop_px` not re-remapped), carried forward
  unchanged since the retune does not touch this geometry.
- `test_unusable_art_crop_px_abstains` (parametrized) — degenerate/missing `art_crop_px` inputs.

`TestCastArtEdgeContinuityVote` carried forward unchanged — `cast_art_edge_continuity_vote`'s own
signature and behaviour are untouched by this retune.

**Order-dependence (issue #679)**: `test_local_art_edge.py` run individually — 23 passed (55.6s).
Full `cardpicker/tests/` suite run together — 3678 passed, 8 skipped, 0 failed (779.4s). Both runs
clean; no order-dependent failure surfaced for this module.

## Recommendation

**Do not wire, do not persist.** No `ImageEvidence.art_edge_class` field, no migration, no Stage C
extraction, no `EXTRACTOR_OWNERSHIP`/manifest entry, no vote wiring — matching the brief's own
stated fallback. The retuned comparison is real, tested, and does fix the specific bug it targeted
(confirmed both synthetically and by the "Academic Probation" trace not regressing on THAT
mechanism — its remaining miss traces to inputs, not to the comparison itself). It is shipped as
the new `classify_art_edge_continuity` implementation, evidence-only, called from nowhere but its
own tests — the same state the pre-retune code was already in, on more defensible internals.

**What would change this recommendation**: fixing `classify_border_color`'s "not uniform →
borderless" catch-all for the extended-art population (already an open item on that classifier,
predating this PR), and/or widening `_BORDER_SAMPLE_BANDS`'/`normalize_crop_box`'s trimmed-image
edge-band geometry so it is not reduced to ~2px on a genuinely trimmed image. Both are
`local_fallback.py` (PROTECTED CORE) changes, out of this PR's scope by the brief's own framing,
and both would need their own validation pass before being trusted — not a reason to fold them
into a retune of a different module speculatively.

## Reproducibility

Not committed (this repo's established convention for one-off analysis scripts, matching the
prior session's own precedent):

- `/tmp/opencode/scratch_art_edge/probe3.py` — the synthetic-image reproduction of the pre-retune
  defect and the retuned fix, run against both the pre- and post-retune code.
- `/tmp/opencode/scratch_art_edge/scryfall_validation.py` — the three-cohort Scryfall fetch/
  classify probe (search via `SCRYFALL_REST`, images via `SCRYFALL_CDN`, both the pre-retune
  classifier reproduced inline and the retuned one imported live from the module under test).
- `/tmp/opencode/scratch_art_edge/scryfall_validation_results.csv` — the 70-row raw output
  (cohort, Scryfall id/name/set, `bleed_class`, `layout_class`, old/new classification — no image
  data).
- `/tmp/opencode/scratch_art_edge/debug_one.py` — the single-card diagnostic trace behind the
  "root cause" section above (numeric RGB/distance output only, no image written to disk).

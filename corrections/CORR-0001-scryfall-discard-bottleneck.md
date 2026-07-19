# CORR-0001: Scryfall REST calls discarding already-fetched art-crop URLs

- **Date**: 2026-07-19
- **Trigger / wrong premise**: `get_or_compute_canonical_hash` queried
  Scryfall's live REST API per candidate for the art-crop image URL,
  even though the same URL (`image_uris.art_crop` /
  `card_faces[0].image_uris.art_crop`) was already present — and
  discarded, unused — in the weekly bulk-data dump that
  `import_scryfall_printing_metadata` reads for every card anyway.
- **How caught**: the owner flagged directly that a live REST query
  shouldn't be necessary for data already being pulled in bulk;
  confirmed with an instrumented before/after probe
  (`probe_harvest_pipeline --sample-size=30`, identical 30-card
  methodology both times) rather than taken on faith.
- **Blast radius**: at measurement time, 34.5% of catalog candidates
  (39,080 of 113,224) were paying a live, unnecessary REST + CDN
  round-trip on every hash computation. Probe: phash mean
  16.272s/card → 1.834s/card (8.9x); total probe wall-clock
  521.76s → 85.79s (6.1x).
- **Systemic fix**: `PrintingMetadataRow` now parses the art-crop URL
  straight from the bulk dump; `CanonicalPrintingMetadata.art_crop_url`
  stores it; the hash function checks this local field first, live
  REST only as a genuine-gap fallback. Shipped in `65df7d8d` (PR #131,
  2026-07-19), confirmed via the after-probe in `e10e4c41`, narrative
  in `docs/features/catalog-completion-plan.md` (lines ~743-820).
- **Disposition**: `gate` (the code fix removes the unnecessary call
  path outright) + `eval` (the before/after probe methodology is the
  permanent evidence a regression would be caught the same way again).

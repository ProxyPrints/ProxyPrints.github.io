# CORR-0002: proposed R2 image-persistence tier violated the no-image-storage posture

- **Date**: 2026-07-19
- **Trigger / wrong premise**: two proposed designs (a "write-through
  hedge" persisting a copy of every fetched image to R2, ~44GB /
  ~$0.66/mo, and a related whole-image-persistence idea for a new
  R2-cached harvest tier) were framed as sensible engineering hedges
  against re-fetch cost — cheap, so assumed uncontroversial.
- **How caught**: an owner FINAL POSTURE directive rejected both,
  2026-07-19 — on legal/federation-posture principle, not cost. This
  project's governing claim is "card artwork never crosses the wire" /
  is never stored; any pixel-retention tier violates that regardless
  of how cheap or convenient it is.
- **Blast radius**: both proposals closed SUPERSEDED-BY-POSTURE before
  any of it was built — caught at design/proposal time, zero shipped
  code affected. Stage C's evidence-store design changed to
  pure-metadata-only (hashes, OCR text/TSV, geometry — no persisted
  crops) as a direct result.
- **Systemic fix**: a standing test codified directly in CLAUDE.md
  ("Governing premise: we index, we do not store images" — "if it
  stores image pixels beyond transient display-serving cache, it
  fails regardless of other merits"), specifically so the same idea
  can't be silently re-derived and re-proposed by a future session
  without hitting this test first. Shipped in `62e5e7b8` (PR #132,
  2026-07-19); full posture narrative in
  `docs/features/catalog-completion-plan.md` (~line 1006 on). The
  cancelled design's specifics are deliberately NOT re-described in
  CLAUDE.md itself, so a future session evaluates the standing test
  fresh rather than re-deriving the old proposal from its own
  cancellation notice.
- **Disposition**: `prose` (a standing doc test in CLAUDE.md) —
  candidate for future `gate` promotion (a lint/CI check scanning for
  image-persistence code patterns) if this recurs, per
  `docs/lessons.md`'s triage note; not built as a gate yet since it
  hasn't recurred.

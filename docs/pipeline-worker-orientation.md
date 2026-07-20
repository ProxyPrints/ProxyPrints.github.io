# Pipeline worker orientation (Stage C / extractor work)

Lowest-token bootstrap for a worker building or touching a Stage C
extractor. Read this doc plus your one specific task module (the
issue/task describing your extractor) — that's the whole bootstrap.
You should not need `docs/features/catalog-completion-plan.md` (1,500+
lines) or to open `image_evidence.py`/`models.py`/`golden_set.py` cold;
they're linked below for depth only, not required reading.

Scope: catalog/pipeline knowledge only. Nothing here about fleet
coordination, worker rostering, or reporting format — that's covered
elsewhere and isn't this doc's job.

## Core — know exactly this before writing code

**Governing posture: we index, we do not store images.** The catalog
persists knowledge _about_ a card's image, never the image itself.
`ImageEvidence` is pure metadata — hashes, OCR text, geometry/layout
classes, quality signals. Crop **coordinates** persist; crop **pixels**
are computed in memory during extraction and discarded, never written
anywhere. Standing test for anything you build: if it stores image
pixels beyond transient display-serving cache, it fails, full stop —
no exceptions for "just this once" caching ideas. See `CLAUDE.md`'s
"Governing premise" and `docs/features/catalog-completion-plan.md`'s
"Governing posture" section for the full directive.

**Mental model: this is a funnel to a human review queue, not an
auto-committing pipeline.** Nothing an extractor or calculator produces
gets written as a verdict on its own — it feeds a human confirmation
step downstream. Two-speed shape:

- **Geometry/bleed runs first, on every card.** Cheap, and its output
  (`width`/`height`/`bleed_class`) is what later crop-coordinate
  extractors need to aim their crop regions correctly.
- **Collector-line OCR is the near-unique join key.** A parsed
  `(set_code, collector_number)` pair is usually enough to look a
  printing straight up in Scryfall data — the fast path, roughly 17% of
  cards today.
- **Cards that don't hit fall to phash/visual measurement** — the slow
  path, comparing rendered images rather than reading printed text.
- **Extractors emit raw signals only.** The Scryfall lookup itself,
  agreement-checking, and deduction from raw signals to a printing
  identity is Stage D (the calculator layer)'s job — never something an
  extractor does itself. If you're tempted to add a lookup or a verdict
  inside an extractor function, stop — that's out of scope for Stage C.
- Scryfall's bulk data lives on disk as `default_cards.json`, loaded via
  `MPCAutofill/cardpicker/printing_metadata_import.py`.

**The extractor pattern** (see `image_evidence.py`'s module docstring
for the full rationale):

- The image is fetched **once**, at the top of `extract_card_evidence`
  — every extractor function in that pass reuses the same in-memory
  image, never re-fetching.
- **One pure function per signal.** No DB writes inside it — it only
  computes and returns. Where a signal already has a shipped classifier
  (`local_fallback.classify_bleed_edge`, `classify_border_color`,
  `extract_artist_name`; `local_ocr.parse_collector_line`,
  `run_tesseract_tsv`), **call it, don't re-derive the logic** — this is
  what keeps stored evidence guaranteed-consistent with what the live
  pilot/vote path already concludes.
- Every extractor records its own key in `extractor_versions` (ran to
  completion) and, if it declined to produce a value, a matching key in
  `skip_reasons` (a named reason, e.g. `fetch_failed`/`ambiguous`/
  `no-text` — reuse an existing reason string before inventing a new
  one). Omitting the key entirely (neither map) means it crashed —
  that's "dropped," a different, worse outcome than a named skip.
- `persist_evidence` is a separate, later step. It writes only the
  fields your own extractor computed (`get_or_create` + per-field
  merge) — never touches another extractor's already-written columns.
  This additive discipline is what makes independent, one-extractor-
  per-PR PRs safe to land in any order.
- **One PR per extractor. Golden-gate before merge** (see below) — this
  is the hard gate, not a suggestion.
- Any schema change is an **additive-only** migration (`AddField` only,
  never alter/drop an existing column). Before running a migration (or
  a golden-set gathering pass against production), check
  `gh issue list --label deploy-freeze-active` is empty, fresh, every
  time — don't rely on a check from an earlier session.

**PROTECTED CORE — import-and-call only, never modify.** Full list and
absorption protocol: `docs/upstreaming/license-provenance.md` §2/§3.
The two files a Stage C extractor will actually touch:

- `local_fallback.py` — protected core. Call its exported functions
  (`classify_bleed_edge`, `classify_border_color`, `extract_artist_name`,
  `normalize_crop_box`, its crop-box constants, etc.); never edit the
  file itself.
- `local_ocr.py` — **not** protected core. New OCR-adjacent helpers
  (e.g. `run_tesseract_tsv`) get added here directly when needed.

**Golden-set convention** (`golden_set.py`'s own docstring has the
full mechanics): `GOLDEN_CARD_IDS` is a fixed, pinned list of 30 real
cards. Your extractor's PR adds one new key to `GOLDEN_EXPECTATIONS`
(keyed by your extractor's name, matching its `extractor_versions` key)
holding its expected value per golden card. Gather those expectations
via a one-off, **read-only** script that calls `extract_card_evidence()`
only — never `persist_evidence` — against the real 30 cards, then
delete the script; it's not something that lands in the repo. Pin only
discrete/stable values (a classification, a parsed field) — leave out
continuous or brittle ones (raw OCR text, exact pixel floats, anything
that could drift on a library version bump) per the existing
extractors' own precedent.

## Map — for depth, read only what you need

- **Full pipeline design & status** (Stages A–F, all owner directives,
  BINDING): `docs/features/catalog-completion-plan.md` — "Governing
  posture" section for the storage posture in full; "Stages C–F" section
  for what's shipped extractor-by-extractor and what's queued next
  (phash, symbol-strip, legal-line, border-color follow-ups, Stage D's
  pipeline-fidelity gate).
- **Extractor code + the reasoning behind each design choice**:
  `MPCAutofill/cardpicker/image_evidence.py` — read its module
  docstring before its code; every "why this and not that" for the
  shipped extractors (geometry_bleed, layout_class, crop_coordinates,
  collector_line_ocr, artist_ocr, collector_line_tsv) is answered there.
- **Evidence storage model**: `MPCAutofill/cardpicker/models.py`'s
  `ImageEvidence` class docstring — keying, `extractor_versions`,
  reconciliation-ledger semantics (attempted/voted/skipped/dropped).
- **Golden-set mechanics**: `MPCAutofill/cardpicker/golden_set.py`'s
  module docstring — selection method, replacement policy if a pinned
  card ever disappears from the catalog.
- **PROTECTED CORE full file list + external-code absorption
  protocol**: `docs/upstreaming/license-provenance.md` §2 and §3.
- **Scryfall bulk-data import**:
  `MPCAutofill/cardpicker/printing_metadata_import.py`.
- **Storage posture, one-line version, always current**: `CLAUDE.md`'s
  "Governing premise" section.

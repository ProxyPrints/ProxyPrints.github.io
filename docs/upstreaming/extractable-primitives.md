# Extractable-primitives ledger

**Status: HOLD — seeded table for owner review**, not yet a to-do list. This
is an audit, not a build: it inventories what in this codebase is already
generic enough that an outside consumer could lift it wholesale, and marks
everything else honestly entangled. Nothing here implies intent to actually
send a PR — that's a separate decision per row, made later, by a human.

**Ground truth**: read directly from the repo on `master` (this audit's
branch point) by five parallel file-level passes — frontend search/browse,
frontend PDF/export, backend (`MPCAutofill/`), docs tooling + federation,
and the fork-only-modules inventory used by the mechanical tether below —
each verified against actual `import`/`from` lines, not inferred from
filenames or doc comments. 2026-07-19.

## Why this exists

This fork carries a lot of code that has nothing to do with its own
fork-only features (the weighted-vote/consensus system, `CanonicalCard`/
`CanonicalArtist`/`CanonicalPrintingMetadata`, Discord OAuth + the
Moderators gate). Some of it was written generic from the start; some
started fork-specific and got refactored clean along the way; some looks
generic but is quietly entangled by co-location (a clean function sitting
in a file whose _other_ top-level imports drag in the vote system). None
of that is visible without actually walking the codebase and checking
imports file by file — this table is that walk, kept current by the
mechanical tether in the next section instead of going stale the moment
someone adds an import.

**Candidate consumers**, referenced by short name in the table:

- **upstream** — `chilli-axe/mpc-autofill`, the project this repo forked
  from (see `docs/infrastructure.md`'s upstreaming workflow section)
- **proxies-at-home** — the wider MIT-lineage proxy-tooling ecosystem
  descended from/adjacent to mpc-autofill (not a single repo — a lineage)
- **federation peers** — other instances running this fork's federation
  protocol (`docs/federation-v1.md`, `docs/federation/public-export-v1.md`)

## The mechanical tether

A row marked `CLEAN` below is a claim: _this file imports nothing from the
fork-only vote system, `CanonicalPrinting`/consensus, or auth modules._
That claim is checked by `.github/scripts/docs_lint.py`'s
`check_extractable_primitives_tether()`, which runs in the same
`docs-lint.yml` CI job as the link/path checks (every PR touching
`docs/**`, and weekly regardless). It parses this file's own tables,
resolves every backtick-quoted file path in a `CLEAN` row, and greps that
file's own `import`/`from` lines (TYPE_CHECKING-guarded imports excluded —
type-only references aren't runtime coupling) against a hardcoded
fork-only-module allowlist (the vote system, `CanonicalPrinting`/
consensus, and auth/Discord modules — see the check's own docstring for
the exact list, kept there rather than duplicated here so there's one
place it can go stale, not two). A `CLEAN` claim that becomes false — a
future commit adds an import from `cardpicker.vote_consensus` to a file
this table calls clean — fails CI at the commit that causes it, not at
whenever someone next reads this file.

**Known limitation, same shape as the rest of docs-lint**: this checks
_direct_ imports of the exact file(s) listed in a row, one level deep —
it does not walk the import graph transitively. A file that's clean itself
but imports a _different_ local file that's entangled (e.g.
`GridSelectorResults.tsx` composing `GridSelectorFilters.tsx`, which then
imports `CanonicalCardFilter.tsx`) won't be caught by the tether if the
row is (wrongly) marked `CLEAN` — that class of entanglement has to be
caught by the human audit, same as any other judgment call docs-lint
can't make. Every row below that has this shape is marked entangled by
hand for exactly this reason, not left for the lint to catch.

The tether only checks the four named fork-only categories. A row can
still carry a non-`CLEAN` entanglement label for something outside that
scope (e.g. "entangled-with-image-cdn-infra") — those labels are honest
audit findings, just not mechanically enforced, because coupling to this
fork's own image CDN isn't a licensing/upstreaming concern the way
coupling to the vote system is.

## Frontend — search/browse

| Primitive                                         | File(s)                                                                                                                                                                                     | Problem solved                                                                                                                                                                                          | Candidate consumers                            | Entanglement                          | License note                                                                                                                                       |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Scroll-triggered virtualization                   | `frontend/src/components/RenderIfVisible.tsx`                                                                                                                                               | Cheaply virtualizes long lists/grids of expensive DOM (card images) via IntersectionObserver + ResizeObserver, no windowing library                                                                     | upstream, proxies-at-home, federation peers    | CLEAN                                 | Vendored from `NightCafeStudio/react-render-if-visible` (MIT) with an upstream bugfix applied — preserve attribution on lift                       |
| Requested-printing badge (mechanics only)         | `frontend/src/features/card/RequestedPrintingBadge.tsx`                                                                                                                                     | Shows a slot's literal search input alongside a resolved/substituted result so a silent substitution isn't lost                                                                                         | upstream, proxies-at-home                      | CLEAN                                 | —                                                                                                                                                  |
| Generic UI kit                                    | `frontend/src/components/OverflowList.tsx`, `OverflowCol.tsx`, `Blurrable.tsx`, `ClickToCopy.tsx`, `AutofillTable.tsx`, `Spinner.tsx`, `DisableSSR.tsx`, `icon.tsx`, `AutofillCollapse.tsx` | Assorted self-contained UI primitives (overflow-collapsing list, viewport-relative scroll column, click-to-copy, generic table, SSR-skip wrapper, etc.)                                                 | upstream, proxies-at-home                      | CLEAN                                 | `OverflowList.tsx` vendored from `mattrothenberg/react-overflow-list` (MIT); `DisableSSR.tsx` credited to a StackOverflow answer in its own header |
| Embeddable version-picker (`GridSelectorResults`) | `frontend/src/features/gridSelector/GridSelectorResults.tsx`, `GridSelectorModal.tsx`, `useGridSelectorSearch.ts`                                                                           | Renders a card-version picker as modal or inline-embedded, driven by one search hook                                                                                                                    | upstream, proxies-at-home (if de-entangled)    | entangled-with-consensus (transitive) | —                                                                                                                                                  |
| Card image loading/error states                   | `frontend/src/features/card/Card.tsx` (`useImageSrc`, `ImageState`, `ErrorPlaceholder`, `SlowLoadHint`)                                                                                     | Multi-source image fallback (bucket → worker CDN → local-file blob) with slow-load hint and styled missing-image placeholder                                                                            | upstream, proxies-at-home (if de-entangled)    | entangled-with-consensus              | —                                                                                                                                                  |
| Image-CDN URL helpers                             | `frontend/src/common/image.ts`                                                                                                                                                              | Resolves a card identifier to its bucket/worker CDN URL                                                                                                                                                 | upstream, proxies-at-home (with their own CDN) | entangled-with-image-cdn-infra        | —                                                                                                                                                  |
| Contextual consent toast                          | `frontend/src/features/consent/consentToast.ts`, `ConsentToast.tsx`, `useConsentToast.tsx`                                                                                                  | General-purpose permission-triggered accept/decline toast (`useConsentToast().requestConsent(key, message)`), per-permission-key session-scoped decision, no consumer feature wired in yet (issue #204) | upstream, proxies-at-home                      | CLEAN                                 | —                                                                                                                                                  |

## Frontend — PDF / export

| Primitive                        | File(s)                                                                                                                                              | Problem solved                                                                                                                                                       | Candidate consumers                            | Entanglement                                                                                                                 | License note                                |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| PDF render core                  | `frontend/src/features/pdf/useRenderPDF.ts`, `pdfRenderService.ts`, `pdf.worker.ts`, `PDF.tsx`                                                       | Off-main-thread PDF generation via a comlink-wrapped Web Worker + `@react-pdf/renderer` document tree                                                                | upstream, proxies-at-home                      | CLEAN                                                                                                                        | —                                           |
| Eager-WASM lazy-mount fix        | `frontend/src/features/pdf/PDFGeneratorModal.tsx`, `frontend/src/features/export/FinishedMyProject.tsx`, `frontend/src/components/ProjectEditor.tsx` | `next/dynamic({ssr:false})` + `mountOnEnter` on the PDF tab so `@react-pdf/renderer`'s WASM doesn't eagerly load (and phantom-download) before the PDF tab is opened | upstream, proxies-at-home                      | CLEAN (pattern-level — the call sites live in larger entangled files, so this is a pattern to replicate, not a file to lift) | —                                           |
| Page-layout math                 | `frontend/src/features/pdf/layout.ts`                                                                                                                | Pure page/card/bleed/margin/spacing geometry, page-absolute slot rects out; zero imports                                                                             | upstream, proxies-at-home                      | CLEAN                                                                                                                        | —                                           |
| PDF canvas preview               | `frontend/src/features/pdf/PDFCanvasPreview.tsx`                                                                                                     | pdf.js canvas-based render preview                                                                                                                                   | upstream, proxies-at-home                      | CLEAN                                                                                                                        | —                                           |
| Generic concurrency helpers      | `frontend/src/common/semaphore.ts`, `frontend/src/common/concurrencyLimit.ts`                                                                        | Bounded-concurrency gate (`Semaphore`) and a `mapWithConcurrencyLimit` helper                                                                                        | upstream, proxies-at-home                      | CLEAN                                                                                                                        | —                                           |
| Paced/retrying image fetch       | `frontend/src/features/pdf/pdfImage.ts`                                                                                                              | Semaphore-gated, exponential-backoff full-resolution image fetch for PDF export                                                                                      | upstream, proxies-at-home (with their own CDN) | entangled-with-image-cdn-infra                                                                                               | —                                           |
| Bleed-prior vote resolution      | `frontend/src/features/pdf/bleedPriorResolution.ts`                                                                                                  | Derives a per-card bleed lean from the weighted-vote consensus system                                                                                                | — (fork-only by design)                        | entangled-with-vote-consensus                                                                                                | —                                           |
| Ordering-service flag icons      | `frontend/src/components/flags.tsx`                                                                                                                  | Small flag-icon wrappers for print-service country badges                                                                                                            | upstream, proxies-at-home                      | CLEAN                                                                                                                        | SVGs vendored from `lipis/flag-icons` (MIT) |
| Ordering-service link components | `frontend/src/components/MakePlayingCardsLink.tsx`, `NotMPCLink.tsx`, `PringlePrintsLink.tsx`                                                        | Thin link-out wrappers around a name+URL constant                                                                                                                    | upstream, proxies-at-home                      | CLEAN (constants are product-specific — expected substitution, not entanglement)                                             | —                                           |
| Sheet pagination helper          | `frontend/src/features/display/displayPagination.ts`                                                                                                 | Chunks project members into per-sheet slot groups for the print-sheet preview                                                                                        | upstream, proxies-at-home                      | CLEAN                                                                                                                        | —                                           |

## Backend

| Primitive                                  | File(s)                                                                                                                                                                        | Problem solved                                                                                                                                                                      | Candidate consumers                                                   | Entanglement                                            | License note |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------- | ------------ |
| Outbound rate limiter ("lh4 rate limiter") | `MPCAutofill/cardpicker/local_phash.py` (`_RateLimiter`, `run_content_phash_backfill`)                                                                                         | Paces a threaded worker pool to a strict `<= N req/sec` ceiling against Google's `lh4.googleusercontent.com` image-resize endpoint                                                  | upstream, proxies-at-home (as a copy-paste, not an import — see note) | entangled-with-CanonicalPrinting (colocation)           | —            |
| Perceptual-hash storage utility            | `MPCAutofill/cardpicker/local_phash.py` (`_hash_to_int`, `_int_to_hash`, `compute_card_art_hash`, `find_best_match`)                                                           | Encodes/decodes an `imagehash.ImageHash` as a signed 64-bit DB int; threshold+margin best-match selection                                                                           | upstream, proxies-at-home                                             | entangled-with-CanonicalPrinting (colocation)           | —            |
| Search-query sanitisation                  | `MPCAutofill/cardpicker/search/sanitisation.py`                                                                                                                                | Normalizes free-text queries/names (lowercase, strip bracketed text/punctuation/digits, collapse whitespace) for consistent matching                                                | upstream, proxies-at-home                                             | CLEAN                                                   | —            |
| OCR crop/preprocessing helpers             | `MPCAutofill/cardpicker/local_ocr.py` (`crop_collector_line`, `preprocess_variants`, `run_tesseract`, `parse_collector_line`, `_normalize_collector_number`)                   | Fractional-bbox crop, grayscale/upscale/threshold-both-polarities preprocessing, and regex parse of an OCR'd collector-number line                                                  | upstream, proxies-at-home                                             | CLEAN                                                   | —            |
| Image color/quality-signal math            | `MPCAutofill/cardpicker/local_image_quality.py` (`is_image_truncated`, `compute_blur_variance`, `compute_entropy`, `compute_color_profile`)                                    | Truncation check, Laplacian-kernel blur variance, grayscale entropy, and per-channel RGB mean/stddev, all pure `PIL.ImageStat`/`ImageFilter` calls against an already-fetched image | upstream, proxies-at-home, federation peers                           | CLEAN (zero `cardpicker.*` imports at all — only `PIL`) | —            |
| Bleed/border geometry helpers              | `MPCAutofill/cardpicker/local_fallback.py` (`normalize_crop_box`, `classify_bleed_edge`)                                                                                       | Pure crop-box remapping (bleed vs. trim) and aspect-ratio-based border classification                                                                                               | upstream, proxies-at-home (as a copy-paste, not an import — see note) | entangled-with-vote-consensus (colocation)              | —            |
| Generic backend utilities                  | `MPCAutofill/cardpicker/utils.py` (`get_json_endpoint_rate_limited`, `twos_complement`, `section_timer`, `time_to_hours_minutes_seconds`, `log_hours_minutes_seconds_elapsed`) | Rate-limited JSON GET wrapper, signed-int bit-twiddling, timing decorator/formatter                                                                                                 | upstream, proxies-at-home                                             | CLEAN                                                   | —            |
| Batch-flush checkpoint pattern             | `MPCAutofill/cardpicker/local_phash.py` (`run_content_phash_backfill`), `deductive_backfill.py` (`run_backfill`), `local_identify_printing_tags.py` (`run_pilot`)              | Sliding-window worker pool + periodic bulk-flush + NULL-filter-as-checkpoint for resumable backfill jobs                                                                            | upstream, proxies-at-home (needs generalizing first — see note)       | entangled — no clean instance exists yet                | —            |
| Elasticsearch connection helpers           | `MPCAutofill/cardpicker/search/search_functions.py` (`get_elasticsearch_connection`, `ping_elasticsearch`, `elastic_connection`, `SearchExceptions`)                           | Thread-local ES client + a decorator translating raw ES connection errors into app exceptions                                                                                       | upstream, proxies-at-home                                             | entangled-with-consensus (colocation)                   | —            |
| Back-face name lookup (issue #199)         | `MPCAutofill/cardpicker/printing_metadata_import.py` (`get_back_face_names`, `is_back_face`, `DOUBLE_FACED_LAYOUTS`)                                                           | Deterministic name → "is this a known DFC back face" lookup from Scryfall's on-disk `card_faces` bulk data, no network fetch                                                        | upstream, proxies-at-home                                             | entangled-with-CanonicalPrinting (colocation)           | —            |

## Docs tooling & federation

| Primitive                      | File(s)                                              | Problem solved                                                                                                                                                                                                                                          | Candidate consumers                                                                                 | Entanglement                                                      | License note                                                                     |
| ------------------------------ | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Docs single-transform pipeline | `.github/scripts/publish_wiki.py`, `publish_site.py` | One shared link-rewrite transform (`transform_links()`) publishing the same `docs/` markdown to both a GitHub wiki and a static site, with a marker-based "only delete pages I generated" safety property                                               | upstream, proxies-at-home, federation peers (any project with `docs/` + wiki + site)                | CLEAN                                                             | —                                                                                |
| Upstream wiki drift tracker    | `.github/scripts/upstream_wiki_drift.py`             | Diffs an external GitHub wiki's git history against a last-seen-SHA table, updates it in place — detection only, never copies wiki prose                                                                                                                | proxies-at-home, any fork tracking an upstream project's wiki                                       | CLEAN                                                             | —                                                                                |
| Federation hash tool           | `federation-hash-tool/hash_my_cards.py`              | Computes a stable perceptual hash of a card image using this fork's crop/classify recipe, so a peer can independently reproduce the same hash and join against a published federation export without transmitting raw images                            | federation peers                                                                                    | CLEAN (narrowly scoped by design — see note)                      | MIT, deliberately distinct from the ODbL-licensed export _data_ it joins against |
| Saved-deck export decrypt tool | `decrypt-saved-deck-export/decrypt.mjs`              | Decrypts a ProxyPrints saved-decks export bundle (PBKDF2-SHA256 + AES-256-GCM, via Node's own `node:crypto` WebCrypto) without this codebase, this site, or any server existing at all — zero imports from anywhere in this repo, zero npm dependencies | upstream, proxies-at-home (any zero-knowledge saved-deck implementation using the same wire format) | CLEAN (zero imports at all, narrowly scoped by design — see note) | MIT, same precedent as the federation hash tool row above                        |

## Detail notes

**Embeddable version-picker (`GridSelectorResults`)** — `GridSelectorResults.tsx`
itself has no fork-only imports, but it composes `GridSelectorFilters.tsx`,
which imports `CanonicalCardFilter` from
`frontend/src/features/filters/CanonicalCardFilter.tsx` — that filter reads
`card.canonicalCard`/`card.canonicalArtist` directly. This is the shallow-lint
blind spot described in "The mechanical tether" above: the tether would not
catch this on its own, which is exactly why it's hand-marked entangled here.

**Card image loading/error states** — the clean parts (`useImageSrc`,
`ImageState`, `ErrorPlaceholder`, `SlowLoadHint`) share a file/component with
`getPrintingMatchLabel`'s community-tag match-label rendering, and the
`CardDocument` type itself (`frontend/src/common/types.ts`) carries
`canonicalCard`/`canonicalArtist`/`printingTagStatus` fields. An extractor
would need to fork `CardImage` into a version without the match-label block
and slim the type down.

**Outbound rate limiter / perceptual-hash storage utility** — both live in
`local_phash.py`, whose own top-level imports include
`from cardpicker.local_fallback import classify_bleed_edge, normalize_crop_box`
and `from cardpicker.models import CanonicalCard, Card`. The logic itself
(`_RateLimiter` is 19 lines, no fork imports at all; the phash int-encoding
functions only touch `imagehash`/arithmetic) is genuinely clean — the
entanglement is the file's other imports, not these functions' own bodies.
Lifting either means copying the relevant lines out, not importing the file.

**Bleed/border geometry helpers** — same shape: `local_fallback.py`'s module
header imports `CanonicalCard`, `CardTagVote`, `Tag`, `VotePolarity`,
`VoteSource` at the top of the file (they're used by other functions in the
same module, e.g. `cast_border_attribute_vote`), so importing the module at
all pulls in the vote-system Django app even though `normalize_crop_box`/
`classify_bleed_edge` never touch any of those symbols.

**Batch-flush checkpoint pattern** — `local_phash.py`'s instance is the
least entangled of the three (only touches `Card.content_phash`, a plain
field — but still inherits the file's own `CanonicalCard`/`local_fallback`
imports per the note above); `deductive_backfill.py` and
`local_identify_printing_tags.py`'s instances flush `CardPrintingTag`/
`CardTagVote` directly. In all three cases the batch-size param + local
`flush()` closure + `bulk_create`/`bulk_update` + NULL-filter-as-checkpoint
idiom is hand-duplicated per caller rather than factored into a shared
utility — extracting it means generalizing the fetch/compute/persist steps
into parameters, not lifting a file.

**Search-query sanitisation** — the real risk here isn't entanglement, it's
architectural duplication: the frontend hand-maintains its own mirror in
`frontend/src/common/processing.ts`, and the two have drifted before
(upstream PR #460 fixed `to_searchable()`'s "the"-stripping bug; the
frontend mirror wasn't updated until a later fork commit caught it). Worth
its own follow-up (single source of truth, or a generated/tested parity
fixture like the docs link-rewrite one) — out of scope for this ledger.

**OCR crop/preprocessing helpers** — `local_ocr.py` has one
`TYPE_CHECKING`-only reference to `cardpicker.local_identify_printing_tags`
(a type hint for `CandidatePrinting`, never evaluated at runtime); the
tether excludes `TYPE_CHECKING` blocks from its import scan for exactly this
reason. `validate_against_candidates`, the one function in this file that's
_semantically_ tied to printing identification (even though it has no
fork-only import), is not included in this row's primitive — an extractor
drops that one function and keeps the rest. `find_matching_candidates`
(added 2026-07-20, Stage D's join-key calculator — the candidate-narrowing
filter `validate_against_candidates` already computed internally, extracted
so a caller with independent tie-break evidence can inspect the ambiguous
match set directly) is excluded for the identical reason — it's the same
printing-identification matching logic, just under a new name, not a
separate primitive.

**Federation hash tool** — the _code artifact_ has zero fork dependencies
(confirmed: its only two mentions of `cardpicker` are provenance comments,
not imports; dependencies are `Pillow` + `imagehash` only). What's narrow by
design is the _hashing recipe_ itself (crop box, bleed/trim classification,
phash parameters) — an arbitrary-but-fixed convention this fork chose, not
a universal algorithm every consumer would want verbatim. Contrast with the
federation _protocol_ (signing scheme, `VoteSource.FEDERATED` gate,
publisher-only posture) in `docs/federation-v1.md`, which genuinely is
fork-only by definition — the hash tool is the one piece of the federation
program that cleanly separates from that layer.

**Saved-deck export decrypt tool** — zero imports of any kind, not just zero
fork-specific ones: `decrypt.mjs` re-implements the (tiny) AES-256-GCM/
PBKDF2-SHA256 wrap/unwrap logic itself using only Node's built-in
`node:crypto`, rather than importing `frontend/src/common/savedDeckCrypto.ts`

- deliberately, since the whole point is running with none of this
  repository's own code present. What's narrow by design is the wire format
  (docs/proposals/proposal-g-user-accounts-saved-decks.md's "PR-6, post-v1:
  deck portability" section, also reproduced in the tool's own readme.md) -
  an arbitrary-but-fixed convention this fork chose for its saved-decks
  export, not a universal format. `frontend/src/common/savedDeckCrypto.ts`
  and `frontend/src/features/savedDecks/deckPayload.ts` (the in-app
  counterparts this tool's logic mirrors) are themselves NOT rowed here -
  they predate this ledger's 2026-07-19 sweep and haven't been audited for
  it yet; not rowing this tool's own dependencies-that-aren't-actually-
  dependencies (see above) doesn't change that gap.

**Back-face name lookup** — `get_back_face_names`/`is_back_face`/
`DOUBLE_FACED_LAYOUTS` touch only `Path`/pydantic parsing of the raw bulk
JSON, no fork-only symbol at all in their own bodies — but they live in
`printing_metadata_import.py`, already listed in `docs_lint.py`'s
`FORK_ONLY_PY_MODULES` (the file's other top-level code imports
`CanonicalCard`/`CanonicalPrintingMetadata`), same "clean logic,
colocation-entangled file" shape as the bleed/border and rate-limiter rows
above. Lifting means copying the three names out, not importing the
module.

## Not audited this pass

`frontend/src/features/clientSearch/` (the Orama-based client-side local/
Google-Drive search indexer) is a substantial standalone subsystem that
this pass's frontend agent flagged as worth its own dedicated audit rather
than a single table row — deferred, not forgotten.

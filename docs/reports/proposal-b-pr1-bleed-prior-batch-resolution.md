As of: 2026-07-18
Task: Proposal B deferred PR-1 — batch prior-resolution
Branch: `claude/e2-bleed-prior-batch-resolution` (stacked on `claude/proposal-b-bleed-normalization`, PR #66)

## What shipped

The main-thread, concurrency-bounded batch fetch of each export card's `appropriate-bleed`
machine-vote lean, via the existing `APIGetTagConsensus` endpoint (`store/api.ts` — no new
endpoint, per the approved spec). This populates `PDFProps.bleedPriors`, which `PDF.tsx`'s
`PDFCardImage` (built in PR #66) already reads and defaults safely to `"unresolved"` when
absent — this PR is what actually populates it with real data instead of that default.

**Why main thread, not the render worker**: `APIGetTagConsensus`'s CSRF header needs
`document.cookie` (`getCSRFHeader()`, `common/cookies.ts`), and `document` doesn't exist inside
`pdf.worker.ts`'s Web Worker context. The resolved `{[identifier]: BleedPrior}` map is plain,
structured-clone-safe data — it crosses the main-thread → worker boundary the same way every
other `PDFProps` field already does, no new plumbing needed there.

### New files

- `frontend/src/common/concurrencyLimit.ts` — `mapWithConcurrencyLimit<T, R>(items, concurrency,
  fn)`, a general-purpose bounded-concurrency map (worker-pool-over-an-index-cursor, not
  fixed-size batching — a worker claims the next unclaimed index the instant it's free, rather
  than waiting for a whole batch to finish). Deliberately a new, separate utility rather than
  reusing `GoogleDriveService.ts`'s own private `Semaphore` class — that class isn't exported,
  and extracting/refactoring it would have expanded this PR's review surface into an unrelated
  file for a small win. 6 tests: order preservation, concurrency actually bounded (not
  serialized), every item processed exactly once, empty input, concurrency > item count,
  rejection propagation (no built-in per-item error tolerance — that's the caller's job).
- `frontend/src/features/pdf/bleedPriorResolution.ts` — `resolveBleedPriors(backendURL,
  identifiers, concurrency?)`. Deduplicates identifiers, fetches each unique card's
  `TagConsensusResponse` via `APIGetTagConsensus`, maps the `appropriate-bleed` entry's
  `netPolarity` to a `BleedPrior`: clearly positive → `"bleed"`, clearly negative → `"trimmed"`,
  missing entry or zero/near-zero → `"unresolved"` (this 3-way split is for code
  clarity/debugging — `resolveBleedPlan`'s own fallback already treats `"trimmed"` and
  `"unresolved"` identically, extending the full target). A single card's lookup failure (network
  blip, rate limit, an identifier the backend doesn't recognize) is caught internally and degrades
  that one card to `"unresolved"` — never fails the whole batch. Concurrency defaults to 6,
  matching `GoogleDriveService`'s own existing default (`BLEED_PRIOR_RESOLUTION_CONCURRENCY`, a
  named constant, not empirically tuned for this specific endpoint but a reasonable,
  already-precedented starting point). 7 tests covering every branch of the netPolarity mapping,
  the failure-tolerance behavior, deduplication, and the empty-input case.

### Changed files

- `frontend/src/features/pdf/PDFGenerator.tsx` — `downloadPDF`/`saveToDrivePDF` both gained a
  `backendURL: string | null` parameter; each now calls `resolveBleedPriors` once, right before
  `pdfRenderService.renderPDF(...)`, using `Object.keys(props.cardDocumentsByIdentifier)` as the
  export's own card set (already deduplicated by that map's construction). Skipped entirely
  (`bleedPriors` stays `undefined`) when no remote backend is configured — matches
  `PDFCardImage`'s existing safe default, no special-casing needed downstream. `useDownloadPDF`/
  `useSaveToDrivePDF` thread the new parameter through; the main component now selects
  `backendURL` via `selectRemoteBackendURL` (`store/slices/backendSlice.ts`) and passes it to
  both hooks.

## Verification

- `npx tsc --noEmit`: clean.
- `npx eslint` on all new/changed files: 0 errors/warnings.
- `npx prettier@2.7.1 --write`: applied.
- Full `npx jest --runInBand`: **282/282 passing** (269 from PR #66's own build + 13 new this
  pass), zero regressions.
- Full `npx playwright test tests/PDFGenerator.spec.ts`: **4/4 passing**, same timing as before
  this PR (17–27s per test, no hang, no new failure). This suite has **no `tagConsensus` mock at
  all** — every card's lookup genuinely fails (unmocked request) during this run, which is
  exactly the failure-tolerance path `resolveSingleBleedPrior`'s try/catch exists for. Passing
  cleanly here is real, end-to-end confirmation that an unmocked/failing batch degrades to
  `"unresolved"` per card rather than hanging or failing the export — not just an assertion in a
  unit test.

## Deviations

None from the authorized scope. One implementation detail worth flagging: `mapWithConcurrencyLimit`
was built as a new, separate utility rather than extracting `GoogleDriveService`'s existing
`Semaphore` — a deliberate choice to keep this PR's diff to new files plus `PDFGenerator.tsx`'s
own wiring, not a refactor of an unrelated, already-working module. If a shared concurrency
primitive across both features is wanted later, that's a clean, separate follow-up.

## Open items

None blocking. PR-2 (manual-override UI + persistence) and PR-3 (preview badge) remain queued
behind this, per the standing order (B PR-2 → PR-3 → C part (b) → E-3 → F).

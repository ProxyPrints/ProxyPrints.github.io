As of: 2026-07-18
Task: Proposal B deferred PR-3 — WYSIWYG preview badge ("bleed will be generated")
Branch: `claude/e4-bleed-preview-badge` (stacked on `claude/e3-bleed-override-ui`, PR #71)

## What shipped

A hedged badge on `PagePreview.tsx`'s fast/CSS WYSIWYG preview (Proposal A), reading
"Bleed will be generated" on any card export is expected to synthesize bleed for. Per the audit's
suggestion-vs-confirmed vocabulary, explicitly never framed as a confirmed fact — it's a hedge
based on the same signals PR-1/PR-2 already resolve, not the real per-side measurement (which only
runs at actual export, on the full-resolution decode — see the approved spec's own "PREVIEW
INTERACTION" line).

**With this, Proposal B is complete end to end** per the originally approved spec: measurement,
extension, priors (PR-1), manual override + persistence (PR-2), and now the preview badge (PR-3).
Only the merge-time server-side calibration pass and the flagged-not-built XML field remain, both
intentionally out of scope for any of these three PRs.

### The hedge logic

New pure function `willLikelyGenerateBleed(prior, manualOverride)` in `bleedNormalize.ts`, next to
`resolveBleedPlan`:

```
force-bleed    -> false (no synthetic bleed expected)
force-trimmed  -> true  (synthetic bleed expected)
auto + "bleed" -> false
auto + "trimmed" | "unresolved" -> true
```

This mirrors `resolveBleedPlan`'s own manualOverride/prior precedence exactly, minus the per-side
measurement branch — the WYSIWYG preview only has small thumbnails in memory, not a decoded
full-resolution bitmap, so no real `CardMeasurement` is available to it. The interpretation of "the
measurement where available" (from the authorization message) worth flagging explicitly: the one
already-resolved, synchronous signal available outside the async canvas pipeline is PR-2's manual
override, which fully determines the real outcome the same way a measurement would (see
`resolveBleedPlan`'s own `if (manualOverride === "force-bleed") return ...` short-circuit, which
skips the measurement entirely) — so it's used here as the closest available stand-in. 6 new tests
covering every branch.

### Wiring (`PDFGenerator.tsx`, `PagePreview.tsx`)

- `PagePreviewSlotContent` gained an optional `willGenerateBleed?: boolean` field. `undefined`
  renders no badge (bleed normalization doesn't apply to this card's source, or no signal has
  resolved yet); `true` renders it; `false` explicitly renders nothing (not the same as
  `undefined` internally, but the same visible result — kept as two states for clarity when
  reading `PDFGenerator.tsx`'s derivation logic, not because the UI distinguishes them).
- `PDFGenerator.tsx` resolves `bleedPriors` for just the **currently-visible preview page's**
  eligible cards (same Google Drive/local-file filter as PR-2's override list), debounced 500ms
  (matching this component's own existing debounce pattern via `useDebounce`+`equalityFn`) so
  retyping a search query doesn't fire a fresh batch of `tagConsensus` requests on every keystroke.
  Reuses PR-1's `resolveBleedPriors` — no new fetch logic.
  Bounded to the visible page only (not the whole project), keeping this in the same spirit as the
  existing "fast preview only shows page 1" scoping and the spec's memory-discipline concerns.
- Per card, the badge only renders once there's a real signal to hedge on — an explicit override,
  or a resolved prior. Before either is available, no badge shows at all, rather than showing a
  provisional guess that would flicker wrong-then-right as the prior fetch resolves.

## Verification

- `npx tsc --noEmit`: clean.
- `npx eslint` on all new/changed files: 0 errors, 0 new warnings (one pre-existing `<img>`
  `no-img-element` warning on `PagePreview.tsx`, present before this PR too).
- Full `npx jest --runInBand`: **301/301 passing** (295 from PR #66/PR-1/PR-2's build + 6 new
  `willLikelyGenerateBleed` tests), zero regressions.
- Full `npx playwright test tests/PDFGenerator.spec.ts`: **7/7 passing** at `--workers=1`
  (real browser, real network mocking via MSW). Two new tests: one that mocks a clearly-negative
  `appropriate-bleed` `tagConsensus` response (prior "trimmed") and confirms the badge appears with
  the exact hedged text, and one that confirms setting "Force bleed" via PR-2's override control
  makes the badge disappear even though the underlying prior is still "trimmed" — real end-to-end
  confirmation of the override-wins-outright precedence, not just a unit-test assertion of the
  pure function. New MSW handler `tagConsensusAppropriateBleedTrimmed` added to
  `src/mocks/handlers.ts` for this. One transient failure seen only under `--workers=2` (default),
  reproduced as a flake by re-running the single failing test in isolation (passed) and the full
  suite at `--workers=1` (7/7 passed) — resource contention between two concurrent dev-server-backed
  browser contexts, not a real regression from this PR's changes.

## Deviations

None from the authorized scope. One interpretation call worth flagging (documented above and in
the proposal doc): "the measurement where available" was read as "PR-2's manual override," since
no real per-side measurement is available to the cheap CSS preview at all — flagging this
explicitly in case a different reading was intended.

## Open items

None blocking. Proposal C part (b) is next per the standing order — not started this pass, per the
standing pacing rule (new proposal, not a follow-up to B).

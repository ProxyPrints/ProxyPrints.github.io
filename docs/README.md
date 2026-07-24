# docs/ — map of this directory

An honest index, grouped by why you'd be reading rather than by folder.
New here? Start with [`overview.md`](overview.md) — it's written for a
reader with zero prior context on this fork. `CLAUDE.md` (repo root) has
its own flat docs index too, but that one's a working index for Claude
Code sessions specifically; this one's for everybody else.

## Understanding the system

The methodology and the systems it governs.

- [`overview.md`](overview.md) — what this fork is, how it relates to
  upstream, and where everything else in this list fits.
- [`documentation-process.md`](documentation-process.md) — the standing
  system this very directory runs on: docs/ as source of truth, the wiki
  as a generated view of it, mechanical lint vs. the quarterly judgment
  pass, and how upstream's own wiki is tracked (linked + attributed,
  never mirrored).
- [`theory.md`](theory.md) — the printing-identification pipeline as
  candidate-constrained decoding: false-accept bound, prior-art comparison,
  soundness mechanisms. Written for an external reader; doubles as the
  federation pitch's technical annex. **Reviewed and approved by the owner,
  2026-07-17.**
- [`identification-pipeline.md`](identification-pipeline.md) — the same
  pipeline, as a plain-language stage-by-stage walkthrough (Stage C
  evidence extraction, Stage D join-key calculator, the human-backed vote
  gate) rather than `theory.md`'s formal decoding model. **Reviewed and
  approved by the owner, 2026-07-21.**
- [`reference/vote-weight-matrix.md`](reference/vote-weight-matrix.md) —
  the owner-ratified 2026-07-22 vote-weight scenario matrix (raw decision
  record, implemented in PR #325) that `theory.md`'s §4/§7a and
  `identification-pipeline.md`'s g5 paragraph narrate; reference only, not
  re-derived after ratification.
- [`reference/funnel-spec.md`](reference/funnel-spec.md) — the
  owner-ratified 2026-07-22 `/display` art-picker funnel spec (raw design
  record, implemented in PR #329) that `features/grid-selector.md`'s "The
  art-picker FUNNEL" section narrates; reference only, recovered during
  the 2026-07-23 D-lettering sweep from a local, never-committed artifact.
- [`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) — canonical
  status page for the pipeline-fidelity gate (GitHub issue #154): gate
  definition, artifact 1 (parity replay — DONE, owner-accepted
  2026-07-22, now closed history per the 2026-07-23 new-data basis
  ruling) and artifact 2 status (all 3 MISSING constants decided, fix
  for 2 merged AND deployed 2026-07-23T01:33Z), the #347-amended fire
  sequence — now **COMPLETE end to end, gate FIRED, true completion
  2026-07-24**: Bug-B whole-DB reparse dry-run, the pilot dry-run and
  `--write` (130,210 votes), `consensus_recompute --apply`, plus five
  further 2026-07-24 corrective/completion passes (lexicon-gate
  retraction, marker reparse, artist-credit fill, calculator re-pass, a
  second `consensus_recompute` closer) all DONE — live resolved-printing
  count is **3** (corrected from a provisional 4), all 218,345 cards
  remain `artist_vote_status=unresolved` (single-machine-vote-below-
  threshold finding), review queue is **134,370** cards (Bug-A's full
  re-scan deferred post-pilot is the one tracked open item) — and the
  #340 root-cause footprint sizing. Single source of
  truth for this gate's status — `theory.md`, `identification-pipeline.md`,
  `features/catalog-completion-plan.md`, and the knowledge-inventory
  report link here rather than restating it.
- [`federation-v1.md`](federation-v1.md) — federation verdict exchange
  format v1 (spec; no implementation yet — instances would share resolved
  consensus verdicts as signed JSON, never raw votes). Companion HOLD
  spec for the concrete publish-first artifact: see "Plans & proposals"
  below.
- [`upstreaming/vote-system.md`](upstreaming/vote-system.md) — the vote
  system (printing/artist/tag weighted consensus) as a cherry-pick
  extraction manifest for upstreaming to `chilli-axe/mpc-autofill`; also
  the clearest single write-up of how that system is built, commit by
  commit. Accurate through 2026-07-13 only — see
  `upstreaming/readiness-audit.md` §5 for what's changed since.
- [`upstreaming/readiness-audit.md`](upstreaming/readiness-audit.md) —
  full fork-vs-upstream diff decomposed into feature chunks (with a
  license-provenance column), dependency graph, the upstream-value/
  extraction-ease ladder, and the branch architecture proposal.
- [`upstreaming/license-provenance.md`](upstreaming/license-provenance.md)
  — the one-time external-code provenance sweep, the PROTECTED CORE
  module list + its CI license lint, and the absorption protocol for any
  future external-code intake.
- [`upstreaming/conventions.md`](upstreaming/conventions.md) — one-page
  checklist any `upstream-fix-*`/`upstream-feat-*` branch must satisfy
  before it's PR-ready.
- [`upstreaming/drift-log.md`](upstreaming/drift-log.md) — auto-generated,
  edited in place weekly: does each `upstream-*` branch still apply
  cleanly onto current `upstream/master`. Detection only.
- [`upstreaming/upstream-wiki-drift.md`](upstreaming/upstream-wiki-drift.md)
  — weekly, automated, detection-only tracking of what's changed on
  chilli-axe/mpc-autofill's own wiki since we last looked.
- [`upstreaming/extractable-primitives.md`](upstreaming/extractable-primitives.md)
  — repo-wide ledger of generic, no-fork-dependency code an outside
  consumer (upstream, the proxies-at-home lineage, federation peers) could
  lift wholesale, versus what's honestly entangled. HOLD: seeded audit
  awaiting owner review, not yet a to-do list. `CLEAN` claims are checked
  by a mechanical tether riding `docs-lint`. Deliberately left out of
  `wiki-publish-map.json` while HOLD, same reasoning
  `documentation-process.md` gives for excluding `docs/proposals/` — add
  it once the owner review clears.
- [`features/printing-tags.md`](features/printing-tags.md) — the "What's
  That Card?" printing-consensus tagging system and vote-queue funnel,
  backend + frontend. Stages 1–7 are the current-state reference; Stage 8
  onward (local/zero-API-cost backfill) is documented live in the next
  entry instead.
- [`features/catalog-completion-plan.md`](features/catalog-completion-plan.md)
  — the six-part catalog-completion package (Stage 8+): run-cohort safety,
  `content_phash` backfill, evidence recovery, LANDS, residual
  classification, and the formal note that became `theory.md`. The live
  source of truth for anything past Stage 7 — its "Harvest-calculate
  pipeline" section (Stages A-F) is now ~65% of the file and where
  current work lives.
- [`features/moderation.md`](features/moderation.md) — Discord OAuth login,
  the `Moderators` group gate, the sensitive-tag approval queue, card
  reports.
- [`features/card-dom-api.md`](features/card-dom-api.md) — generic
  `data-card-*` attributes + `mpc:card-selected` event for external
  tooling/testing/accessibility.
- [`features/pdf-generator.md`](features/pdf-generator.md) — PDF export
  tab: eager-WASM/preview/image-rendering bug fixes.
- [`features/print-export-page.md`](features/print-export-page.md) — the
  "Print!" export page's ordering tabs and flag icons.
- [`features/google-drive-connect.md`](features/google-drive-connect.md) —
  Google Drive picker, Local Folder, and Save-PDF-to-Drive.
- [`features/grid-selector.md`](features/grid-selector.md) — the
  card-version-picker modal + `Card.tsx`'s image loading/error states.
- [`features/display-left-rail.md`](features/display-left-rail.md) — the
  `/display` left rail (card surface): the confidence element, the
  Sources accordion + pinned-favourite sources, the Select Version
  continuous grid, the artist support button, and the buttons-look-like-
  buttons audit.
- [`features/theming.md`](features/theming.md) — the 2026-07-24
  theme-defaults pass: `_theme-tokens.scss` (the one canonical palette +
  corner-radius token file), the derivation layering that keeps every
  Bootstrap variable override pointed at a token instead of a scattered
  literal, the "born grey" Bootstrap-default inventory it fixed (Modal/
  Dropdown/Popover/Toast/`Card.Header`/`Offcanvas`/table-head/the
  form-select chevron), and its relationship to the fidelity specs
  (`DisplayLeftRailFidelity.spec.ts` et al. assert some of these same
  token values — retheming means updating both together).
- [`features/search-operator-syntax.md`](features/search-operator-syntax.md)
  — Scryfall-style `artist:`/`border:`/`frame:`/`tag:`/`set:`/`lang:`
  search-operator syntax: the pure parser and the fork-coupled wiring seam.
- [`features/image-cdn.md`](features/image-cdn.md) — the Worker + R2
  bucket image CDN.
- [`features/local-file-source.md`](features/local-file-source.md) —
  backend `LOCAL_FILE` catalog source type.
- [`features/saved-decks.md`](features/saved-decks.md) — zero-knowledge
  user accounts + server-side saved decks: the crypto design, backend
  endpoints, frontend wiring, the shipped PR-5 per-deck share links and
  PR-6 deck-portability addendum (export/import + standalone decrypt
  tool), and the still-design-only PR-7 addendum.
- [`features/consent-toast.md`](features/consent-toast.md) — the reusable,
  permission-triggered contextual consent toast (issue #204): a
  bottom-corner accept/decline prompt shown only right before an action
  that needs it, per-permission-key session scoping, no dependency on any
  consumer feature yet.
- [`features/foreign-order-resilience.md`](features/foreign-order-resilience.md)
  — issue #324 Phase 1: rendering "orphan" cards (Drive file IDs the
  catalog has never indexed) from text/XML import, direct-from-Google
  fetch with tiered sizing, the invalidation-listener root-cause fix,
  round-trip export, and what's deferred to Phase 2.

## Using it

For an end user or a third party running their own instance — distinct
from both the architecture docs above and this fork's own operations
below.

- [`user-guide.md`](user-guide.md) — searching, the "What's That Card?"
  vote queue, exporting a print-ready PDF, saving a project. Migrated
  from the wiki's own `User-Guide` page; still a skeleton (not all
  sections written).
- [`self-hosting.md`](self-hosting.md) — standing up and operating your
  _own_ instance of this project (not specific to how ProxyPrints.ca
  itself is hosted — see "Operating it" below for that). Migrated from
  the wiki's own `Instance-Admin-Guide` page.

## Operating it

Deployment, incidents, and cross-session lessons.

- [`infrastructure.md`](infrastructure.md) — Docker build/deploy, secrets &
  credentials, telemetry removal, CI/CD state, push policy, the
  upstreaming workflow, the drives.csv history-rewrite incident.
- [`troubleshooting.md`](troubleshooting.md) — symptom-first index of
  recurring blockers. Grep your error text here before re-deriving a fix.
- [`lessons.md`](lessons.md) — terse, reusable cross-session lessons (CI
  vs. local venv trust, worktree port collisions, ES mapping drift, and
  more).
- [`features/stage-e-operations.md`](features/stage-e-operations.md) — the
  Stage E Phase 1 envelope enforcement primitive: PASSIVE vs. BULK mode,
  the four ratified pause bars, and the trip/resume runbook
  (`resolve_envelope_trip --acknowledge-trip`). Companion to
  [`proposals/stage-e-streaming.md`](proposals/stage-e-streaming.md), which
  remains the design authority.

## Plans & proposals

One-word status per doc; see each file for the full survey/spec.

| Doc                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Status   |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| [`proposals/proposal-b-bleed-normalization.md`](proposals/proposal-b-bleed-normalization.md) — export-time per-side bleed normalization                                                                                                                                                                                                                                                                                                                                                   | PARTIAL  |
| [`proposals/proposal-c-context-menu-restyle.md`](proposals/proposal-c-context-menu-restyle.md) — right-click/long-press context menu (shipped); restyle direction (HOLD)                                                                                                                                                                                                                                                                                                                  | PARTIAL  |
| [`proposals/proposal-f-public-stats-page.md`](proposals/proposal-f-public-stats-page.md) — public `/stats` transparency page                                                                                                                                                                                                                                                                                                                                                              | HOLD     |
| [`proposals/proposal-g-user-accounts-saved-decks.md`](proposals/proposal-g-user-accounts-saved-decks.md) — user accounts + saved decks via Discord OAuth (core build + PR-5 share links + PR-6 deck portability shipped; see [`features/saved-decks.md`](features/saved-decks.md) — PR-7 addendum still HOLD)                                                                                                                                                                             | PARTIAL  |
| [`proposals/proposal-h-display-layout-spec.md`](proposals/proposal-h-display-layout-spec.md) — the living `/display` spec: one page merging the "Choose Art" editor and PDF export into a live print-sheet preview + card-details rail (three-region layout and every owner-ratified layout decision since); [`proposals/proposal-h-unified-display-page.md`](proposals/proposal-h-unified-display-page.md) is the original draft, now HISTORICAL/superseded — see that file's own banner | PARTIAL  |
| [`proposals/proposal-i-docs-as-site-source.md`](proposals/proposal-i-docs-as-site-source.md) — extends the docs/-to-wiki publish pipeline with a second target: rendered site pages + build-time JSON data extracts                                                                                                                                                                                                                                                                       | BUILDING |
| [`proposals/proposal-i-readme-pipeline.md`](proposals/proposal-i-readme-pipeline.md) — folds `readme.md` into the same pipeline as a third (`readme`) emit mode: content merge map, owner GO decision, and what shipped                                                                                                                                                                                                                                                                   | SHIPPED  |
| [`federation/public-export-v1.md`](federation/public-export-v1.md) — publish-first federation: signed verdict export consumable by mpc-autofill forks and the MIT-lineage proxy tools, no peer required                                                                                                                                                                                                                                                                                   | HOLD     |
| [`proposals/stage-e-streaming.md`](proposals/stage-e-streaming.md) — Stage E streaming assembly design brief (issue #153): trigger/granularity/backpressure/consensus-recompute/gate/observability decisions, efficiency candidates checked against `theory.md`'s soundness bound, and the hardware envelope/federated-scalability analysis                                                                                                                                               | HOLD     |

Not every shipped proposal-lettered feature has a survey doc here — some
(e.g. Proposal A, Proposal D) went straight from idea to shipped PR without
a separate written spec. This list is only the ones that got a dedicated
doc. Like Records, this bucket is never published to the wiki — a HOLD
spec isn't real yet and shouldn't read as if it is.

## Records

Point-in-time findings and relayed work products, not living reference —
and, per [`documentation-process.md`](documentation-process.md), never
published to the wiki (the wiki is a generated view of "Understanding the
system" + "Using it" + "Operating it" only).

- **`audits/`** — [`ui-content-audit.md`](audits/ui-content-audit.md) (12
  UI content-accuracy findings) landed via #56 and its Disposition column
  was filled in after the build pass (#64) shipped 11 of 12 findings (#11
  got a process fix instead — see `CLAUDE.md`'s policy-text-dates rule).
- **`data/`** — dated data records, two conventions so far: (1) JSON
  pipeline snapshots (one file per date, plus a sibling `.md` with
  per-field query provenance), for chart/infographic generation — the
  homepage panel's reserved-not-built catalog-stats chart slot
  ([`features/homepage-panel.md`](features/homepage-panel.md)) is the
  intended eventual consumer. See
  [`data/2026-07-22-pipeline-snapshot.md`](data/2026-07-22-pipeline-snapshot.md)
  for the first one. (2) per-run reports + resource metrics (RSS/IO/CPU,
  per-card cost) keyed by `run_id`, for
  [`pipeline-fidelity-gate.md`](pipeline-fidelity-gate.md) §9's fire
  sequence specifically — no JSON sibling, `.md` only. See
  [`data/2026-07-23-bugb-reparse-dryruns.md`](data/2026-07-23-bugb-reparse-dryruns.md)
  for the first one.
- [`reports/`](reports/README.md) — the report-relay convention (see that
  directory's own README, which indexes every report currently merged).

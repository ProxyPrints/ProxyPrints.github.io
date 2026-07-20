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
  source of truth for anything past Stage 7.
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
- [`features/image-cdn.md`](features/image-cdn.md) — the Worker + R2
  bucket image CDN.
- [`features/local-file-source.md`](features/local-file-source.md) —
  backend `LOCAL_FILE` catalog source type.
- [`features/saved-decks.md`](features/saved-decks.md) — zero-knowledge
  user accounts + server-side saved decks: the crypto design, backend
  endpoints, frontend wiring, the shipped PR-6 deck-portability addendum
  (export/import + standalone decrypt tool), and the still-design-only
  PR-5/7 addenda.
- [`features/consent-toast.md`](features/consent-toast.md) — the reusable,
  permission-triggered contextual consent toast (issue #204): a
  bottom-corner accept/decline prompt shown only right before an action
  that needs it, per-permission-key session scoping, no dependency on any
  consumer feature yet.

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

## Plans & proposals

One-word status per doc; see each file for the full survey/spec.

| Doc                                                                                                                                                                                                                                                                                         | Status   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| [`proposals/proposal-b-bleed-normalization.md`](proposals/proposal-b-bleed-normalization.md) — export-time per-side bleed normalization                                                                                                                                                     | PARTIAL  |
| [`proposals/proposal-c-context-menu-restyle.md`](proposals/proposal-c-context-menu-restyle.md) — right-click/long-press context menu (shipped); restyle direction (HOLD)                                                                                                                    | PARTIAL  |
| [`proposals/proposal-f-public-stats-page.md`](proposals/proposal-f-public-stats-page.md) — public `/stats` transparency page                                                                                                                                                                | HOLD     |
| [`proposals/proposal-g-user-accounts-saved-decks.md`](proposals/proposal-g-user-accounts-saved-decks.md) — user accounts + saved decks via Discord OAuth (core build + PR-6 deck portability shipped; see [`features/saved-decks.md`](features/saved-decks.md) — PR-5/7 addenda still HOLD) | PARTIAL  |
| [`proposals/proposal-h-unified-display-page.md`](proposals/proposal-h-unified-display-page.md) — one page merging the "Choose Art" editor and PDF export into a live print-sheet preview + card-details rail                                                                                | PARTIAL  |
| [`proposals/proposal-i-docs-as-site-source.md`](proposals/proposal-i-docs-as-site-source.md) — extends the docs/-to-wiki publish pipeline with a second target: rendered site pages + build-time JSON data extracts                                                                         | BUILDING |
| [`proposals/proposal-i-readme-pipeline.md`](proposals/proposal-i-readme-pipeline.md) — folds `readme.md` into the same pipeline as a third (`readme`) emit mode: content merge map, owner GO decision, and what shipped                                                                     | SHIPPED  |
| [`federation/public-export-v1.md`](federation/public-export-v1.md) — publish-first federation: signed verdict export consumable by mpc-autofill forks and the MIT-lineage proxy tools, no peer required                                                                                     | HOLD     |

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
- [`reports/`](reports/README.md) — the report-relay convention (see that
  directory's own README, which indexes every report currently merged).

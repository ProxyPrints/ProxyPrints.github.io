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
  consensus verdicts as signed JSON, never raw votes).
- [`upstreaming/vote-system.md`](upstreaming/vote-system.md) — the vote
  system (printing/artist/tag weighted consensus) as a cherry-pick
  extraction manifest for upstreaming to `chilli-axe/mpc-autofill`; also
  the clearest single write-up of how that system is built, commit by
  commit.
- [`upstreaming/upstream-wiki-drift.md`](upstreaming/upstream-wiki-drift.md)
  — weekly, automated, detection-only tracking of what's changed on
  chilli-axe/mpc-autofill's own wiki since we last looked.
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

| Doc                                                                                                                                                      | Status |
| -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| [`proposals/proposal-f-public-stats-page.md`](proposals/proposal-f-public-stats-page.md) — public `/stats` transparency page                             | HOLD   |
| [`proposals/proposal-g-user-accounts-saved-decks.md`](proposals/proposal-g-user-accounts-saved-decks.md) — user accounts + saved decks via Discord OAuth | HOLD   |

Not every shipped proposal-lettered feature has a survey doc here — some
(e.g. Proposal A, Proposal D) went straight from idea to shipped PR without
a separate written spec. This list is only the ones that got a dedicated
doc. Like Records, this bucket is never published to the wiki — a HOLD
spec isn't real yet and shouldn't read as if it is.

## Records

Point-in-time findings and relayed work products, not living reference —
and, per [`documentation-process.md`](documentation-process.md), never
published to the wiki (the wiki is a generated view of "Understanding the
system" + "Operating it" only).

- **`audits/`** — not yet on this branch. `docs/audits/ui-content-audit.md`
  (12 UI content-accuracy findings, HOLD) exists on the unmerged
  `claude/ui-content-audit` branch; that PR (#56) is deliberately held open
  until the audit worker adds a per-row disposition column reflecting the
  build pass (PRs #64/#65). Not this pass's to merge — will appear here
  once #56 lands.
- [`reports/`](reports/README.md) — the report-relay convention (see that
  directory's own README). No reports have merged to this branch yet: the
  convention and its first files live on the `report-relay`/`report-relay-2`
  branches and are expected to land in a docs batch soon. The README is
  written now so the directory has its orientation in place before that
  merge.

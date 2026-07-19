# docs/MANIFEST.md — routing map

Not another index (see [`README.md`](README.md) for the audience-grouped
map, [`../CLAUDE.md`](../CLAUDE.md) for the flat session index) — this one
exists to be **queried by topic/surface**, so a task can be routed to its
governing docs without anyone having to remember which file covers what.

**Authority** column:

- `BINDING` — governs current behavior; a task touching its surface should
  read it first and a conflict with it should halt work, not get silently
  overridden.
- `reference` — background, methodology, or a lookup index; useful, not a
  constraint on how to act.
- `historical` — point-in-time record (a report, a resolved proposal, a
  HOLD spec not yet real). Useful for context, never for "what's true now."

| path                                  | purpose                                                                                                                                                                              | governs-what-surface                                          | authority  |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------- | ---------- |
| `documentation-process.md`            | docs/ as source of truth; wiki as a generated view; lint vs. quarterly judgment pass                                                                                                 | any docs/ or wiki-publish-pipeline edit                       | BINDING    |
| `overview.md`                         | what this fork is, how it relates to upstream, orientation for a zero-context reader                                                                                                 | none (orientation only)                                       | reference  |
| `theory.md`                           | printing-identification pipeline as candidate-constrained decoding: false-accept bound, soundness mechanisms. Owner-reviewed 2026-07-17                                              | printing-consensus / tag-consensus design decisions           | BINDING    |
| `federation-v1.md`                    | federation verdict exchange format v1 (spec, no implementation yet)                                                                                                                  | future federation work only                                   | historical |
| `federation/public-export-v1.md`      | HOLD spec: publish-first federation export                                                                                                                                           | future federation work only                                   | historical |
| `infrastructure.md`                   | Docker build/deploy, secrets, CI/CD state, push policy detail, upstreaming workflow, branch-protection trade-off                                                                     | any deploy/CI/push/branch-protection change                   | BINDING    |
| `troubleshooting.md`                  | symptom-first index of recurring blockers                                                                                                                                            | any blocker costing >15min                                    | reference  |
| `lessons.md`                          | terse cross-session lessons + the lessons→gates triage ritual                                                                                                                        | any recurring "always/never" pattern                          | reference  |
| `upstreaming/conventions.md`          | checklist any `upstream-fix-*`/`upstream-feat-*` branch must satisfy before PR-ready                                                                                                 | any upstream-bound branch                                     | BINDING    |
| `upstreaming/license-provenance.md`   | PROTECTED CORE file list + CI license lint + absorption protocol for external code                                                                                                   | any external-code intake, any PROTECTED CORE file edit        | BINDING    |
| `upstreaming/readiness-audit.md`      | fork-vs-upstream diff, extraction-ease ladder, branch architecture                                                                                                                   | upstreaming planning                                          | reference  |
| `upstreaming/drift-log.md`            | auto-generated weekly: do `upstream-*` branches still apply cleanly                                                                                                                  | upstreaming maintenance                                       | reference  |
| `upstreaming/upstream-wiki-drift.md`  | auto-generated weekly: chilli-axe wiki changes (detection only)                                                                                                                      | upstreaming maintenance                                       | reference  |
| `upstreaming/vote-system.md`          | vote system as cherry-pick extraction manifest. Accurate through 2026-07-13 only                                                                                                     | upstreaming the vote system specifically                      | historical |
| `features/catalog-completion-plan.md` | the harvest/calculate pipeline (Stage 8+): run-cohort safety, phash backfill, evidence recovery, governing image-storage posture. **Live source of truth for anything past Stage 7** | Stage 8+ pipeline work, harvest/calculate/evidence-store code | BINDING    |
| `features/printing-tags.md`           | "What's That Card?" printing-consensus + vote-queue funnel, backend + frontend, Stages 1-7                                                                                           | printing-consensus code, vote-queue UI                        | BINDING    |
| `features/moderation.md`              | Discord OAuth, Moderators group gate, sensitive-tag queue, card reports                                                                                                              | moderation-surface code                                       | BINDING    |
| `features/card-dom-api.md`            | generic `data-card-*` attributes + `mpc:card-selected` event                                                                                                                         | card DOM/external-tooling API                                 | BINDING    |
| `features/pdf-generator.md`           | PDF export tab bug-fix history                                                                                                                                                       | PDF export code                                               | reference  |
| `features/print-export-page.md`       | "Print!" page ordering tabs + flag icons                                                                                                                                             | print-export page code                                        | BINDING    |
| `features/google-drive-connect.md`    | Drive picker, Local Folder, Save-PDF-to-Drive                                                                                                                                        | Google Drive integration code                                 | BINDING    |
| `features/grid-selector.md`           | card-version-picker modal + `Card.tsx` image loading/error states                                                                                                                    | grid-selector / Card.tsx code                                 | BINDING    |
| `features/image-cdn.md`               | the Worker + R2 bucket image CDN                                                                                                                                                     | image-cdn/ Worker code                                        | BINDING    |
| `features/local-file-source.md`       | backend `LOCAL_FILE` catalog source type                                                                                                                                             | local-file source code                                        | BINDING    |
| `features/saved-decks.md`             | zero-knowledge accounts + saved decks: crypto design, endpoints, PR-5/6/7 addenda                                                                                                    | accounts/saved-decks code                                     | BINDING    |
| `features/artist-support-links.md`    | zero-crawl link-out to MTG Artist Connection                                                                                                                                         | `ArtistSupportLink.tsx` and its surfaces                      | BINDING    |
| `features/homepage-panel.md`          | landing panel, its gating, reserved catalog-stats slot                                                                                                                               | `HomepagePanel.tsx`                                           | BINDING    |
| `user-guide.md`                       | end-user guide: search, vote queue, PDF export, saving a project                                                                                                                     | end-user-facing docs only                                     | reference  |
| `self-hosting.md`                     | standing up your own instance (not this fork's own hosting)                                                                                                                          | self-hoster-facing docs only                                  | reference  |
| `readme-sections.md`                  | source regions the README-pipeline assembles from                                                                                                                                    | README-generation pipeline                                    | BINDING    |
| `wiki-home-intro.md`                  | wiki homepage intro content                                                                                                                                                          | wiki-publish pipeline                                         | BINDING    |
| `proposals/`                          | one HOLD/BUILDING/PARTIAL/SHIPPED spec per lettered proposal — see [`README.md`](README.md)'s own status table                                                                       | whichever proposal a task implements                          | historical |
| `reports/`                            | dated, point-in-time session/agent reports — see [`reports/README.md`](reports/README.md)                                                                                            | none (record only, check its own date before trusting)        | historical |
| `audits/`                             | UI content-accuracy findings (currently only on an unmerged branch)                                                                                                                  | UI-content-accuracy work                                      | historical |

## Not yet in this table

`docs/reports/schema.json` isn't `docs/` proper (it lives under
`docs/reports/`) — not a manifest row, but worth knowing about for the
same "what governs this surface" question. A future pass could fold
config-adjacent files like this in if the "governs-what" query needs to
reach past `docs/` itself.

## Maintenance

No CI enforcement yet (deliberately deferred — see the lessons→gates
triage note in `lessons.md`: measure whether a doc actually goes stale
unnoticed before promoting this to a gate). For now: a new `docs/*.md`
file gets a row here in the same PR that adds it, same convention as
every other "edit in place, don't let it rot silently" rule in this
project.

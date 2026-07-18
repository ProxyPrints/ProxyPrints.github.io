As of: 2026-07-18
What this is: UI content-accuracy audit findings — every piece of user-visible copy/data checked against current reality. HOLD, nothing here is fixed yet.
Selection pending — items marked SELECTED will be built; unmarked items are logged but not actioned.

## Summary

**12 findings.** By severity: 5 → 1 · 4 → 3 · 3 → 4 · 2 → 2 · 1 → 2.

**Severity scale:**
- **5** — a suggestion or inference is presented indistinguishably from confirmed fact; the user has no signal to doubt it.
- **4** — actively broken, or a confidently-stated claim with real-world (money/ordering) consequence and no verification.
- **3** — a silently wrong pointer or reference (identity/destination mismatch) presented with plausible-looking authority.
- **2** — misattribution or incomplete identity signal, low practical consequence.
- **1** — clarity gap only; not an accuracy problem.

## Findings

| Selected | # | Location | Current text | Why wrong | Proposed text | Severity |
|---|---|---|---|---|---|---|
| [ ] | 1 | `frontend/src/features/export/FinishedMyProject.tsx:188` | `` `https://download.mpcautofill.com/?platform=${platform}` `` — click target behind all 4 desktop-tool download buttons | Domain not owned by this fork (`docs/infrastructure.md` confirms the deploy job for it always fails) — the primary conversion action of the export flow is a dead link | Point at this fork's own GitHub Releases assets, or a ProxyPrints-owned download host | 4 |
| [ ] | 2 | `frontend/src/features/export/FinishedMyProject.tsx:347-390` | "pick a cardstock finish and a batch size for your order... send your file using their order form or email" | Code comment admits steps/pricing/batch-size/service-area were derived from a one-time read of pringleprints.ca, "not a manual walkthrough," pricing/service area "may have changed since" — the owner's own shop, real money, zero on-screen disclaimer | Do a real walkthrough verification pass, or show "steps may have changed — confirm at pringleprints.ca" until verified | 4 |
| [ ] | 3 | `frontend/src/features/export/FinishedMyProject.tsx:303-345` | "There are three simple steps for turning your project into an order with NotMPC.com" | Same self-flagged-unverified TODO as #2, third-party site, lower stakes than the owner's own shop | Same treatment — verify or disclaim | 3 |
| [ ] | 4 | `frontend/src/features/questionFeed/QuestionFeed.tsx:517-529` | `"{total} total · {contested} contested · {fresh} fresh"`, e.g. "142 total · 30 contested · 112 fresh" | Per PR #29/#34 these are independent overlapping metrics, not a partition — `contested+fresh` need not sum to `total`. Worse, the documented backend-version-skew fallback (`normalizeQuestionFeedCounts`) hardcodes `fresh = total`, `contested = 0`, so "0 contested · 142 fresh" can mean "stale build," not "queue is all-fresh" | Drop "fresh" from the subline, or relabel to signal non-additivity; treat `total == fresh` as an internal version-skew signal, not a display state | 4 |
| [ ] | 5 | `frontend/src/features/ui/Footer.tsx:18` | "Made with ♥️ by chilli_axe" — only site-wide credit | Correct as attribution, but with no ProxyPrints/fork branding alongside it, a visitor can't tell this isn't the upstream site | Add ProxyPrints credit alongside (not replacing) the existing line | 2 |
| [ ] | 6 | `frontend/src/features/ui/Navbar.tsx:130` | `href="https://github.com/chilli-axe/mpc-autofill/releases/latest"` | Site-wide nav CTA points at upstream's release channel — risk of a desktop-tool build not verified against this fork's backend/API | Point at a ProxyPrints-specific release channel if one exists, or confirm upstream compatibility | 3 |
| [ ] | 7 | `frontend/src/features/export/FinishedMyProject.tsx:256` | `href="https://github.com/chilli-axe/mpc-autofill/releases/latest/"` ("Grab it directly from GitHub here") | Same fork-mismatch risk as #6, second call site | Same fix as #6 | 3 |
| [ ] | 8 | `frontend/src/features/export/FinishedMyProject.tsx:215` | `href="https://github.com/chilli-axe/mpc-autofill/tree/master/desktop-tool/"` ("download the source code instead...here") | Points at upstream's source tree, not this fork's, if it diverges | Verify divergence; repoint if this fork carries its own desktop-tool changes | 3 |
| [ ] | 9 | `frontend/src/features/export/FinishedMyProject.tsx:138` | `href="https://github.com/chilli-axe/mpc-autofill/wiki/Desktop-Tool"` ("Check out our wiki here") | Wiki describes upstream's desktop tool/setup, may not reflect ProxyPrints-specific config | Confirm applicability or link a ProxyPrints-specific doc | 2 |
| [ ] | 10 | `frontend/src/features/attributeChips/AttributeChipPanel.tsx:37-42, 230-236` | Chip background color/opacity encodes aggregate voter consensus (`netPolarity`) with zero legend; the one tooltip present reflects the viewer's own tap state, not the fill color | A saturated-green chip can be misread as "the system confirmed this" — a machine-derived signal presented indistinguishably from confirmed fact | Add a legend/tooltip anchoring the fill to real numbers, e.g. "N% of voters agree" | 5 |
| [ ] | 11 | `frontend/src/pages/about.tsx:92` | "Last updated: 12th July, 2026" (Privacy Policy) | Hardcoded date, accurate today, not tied to actual content changes — will silently go stale | No code fix needed now — process note to update on every policy text change | 1 |
| [ ] | 12 | `frontend/src/features/card/DeckbuilderConfirmAffordance.tsx:237-262` | Badge is a bare "?", buttons are bare "Y"/"N"; only explanatory text is a screen-reader-only `aria-label` | Not inaccurate (never claims certainty it doesn't have) — a clarity gap, not a truth violation | Consider a one-word visible label (e.g. "Confirm?") alongside the `aria-label` | 1 |

## Confirmed NOT a finding — correct attribution, leave alone

`frontend/src/pages/about.tsx:51-70` — "About {ProjectName}" section crediting chilli-axe/mpc-autofill's contributors via contrib.rocks. Explicitly the kind of correct upstream credit this audit was scoped to leave untouched.

## Checked, nothing found

**Superseded-behavior help text** (old pre-funnel `/whatsthat` flow, removed chip-gate, old no-match reasons): searched every `title`/`tooltip`/`placeholder`/`aria-label` across `attributeChips/`, `questionFeed/`, `printingTags/`, plus `frontend/src/pages/*` for About/FAQ content. Nothing found — the redesign copy (PRs #49/#50/#55) is internally consistent, and `printingQueue.tsx` (the old URL) is a pure redirect stub with no leftover UI text.

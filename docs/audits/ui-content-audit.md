# UI content-accuracy audit

Survey-only findings from a full sweep of user-visible copy and dynamic
data across the frontend, checked against current reality (repo docs,
recent behavior changes in the funnel redesign and count semantics).
**HOLD — none of these have been fixed yet.** This file is the
selection surface: pick items below, and a build pass addresses them.

Ranked by user impact. Each item: location, current text, why it's
wrong, proposed text, severity.

## 1. CRITICAL — broken desktop-tool download domain

**Location:** `frontend/src/features/export/FinishedMyProject.tsx:188`

**Current:**
```
const assetURL = `https://download.mpcautofill.com/?platform=${platform}`;
```
This is the click target behind all 4 desktop-tool download buttons
(Windows / macOS-Intel / macOS-ARM / Linux) on the post-export screen.

**Why wrong:** `docs/infrastructure.md` confirms this domain isn't
owned by this fork's Cloudflare account, and its own deploy job
(`publish-github-release-reverse-proxy`) "always fails" as a result.
The primary conversion action of the entire export flow is a dead
link.

**Proposed:** point at this fork's own GitHub Releases asset URLs, or
a ProxyPrints-owned download host.

## 2. HIGH — PringlePrints ordering instructions, self-flagged unverified

**Location:** `frontend/src/features/export/FinishedMyProject.tsx:347-390`

**Current:** "pick a cardstock finish and a batch size for your
order... send your file using their order form or email," guarded by
a code comment admitting the steps/pricing/batch-size/service-area
were derived from "a one-time read of pringleprints.ca's site copy,
not a manual walkthrough of their order process," and that "pricing
and service area in particular may have changed since."

**Why wrong:** this is the owner's own print shop — stale steps or
pricing shown to a paying customer with zero on-screen disclaimer.

**Proposed:** do a real walkthrough verification pass now (owner has
direct access), or add a visible "steps may have changed — confirm at
pringleprints.ca" note until verified.

## 3. HIGH — NotMPC ordering instructions, same self-flagged issue

**Location:** `frontend/src/features/export/FinishedMyProject.tsx:303-345`

**Current:** "There are three simple steps for turning your project
into an order with NotMPC.com," guarded by the same class of
self-flagged-unverified TODO immediately above it.

**Why wrong:** same unverified-third-party-flow risk as #2, lower
stakes (not the owner's own shop).

**Proposed:** same treatment — verify or add a disclaimer.

## 4. HIGH — /whatsthat counts subline reads as broken

**Location:** `frontend/src/features/questionFeed/QuestionFeed.tsx:517-529`

**Current:** `"{total} total · {contested} contested · {fresh}
fresh"`, e.g. "142 total · 30 contested · 112 fresh."

**Why wrong:** per PR #29/#34 and `docs/features/printing-tags.md`,
these are independent, overlapping metrics, not a partition of
total — `contested + fresh` isn't guaranteed to sum to `total`.
Worse, in the documented old-backend-version fallback path
(`normalizeQuestionFeedCounts`), `fresh` is hardcoded equal to
`total` (`confirmable`/`contested` forced to 0) purely because of a
frontend/backend version-skew case — a visitor sees "142 total · 0
contested · 142 fresh" and reads it as "the whole queue is fresh,"
when it may just mean they're on a stale build.

**Proposed:** drop "fresh" from the subline (keep total/contested
only), or relabel to signal non-additivity (e.g. "142 total,
including 30 contested"). Separately, treat `total == fresh` as an
internal version-skew signal, not a state to display as-is.

## 5. MEDIUM — footer credits upstream only, no fork identity

**Location:** `frontend/src/features/ui/Footer.tsx:18`

**Current:** "Made with ♥️ by chilli_axe" — the only site-wide credit,
shown on every page.

**Why wrong:** correct as attribution, but with no ProxyPrints/fork
branding alongside it, a visitor has no way to tell via the footer
that they're not on the upstream site.

**Proposed:** add ProxyPrints credit alongside (not replacing) the
existing line, e.g. "ProxyPrints — a fork of chilli_axe's MPC
Autofill, made with ♥️."

## 6. MEDIUM — navbar Download link points at upstream

**Location:** `frontend/src/features/ui/Navbar.tsx:130`

**Current:** `href="https://github.com/chilli-axe/mpc-autofill/releases/latest"`

**Why wrong:** site-wide nav CTA points at upstream's release
channel, not a ProxyPrints-specific one — risk of serving a
desktop-tool build not verified against this fork's backend/API.

**Proposed:** point at a ProxyPrints-specific release channel if one
exists, or confirm upstream releases are actually compatible before
leaving as-is.

## 7. MEDIUM — "Grab it directly from GitHub here" fallback link

**Location:** `frontend/src/features/export/FinishedMyProject.tsx:256`

**Current:** `href="https://github.com/chilli-axe/mpc-autofill/releases/latest/"`

**Why wrong:** same fork-mismatch risk as #6, a second call site.

**Proposed:** same fix as #6.

## 8. MEDIUM — "download the source code instead...here" link

**Location:** `frontend/src/features/export/FinishedMyProject.tsx:215`

**Current:** `href="https://github.com/chilli-axe/mpc-autofill/tree/master/desktop-tool/"`

**Why wrong:** same fork-mismatch class — points at upstream's source
tree, not this fork's, if it diverges.

**Proposed:** verify divergence; repoint if this fork carries its own
desktop-tool changes.

## 9. MEDIUM — "Check out our wiki here" link

**Location:** `frontend/src/features/export/FinishedMyProject.tsx:138`

**Current:** `href="https://github.com/chilli-axe/mpc-autofill/wiki/Desktop-Tool"`

**Why wrong:** wiki content describes upstream's desktop tool/setup,
which may not reflect ProxyPrints-specific configuration differences.

**Proposed:** confirm wiki applicability or link a ProxyPrints-specific
doc if one exists.

## 10. LOW-MEDIUM — confidence-fill chip has no legend

**Location:** `frontend/src/features/attributeChips/AttributeChipPanel.tsx:37-42, 230-236`

**Current:** chip background color/opacity is a continuous function of
aggregate voter consensus (`netPolarity`), with zero legend anywhere.
The only tooltip present ("Yes"/"No"/"Tap to describe what you see")
reflects the current viewer's own tap state, not what the fill color
means.

**Why wrong:** not a false claim, but a saturated-green chip could be
misread as "the system confirmed this" when the one available tooltip
doesn't explain the color at all — a clarity gap adjacent to
accuracy.

**Proposed:** add a brief legend or tooltip anchoring the fill to real
numbers, e.g. "N% of voters agree."

## 11. LOW — hardcoded Privacy Policy date

**Location:** `frontend/src/pages/about.tsx:92`

**Current:** "Last updated: 12th July, 2026"

**Why wrong:** hardcoded date, accurate today, not tied to actual
content changes — will silently go stale the next time the policy
text changes without this line being updated in lockstep.

**Proposed:** no code fix needed now — process note to update this
line whenever policy text changes, not a display-logic problem.

## 12. LOW — Level 0 affordance has no visible label

**Location:** `frontend/src/features/card/DeckbuilderConfirmAffordance.tsx:237-262`

**Current:** badge is a bare "?", action buttons are bare "Y"/"N";
only explanatory text is a screen-reader-only `aria-label` ("Compare
against the imported printing").

**Why wrong:** not inaccurate (never claims certainty it doesn't
have), but unclear to a sighted user until they interact with it —
closer to a clarity gap than a truth violation, included for
completeness since it was named explicitly in scope.

**Proposed:** consider a one-word visible label (e.g. "Confirm?") in
addition to the `aria-label`.

## Confirmed NOT a finding — correct attribution, leave alone

`frontend/src/pages/about.tsx:51-70` — "About {ProjectName}" section
crediting chilli-axe/mpc-autofill's contributors via contrib.rocks,
explicitly the kind of correct upstream credit this audit was scoped
to leave untouched.

## What was checked with no findings

**Superseded-behavior help text** (old pre-funnel /whatsthat flow,
removed chip-gate, old no-match reasons): searched every
`title`/`tooltip`/`placeholder`/`aria-label` across
`attributeChips/`, `questionFeed/`, `printingTags/`, plus
`frontend/src/pages/*` for About/FAQ content. Nothing found — the
redesign copy (PRs #49/#50/#55) is internally consistent with itself,
and `printingQueue.tsx` (the old URL) is a pure redirect stub with no
leftover UI text.

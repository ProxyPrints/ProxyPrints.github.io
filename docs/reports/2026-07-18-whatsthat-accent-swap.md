```
TASK: /whatsthat accent color swap (blue -> AA-verified navy against orange bg)
Branch: claude/starburst-oversize-fix -> PR #91 (same branch as the starburst fix, per
        "same page area, your call")
Commit: 19c212a

WHAT SHIPPED:
- Orange background (#ff4719) confirmed staying, per the owner's ratification -
  no code change needed for that half of the decision.
- Accent swap scoped to StarburstBackground (the orange-background element) in
  whatsthat.tsx only: links (--bs-link-color-rgb), the "Filter by attribute"
  toggle (.btn-link), Level 3's "Confirm & continue" (.btn-primary), and the
  moderator tab switcher's active pill (.nav-pills). Semantic colors (success/
  danger/warning) and attribute-chip polarity fills untouched - confirmed by
  scoping the override to a single element and its descendants, not any
  site-wide variable.
- New accent: #12262c, derived from Superhero's own info/cyan (#5bc0de) by
  uniform multiplicative darkening (preserves hue/saturation, reduces only
  luminance) until AA-for-text clears against the orange background.

MEASURED WCAG RATIOS (rule 1's explicit ask):
- #12262c (new accent) vs #ff4719 (page bg): 4.60:1 - PASSES AA normal text (4.5:1)
- white vs #12262c (button text on the new accent fill): 15.68:1 - passes easily
- Reference/baseline, for context: old accent #4c9be8 vs #ff4719 = 1.16:1 (fails
  badly - confirms the owner's "drowning" observation was accurate); even pure
  white vs #ff4719 only reaches 3.41:1 (still fails AA normal text) - meaning NO
  light tint of any hue can pass AA against this specific orange (its luminance
  sits in a mid-range that only a sufficiently dark color's wider luminance gap
  clears), which is why StarburstBackground's own body text is already black,
  not white, for the identical reason. This constrained the direction (darken,
  not lighten) - documented in the code comment, not just this report.
- Hover/active button states are simple lighten/darken steps off the verified
  base, not independently contrast-checked (the base + its white text are the
  two ratios AA actually depends on; interaction-state tints don't carry their
  own text-legibility requirement).

REAL BUG FOUND: overriding Bootstrap 5.2's --bs-primary-family custom
properties alone does NOT reach .btn-primary's rendered background. Bootswatch's
Superhero theme (_bootswatch.scss) hardcodes a LITERAL background-color on
.btn-primary directly (not var(--bs-btn-bg)), at equal CSS specificity to and
later in compiled source order than Bootstrap's own custom-property-driven
.btn rule - it wins the cascade regardless of what --bs-btn-bg resolves to.
Diagnosed by comparing a live element's queried --bs-btn-bg custom-property
value (correctly showed my override) against its actually-rendered
background-color (still showed the old theme blue) - a genuine mismatch that
took directly reading bootswatch's compiled SCSS source to explain. Fixed by
also setting background-color/border-color directly in the override (my
selector's higher specificity wins over bootswatch's bare .btn-primary, no
!important needed). .btn-link (the "Filter by attribute" toggle) is NOT
affected by this same issue - bootswatch's hardcoding loop only iterates
$theme-colors, and "link" isn't one, so the standard custom-property approach
works correctly for it.

SCOPE VERIFICATION (rule 3's explicit ask): confirmed via live computed
styles, not just code reading -
- /whatsthat's "Filter by attribute" link: rgb(18, 38, 44) = #12262c (new) ✓
- /whatsthat's Level 3 "Confirm & continue" button: bg rgb(18, 38, 44), text
  white ✓
- /whatsthat's OWN Footer links (GitHub/Reddit/Discord/etc., sitting on the
  page's standard dark body background, not the orange): rgb(76, 155, 232) =
  #4c9be8 (site-wide default) - UNCHANGED, confirming the scope correctly
  excludes the Footer (which needs the ORIGINAL accent for its own good
  contrast against a completely different background).
- A different page (/editor)'s nav link: unchanged from its normal color -
  zero leakage confirmed.
Screenshots (before/after at 1280px desktop and 390px mobile, plus the
/editor zero-leakage proof) sent directly in chat.

BRANCH DECISION (rule 4's explicit ask): committed to PR #91's existing
branch (claude/starburst-oversize-fix) rather than opening a new PR - same
page, same visual-diagnosis lineage, and PR #91 was still open/unmerged at
the time this landed. PR #91's title/description updated to cover both
fixes.

DEVIATIONS: none from the four numbered rules. The owner's rule 1 anticipated
exactly the outcome found (permitted "a darkened/adjusted variant... if
contrast demands") - the darkening required was more aggressive than a
casual reading of "start from #5bc0de" might suggest, but the measured
numbers make the reason concrete rather than a stylistic overreach.

VERIFICATION:
- npx tsc --noEmit: clean except one pre-existing, unrelated error in
  DisplayPage.tsx (a concurrent session's PR #87 - confirmed via git log/
  git show not caused by this change, already flagged in the prior /whatsthat
  diagnosis report).
- npx jest --runInBand: 32 suites / 345 tests passing.
- npx eslint + npx prettier --check on whatsthat.tsx: clean.
- Live Playwright/MSW render, desktop + mobile, reaching Level 3's primary
  button and a second page - all via direct computed-style queries, not
  visual inspection alone.
- PR #91: https://github.com/ProxyPrints/ProxyPrints.github.io/pull/91

OPEN ITEMS / DECISIONS NEEDED:
1. The new accent (#12262c) is a very dark navy, close to (but distinguishable
   from) the page's own black body text - by necessity, not choice (see the
   measured-ratios section: no lighter option passes AA against this orange).
   Visually it still reads as clearly "blue-hued" and pops strongly against
   the orange in the attached screenshots, but it's a judgment call whether
   this satisfies the spirit of "so interactive elements read against the hot
   background" as intended, or whether the owner would rather relax to AA
   Large Text's 3:1 threshold (reachable with a visibly lighter/more vibrant
   blue) for a punchier look at the cost of stricter-than-3:1 normal-text
   compliance. Flagging for a look at the actual screenshots rather than
   deciding unilaterally which threshold to target.
2. DisplayPage.tsx's tsc error (flagged in the prior report too) is still
   unresolved on master - not touched by this task either, still needs an
   owner-assigned follow-up.

LIVE STATE: PR #91 open against master (both fixes), not merged. No local
dev servers or background processes left running. Scratch diagnostic
Playwright specs (not committed) created and deleted during investigation.
```

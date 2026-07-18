```
TASK: CLOUD session (upstream-readiness) — proxies-at-home lineage
recon (Akurosia/kclipsto), federation spec update. Branch:
federation-lineage-recon-cvq14g. PR:
https://github.com/ProxyPrints/ProxyPrints.github.io/pull/103 (against
this fork's own master — never upstream). Documentation only, no
outreach, no PRs against any external repo.

WHAT SHIPPED (docs/federation/public-export-v1.md §6(b), plus new §8):

1. Lineage check: kclipsto/proxies-at-home (the repo the Akurosia
   fork's README claims as its own source) does NOT resolve —
   api.github.com/repos/kclipsto/proxies-at-home 404s; the kclipsto
   account's only other public repo (proxxied-issues) is unrelated.
   Akurosia/proxies-at-home IS public, a real fork of
   acoreyj/proxies-at-home (per GitHub's own parent/source metadata,
   not of kclipsto's), last pushed 2026-04-02T08:53:30Z — used as the
   accessible stand-in for the rest of this recon since kclipsto's own
   repo can't be read directly.
2. Consumer story (b) updated with the concrete finding: named in the
   spec (real, working mpcfill-style search + XML export integration),
   but explicitly NOT labeled MIT. README's own "License: MIT" claim
   conflicts with package.json's "license": "ISC"; no LICENSE file
   exists anywhere in the repo root; GitHub's license-detection API
   returns null for the repo. Followed this doc's own established
   precedent (the earlier alex-taxiera/proxy-print MIT->AGPL-3.0
   correction) — named without asserting a confident license rather
   than picking one to match the "open-source-nameable" instruction at
   face value.
3. XML dialect paragraph added, flagged for PR-7's XML 2.0
   provenance-attribute design: read mpcXmlExport.ts (attribute-free
   <order>/<fronts>/<backs>/<card> dialect, all data as child elements)
   and importParsers.ts (DOMParser + tag-name/CSS-selector lookups
   only, no schema/whitelist validation anywhere) — confirmed this
   parser would silently ignore, not reject, any unknown attributes or
   child elements a future XML 2.0 provenance extension might add.
4. One-line correction added: the doc's earlier framing (naming only
   the MIT upstream acoreyj/proxies-at-home, implicitly treating the
   live proxxied.com deployment as a separate, unexamined closed
   service) is superseded by this finding — the actual production
   fork is public and its integration code is readable, though its
   own license remains genuinely unresolved rather than confidently
   open.

Mid-turn addition, folded into the same branch/PR per the "your call"
instruction: new §8 "Future work (design intent, no build)" —
documents the intent to build two upstream-shaped reference consumers
in this repo (a Django import command for mpc-autofill, a TS
verdict-lookup module for proxies-at-home), with upstreaming
contribution gated on (a) the export going live and (b) for
proxies-at-home specifically, on initial contact — noting the
license-ambiguity finding above as a reason that contact needs to
clarify licensing before any code changes hands either direction.

DEVIATIONS:
- Did not label Akurosia/proxies-at-home "MIT" despite the task's
  "name the repo + license, per the open-source-nameable rule"
  instruction, because the actual license is contradictory/unresolved
  (see finding 2 above) — treated "verify before naming" as the
  governing rule over "always attach a license label," matching how
  this same doc already handled the alex-taxiera/proxy-print
  correction. Flagging this explicitly rather than silently picking
  MIT to satisfy the letter of the instruction.
- §8 was added as a new section rather than folding into the existing
  §7 ("What v1 explicitly isn't") — §7 states what v1 deliberately
  excludes; the reference-consumer/upstreaming intent is a genuine
  future-work item, not an exclusion, so it reads better as its own
  section.

VERIFICATION:
- All GitHub facts (repo existence/visibility/fork-parent, license
  fields, actual file contents) checked live via api.github.com and
  raw.githubusercontent.com fetches — not assumed from the Akurosia
  README's own self-description at any point (its own claimed source
  repo, kclipsto/proxies-at-home, turned out not to resolve).
- python3 .github/scripts/docs_lint.py — clean.
- npx prettier@2.7.1 --check (pinned version) on the touched file —
  clean.

OPEN ITEMS / DECISIONS NEEDED:
1. Akurosia/proxies-at-home's real license is unresolved (README says
   MIT, package.json says ISC, no LICENSE file, GitHub detects none) —
   if this project matters enough to name confidently with a license
   in future spec revisions, that likely needs direct contact with the
   repo's maintainer, not further guessing from this session.
2. PR #103 is open against this fork's own master, awaiting the
   owner's merge-queue action.

LIVE STATE: branch federation-lineage-recon-cvq14g pushed to origin;
PR #103 open against ProxyPrints/ProxyPrints.github.io master,
unmerged. Separate from PR #100 (docs/conventions hygiene batch),
still also open/unmerged. No outreach performed to any external repo
or its maintainers. No uncommitted work left behind.
```

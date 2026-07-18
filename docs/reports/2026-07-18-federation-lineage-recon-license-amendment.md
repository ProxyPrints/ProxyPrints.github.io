```
TASK: CLOUD session (upstream-readiness) — one-line amendment to PR
#103's §6(b) license phrasing, per owner decision. Same branch:
federation-lineage-recon-cvq14g. PR:
https://github.com/ProxyPrints/ProxyPrints.github.io/pull/103

WHAT SHIPPED: replaced the prior "genuinely unclear, not confidently
MIT" framing in docs/federation/public-export-v1.md §6(b) with a
SHA-pinned "stated MIT" attribution, per instruction:
"stated MIT (README, as of commit
2a5826788ff7c1827b73c6042d0b4b5d1a4e8340, 2026-02-22; package.json
states ISC — near-equivalent permissive; no LICENSE file present)".
- Pinned SHA fetched live (GitHub's commit history for README.md on
  Akurosia/proxies-at-home's main branch), not guessed — 2026-02-22,
  "Update README.md (#188)", authored by kclipsto (the same name as
  the account the README itself credits as the upstream source).
- Added the requested footnote: permissive intent is credited and
  SHA-snapshotted so the claim can't silently drift if the README
  changes later; package.json's ISC treated as near-equivalent
  permissive rather than a disqualifying contradiction; the missing
  LICENSE file stays the one real, unresolved gap, explicitly left for
  the eventual first-contact outreach (§8) to raise, not something
  this footnote resolves on its own.
- Practical rule restated unchanged from the prior wording: design
  patterns may be referenced freely; actual code reuse from the fork's
  post-acoreyj additions still waits on a LICENSE file or the
  operator's own word.
- PR #103's description updated to reflect the amendment.

DEVIATIONS: none — applied exactly as specified.

VERIFICATION:
- python3 .github/scripts/docs_lint.py — clean.
- npx prettier@2.7.1 --check (pinned version) — clean after one
  --write pass (only the two hunks actually touched reformatted,
  confirmed via git diff hunk count — rest of the file untouched).
- Confirmed diff scope: `git diff` shows exactly 2 hunks changed
  (the §6(b) paragraph and the new footnote), nothing else in the
  504+-line file touched.

OPEN ITEMS / DECISIONS NEEDED: none new. Still open from the prior
relay: PR #103 awaiting the owner's merge-queue action (unchanged).

LIVE STATE: branch federation-lineage-recon-cvq14g now has 2 commits
(the original recon + §8, then this license-phrasing amendment),
pushed to origin. PR #103 open against
ProxyPrints/ProxyPrints.github.io master, description updated,
unmerged. No uncommitted work left behind.
```

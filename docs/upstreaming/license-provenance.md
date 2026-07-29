# License provenance + protected core

As of: 2026-07-19. **HOLD — owner review, per the original commission.**
Companion to [`readiness-audit.md`](readiness-audit.md) (§9 there is the
short pointer; this file is the full findings + policy). Nothing here
changes CI behavior for existing code beyond the one new, currently-empty
lint job in §2 — it fires on zero real violations today and exists to
catch a future one.

## 0. What this is

The owner's ledger commission, in order: (1) a provenance column on the
extraction ladder — done, `readiness-audit.md` §1.1–1.3/§9. (2) a
one-time external-code sweep — done, §1 below. (3) a PROTECTED CORE
policy for federation/vote-system modules — §2. (4) an absorption
protocol for any future external-code intake — §3. (5) disclosure
mechanics (README region, NOTICE convention, site footer) — §4, built
now per the commission's own "cheap today, load-bearing the day any
absorption happens" framing, except the site footer piece, explicitly
routed elsewhere (§4.3). (6) a CLAUDE.md convention line — added
directly to `CLAUDE.md`'s Tooling rules section in this same change; not
duplicated here.

## 1. Provenance audit — findings

**Not "expected clean, confirmed clean."** The sweep (every `.py`, `.ts`,
`.tsx`, `.js`, `.jsx`, `.css`, `.html`, `.go`, `.sh` file repo-wide,
outside `node_modules/`, `.git/`, and lockfiles, across `MPCAutofill/`,
`frontend/`, `schemas/`, `image-cdn/`, `desktop-tool/`,
`cloudflare-static-site/`, `github-release-reverse-proxy/`, `docker/`,
`.github/`) found 4 real external-origin items. None are a licensing
_violation_ — nothing here is copyleft-incompatible with this repo's own
GPL-3.0 — but 2 of the 4 are missing full license-notice compliance, a
real, previously-unnoticed gap this pass closes rather than papers over.

### 1.1 `frontend/src/components/flags.tsx` + 3 SVG assets

`flag-usa.svg`, `flag-canada.svg`, `flag-china.svg` (`frontend/public/`),
vendored from [`lipis/flag-icons`](https://github.com/lipis/flag-icons)
(MIT), added in commit `f048ca32`. Already the ladder's own IV.5 finding
(`readiness-audit.md` §1.2) — cross-referenced there, not a new
discovery. **Attribution present but incomplete**: `flags.tsx` carries a
comment citing the source repo and "MIT license," but the MIT license
text itself isn't reproduced anywhere in this repo — a comment saying
"see that repo's LICENSE" doesn't satisfy MIT's own "include a copy of
this permission notice" requirement literally, even though the practical
risk is low (the reference is genuine, specific, and correct). Closed by
§4's new `NOTICE` file, which reproduces the actual notice text for all
four items in this section in one place.

### 1.2 `frontend/src/components/RenderIfVisible.tsx`

Vendored from
[`NightCafeStudio/react-render-if-visible`](https://github.com/NightCafeStudio/react-render-if-visible),
commit `6254ffce` ("vendor in `NightCafeStudio/react-render-if-visible`
on 2025-04-06 to apply the fix from .../pull/21"). **License correction,
verified not assumed**: the vendoring commit's own comment doesn't state
a license, and the audit sub-pass that first flagged this file wrongly
assumed MIT without checking. Verified directly against the upstream
repo's GitHub API license metadata for this doc (2026-07-19): it's
**Apache License 2.0**, not MIT. This is exactly the "verified, not
assumed" mistake this repo's own conventions exist to catch — recorded
here rather than silently corrected, since the wrong assumption briefly
existed in this pass's own working notes.

Apache-2.0 code is compatible with inclusion in a GPL-3.0 project (a
one-directional compatibility both the FSF and the Apache Software
Foundation recognize for GPLv3 specifically) but has real requirements
beyond a bare source comment: retain the original copyright/attribution
notice, and state significant changes made to the file. Neither is fully
present today — closed by §4's `NOTICE` file plus this doc's own record
of what changed (the PR #21 fix, per the original vendoring comment).

### 1.3 `frontend/src/components/OverflowList.tsx`

Vendored from
[`mattrothenberg/react-overflow-list`](https://github.com/mattrothenberg/react-overflow-list)
"with some minor tweaks to reduce flickering" per its own comment;
earliest commit found in this fork's visible history is `ad3ed3d0` (a
rename commit — the actual vendoring predates it). **Verified**: MIT,
confirmed directly against the upstream repo's GitHub API license
metadata (2026-07-19). License terms aren't reproduced in-repo — same gap
as §1.1, closed the same way.

### 1.4 `MPCAutofill/cardpicker/local_pilot_data/keyrune/`

`keyrune.ttf` + `codepoints.json`, vendored from the `keyrune` npm
package for server-side OCR/phash set-symbol matching
(`local_fallback.py`), introduced in commit `ff7bedd0` ("Add local
OCR/phash printing-ID backfill pilot (Stage 8)"). **Already fully
compliant** — the only one of the four that is: a comment cites "the
keyrune npm package, SIL OFL 1.1," and a complete `LICENSE.md` (Keyrune's
own — GPL-3.0 for its code/icons, SIL OFL 1.1 for its fonts, copyright
Andrew Gioia) is checked in alongside the vendored files. Cited in §3 as
the pre-existing positive precedent the absorption protocol formalizes —
this vendoring already did, by instinct, exactly what §3 now requires in
writing.

**Not the same thing as `frontend/public/keyrune/`**: the frontend has
its own, separate, gitignored copy of keyrune's font, generated at
`npm install` time from the real `keyrune` npm dependency declared in
`package.json` — ordinary dependency management with its own license
metadata already tracked by npm, not a second vendoring finding. Two
independent uses of the same upstream project, one vendored-in-place
(backend, this section), one dependency-managed (frontend).

### 1.5 Minor attributed one-liners — noted, not a compliance concern

Eight short (1–8 line) code idioms, each with an inline StackOverflow
citation, no substantial copied logic: `DisableSSR.tsx`, `api.ts`,
`processing.ts`, `Card.tsx`, `Layout.tsx`, `jest.setup.ts`,
`desktop-tool/autofill.py`, `MPCAutofill/MPCAutofill/settings.py`. Listed
for completeness per the audit's own scope, not flagged as action items —
short idiomatic snippets at this size are standard practice and not
meaningfully "external code" in the sense this audit cares about.

### 1.6 Not a concern — auto-generated, not hand-copied

`image-cdn/worker-configuration.d.ts` and
`github-release-reverse-proxy/worker-configuration.d.ts` carry large
embedded Apache-2.0 headers (Cloudflare/Microsoft copyright) — both
self-declare "Generated by Wrangler by running `wrangler types`," a
build/type-generation artifact from the Cloudflare Workers toolchain both
projects already depend on, functionally equivalent to a lockfile. No
action needed.

### 1.7 Swept clean — stated with the actual scope, not vague reassurance

- Every source file repo-wide for attribution keywords (`vendored`,
  `adapted from`, `copied from`, `taken from`, `based on`,
  `stackoverflow`, `MIT`, `Apache`, `BSD`, `Copyright (c)`) — every hit
  triaged above; the rest were false positives (identifier names, this
  repo's own `LICENSE.md`, `package.json` license fields).
- No `THIRD_PARTY`, `NOTICE` (before this change), `ATTRIBUTIONS`, or
  `vendor`-named directory anywhere in the tree.
- `frontend/public/` fully enumerated: only asset beyond the items above
  is `arrow.svg` (an Adobe Illustrator generator string, no
  copyright/license text, no external attribution — reads as originally
  authored, not vendored).
- The local OCR/phash pilot code (`local_phash.py`, `local_fallback.py`,
  `local_identify_printing_tags.py`, `models.py`) checked specifically
  for algorithm-attribution or paper/AGPL citations, given it's exactly
  the kind of code where a copy-pasted implementation would be tempting —
  none found. Perceptual hashing uses the real `ImageHash~=4.3.2` PyPI
  dependency (`import imagehash`, pinned in `MPCAutofill/requirements.txt`),
  not a copied algorithm.
- `desktop-tool/`, `schemas/`, `cloudflare-static-site/`, `docker/`,
  `.github/` — same keyword sweep, nothing beyond §1.5's one-liner.

## 2. Protected core

**Scope — the actual files, not just the concept**, since a policy
nobody can point at doesn't function as one:

- `MPCAutofill/cardpicker/vote_consensus.py`
- `MPCAutofill/cardpicker/printing_consensus.py`
- `MPCAutofill/cardpicker/tag_consensus.py`
- `MPCAutofill/cardpicker/artist_consensus.py`
- `MPCAutofill/cardpicker/local_phash.py` — **still protected**; carries
  one authorised exception, 2026-07-29, logged in §2.1. The exception
  covers that one change, not the file.
- `MPCAutofill/cardpicker/local_fallback.py` — **still protected**; carries
  one authorised exception, 2026-07-29, logged in §2.1. The exception
  covers that one change, not the file.
- `federation-hash-tool/hash_my_cards.py` (+ its test)
- `MPCAutofill/cardpicker/tests/test_federation_hash_tool_parity.py` (the
  parity tether between the previous two)
- `decrypt-saved-deck-export/decrypt.mjs` (+ its test) — the standalone,
  zero-import, zero-dependency decrypt tool for a saved-decks export
  bundle (PR #242); same standalone-trust-anchor risk shape as the
  federation hash tool above, not itself part of the vote/federation
  system. **Not yet in `check_protected_core_license.py`'s
  `PROTECTED_CORE_FILES`** — that file only exists on PR #242's branch,
  not yet on `master`; add both paths to the CI script's list in the PR
  that merges #242 (or immediately after), per this section's own "keep
  these in sync in the same PR" convention.
- **Prospectively**: any future verdict schema/signing/export/import/
  keygen module (`federation-v1.md`/`federation/public-export-v1.md`
  describe the format; per those docs, "format committed ahead of
  code" — none of that code exists yet, so there's nothing to list here
  today beyond the commitment that whatever gets built there joins this
  list in the same PR).

**Explicitly NOT file-level protected here, despite being
conceptually part of the vote/consensus system**:
`MPCAutofill/cardpicker/models.py`. The `VoteSource`/
`AbstractWeightedVote`/`CanonicalPrintingMetadata`/`CardPrintingTag`
class definitions inside it are real protected-core content, but the
file also holds dozens of unrelated model classes — a file-level import
lint would either miss real violations scoped to just those classes or
false-positive on every unrelated model change in the same file. Per
this repo's own established "narrow v1, no heavyweight AST library"
philosophy (`docs_lint.py`'s own stated limitation), building a real
per-symbol static-analysis check is out of v1 scope. Until/unless that's
worth building, this is a **manual-review item**: any PR touching those
four classes specifically should get the same license-provenance
scrutiny as a file on the mechanical list, by convention, not by CI gate.

**One real correction to the commission's own framing, stated plainly
rather than silently absorbed**: the directive says protected-core files
"MUST remain GPL-3-clean." That's accurate for every file in the list
above **except** `federation-hash-tool/hash_my_cards.py` and its test —
that tool is **deliberately MIT-licensed**, a distinct, already-decided
choice (`docs/federation/public-export-v1.md` §5: "Distinct from the
reference tooling's MIT license... those are separate decisions about
separate artifacts," decided by the owner 2026-07-18), precisely so
third-party consumers can use it without GPL's copyleft attaching —
and, as of PR #242, `decrypt-saved-deck-export/decrypt.mjs` and its
test as well — that tool is likewise **deliberately MIT-licensed**, a
distinct, already-decided choice (PR #242, mirroring the federation
hash tool's own precedent, decided by the owner 2026-07-20), precisely
so third-party consumers can use it without GPL's copyleft attaching.
The actual invariant isn't "everything here must be GPL-3" — it's **"nothing
here may import from or derive from AGPL-marked code,"** which would
poison either license (AGPL is incompatible with distributing under
GPL-3.0-only, and definitely incompatible with keeping something
genuinely MIT-permissive). The CI check below enforces the real
invariant, not the narrower one the directive stated.

**The CI check — built, not just designed**: a new
`.github/scripts/check_protected_core_license.py` walks each
protected-core file's local (intra-repo) imports and fails if any
imported local module carries an `AGPL` mention in a `# PROVENANCE:`
header comment (the format §3's absorption protocol requires of any
future external-code intake) — also fails if a protected-core file
carries that marker on itself directly. Wired into `docs-lint.yml` as a
new `protected-core-license` job. **Passes today with zero findings**,
correctly — nothing in this repo is AGPL-marked; the check's only job is
to trip the day that stops being true. Deliberately does NOT attempt to
scan transitive PyPI/npm dependency license metadata (a much larger,
separate problem — tools like `pip-licenses` exist for that and aren't
part of this pass); it catches the specific risk the absorption protocol
is actually worried about: someone pasting AGPL-licensed _source code_
directly into a protected-core file, not a third-party package turning
out to have an unexpected license three dependencies deep.

### 2.1 Authorised exceptions — the log

Protection here means **deliberate review**, not immutability. A change to
a listed file is allowed when the owner rules on it specifically. Every
such ruling gets an entry below, so a reviewer who was not present can see
what was changed, why, who authorised it, and — the part that matters most
— **how far the authorisation reaches**. An entry that reads as a
precedent would be worse than no entry: the whole value of the policy is
that the next change has to be asked for again.

The file stays on the list in §2 either way. An exception authorises **one
change**; it does not un-protect a file.

**2026-07-29 — `MPCAutofill/cardpicker/local_phash.py`: declare the two
skip-reason constants at source.**

- **What changed.** `find_best_match` returned two skip reasons as bare
  inline string literals, `"no-hashable-candidates"` and
  `"no-clear-winner"`. They are now declared as module-level
  `PHASH_NO_HASHABLE_CANDIDATES_SKIP_REASON` and
  `PHASH_NO_CLEAR_WINNER_SKIP_REASON`, exported in `__all__`, and returned
  by name. The mirrored copies of both constants in
  `local_identify_printing_tags.py` (added by PR #567 precisely because
  this file could not be edited) were deleted; that module now imports the
  one it uses. Nothing else in the file was touched.
- **Why.** The `*_SKIP_REASON` declaration convention and the roster tether
  `check_skip_reason_roster_tether()` (PR #567,
  `docs/reference/skip-reasons.md`) derive the skip-reason roster by
  scanning for module-level `NAME = "<literal>"` declarations. **The tether
  cannot enumerate literals it cannot see.** With the values declared only
  in the consuming module, a NEW literal added inside `find_best_match`
  would have reached `CardScanLog.skip_reason` — a column with ~2.7M
  production rows and no `choices` list or foreign key protecting it — with
  no lint failure anywhere. PR #567 documented that hole and could not
  close it, because closing it required editing this file. Two declarations
  in a protected file is the smaller risk; an undetectable roster gap in
  the vote system's own scan log is the larger one.
- **Who authorised it.** The owner, ruling on 2026-07-29 on a request that
  named this file and this change specifically.
- **Effect: none, and it is proved rather than asserted.** This is a
  naming-only change. The string VALUES are untouched, so a `CardScanLog`
  row written after it is byte-identical to one written before. Proof, in
  the PR: (a) the after-source with the two constants inlined back to their
  literals parses to an AST identical to the before-source; (b) the
  sequence of strings `find_best_match` can return, resolved statically
  through the module's constant table, is unchanged; (c)
  `tests/test_skip_reason_roster.py`, which pins every roster value against
  a hand-written expected set, needed **no edit** — the constant NAMES were
  kept byte-identical too, so nothing about the roster moved except its
  declaration site. There is no licensing effect of any kind: no import was
  added to or removed from this file, no external code was introduced, and
  the file's GPL-3.0 status and `PROVENANCE:`-header cleanliness are
  unchanged. `check_protected_core_license.py` passes, and
  `local_phash.py` remains in `PROTECTED_CORE_FILES` and in §2's list
  above.

- **What keeps the hole closed.** The tether alone cannot: it is blind to
  exactly the two regressions that would undo this. Two guards in
  `tests/test_skip_reason_roster.py` cover them —
  `test_phash_skip_reasons_are_declared_at_their_origin_and_nowhere_else`
  (fails if any other `cardpicker` module re-declares either value, i.e. if
  the mirror comes back) and
  `test_find_best_match_returns_no_bare_skip_reason_literal` (fails if a
  skip reason is returned from `find_best_match` as a bare literal rather
  than a named module-level constant). Both were mutation-checked against
  the regression each claims to catch.

- **SCOPE OF THIS EXCEPTION — read this before citing it.** It permits
  **declaring skip-reason constants in `local_phash.py`**, and that is its
  entire reach. It is specifically NOT:
  - a general licence to edit `local_phash.py`;
  - a licence to edit any other protected-core file, including the four
    consensus modules, `local_fallback.py`, or the federation hash tool —
    several of which emit skip-reason-shaped literals of their own (see
    `docs/reference/skip-reasons.md`), and none of which are covered here;
  - a standing rule that "lint-driven refactors are exempt". The next
    change of any shape to any file on this list, including the next
    lint-driven one, **needs its own ruling and its own entry below.**

**2026-07-29 — `MPCAutofill/cardpicker/local_fallback.py`: declare the
three skip-reason constants at source.**

The second entry in this log, and it is the second entry rather than a
continuation of the first: the previous entry's own SCOPE section names
`local_fallback.py` explicitly as a file it does **not** cover. This change
was asked for and ruled on separately.

- **What changed.** `run_fallback_for_card` set
  `FallbackOutcome.skip_reason` from three bare inline string literals,
  `"no-evidence"`, `"eliminated"` and `"ambiguous"`. They are now declared
  as module-level `LOCAL_FALLBACK_NO_EVIDENCE_SKIP_REASON`,
  `LOCAL_FALLBACK_ELIMINATED_SKIP_REASON` and
  `LOCAL_FALLBACK_AMBIGUOUS_SKIP_REASON`, exported in `__all__`, and passed
  by name. Two docstrings and one field comment were extended to say so.
  **Nothing else in the file was touched, and no mirror was deleted because
  none existed** — unlike the `local_phash` case, these values were never
  re-declared in a consuming module, because this engine's one non-test
  caller never reads them (see "Effect" below). The `FALLBACK_*_SKIP_REASON`
  family in `local_calculate_verdicts.py` is **not** a mirror of these: it
  belongs to the separate `stage-d-fallback-v1` calculator, has its own
  rows, and deliberately renames this engine's `no-evidence` to
  `no-sub-check-evidence`. It was checked and left alone; collapsing the two
  families would erase a real distinction. The `LOCAL_FALLBACK_` prefix
  exists to keep them apart, and matches this module's own
  `FALLBACK_ANONYMOUS_ID = "local-fallback-v1"`.
- **Completeness — verified, not taken on trust.** The request named three
  literals. The file was re-scanned with an AST pass for every `skip_reason=`
  keyword argument, every `.skip_reason` attribute assignment, and every
  lowercase/hyphenated string constant it contains. Three is the complete
  set. The other lowercase literals the scan surfaced (`black`, `white`,
  `silver`, `borderless`, `modern`, `old`, `trimmed`, `bleed`,
  `appropriate-bleed`) are classifier outputs and tag names on paths that
  never touch `skip_reason`.
- **Why.** Identical to the previous entry's reasoning, and the reasoning is
  the point rather than the precedent: the `*_SKIP_REASON` declaration
  convention and the roster tether `check_skip_reason_roster_tether()`
  (PR #567, `docs/reference/skip-reasons.md`) derive the roster by scanning
  for module-level `NAME = "<literal>"` declarations. **The tether cannot
  enumerate literals it cannot see.** A fourth reason added inside
  `run_fallback_for_card` would have joined three invisible siblings, and
  `CardScanLog.skip_reason` — ~2.7M production rows, no `choices` list, no
  foreign key — is what it would eventually reach.
- **The defect was LATENT, not live, and that is an argument for closing it
  rather than against.** Nothing persists this outcome today: the module's
  own printing-vote/scan-log write branch was retired by PR #560 on
  2026-07-29, and its one non-test caller,
  `local_residual_classify.recover_frame_mismatch_printing_via_fallback_refetch`,
  reads `outcome.printing_pk` and discards `skip_reason` entirely. So no row
  reaches the column through this path right now. The invisibility, however,
  is a property of the literals and not of the caller: it becomes a live
  hole the instant anything persists the outcome, and nothing would fail at
  that moment to mark it. Closing it while it is cheap, and while the change
  is provably inert, is the smaller intervention in a protected file — not
  the larger one.
- **Who authorised it.** The owner, ruling on 2026-07-29 on a request that
  named this file, this function and these literals specifically, and that
  set the same condition as the first ruling: that it hold up to audit.
- **Effect: none, and it is proved rather than asserted.** This is a
  naming-only change. The string VALUES are untouched, so a `CardScanLog`
  row written after it is byte-identical to one written before. Proof, in
  the PR: (a) the after-source, with the three constants inlined back to
  their literals and their declarations and `__all__` entries removed,
  parses to an AST identical to the before-source once docstrings are
  normalised — docstrings are the only other difference, and they are not
  executable; (b) the sequence of strings `run_fallback_for_card` can put on
  `skip_reason`, resolved statically through the module's constant table, is
  `['no-evidence', 'eliminated', 'ambiguous']` before and after; (c)
  `tests/test_local_fallback.py` asserts two of the three (`eliminated`,
  `no-evidence`) against `run_fallback_for_card`'s live output as raw string
  literals, and was deliberately **not** edited — it is an independent,
  behavioural pin that does not read the new constants at all and would fail
  if a value moved. (`ambiguous` has no such behavioural test; it is pinned
  statically instead, by `EXPECTED_SKIP_REASONS` and by the origin guard in
  `tests/test_skip_reason_roster.py`. Stated rather than glossed: the
  behavioural coverage is 2/3, and adding a third case is a test-coverage
  question outside this exception's scope, not a gap in the proof — (a) and
  (b) already cover all three at the source level.) There is no licensing
  effect of any kind: no import was added to or removed from this file, no
  external code was introduced, and the file's GPL-3.0 status and
  `PROVENANCE:`-header cleanliness are unchanged.
  `check_protected_core_license.py` passes, and `local_fallback.py` remains
  in `PROTECTED_CORE_FILES` and in §2's list above.
- **What keeps the hole closed.** The tether alone cannot; it is blind to
  both ways this can be undone. Two guards in
  `MPCAutofill/cardpicker/tests/test_skip_reason_roster.py` cover them —
  `test_local_fallback_skip_reasons_are_not_re_mirrored_elsewhere` (fails if
  any other `cardpicker` module declares one of these three values under a
  constant name not already pinned for it, and fails outright on any
  `LOCAL_FALLBACK_`-prefixed declaration outside this file) and
  `test_run_fallback_for_card_sets_no_bare_skip_reason_literal` (fails if
  `skip_reason` is set from a bare literal rather than a named module-level
  constant). A third,
  `test_local_fallback_skip_reasons_are_declared_at_their_origin`, pins the
  three name/value pairs to this file. The mirror guard is deliberately
  narrower than the `local_phash` one: `no-evidence`, `eliminated` and
  `ambiguous` are shared vocabulary that several calculators legitimately
  declare under their own prefixes, so a flat "declared nowhere else" ban
  would forbid the roster's own design. All three were mutation-checked
  against the regression each claims to catch.
- **SCOPE OF THIS EXCEPTION — read this before citing it.** It permits
  **declaring skip-reason constants in `local_fallback.py`**, and that is
  its entire reach. It is specifically NOT:
  - a general licence to edit `local_fallback.py` — every other function in
    it (the border/artist/symbol sub-checks, the three `cast_*_vote`
    helpers, `classify_bleed_edge`, `normalize_crop_box`) is untouched and
    stays untouchable without a fresh ruling;
  - a licence to edit any other protected-core file, including
    `local_phash.py` (whose own exception is likewise spent), the four
    consensus modules, the federation hash tool, or the saved-deck decrypt
    tool;
  - a precedent that the _pattern_ is now pre-authorised. Two rulings on two
    files with the same defect do not make a third automatic. **The next
    change of any shape to any file on this list needs its own ruling and
    its own entry in this log** — including the next skip-reason one.

## 3. Absorption protocol

For the day the "permitted zone" (everything outside protected core) ever
needs a capability that only exists as AGPL code elsewhere:

1. **Never blend into an existing GPL file.** A bounded, standalone
   module only.
2. **Verbatim AGPL header preserved** at the top of the vendored file,
   unmodified.
3. **A `# PROVENANCE:` comment**, naming the source repo, the exact
   commit/tag vendored from, and the license — the same shape as §1's
   own findings already use informally (`flags.tsx`'s "vendored from
   ... on <date>" comment is the closest existing precedent, now
   formalized).
4. **A ledger row** — the vendored module's own entry in whichever table
   most naturally covers it (a new row in `readiness-audit.md`'s §1
   tables if it's an extractable chunk, or a new entry in this doc's §1
   if it's infrastructure-shaped like the four §1 findings).
5. **A `NOTICE` entry** — see §4.2. The `keyrune` font vendoring (§1.4)
   is the one existing case that already did most of this by instinct
   (provenance comment + a full LICENSE.md alongside) before this
   protocol existed in writing; it's the template to match, not a
   counter-example.

**For PROTECTED CORE specifically**: the protocol above does not apply —
protected core "accepts patterns, never external code" (the convention
line now in `CLAUDE.md`). If a needed capability exists only as AGPL code
elsewhere, **reimplement from the pattern**: describe the behavior in a
doc (not copy the source), implement independently from that
description, record the clean-room decision as a ledger row here. This
is the one asymmetry between protected core and the rest of the repo —
everywhere else, bounded absorption with full attribution is permitted
with owner sign-off; inside protected core, only the pattern may cross,
never the code.

**Default posture, repo-wide, stated once rather than re-litigated per
case**: patterns (ideas, algorithms-as-described, UI approaches) may be
referenced freely from any public codebase, as they already are
elsewhere in this repo's own docs (e.g. `docs/federation/public-export-v1.md`
§6b's own careful, non-code use of `proxies-at-home`'s public integration
code as a design reference). Actual code reuse is case-by-case, requires
the absorption protocol above, and requires owner sign-off — never a
unilateral call.

## 4. Disclosure mechanics

### 4.1 README source-region — built

`docs/readme-sections.md` gained a fourth `README-REGION`
(`license-provenance`), assembled into `readme.md` by the existing
`readme` emit mode (`.github/scripts/publish_readme.py`,
`docs/proposals/proposal-i-readme-pipeline.md`) — no new machinery, the
pipeline this session shipped earlier today already does exactly this
job. Content: "GPL-3.0; complete corresponding source: this repository;
third-party-derived modules listed in `NOTICE`" per the commission's own
wording, linking to the new `NOTICE` file (§4.2). Cheap today (the
pipeline already exists); load-bearing the day any absorption actually
happens, since the statement's own truth ("third-party-derived modules
listed in NOTICE") only holds if `NOTICE` is kept current — which the
absorption protocol's own step 5 (§3) requires as part of intake, not as
an afterthought.

### 4.2 `NOTICE` file — built

New file at the repo root, `NOTICE`, consolidating proper attribution for
every §1 finding: `lipis/flag-icons` (MIT), `NightCafeStudio/react-render-if-visible`
(Apache-2.0, with the required "changes made" statement), `mattrothenberg/react-overflow-list`
(MIT), and a pointer to `MPCAutofill/cardpicker/local_pilot_data/keyrune/LICENSE.md`
for the keyrune vendoring (kept as its own file rather than duplicated,
since it's already a complete, correct, standalone license file). This is
the "one canonical place a reader can check" the README's new
license-provenance line promises, and closes §1.1/§1.2/§1.3's actual
compliance gaps (comment-only attribution → a real, complete notice).

### 4.3 Site footer source link — NOT built here, routed to the frontend lane

Per the commission's own routing instruction. This cloud session has no
direct channel to the parallel frontend-lane session (confirmed
concretely once already this session: an unrelated branding/mobile-funnel
task arrived misdirected here and had to be declined rather than
silently actioned — see this session's own history). Queued here as the
explicit, addressable deliverable a frontend-lane task description should
reference: **add a footer link, likely in `frontend/src/features/ui/Footer.tsx`,
pointing to the repo's `NOTICE` file (or the README's new
license-provenance section) — the "one-liner" the commission asked for,
GPL-3.0 attribution/source-availability, visible from every page.** Not
actioned by this change; the owner needs to either hand this to that lane
directly or re-route it back to this one.

## 5. Open items for owner review

1. §1's two incomplete-attribution findings (RenderIfVisible.tsx,
   OverflowList.tsx) are closed by the new `NOTICE` file as of this
   change — confirm that's sufficient, or whether the individual source
   files should also get their own comments expanded to quote license
   text inline (belt-and-suspenders, not required by either license).
2. §2's `models.py` gap (protected-core vote/consensus classes sharing a
   file with unrelated models, not mechanically lint-covered) — confirm
   the manual-review-item treatment is acceptable, or whether a
   per-symbol check is worth building despite the added complexity.
3. §2's correction to the commission's own "GPL-3-clean" framing (the
   hash tool is deliberately MIT, not GPL-3) — confirm the restated
   invariant ("no AGPL-derived code, whatever the file's own permissive-
   or-copyleft license is") is the intended policy.
4. §4.3 — who picks up the site footer link: the frontend lane directly,
   or does the owner want it re-routed back to this session instead?
5. Whether `readiness-audit.md`'s 41-row actual count (vs. the
   commission's 27-row estimate) changes anything about how the
   provenance column gets used going forward, or is just a number worth
   knowing.

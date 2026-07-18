# Public federation export v1

**Status: SPEC DECIDED. Spec-doc hold lifted; BUILD hold remains.**
Owner review is complete — the license decision (§5, ODbL 1.0) is made,
and this document now reflects that decision rather than presenting it
as open. Nothing in this spec has been implemented yet, and nothing
below should be read as already built. Build (management command,
signing, cron, tooling, publish) begins only when the owner separately
green-lights it, and per this program's standing split, gets routed
between this session and the server session at that point — not before.
The spec-doc itself, however, is ready to merge.

## 0. What this is, relative to `federation-v1.md`

[`../federation-v1.md`](../federation-v1.md) already specifies the
general verdict-exchange format and states ProxyPrints' v1 posture as
**publisher-only**: we emit signed verdicts, we consume none, zero
catalog-integrity risk on our side. This document is that publisher side
made concrete and buildable — a specific file format, a specific hashing
recipe, a specific publish mechanism, a specific pair of consumer
ecosystems it's actually meant to serve. Where this doc and
`federation-v1.md` disagree on a detail, this one wins for the publisher
side specifically (it's the more current, more concrete spec); the
peer-to-peer subscriber/import machinery `federation-v1.md` describes is
explicitly **not** part of this program — see §7.

**The framing shift this doc makes explicit**: `federation-v1.md`
imagines pairwise peer relationships (per-peer pinned keys, no open
enrollment). This program is different in kind — **publish-first,
no-peer-required federation**: one signed, versioned, publicly-fetchable
file anyone can consume without ever registering with us or exchanging
keys out-of-band. The peer model isn't wrong, it's just a _later_
capability (mutual, bidirectional trust) this doesn't need to wait for.
Anyone — a fork, an unrelated MIT-licensed tool, a hobbyist script — can
start consuming the moment this ships.

## 1. What's published (and the hard line)

**The hard line, stated once, applies everywhere in this doc**: **never
images. Never image URLs to third-party storage** (not our R2 bucket,
not a Google Drive link, nothing). What's published is exclusively
_conclusions about_ an image a consumer already has — keyed by a hash of
that image's content, never by a fetchable pointer to it. This isn't a
performance choice, it's the entire reason this can be publish-first
with zero catalog-integrity or takedown-liability risk: nothing this
program emits can be used to reconstruct, redistribute, or scrape
anyone's card images. A consumer must independently possess the image to
ever join against this export at all.

### Draft record shape (to critique, not final)

One JSON object per resolved verdict, newline-delimited (see §4):

```json
{
  "content_phash": "a1b2c3d4e5f60718",
  "printing": {
    "set": "znr",
    "collector_number": "135",
    "scryfall_id": "3f8e6e02-...-uuid"
  },
  "attributes": {
    "border_color": "black",
    "frame": "2015",
    "bleed": "bleed"
  },
  "basis": {
    "human_confirmed": true,
    "vote_weight": 6.5,
    "human_votes": 3
  },
  "resolved_at": "2026-07-18T00:00:00Z",
  "record_version": 1
}
```

Notes on each field, and open questions flagged inline:

- **`content_phash`** — see §2 for the exact recipe. A **hex string**
  (16 hex chars for the 64-bit hash), not the signed two's-complement
  integer `Card.content_phash` is stored as internally
  (`local_phash.py::_hash_to_int`/`_int_to_hash`) — the internal
  representation is a DB-storage optimization specific to this fork's
  Python/Postgres stack; a hex string is what `imagehash.hex_to_hash()`
  already expects on the Python side and is trivially parseable in any
  other language without 64-bit-signed-integer bit-twiddling. **Open
  question**: should this key on `CanonicalCard`-level identity instead
  (one record per printing) with `content_phash` as an _array_ of known
  hashes for that printing, rather than one record per observed image?
  Real MTG printings have multiple photographed copies in our own
  catalog already (different scan angles/lighting/generations) that
  could each independently phash-match a consumer's image for the _same_
  printing — a one-record-per-hash shape means a consumer might need to
  check several records to find their match; a one-record-per-printing
  shape with an array avoids that at the cost of a less trivial dedup
  step on our side at export time. Flagging for the owner's HOLD review,
  not resolved here.
- **`printing`** — both `set`+`collector_number` (upstream mpc-autofill
  family's own lingua franca — this is exactly what `CanonicalCard`
  already keys on, see `docs/features/local-file-source.md` and
  `printing-tags.md`) **and** `scryfall_id` (the MIT-lineage tools'
  lingua franca — confirmed live, see §6). Shipping both costs nothing
  (we already have both on every resolved `CanonicalCard`) and removes
  any need for a consumer to cross-reference Scryfall themselves just to
  join on our export.
- **`attributes`** — only the attribute _classes_ this fork actually
  resolves consensus on: `border_color`/`frame` (from
  `CanonicalPrintingMetadata`, already Scryfall-sourced, high
  confidence — arguably shouldn't even need a "verdict" since it's
  Scryfall metadata we already trust, but included for consumers whose
  own catalog doesn't have Scryfall metadata joined in), and `bleed`
  (`"bleed"` / `"trimmed"`, the `appropriate-bleed` tag's resolved
  outcome — see `docs/features/moderation.md`). Omit the key entirely
  for any attribute this specific verdict has no resolved conclusion on
  — never emit a null/unknown placeholder (matches this fork's existing
  "omit, never emit empty" convention, see `docs/features/card-dom-api.md`).
- **`basis`** — `human_confirmed` is redundant with §1's "human-confirmed
  only" gate (every record in this export is `true`, by construction —
  see below) but included anyway so a consumer never has to _trust_ that
  gate blindly; it's a self-describing, independently-checkable field on
  every record. `vote_weight`/`human_votes` are advisory context, not
  something a consumer needs to re-derive our own consensus math from.
- **`record_version`** — per-record, not just a top-level file
  `schema_version` (`federation-v1.md`'s file already has one) — lets an
  export mix record shapes across a schema transition without forcing a
  flag day, the same reasoning the upstream-readiness audit's XML 2.0
  chunk write-up applied to its own versioned format (that audit doc is
  on a sibling unmerged branch as of this writing, not yet a path this
  file can safely link to — see this doc's own note in §7).

### Human-confirmed-only in v1

**The gate is the export.** Only verdicts that cleared this fork's
existing human-backed resolution gate
(`vote_consensus.py::is_human_backed_source`, `docs/features/printing-tags.md`)
are ever published — machine suggestions (OCR/phash/deduction votes that
haven't yet been confirmed by a human vote) **stay home**, full stop, no
"confidence score" export tier for them in v1. This isn't a technical
limitation, it's a brand decision stated plainly: what a consumer gets
from this export is exactly the thing `docs/theory.md` argues this
fork's whole identification pipeline is _for_ — evidence that's been
through a human-backed consensus gate, not raw model output dressed up
as ground truth. A consumer importing this data is importing our
review's outcome, not our review's inputs.

## 2. Keying + tooling

The entire join only works if a consumer's own phash computation is
**bit-identical in method** to ours — a "close enough" reimplementation
that differs in crop region or fetch size will silently produce
different hashes and never match anything. This is the single highest-
leverage precision requirement in this whole spec.

### The exact recipe (from `MPCAutofill/cardpicker/local_phash.py`/`local_fallback.py`, current code)

**Correction, added when this recipe was actually implemented**: the
original draft of this section described only a fixed crop box and
omitted a real step our own code performs before every hash — a
faithful reimplementation needs it too, or a consumer's hashes won't
match ours for the ~2.5% of images that are trimmed rather than
bleed-inclusive (see step 1 below). Caught while building the reference
tool against `compute_content_phash_for_card`'s actual call chain, not
assumed correct from this doc's own earlier description.

1. **Classify the image as `"bleed"` or `"trimmed"`** by aspect ratio,
   before cropping anything. Compare `width / height` against two
   reference ratios derived from a standard 63×88mm MTG card trim size
   plus a 3.175mm (⅛") bleed margin per edge: `TRIM_ASPECT_RATIO = 63 / 88`, `BLEED_ASPECT_RATIO = (63 + 2×3.175) / (88 + 2×3.175)`.
   Whichever reference ratio the image's actual ratio is closer to
   wins, **unless neither is within 0.03** — then abstain (`None`):
   genuinely ambiguous, not a forced guess. ~97.5% of real card images
   are bleed-inclusive; this step exists for the ~2.5% minority that
   aren't.
2. **Crop to the art region**, as a fraction of the full image:
   `(left, top, right, bottom) = (0.07, 0.10, 0.93, 0.58)` for a
   `"bleed"` or ambiguous (`None`) image — used as-is, no remapping.
   This box is deliberately crude (a fixed fraction, not a real
   frame-aware detector) and that crudeness is a _feature_ for
   interoperability: cheap for any consumer to reimplement exactly, in
   any language, with zero MTG-frame-detection logic of their own.
   **For a `"trimmed"` image**, the same four fractions must first be
   rescaled to the trimmed image's own coordinate space (the box was
   tuned against bleed-inclusive images, so used unchanged it lands in
   the wrong place once the bleed margin's pixels no longer exist):
   `left'/right' = clamp01((left/right − wf) / (1 − 2×wf))`,
   `top'/bottom' = clamp01((top/bottom − hf) / (1 − 2×hf))`, where
   `wf = 3.175 / (63 + 2×3.175)` and `hf = 3.175 / (88 + 2×3.175)` — the
   bleed margin's fraction of the full bleed-inclusive image's
   width/height respectively, derived from the same reference geometry
   as step 1, not a separate guess.
3. **Compute `imagehash.phash`** (Python `imagehash` package,
   `hash_size=8` — the library's own default) on the cropped region.
   64 bits out.
4. **Fetch size doesn't need to match exactly** — phash's own internal
   downsample to 32×32 grayscale before its DCT means anything
   comfortably above that resolution converges to the same hash; this
   fork's own ingest pipeline uses a deliberately small fetch (140px
   tall) purely for fetch-speed reasons, not hash-accuracy ones. A
   consumer hashing their own already-downloaded, full-resolution image
   is fine and should NOT downscale first — the algorithm does that
   internally.
5. **Encode as a 16-hex-char string** — `imagehash.ImageHash`'s own
   `str()` conversion already produces exactly this; there's no need to
   reach for the internal signed two's-complement integer
   `Card.content_phash` is stored as (that's a DB-storage detail
   specific to this fork's Postgres schema, not part of the interchange
   format — see §1's field note).

### Distance semantics — empirically tuned, not textbook, and said so

**Match threshold: Hamming distance ≤ 20.** This is _not_ the commonly-
quoted "under 10" imagehash convention (that assumes well-aligned,
full-card crops; this fork's crude art-only crop needs a looser bound).
Tuned against real production distances measured 2026-07-15 across ~26
real multi-candidate cards internally: genuinely-different printings'
minimum observed distance never fell below 14, and un-normalized
reprints sharing identical official art cluster within a few points of
each other (correctly, since they _should_ often be visually
indistinguishable at this crop/hash resolution — phash alone can't
disambiguate two printings that used the same official art asset; that
disambiguation has to come from other signal, e.g. `set`/
`collector_number` metadata already present in the same export record).
**Stated honestly, not oversold**: this threshold comes from a ~26-card
internal sample, not an exhaustive validation across every printing in
the catalog — a consumer should treat "distance ≤ 20" as "worth
surfacing as a candidate," not "guaranteed correct," exactly the same
epistemic status this fork's own internal pilot treats it with (the
upstream-readiness audit's own Tier 5 entry on this same engine makes
the identical pilot-status caveat — see §7's note on that doc's
unmerged-branch status).

### Reference implementation

**Built** — `federation-hash-tool/` at the repo root, separate PR (#97),
own review, currently pending merge alongside this one. Verified
byte-for-byte identical against this fork's real backend implementation
before that PR was opened (not assumed from matching this section's
prose), and guarded going forward by a permanent CI parity test on the
backend side rather than a one-time check. Treat this section as the
interface contract that build satisfies; the tool's own `readme.md` is
the how-to-use-it docs. A single-file script (no package publish needed
for v1 — a `pip install`-able package is a nice-to-have once there's real
external usage to justify the packaging overhead, not a v1 requirement):

- **Interface**: `hash_folder(path) -> dict[filename, content_phash_hex]`
  as the core function; a CLI wrapper (`python hash_my_cards.py ./my_scans/`) that also accepts `--export-url` to fetch the current
  export and print matches directly, so "hash your folder, join against
  the export" is genuinely one command, not a two-step manual join.
- **Dependencies**: `Pillow` + `imagehash` only — both are already this
  fork's own backend dependencies (`MPCAutofill/requirements.txt`), so
  nothing new to vet license-wise; deliberately no Django/DB/network
  dependency so it runs standalone outside this fork's own stack.
- **Must implement**: exactly the bleed-classification step, crop box
  (with its trimmed-image remapping), `hash_size=8`, and hex encoding
  above — nothing else. The distance-matching/threshold logic belongs
  in the CLI wrapper's join step, not the hashing function itself
  (keep the hash function pure and trivially portable to a non-Python
  reimplementation later, since "the recipe" in this section is really
  the spec, not this particular script).
- **License**: MIT, matching `acoreyj/proxies-at-home`'s own license
  (see §6) — this tooling exists specifically to make consumption cheap
  for external MIT-licensed tools; encumbering it with a stricter
  license would work against the entire point.

## 3. Signing

**Recommend ed25519 via `minisign`**, not `ssh-keygen -Y`. Reasoning,
not a coin flip: `minisign` is purpose-built for exactly this use case
(sign a file, publish a detached signature, verify with a public key) —
its comment field and simple two-file (`.minisig` + pubkey) output are
designed for "a stranger downloads this and verifies it," where
`ssh-keygen -Y sign`/`-Y verify` is designed around SSH's own
allowed-signers-file workflow (a format most non-SSH-admin consumers
have never touched and would need explaining from scratch). Both use the
same underlying ed25519 primitive — this is a UX/discoverability choice
for external consumers, not a cryptographic one. `minisign` binaries
exist for every major OS and there's a pure-Python verifier
(`pyminisign` or equivalent) for a consumer who'd rather not shell out to
a binary.

- **Key generation**: `minisign -G` once, offline, on infrastructure the
  owner controls directly (not CI) — the private key never touches
  GitHub Actions or any repo.
- **Key publication**: the public key committed in-repo (a new
  `public-key.txt` alongside this doc, or similar — exact filename not
  worth deciding until this HOLD is actually approved) _and_ displayed
  on the site itself (About page or a dedicated `/federation` route) —
  two independent channels, so a consumer who only trusts one of
  {git history, live site} still has a
  way to cross-check the other wasn't tampered with.
- **Signing step**: each generated export file gets a detached
  `minisign -S` signature alongside it at publish time (§4's management
  command's last step).
- **Verification one-liner** (for the docs, once built):
  `minisign -Vm export-2026-07-18.jsonl -P <published-pubkey>` — exits
  non-zero on any mismatch. Document this exact command in the export's
  own README/landing page, not buried in this spec only.

## 4. Publish channel

**Recommend Cloudflare R2 over GitHub Pages**, for one concrete reason:
this repo's own image-cdn already runs on R2/Workers
(`docs/features/image-cdn.md`) — reusing that infrastructure means no
new account/billing surface, and R2's zero-egress-fee model matters here
specifically because a growing JSONL export re-fetched by an unknown
number of external consumers on an unknown cadence is exactly the kind
of traffic pattern egress fees bite hardest on. GitHub Pages (what the
frontend itself already deploys to) is the alternative, and would also
work — flagging R2 as the recommendation with reasoning, not the only
option, since either "fits our infra" per this doc's own §4 framing.

- **Format**: versioned JSONL (one JSON record per line, easy to
  `tail -f`/stream-parse in any language, no need to load a whole file
  into memory to process it incrementally) — matches this fork's own
  `human_votes`/verdict shape already, and is the de facto standard for
  exactly this kind of append-friendly dataset.
- **Full snapshot + dated increments**: `export-full.jsonl` (regenerated
  wholesale, always-current — the primary artifact most consumers want)
  plus `export-2026-07-18.jsonl`-style dated increments (records
  resolved/changed since the previous snapshot — useful for a consumer
  who wants to avoid re-downloading and re-diffing a multi-hundred-
  thousand-record file on every check). Both signed independently
  (§3) — a consumer verifying only the increment they actually fetched
  shouldn't need the full snapshot just to check a signature.
- **Regeneration**: a management command (`export_public_verdicts` or
  similar), run on a schedule via this fork's existing `django-q2`
  cron rails (`docs/infrastructure.md`'s "Startup vs. scheduled catalog
  sync" — same mechanism the daily `update_database` schedule already
  uses, not a new scheduling subsystem). Follows this fork's own
  established automation conventions rather than inventing new ones:
  - **`run_id`** — every regeneration run gets one (same pattern as
    `PilotRunLedger`/`local_identify_printing_tags`'s `run_id`,
    `docs/features/printing-tags.md`), so a bad export run is
    identifiable and revocable the same way a bad vote cohort already
    is.
  - **A ledger row per run** — timestamp, record count, file hashes,
    signature status — mirroring `PilotRunLedger`'s own shape, not a
    new concept.
  - **Dry-run default** — the command computes and reports what _would_
    publish (record count, diff size vs. last publish) without actually
    writing/signing/uploading unless passed an explicit `--publish`
    flag, matching this fork's existing "never a destructive default"
    discipline (`purge_machine_votes`, `deductive_backfill_printing_tags`
    — every management command in this area defaults to safe/inert).

## 5. License — DECIDED: ODbL 1.0

**The export data publishes under the Open Database License (ODbL)
1.0.** Distinct from the reference tooling's MIT license (§2) — those
are separate decisions about separate artifacts (code vs. data), and
only the data license was open. Decided by the owner, 2026-07-18.

### Why ODbL over CC0

Both were real options at spec-draft time. CC0 (public domain
dedication) would have maximized adoption breadth — any consumer, no
attribution or share-alike obligation, nothing requiring a downstream
user to credit ProxyPrints or contribute anything back. ODbL trades some
of that breadth for **reciprocity**, deliberately: consumers may use the
verdicts freely, but a publicly redistributed database _built on_ this
export must be shared back openly, under the same terms. The owner chose
this posture on purpose — accepting some consumer friction (a license a
casual adopter has to actually read once) in exchange for a growing,
genuinely open commons rather than a one-way data donation. For the
mpc-autofill-family consumer story (§6a), this changes nothing in
practice — sibling forks sharing improvements back is already the norm
there. For the MIT-lineage consumer story (§6b), this is the friction
the owner is knowingly accepting: `acoreyj/proxies-at-home` (MIT) or a
similar tool folding this data into its own bundled dataset needs to
think about whether that triggers share-alike for that bundled artifact.
The three clarifications below exist specifically to shrink that
friction to its real, legal size — smaller than "ODbL" sounds to someone
who's only ever worked with permissive code licenses.

### What this actually means for a consumer (true under ODbL, stated plainly)

- **(a) Using the data and displaying results in your own application
  requires only attribution — never opening your code or your app.**
  ODbL calls this a "produced work" (the output of using a database, as
  opposed to the database itself): a proxy-generation tool that reads
  this export and shows a user "this is Zendikar Rising #135" is
  producing a produced work. Produced works carry only an attribution
  requirement (see (c)), not a share-alike one. Your application's
  source code is never encumbered by this license, regardless of how
  you built it or whether it's open-source at all.
- **(b) Share-alike applies only to _publicly redistributed_ derivative
  _databases_.** If you take this export, transform or merge it into
  your own dataset, and **publish that dataset** for others to consume,
  the resulting database must be shared under ODbL too. If you use the
  data privately, internally, or only ever expose it through an
  application's produced works (see (a)), there is no share-alike
  obligation at all — internal use is completely unencumbered.
- **(c) Attribution format**: `Contains data from ProxyPrints.ca, made available under ODbL` plus a link to the export's landing page (§4).
  Any reasonably prominent placement — an about/credits page, a footer,
  a README for a redistributed dataset — satisfies it; ODbL doesn't
  mandate a specific location or format beyond "reasonably calculated to
  make the source of the Database attributable."

### A non-legal note, alongside the license

None of the above is a request — it's just what the license actually
requires, stated plainly so it reads smaller than "ODbL" sounds. Beyond
that: if you build something useful on top of this data, we'd
genuinely welcome hearing about it or getting improvements back, even in
places the license doesn't require it (a produced work, a private
internal use) — that's an invitation, not a term.

**Note on the named MIT-lineage projects**: `alex-taxiera/proxy-print`
is itself **AGPL-3.0**, not MIT (verified directly against its GitHub
license metadata for this doc, 2026-07-18 — correcting the original
framing that grouped both named projects as "MIT lineage"; see §6b).
ODbL-licensed data flowing into an AGPL-3.0 project raises its own
compatibility question neither license was written with the other in
mind for — the produced-works exception in (a) above still applies
regardless (an AGPL-licensed tool displaying results from this data is
still just producing a produced work), but a maintainer folding the
_data itself_ into their own bundled database should read (b) carefully
before assuming AGPL's own copyleft and ODbL's share-alike compose
cleanly.

## 6. Consumer stories

### (a) An mpc-autofill-fork operator imports verdicts as suggestions

A sibling fork operator (running their own mpc-autofill-family instance,
with or without this fork's own vote/consensus stack) fetches
`export-full.jsonl`, verifies its signature (§3), and for each record
whose `content_phash` matches an image already in _their_ catalog
(computed with the §2 reference tooling against their own images),
imports the verdict — **as a suggestion into their own review gate**,
never a resolution that bypasses it. This is exactly
`federation-v1.md`'s existing import-rules framing (`source='federated'`
votes, subject to the importing instance's own consensus thresholds) and
exactly why `federation-v1.md`'s "Known gate issue" section (flagged,
not yet fixed) matters before anyone actually builds import: a federated
verdict must never singlehandedly clear a human-backed gate on the
importing side, only ever contribute weight toward it. This story is
the whole reason that gate-issue fix is a real prerequisite for
_consumption_, not just a nice-to-have — but note it's **not** a
prerequisite for _this_ program (§0/§7: v1 is publish-only, no
consumption happens on our side at all).

### (b) An MIT-lineage client-side tool auto-suggests printing + bleed

A user of `acoreyj/proxies-at-home` ("Proxxied," confirmed MIT-licensed,
uses the Scryfall API for card identification — verified directly
against its README for this doc, 2026-07-18) uploads a scanned/photographed
card image to build their own proxy sheet. The tool hashes the uploaded
image with the §2 reference recipe, checks it against a locally-cached
copy of `export-full.jsonl`, and on a match within the §2 distance
threshold, auto-fills the `scryfall_id`/`set`+`collector_number` the
user's image actually depicts (rather than requiring the user to
identify it by hand) and surfaces the resolved `bleed` attribute as a
hint for that tool's own bleed-handling/normalization logic. No
ProxyPrints account, login, or API call required — the tool's maintainer
just needs to fetch a public, signed, static file and reimplement one
crop-and-hash function.

**Correction to this task's own framing, stated plainly rather than
quietly absorbed**: `alex-taxiera/proxy-print` ("Proxy Print Setup," a
tool explicitly designed to pair with MPC Autofill) is **AGPL-3.0**, not
MIT — verified against its GitHub repository's own detected license
metadata for this doc, 2026-07-18. Its public README doesn't document
its own card-identification method (no Scryfall/set-collector/hash
mention found in the fetched content), so its consumer story here is
necessarily more speculative than (b)'s `proxies-at-home` example — the
export's own `scryfall_id`/`set`+`collector_number` fields (§1) are
still the right join keys to offer it _if_ it adds printing-specific
identification later, but this doc shouldn't claim more concrete
knowledge of its internals than was actually verified. Both projects are
real, both are worth naming, but only one is actually MIT — §5's license
discussion accounts for this discrepancy rather than assuming both
consumers sit under the same permissive umbrella.

**Concrete finding, not a hypothetical (2026-07-18)**: `Akurosia/proxies-at-home`,
a public GitHub fork of `acoreyj/proxies-at-home`, is the accessible copy of
the codebase that actually powers the production `proxxied.com` deployment —
its README documents that production URL, its own backend/frontend hosting,
and states its source lives at `kclipsto/proxies-at-home`. That claimed
source repo does **not** resolve (`api.github.com/repos/kclipsto/proxies-at-home`
404s, and the `kclipsto` account's only other public repo is an unrelated
issue tracker) — so `Akurosia`'s fork, not `kclipsto`'s repo, is what was
actually readable for this finding. **License: stated MIT** (README, as of
commit `2a5826788ff7c1827b73c6042d0b4b5d1a4e8340`, 2026-02-22; `package.json`
states `"ISC"` — near-equivalent permissive) — **no `LICENSE` file present**.[^akurosia-license]
Naming it here credits the stated permissive intent while being precise
about the one real gap, rather than either asserting a confirmed MIT (which
this doc already corrected once, for `alex-taxiera/proxy-print`, and
shouldn't repeat the opposite mistake of) or omitting the project entirely
over a missing file. **Practical rule, unchanged**: the design _patterns_
this section already describes may be referenced freely, as with any public
codebase; actual code reuse from the fork's post-`acoreyj` additions waits
on either a `LICENSE` file landing or the operator's own word — the
eventual first-contact outreach (§8) can raise this directly and
constructively, not as a blocker to naming the project now. What's
confirmed by reading
its actual source (`client/src/helpers/mpcXmlExport.ts`,
`mpcAutofillApi.ts`, `importParsers.ts`): it already calls a real
MPC-Autofill-style search backend (`POST /api/mpcfill/search` and
`/batch-search`, proxied through its own server) to resolve card art by
identifier, and its XML export is a plain, attribute-free `<order>`/
`<fronts>`/`<backs>`/`<card>` dialect (`id`/`slots`/`name`/`query` as
child elements, no version attribute) — genuinely compatible with this
export's `scryfall_id`/`set`+`collector_number` join keys, independent of
the license question.

**Import-side XML dialect note, informing the PR-7 XML 2.0 provenance-attribute
design**: this tool's own XML import (`importParsers.ts`) uses the browser's
native `DOMParser`, then pulls known child elements by CSS-selector/tag-name
(`"fronts > card"`, `id`, `name`, `slots`) with no schema/whitelist
validation anywhere in the path — it does not enumerate or reject unrecognized
elements or attributes, it simply never looks for them. A future XML 2.0
export carrying optional provenance attributes or child elements (e.g. a
`provenance`/`confidence` attribute on `<card>`, per the "Tracked, not
building (XML)" note in `docs/proposals/proposal-b-bleed-normalization.md`)
would pass through this parser untouched — ignored, not rejected — meaning
PR-7 can add such fields without needing a coordinated opt-in from
downstream consumers built this way; it's a genuinely safe, additive
extension against at least this one real consumer's actual parsing code, not
just an assumption about XML's general leniency.

**One-line correction to this doc's own earlier framing**: the "production,
proprietary" characterization implicit in citing only the MIT upstream
(`acoreyj/proxies-at-home`) and treating the live `proxxied.com` deployment
as a separate, unexamined closed service is superseded by this finding — the
actual production fork is public and its integration code is readable, even
though its license status (unlike the MIT upstream it forked from) remains
genuinely unresolved rather than confidently open.

## 7. What v1 explicitly isn't

Stated plainly so nothing here gets read as more than it is:

- **No subscriber component.** This fork imports nothing from anyone in
  v1 — see `federation-v1.md`'s existing "v1 launch posture:
  PUBLISHER-ONLY." The subscriber/consumer piece stays tracked as a
  deferred, precondition-gated entry on the upstream-readiness audit's
  own extraction ladder (Tier 6 there, on a sibling unmerged branch as
  of this writing) exactly where it already sits — this program doesn't
  change that gate, it's the _publish_ half maturing while the
  _subscribe_ half stays untouched.
- **No per-peer trust configuration.** There's no peer registry, no
  pinned per-instance public key exchange, no enrollment step of any
  kind — the entire point of publish-first federation (§0) is that none
  of that machinery is a prerequisite. `federation-v1.md`'s per-peer
  key-pinning model is real and still the right design for eventual
  bidirectional federation; it's just not what this program builds.
- **No verdict ingestion, anywhere, in either direction.** Nothing this
  program builds reads a verdict _in_ — not from a peer, not from a
  consumer, not from anything. Every artifact in §§1–4 is write-only
  from this fork's perspective.

These three stay gated on real peers existing, per the existing ledger
(`federation-v1.md`'s "Known gate issue" section, and the general
publisher-before-subscriber sequencing `federation-v1.md`'s
"Participation modes" section already argues for) — not on a schedule,
not on this program shipping. Revisit when there's an actual second
instance on the other end of a real subscribe relationship, exactly the
same revisit condition the audit ladder's Tier 6 entry already states.

## 8. Future work (design intent, no build)

**Reference consumers + upstreaming intent**: two reference consumer
implementations are planned to live in this repo — a Python/Django-style
import command for the mpc-autofill family, and a TypeScript
verdict-lookup module for the `proxies-at-home` family (§6b) — written
upstream-shaped from the start: generic "import community identification
data" capabilities, standalone-useful on their own, instance-agnostic
rather than hardcoded to this fork's own catalog or API shape. The
explicit long-term goal is to contribute each to its respective upstream,
once (a) this export is actually live (nothing to consume until then) and
(b) the relationship exists — for mpc-autofill, via the existing
contribution ladder (`docs/upstreaming/`); for `proxies-at-home`, after
initial contact, since no prior relationship exists yet and §6b's own
license-ambiguity finding on the `Akurosia`/`kclipsto` fork means that
contact would need to clarify licensing before any code changes hands in
either direction. Gated accordingly in the project ledger — this is a
design note recording intent, not a build authorized by this doc.

[^akurosia-license]:
    Rationale for citing a SHA-pinned "stated MIT" rather
    than either asserting a confirmed license or omitting the project: the
    README's own words are the maintainer's clearly expressed permissive
    intent, and pinning the commit means this doc's claim can't silently
    drift if the README changes later — it's a snapshot of what was said,
    not a live claim about what's true today. `package.json`'s `"ISC"` is
    treated as near-equivalent permissive (both are short, notice-preserving
    permissive licenses) rather than a contradiction worth withholding
    attribution over. The one actual gap — no `LICENSE` file, so nothing
    here is a legally reliable grant — stays a gap, not something this
    footnote resolves; it's exactly what a future first-contact outreach
    (§8) is for.

"""
Collector-line artist recovery - reading the artist credit out of the string we ALREADY extract
successfully, instead of trying to repair the dedicated artist-crop OCR.

PROVENANCE: entirely original code, written from scratch for this repo. No patterns or source
were copied from any external project; this note exists per this repo's own house convention
(`docs/upstreaming/license-provenance.md` §3's absorption-protocol framing, applied here even
though this module imports nothing external - it sits adjacent to `modern_artist_credit.py` and
does the same shape of fuzzy-name-matching work a future auditor might reasonably wonder about
the provenance of). `local_fallback.py` (PROTECTED CORE) is neither modified nor imported here.

THE MEASURED GAP THIS CLOSES (read-only production survey, 2026-07-29 - measured, not guessed):

  - `ImageEvidence.artist_ocr_name` is BLANK on 206,719 of 220,669 rows (93.7%). The dedicated
    artist-crop OCR (`local_fallback.extract_artist_name`, an "Illus. <name>" anchor - PROTECTED
    CORE, never touched here) effectively does not fire on modern frames.
  - `ImageEvidence.collector_line_raw_text` is populated on 195,152 rows (88.4%), and the artist
    is ALREADY IN IT. Real examples, verbatim from production:
        '124/281R\\nAFR « EN %®ALESSAND'   -> Alessandra Pisano, truncated
        '204/361R\\nCLB ¢ EN LINDSEY L'    -> Lindsey Look, truncated
        '059/274R\\nDMR ¢ EN RON SPEA'     -> Ron Spears, truncated
  - So the job here is NOT a better OCR pass. It is a better READ of a string we already have.
    Zero image fetches, zero tesseract calls anywhere in this module.

WHY THIS IS A SEPARATE MODULE FROM `modern_artist_credit.py`. That module re-reads
`artist_ocr_raw_text` - a WIDE bottom-of-card band that captures whole, untruncated credit lines
plus bleeding flavor text. Its two central design choices are wrong for this input:
  1. it length-prefilters the lexicon to ±2 characters of the candidate, which structurally
     cannot match `ALESSAND` (8) against `Alessandra Pisano` (17); and
  2. it has no notion of truncation at all - a right-edge-clipped name is simply a low ratio.
The collector-line crop is NARROW and clips the artist's name at the card's right edge, so
truncation is the DOMINANT failure mode here rather than an edge case. Extending the other module
would mean bolting a second, contradictory matching mode onto it; the two are kept apart on
purpose, and neither imports the other.

HOW IT WORKS.

  1. TOKENIZE each line and take every contiguous 1..4-word window (minus windows containing a
     structural token - language codes, watermark vocabulary; see `CANDIDATE_STOPWORDS`).
  2. NORMALIZE both sides to letters/digits only, lowercased (`_normalize`). This is what makes
     the very common lost-space read work: `'VMA~+EN > MIKEBIE'` -> `mikebie`, which is an exact
     prefix of `mikebierek` ("Mike Bierek"). Comparing raw strings misses every one of these.
  3. MATCH each candidate against the `CanonicalArtist` lexicon in one of two modes:
       - FULL, when the candidate is at least as long as the lexicon entry: ordinary
         `difflib.SequenceMatcher` ratio over the whole entry (the same similarity primitive
         `local_fallback.match_artist` and `modern_artist_credit` already use - deliberately not a
         third metric).
       - TRUNCATED, when the lexicon entry is longer: ratio against the entry's PREFIX of the
         candidate's own length. This is the whole point of the module.
  4. RANK candidates by `(ratio, normalized candidate length)` - the length term is load-bearing,
     not decoration. Without it a bare first name always ties its own full name at ratio 1.0 (in
     `'> RICHARD WRIGHT'`, `RICHARD` prefix-matches eight different real "Richard ..." entries at
     1.0 and would drown out the exact `RICHARD WRIGHT` read). Longest wins the tie.

THE TRUNCATION GUARD (`line_final` + `MAX_DROPPABLE_PREFIX_LEN`) - grounded in the physical cause,
not tuned by taste. A name is truncated because the CROP CUT ITS RIGHT EDGE, so a prefix match is
only ever legitimate for a candidate that runs to the END of its line AND that is the whole
name-shaped tail of that line - the only tokens allowed to sit to its left are structural
stopwords or the 1-3 character brush-glyph garble tesseract reliably emits ("te", "be", "%®",
"Ne", "i"). Dropping a real word to manufacture a shorter prefix candidate is exactly the
false-positive this forbids: in the production row `'Kelton Vincent\\nbe DIVINE REVOCATIO!'` the
window `Vincent` is line-final and prefix-matches four real "Vincent ..." artists at 1.0, but its
left neighbour `Kelton` is a real 6-character word, so the whole name-shaped tail is
`Kelton Vincent`, not `Vincent` - rejected. FULL matches are unaffected by this guard (an
untruncated name can legitimately appear anywhere in the text).

WIDENING THE READ (2026-07-29) - THE CROP THAT CLIPS THE NAME ALREADY HAS A FULL-WIDTH TWIN, AND
IT IS ALREADY IN THE DATABASE. The truncation this module was built to survive is caused by
geometry, measured over 4,000 production rows on a 680x925 image:

    collector_line_crop_px = [41, 832, 238, 893]   -> x 6%-35% of the card's width
    legal_line_crop_px     = [0,  832, 680, 893]   -> x 0%-100%, THE SAME y BAND

`local_ocr.DEFAULT_CROP_BOX` (0.06, 0.90, 0.35, 0.965) and `local_ocr.LEGAL_LINE_CROP_BOX`
(0.0, 0.90, 1.0, 0.965) share a byte-identical vertical extent. The artist credit prints on that
same row, to the RIGHT of the set code - past 35% of the width - which is why the collector read
truncates and the legal read does not. Verbatim production pairs:

    collector 'MMQ: EN > TERESE NIE'    legal 'MMQ: EN > TERESE NIELSEN'
    collector 'IMA* EN RAYMOND!'        legal 'IMA>* EN he RAYMOND SWANLAND'
    collector 'NDP » EN > MARTINAP'     legal 'NDP » EN b> MARTINA PILCEROVA'

So the "widen the collector crop" fix requires NO geometry change, NO new tesseract call, and -
decisively - NO extractor version bump: `legal_line_raw_text` is an already-persisted field on
204,550 of 220,669 rows, extracted since issue #151. `recover_artist_from_card_text` reads BOTH
strings and keeps the better reading. Widening `DEFAULT_CROP_BOX` itself was the alternative, and
was rejected: it would change `collector_line_ocr`/`collector_line_tsv` output, forcing a bump of
both extractor versions, which invalidates every existing row against `run_image_evidence_cohort.
MANIFEST_EXTRACTOR_CURRENT_VERSIONS` and re-extracts ~220k cards - to recover pixels this
repository has already been storing all along.

TRUNCATED MATCHING IS DISABLED FOR THE LEGAL-LINE TEXT, on the same physical grounding the
truncation guard itself rests on: a prefix match is only ever legitimate where the crop CLIPS the
name's right edge, and this one runs to the full card width. Enabling it there would add a pure
false-positive surface (the legal line's right-hand tail is usually watermark prose or garble) for
a truncation that cannot physically occur.

CARD-NAME NARROWING (2026-07-29) - the second precision lever, and it is NOT circular. A card's
own NAME is source metadata already in hand; name -> artists comes from Scryfall reference data
(`CanonicalCard.artist`). Per `docs/theory.md` §10a this is a NEIGHBOURHOOD lookup scoped by a
join-key VALUE (the name), which is batchable - scoped by name VALUES, never by `card_ids`.
Measured on production: of 34,868 canonical names with at least one artist, 79.0% have exactly
ONE distinct artist and 93.1% have at most two (mean 1.40, max 176). `RON SPEA` against 2,504
lexicon entries is irreducibly ambiguous between "Ron Spears" and "Ron Spencer"; against the one
artist who illustrated a printing of *Mystic Remora* it is decisive.

It is applied as a strict INTERSECTION of the already-computed compatible set (`_score_candidate`),
never as a replacement pool, and only when that intersection is NON-EMPTY. Three properties fall
out of that shape, all of them load-bearing:
  - it can never manufacture a match the full lexicon would not have made, so no new false
    positive is reachable through it;
  - it can only ever SHRINK the compatible set - the honesty property this module is built around
    (a SET, stored only when exactly one member fits) is preserved rather than forced to one;
  - an empty intersection FALLS BACK to the unnarrowed set rather than abstaining, which is what
    keeps a decorated (`Vorpal Sword (NormalPlus Alessandra Pisano)`) or genuinely custom name -
    only 48% of uploaded names match a canonical name exactly - from silently losing artist
    recovery.
The narrowing is deliberately applied BEFORE the `MAX_COMPATIBLE` abstention, not after: a reading
that fits eight artists carries no information globally but is decisive once scoped to one card's
name, and narrowing after the cap would discard exactly that population.

Name resolution is NOT reimplemented here. `NameArtistLookup` delegates entirely to
`local_identify_printing_tags.CandidateNameIndex.candidates_for` - the codebase's existing
three-tier normaliser (`to_searchable`, filename-duplicate-suffix strip, de-concatenation
fallback) - and Stage D skips even that, reading the artists straight off the name-scoped
`list[CandidatePrinting]` it has already resolved via `_resolve_candidates_for_card`. A private
second normaliser here would put the two halves of one predicate in different name spaces - a
real hazard on its own engineering merits, and one `local-name-frequency-v1` still carries today
(it groups its eligible-card count by the raw `Card.name` while resolving candidate printings
through the normalised `to_searchable` key). A read-only backtest against this catalogue's own
confirmed matches found that calculator's structural double gate wrong on 64.9% of its checkable
outcomes (1,945/2,996 simulated firings) - see
`docs/reports/2026-08-21-name-frequency-elimination-soundness.md` for the method and its bounds.

COMPATIBLE NAMES, NOT ONE NAME - the single most important design decision here, and the reason
this module returns a SET. A truncated read is frequently, and irreducibly, compatible with more
than one real artist: `CLIFF CHIL` fits both "Cliff Childs" and "Cliff Chiang"; `DAARKEN` fits
both "Daarken" and "Daarken & Jared Blando"; `DANIEL Li` fits both "Daniel Lieske" (ratio 1.00)
and "Daniel Ljunggren" (0.875). Collapsing that to a single best guess manufactures a confident
answer the pixels do not support, and - because the consumer of this module is a CONTRADICTION
check - a wrong collapse produces a wrong contradiction, which is strictly worse than no reading
at all. So a result carries every lexicon entry within `COMPATIBLE_BAND` of the top ratio, and:

  - `is_compatible_with(artist)` - the CONTRADICTION test, true if `artist` is anywhere in that
    set. This is what gates escalation (`image_evidence`) and vote abstention
    (`local_calculate_verdicts`). It only ever answers "no" when the reading is incompatible with
    EVERY plausible interpretation.
  - `canonical_name` - the STORAGE value, and deliberately `None` unless the compatible set has
    exactly ONE member. Owner ruling, 2026-07-29: "fuzzy MATCHING is permitted, fuzzy STORAGE is
    not - resolve to the canonical artist." Every name this module ever returns is a verbatim
    `CanonicalArtist.name`, never an OCR string, and a genuinely ambiguous read stores nothing.

CANONICAL RESOLUTION FALLS OUT OF THE LEXICON, NOT A HAND-CURATED ALIAS TABLE. The owner's worked
example - "Riyou Kamei" and "Ryo Kamei" are one person and must resolve to one canonical artist -
needs no special case: the live lexicon contains only "Ryo Kamei" (verified read-only against
production, 2026-07-29 - `CanonicalArtist` holds exactly one row matching `%kamei%`), the card
prints "RIYOU KAMEI", and normalized fuzzy matching scores `riyoukamei` against `ryokamei` at
0.889 - over `MIN_RATIO_FULL_MULTI`, with no other lexicon entry close - so the recovered value
IS "Ryo Kamei". An alias table was considered and rejected: inferring "these two strings are the
same person" is precisely the confident-but-wrong judgement this module exists to avoid making,
and a curated table would have to be maintained by hand forever against a lexicon that is
re-derived from Scryfall on every sync.

THRESHOLDS - every one measured against two read-only production samples pulled 2026-07-29 (4,000
`ImageEvidence` rows with a BLANK `artist_ocr_name`, and 6,000 rows joined to the real
`CanonicalCard` their stored set+number resolves to), never guessed:
  - `MIN_RATIO_TRUNCATED` = 0.92, held higher than the full-match bar because a prefix comparison
    has strictly less material to disagree on.
  - `MIN_TRUNCATED_LETTERS` = 7 - a shorter prefix is not enough evidence for anybody. Set by the
    shortest genuine case in the sample (`ronspea`, `markted`, `mikebie` - all exactly 7).
  - `MIN_CANDIDATE_LETTERS` = 5 for any match at all. Found by a real false positive: the pure-
    noise row `'\\\\ ate ER C7 ed Ra y'` matched the real (3-character) lexicon mononym "Ray".
  - `COMPATIBLE_BAND` = 0.15 - anything within this of the top ratio is a plausible alternative
    reading. Set by the `DANIEL Li` case above (top 1.00, alternative 0.875, gap 0.125): at 0.12
    this module confidently contradicted a correct "Daniel Ljunggren" printing.
  - `MAX_COMPATIBLE` = 6 - past this the reading carries no information (`RICHARD` alone fits
    eight real artists), so it abstains entirely rather than returning a set nothing can fail.

MEASURED YIELD - read-only production, 2026-07-29, every-Nth-id deterministic samples over the
live 220,669-row `ImageEvidence` table (206,719 of them, 93.7%, still carry a BLANK
`artist_ocr_name`). "V0" is this module as first shipped - collector line only, no narrowing;
"V2" is it as it stands, with both fixes above:

  YIELD, 4,000 BLANK-artist rows                        V0        V2
    produces a reading                                39.8%     57.6%
    resolves to ONE canonical name, i.e. storable     26.1%     57.4%
  Storable names gained by V2: 1,248. Lost: 0. Changed: 0 - the two fixes are strictly additive
  over this sample, never a re-decision of a row V0 already resolved.

  CONTRADICTION, 8,000 set+number rows (4,574 resolve to a real printing)
    produces a reading                                54.9%     87.5%
    of those readings, CONTRADICT that printing        7.0%      7.2%
    of INDEPENDENTLY-CORROBORATED rows (n=4,170),
    i.e. the false-contradiction rate                 2.11%     3.02%
  "Independently corroborated" = the card's own NAME resolves to a canonical printing whose artist
  IS the artist of the printing its stored collector number resolves to - two unrelated axes
  agreeing, so a contradiction raised against one is very largely a false one. The rate rises 0.9
  points while the population that produces any reading at all rises 60%; per reading it is flat.
  Hand-inspection of the residue found most of it is not a misread artist at all but the owner's
  own already-described defect from the other end ("cards where the artist and illustration were
  accurate but the reported collector ID was incorrect") - e.g. an alternate-art proxy named
  `Verdant Catacombs (Golden Age 2 Sam Burley)` whose credit genuinely reads SAM BURLEY while its
  collector number resolves to the mainline Vance Kovacs printing.

  STORAGE PRECISION on that same corroborated cohort (n=4,170)
    fraction of the cohort a name is stored for       33.7%     88.8%
    of those stored names, correct                   95.87%    96.70%
  Coverage 2.6x, precision UP - the widened read is not trading accuracy for volume.

  COST: 4.08 -> 10.42 ms per row, single-threaded, on the production box (the legal-line read is
  the added ~6.3 ms). Stage D is not compute-bound. Stage C has ~170 ms/card of idle compute
  against a fetch-rate-limited 688 ms/card, and pays this once for the storage recovery plus once
  per lexicon-valid escalation attempt - typically ~21 ms/card, bounded at ~94 ms by the existing
  8-attempt ceiling.

JOINT / COLLABORATIVE ARTIST CREDITS (2026-07-29) - the defect this closes, and the one place
where compatibility is deliberately NOT a set-membership test. Worked example, verbatim from
production (card 679, "Weathered Wayfarer (NormalPlus Greg Hildebrandt & Tim Hildebrandt)"):

    legal_line_raw_text: '034/577 R ,\n2X2 « EN © GREG HILDEBRANDT & TIM HILDEBRAMBT2022 Proxy...'
                                                                     ^^^^^^^^^^^ garbled surname

The window `GREG HILDEBRANDT` matches the STANDALONE lexicon entry "Greg Hildebrandt" at ratio
1.00 and normalized length 15. The card's actual printing (`2x2 034`) is credited to the JOINT
entry "Greg Hildebrandt & Tim Hildebrandt", which - being 29 normalized characters against a
15-character candidate - is only reachable in TRUNCATED mode, and TRUNCATED mode is off for the
legal line (and off for any collector-line window that isn't the line's whole name-shaped tail).
So the joint entry never entered `compatible_names` and a CORRECT vote was judged contradicted.
This is not merely a measurement artefact: the same comparison drives the Stage D veto, so
`stage-d-join-key` was silently ABSTAINING (`skip_reason="artist-mismatch"`) on collaborative
credits. Truncation makes it worse, not better - the crop clips the RIGHT edge, so the second
component of a joint credit is exactly the part that gets lost, and the first component surviving
alone is the COMMON case rather than an edge case.

THE SEPARATOR VOCABULARY IS MEASURED, NOT ASSUMED (read-only census of all 2,523 `CanonicalArtist`
rows, 2026-07-29):
  - `' & '` (space-ampersand-space): 219 rows, and it is the ONLY joint-credit form present. Every
    one of the 219 has exactly TWO components (no three-way credit exists in the catalog), and the
    ampersand appears in NO other context - all 219 occurrences of the character `&` are this one.
  - `' and '`: 0 rows. `' + '`: 0. `';'`: 0. `' x '`: 0. `'|'`: 0. Dash-separated: 0.
  - `','`: 20 rows, NONE of them joint credits - they are name suffixes ("Edward P. Beard, Jr.")
    and the Unfinity age gag ("Mark Rosewater, Age 54½"). Splitting on it would produce "Jr." as
    an artist, so comma is deliberately NOT a separator here. Note the 20 include
    "Anthony S. Waters & Edward P. Beard, Jr.", a joint credit whose SECOND component itself
    contains a comma - which is exactly why the split is on `&` only and the components are used
    whole rather than re-split.
  - `'/'`: 1 row, "宋其金/Song Qijin" - a transliteration of ONE person's name into two scripts, an
    alias rather than a collaboration. Excluded on that reading; it is also inert either way,
    since neither half is a standalone lexicon entry that could be recovered.
So `JOINT_CREDIT_SEPARATOR_RE` is `&` and nothing else. If the lexicon ever grows a second form,
the census above is the thing to re-run - `_joint_credit_components` is the single place to change.

WHAT THE FIX IS, PRECISELY: `is_compatible_with(artist_name)` decomposes ITS ARGUMENT - the
printing's credit - into components and asks whether any component is in the recovered compatible
set, by EXACT normalized equality (no fuzzy ratio is introduced anywhere; the components are
compared with the same `_normalize` the direct test already uses). `compatible_names` itself is
NOT widened, and `canonical_name` is therefore byte-identical - the storage path cannot write a
name it would not have written before.

The direction is the whole safety argument, and it is ONE-WAY ON PURPOSE:
  - recovered {"Greg Hildebrandt"} vs printing "Greg Hildebrandt & Tim Hildebrandt" -> COMPATIBLE.
    The read is a truncated view of the printing's own credit, which is the physical mechanism.
  - recovered {"Greg Hildebrandt"} vs printing "Tim Hildebrandt" -> still CONTRADICTED. Two
    artists do NOT become compatible with each other merely because some joint entry names both;
    only the joint STRING is ever explained by one of its own components.
  - recovered {"Daarken & Jared Blando"} vs printing "Daarken" -> still CONTRADICTED, deliberately.
    That direction is not truncation: the card's pixels named a collaborator the printing does not
    credit, which is a real disagreement about WHICH printing this is. Measured cost of holding
    this line: 0 votes - the reverse rule was implemented and censused alongside the shipped one
    over the full 41,129-vote population and restored NOTHING the one-way rule does not, so the
    extra false-agreement surface buys literally zero and is not shipped.

WHAT IT CAN AND CANNOT DETECT, STATED PLAINLY. It can no longer distinguish "this card is credited
to X alone" from "this card is credited to X & Y and the crop ate Y" - those two readings are
genuinely identical in the surviving pixels, so a card whose credit really is the standalone X
will no longer contradict a printing credited to "X & Y". That is the exact ambiguity truncation
creates, and this module's stated rule for it is to report the SET rather than manufacture a
confident answer. Everything else is unchanged: a printing by an artist the reading has no
component-level relationship with is still contradicted, a non-joint printing artist is compared
exactly as before, and an unreadable line still produces no reading and therefore no contradiction.

MEASURED BLAST RADIUS - FULL census, not a sample: every one of the 41,129 positive
`stage-d-join-key-v1` votes, re-scored end to end against read-only production, 2026-07-29, 396 s.
(A further 16,820 `stage-d-join-key-v1` rows are `is_no_match=True` and name no printing, so there
is nothing for them to contradict; they are outside the population by construction.) 37,589 of the
41,129 produce a reading at all; the other 3,540 are unreadable and never contradict anything.

    apparent contradictions BEFORE                     1,261  (3.07% of the population)
    apparent contradictions AFTER                      1,218  (2.96%)
    removed by this fix                                   43  (3.4% of all contradictions)
    newly-created contradictions                           0  (the change only ever widens)

Because the Stage D veto fires on exactly this comparison, those 43 are also 43 CURRENTLY-
SUPPRESSED CORRECT VOTES this restores - cards on which `skip_reason="artist-mismatch"` is written
today and will not be. All 43 are the `' & '` class; no other separator appears in any of them,
which is what the census above predicts. Confirmed shapes among them: "Greg Hildebrandt" vs
"Greg Hildebrandt & Tim Hildebrandt" (the reported card 679); "Zoltan Boros" vs "Zoltan Boros &
Gabor Szikszai"; "M. W. Kaluta" vs "M. W. Kaluta & DiTerlizzi"; "Mitchell Malloy" vs "Mitchell
Malloy & Maddie Julyk"; and the ORDER-REVERSED cases "Brian Snõddy" vs "Paolo Parente & Brian
Snõddy" and "Gabor Szikszai" vs "Zoltan Boros & Gabor Szikszai", where the surviving name is the
SECOND component - which is why the test is membership over ALL components rather than a prefix
test on the first one.

THE FIX DOES NOT SWALLOW GENUINE DISAGREEMENT, MEASURED ON THE SAME POPULATION. 26 of the 1,218
surviving contradictions still involve a joint credit on one side or the other; 8 of those have a
JOINT printing artist and were hand-checked one by one - every one is a real disagreement in which
the recovered name is not a component of the joint credit at all ("Dermot Power" vs "Greg
Hildebrandt & Tim Hildebrandt", "Tobihachi" vs "Justin Hernandez & Alexis Hernandez", "Jung Park"
vs "Jana Schirmer & Johannes Voss"). They stay contradicted, correctly.

WHERE THE DEFECT CAME FROM, since it matters for who else can hit it: it is a REGRESSION OF THE
LEGAL-LINE WIDENING, not an original flaw. Re-scoring the same 41,129 votes through the pre-
widening code path (`recover_artist_from_collector_line`, collector text only, no card-name
narrowing) finds 748 contradictions and this fix changes NONE of them - zero of that path's
contradictions are this class. The reason is exactly the truncation guard: a clipped
`GREG HILDEBRAN` matches the standalone entry and the joint entry EQUALLY well in TRUNCATED mode,
so the joint entry was already in `compatible_names`. The full-width legal line supplies the whole
first component, which lands a FULL exact match on the standalone entry alone, and TRUNCATED mode
is off for that text - so widening the read is what took the joint entry out of the set. Any
future "read a wider crop" change should expect this same shape of consequence.

Pure module: every reading function takes an already-built `ArtistLexicon` and does no I/O
whatsoever. The only DB-touching functions are `load_artist_lexicon`, `build_name_artist_lookup`
and `build_printing_artist_lookup`, which the CALLER calls once per batch and threads through -
the same "built once per batch, passed through explicitly" convention
`local_calculate_verdicts.known_set_codes` already established for the set-code gate.
"""

import difflib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Optional

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from cardpicker.local_identify_printing_tags import CandidateNameIndex

# A "word" for this module's purposes. Deliberately allows a ONE-character token (unlike
# `modern_artist_credit.WORD_RE`, which requires two): the collector-line crop routinely clips a
# name mid-word, leaving a single surviving initial that is genuinely part of the read - e.g.
# 'CLB ¢ EN LINDSEY L' (Lindsey Look). Dropping that trailing "L" would cost a real character of
# evidence on exactly the rows this module exists for.
TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’.\-]*")

_NON_ALPHANUMERIC_RE = re.compile(r"[^a-z0-9]+")

# The joint/collaborative-credit separator, and the ONLY one - see the module docstring's
# separator census (read-only, all 2,523 live `CanonicalArtist` rows, 2026-07-29): 219 rows carry
# `' & '`, every one of them exactly two components, and no other joint form exists in the
# catalog at all. Comma is excluded on purpose (its 20 rows are name suffixes like "Jr." and the
# Unfinity age gag, never collaborations) and so is the single `'/'` row, which is one person's
# name transliterated into two scripts. Surrounding whitespace is flexible so a lexicon that ever
# drifts to `'A&B'` still decomposes; the ampersand itself is required.
JOINT_CREDIT_SEPARATOR_RE = re.compile(r"\s*&\s*")

MAX_CANDIDATE_WORDS = 4
# Below this many normalized characters a candidate is not evidence of anything - see the module
# docstring's "Ra y"/"Ray" false positive.
MIN_CANDIDATE_LETTERS = 5
# A TRUNCATED (prefix) comparison needs more surviving characters than a full one, since it has
# strictly less material to disagree on. 7 is the shortest genuine truncated read in the
# production sample ('ronspea', 'markted', 'mikebie').
MIN_TRUNCATED_LETTERS = 7
MIN_RATIO_TRUNCATED = 0.92
MIN_RATIO_FULL_MULTI_WORD = 0.85
MIN_RATIO_FULL_SINGLE_WORD = 0.92
# Every lexicon entry scoring within this of the best one is retained as a plausible alternative
# reading rather than discarded - see the module docstring's COMPATIBLE NAMES section.
COMPATIBLE_BAND = 0.15
MAX_COMPATIBLE = 6
# The longest token that may sit immediately left of a TRUNCATED candidate without invalidating
# it - the brush-glyph garble tesseract emits ("te", "be", "Ne", "i", "b") never runs longer.
MAX_DROPPABLE_PREFIX_LEN = 3

# Tokens that disqualify any window containing them: language markers, and the proxy/watermark
# vocabulary that shares the collector-line crop with the credit. Same role (and mostly the same
# contents) as `modern_artist_credit.CANDIDATE_STOPWORDS` - deliberately short, because the
# lexicon match is what does the real precision work, not this list. Kept as its own copy rather
# than imported: the two modules read DIFFERENT crops and their stopword sets are free to diverge
# (this one adds the collector-line-specific language markers, and the grammatical connectors the
# other module keeps in a separate set, since the narrow crop rarely carries running prose).
CANDIDATE_STOPWORDS = {
    "en", "fr", "de", "jp", "it", "pt", "es", "ru", "ko", "zh", "ja", "nl", "cn", "cs", "ct", "sp", "ph",
    "ai", "ft", "not", "for", "sale", "proxy", "proxies", "custom", "unofficial",
    "fan", "content", "card", "cards", "cardconjurer", "mpcautofill", "com",
    "mtg", "mtgx", "ndp", "playtest", "org", "organized", "play", "only",
    "casual", "use", "midjourney", "midiourney", "invalidcards",
    "unknown", "cemodens", "noxproxy", "nox", "polite", "frog", "proxycard",
    "the", "and", "with", "from", "into", "onto", "then", "when", "after", "before",
}  # fmt: skip


def _normalize(text: str) -> str:
    """Lowercase, letters/digits only. Applied to BOTH sides of every comparison - see the module
    docstring's step 2 for why (the lost-space read `MIKEBIE` -> `mikebierek` is not recoverable
    any other way, and OCR punctuation noise `«`/`¢`/`%®` disappears for free)."""
    return _NON_ALPHANUMERIC_RE.sub("", text.lower())


def _joint_credit_components(artist_name: str) -> tuple[str, ...]:
    """The individual artists named by a JOINT credit, or an EMPTY tuple when `artist_name` is not
    one (module docstring's JOINT / COLLABORATIVE ARTIST CREDITS section).

    Split on `JOINT_CREDIT_SEPARATOR_RE` only, and on the RAW string - `_normalize` erases the
    separator along with every other non-alphanumeric character, so decomposition has to happen
    before normalization or it cannot happen at all. Components are returned WHOLE and never
    re-split: the live lexicon's "Anthony S. Waters & Edward P. Beard, Jr." has a comma inside its
    second component, and treating that comma as a separator would yield "Jr." as an artist.

    A DEGENERATE split - a leading or trailing ampersand, so that only one side carries a name -
    is reported as NOT a joint credit rather than as a one-sided one: "& Foo" must not make
    everything compatible with "Foo". The emptiness test is on the STRIPPED RAW part, deliberately
    NOT on `_normalize`d text: `_normalize` keeps only `[a-z0-9]`, so the live lexicon's
    "Wesley Burt & コーヘー" has a second component that normalizes to the empty string while being
    a perfectly real collaborator. Testing the normalized form there would silently classify that
    row as non-joint and leave its half of this defect unfixed. A component that normalizes to
    nothing simply never matches anything in the compatible set, which is the correct outcome
    without needing to reject the whole credit."""
    if not artist_name or "&" not in artist_name:
        return ()
    components = tuple(part.strip() for part in JOINT_CREDIT_SEPARATOR_RE.split(artist_name))
    if sum(1 for part in components if part) < 2:
        return ()
    return components


@dataclass(frozen=True)
class ArtistLexicon:
    """Every distinct `CanonicalArtist.name`, bucketed by the FIRST normalized character for a
    cheap prefilter - built once per batch (`load_artist_lexicon`) and reused across every row.

    Deliberately NOT bucketed by length the way `modern_artist_credit.LexiconIndex` is: a
    truncated candidate is by definition much shorter than the entry it belongs to, so a length
    prefilter would reject exactly the population this module exists to serve. First-character
    bucketing costs ~100 comparisons per candidate against the live ~2.5k-name lexicon, which
    measures at ~4.6 ms/row end to end - affordable in both consumers (Stage C has ~170 ms/card of
    idle compute against a fetch-rate-limited 688 ms/card; Stage D is not compute-bound at all).

    KNOWN, ACCEPTED LIMITATION: a read whose FIRST character is garbled lands in the wrong bucket
    and is never matched. Widening to a full-lexicon scan would be ~25x the work per candidate for
    a cohort that is, by construction, the least legible one - so this abstains instead.
    """

    names: tuple[str, ...]
    _by_first_character: dict[str, tuple[tuple[str, str], ...]]

    def pool_for(self, normalized_candidate: str) -> tuple[tuple[str, str], ...]:
        if not normalized_candidate:
            return ()
        return self._by_first_character.get(normalized_candidate[0], ())


def build_artist_lexicon(names: list[str]) -> ArtistLexicon:
    by_first: dict[str, list[tuple[str, str]]] = {}
    for name in names:
        normalized = _normalize(name)
        if not normalized:
            continue
        by_first.setdefault(normalized[0], []).append((name, normalized))
    return ArtistLexicon(
        names=tuple(names),
        _by_first_character={key: tuple(values) for key, values in by_first.items()},
    )


@dataclass(frozen=True)
class RecoveredArtist:
    """One reading of the artist credit in a collector line.

    `compatible_names` is the whole point (module docstring's COMPATIBLE NAMES section): every
    `CanonicalArtist.name` the reading plausibly denotes, not a single best guess. `candidate`
    keeps the ORIGINAL-cased matched span for the audit trail; `ratio` is the winning
    `SequenceMatcher` score.
    """

    candidate: str
    ratio: float
    compatible_names: tuple[str, ...]

    @property
    def canonical_name(self) -> Optional[str]:
        """The value that may be STORED - `None` unless exactly one canonical artist is
        compatible with this reading. Owner ruling, 2026-07-29: fuzzy matching is permitted,
        fuzzy storage is not. An ambiguous read is still fully usable for `is_compatible_with`
        (which needs only to rule artists OUT), it just has no single name to write down."""
        if len(self.compatible_names) != 1:
            return None
        return self.compatible_names[0]

    def is_compatible_with(self, artist_name: str) -> bool:
        """The CONTRADICTION test. True when `artist_name` is one of the plausible readings -
        i.e. this reading does NOT contradict it. Compared on the normalized form so a lexicon
        that ever drifts in casing/punctuation ("rk post" vs "RK Post") can't manufacture a
        spurious contradiction. An empty/None-ish `artist_name` is never a contradiction: absent
        data is not evidence, the same rule `local_calculate_verdicts._apply_agreement_checks`
        already applies to every one of its own agreement checks.

        JOINT CREDITS (2026-07-29, module docstring's own section): a printing credited to
        "Greg Hildebrandt & Tim Hildebrandt" is NOT contradicted by a reading of
        "Greg Hildebrandt", because the crop clips the card's right edge and the second component
        of a joint credit is precisely what it eats. The ARGUMENT is decomposed, never
        `compatible_names`, which is what keeps this one-way: a joint credit is explained by any
        ONE OF ITS OWN components, but two artists never become compatible with EACH OTHER just
        because some joint entry somewhere names both of them. Component matching is exact
        normalized equality - no fuzzy ratio is introduced here, so a near-miss name cannot slip
        in through the joint path that could not already match directly."""
        if not artist_name:
            return True
        compatible_normalized = {_normalize(name) for name in self.compatible_names}
        if _normalize(artist_name) in compatible_normalized:
            return True
        return any(
            _normalize(component) in compatible_normalized for component in _joint_credit_components(artist_name)
        )


def _candidate_windows(tokens: list[str]) -> list[tuple[str, int, bool]]:
    """Every contiguous 1..`MAX_CANDIDATE_WORDS`-word window of one line's `tokens`, minus windows
    containing a `CANDIDATE_STOPWORDS` member. Returns `(text, word_count, truncation_eligible)`.

    `truncation_eligible` encodes the module docstring's TRUNCATION GUARD: the window must reach
    the END of the line (that is where the crop clips) AND must be the whole name-shaped tail of
    it - the only token permitted to its immediate left is a stopword or a `MAX_DROPPABLE_PREFIX_
    LEN`-or-shorter glyph-garble fragment. A window that fails this is still usable for a FULL
    match; it just may not claim to be a truncated name."""
    windows: list[tuple[str, int, bool]] = []
    total = len(tokens)
    for width in range(1, MAX_CANDIDATE_WORDS + 1):
        for start in range(0, total - width + 1):
            words = tokens[start : start + width]
            if any(word.lower().strip(".") in CANDIDATE_STOPWORDS for word in words):
                continue
            left = tokens[start - 1] if start > 0 else None
            tail_is_whole_name = (
                left is None or left.lower().strip(".") in CANDIDATE_STOPWORDS or len(left) <= MAX_DROPPABLE_PREFIX_LEN
            )
            windows.append((" ".join(words), width, (start + width == total) and tail_is_whole_name))
    return windows


def _score_candidate(
    candidate: str,
    word_count: int,
    truncation_eligible: bool,
    lexicon: ArtistLexicon,
    allowed_normalized: Optional[frozenset[str]] = None,
) -> Optional[tuple[float, tuple[str, ...], int]]:
    """Score ONE candidate window against the lexicon. Returns
    `(top_ratio, compatible_names, normalized_length)` or `None` if this candidate produces no
    trustworthy reading. See the module docstring for every threshold applied here.

    `allowed_normalized` is the CARD-NAME NARROWING (module docstring): the `_normalize`d artists
    who actually illustrated some printing of this card's own name. Applied strictly as an
    INTERSECTION of the already-computed compatible set, and only when that intersection is
    non-empty - see the module docstring for why it can only ever shrink ambiguity, never
    manufacture a match the full lexicon wouldn't have made and never abstain where the
    unnarrowed code resolves."""
    normalized_candidate = _normalize(candidate)
    if len(normalized_candidate) < MIN_CANDIDATE_LETTERS:
        return None

    scored: list[tuple[float, str]] = []
    top_ratio = 0.0
    top_floor = 1.0
    for name, normalized_name in lexicon.pool_for(normalized_candidate):
        if len(normalized_name) > len(normalized_candidate):
            # TRUNCATED mode - compare against the entry's own prefix of the candidate's length.
            if not truncation_eligible or len(normalized_candidate) < MIN_TRUNCATED_LETTERS:
                continue
            head = normalized_name[: len(normalized_candidate)]
            ratio = difflib.SequenceMatcher(None, normalized_candidate, head).ratio()
            floor = MIN_RATIO_TRUNCATED
        else:
            # FULL mode - the candidate is at least as long as the entry, nothing was clipped.
            ratio = difflib.SequenceMatcher(None, normalized_candidate, normalized_name).ratio()
            floor = MIN_RATIO_FULL_SINGLE_WORD if word_count == 1 else MIN_RATIO_FULL_MULTI_WORD
        scored.append((ratio, name))
        if ratio > top_ratio:
            top_ratio, top_floor = ratio, floor

    if not scored or top_ratio < top_floor:
        return None
    compatible = tuple(sorted(name for ratio, name in scored if ratio >= top_ratio - COMPATIBLE_BAND))
    if allowed_normalized:
        # CARD-NAME NARROWING (module docstring). Applied HERE - before `MAX_COMPATIBLE` - on
        # purpose: a reading that fits eight real artists carries no information against the full
        # lexicon and is abstained on below, but if only one of those eight ever illustrated a
        # printing of THIS card's name, the same reading is decisive. Narrowing after the cap
        # would throw that population away before it could be rescued.
        narrowed = tuple(name for name in compatible if _normalize(name) in allowed_normalized)
        if narrowed:
            compatible = narrowed
    if len(compatible) > MAX_COMPATIBLE:
        # Too many real artists fit this reading for it to mean anything (module docstring's
        # MAX_COMPATIBLE note) - abstain rather than return a set nothing could ever fail.
        return None
    return top_ratio, compatible, len(normalized_candidate)


def _normalized_allowed(allowed_artist_names: Optional[Iterable[str]]) -> Optional[frozenset[str]]:
    """The card-name-narrowed artist set, `_normalize`d for comparison against lexicon entries -
    or `None` when the caller supplied nothing (or nothing usable), which turns the narrowing off
    entirely and leaves `_score_candidate` at its full-lexicon behaviour. See the module
    docstring's CARD-NAME NARROWING section for why an EMPTY set must mean "don't narrow" rather
    than "nothing is allowed": a decorated or genuinely custom card name resolves to no canonical
    printing at all, and must not silently lose artist recovery because of it."""
    if not allowed_artist_names:
        return None
    normalized = frozenset(_normalize(name) for name in allowed_artist_names if name)
    normalized -= {""}
    return normalized or None


def _best_reading(
    raw_text: str,
    lexicon: ArtistLexicon,
    allowed_normalized: Optional[frozenset[str]],
    truncation_allowed: bool,
) -> Optional[tuple[tuple[float, int], RecoveredArtist]]:
    """Scan one text, score every candidate window of every line, and return the best reading
    together with its ranking key - or `None` when nothing clears the bars.

    Ranking is by `(ratio, normalized candidate length)`: the length tie-break is what keeps a
    bare first name from drowning out the full name it is a prefix of - see the module docstring's
    step 4 for the `RICHARD` / `RICHARD WRIGHT` case this exists for. The SAME key is what makes
    `recover_artist_from_card_text` prefer an untruncated legal-line read over the collector
    line's clipped prefix of the same name for free (`terese nielsen`, 13 characters, beats
    `terese nie`, 9, at the identical ratio 1.0).

    `truncation_allowed=False` disables TRUNCATED (prefix) matching for this text entirely, and
    is grounded in the physical cause the truncation mode exists for: a prefix match is only ever
    legitimate against a crop that CLIPS the name's right edge. See the module docstring's
    WIDENING THE READ section - `legal_line_crop_px` runs to the full card width, so nothing in
    it is clipped and a prefix match there would be a pure false-positive surface.
    """
    best_key: Optional[tuple[float, int]] = None
    best: Optional[RecoveredArtist] = None
    for line in raw_text.splitlines():
        tokens = TOKEN_RE.findall(line)
        for candidate, word_count, truncation_eligible in _candidate_windows(tokens):
            scored = _score_candidate(
                candidate, word_count, truncation_eligible and truncation_allowed, lexicon, allowed_normalized
            )
            if scored is None:
                continue
            ratio, compatible, normalized_length = scored
            key = (ratio, normalized_length)
            if best_key is None or key > best_key:
                best_key = key
                best = RecoveredArtist(candidate=candidate, ratio=ratio, compatible_names=compatible)
    if best_key is None or best is None:
        return None
    return best_key, best


def recover_artist_from_collector_line(
    raw_text: str, lexicon: ArtistLexicon, allowed_artist_names: Optional[Iterable[str]] = None
) -> Optional[RecoveredArtist]:
    """Read the artist out of ONE collector-line text: pure function, no DB or network access (the
    caller builds `lexicon` once per batch via `load_artist_lexicon` and threads it through).
    Returns the best reading, or `None` when nothing clears the bars. `None` means "no reading",
    NEVER a low-confidence best effort.

    `allowed_artist_names` (2026-07-29, module docstring's CARD-NAME NARROWING) - the artists who
    illustrated a printing of this card's own name. Optional, and `None`/empty means "don't
    narrow", so every pre-narrowing caller's behaviour is byte-identical.

    Truncation matching is ON here: this text comes from `collector_line_crop_px`, which stops at
    35% of the card's width and therefore clips the artist's name at its right edge. Prefer
    `recover_artist_from_card_text` where a `legal_line_raw_text` is also on hand.
    """
    result = _best_reading(raw_text, lexicon, _normalized_allowed(allowed_artist_names), truncation_allowed=True)
    return None if result is None else result[1]


def recover_artist_from_card_text(
    collector_line_raw_text: str,
    legal_line_raw_text: str,
    lexicon: ArtistLexicon,
    allowed_artist_names: Optional[Iterable[str]] = None,
) -> Optional[RecoveredArtist]:
    """THE PREFERRED ENTRY POINT (2026-07-29, module docstring's WIDENING THE READ section): read
    the artist out of BOTH stored reads of the card's own bottom print row, and keep whichever
    produces the better reading under the single shared ranking key.

    `legal_line_raw_text` is the SAME horizontal band as the collector line (both crops span
    y 0.90-0.965 of the card) at the FULL card width instead of the collector crop's left-hand
    6-35% window - so it holds the artist credit WHOLE where the collector line holds a clipped
    prefix of it. Truncation matching is therefore enabled for the collector text and disabled for
    the legal text; see `_best_reading`. Pure function, no I/O: both strings are already-persisted
    `ImageEvidence` fields.

    Either text may be empty (a fetch failure, a card whose legal-line extractor found nothing) -
    an empty string simply produces no reading and the other source decides on its own.
    """
    allowed_normalized = _normalized_allowed(allowed_artist_names)
    readings = [
        _best_reading(legal_line_raw_text, lexicon, allowed_normalized, truncation_allowed=False),
        _best_reading(collector_line_raw_text, lexicon, allowed_normalized, truncation_allowed=True),
    ]
    best_key: Optional[tuple[float, int]] = None
    best: Optional[RecoveredArtist] = None
    for reading in readings:
        if reading is None:
            continue
        key, recovered = reading
        # Strict `>`, with the legal-line reading scored FIRST: on an exact tie the unclipped
        # full-width read is the one that survives, since it is the better-evidenced of two
        # equally-scoring readings.
        if best_key is None or key > best_key:
            best_key, best = key, recovered
    return best


# ---------------------------------------------------------------------------------------------
# DB-touching layer. Everything above this line is pure and unit-tested against a tiny in-memory
# lexicon (test_collector_line_artist.py); the two functions below are the ONLY places this module
# talks to the database, and both are called once per BATCH by their caller, never per row.
# ---------------------------------------------------------------------------------------------


def load_artist_lexicon() -> ArtistLexicon:
    """Every distinct `CanonicalArtist.name` currently on record, as one `ArtistLexicon`. One
    query. Called once per batch by the caller (`stage_e_dispatch._run_stage_c`,
    `local_calculate_verdicts.run_join_key_calculator`), never per card."""
    from cardpicker.models import CanonicalArtist

    return build_artist_lexicon(list(CanonicalArtist.objects.values_list("name", flat=True)))


def build_name_artist_lookup() -> "NameArtistLookup":
    """A `card name -> the artists who illustrated a printing of that name` resolver for Stage C
    (module docstring's CARD-NAME NARROWING). Stage D never calls this: it has already resolved
    the card's own name-scoped `list[CandidatePrinting]` and reads the same artists straight off
    it. See `NameArtistLookup` for why this reuses `CandidateNameIndex` wholesale rather than
    building a second name index."""
    from cardpicker.local_calculate_verdicts import _get_cached_candidate_name_index

    return NameArtistLookup(_get_cached_candidate_name_index())


class NameArtistLookup:
    """Resolves an uploaded `Card.name` to the artists who illustrated a real printing of that
    name - the candidate narrowing described in the module docstring's CARD-NAME NARROWING
    section.

    NO NAME NORMALISER OF ITS OWN, DELIBERATELY. It delegates the whole raw-name -> catalog-name
    resolution to `local_identify_printing_tags.CandidateNameIndex.candidates_for`, the codebase's
    existing three-tier normaliser (`to_searchable`, then a filename-duplicate-suffix strip, then
    the de-concatenation fallback), and reads `CandidatePrinting.artist_name` off whatever that
    returns. A second, private normaliser here would be a name-space mismatch between the two
    halves of one predicate - the same class of hazard `local-name-frequency-v1` still carries
    today (see the module docstring's NAME RESOLUTION paragraph) - and is why this class contains
    no string handling at all.

    Uploader-decorated names ("Vorpal Sword (NormalPlus Alessandra Pisano)") and genuinely custom
    cards resolve to zero candidates; that is reported honestly as an EMPTY tuple, which every
    consumer reads as "don't narrow" (see `_normalized_allowed`), never as "no artist is allowed".

    Costs nothing extra in a Stage E worker that also runs Stage D: `_get_cached_candidate_name_
    index` is the single, process-cached entry point that module already documents as mandatory
    for every batch-reachable caller, so the 113k-row index is built at most once per worker
    process regardless of how many stages ask for it.
    """

    def __init__(self, index: "CandidateNameIndex") -> None:
        self._index = index

    def __call__(self, card_name: str) -> tuple[str, ...]:
        if not card_name:
            return ()
        return tuple(
            sorted(
                {candidate.artist_name for candidate in self._index.candidates_for(card_name) if candidate.artist_name}
            )
        )


def build_printing_artist_lookup() -> "PrintingArtistLookup":
    """A `(set_code, collector_number) -> artist name` resolver for Stage C, which - unlike Stage
    D - has no `CandidatePrinting` list and no already-fetched `CanonicalCard` row to read an
    artist off. See `PrintingArtistLookup` for the caching shape and why it is per-expansion."""
    return PrintingArtistLookup()


class PrintingArtistLookup:
    """Resolves a parsed `(set_code, collector_number)` pair to the artist of the printing it
    denotes, for the Stage C escalation gate.

    ONE QUERY PER EXPANSION, NOT PER CARD. A Stage C batch hammers the same handful of expansions,
    so this loads a whole expansion's `{normalized collector number: artist name}` map on first
    touch and answers every later card in that set from memory. A single MTG expansion is a few
    hundred rows; the cache is bounded at `_MAX_CACHED_EXPANSIONS` so a long-lived worker process
    walking the whole catalog can't accumulate all ~800 of them.

    Collector numbers are compared through `local_ocr._normalize_collector_number` - the SAME
    normalization `find_matching_candidates` already applies (leading zeros and case carry no
    meaning), so this resolver and Stage D's own candidate matching can never disagree about which
    printing a given parse denotes.

    Instantiated by `build_printing_artist_lookup` and threaded into `compute_card_evidence`
    explicitly, so that function keeps its "never issues its own DB query" property - the same
    shape `known_set_codes` already has.
    """

    _MAX_CACHED_EXPANSIONS = 64

    def __init__(self) -> None:
        self._by_expansion: dict[str, dict[str, str]] = {}

    def __call__(self, set_code: Optional[str], collector_number: Optional[str]) -> Optional[str]:
        if not set_code or not collector_number:
            # No set code means no globally-unique printing to resolve (the pre-M15 collector-
            # number-only case) - the same carve-out `image_evidence._parse_is_lexicon_valid` and
            # `calculate_join_key_verdict`'s own set-code gate both apply.
            return None
        from cardpicker.local_ocr import _normalize_collector_number

        expansion = self._artists_for_expansion(set_code.lower())
        return expansion.get(_normalize_collector_number(collector_number))

    def _artists_for_expansion(self, set_code: str) -> dict[str, str]:
        cached = self._by_expansion.get(set_code)
        if cached is not None:
            return cached
        from cardpicker.local_ocr import _normalize_collector_number
        from cardpicker.models import CanonicalCard

        rows = CanonicalCard.objects.filter(expansion__code__iexact=set_code).values_list(
            "collector_number", "artist__name"
        )
        loaded = {_normalize_collector_number(number): artist for number, artist in rows}
        if len(self._by_expansion) >= self._MAX_CACHED_EXPANSIONS:
            # Bounded, insertion-ordered eviction (dicts preserve insertion order) - a plain cap,
            # not an LRU: Stage C walks cards in ledger order, so expansion locality is temporal
            # and the oldest entry is also the least likely to come back.
            self._by_expansion.pop(next(iter(self._by_expansion)))
        self._by_expansion[set_code] = loaded
        return loaded


# ---------------------------------------------------------------------------------------------
# BACKFILL LAYER (2026-07-29, PR #569's own recorded open item).
#
# WHY THIS EXISTS. Everything above recovers an artist DURING a Stage C extraction, so it only
# ever reaches a card that is being re-extracted for some other reason. At the moment it landed,
# 206,719 of 220,669 `ImageEvidence` rows (93.7%) carried a blank `artist_ocr_name`, and every one
# of them would have stayed blank until something re-extracted it - a ~220k-card fetch+OCR pass
# whose whole cost buys pixels this repository has already read.
#
# It does not need those pixels. `recover_artist_from_card_text` consumes two STRINGS, and both
# are already persisted on the row: `collector_line_raw_text` (the winning collector-line OCR
# attempt) and `legal_line_raw_text` (the full-width read of the same y band). So this layer is a
# pure re-read of stored evidence: NO image fetch, NO tesseract call, NO network access of any
# kind - the same posture `modern_artist_credit.run_modern_artist_credit_backfill` already
# established for its own re-read of `artist_ocr_raw_text`, and the reason both can run against a
# 200k-row population in minutes rather than days.
#
# THE TWO INVARIANTS IT MUST NOT BREAK, both inherited rather than re-decided here:
#   * THE `Illus.` ANCHOR ALWAYS WINS (PR #563's rule). The anchor's own reading is never
#     overwritten - this fills a BLANK `artist_ocr_name` and nothing else. Enforced twice: the
#     eligibility queryset selects only `artist_ocr_name=""`, and the writer re-checks the same
#     condition on the in-memory row immediately before staging a write.
#   * FUZZY MATCHING YES, FUZZY STORAGE NO (owner ruling, 2026-07-29). The stored value is always
#     `RecoveredArtist.canonical_name`, which is a verbatim `CanonicalArtist.name` and is `None`
#     unless exactly ONE canonical artist is compatible with the reading. An ambiguous reading is
#     counted (`ambiguous`) and skipped, never resolved by picking a best guess.
# ---------------------------------------------------------------------------------------------


@dataclass
class CollectorLineArtistBackfillResult:
    """Aggregate outcome of one backfill pass, plus a capped audit sample - the same shape
    `modern_artist_credit.BackfillResult` uses, extended with the one distinction that matters
    for THIS recovery: a row can fail either because no reading cleared the bars at all
    (`no_reading`) or because a reading was found but fits more than one canonical artist
    (`ambiguous`). Collapsing the two would hide whether a disappointing yield came from
    illegible text or from a lexicon full of near-identical names, which are different problems
    with different fixes."""

    dry_run: bool = False
    run_id: str = ""
    considered: int = 0
    no_reading: int = 0
    ambiguous: int = 0
    would_fill: int = 0
    filled: int = 0
    audit: list[dict[str, Any]] = field(default_factory=list)


def backfill_eligible_evidence_queryset() -> "QuerySet[Any]":
    """Every `ImageEvidence` row this backfill may consider: (a) `artist_ocr_name` currently
    blank - the `Illus.`-anchor invariant, applied in SQL so an ineligible row is never even
    loaded; (b) at least one of the two source strings non-blank, since a row with neither has
    nothing to re-read; (c) CURRENT for its card (`content_hash` matches the card's own live
    `content_phash`), the "never trust a stale evidence row from a prior image version" rule every
    Stage C/D reader in this codebase applies; and (d) not md5-contradicted
    (`evidence_transfer.md5_currency_q`, null-tolerant by design).

    Conditions (c) and (d) are lifted verbatim from `modern_artist_credit.
    eligible_evidence_queryset` rather than restated in this module's own words - the two
    backfills re-read different stored strings off the SAME table under the same currency rule,
    and a currency rule that drifted between them would be a silent correctness bug in whichever
    one was updated second.

    `select_related("card")` is load-bearing, not an optimisation: the card-name narrowing below
    needs `evidence.card.name` on every row, and a lazy FK would turn one query into 207k.
    Ordered by pk so a run is reproducible and so an interrupted run's progress is describable.
    """
    from django.db.models import F

    from cardpicker.evidence_transfer import md5_currency_q
    from cardpicker.models import ImageEvidence

    return (
        ImageEvidence.objects.filter(artist_ocr_name="", content_hash=F("card__content_phash"))
        .exclude(collector_line_raw_text="", legal_line_raw_text="")
        .filter(md5_currency_q())
        .select_related("card")
        .order_by("pk")
    )


def run_collector_line_artist_backfill(
    run_id: str,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
    limit: Optional[int] = None,
    lexicon: Optional[ArtistLexicon] = None,
    name_artist_lookup: Optional["NameArtistLookup"] = None,
) -> CollectorLineArtistBackfillResult:
    """The batch runner. Walks `backfill_eligible_evidence_queryset()`, re-reads each row's two
    stored strings through `recover_artist_from_card_text`, and - only when `dry_run=False` -
    writes the single unambiguous canonical artist onto `ImageEvidence.artist_ocr_name`.

    `run_id`/`extractor_versions` are deliberately NOT touched on any row written here, matching
    `run_modern_artist_credit_backfill`/`reparse_collector_evidence`'s own convention: this is a
    downstream re-parse of already-extracted evidence, not a Stage C extraction pass, and stamping
    it as one would both misrepresent the row's provenance and (via `extractor_versions`) change
    what `run_image_evidence_cohort`'s resume filter believes about that card. The pass's own
    identity lives on its `PilotRunLedger` row instead - see the command wrapper.

    BOTH PER-RUN RESOLVERS ARE BUILT ONCE, HERE, AND THREADED THROUGH - never per row. `lexicon`
    is one query; `name_artist_lookup` is backed by `local_calculate_verdicts.
    _get_cached_candidate_name_index()`, the single process-cached entry point every
    batch-reachable caller in this codebase is required to use (~1.6 s / ~100 MB to build, once).
    Both are injectable so a test can drive this against a tiny in-memory lexicon.

    WRITES ARE BATCHED (`bulk_update` every `chunk_size` staged rows), not per row: the live
    population is ~207k rows, where one `UPDATE` per row is ~207k round trips for a single
    narrow column. Reads use `.iterator(chunk_size=...)` so the whole population is never
    materialised in memory at once. `filled` is incremented only after the batch it belongs to
    has actually been flushed, so a crash mid-pass can never leave the counter claiming writes
    that did not commit.

    `limit` (optional) caps how many eligible rows are CONSIDERED - the read-only measurement
    handle: a `--dry-run --limit N` pass reports the real yield on a real sample without
    committing to a full walk.
    """
    from cardpicker.models import ImageEvidence

    lexicon = lexicon or load_artist_lexicon()
    if name_artist_lookup is None:
        name_artist_lookup = build_name_artist_lookup()
    result = CollectorLineArtistBackfillResult(dry_run=dry_run, run_id=run_id)

    pending: list[Any] = []

    def _flush() -> None:
        if not pending:
            return
        ImageEvidence.objects.bulk_update(pending, ["artist_ocr_name"])
        result.filled += len(pending)
        pending.clear()

    queryset = backfill_eligible_evidence_queryset()
    if limit is not None:
        queryset = queryset[:limit]

    for evidence in queryset.iterator(chunk_size=chunk_size):
        result.considered += 1
        if evidence.artist_ocr_name:
            # Defence in depth behind the queryset's own filter - the `Illus.` anchor's reading is
            # never overwritten, and this second check makes that true of the in-memory row too.
            continue

        recovered = recover_artist_from_card_text(
            evidence.collector_line_raw_text,
            evidence.legal_line_raw_text,
            lexicon,
            allowed_artist_names=name_artist_lookup(evidence.card.name),
        )
        if recovered is None:
            result.no_reading += 1
            continue
        if recovered.canonical_name is None:
            # A real reading, but compatible with more than one canonical artist. Fuzzy matching
            # is permitted, fuzzy storage is not (owner ruling) - so this row stays blank.
            result.ambiguous += 1
            continue

        result.would_fill += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append(
                {
                    "evidence_id": evidence.pk,
                    "card_id": evidence.card_id,
                    "card_name": evidence.card.name,
                    "candidate": recovered.candidate,
                    "matched_name": recovered.canonical_name,
                    "ratio": round(recovered.ratio, 3),
                }
            )

        if not dry_run:
            evidence.artist_ocr_name = recovered.canonical_name
            pending.append(evidence)
            if len(pending) >= chunk_size:
                _flush()

    if not dry_run:
        _flush()

    return result


__all__ = [
    "TOKEN_RE",
    "MAX_CANDIDATE_WORDS",
    "MIN_CANDIDATE_LETTERS",
    "MIN_TRUNCATED_LETTERS",
    "MIN_RATIO_TRUNCATED",
    "MIN_RATIO_FULL_MULTI_WORD",
    "MIN_RATIO_FULL_SINGLE_WORD",
    "COMPATIBLE_BAND",
    "MAX_COMPATIBLE",
    "MAX_DROPPABLE_PREFIX_LEN",
    "CANDIDATE_STOPWORDS",
    "JOINT_CREDIT_SEPARATOR_RE",
    "ArtistLexicon",
    "build_artist_lexicon",
    "RecoveredArtist",
    "recover_artist_from_collector_line",
    "recover_artist_from_card_text",
    "load_artist_lexicon",
    "NameArtistLookup",
    "build_name_artist_lookup",
    "PrintingArtistLookup",
    "build_printing_artist_lookup",
    "CollectorLineArtistBackfillResult",
    "backfill_eligible_evidence_queryset",
    "run_collector_line_artist_backfill",
]

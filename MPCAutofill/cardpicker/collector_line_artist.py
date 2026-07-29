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

MEASURED YIELD on those samples (`recover_artist_from_collector_line`, thresholds as shipped):
  - 33.5% of currently-BLANK-artist rows produce a reading (21.8% of all rows resolve to a single
    canonical name and are therefore storable), against 6.3% populated today.
  - 49.5% of set+number-resolvable rows produce a reading; of those, 10.7% CONTRADICT the artist
    of the printing their own stored collector number resolves to. Hand-inspection of that
    contradicting cohort is what the owner already described from the other end: "cards where the
    artist and illustration were accurate but the reported collector ID was incorrect."
  - ~4.6 ms per row, single-threaded, on the production box.

Pure module: `recover_artist_from_collector_line` takes an already-built `ArtistLexicon` and does
no I/O whatsoever. The only DB-touching function is `load_artist_lexicon`, which the CALLER calls
once per batch and threads through - the same "built once per batch, passed through explicitly"
convention `local_calculate_verdicts.known_set_codes` already established for the set-code gate.
"""

import difflib
import re
from dataclasses import dataclass
from typing import Optional

# A "word" for this module's purposes. Deliberately allows a ONE-character token (unlike
# `modern_artist_credit.WORD_RE`, which requires two): the collector-line crop routinely clips a
# name mid-word, leaving a single surviving initial that is genuinely part of the read - e.g.
# 'CLB ¢ EN LINDSEY L' (Lindsey Look). Dropping that trailing "L" would cost a real character of
# evidence on exactly the rows this module exists for.
TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’.\-]*")

_NON_ALPHANUMERIC_RE = re.compile(r"[^a-z0-9]+")

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
        already applies to every one of its own agreement checks."""
        if not artist_name:
            return True
        normalized = _normalize(artist_name)
        return any(_normalize(name) == normalized for name in self.compatible_names)


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
    candidate: str, word_count: int, truncation_eligible: bool, lexicon: ArtistLexicon
) -> Optional[tuple[float, tuple[str, ...], int]]:
    """Score ONE candidate window against the lexicon. Returns
    `(top_ratio, compatible_names, normalized_length)` or `None` if this candidate produces no
    trustworthy reading. See the module docstring for every threshold applied here."""
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
    if len(compatible) > MAX_COMPATIBLE:
        # Too many real artists fit this reading for it to mean anything (module docstring's
        # MAX_COMPATIBLE note) - abstain rather than return a set nothing could ever fail.
        return None
    return top_ratio, compatible, len(normalized_candidate)


def recover_artist_from_collector_line(raw_text: str, lexicon: ArtistLexicon) -> Optional[RecoveredArtist]:
    """The entry point: pure function, no DB or network access (the caller builds `lexicon` once
    per batch via `load_artist_lexicon` and threads it through). Scans every line of `raw_text`,
    scores every candidate window, and returns the best reading - or `None` when nothing clears
    the bars. `None` means "no reading", NEVER a low-confidence best effort.

    Ranking is by `(ratio, normalized candidate length)`: the length tie-break is what keeps a
    bare first name from drowning out the full name it is a prefix of - see the module docstring's
    step 4 for the `RICHARD` / `RICHARD WRIGHT` case this exists for.
    """
    best_key: Optional[tuple[float, int]] = None
    best: Optional[RecoveredArtist] = None
    for line in raw_text.splitlines():
        tokens = TOKEN_RE.findall(line)
        for candidate, word_count, truncation_eligible in _candidate_windows(tokens):
            scored = _score_candidate(candidate, word_count, truncation_eligible, lexicon)
            if scored is None:
                continue
            ratio, compatible, normalized_length = scored
            key = (ratio, normalized_length)
            if best_key is None or key > best_key:
                best_key = key
                best = RecoveredArtist(candidate=candidate, ratio=ratio, compatible_names=compatible)
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
    "ArtistLexicon",
    "build_artist_lexicon",
    "RecoveredArtist",
    "recover_artist_from_collector_line",
    "load_artist_lexicon",
    "PrintingArtistLookup",
    "build_printing_artist_lookup",
]

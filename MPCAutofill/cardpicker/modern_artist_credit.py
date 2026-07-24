"""
Modern (bare-name) artist-credit recognizer - issue #368.

PROVENANCE: entirely original code, written from scratch for this repo. No patterns or source
were copied from any external project; this note exists per this repo's own house convention
(`docs/upstreaming/license-provenance.md` SS3's absorption-protocol framing, applied here even
though this module doesn't import anything external - it sits directly adjacent to
`artist_consensus.py` (PROTECTED CORE) and does the kind of fuzzy-name-matching work a future
auditor might reasonably wonder about the provenance of).

THE GAP THIS CLOSES. `ImageEvidence.artist_ocr_raw_text` is already captured for ~215k cards
(~98.5% of evidence rows) by the existing Stage C OCR-group extractor
(`cardpicker.image_evidence`, `local_ocr`/`local_fallback.extract_artist_name`), but
`artist_ocr_name` - the PARSED name - is populated for only ~13.6k of them. The reason: the
existing extractor (`local_fallback.extract_artist_name`, PROTECTED CORE - never modified here)
anchors ONLY on an "Illus. <name>" credit line, the old-border convention. Modern frames instead
print a bare name (often beside a small brush-glyph icon that tesseract reliably mangles into 1-4
junk characters) next to the set code/language code/collector number - a completely different
shape the "Illus." anchor was never meant to catch, and this module intentionally does NOT try to
extend or patch that regex (PROTECTED CORE accepts patterns from outside code, never edits -
`docs/upstreaming/license-provenance.md` SS2; the same principle applies to a fork's own new code
touching it). Instead, this is a wholly independent, parse-only re-reader of the SAME already-
stored `artist_ocr_raw_text` strings: given a raw OCR string, try to recover a real artist name
from it via fuzzy matching against the known-artist lexicon (every `CanonicalArtist.name`, ~2.5k
distinct strings, itself sourced from the canonical Scryfall-derived registry, never scraped or
invented here). NO image fetch, NO OCR call, anywhere in this module - see
`cardpicker.management.commands.backfill_modern_artist_names` for the read-only batch runner
built on top of it.

DOWNSTREAM: NOTHING NEW IS WIRED HERE, ON PURPOSE. `ImageEvidence.artist_ocr_name` already has a
production consumer - `local_calculate_verdicts.calculate_join_key_verdict`'s "ARTIST-OCR
CORROBORATION" step reads it directly (`if evidence.artist_ocr_name and canonical is not None:
... match_artist(evidence.artist_ocr_name, ...)`) to narrow/corroborate printing identification,
and `local_identify_printing_tags` consults it the same way for the live pilot path. This module
only ever fills a previously-BLANK `artist_ocr_name` (`cardpicker.management.commands.
backfill_modern_artist_names`'s own no-overwrite guarantee) - every name it writes flows into
that existing consumer automatically, the next time the join-key calculator runs over the
affected cards. Nothing downstream needed to change for this to take effect.

WHY LEXICON-VALIDATION IS THE SAFETY NET, NOT THE EXTRACTION REGEX. A modern credit line's shape
varies enormously in OCR output - the brush glyph reads as anything from "%©" to "te" to "Ne" to
a stray real English/French word; the name itself can be ALL CAPS, Title Case, missing its
spaces entirely ("MARKTEDIN"), or missing a character or two to genuine OCR noise (the Kalk
Kopinski case card #83867 - "Kalk Kopinski" for the real "Karl Kopinski", edit-distance 2 on a
13-character string). No fixed regex reliably isolates "the name" from that variety. So instead
this module extracts every SHORT (<=4 word) token-window per line as a name CANDIDATE, and lets a
tolerant fuzzy match against the real, closed lexicon of actually-existing artist names be the
precision gate - a candidate that doesn't resemble any real artist closely enough, with a clear
margin over the next-best lexicon entry, is simply never accepted. "A wrong artist name is worse
than none" (task directive) drives every threshold below toward the conservative side.

TWO CONCRETE FALSE-POSITIVE GUARDS, EACH FOUND BY SAMPLING REAL PRODUCTION ROWS, NOT ASSUMED:

  1. MARGIN OVER RUNNER-UP (MIN_MATCH_MARGIN). Fuzzy-matching a short candidate against ~2.5k
     names risks a coincidental near-tie between two real (but different) artists. Requiring the
     best match to clear the SECOND-best by a real margin, not just an absolute ratio floor,
     mirrors this codebase's own established convention for exactly this shape of risk (compare
     `local_fallback.SYMBOL_MARGIN`).

  2. THE RUNNING-PROSE NEIGHBOUR GUARD (`_looks_like_running_prose_neighbour`). Because
     `artist_ocr_raw_text` is OCR'd from a wide bottom-of-card crop band (`local_fallback.
     ARTIST_CROP_BOX`), it often also contains a trailing fragment of rules/flavor text bleeding
     up from above the credit line, not just the credit line itself. Sampling production rows
     surfaced a genuine false positive from this: card evidence id 517's raw text was
     "...ensuite, plus rien.\nU 0663\nCMM . FR > JESPER EISING...\n" - ordinary French flavor
     text ("...then, nothing more.") sits on its own line, and "rien." (French for "nothing")
     happens to ALSO be a real (if obscure) artist's literal stage name in the lexicon, so a
     naive best-fuzzy-match-anywhere-in-the-text approach would confidently return "Rien." and
     silently miss the REAL credit ("Jesper Ejsing") one line below. The fix: a candidate whose
     immediately preceding token is a genuine closed-class grammatical connector word (`plus`,
     `and`, `the`, `avec`, ...) is rejected outright - a real credit-line's glyph-icon-turned-
     junk prefix is essentially never one of these words (verified: this rejects zero of the
     true positives found across two independent samples, ~6.5k rows total, while fixing this
     one false positive - see `test_modern_artist_credit.py`'s
     `test_running_prose_neighbour_rejected_not_a_false_positive` for the exact fixture).

THRESHOLDS (tuned empirically against two independent samples pulled read-only from production -
a 4,000-row sequential-id sample and a 2,500-row uniform-random sample, ~6,500 rows total, before
this module was finalized - not guessed):
  - `MIN_RATIO_MULTI_WORD` = 0.85 (a >=2-word candidate matched against its lexicon counterpart)
  - `MIN_RATIO_SINGLE_WORD` = 0.92 (a lone mononym - held to a stricter bar: a 1-word candidate
    has far less material to disagree on, so an accidental high-ratio collision with an unrelated
    short lexicon mononym is comparatively more likely)
  - `MIN_MATCH_MARGIN` = 0.06 (best ratio must clear the runner-up by at least this much)
  - `MIN_SINGLE_WORD_CANDIDATE_LENGTH` = 5 (a single-token candidate under 5 characters is
    rejected outright regardless of ratio - see the "Seta"/"SETTA" false-positive this guards
    against, found and fixed during tuning: a 4-character token has enough OCR-noise candidates
    floating around a busy crop that even a high ratio isn't trustworthy on its own)
  - candidate windows are capped at 4 words (`MAX_CANDIDATE_WORDS`) - real `CanonicalArtist`
    names are almost always 1-3 words (a bare sweep of the lexicon: 318 one-word, 1,820 two-word,
    134 three-word, only 21 four-word entries, out of 2,523 total, `&`-joined collaborations
    aside), so a wider window only invites more noise for no real recall gain.

WHAT THIS MODULE DELIBERATELY DOES NOT TRY TO DO: match `&`-joined collaboration credits (e.g.
"Zoltan Boros & Gabor Szikszai") as a single unit - OCR reliably drops or mangles the ampersand,
and guessing at a collaborator pairing from a half-visible name is exactly the kind of confident-
but-wrong outcome this module is built to avoid. A collaboration credit simply goes unmatched
(same conservative outcome as any other genuinely unrecoverable case) unless the lexicon
separately lists one of the collaborators under their own solo credit string too, in which case
ordinary lexicon matching picks that up on its own merits, unassisted.

Pure, DB-touching-only-to-load-the-lexicon module: `recognize_artist_credit` itself takes an
already-built `LexiconIndex` and does no I/O - see `test_modern_artist_credit.py` for how the
unit tests exercise it against a small in-memory lexicon rather than the real one.
"""

import difflib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from django.db.models import QuerySet

WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'.\-]{1,30}")

MAX_CANDIDATE_WORDS = 4
MIN_RATIO_MULTI_WORD = 0.85
MIN_RATIO_SINGLE_WORD = 0.92
MIN_MATCH_MARGIN = 0.06
MIN_SINGLE_WORD_CANDIDATE_LENGTH = 5
# lexicon prefilter window: only lexicon entries within this many characters of a candidate's own
# length are ever compared against it (see LexiconIndex) - a cheap, generous bound (real OCR
# garble essentially never changes a name's length by more than a couple of characters) that
# keeps this module fast enough to run over the full ~200k-row backlog in one pass.
LENGTH_PREFILTER_WINDOW = 2

# Tokens that, if found ANYWHERE inside a candidate window, disqualify that whole window - set/
# language codes, rarity-adjacent tokens, and the proxy/AI-generator watermark vocabulary
# observed directly in sampled raw text (module docstring). Deliberately conservative/short:
# this list only needs to keep obvious non-name tokens out of a candidate window, NOT do the
# real precision work - the lexicon fuzzy-match below is what actually decides whether a
# candidate is trustworthy.
CANDIDATE_STOPWORDS = {
    "en", "fr", "de", "jp", "it", "pt", "es", "ru", "ko", "zh", "ja", "nl", "cn",
    "ai", "ft", "not", "for", "sale", "proxy", "proxies", "custom", "unofficial",
    "fan", "content", "card", "cards", "cardconjurer", "mpcautofill", "com",
    "mtg", "mtgx", "ndp", "playtest", "org", "organized", "play", "only",
    "casual", "use", "midjourney", "midiourney", "invalidcards",
    "unknown", "cemodens", "noxproxy", "nox", "polite", "frog", "proxycard",
}  # fmt: skip

# See the module docstring's "running-prose neighbour guard" section. Deliberately a small,
# closed class of unambiguous grammatical connector words across the languages this catalog
# actually sees (English/French/German/Spanish/Portuguese flavor text) - NOT a general
# "any lowercase word" test, which was tried during tuning and rejected many genuine glyph-
# garble neighbours (e.g. "for"/"sale"/"aoe"/"woe" - all real lowercase strings that happen to
# sit right before a genuine credit name in sampled raw text).
RUNNING_PROSE_FUNCTION_WORDS = {
    "the", "and", "with", "from", "into", "onto", "then", "when", "after", "before",
    "while", "plus", "avec", "dans", "pour", "mais", "chez", "vers", "sans", "depuis",
    "und", "aber", "pero", "also",
}  # fmt: skip


def _looks_like_running_prose_neighbour(token: str) -> bool:
    return token.lower() in RUNNING_PROSE_FUNCTION_WORDS


def _tokens_of(line: str) -> list[str]:
    return [m.group(0) for m in WORD_RE.finditer(line)]


def _candidate_windows(tokens: list[str]) -> list[tuple[str, int]]:
    """Every contiguous 1..MAX_CANDIDATE_WORDS-word window of `tokens`, minus windows containing
    a stopword or immediately preceded by a running-prose function word. Returns
    (candidate_text, word_count) pairs; `candidate_text` preserves the ORIGINAL casing (matching
    is always done case-insensitively, but the caller may want the original for its audit trail).
    """
    out: list[tuple[str, int]] = []
    for width in range(1, MAX_CANDIDATE_WORDS + 1):
        for i in range(0, len(tokens) - width + 1):
            words = tokens[i : i + width]
            if any(word.lower().strip(".") in CANDIDATE_STOPWORDS for word in words):
                continue
            if i > 0 and _looks_like_running_prose_neighbour(tokens[i - 1]):
                continue
            candidate = " ".join(words)
            if len(candidate) < 3:
                continue
            out.append((candidate, width))
    return out


@dataclass(frozen=True)
class LexiconIndex:
    """A `CanonicalArtist.name` lookup, bucketed by (first letter, length) for a cheap prefilter
    - built once per command invocation (`build_lexicon_index`) and reused across every row, not
    rebuilt per candidate. `entries` is retained for iteration/debugging; `_by_bucket` is the
    actual hot-path lookup table `pool_for` uses."""

    entries: tuple[str, ...]
    _by_bucket: dict[tuple[str, int], tuple[tuple[str, str], ...]]

    def pool_for(self, candidate_lower: str) -> tuple[tuple[str, str], ...]:
        if not candidate_lower:
            return ()
        first = candidate_lower[0]
        n = len(candidate_lower)
        out: list[tuple[str, str]] = []
        for length in range(max(1, n - LENGTH_PREFILTER_WINDOW), n + LENGTH_PREFILTER_WINDOW + 1):
            out.extend(self._by_bucket.get((first, length), ()))
        return tuple(out)


def build_lexicon_index(names: list[str]) -> LexiconIndex:
    by_bucket: dict[tuple[str, int], list[tuple[str, str]]] = {}
    for name in names:
        lowered = name.lower()
        if not lowered:
            continue
        key = (lowered[0], len(lowered))
        by_bucket.setdefault(key, []).append((name, lowered))
    return LexiconIndex(entries=tuple(names), _by_bucket={key: tuple(values) for key, values in by_bucket.items()})


def _best_lexicon_match(candidate: str, pool: tuple[tuple[str, str], ...]) -> tuple[float, Optional[str], float]:
    """Best (ratio, name) and the runner-up ratio within `pool`, via `difflib.SequenceMatcher` -
    the same character-similarity technique `local_fallback.match_artist` already uses for its
    own (narrower, candidate-scoped) artist fuzzy-match, kept consistent rather than introducing
    a second similarity metric into the codebase."""
    candidate_lower = candidate.lower()
    best_ratio, best_name, runner_up_ratio = 0.0, None, 0.0
    for original, lowered in pool:
        ratio = difflib.SequenceMatcher(None, candidate_lower, lowered).ratio()
        if ratio > best_ratio:
            runner_up_ratio = best_ratio
            best_ratio, best_name = ratio, original
        elif ratio > runner_up_ratio:
            runner_up_ratio = ratio
    return best_ratio, best_name, runner_up_ratio


@dataclass(frozen=True)
class RecognizedArtist:
    """One confident recognition - the winning candidate span, the lexicon name it matched, and
    the ratio/runner-up-ratio/word-count that justified accepting it (kept for the management
    command's audit-sample output, not just the bare name)."""

    candidate: str
    matched_name: str
    ratio: float
    runner_up_ratio: float
    word_count: int


def recognize_artist_credit(raw_text: str, lexicon: LexiconIndex) -> Optional[RecognizedArtist]:
    """The recognizer entry point: pure function, no DB/network access (the caller loads
    `lexicon` once via `build_lexicon_index` and passes it in). Scans every line of `raw_text`,
    tries every candidate window per line, and returns the SINGLE highest-ratio accepted match
    across the whole text - or `None` if nothing clears both the ratio floor and the margin-over-
    runner-up bar for its word count (module docstring's THRESHOLDS section). Never guesses:
    absence of a result here means "leave `artist_ocr_name` blank," never a low-confidence best
    effort.
    """
    best: Optional[RecognizedArtist] = None
    for line in raw_text.splitlines():
        tokens = _tokens_of(line)
        for candidate, word_count in _candidate_windows(tokens):
            pool = lexicon.pool_for(candidate.lower())
            if not pool:
                continue
            ratio, matched_name, runner_up_ratio = _best_lexicon_match(candidate, pool)
            if matched_name is None:
                continue
            min_ratio = MIN_RATIO_SINGLE_WORD if word_count == 1 else MIN_RATIO_MULTI_WORD
            if ratio < min_ratio:
                continue
            if (ratio - runner_up_ratio) < MIN_MATCH_MARGIN:
                continue
            if word_count == 1 and len(candidate) < MIN_SINGLE_WORD_CANDIDATE_LENGTH:
                continue
            if best is None or ratio > best.ratio:
                best = RecognizedArtist(
                    candidate=candidate,
                    matched_name=matched_name,
                    ratio=ratio,
                    runner_up_ratio=runner_up_ratio,
                    word_count=word_count,
                )
    return best


# ---------------------------------------------------------------------------------------------
# DB-touching layer: loading the real lexicon and the read-mostly batch runner. Everything above
# this line is pure and unit-tested against a tiny in-memory lexicon
# (test_modern_artist_credit.py); everything below is exercised by
# test_backfill_modern_artist_names.py against the real ORM (pytest-django's ephemeral test DB,
# never production - see that test module's own docstring).
# ---------------------------------------------------------------------------------------------


def load_lexicon_index() -> LexiconIndex:
    """Every distinct `CanonicalArtist.name` currently on record, as a fresh `LexiconIndex` - one
    query, called once per command invocation (never per-row) by the caller below."""
    from cardpicker.models import CanonicalArtist

    names = list(CanonicalArtist.objects.values_list("name", flat=True))
    return build_lexicon_index(names)


def eligible_evidence_queryset() -> "QuerySet[Any]":
    """Every `ImageEvidence` row that (a) already carries a non-blank `artist_ocr_raw_text` (b)
    has a currently-blank `artist_ocr_name` and (c) is the CURRENT evidence row for its card -
    `content_hash` matches the card's own live `content_phash`, the same "never trust a stale
    evidence row from a prior image version" convention every other Stage C/D reader in this
    codebase follows (e.g. `local_detect_ai_art._eligible_cards_queryset`,
    `reparse_collector_evidence._current_evidence_for_card`). A card with no `content_phash` yet
    (no stable hash to key a CURRENT lookup against) is excluded by the join returning no match,
    the same outcome those other readers reach via an explicit `if card.content_phash is None`
    skip.
    """
    from django.db.models import F

    from cardpicker.models import ImageEvidence

    return (
        ImageEvidence.objects.exclude(artist_ocr_raw_text="")
        .filter(artist_ocr_name="", content_hash=F("card__content_phash"))
        .select_related("card")
    )


@dataclass
class BackfillResult:
    dry_run: bool = False
    run_id: str = ""
    considered: int = 0
    would_fill: int = 0
    filled: int = 0
    no_match: int = 0
    # capped audit sample, matching AiArtDetectorResult/JoinKeyCalculatorResult's own "up to N,
    # for the report" convention elsewhere in this codebase.
    audit: list[dict[str, Any]] = field(default_factory=list)


def run_modern_artist_credit_backfill(
    run_id: str,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
    lexicon: Optional[LexiconIndex] = None,
) -> BackfillResult:
    """The batch runner (module docstring). Reads `eligible_evidence_queryset()`, tries
    `recognize_artist_credit` against each row's `artist_ocr_raw_text`, and - only when
    `dry_run=False` - writes the matched name straight onto `ImageEvidence.artist_ocr_name`
    (`evidence.save(update_fields=["artist_ocr_name"])`, matching `reparse_collector_evidence`'s
    own single-field-save convention; `run_id`/`extractor_versions` are deliberately left
    untouched - this is a downstream re-parse of already-extracted evidence, not a Stage C
    extraction pass, so it must not misrepresent itself as one in either field).

    NEVER OVERWRITES: `eligible_evidence_queryset()` only selects rows with a currently-blank
    `artist_ocr_name` in the first place, and the write below re-checks `if evidence.
    artist_ocr_name: continue` immediately before saving as a second, defence-in-depth guard
    against a same-row double-count within one run (the queryset is evaluated once via
    `.iterator()`, so this only matters if a row were somehow visited twice - it costs nothing
    and removes any doubt).

    NO IMAGE FETCH, NO OCR: every input is already-persisted `ImageEvidence.artist_ocr_raw_text`;
    this function performs zero `image_cdn_fetch`/`local_ocr` calls.
    """
    lexicon = lexicon or load_lexicon_index()
    result = BackfillResult(dry_run=dry_run, run_id=run_id)

    for evidence in eligible_evidence_queryset().iterator(chunk_size=chunk_size):
        result.considered += 1
        if evidence.artist_ocr_name:
            continue  # defence-in-depth, see docstring - should be unreachable given the queryset

        recognized = recognize_artist_credit(evidence.artist_ocr_raw_text, lexicon)
        if recognized is None:
            result.no_match += 1
            continue

        result.would_fill += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append(
                {
                    "evidence_id": evidence.pk,
                    "card_id": evidence.card_id,
                    "candidate": recognized.candidate,
                    "matched_name": recognized.matched_name,
                    "ratio": round(recognized.ratio, 3),
                    "margin": round(recognized.ratio - recognized.runner_up_ratio, 3),
                }
            )

        if not dry_run:
            evidence.artist_ocr_name = recognized.matched_name
            evidence.save(update_fields=["artist_ocr_name"])
            result.filled += 1

    return result


__all__ = [
    "WORD_RE",
    "MAX_CANDIDATE_WORDS",
    "MIN_RATIO_MULTI_WORD",
    "MIN_RATIO_SINGLE_WORD",
    "MIN_MATCH_MARGIN",
    "MIN_SINGLE_WORD_CANDIDATE_LENGTH",
    "LENGTH_PREFILTER_WINDOW",
    "CANDIDATE_STOPWORDS",
    "RUNNING_PROSE_FUNCTION_WORDS",
    "LexiconIndex",
    "build_lexicon_index",
    "RecognizedArtist",
    "recognize_artist_credit",
    "load_lexicon_index",
    "eligible_evidence_queryset",
    "BackfillResult",
    "run_modern_artist_credit_backfill",
]

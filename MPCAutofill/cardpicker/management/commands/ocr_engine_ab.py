"""
Read-only real-image A/B validation tool for the OCR engine seam (issue #423, cardpicker/
local_ocr.py's own module docstring). Fetches a bounded sample of real card images TRANSIENTLY
(the same fetch helper and shared rate-limiter every other pilot command uses -
`image_cdn_fetch.fetch_card_image_bytes`, paced via `harvest_fetch_limiter.GOOGLE_IMAGE` - see
that module's own docstring) and runs the SAME preprocessing through both OCR engines
(`local_ocr.run_tesseract_text_and_words`, dispatched via `django.test.override_settings` so this
command dogfoods the exact same seam production code would use, not a parallel implementation of
its own) - never persists a single pixel, matching CLAUDE.md's "Governing premise: we index, we
do not store images". This is the tool #423's spike comment says any GO decision on flipping
`OCR_ENGINE` is gated on; running it does not itself flip anything (see local_ocr.py's own
docstring for why the flip is deliberately deferred to issue #480's combined whole-catalog pass).

SCOPE REDUCTION vs `run_image_evidence_cohort.py` (deliberate, read this before reusing this
command's shape for something bigger): that command's own two-stage windowed fetch/compute
pipeline exists to protect a 200k-card UNATTENDED production harvest from the exact
parent-process memory blowup its own module docstring documents two real incidents of. This
command is bounded to `--sample` (default 200) images, run interactively, so that architecture
would be pure overhead here - fetches run on a plain `ThreadPoolExecutor` (still paced by the
same shared `GOOGLE_IMAGE` limiter every fetch call already goes through, regardless of caller
concurrency), and the OCR/compare step for each result runs sequentially in the main thread
afterwards (CPU-bound, not worth parallelizing at this scale). Do not copy this command's fetch
shape for a full-catalog-sized run - see `run_image_evidence_cohort.py`'s own module docstring for
why that one earns its complexity and this one doesn't need it.

ONE PREPROCESSING VARIANT PER IMAGE (deliberate, narrower than the real Stage C
`collector_line_ocr` extractor's own multi-tier escalation in `image_evidence.py`): this command
measures `local_ocr.preprocess_variants(...)[0]` (the primary, dark-text-on-light polarity) only -
matching the instruction's own "per-image" granularity literally, and matching the 2026-07-25
spike's own methodology (which also tested a bounded polarity-variant set, not the full escalation
ladder). The full multi-tier escalation this deliberately does NOT replicate is `image_evidence.
py`'s own concern, not this validation tool's - reproducing it here would make this command a
second, drifting implementation of that extractor rather than a validator OF it.

SAMPLING: drawn from cards that already carry a `collector_line_ocr` `ImageEvidence` row (i.e.
`extractor_versions` contains that key) - this is what makes the third "stored-vs-fresh agreement"
column possible (comparing a fresh pytesseract-engine read, right now, against what the real
Stage C pipeline stored for that same card the last time it ran) - a real, useful signal on its
own: a large stored-vs-fresh DISAGREEMENT rate would mean something in the pipeline (crop box,
preprocessing, or the fetched image itself) has drifted since that evidence was written, entirely
independent of which OCR engine either read used. `--seed` makes the sample reproducible across
repeated runs (e.g. re-running after a code change, to see whether the same sample's agreement
rates moved) - the effective seed is always echoed to stdout (and recorded on this run's own
ledger row) so an unseeded run's own sample is still identifiable after the fact.

LEDGER: standard `PilotRunLedger` self-recording convention (`cardpicker.pilot_run_lifecycle`),
but `dry_run=True` UNCONDITIONALLY - this command has no write mode at all (no CLI flag toggles
that), so every row it ever creates records the same "this run wrote nothing" fact the dry_run
column already exists to carry elsewhere. No `enforce_dry_run_precondition` call - that guard
exists to gate WRITE commands behind a matching prior dry-run; a command that can never write has
nothing for that guard to gate.
"""

import contextlib
import logging
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Iterator, Optional

from django.core.management.base import BaseCommand, CommandParser
from django.test import override_settings
from django.utils import timezone

from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.image_cdn_fetch import DEFAULT_FETCH_DPI, fetch_card_image_bytes
from cardpicker.image_evidence import _parse_is_lexicon_valid
from cardpicker.local_calculate_verdicts import (
    _get_cached_candidate_name_index,
    _resolve_candidates_for_card,
    known_set_codes,
)
from cardpicker.local_ocr import (
    DEFAULT_CROP_BOX,
    OCR_ENGINE_PYTESSERACT,
    OCR_ENGINE_TESSEROCR,
    TESSERACT_CONFIG,
    OcrParseResult,
    crop_collector_line,
    parse_collector_line,
    preprocess_variants,
    run_tesseract_text_and_words,
    validate_against_candidates,
)
from cardpicker.models import Card, ImageEvidence, PilotRunLedger
from cardpicker.pilot_run_lifecycle import (
    initial_counters,
    mark_ledger_failed,
    merge_counters,
    resilient_terminal_output,
    scope_hash,
)
from cardpicker.utils import get_baked_git_sha

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE = 200
# A little above GOOGLE_IMAGE's own max_concurrency=6 (matching run_image_evidence_cohort.py's
# own DEFAULT_FETCH_THREADS sizing rationale) - the limiter's own semaphore is the real
# concurrency ceiling regardless of thread count.
FETCH_THREADS = 8
PROGRESS_EVERY = 25


@dataclass(frozen=True)
class _FetchOutcome:
    card_id: int
    image_bytes: Optional[bytes] = None
    content_hash: Optional[int] = None
    card_name: Optional[str] = None
    outcome: Optional[str] = None  # None means fetched OK; otherwise a skip reason


@dataclass
class _CardAbResult:
    card_id: int
    card_name: str
    byte_identical: bool
    parse_agree: bool
    stored_vs_fresh_agree: Optional[bool]
    conf_delta: Optional[float]
    latency_pytesseract_ms: float
    latency_tesserocr_ms: float
    # kept alongside `parse_agree` (not derivable from it) so `--disagreements-detail` can
    # classify each disagreeing card's two parses without re-running either engine.
    parsed_pytesseract: OcrParseResult
    parsed_tesserocr: OcrParseResult


@dataclass
class _AbSummary:
    sample_requested: int
    sample_drawn: int
    seed: int
    results: list[_CardAbResult] = field(default_factory=list)
    fetch_failures: int = 0
    lockout_hit: bool = False


def _fetch_one(card_id: int, stop_event: Any) -> _FetchOutcome:
    if stop_event.is_set():
        return _FetchOutcome(card_id=card_id, outcome="skipped-lockout")
    try:
        card = Card.objects.select_related("source").get(pk=card_id)
    except Card.DoesNotExist:
        return _FetchOutcome(card_id=card_id, outcome="dropped")
    try:
        image_bytes = fetch_card_image_bytes(card, dpi=DEFAULT_FETCH_DPI)
    except GoogleFetchLockoutError:
        stop_event.set()
        logger.error("GoogleFetchLockoutError observed - stopping the run, no further fetches submitted")
        return _FetchOutcome(card_id=card_id, outcome="lockout")
    if image_bytes is None:
        return _FetchOutcome(card_id=card_id, outcome="fetch_failed")
    return _FetchOutcome(
        card_id=card_id,
        image_bytes=image_bytes,
        content_hash=card.content_phash,
        card_name=card.name,
        outcome=None,
    )


def _mean_conf(words: list[dict[str, Any]]) -> Optional[float]:
    confidences = [w["conf"] for w in words if w["conf"] >= 0]
    return sum(confidences) / len(confidences) if confidences else None


@contextlib.contextmanager
def _suppress_libpng_warnings() -> Iterator[None]:
    """Some real card images decode with a benign libpng `iCCP: known incorrect sRGB profile`
    (and similar) warning - emitted by libpng itself straight to the process's OS-level stderr
    file descriptor during Pillow's decode, not raised as a Python `warnings.warn` call, so a
    `warnings.catch_warnings()` filter can never catch it. Redirects fd 2 to `os.devnull` only
    for the duration of the image decode/crop/preprocess calls below, so this run's own stdout
    (what an executor tails and what `--disagreements-detail`'s report depends on) survives
    untouched. Safe here specifically because `_compare_one_card` runs strictly sequentially in
    the main thread (module docstring) - never wrap a call made from a worker thread with this,
    the fd redirect is process-global, not per-thread.
    """
    saved_fd = os.dup(2)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(saved_fd, 2)
        os.close(devnull_fd)
        os.close(saved_fd)


def _compare_one_card(
    card_id: int, card_name: str, content_hash: Optional[int], image_bytes: bytes
) -> Optional[_CardAbResult]:
    """The compute-only half - takes already-fetched bytes (never re-fetches), decodes lazily,
    crops+preprocesses ONCE, then runs the SAME variant through both engines via the real seam
    (`run_tesseract_text_and_words`, `override_settings` swapping which engine is active - see
    module docstring for why this dogfoods the seam instead of re-implementing dispatch here).
    Returns `None` only if the image itself fails to decode/crop (a genuinely corrupt fetch) -
    counted by the caller as a fetch_failures-style skip, matching `run_image_evidence_cohort.py`'s
    own "a failure this late in the pipeline is still a fetch_failed for reporting purposes"
    convention.
    """
    from PIL import Image

    try:
        with _suppress_libpng_warnings():
            image = Image.open(BytesIO(image_bytes))
            cropped = crop_collector_line(image, DEFAULT_CROP_BOX)
            variant = preprocess_variants(cropped)[0]
    except Exception:
        logger.exception("Failed to decode/crop/preprocess card %s - counting as a fetch failure", card_id)
        return None

    with override_settings(OCR_ENGINE=OCR_ENGINE_PYTESSERACT):
        started_at = time.monotonic()
        text_py, words_py = run_tesseract_text_and_words(variant, config=TESSERACT_CONFIG)
        latency_py_ms = (time.monotonic() - started_at) * 1000

    with override_settings(OCR_ENGINE=OCR_ENGINE_TESSEROCR):
        started_at = time.monotonic()
        text_te, words_te = run_tesseract_text_and_words(variant, config=TESSERACT_CONFIG)
        latency_te_ms = (time.monotonic() - started_at) * 1000

    parsed_py = parse_collector_line(text_py)
    parsed_te = parse_collector_line(text_te)

    conf_py = _mean_conf(words_py)
    conf_te = _mean_conf(words_te)
    conf_delta = abs(conf_py - conf_te) if conf_py is not None and conf_te is not None else None

    stored_vs_fresh_agree: Optional[bool] = None
    # content_hash is Optional[int] (a fetch outcome may carry None - e.g. a card whose own
    # content_phash was never set) - ImageEvidence.content_hash is a non-nullable BigIntegerField,
    # so there is nothing to compare against a None hash; skip the lookup entirely rather than
    # querying with a value the column can never actually hold.
    if content_hash is not None:
        stored_row = (
            ImageEvidence.objects.filter(card_id=card_id, content_hash=content_hash)
            .exclude(collector_line_raw_text="")
            .order_by("-updated_at")
            .first()
        )
        if stored_row is not None:
            stored_parsed = (
                stored_row.collector_line_set_code or None,
                stored_row.collector_line_collector_number or None,
            )
            stored_vs_fresh_agree = stored_parsed == (parsed_py.set_code, parsed_py.collector_number)

    return _CardAbResult(
        card_id=card_id,
        card_name=card_name,
        byte_identical=text_py == text_te,
        parse_agree=(parsed_py.set_code, parsed_py.collector_number)
        == (parsed_te.set_code, parsed_te.collector_number),
        stored_vs_fresh_agree=stored_vs_fresh_agree,
        conf_delta=conf_delta,
        latency_pytesseract_ms=latency_py_ms,
        latency_tesserocr_ms=latency_te_ms,
        parsed_pytesseract=parsed_py,
        parsed_tesserocr=parsed_te,
    )


def run_ab(sample: int, seed: Optional[int], stdout_write: Any) -> _AbSummary:
    effective_seed = seed if seed is not None else int(time.time())
    rng = random.Random(effective_seed)

    candidate_ids = list(
        ImageEvidence.objects.filter(extractor_versions__has_key="collector_line_ocr")
        .values_list("card_id", flat=True)
        .distinct()
    )
    sample_drawn = min(sample, len(candidate_ids))
    sampled_ids = rng.sample(candidate_ids, sample_drawn) if candidate_ids else []

    stdout_write(
        f"seed={effective_seed} candidate_pool={len(candidate_ids)} sample_requested={sample} "
        f"sample_drawn={sample_drawn}"
    )

    summary = _AbSummary(sample_requested=sample, sample_drawn=sample_drawn, seed=effective_seed)
    if not sampled_ids:
        return summary

    import threading

    stop_event = threading.Event()
    completed = 0
    with ThreadPoolExecutor(max_workers=FETCH_THREADS) as fetch_pool:
        futures = {fetch_pool.submit(_fetch_one, card_id, stop_event): card_id for card_id in sampled_ids}
        for future in as_completed(futures):
            outcome = future.result()
            completed += 1
            if outcome.outcome == "lockout":
                summary.lockout_hit = True
                continue
            if outcome.outcome is not None:
                summary.fetch_failures += 1
            else:
                assert outcome.image_bytes is not None
                assert outcome.card_name is not None
                result = _compare_one_card(
                    outcome.card_id, outcome.card_name, outcome.content_hash, outcome.image_bytes
                )
                if result is None:
                    summary.fetch_failures += 1
                else:
                    summary.results.append(result)
            if completed % PROGRESS_EVERY == 0 or completed == len(sampled_ids):
                stdout_write(f"[{completed}/{len(sampled_ids)}] fetch_failures={summary.fetch_failures}")

    return summary


def _fmt_bool(value: Optional[bool]) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


def _print_report(summary: _AbSummary, stdout_write: Any) -> dict[str, Any]:
    n = len(summary.results)
    stdout_write("")
    stdout_write(
        f"{'card_id':>10} {'byte_identical':>14} {'parse_agree':>12} {'stored_vs_fresh':>16} "
        f"{'conf_delta':>10} {'lat_py_ms':>10} {'lat_te_ms':>10}"
    )
    for r in summary.results:
        conf_str = f"{r.conf_delta:.2f}" if r.conf_delta is not None else "n/a"
        stdout_write(
            f"{r.card_id:>10} {_fmt_bool(r.byte_identical):>14} {_fmt_bool(r.parse_agree):>12} "
            f"{_fmt_bool(r.stored_vs_fresh_agree):>16} {conf_str:>10} "
            f"{r.latency_pytesseract_ms:>10.1f} {r.latency_tesserocr_ms:>10.1f}"
        )

    byte_identical_count = sum(1 for r in summary.results if r.byte_identical)
    parse_agree_count = sum(1 for r in summary.results if r.parse_agree)
    stored_compared = [r for r in summary.results if r.stored_vs_fresh_agree is not None]
    stored_agree_count = sum(1 for r in stored_compared if r.stored_vs_fresh_agree)
    conf_deltas = [r.conf_delta for r in summary.results if r.conf_delta is not None]
    mean_conf_delta = sum(conf_deltas) / len(conf_deltas) if conf_deltas else None
    mean_latency_py = sum(r.latency_pytesseract_ms for r in summary.results) / n if n else None
    mean_latency_te = sum(r.latency_tesserocr_ms for r in summary.results) / n if n else None
    speedup = (mean_latency_py / mean_latency_te) if mean_latency_py and mean_latency_te else None

    stdout_write("")
    stdout_write("--- summary ---")
    stdout_write(f"n={n} (sample_drawn={summary.sample_drawn} fetch_failures={summary.fetch_failures})")
    if n:
        stdout_write(f"byte_identical: {byte_identical_count}/{n} ({100 * byte_identical_count / n:.1f}%)")
        stdout_write(f"parse_agree: {parse_agree_count}/{n} ({100 * parse_agree_count / n:.1f}%)")
    if stored_compared:
        stdout_write(
            f"stored_vs_fresh_agree: {stored_agree_count}/{len(stored_compared)} "
            f"({100 * stored_agree_count / len(stored_compared):.1f}%)"
        )
    else:
        stdout_write("stored_vs_fresh_agree: no comparable stored evidence rows in this sample")
    if mean_conf_delta is not None:
        stdout_write(f"mean |confidence delta|: {mean_conf_delta:.2f}")
    if mean_latency_py is not None and mean_latency_te is not None:
        speedup_str = f" (speedup={speedup:.2f}x)" if speedup else ""
        stdout_write(
            f"mean latency: pytesseract={mean_latency_py:.1f}ms tesserocr={mean_latency_te:.1f}ms{speedup_str}"
        )
    if summary.lockout_hit:
        stdout_write("GoogleFetchLockoutError observed during this run - stopped early.")

    return {
        "n": n,
        "byte_identical_count": byte_identical_count,
        "parse_agree_count": parse_agree_count,
        "stored_compared": len(stored_compared),
        "stored_agree_count": stored_agree_count,
        "mean_conf_delta": mean_conf_delta,
        "mean_latency_pytesseract_ms": mean_latency_py,
        "mean_latency_tesserocr_ms": mean_latency_te,
        "fetch_failures": summary.fetch_failures,
        "lockout_hit": summary.lockout_hit,
        "sample_drawn": summary.sample_drawn,
        "seed": summary.seed,
    }


DISAGREEMENT_BUCKET_TESSEROCR_ONLY = "tesserocr_only_valid"
DISAGREEMENT_BUCKET_PYTESSERACT_ONLY = "pytesseract_only_valid"
DISAGREEMENT_BUCKET_BOTH_VALID = "both_valid_different"
DISAGREEMENT_BUCKET_NEITHER_VALID = "neither_valid"
DISAGREEMENT_BUCKETS = (
    DISAGREEMENT_BUCKET_TESSEROCR_ONLY,
    DISAGREEMENT_BUCKET_PYTESSERACT_ONLY,
    DISAGREEMENT_BUCKET_BOTH_VALID,
    DISAGREEMENT_BUCKET_NEITHER_VALID,
)


@dataclass(frozen=True)
class _ParseValidation:
    lexicon_valid: bool
    candidate_match: bool

    @property
    def valid(self) -> bool:
        return self.lexicon_valid and self.candidate_match


def _classify_parse(
    parsed: OcrParseResult, card_name: str, known_codes: frozenset[str], index: Any
) -> _ParseValidation:
    """Classifies a single engine's parse for `--disagreements-detail` - LEXICON-VALID reuses
    `image_evidence._parse_is_lexicon_valid` (the same "set code is None, or exists in
    `CanonicalExpansion`" gate `local_calculate_verdicts.calculate_join_key_verdict` applies
    inline via its own `known_set_codes()`-built lexicon - see that function's own SET-CODE
    LEXICON GATE docstring paragraph); CANDIDATE-MATCHES reuses `local_ocr.
    validate_against_candidates` unmodified against this card's own name-scoped candidate set
    (`local_calculate_verdicts._resolve_candidates_for_card`, the same back-face-aware resolver
    the real join-key calculator uses - see that function's own docstring for why candidates
    MUST be name-scoped, never a global query). Neither check is reimplemented here."""
    lexicon_valid = _parse_is_lexicon_valid(parsed, known_codes)
    candidates = _resolve_candidates_for_card(card_name, index)
    matched, _skip_reason = validate_against_candidates(parsed, candidates)
    return _ParseValidation(lexicon_valid=lexicon_valid, candidate_match=matched is not None)


def _fmt_parsed(parsed: OcrParseResult) -> str:
    return f"({parsed.set_code}, {parsed.collector_number})"


def _print_disagreements_detail(summary: _AbSummary, stdout_write: Any) -> dict[str, int]:
    """For every card whose two engines' PARSES disagree (`_CardAbResult.parse_agree is False`),
    prints one classification line per card and returns a summary dict of the four mutually
    exclusive buckets below (also merged into this run's own ledger `counters` by the caller).
    Read-only throughout - `known_set_codes()` and `_get_cached_candidate_name_index()` are both
    plain DB reads, no write path exists here at all (matching this whole command's own
    unconditional `dry_run=True` convention).

    A parse counts as VALID for bucketing purposes only when BOTH named checks pass (lexicon-
    valid AND candidate-matched) - `candidate_match=True` structurally implies `lexicon_valid=
    True` already (a real matched `CandidatePrinting`'s `expansion_code` is always a real
    `CanonicalExpansion.code`, or the parse never carried a set code at all - the pre-M15,
    collector-number-only case `_parse_is_lexicon_valid` already treats as vacuously valid), so
    this conjunction is equivalent to `candidate_match` alone in practice; written as an explicit
    `and` anyway so the bucket definition doesn't silently depend on that structural fact holding
    forever.
    """
    disagreements = [r for r in summary.results if not r.parse_agree]
    counts = {bucket: 0 for bucket in DISAGREEMENT_BUCKETS}

    stdout_write("")
    stdout_write("--- disagreements detail ---")
    if not disagreements:
        stdout_write("no parse-level disagreements in this sample")
        return counts

    known_codes = known_set_codes()
    index = _get_cached_candidate_name_index()

    for r in disagreements:
        py = _classify_parse(r.parsed_pytesseract, r.card_name, known_codes, index)
        te = _classify_parse(r.parsed_tesserocr, r.card_name, known_codes, index)

        if py.valid and te.valid:
            bucket = DISAGREEMENT_BUCKET_BOTH_VALID
        elif py.valid:
            bucket = DISAGREEMENT_BUCKET_PYTESSERACT_ONLY
        elif te.valid:
            bucket = DISAGREEMENT_BUCKET_TESSEROCR_ONLY
        else:
            bucket = DISAGREEMENT_BUCKET_NEITHER_VALID
        counts[bucket] += 1

        stdout_write(
            f"card_id={r.card_id} "
            f"pytesseract={_fmt_parsed(r.parsed_pytesseract)} "
            f"lexicon_valid={_fmt_bool(py.lexicon_valid)} candidate_match={_fmt_bool(py.candidate_match)} | "
            f"tesserocr={_fmt_parsed(r.parsed_tesserocr)} "
            f"lexicon_valid={_fmt_bool(te.lexicon_valid)} candidate_match={_fmt_bool(te.candidate_match)} | "
            f"bucket={bucket}"
        )

    stdout_write("")
    stdout_write("--- disagreements classification summary ---")
    stdout_write(
        f"tesserocr_only_valid={counts[DISAGREEMENT_BUCKET_TESSEROCR_ONLY]} "
        f"pytesseract_only_valid={counts[DISAGREEMENT_BUCKET_PYTESSERACT_ONLY]} "
        f"both_valid_different={counts[DISAGREEMENT_BUCKET_BOTH_VALID]} "
        f"neither_valid={counts[DISAGREEMENT_BUCKET_NEITHER_VALID]}"
    )
    return counts


class Command(BaseCommand):
    help = (
        "Read-only real-image A/B validation for the tesserocr OCR engine seam (issue #423): "
        "fetches a bounded sample of real card images transiently (never persisted - see module "
        "docstring), OCRs the SAME preprocessed crop through both pytesseract and tesserocr via "
        "the real local_ocr engine seam, and reports per-image byte-identity, parse-level "
        "agreement, stored-vs-fresh agreement (drift detection against this card's existing "
        "collector_line_ocr evidence), confidence deltas, and per-call latency for both engines. "
        "Writes nothing to ImageEvidence or any card - purely a report. This is the tool #423's "
        "spike comment names as the prerequisite for any future OCR_ENGINE flip decision. "
        "--disagreements-detail additionally classifies every parse-level disagreement by "
        "lexicon-validity and candidate-match, against the real known_set_codes()/"
        "validate_against_candidates checks (still read-only)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--sample",
            type=int,
            default=DEFAULT_SAMPLE,
            help=f"Number of cards to sample (default: {DEFAULT_SAMPLE}).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Random seed for reproducible sampling - default: derived from the current "
            "time (always echoed to stdout and the run's own ledger row, so an unseeded run's "
            "sample is still identifiable after the fact).",
        )
        parser.add_argument(
            "--disagreements-detail",
            action="store_true",
            default=False,
            help="For every card where the two engines' parses disagree, print a per-card "
            "classification line (each engine's parsed (set_code, collector_number), whether "
            "each is lexicon-valid and candidate-matched) plus a "
            "tesserocr_only_valid/pytesseract_only_valid/both_valid_different/neither_valid "
            "summary - also merged into this run's own ledger counters. Read-only, same as "
            "every other report this command produces.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        sample: int = max(0, options["sample"])
        seed: Optional[int] = options["seed"]
        disagreements_detail: bool = options["disagreements_detail"]
        # Microsecond-precision timestamp (2026-07-25, PR #470's own "same-day/same-second
        # collision" fix, mirrored here rather than re-derived - see that PR for the original
        # UNIQUE-constraint incident on PilotRunLedger.run_id): a whole-second-only timestamp
        # collides when this command runs twice within the same second (a real case: two
        # back-to-back A/B validation passes, or a test suite invoking it repeatedly).
        run_id = f"ocr-engine-ab-{timezone.now().strftime('%Y%m%dT%H%M%S%f')}Z"

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="ocr_engine_ab",
            dry_run=True,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
            counters=initial_counters(scope=scope_hash("sample", sample, "seed", seed)),
        )

        try:
            self.stdout.write(f"run_id={run_id} sample={sample} seed={seed}")
            ab_summary = run_ab(sample=sample, seed=seed, stdout_write=self.stdout.write)
            report_counters = _print_report(ab_summary, self.stdout.write)

            if disagreements_detail:
                report_counters = merge_counters(
                    report_counters, _print_disagreements_detail(ab_summary, self.stdout.write)
                )

            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.counters = merge_counters(ledger.counters, report_counters)
            ledger.save(update_fields=["status", "finished_at", "counters"])

            with resilient_terminal_output():
                self.stdout.write(f"DONE run_id={run_id} n={report_counters['n']}")
        except Exception as exc:
            mark_ledger_failed(ledger, exc)
            raise

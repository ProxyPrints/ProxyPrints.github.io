"""
Bounded, owner-authorized dataset run (2026-07-20): drives Stage C's per-card callable unit
(`cardpicker.image_evidence.extract_card_evidence` + `persist_evidence`) over a prioritized
cohort of cards to produce the FIRST real `ImageEvidence` rows on the live catalog. This is
deliberately NOT the full-catalog harvest (that needs Stage D/E's pipeline-fidelity + soak
gates and a separate owner GO - see docs/features/catalog-completion-plan.md's "Stage E resume
contract" section) - just a simple concurrent driver, matching FINAL POSTURE item 8a's
requirement that the per-card unit stay independent of any particular bulk-runner shape.

Prioritization: cards are ordered by their name's most-popular-printing `edhrec_rank` (a cheap
name-level proxy for docs/features/catalog-completion-plan.md's full harvest-priority chain -
"lands chunk -> dying-source -> queue-backing -> descending edhrec_rank -> cold tail" - not
reimplemented in full here, since the dying-source/queue-backing legs need signals this bounded
run doesn't have time to build; deviation noted in this run's own report). A NAIVE
per-Card correlated subquery against `CanonicalCard` (one lookup per card, forcing the DB to
evaluate it for all ~218k cards before an ORDER BY LIMIT can apply) was measured live and
cancelled after >2 minutes with no result - see this run's dated report. The two-step version
below avoids that: one cheap aggregate query builds a `{lowercased name: min edhrec_rank}` dict
(0.2s measured against the live catalog), then Python does the per-card lookup + sort against
however many (id, name) pairs are in scope - no per-row DB round trip.

Resume/kill-safety: `persist_evidence` is already idempotent per (card, content_hash) - a
re-run overwrites the same row rather than erroring or duplicating. This command ALSO applies a
resume filter up front (skip any card whose ImageEvidence row already carries every manifest
extractor's version key) so a re-invocation after a kill does not re-pay the fetch+OCR cost for
cards already done, matching task #147's resume-contract spirit without building its full
run-ledger machinery (explicitly out of scope for this bounded run per its own directive).

A `GoogleFetchLockoutError` (403 from the shared Google-bound destination) is a hard stop for
the whole run, exactly as `image_cdn_fetch.fetch_card_image`'s own docstring requires every
caller to treat it - this command sets a stop flag the moment one is observed and lets already
in-flight work drain, rather than continuing to submit new work into a destination that has
already locked us out.
"""

import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Min

from cardpicker.harvest_fetch_limiter import (
    GOOGLE_IMAGE,
    GoogleFetchLockoutError,
    get_limiter,
)
from cardpicker.image_evidence import extract_card_evidence, persist_evidence
from cardpicker.models import CanonicalCard, Card, ImageEvidence

logger = logging.getLogger(__name__)

# The full Stage C manifest as of 2026-07-20 (fetch_health + geometry-bleed + geometry-group +
# OCR-group) - matches image_evidence.extract_card_evidence's own extractor_versions keys.
MANIFEST_EXTRACTOR_KEYS = frozenset(
    {
        "fetch_health",
        "geometry_bleed",
        "layout_class",
        "crop_coordinates",
        "collector_line_ocr",
        "artist_ocr",
        "collector_line_tsv",
    }
)

DEFAULT_LIMIT = 3000
DEFAULT_WORKERS = 6  # matches the settled GOOGLE_IMAGE concurrency-raise probe config
PROGRESS_EVERY = 25


class Command(BaseCommand):
    help = (
        "Bounded dataset run (2026-07-20): drives extract_card_evidence + persist_evidence over "
        "a prioritized (edhrec_rank-ordered) cohort of cards. NOT the full-catalog harvest - see "
        "this command's own module docstring."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Cohort size. Default: {DEFAULT_LIMIT}.")
        parser.add_argument(
            "--workers",
            type=int,
            default=DEFAULT_WORKERS,
            help=f"Thread pool size - matches the settled GOOGLE_IMAGE concurrency config "
            f"(rate_per_sec={GOOGLE_IMAGE.rate_per_sec}, max_concurrency={GOOGLE_IMAGE.max_concurrency}). "
            f"Default: {DEFAULT_WORKERS}.",
        )
        parser.add_argument(
            "--run-id",
            type=str,
            default=None,
            help="Free-text run identifier stored on each ImageEvidence/CardScanLog row this run "
            "writes (no PilotRunLedger row - out of scope for this bounded run). Default: "
            "auto-generated from the current UTC timestamp.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Extract but do not persist anything - for timing/sampling only.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # tesseract's LSTM engine can multi-thread itself internally via OpenMP - without this,
        # N concurrent tesseract subprocesses (one per in-flight OCR call) could each ALSO
        # spread across every core, oversubscribing well past --workers. Same fix
        # local_identify_printing_tags.py's own concurrent path already applies.
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")

        limit: int = options["limit"]
        workers: int = max(1, options["workers"])
        dry_run: bool = options["dry_run"]
        run_id: str = options["run_id"] or f"stagec-cohort-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"

        self.stdout.write(f"run_id={run_id} limit={limit} workers={workers} dry_run={dry_run}")

        # Step 1: cheap name -> min(edhrec_rank) map - see module docstring for why this replaces
        # a per-row correlated subquery.
        t0 = time.monotonic()
        name_rank: dict[str, int] = {}
        rank_rows = (
            CanonicalCard.objects.filter(printing_metadata__edhrec_rank__isnull=False)
            .values("name")
            .annotate(min_rank=Min("printing_metadata__edhrec_rank"))
        )
        for row in rank_rows.iterator():
            key = row["name"].lower()
            existing = name_rank.get(key)
            if existing is None or row["min_rank"] < existing:
                name_rank[key] = row["min_rank"]
        self.stdout.write(f"Built name->edhrec_rank map ({len(name_rank)} names) in {time.monotonic() - t0:.2f}s")

        # Step 2: resume filter - cards whose ImageEvidence row already has every manifest key.
        already_done_ids: set[int] = set()
        for card_id, extractor_versions in ImageEvidence.objects.values_list("card_id", "extractor_versions"):
            if MANIFEST_EXTRACTOR_KEYS.issubset(extractor_versions.keys()):
                already_done_ids.add(card_id)
        if already_done_ids:
            self.stdout.write(f"Resume filter: skipping {len(already_done_ids)} already-fully-processed cards")

        # Step 3: candidate (id, name) pairs, cheapest possible shape for the Python-side sort.
        candidates = (
            Card.objects.filter(content_phash__isnull=False).exclude(id__in=already_done_ids).values_list("id", "name")
        )
        id_name_pairs = list(candidates)
        self.stdout.write(f"{len(id_name_pairs)} eligible cards before cohort slicing")

        def priority_key(pair: tuple[int, str]) -> tuple[float, int]:
            card_id, name = pair
            rank = name_rank.get(name.lower())
            return (rank if rank is not None else math.inf, card_id)

        id_name_pairs.sort(key=priority_key)
        cohort_ids = [card_id for card_id, _name in id_name_pairs[:limit]]
        self.stdout.write(f"Cohort: {len(cohort_ids)} cards (prioritized by edhrec_rank, cold tail last)")

        if not cohort_ids:
            self.stdout.write("Nothing to do.")
            return

        # Step 4: fetch real Card objects, reordered to match the priority order computed above
        # (id__in does not preserve list order).
        cards_by_id = {c.pk: c for c in Card.objects.select_related("source").filter(id__in=cohort_ids)}
        ordered_cards = [cards_by_id[cid] for cid in cohort_ids if cid in cards_by_id]

        stop_on_lockout = {"hit": False}
        completed = 0
        fetch_failures = 0
        run_start = time.monotonic()
        google_limiter = get_limiter(GOOGLE_IMAGE)

        def process_one(card: Card) -> Optional[str]:
            if stop_on_lockout["hit"]:
                return "skipped-lockout"
            try:
                result = extract_card_evidence(card)
            except GoogleFetchLockoutError:
                stop_on_lockout["hit"] = True
                logger.error("GoogleFetchLockoutError observed - stopping the run, no further work submitted")
                raise
            if not dry_run:
                persist_evidence(result, run_id=run_id)
            return "fetch_failed" if result.fields.get("fetch_ok") is False else "ok"

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_one, card): card for card in ordered_cards}
            for future in as_completed(futures):
                card = futures[future]
                try:
                    outcome = future.result()
                except GoogleFetchLockoutError:
                    continue
                except Exception:
                    logger.exception("Dropped card %s (uncaught exception)", card.pk)
                    outcome = "dropped"
                completed += 1
                if outcome in ("fetch_failed", "dropped"):
                    fetch_failures += 1
                if completed % PROGRESS_EVERY == 0 or completed == len(ordered_cards):
                    elapsed = time.monotonic() - run_start
                    rate = completed / elapsed if elapsed > 0 else 0.0
                    self.stdout.write(
                        f"[{completed}/{len(ordered_cards)}] elapsed={elapsed:.0f}s rate={rate:.3f}/s "
                        f"fetch_failures={fetch_failures} live_google_rate={google_limiter.current_rate():.2f}/s"
                    )
                    self.stdout.flush()

        elapsed = time.monotonic() - run_start
        rate = completed / elapsed if elapsed > 0 else 0.0
        self.stdout.write(
            f"DONE run_id={run_id} completed={completed}/{len(ordered_cards)} elapsed={elapsed:.0f}s "
            f"rate={rate:.3f}/s fetch_failures={fetch_failures} lockout_hit={stop_on_lockout['hit']}"
        )

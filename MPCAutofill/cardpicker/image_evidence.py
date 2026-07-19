"""
Stage C's per-card callable extraction unit (docs/features/catalog-completion-plan.md, task
#145). Fetch -> extract -> return, no DB writes - a pure function safe to call from the bulk
harvest runner OR a future demand-driven lazy-mode task (FINAL POSTURE directive item 8a,
2026-07-19: "the per-card work unit must be a callable unit independent of the bulk runner" -
BINDING now, not deferred design). Modelled on local_identify_printing_tags._compute_card's
existing fetch/extract/no-side-effects shape, generalized and made importable rather than
module-private.

Persistence (`persist_evidence`) is a separate, thin step so callers control their own
transaction boundaries (the bulk runner's future atomic-batch-seam, task #147 item 3; a
lazy-mode task's own single-card transaction) - `extract_card_evidence` itself never touches
the DB, and image bytes never persist anywhere (CLAUDE.md's "Governing premise": we index, we
do not store images) - they go out of scope the moment this function returns.

Extend this module (not ImageEvidence's callers) when adding a new extractor: fetch once at
the top of `extract_card_evidence`, call each new pure extractor function against the same
in-memory image, and add its fields/version/skip-reason to the result. Only `fetch_health`
exists today - intentional, per task #145's "infrastructure PR first, one extractor per PR
after" sequencing.

RECONCILIATION LEDGER (owner directive 2026-07-19, task #155): `build_reconciliation_report`
answers "attempted = voted + each named skip-reason + dropped" for one extractor over one set
of cards, by querying ImageEvidence.extractor_versions + CardScanLog directly - see
ImageEvidence's own docstring for the exact voted/skipped/dropped definitions.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.image_cdn_fetch import DEFAULT_FETCH_DPI, fetch_card_image
from cardpicker.models import Card, CardScanLog, ImageEvidence

logger = logging.getLogger(__name__)

FETCH_HEALTH_EXTRACTOR_VERSION = "fetch-health-v1"


@dataclass(frozen=True)
class ExtractionResult:
    """
    Pure result of one card's extraction pass - no DB writes have happened yet. `fields` holds
    every ImageEvidence column this pass computed a value for. `extractor_versions` holds the
    version tag for every extractor that RAN TO COMPLETION for this card (whether it found a
    positive result or a named-skip outcome) - an extractor that raises/crashes omits its own
    key here, which is what makes it "dropped" rather than "skipped" for reconciliation
    purposes (see module docstring). `skip_reasons` holds a named reason for every extractor
    that ran but declined to produce a real value (e.g. fetch failure) - always a subset of
    extractor_versions' keys.
    """

    card_id: int
    content_hash: Optional[int]
    fields: dict[str, Any] = field(default_factory=dict)
    extractor_versions: dict[str, str] = field(default_factory=dict)
    skip_reasons: dict[str, str] = field(default_factory=dict)


def extract_card_evidence(card: Card, dpi: Optional[int] = DEFAULT_FETCH_DPI) -> ExtractionResult:
    """
    The per-card callable work unit. `card.content_phash` (not recomputed here) is the content
    hash this evidence is keyed against - hash-at-ingest (Part 2) already populates it for
    essentially every card by the time Stage C runs. If it's still null, the result's
    `content_hash` is None and `persist_evidence` will refuse to write a row, since
    ImageEvidence's "computed-once-forever" premise depends on a stable hash to key on.
    """

    fields: dict[str, Any] = {}
    extractor_versions: dict[str, str] = {}
    skip_reasons: dict[str, str] = {}

    try:
        image = fetch_card_image(card, dpi=dpi)
    except GoogleFetchLockoutError:
        # A 403 lockout is a hard stop for the whole run, not a per-card fetch-health
        # observation - propagate exactly as image_cdn_fetch.fetch_card_image's own docstring
        # requires every caller to.
        raise

    if image is None:
        fields["fetch_ok"] = False
        fields["fetch_error_class"] = "fetch_failed"
        skip_reasons["fetch_health"] = "fetch_failed"
    else:
        fields["fetch_ok"] = True
        fields["fetch_error_class"] = ""
    # Set even on skip - fetch_health RAN TO COMPLETION either way, it just didn't find a
    # positive result. Omitted only if this function raises before reaching here.
    extractor_versions["fetch_health"] = FETCH_HEALTH_EXTRACTOR_VERSION

    return ExtractionResult(
        card_id=card.pk,
        content_hash=card.content_phash,
        fields=fields,
        extractor_versions=extractor_versions,
        skip_reasons=skip_reasons,
    )


def persist_evidence(result: ExtractionResult, run_id: Optional[str] = None) -> Optional[ImageEvidence]:
    """
    The thin, separate DB-write step (see module docstring for why this is split from
    `extract_card_evidence`). Refuses to write if `content_hash` is None. Uses
    `get_or_create` + field merge (not a blind create) so a re-run against the SAME (card,
    content_hash) pair updates in place rather than erroring on the unique constraint - this is
    what makes independently-landing extractor PRs additive: each one's own pass only ever
    touches its own fields/version key, never clobbers another extractor's already-written data.

    Also writes a `CardScanLog` row for every entry in `result.skip_reasons` (the
    reconciliation ledger's "named skip" leg - see module docstring), tagged
    `anonymous_id=<extractor name>` so it correlates back to `extractor_versions`' own keys.
    """

    if result.content_hash is None:
        logger.warning("Skipping ImageEvidence persist for card %s: content_phash is null", result.card_id)
        return None

    evidence, _ = ImageEvidence.objects.get_or_create(card_id=result.card_id, content_hash=result.content_hash)
    for field_name, value in result.fields.items():
        setattr(evidence, field_name, value)
    evidence.extractor_versions = {**evidence.extractor_versions, **result.extractor_versions}
    evidence.run_id = run_id
    evidence.save()

    for extractor_name, skip_reason in result.skip_reasons.items():
        CardScanLog.objects.create(
            card_id=result.card_id, anonymous_id=extractor_name, skip_reason=skip_reason, run_id=run_id
        )

    return evidence


@dataclass(frozen=True)
class ReconciliationReport:
    """See ImageEvidence's own docstring for the exact voted/skipped/dropped definitions."""

    extractor_name: str
    attempted: int
    voted: int
    skipped_by_reason: dict[str, int]
    dropped: int

    def is_consistent(self) -> bool:
        return self.attempted == self.voted + sum(self.skipped_by_reason.values()) + self.dropped


def build_reconciliation_report(
    extractor_name: str, card_ids: list[int], run_id: Optional[str] = None
) -> ReconciliationReport:
    """
    Queries ImageEvidence + CardScanLog directly rather than a separately-maintained counter,
    so the report can never drift from what was actually persisted. `run_id`, if given, scopes
    the CardScanLog side to that run only (matching CardScanLog's own run_id-scoped query
    convention elsewhere) - ImageEvidence's own `run_id` is a last-writer field, not filtered
    here, since a card's evidence may have been written by an earlier run and only skipped (or
    not attempted at all) in this one.
    """

    attempted = len(card_ids)

    ran_card_ids = set(
        ImageEvidence.objects.filter(card_id__in=card_ids, extractor_versions__has_key=extractor_name).values_list(
            "card_id", flat=True
        )
    )

    skip_qs = CardScanLog.objects.filter(card_id__in=card_ids, anonymous_id=extractor_name)
    if run_id is not None:
        skip_qs = skip_qs.filter(run_id=run_id)

    skipped_by_reason: dict[str, int] = {}
    skipped_card_ids: set[int] = set()
    for card_id, skip_reason in skip_qs.values_list("card_id", "skip_reason"):
        skipped_by_reason[skip_reason] = skipped_by_reason.get(skip_reason, 0) + 1
        skipped_card_ids.add(card_id)

    voted = len(ran_card_ids - skipped_card_ids)
    dropped = attempted - len(ran_card_ids | skipped_card_ids)

    return ReconciliationReport(
        extractor_name=extractor_name,
        attempted=attempted,
        voted=voted,
        skipped_by_reason=skipped_by_reason,
        dropped=dropped,
    )


__all__ = [
    "ExtractionResult",
    "extract_card_evidence",
    "persist_evidence",
    "ReconciliationReport",
    "build_reconciliation_report",
    "FETCH_HEALTH_EXTRACTOR_VERSION",
]

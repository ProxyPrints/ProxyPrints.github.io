"""
Stage C evidence transfer (issue #473 PR-2, folded with issue #472 per the owner-approved
2026-07-25 fold - "same function, one coherent change"). Before a card with a known
`Card.md5_checksum` pays for a real fetch+extraction pass, check whether an md5-identical sibling
already holds a CURRENT, full-manifest `ImageEvidence` row - if so, copy that row's own field
values onto this card's own `(card, content_hash)` row instead of re-doing byte-identical work.
Two callers, one function: the streaming conveyor's `stage_e_dispatch._run_stage_c` (checked
BEFORE handing a card to the decoupled fetch-ahead thread, #472) and the BULK
`run_image_evidence_cohort.py` fetch stage (`_fetch_one_card`, checked BEFORE the network fetch
call) - see each call site's own docstring for exactly where this is wired in.

KILL-SWITCH (Tron §8 gate condition, 2026-07-25): `settings.STAGE_C_EVIDENCE_TRANSFER_ENABLED`
(default `True`) gates `find_transfer_source` at its very top - `False` makes every call return
`None` immediately, with no query issued at all, so both seams fall straight through to their own
pre-existing real-fetch path exactly as if this module didn't exist. Exists for first-pass
reversibility - a single settings flip turns transfer off catalog-wide with no code change, if a
live run needs to isolate whether an anomaly originates here.

GROUP KEY: md5 alone (issue #473's parent ruling 3 - a NULL or unique md5 is a "group of one";
every card without a known md5 falls straight through `find_transfer_source` returning `None`,
i.e. today's unconditional fetch/extract behavior, unchanged).

PAIRING RULE (binding, issue #473's 2026-07-25 comment, owner-ratified alongside PR-1's
`Card.sha256_checksum` addition, now a real column on every deploy this branch runs against):
a byte-identical claim this strong needs a cryptographic backstop before this module trusts it
enough to SKIP real extraction. Whenever BOTH cards carry a sha256, it must ALSO match. An md5
match with a present-on-both sha256 MISMATCH is a loud anomaly (logged at ERROR AND written as a
durable `CardScanLog` row, see ANOMALY LOGGING below) - transfer is skipped and the caller falls
through to real extraction, never a silent downgrade to an md5-only transfer. md5 collisions are
constructible; a present sha256 is exactly the case this module has enough information to verify
the "identical bytes" premise cryptographically instead of assuming it, so it always overrides an
md5-only pairing whenever both sides have one. When sha256 is absent on either side, the pairing
rests on md5 + the content-hash assertion below alone.

CONTENT-HASH ASSERTION: byte-identical files imply an identical perceptual hash (phash is a pure
function of pixel content - identical bytes decode to identical pixels). This is ASSERTED, not
merely trusted: the sibling's own `content_hash` (guaranteed by the currency query below to equal
the sibling CARD's own live `content_phash`) is compared against THIS card's own `content_phash`.
A mismatch here is impossible for two cards that are genuinely byte-identical, so observing one is
evidence of a REAL anomaly (a stale/incorrect md5 pairing, an actual md5 collision, or a
data-entry error) - logged loudly at ERROR, transfer skipped, never transferred anyway.

TRANSFER-SOURCE INTEGRITY (Tron §8 gate condition, 2026-07-25 - tightened from an earlier draft
that reused the null-tolerant CURRENCY rule for this too): a sibling is only a valid transfer
SOURCE if its own stamped `md5_checksum` IS NOT NULL and EQUALS the target's own live md5 -
`image_evidence.current_evidence_queryset`'s null-tolerant rule (a legacy unstamped row stays
CURRENT for its own card) is a currency notion, never a transfer-source-eligibility one; minting
a fresh stamp on the copy from a source that never carried one at all would launder an unverified
value into a verified-looking field. See `_current_sibling_evidence_queryset`'s own docstring.

ANOMALY LOGGING (Tron §8 gate condition, 2026-07-25): both anomaly paths in `find_transfer_source`
now write a durable `CardScanLog(anonymous_id=EVIDENCE_TRANSFER_ANONYMOUS_ID, skip_reason=<the
specific anomaly>)` row in addition to the `logger.error` call - the log line alone isn't queryable
after the fact; a whole-catalog run needs to be able to COUNT how many cards hit each anomaly,
per card, the same way every other named-skip population in this codebase is counted (`CardScanLog`
is already the established "durable negative record" primitive - see that model's own docstring).

Neither anomaly path raises - both return `None` from `find_transfer_source`, and every caller's
own contract for a `None` result is "fall through to real extraction" (never "give up on this
card"), so a loud anomaly degrades to the pre-existing, already-correct behavior rather than
failing the whole batch/card.
"""

import logging
from typing import Optional

from django.conf import settings
from django.db.models import F, Q, QuerySet

from cardpicker.models import Card, CardScanLog, ImageEvidence

logger = logging.getLogger(__name__)

# This module's own CardScanLog anonymous_id (issue #473 PR-2's ANOMALY LOGGING section above) -
# distinct from every extractor's own anonymous_id (image_evidence.py) and every Stage D
# calculator's own (local_calculate_verdicts.py), matching this codebase's own "one anonymous_id
# per distinct write population" convention.
EVIDENCE_TRANSFER_ANONYMOUS_ID = "evidence-transfer-v1"
EVIDENCE_TRANSFER_SHA256_MISMATCH_SKIP_REASON = "transfer-sha256-mismatch"
EVIDENCE_TRANSFER_CONTENT_HASH_MISMATCH_SKIP_REASON = "transfer-content-hash-mismatch"

# Every concrete ImageEvidence field that represents actual extracted content - copied verbatim
# from the sibling row onto the target's own row. Deliberately EXCLUDES: "id" (a fresh row gets
# its own pk via get_or_create), "card"/"card_id" (the target, never the sibling), "content_hash"
# (the TARGET's own content_phash - already the get_or_create key, never the sibling's), "run_id"
# (set fresh by the caller, not copied), "created_at"/"updated_at" (Django-managed), and this PR's
# own four new fields (md5_checksum/sha256_checksum/transferred/transferred_from_card_id) - each
# of those four is set explicitly from the TARGET card's own values by `transfer_evidence` below,
# never copied from the sibling (see that function's own docstring for why).
_NON_TRANSFERABLE_FIELD_NAMES = frozenset(
    {
        "id",
        "card",
        "content_hash",
        "run_id",
        "created_at",
        "updated_at",
        "md5_checksum",
        "sha256_checksum",
        "transferred",
        "transferred_from_card_id",
    }
)
_TRANSFERABLE_FIELD_NAMES = [
    f.name
    for f in ImageEvidence._meta.get_fields()
    if getattr(f, "concrete", False) and f.name not in _NON_TRANSFERABLE_FIELD_NAMES
]


def md5_currency_q(related_prefix: str = "card__") -> Q:
    """
    Bulk (F-expression-based) Q object expressing the md5 half of `ImageEvidence`'s own CURRENCY
    rule (see `image_evidence.current_evidence_queryset`'s own docstring for the single-card,
    literal-value form of the identical rule) - True (row stays CURRENT/eligible) unless the row's
    own stamped `md5_checksum` is non-null AND the related Card's live `md5_checksum` (reached via
    `related_prefix`, default `"card__"` i.e. `ImageEvidence.card`) is ALSO non-null AND the two
    disagree. Three-clause OR, not a single equality check, specifically so a NULL on either side
    (a legacy unstamped row, or a card whose source never carries an md5 at all) never excludes a
    row - SQL's three-valued logic means a bare `md5_checksum=F(...)` comparison would silently
    evaluate to NULL/false whenever either side is NULL, which is the OPPOSITE of the null-tolerant
    behavior this rule requires.

    NULL-TOLERANT BY DESIGN FOR CURRENCY ONLY (Tron §8 gate condition, 2026-07-25 - see module
    docstring's "TRANSFER-SOURCE INTEGRITY" section): this function is used by
    `image_evidence.current_evidence_queryset` and `modern_artist_credit.py`'s own bulk currency
    read, NEVER by this module's own `_current_sibling_evidence_queryset` below - a transfer
    SOURCE's own eligibility requires a strict non-null equality match instead, applied inline
    there rather than through this null-tolerant helper.
    """
    return (
        Q(md5_checksum__isnull=True)
        | Q(**{f"{related_prefix}md5_checksum__isnull": True})
        | Q(md5_checksum=F(f"{related_prefix}md5_checksum"))
    )


def _current_sibling_evidence_queryset(card: Card) -> "QuerySet[ImageEvidence]":
    """Every OTHER card's own CURRENT, full-manifest `ImageEvidence` row sharing `card`'s own
    md5_checksum - "current" here means the sibling row's own `content_hash` matches ITS OWN
    card's live `content_phash` (the pre-existing currency rule). TRANSFER-SOURCE INTEGRITY
    (Tron §8 gate condition, 2026-07-25, module docstring's own section): a sibling row's own
    stamped `md5_checksum` must be NOT NULL and EQUAL to `card`'s own live md5 -
    `.filter(md5_checksum=card.md5_checksum)` below is a strict, non-null-tolerant Django lookup
    (SQL's three-valued logic means `md5_checksum = <value>` never matches a NULL row), deliberately
    NOT `md5_currency_q()` (that helper's own null-tolerant rule is for CURRENCY checks only, see
    its own docstring) - a source row that never carried a stamp at all is never eligible to seed a
    transfer, regardless of how "close" the rest of the match looks; minting a fresh stamp on the
    copy from an unstamped source would launder an unverified value into a verified-looking field.
    Full-manifest (`extractor_versions__has_keys` over every Stage C extractor key, imported
    lazily - see `stage_e_dispatch._stage_c_manifest_extractor_keys`'s own docstring for why this
    module-boundary import stays call-time-only) - a partially-extracted sibling (e.g. itself
    mid-transfer-chain, which never actually happens since transfer always writes every manifest
    key at once, but guarded regardless) is never a source either. Most-recently-updated first, in
    case more than one qualifying sibling somehow exists (rare - md5 groups are usually small)."""
    from cardpicker.management.commands.run_image_evidence_cohort import (
        MANIFEST_EXTRACTOR_KEYS,
    )

    return (
        ImageEvidence.objects.filter(card__md5_checksum=card.md5_checksum)
        .exclude(card_id=card.pk)
        .filter(content_hash=F("card__content_phash"))
        .filter(md5_checksum=card.md5_checksum)
        .filter(extractor_versions__has_keys=list(MANIFEST_EXTRACTOR_KEYS))
        .select_related("card")
        .order_by("-updated_at")
    )


def _record_transfer_anomaly(card: Card, skip_reason: str) -> None:
    """Durable anomaly marker (Tron §8 gate condition, 2026-07-25 - see module docstring's
    "ANOMALY LOGGING" section) - a plain `.create()`, not batched, since `find_transfer_source` is
    called per-card, not per-batch, and an anomaly is rare (the whole point is that it's a real
    data problem, not routine traffic)."""
    CardScanLog.objects.create(card_id=card.pk, anonymous_id=EVIDENCE_TRANSFER_ANONYMOUS_ID, skip_reason=skip_reason)


def find_transfer_source(card: Card) -> Optional[ImageEvidence]:
    """
    Returns the md5-sibling `ImageEvidence` row eligible to be copied onto `card`, or `None`.
    Otherwise a pure lookup (the pairing/content-hash asserts, module docstring) - `transfer_
    evidence` below does the actual `ImageEvidence` write - EXCEPT that either anomaly path below
    now also writes a durable `CardScanLog` row (Tron §8 gate condition - see module docstring's
    "ANOMALY LOGGING" section), so this function is no longer write-free in the anomaly case,
    only in the "not eligible yet" and "eligible" cases. `None` in every one of these cases:

    - `settings.STAGE_C_EVIDENCE_TRANSFER_ENABLED` is `False` (the kill-switch, module docstring) -
      no query issued at all.
    - `card.md5_checksum` is `None` (a "group of one", issue #473's ruling 3) - the overwhelming
      majority of the catalog until the backfill enrolls more cards.
    - `card.content_phash` is `None` - no stable hash yet to key this card's OWN
      `(card, content_hash)` row against, matching every other "no stable hash yet" early-return
      in this codebase (`local_calculate_verdicts._eligible_cards_queryset`'s own callers, etc.).
    - No qualifying sibling row exists at all - the ordinary, non-anomalous "nothing to transfer
      from yet" outcome.
    - The sha256 pairing check fails (both sides carry a sha256, and they disagree) - a LOUD
      anomaly, logged at ERROR + a durable CardScanLog row.
    - The content-hash assertion fails (this card's own `content_phash` disagrees with the
      sibling's) - also a LOUD anomaly, logged at ERROR + a durable CardScanLog row.

    Only the last two are actually anomalous; the first four are all just "not eligible yet".
    """
    if not getattr(settings, "STAGE_C_EVIDENCE_TRANSFER_ENABLED", True):
        return None

    if card.md5_checksum is None or card.content_phash is None:
        return None

    sibling_evidence = _current_sibling_evidence_queryset(card).first()
    if sibling_evidence is None:
        return None

    sibling_card = sibling_evidence.card

    card_sha256 = card.sha256_checksum
    sibling_sha256 = sibling_card.sha256_checksum
    if card_sha256 is not None and sibling_sha256 is not None and card_sha256 != sibling_sha256:
        logger.error(
            "Evidence transfer anomaly: card %s and md5 sibling %s share md5_checksum %s but "
            "sha256_checksum disagrees (%s != %s) - skipping transfer, falling through to real "
            "extraction",
            card.pk,
            sibling_card.pk,
            card.md5_checksum,
            card_sha256,
            sibling_sha256,
        )
        _record_transfer_anomaly(card, EVIDENCE_TRANSFER_SHA256_MISMATCH_SKIP_REASON)
        return None

    if sibling_evidence.content_hash != card.content_phash:
        logger.error(
            "Evidence transfer anomaly: card %s and md5 sibling %s share md5_checksum %s but "
            "content_phash disagrees (target=%s, sibling evidence=%s) - skipping transfer, "
            "falling through to real extraction",
            card.pk,
            sibling_card.pk,
            card.md5_checksum,
            card.content_phash,
            sibling_evidence.content_hash,
        )
        _record_transfer_anomaly(card, EVIDENCE_TRANSFER_CONTENT_HASH_MISMATCH_SKIP_REASON)
        return None

    return sibling_evidence


def transfer_evidence(card: Card, source: ImageEvidence, run_id: Optional[str] = None) -> ImageEvidence:
    """
    THE WRITE half of evidence transfer - copies every extractor field + `extractor_versions` from
    `source` (an md5-sibling's own CURRENT, full-manifest row, already vetted by
    `find_transfer_source`'s own pairing/content-hash asserts AND its own strict, non-null
    `md5_checksum` match - this function trusts its caller to have called that first, it re-verifies
    nothing itself) onto `card`'s own `(card, content_hash)` row. Same `get_or_create` + field-merge
    shape as `image_evidence.persist_evidence` (reused convention, not reinvented) - a re-run
    against the same pair updates in place rather than erroring on the unique constraint.

    Stamps `md5_checksum`/`sha256_checksum` from `card` itself (the TARGET, never `source` -
    `find_transfer_source` already verified `card.md5_checksum == source.card.md5_checksum` via a
    strict, non-null match, so stamping the target's own live value is equivalent to copying the
    sibling's, but stays correct even in the degenerate case where the two could ever disagree
    post-verification-race) and sets `transferred=True` + `transferred_from_card_id=source.card_id`.

    INTERIM STAGE D GUARD (issue #473 PR-2, temporary by design - see `ImageEvidence.transferred`'s
    own model-field docstring and `local_calculate_verdicts._eligible_cards_queryset`'s own
    coordination-note comment): `transferred=True` here is what that guard reads to exclude this
    card from the TWO machine-voting Stage D calculators (join-key/fallback - both cast a
    `CardPrintingTag` vote) until PR-3's group-level vote pooling lands and removes the guard - a
    transferred row's own machine "observation" is the SAME bytes a sibling card already voted
    from, not an independent one. The third calculator, slow-path, is deliberately NOT guarded -
    it casts no machine vote at all, only a human-review routing marker, which is exactly the
    safety net the guard exists to preserve.
    """
    evidence, _ = ImageEvidence.objects.get_or_create(card_id=card.pk, content_hash=card.content_phash)
    for field_name in _TRANSFERABLE_FIELD_NAMES:
        setattr(evidence, field_name, getattr(source, field_name))
    evidence.extractor_versions = dict(source.extractor_versions)
    evidence.run_id = run_id
    evidence.md5_checksum = card.md5_checksum
    evidence.sha256_checksum = card.sha256_checksum
    evidence.transferred = True
    evidence.transferred_from_card_id = source.card_id
    evidence.save()
    return evidence


__all__ = [
    "EVIDENCE_TRANSFER_ANONYMOUS_ID",
    "EVIDENCE_TRANSFER_SHA256_MISMATCH_SKIP_REASON",
    "EVIDENCE_TRANSFER_CONTENT_HASH_MISMATCH_SKIP_REASON",
    "md5_currency_q",
    "find_transfer_source",
    "transfer_evidence",
]

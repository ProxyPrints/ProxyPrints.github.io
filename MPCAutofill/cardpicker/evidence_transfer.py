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

GROUP KEY: md5 alone (issue #473's parent ruling 3 - a NULL or unique md5 is a "group of one";
every card without a known md5 falls straight through `find_transfer_source` returning `None`,
i.e. today's unconditional fetch/extract behavior, unchanged).

PAIRING RULE (binding, issue #473's 2026-07-25 comment, owner-ratified alongside PR-1's
`Card.sha256_checksum` addition): a byte-identical claim this strong needs a cryptographic
backstop before this module trusts it enough to SKIP real extraction. Whenever BOTH cards carry a
sha256 (`Card.sha256_checksum` - added by a sibling PR on the same stacked base, not guaranteed to
exist on this branch yet; read via `checksum_pairing.card_sha256_checksum`'s tolerant `getattr`),
it must ALSO match. An md5 match with a present-on-both sha256 MISMATCH is a loud anomaly (logged
at ERROR) - transfer is skipped and the caller falls through to real extraction, never a silent
downgrade to an md5-only transfer. md5 collisions are constructible; a present sha256 is exactly
the case this module has enough information to verify the "identical bytes" premise
cryptographically instead of assuming it, so it always overrides an md5-only pairing whenever both
sides have one. When sha256 is absent on either side, the pairing rests on md5 + the content-hash
assertion below alone - the pre-sha256, PR-1-only posture.

CONTENT-HASH ASSERTION: byte-identical files imply an identical perceptual hash (phash is a pure
function of pixel content - identical bytes decode to identical pixels). This is ASSERTED, not
merely trusted: the sibling's own `content_hash` (guaranteed by the currency query below to equal
the sibling CARD's own live `content_phash`) is compared against THIS card's own `content_phash`.
A mismatch here is impossible for two cards that are genuinely byte-identical, so observing one is
evidence of a REAL anomaly (a stale/incorrect md5 pairing, an actual md5 collision, or a
data-entry error) - logged loudly at ERROR, transfer skipped, never transferred anyway.

Neither anomaly path raises - both return `None` from `find_transfer_source`, and every caller's
own contract for a `None` result is "fall through to real extraction" (never "give up on this
card"), so a loud anomaly degrades to the pre-existing, already-correct behavior rather than
failing the whole batch/card.
"""

import logging
from typing import Optional

from django.db.models import F, Q, QuerySet

from cardpicker.checksum_pairing import card_sha256_checksum
from cardpicker.models import Card, ImageEvidence

logger = logging.getLogger(__name__)

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
    Bulk (F-expression-based) Q object expressing the md5 half of `ImageEvidence`'s own currency
    rule (see `image_evidence.current_evidence_queryset`'s own docstring for the single-card,
    literal-value form of the identical rule) - True (row stays CURRENT/eligible) unless the row's
    own stamped `md5_checksum` is non-null AND the related Card's live `md5_checksum` (reached via
    `related_prefix`, default `"card__"` i.e. `ImageEvidence.card`) is ALSO non-null AND the two
    disagree. Three-clause OR, not a single equality check, specifically so a NULL on either side
    (a legacy unstamped row, or a card whose source never carries an md5 at all) never excludes a
    row - SQL's three-valued logic means a bare `md5_checksum=F(...)` comparison would silently
    evaluate to NULL/false whenever either side is NULL, which is the OPPOSITE of the null-tolerant
    behavior this rule requires.
    """
    return (
        Q(md5_checksum__isnull=True)
        | Q(**{f"{related_prefix}md5_checksum__isnull": True})
        | Q(md5_checksum=F(f"{related_prefix}md5_checksum"))
    )


def _current_sibling_evidence_queryset(card: Card) -> "QuerySet[ImageEvidence]":
    """Every OTHER card's own CURRENT, full-manifest `ImageEvidence` row sharing `card`'s own
    md5_checksum - "current" here means the sibling row's own `content_hash` matches ITS OWN
    card's live `content_phash` (the pre-existing currency rule) AND its own stamped md5 agrees
    with its own card's live md5 (`md5_currency_q` above) - a stale sibling is never a transfer
    source, regardless of how "close" it looks. Full-manifest (`extractor_versions__has_keys` over
    every Stage C extractor key, imported lazily - see `stage_e_dispatch._stage_c_manifest_
    extractor_keys`'s own docstring for why this module-boundary import stays call-time-only) -
    a partially-extracted sibling (e.g. itself mid-transfer-chain, which never actually happens
    since transfer always writes every manifest key at once, but guarded regardless) is never a
    source either. Most-recently-updated first, in case more than one qualifying sibling somehow
    exists (rare - md5 groups are usually small)."""
    from cardpicker.management.commands.run_image_evidence_cohort import (
        MANIFEST_EXTRACTOR_KEYS,
    )

    return (
        ImageEvidence.objects.filter(card__md5_checksum=card.md5_checksum)
        .exclude(card_id=card.pk)
        .filter(content_hash=F("card__content_phash"))
        .filter(extractor_versions__has_keys=list(MANIFEST_EXTRACTOR_KEYS))
        .filter(md5_currency_q())
        .select_related("card")
        .order_by("-updated_at")
    )


def find_transfer_source(card: Card) -> Optional[ImageEvidence]:
    """
    Returns the md5-sibling `ImageEvidence` row eligible to be copied onto `card`, or `None`. Pure
    lookup + the pairing/content-hash asserts (module docstring) - never writes anything
    (`transfer_evidence` below does the write). `None` in every one of these cases:

    - `card.md5_checksum` is `None` (a "group of one", issue #473's ruling 3) - the overwhelming
      majority of the catalog until the backfill enrolls more cards.
    - `card.content_phash` is `None` - no stable hash yet to key this card's OWN
      `(card, content_hash)` row against, matching every other "no stable hash yet" early-return
      in this codebase (`local_calculate_verdicts._eligible_cards_queryset`'s own callers, etc.).
    - No qualifying sibling row exists at all - the ordinary, non-anomalous "nothing to transfer
      from yet" outcome.
    - The sha256 pairing check fails (both sides carry a sha256, and they disagree) - a LOUD
      anomaly, logged at ERROR.
    - The content-hash assertion fails (this card's own `content_phash` disagrees with the
      sibling's) - also a LOUD anomaly, logged at ERROR.

    Only the last two are actually anomalous; the first three are all just "not eligible yet".
    """
    if card.md5_checksum is None or card.content_phash is None:
        return None

    sibling_evidence = _current_sibling_evidence_queryset(card).first()
    if sibling_evidence is None:
        return None

    sibling_card = sibling_evidence.card

    card_sha256 = card_sha256_checksum(card)
    sibling_sha256 = card_sha256_checksum(sibling_card)
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
        return None

    return sibling_evidence


def transfer_evidence(card: Card, source: ImageEvidence, run_id: Optional[str] = None) -> ImageEvidence:
    """
    THE WRITE half of evidence transfer - copies every extractor field + `extractor_versions` from
    `source` (an md5-sibling's own CURRENT, full-manifest row, already vetted by
    `find_transfer_source`'s own pairing/content-hash asserts - this function trusts its caller to
    have called that first, it re-verifies nothing itself) onto `card`'s own `(card, content_hash)`
    row. Same `get_or_create` + field-merge shape as `image_evidence.persist_evidence` (reused
    convention, not reinvented) - a re-run against the same pair updates in place rather than
    erroring on the unique constraint.

    Stamps `md5_checksum`/`sha256_checksum` from `card` itself (the TARGET, never `source` -
    `find_transfer_source` already verified `card.md5_checksum == source.card.md5_checksum`, so
    stamping the target's own live value is equivalent to copying the sibling's, but stays correct
    even in the degenerate case where the two could ever disagree post-verification-race) and sets
    `transferred=True` + `transferred_from_card_id=source.card_id`.

    INTERIM STAGE D GUARD (issue #473 PR-2, temporary by design - see `ImageEvidence.transferred`'s
    own model-field docstring and `local_calculate_verdicts._eligible_cards_queryset`'s own
    coordination-note comment): `transferred=True` here is what that guard reads to exclude this
    card from the three Stage D calculators (join-key/fallback/slow-path) until PR-3's group-level
    vote pooling lands and removes the guard - a transferred row's own machine "observation" is the
    SAME bytes a sibling card already voted from, not an independent one.
    """
    evidence, _ = ImageEvidence.objects.get_or_create(card_id=card.pk, content_hash=card.content_phash)
    for field_name in _TRANSFERABLE_FIELD_NAMES:
        setattr(evidence, field_name, getattr(source, field_name))
    evidence.extractor_versions = dict(source.extractor_versions)
    evidence.run_id = run_id
    evidence.md5_checksum = card.md5_checksum
    evidence.sha256_checksum = card_sha256_checksum(card)
    evidence.transferred = True
    evidence.transferred_from_card_id = source.card_id
    evidence.save()
    return evidence


__all__ = [
    "md5_currency_q",
    "find_transfer_source",
    "transfer_evidence",
]

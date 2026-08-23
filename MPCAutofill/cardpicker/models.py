import itertools
import re
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional, Sequence

from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.db import connection, models, transaction
from django.utils import dateformat, timezone
from django.utils.translation import gettext_lazy

from cardpicker.constants import DATE_FORMAT
from cardpicker.schema_types import CanonicalArtistClass as SerialisedCanonicalArtist
from cardpicker.schema_types import CanonicalCardClass as SerialisedCanonicalCard
from cardpicker.schema_types import Card as SerialisedCard
from cardpicker.schema_types import CardType, ChildElement, Game, PrintingCandidate
from cardpicker.schema_types import PrintingTagStatus as SerialisedPrintingTagStatus
from cardpicker.schema_types import Source as SerialisedSource
from cardpicker.schema_types import SourceContribution, SourceType
from cardpicker.schema_types import Tag as SerialisedTag
from cardpicker.schema_types import (
    TagVoteDisplayStatus as SerialisedTagVoteDisplayStatus,
)
from cardpicker.sources.source_types import SourceTypeChoices

# Card.tag_vote_statuses' 5-way DB status collapsed to the 2-way distinction the frontend
# needs (Proposal H §4.4′, issue #184) - resolved_apply/resolved_reject both read as
# "resolved" (consensus has spoken, whichever direction), contested/unresolved both read as
# "suggested" (votes exist but haven't cleared consensus). Deliberately a closed mapping, not
# a fallback default - a status this dict doesn't cover (i.e. pending_approval) must be
# excluded from the serialised payload entirely (sensitive-tag co-sign queue, see
# docs/features/moderation.md), never guessed into one bucket or the other.
_TAG_VOTE_DISPLAY_STATUS_BY_DB_STATUS = {
    "resolved_apply": SerialisedTagVoteDisplayStatus.resolved,
    "resolved_reject": SerialisedTagVoteDisplayStatus.resolved,
    "contested": SerialisedTagVoteDisplayStatus.suggested,
    "unresolved": SerialisedTagVoteDisplayStatus.suggested,
    # "pending_approval" intentionally absent - see docstring above.
}

# Attribute name `Prefetch(..., to_attr=...)` writes the per-card list of machine-suggested
# printing votes to - see `suggested_printing_votes_prefetch()` below. Shared constant so the
# prefetch call site and `Card.serialise()`'s read site can't drift on the attribute name.
SUGGESTED_PRINTING_VOTES_ATTR = "_suggested_printing_votes"

# Attribute name `attach_suggested_filter_tags_overlay()` stamps the per-card precomputed
# `suggestedFilterTagNames` list onto - see that function and `Card._suggested_filter_tag_names`
# below. Shared constant so the two sides can't drift on the attribute name, mirroring
# `SUGGESTED_PRINTING_VOTES_ATTR` above.
SUGGESTED_FILTER_TAG_NAMES_ATTR = "_suggested_filter_tag_names_precomputed"


class Games(models.TextChoices):
    MTG = (Game.MTG.value, gettext_lazy(Game.MTG.value))


class Faces(models.TextChoices):
    FRONT = ("FRONT", gettext_lazy("Front"))
    BACK = ("BACK", gettext_lazy("Back"))


class CardTypes(models.TextChoices):
    CARD = (CardType.CARD.name, gettext_lazy(CardType.CARD.value.title()))
    CARDBACK = (CardType.CARDBACK.name, gettext_lazy(CardType.CARDBACK.value.title()))
    TOKEN = (CardType.TOKEN.name, gettext_lazy(CardType.TOKEN.value.title()))


class Cardstocks(models.TextChoices):
    S30_NONFOIL = ("S30_FOIL", gettext_lazy("S30 (Standard Smooth)"))
    S30_FOIl = ("S30_NONFOIL", gettext_lazy("S30 (Standard Smooth) — Foil"))
    S33_NONFOIL = ("S33_FOIL", gettext_lazy("S33 (Superior Smooth)"))
    S33_FOIl = ("S33_NONFOIL", gettext_lazy("S33 (Superior Smooth) — Foil"))
    M31_NONFOIL = ("M31_FOIL", gettext_lazy("M31 (Linen)"))
    M31_FOIl = ("M31_NONFOIL", gettext_lazy("M31 (Linen) — Foil"))
    P10_NONFOIL = ("P10_NONFOIL", gettext_lazy("P10 (Plastic)"))


class CanonicalExpansion(models.Model):
    identifier = models.UUIDField(unique=True)
    code = models.CharField(unique=True)
    name = models.CharField(unique=True)
    game = models.CharField(max_length=20, choices=Games.choices)

    def __str__(self) -> str:
        return f"[{self.code.upper()}] {self.name}"


class CanonicalArtist(models.Model):
    name = models.CharField(unique=True)

    def __str__(self) -> str:
        return self.name

    def serialise(self) -> SerialisedCanonicalArtist:
        return SerialisedCanonicalArtist(name=self.name)


class CanonicalCard(models.Model):
    identifier = models.UUIDField(unique=True)
    canonical_id = models.UUIDField(null=True, blank=True)
    name = models.TextField(db_index=True)
    artist = models.ForeignKey(to=CanonicalArtist, on_delete=models.CASCADE)
    expansion = models.ForeignKey(to=CanonicalExpansion, on_delete=models.CASCADE)
    collector_number = models.CharField(max_length=16)
    is_default = models.BooleanField(default=False)
    image_hash = models.BigIntegerField()
    small_thumbnail_url = models.CharField()
    medium_thumbnail_url = models.CharField()

    def __str__(self) -> str:
        return f"{self.name} [{self.expansion.code.upper()} {self.collector_number}]"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["expansion", "collector_number"],
                name="canonicalcard_unique_expansion_collector_number",
            ),
            models.UniqueConstraint(
                fields=["canonical_id"],
                condition=models.Q(is_default=True),
                name="canonicalcard_unique_default_per_canonical_id",
            ),
        ]

    def serialise(self) -> SerialisedCanonicalCard:
        return SerialisedCanonicalCard(
            canonicalId=str(self.canonical_id),
            collectorNumber=self.collector_number,
            expansionCode=self.expansion.code,
            expansionName=self.expansion.name,
            identifier=str(self.identifier),
            smallThumbnailUrl=self.small_thumbnail_url,
            mediumThumbnailUrl=self.medium_thumbnail_url,
        )

    def serialise_as_printing_candidate(self) -> PrintingCandidate:
        """
        Richer serialisation than `serialise()`, for the printing-tag picker - includes the
        artist name and the `CanonicalPrintingMetadata` sidecar fields that help a human
        disambiguate between candidates (full art, frame, release date), none of which
        `serialise()`'s embedded-in-a-resolved-Card shape needs.
        """
        metadata = getattr(self, "printing_metadata", None)
        frame_effects = metadata.frame_effects if metadata is not None else []
        return PrintingCandidate(
            identifier=str(self.identifier),
            canonicalId=str(self.canonical_id),
            expansionCode=self.expansion.code,
            expansionName=self.expansion.name,
            collectorNumber=self.collector_number,
            artist=self.artist.name,
            smallThumbnailUrl=self.small_thumbnail_url,
            mediumThumbnailUrl=self.medium_thumbnail_url,
            fullArt=metadata.full_art if metadata is not None else False,
            isBorderless=metadata.border_color == "borderless" if metadata is not None else False,
            frame=metadata.frame if metadata is not None else "",
            borderColor=metadata.border_color if metadata is not None else "",
            # curated subset of the `frame_effects` list with a dedicated attribute chip - see
            # cardpicker.attribute_tags / docs/features/printing-tags.md's questionFeed section
            # for why these three and not the (more numerous) rest of the field's values.
            isShowcase="showcase" in frame_effects,
            isExtendedArt="extendedart" in frame_effects,
            isEtched="etched" in frame_effects,
            releasedAt=metadata.released_at.isoformat() if metadata is not None and metadata.released_at else None,
            # Scryfall's illustration UUID, shared across every printing carrying the same
            # artwork - see CanonicalPrintingMetadata.illustration_id. Null-tolerant: the field
            # legitimately lacks a value for some printings (local_illustration.py:137 filters
            # on illustration_id__isnull=False for exactly this reason), so this stays optional
            # on PrintingCandidate rather than defaulting to a sentinel.
            illustrationId=(
                str(metadata.illustration_id) if metadata is not None and metadata.illustration_id else None
            ),
            # Scryfall's art-crop image URL for this printing - see
            # CanonicalPrintingMetadata.art_crop_url's own docstring for provenance. Null-tolerant
            # for the same two reasons illustrationId is above: metadata can be absent entirely,
            # and art_crop_url is `blank=True` so a printing can legitimately carry an empty
            # value - both collapse to None here so the frontend can fall back to
            # mediumThumbnailUrl rather than render a broken image.
            artCropUrl=metadata.art_crop_url if metadata is not None and metadata.art_crop_url else None,
        )


class CanonicalPrintingMetadata(models.Model):
    """
    Additive sidecar holding Scryfall printing-level fields not already captured by
    `CanonicalCard` (which already stores scryfall_id/oracle_id/set/collector_number/
    artist/image data via its `identifier`/`canonical_id`/`expansion`/`collector_number`
    fields). One row per `CanonicalCard`, populated by `import_scryfall_printing_metadata`.

    NOT EVERY FIELD HERE IS SCRYFALL DATA. `catalogued_printings_count` is computed by us,
    over our own rows - see its own comment. Every other field on this model is copied
    verbatim from a bulk-data row.
    """

    canonical_card = models.OneToOneField(
        to=CanonicalCard, on_delete=models.CASCADE, primary_key=True, related_name="printing_metadata"
    )
    full_art = models.BooleanField(default=False)
    border_color = models.CharField(max_length=20, blank=True)
    frame = models.CharField(max_length=10, blank=True)
    frame_effects = models.JSONField(default=list, blank=True)
    # Scryfall's own colour identity, copied verbatim (e.g. `["W", "U"]`, `[]` for colourless) -
    # same JSONField shape as frame_effects above. Motivation: a card's frame colour treatment
    # varies with its colour identity, which makes any fixed-position colour measurement of frame
    # geometry uninterpretable without it (a colour-homogeneous group of cards measured a
    # within-group colour spread of 8.8 at a fixed coordinate against a colour-diverse group's
    # 87.2 at the identical coordinate). Not consumed by any calculator yet - data availability
    # only, see printing_metadata_import.PrintingMetadataRow.color_identity.
    color_identity = models.JSONField(default=list, blank=True)
    # Scryfall's own type line verbatim (e.g. "Basic Land — Forest") - same CharField convention
    # as border_color/frame above. Identifies lands, the most colour-homogeneous group and
    # therefore the cleanest to measure colour identity's effect against (see color_identity
    # above). Not consumed by any calculator yet - data availability only.
    type_line = models.CharField(max_length=255, blank=True, default="")
    # Scryfall's own layout tag verbatim (e.g. "normal", "transform", "planar", "scheme") -
    # the same value `printing_metadata_import.PrintingMetadataRow.layout` already parses and
    # was, until issue #693, discarded after being checked against `DOUBLE_FACED_LAYOUTS`.
    # Persisted so downstream consumers can ask "is this printing physically sideways"
    # (`planar`/`scheme`, plus some `split`/`battle` cards) without re-deriving it from image
    # geometry - measured 2026-08-05: only 46 of 230,378 evidence rows are landscape
    # (width > height), because sideways cards are overwhelmingly rendered into a portrait
    # frame with rotated content, so aspect ratio cannot find them. Canonical metadata is the
    # only reliable source.
    layout = models.CharField(max_length=30, blank=True)
    promo_types = models.JSONField(default=list, blank=True)
    edhrec_rank = models.IntegerField(null=True, blank=True)
    # HOW MANY PRINTINGS OF THIS ORACLE CARD *WE* HAVE CATALOGUED - a COUNT over our own
    # `CanonicalCard` rows, not a number Scryfall reports. `import_scryfall_printing_metadata`
    # builds a Counter over `CanonicalCard.canonical_id` (the oracle id) and stores each row's
    # group size here; rows whose `canonical_id` is NULL (81 in production on 2026-07-29) are
    # stored as 1 by fiat, because there is no oracle group to count.
    #
    # RENAMED FROM `printings_count` 2026-07-29 (migration 0099). The old name, and the docs
    # written against it, asserted this was Scryfall's own printing total for the oracle card.
    # It never was, and the difference is not academic: this number cannot detect that our
    # catalogue holds fewer printings than Scryfall publishes, because it is derived entirely
    # from what our catalogue holds. Anything that wants "how many printings exist in reality"
    # must count rows in the bulk-data file, not read this column.
    catalogued_printings_count = models.IntegerField(default=0)
    released_at = models.DateField(null=True, blank=True)
    lang = models.CharField(max_length=5, default="en")
    # Scryfall's own art-crop image URL, straight from the same bulk-data dump this whole model
    # is populated from (image_uris.art_crop, or card_faces[0].image_uris.art_crop for
    # double-faced cards - see printing_metadata_import.PrintingMetadataRow.art_crop_url).
    # Local-first source for cardpicker.local_phash.get_or_compute_canonical_hash, which
    # previously always hit Scryfall's live REST API per candidate for this exact URL - data
    # already sitting in the same weekly bulk-data file this sidecar already parses (2026-07-19,
    # harvest-calculate pipeline Stage B - see docs/features/catalog-completion-plan.md).
    art_crop_url = models.CharField(blank=True, default="")
    # Scryfall's illustration UUID — identifies the artwork independently of any specific
    # printing. Populated by import_scryfall_printing_metadata (see that function and
    # PrintingMetadataRow.resolved_illustration_id for the single-face/double-face parsing).
    # Null-tolerant: some records legitimately lack it (e.g. faces without art). Indexed for
    # the Stage D illustration deduction calculator's in-memory join against CanonicalCard.
    illustration_id = models.UUIDField(null=True, blank=True, db_index=True)
    # EVERY FACE'S OWN illustration_id, not just the front's (2026-07-29). `illustration_id`
    # above is `PrintingMetadataRow.resolved_illustration_id`, which returns
    # `card_faces[0].illustration_id` for a multi-faced row - the FRONT face - and discards the
    # rest. Each face of a genuine double-faced card carries its OWN artwork and its own
    # `illustration_id` in the same bulk-data row we already parse (e.g. "Invasion of Tolvada //
    # The Broken Sky": front e505aa78-…, back e61d567e-…), so flattening to the front made a
    # back-face scan unattributable: the only illustration on file for that printing belonged to
    # the other side of the card. That gap is what
    # `local_illustration.SINGLE_FACED_ONLY_SKIP_REASON` existed to paper over.
    #
    # SHAPE: an ORDERED list, in Scryfall `card_faces` order (index 0 is always the front), of
    # `{"name": str, "illustration_id": str | None}`. Written only by
    # `printing_metadata_import.PrintingMetadataRow.face_illustrations`.
    #
    # EMPTY FOR EVERYTHING THAT IS NOT A GENUINE DOUBLE-FACED CARD. `split`/`adventure`/`flip`/
    # `aftermath`/`mutate`/`prototype` also nest multiple named modes under `card_faces`, but
    # those modes are printed on the SAME physical face - giving "Stomp" its own entry would
    # invent a second scannable side of "Bonecrusher Giant" that does not exist. The layout
    # allowlist is `printing_metadata_import.DOUBLE_FACED_LAYOUTS`, the same one
    # `get_back_face_names` already uses for exactly this distinction; single-faced rows have no
    # `card_faces` at all and are covered by the scalar `illustration_id` above.
    #
    # WHY JSON AND NOT `ArrayField`/RELATED ROWS. Two CORRELATED values per face (the face's name
    # is what `local_illustration.IllustrationIndex` keys a face-named scan on; the id alone is
    # unusable), which `ArrayField(UUIDField)` cannot carry without a second parallel array that
    # can desynchronise from the first. A related table would add ~2,500 rows and a JOIN to an
    # index build that is already a per-worker-cached catalog-wide hot path, to model an at-most-
    # two-element list. JSONField also matches `frame_effects`/`promo_types` on this same model,
    # so `_sync_printing_metadata`'s field-by-field `!=` diff already compares this shape
    # correctly (both sides are plain Python lists of dicts).
    face_illustrations = models.JSONField(default=list, blank=True)

    def __str__(self) -> str:
        return f"Printing metadata for {self.canonical_card}"

    class Meta:
        indexes = [
            # PARTIAL index over only the rows that HAVE per-face illustrations (~2,500 of
            # 113,224 live). Its consumer is
            # `local_illustration._illustration_index_version_stamp`, which must count them once
            # per calculator invocation to notice an in-place `face_illustrations` backfill -
            # exactly the "column populated by UPDATE, so neither max pk nor row count moves"
            # blind spot that stamp's fifth term already documents for `illustration_id`. Without
            # a predicate matching the count's own `WHERE`, that term is a 113k-row seq scan on a
            # path whose whole contract is O(batch); with it, it is an index-only scan of the
            # 2,500-row subset. NOT a GIN index: nothing filters BY a face illustration value in
            # SQL on a hot path (`printings_for_illustration`'s containment term is a read-side
            # narrowing called at most once per resolved card), so GIN's containment support
            # would be paid for and unused.
            models.Index(
                fields=["canonical_card"],
                condition=~models.Q(face_illustrations=[]),
                name="cpm_face_illustrations_present",
            )
        ]


class CanonicalOracleCard(models.Model):
    """
    Oracle-level facts - identical across every printing of a card - keyed on `canonical_id`
    (Scryfall's oracle id), populated by `oracle_card_import.import_scryfall_oracle_cards` from
    the `oracle_cards` bulk-data cache. Split out of `CanonicalPrintingMetadata`, which is 1:1
    with `CanonicalCard` (i.e. per PRINTING): measured 2026-08-22, 113,224
    `CanonicalPrintingMetadata` rows carried oracle-level facts duplicated across only 35,990
    distinct oracle cards actually represented in this catalogue (~3.15x duplication) - this
    table holds each oracle card's facts exactly once regardless of how many printings exist.

    Not every `CanonicalCard` has a matching row here: rows with `canonical_id=None` (81
    measured 2026-07-29, see `CanonicalPrintingMetadata.catalogued_printings_count`'s own
    comment for the same population) have no oracle card to look up at all - callers must
    treat a missing match as expected, not an error.

    `color_identity`/`type_line` ALSO still live on `CanonicalPrintingMetadata` - this table
    duplicates rather than replaces them there; see `oracle_card_import`'s module docstring for
    why the old columns were left in place.
    """

    canonical_id = models.UUIDField(unique=True, primary_key=True)
    oracle_text = models.TextField(blank=True, default="")
    cmc = models.FloatField(default=0)
    colors = models.JSONField(default=list, blank=True)
    color_identity = models.JSONField(default=list, blank=True)
    type_line = models.CharField(max_length=255, blank=True, default="")
    legalities = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return f"Oracle card {self.canonical_id}"


class Source(models.Model):
    key = models.CharField(max_length=50, unique=True)  # must be a valid HTML id
    user = models.ForeignKey(to=User, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=50, unique=True)  # human-readable name
    identifier = models.CharField(max_length=200, unique=True)  # e.g. drive ID, root directory path
    source_type = models.CharField(
        max_length=20, choices=SourceTypeChoices.choices, default=SourceTypeChoices.GOOGLE_DRIVE
    )
    external_link = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=400, blank=True)
    ordinal = models.IntegerField(default=0)  # TODO: why is this not unique?

    def __str__(self) -> str:
        qty_total, qty_cards, qty_cardbacks, qty_tokens, _ = self.count()
        return (
            f"[{self.ordinal}.] {self.name} "
            f"[{qty_total} total: {qty_cards} cards, {qty_cardbacks} cardbacks, {qty_tokens} tokens]"
        )

    def count(self) -> tuple[str, str, str, str, float]:
        # return the number of cards that this Source created, and the Source's average DPI
        qty_cards = Card.objects.filter(source=self).filter(card_type=CardTypes.CARD).count()
        qty_cardbacks = Card.objects.filter(source=self).filter(card_type=CardTypes.CARDBACK).count()
        qty_tokens = Card.objects.filter(source=self).filter(card_type=CardTypes.TOKEN).count()
        qty_all = qty_cards + qty_cardbacks + qty_tokens

        # if this source has any cards/cardbacks/tokens, average the dpi of all of their things
        avg_dpi = 0
        if qty_all > 0:
            avg_dpi = int(
                (Card.objects.filter(source=self).aggregate(models.Sum("dpi"))["dpi__sum"] if qty_cards > 0 else 0)
                / qty_all
            )
        return (
            f"{qty_all :,d}",
            f"{qty_cards :,d}",
            f"{qty_cardbacks :,d}",
            f"{qty_tokens :,d}",
            avg_dpi,
        )

    class Meta:
        ordering = ["ordinal"]

    def serialise(self) -> SerialisedSource:
        # note: `identifier` should not be exposed here.
        return SerialisedSource(
            pk=self.pk,
            key=self.key,
            name=self.name,
            sourceType=SourceType(SourceTypeChoices[self.source_type].label),
            externalLink=self.external_link,
            description=self.description,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.serialise().model_dump()


def summarise_contributions() -> tuple[list[SourceContribution], dict[str, int], int]:
    """
    Report on the number of cards, cardbacks, and tokens that each Source has, as well as the average DPI across all
    three card types.
    Rawdogging the SQL here to minimise the number of hits to the database. I might come back to this at some point
    to rewrite in Django ORM at a later point.
    """

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                cardpicker_source.name,
                cardpicker_source.identifier,
                cardpicker_source.source_type,
                cardpicker_source.external_link,
                cardpicker_source.description,
                cardpicker_source.ordinal,
                COALESCE(SUM(cardpicker_card.dpi), 0),
                COUNT(cardpicker_card.dpi),
                COALESCE(SUM(cardpicker_card.size), 0)
            FROM cardpicker_source
            LEFT JOIN cardpicker_card ON cardpicker_source.id = cardpicker_card.source_id
            GROUP BY cardpicker_source.name,
                cardpicker_source.identifier,
                cardpicker_source.source_type,
                cardpicker_source.external_link,
                cardpicker_source.description,
                cardpicker_source.ordinal
            ORDER BY cardpicker_source.ordinal, cardpicker_source.name
            """
        )
        results_1 = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                cardpicker_source.identifier,
                cardpicker_card.card_type,
                COUNT(cardpicker_card.card_type)
            FROM cardpicker_source
            LEFT JOIN cardpicker_card ON cardpicker_source.id = cardpicker_card.source_id
            GROUP BY cardpicker_source.identifier, cardpicker_card.card_type
            """
        )
        results_2 = cursor.fetchall()

    source_card_count_by_type: dict[str, dict[str, int]] = defaultdict(dict)
    card_count_by_type: dict[str, int] = {card_type: 0 for card_type in CardTypes}
    for identifier, card_type, count in results_2:
        if card_type is not None:
            source_card_count_by_type[identifier][card_type] = count
            card_count_by_type[card_type] += count
    sources = []
    total_database_size = 0
    for (
        name,
        identifier,
        source_type,
        external_link,
        description,
        ordinal,
        total_dpi,
        total_count,
        total_size,
    ) in results_1:
        # note: `identifier` should not be exposed here.
        sources.append(
            SourceContribution(
                name=name,
                sourceType=SourceType(SourceTypeChoices[source_type].label),
                externalLink=external_link,
                description=description,
                qtyCards=f"{source_card_count_by_type[identifier].get(CardTypes.CARD, 0):,d}",
                qtyCardbacks=f"{source_card_count_by_type[identifier].get(CardTypes.CARDBACK, 0) :,d}",
                qtyTokens=f"{source_card_count_by_type[identifier].get(CardTypes.TOKEN, 0) :,d}",
                avgdpi=f"{(total_dpi / total_count):.2f}" if total_count > 0 else "0",
                size=f"{(total_size / 1_000_000_000):.2f} GB",
            )
        )
        total_database_size += total_size
    return sources, card_count_by_type, total_database_size


class PrintingTagStatus(models.TextChoices):
    """
    Denormalised cache of `cardpicker.printing_consensus.resolve_printing`'s outcome for a `Card`,
    kept in lockstep with `Card.inferred_canonical_card` by `resolve_and_persist_printing` - purely so
    that "which cards still need a human to tag" can be a plain indexed query instead of recomputing
    consensus for every row.
    """

    UNRESOLVED = "unresolved", gettext_lazy("Unresolved")
    RESOLVED = "resolved", gettext_lazy("Resolved")
    NO_MATCH = "no_match", gettext_lazy("No Match")


class ArtistVoteStatus(models.TextChoices):
    """
    Denormalised cache of `cardpicker.artist_consensus.resolve_artist`'s outcome for a `Card`,
    kept in lockstep with `Card.inferred_canonical_artist` by `resolve_and_persist_artist` - same
    purpose as `PrintingTagStatus` above.
    """

    UNRESOLVED = "unresolved", gettext_lazy("Unresolved")
    RESOLVED = "resolved", gettext_lazy("Resolved")
    UNKNOWN = "unknown", gettext_lazy("Unknown")
    CONTESTED = "contested", gettext_lazy("Contested")


class IllustrationVoteStatus(models.TextChoices):
    """
    Denormalised cache of `cardpicker.illustration_consensus.resolve_illustration`'s outcome for a
    `Card`, kept in lockstep with `Card.inferred_illustration_id` by
    `resolve_and_persist_illustration` - same purpose as `PrintingTagStatus`/`ArtistVoteStatus`
    above, and the same four members as `ArtistVoteStatus` because the outcome spaces match
    exactly (a named identity, an explicit "no known identity", or neither).

    UNKNOWN here means CONSENSUS SAYS THERE IS NO KNOWN ARTWORK IDENTITY (enough agents voted
    `is_unknown=True`) - a positive finding, e.g. a custom/altered image with no Scryfall artwork
    behind it. It is NOT "we don't know yet", which is UNRESOLVED. See
    `illustration_consensus`'s module docstring for why `is_unknown` is a full participant in the
    tally rather than an abstention.
    """

    UNRESOLVED = "unresolved", gettext_lazy("Unresolved")
    RESOLVED = "resolved", gettext_lazy("Resolved")
    UNKNOWN = "unknown", gettext_lazy("Unknown")
    CONTESTED = "contested", gettext_lazy("Contested")


class TagVoteStatus(models.TextChoices):
    """
    Per-tag status stored in `Card.tag_vote_statuses` (a JSONField, not a plain model field -
    see that field's own comment for why - so this isn't wired up as a `choices=` kwarg
    anywhere, just symbolic constants for `cardpicker.tag_consensus` to use instead of raw
    strings). Written by `resolve_and_persist_tag_votes`.
    """

    RESOLVED_APPLY = "resolved_apply", gettext_lazy("Resolved (apply)")
    RESOLVED_REJECT = "resolved_reject", gettext_lazy("Resolved (reject)")
    CONTESTED = "contested", gettext_lazy("Contested")
    UNRESOLVED = "unresolved", gettext_lazy("Unresolved")
    # sensitive tags only (Tag.moderation_class == SENSITIVE): the crowd's consensus clears
    # every normal threshold but awaits a privileged (moderator/admin) co-sign - served by the
    # moderation queue, excluded from the public tag queue. See docs/features/moderation.md.
    PENDING_APPROVAL = "pending_approval", gettext_lazy("Pending approval")


class Card(models.Model):
    card_type = models.CharField(max_length=20, choices=CardTypes.choices, default=CardTypes.CARD)
    identifier = models.CharField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    priority = models.IntegerField(default=0)
    source = models.ForeignKey(Source, on_delete=models.CASCADE)
    source_verbose = models.CharField(max_length=50)
    folder_location = models.CharField(max_length=300)
    dpi = models.IntegerField(default=0)
    searchq = models.CharField(max_length=200)
    extension = models.CharField(max_length=200)
    date_created = models.DateTimeField(default=datetime.now)
    date_modified = models.DateTimeField(default=datetime.now)
    size = models.IntegerField()
    tags = ArrayField(models.CharField(max_length=20), default=list, blank=True)  # null=True is just for admin panel
    language = models.CharField(max_length=5)
    canonical_card = models.ForeignKey(
        CanonicalCard, on_delete=models.SET_NULL, blank=True, null=True, related_name="canonical_card"
    )
    canonical_artist = models.ForeignKey(to=CanonicalArtist, on_delete=models.CASCADE, blank=True, null=True)
    inferred_canonical_card = models.ForeignKey(
        CanonicalCard, on_delete=models.SET_NULL, blank=True, null=True, related_name="inferred_canonical_card"
    )
    printing_tag_status = models.CharField(
        max_length=10, choices=PrintingTagStatus.choices, default=PrintingTagStatus.UNRESOLVED, db_index=True
    )
    # artist-vote consensus outcome - only ever surfaced in `serialise()` when neither
    # `canonical_card`/`canonical_artist` (confirmed indexing match) nor
    # `inferred_canonical_card` (a resolved printing-tag vote, which carries its own artist)
    # are set - see the fallback chain in `serialise()` below.
    inferred_canonical_artist = models.ForeignKey(
        to=CanonicalArtist, on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    artist_vote_status = models.CharField(
        max_length=10, choices=ArtistVoteStatus.choices, default=ArtistVoteStatus.UNRESOLVED, db_index=True
    )
    # illustration-vote consensus outcome (`cardpicker.illustration_consensus`), written by
    # `resolve_and_persist_illustration` for EVERY member of this card's md5 identity group at
    # once - byte-identical images are one identification target, so they cannot be allowed to
    # disagree about which artwork they depict.
    #
    # A plain `UUIDField`, NOT a ForeignKey, mirroring `CardIllustrationVote.illustration_id` and
    # `CanonicalPrintingMetadata.illustration_id`: there is no `CanonicalIllustration` table and
    # this field must not cause one to exist (see `CardIllustrationVote`'s own "NOT A FOREIGN KEY"
    # section). It also means this field carries NO dependency on imported Scryfall reference
    # data, which per the 2026-07-29 owner ruling is informative and possibly stale rather than
    # ground truth - the uuid stored here is exactly what agents voted for, and turning it into
    # printings is a live join every consumer performs itself.
    #
    # Only meaningful while `illustration_vote_status == RESOLVED`; NULL for every other status,
    # including UNKNOWN (which asserts there IS no identity, not that one is being withheld).
    inferred_illustration_id = models.UUIDField(null=True, blank=True, db_index=True)
    illustration_vote_status = models.CharField(
        max_length=10, choices=IllustrationVoteStatus.choices, default=IllustrationVoteStatus.UNRESOLVED, db_index=True
    )
    # Per-tag vote status, written by cardpicker.tag_consensus.resolve_and_persist_tag_votes:
    # {tag.name: "resolved_apply" | "resolved_reject" | "contested" | "unresolved" |
    # "pending_approval" (sensitive tags awaiting a privileged co-sign)}. An absent
    # key means no votes at all for that tag on this card - entries are never written for a
    # tag with zero votes. Bookkeeping alongside the existing `tags` array/overlay-merge logic
    # above, not a replacement for it. INVARIANT: keys are `Tag.name` values, which must stay
    # stable - renaming a Tag orphans its entries here and (per docs/federation-v1.md) breaks
    # cross-instance verdict portability, since tags travel by name in that format too. A Tag
    # rename is a data migration, not a plain edit.
    tag_vote_statuses = models.JSONField(default=dict, blank=True)
    # a lowercase CanonicalExpansion.code guessed from a lone set-code bracket token in the
    # source filename (e.g. "[MH3]") - not resolved to a specific printing (no collector
    # number was present to pair with it), just a ranking hint for get_ranked_printing_candidates
    expansion_hint = models.CharField(max_length=10, blank=True, db_index=True)
    # Perceptual hash (imagehash.phash) of THIS card's own uploaded image - NOT the same concept
    # as CanonicalCard.image_hash above (that's a Scryfall CANDIDATE image's hash, computed
    # lazily by local_phash.get_or_compute_canonical_hash; this is OUR OWN uploaded image's
    # hash). Was a dead field named `image_hash` (migration 0046) - always written as a literal
    # 0 placeholder by update_database and never read anywhere; repurposed and renamed here
    # (2026-07-16, hash-at-ingest work, docs/features/printing-tags.md) into a real, populated
    # column, since a same-named-but-different-purpose dead field sitting next to a live one
    # would be a permanent footgun for future readers.
    #
    # Dual consumer, one field: (1) cardpicker.local_clustering's two-threshold dedup (d=0 vote
    # propagation, d<=2 candidate narrowing) - a per-run DB read instead of a per-run fetch; (2)
    # docs/federation-v1.md's reserved `content_hash` verdict-exchange field ("the planned
    # upgrade path for surviving re-uploads"). Cross-instance interchange contract: algorithm is
    # imagehash.phash, hash_size=8 (the library default, 64-bit output - inherited from
    # CanonicalCard.image_hash's pre-existing convention, not deliberately chosen; changing it
    # is a re-hash migration, not a config flip, since federation peers would need to agree on
    # the same params). NULL = not yet computed (see cardpicker.local_phash's ingest/backfill
    # helpers) - distinct from a real hash value of 0, which is why this is nullable rather than
    # reusing 0 as a sentinel the way CanonicalCard.image_hash does (that field predates this
    # decision; not retrofitted here, out of scope).
    content_phash = models.BigIntegerField(null=True, blank=True, db_index=True)
    # md5 checksum substrate (issue #473 PR-1, docs/features/catalog-completion-plan.md's
    # #442-sourced "index Drive checksums" leverage) - the Google Drive API's own `md5Checksum`
    # field on a file listing, copied verbatim from the same folder-listing metadata
    # `transform_image_into_object` already reads (see `cardpicker.sources.api.Image.
    # md5_checksum`) - never computed locally, never derived from image bytes we don't hold (the
    # governing "we index, we do not store images" premise in CLAUDE.md). NULL means "no
    # checksum known for this card" - either the source type doesn't carry one at all (LOCAL_FILE
    # - see `LocalFile.get_all_images_inside_folder`, which never sets it) or the Drive listing
    # simply hadn't been walked with checksum-awareness yet (pre-#473 cards, until
    # `backfill_md5_checksums` or an ordinary re-scan through `update_database` fills it in). Per
    # the owner's ruling 3 on issue #473: a NULL or otherwise-unique md5 is a "group of one" -
    # every future group-level pooling change (PR-2/PR-3) must be a provable no-op for that
    # degenerate case, so this field is NEVER invented/guessed when the listing doesn't supply
    # one. Deliberately a plain string (Drive's own hex-digest format, not re-encoded) rather than
    # a BigIntegerField like `content_phash`/`CanonicalCard.image_hash` - md5 is an opaque
    # cross-source identity key here, not a distance-comparable perceptual hash, so there's no
    # reason to pay the twos-complement int-packing cost those two fields exist for.
    md5_checksum = models.CharField(max_length=32, null=True, blank=True, db_index=True)
    # sha256 checksum (owner-approved addition, 2026-07-25 evening, issue #473 PR-1's comment
    # thread) - same listing walk, same seam, same "copied verbatim, never computed locally"
    # rule as md5_checksum above. Exists for one binding reason, not as a second copy of the same
    # idea: PR-2's evidence-transfer premise ("identical bytes => identical evidence") has to be
    # cryptographic, not merely probabilistic - md5 collisions are constructible, so a transfer
    # gated on md5 alone would be forgeable. The BINDING consequence (stated in that same comment,
    # cited here so it isn't re-derived): whenever BOTH cards in a transfer have a sha256 on file,
    # transfer requires md5 AND sha256 to match; an md5 match with a sha256 mismatch is a loud
    # anomaly (log + skip + flag), never a silent fallback to md5-only. Groups still key on md5
    # ONLY (ruling 1 on issue #473 predates this addition and is unchanged by it) - sha256 is the
    # transfer safety pairing and the future federation join key (issue #451 item 5), not a second
    # grouping axis. NULL for exactly the same reasons md5_checksum can be NULL (LOCAL_FILE
    # sources, or a Drive listing walked before this field existed) - never invented, never
    # backfilled from image bytes we don't hold.
    sha256_checksum = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    def __str__(self) -> str:
        return (
            f"[{self.source.name}] "
            f"<{self.language}> "
            f"{self.name} "
            f"[Type: {self.card_type}, "
            f"Identifier: {self.identifier}, "
            f"Uploaded: {self.date_created.strftime('%d/%m/%Y')}, "
            f"Priority: {self.priority}]"
        )

    def _suggested_canonical_card(self) -> Optional[SerialisedCanonicalCard]:
        """
        The catalog's own best unconfirmed guess at this card's printing (Proposal H §4.4′,
        issue #184) - the printing named by a machine-cast (`VoteSource.DEDUCTION`/`OCR`)
        `CardPrintingTag` vote, mirroring `question_feed.py`'s `_confirm_suggestion_item`
        `ai_vote` lookup exactly (same filter, same "first" semantics) so the two surfaces
        can't drift on what counts as "machine-suggested." Exposes an already-cast vote,
        never computes a new ranking/consensus - `get_ranked_printing_candidates()`'s
        Levenshtein-ranked candidate search is a distinct, deliberately NOT-reused mechanism
        here (too expensive to run per-card across a bulk result set; see
        docs/features/printing-tags.md).

        Only populated while `printing_tag_status != RESOLVED` (never redundant with the
        already-resolved `canonicalCard`), and only when this `Card` came from a queryset
        that attached `suggested_printing_votes_prefetch()` - deliberately does NOT fall back
        to a live per-card query when that prefetch is absent, so forgetting to attach it on
        a new bulk call site fails safe (silently `None`) rather than silently reintroducing
        an N+1 query across the whole result set. Falls back to a single bounded query only
        when called directly on an un-prefetched instance outside a bulk context (e.g. a
        one-off shell/test lookup) - never the code path any bulk endpoint should exercise.
        """
        if self.printing_tag_status == PrintingTagStatus.RESOLVED:
            return None
        votes = getattr(self, SUGGESTED_PRINTING_VOTES_ATTR, None)
        if votes is None:
            votes = list(
                self.printing_tags.filter(source__in=[VoteSource.DEDUCTION, VoteSource.OCR], is_no_match=False)
                .select_related("printing__expansion")
                .order_by("pk")[:1]
            )
        if not votes or votes[0].printing is None:
            return None
        return votes[0].printing.serialise()

    def _suggested_filter_tag_names(self) -> list[str]:
        """
        Tag names leaning APPLY for this card strongly enough to preselect as a /editor filter
        chip (owner-ratified 2026-07-22 vote-weight scenario matrix, decision D6) - see
        `cardpicker.tag_consensus.get_suggested_filter_tags_overlay`'s own docstring for the
        exact qualifying condition.

        Prefers a precomputed value stamped onto `SUGGESTED_FILTER_TAG_NAMES_ATTR` by
        `attach_suggested_filter_tags_overlay()` (call that on the full list of `Card` instances
        a response will serialise with `include_suggested_filter_tags=True` BEFORE calling
        `.serialise(...)` on any of them - this is what `post_cards` in views.py does, one
        `get_suggested_filter_tags_overlay()` call for the whole response instead of one per
        card). Falls back to a single bounded per-card query only when called on an
        un-prefetched instance outside a bulk context (e.g. a one-off shell/test lookup) - never
        the code path any bulk endpoint should exercise, mirroring `_suggested_canonical_card`'s
        own fail-safe-not-N+1 fallback above.
        """
        precomputed = getattr(self, SUGGESTED_FILTER_TAG_NAMES_ATTR, None)
        if precomputed is not None:
            return precomputed

        from cardpicker.tag_consensus import (
            get_suggested_filter_tags_overlay,  # local import - avoids a models<->tag_consensus cycle
        )

        return get_suggested_filter_tags_overlay([self.pk]).get(self.pk, [])

    def _serialise_tag_vote_statuses(self) -> dict[str, SerialisedTagVoteDisplayStatus]:
        """
        Collapses `tag_vote_statuses` (5-way DB status) to the 2-way suggested/resolved
        distinction the frontend needs (Proposal H §4.4′'s "Looks retro-frame? ✓" confirm
        chip, issue #184) - see `_TAG_VOTE_DISPLAY_STATUS_BY_DB_STATUS`'s own docstring for
        the mapping and why `pending_approval` tags are dropped rather than bucketed.
        """
        return {
            tag_name: _TAG_VOTE_DISPLAY_STATUS_BY_DB_STATUS[status]
            for tag_name, status in self.tag_vote_statuses.items()
            if status in _TAG_VOTE_DISPLAY_STATUS_BY_DB_STATUS
        }

    def serialise(
        self, *, include_suggested_printing: bool = False, include_suggested_filter_tags: bool = False
    ) -> SerialisedCard:
        # Explicit if/elif chain (rather than a nested-ternary fallback) so the rung that
        # actually supplied the artist is captured as it's found, not re-derived afterwards by
        # checking which other fields are empty - that "all others empty" style of check would
        # silently misclassify if this chain ever grows a fifth rung. `canonicalArtistIsFromVoteOnly`
        # (used by the frontend's "wrong?" affordance to distinguish a confidently-known artist
        # from a vote-derived one) and the debug-only `canonicalArtistSource` field both derive
        # directly from `artist_source`, so they can never drift out of sync with this chain.
        artist_source: str | None
        resolved_artist: CanonicalArtist | None
        if self.canonical_artist is not None:
            artist_source, resolved_artist = "canonical_artist", self.canonical_artist
        elif self.canonical_card is not None:
            artist_source, resolved_artist = "canonical_card", self.canonical_card.artist
        elif self.inferred_canonical_card is not None:
            artist_source, resolved_artist = "inferred_canonical_card", self.inferred_canonical_card.artist
        elif self.inferred_canonical_artist is not None:
            artist_source, resolved_artist = "inferred_canonical_artist", self.inferred_canonical_artist
        else:
            artist_source, resolved_artist = None, None

        return SerialisedCard(
            identifier=self.identifier,
            cardType=CardType(self.card_type),
            name=self.name,
            priority=self.priority,
            # TODO: consider only including source_pk here. reference the other data from sourceDocuments in frontend
            source=self.source.key,
            sourceName=self.source.name,
            sourceId=self.source.pk,
            sourceVerbose=self.source_verbose,
            sourceType=self.get_source_type(),
            sourceExternalLink=self.get_source_external_link(),
            dpi=self.dpi,
            searchq=self.searchq,
            extension=self.extension,
            dateCreated=dateformat.format(self.date_created, DATE_FORMAT),
            dateModified=dateformat.format(self.date_modified, DATE_FORMAT),
            size=self.size,
            smallThumbnailUrl=self.get_small_thumbnail_url() or "",
            mediumThumbnailUrl=self.get_medium_thumbnail_url() or "",
            tags=sorted(self.tags),
            language=self.language,
            canonicalCard=(
                self.canonical_card.serialise()
                if self.canonical_card
                else (self.inferred_canonical_card.serialise() if self.inferred_canonical_card else None)
            ),
            layout=self.get_layout(),
            canonicalArtist=resolved_artist.serialise() if resolved_artist is not None else None,
            canonicalArtistIsFromVoteOnly=artist_source == "inferred_canonical_artist",
            canonicalArtistSource=artist_source,
            printingTagStatus=SerialisedPrintingTagStatus(self.printing_tag_status),
            suggestedCanonicalCard=(self._suggested_canonical_card() if include_suggested_printing else None),
            suggestedFilterTagNames=(self._suggested_filter_tag_names() if include_suggested_filter_tags else None),
            tagVoteStatuses=self._serialise_tag_vote_statuses(),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.serialise().model_dump()

    def get_source_pk(self) -> int:
        return self.source.pk

    def get_source_name(self) -> str:
        return self.source.name

    def get_source_external_link(self) -> Optional[str]:
        return self.source.external_link or None

    def get_source_type(self) -> SourceType:
        return SourceType(SourceTypeChoices[self.source.source_type].label)

    def get_source_type_choices(self) -> SourceTypeChoices:
        return SourceTypeChoices.from_source_type_schema(self.get_source_type())

    def get_small_thumbnail_url(self) -> Optional[str]:
        return SourceTypeChoices.get_source_type(self.get_source_type_choices()).get_small_thumbnail_url(
            self.identifier
        )

    def get_medium_thumbnail_url(self) -> Optional[str]:
        return SourceTypeChoices.get_source_type(self.get_source_type_choices()).get_medium_thumbnail_url(
            self.identifier
        )

    def get_expansion_code(self) -> str | None:
        # `canonical_card` (a confirmed indexing match, set at ingestion time from source-file
        # tags) takes priority; falling back to `inferred_canonical_card` only when the printing
        # tag vote system has actually resolved consensus means this fallback (and therefore
        # this indexed field, which `get_search`'s expansion_code/collector_number term filter
        # reads) never fires for UNRESOLVED/NO_MATCH cards - mirrors the same fallback chain
        # `Card.serialise()` already uses for the display-facing `canonicalCard` field.
        if self.canonical_card is not None:
            return self.canonical_card.expansion.code.upper()
        if self.printing_tag_status == PrintingTagStatus.RESOLVED and self.inferred_canonical_card is not None:
            return self.inferred_canonical_card.expansion.code.upper()
        return None

    def get_collector_number(self) -> str | None:
        if self.canonical_card is not None:
            return self.canonical_card.collector_number
        if self.printing_tag_status == PrintingTagStatus.RESOLVED and self.inferred_canonical_card is not None:
            return self.inferred_canonical_card.collector_number
        return None

    def get_indexed_artist_name(self) -> str:
        """
        Feeds `documents.py`'s `artist`/`artist_text` ES fields (search-operator syntax,
        2026-07-22). Mirrors `Card.serialise()`'s artist fallback chain EXACTLY (canonical_artist
        > canonical_card.artist > RESOLVED-gated inferred_canonical_card.artist >
        inferred_canonical_artist) - this deliberately has four rungs, not the two a simplified
        reading of the fallback might suggest, because the search index must never disagree with
        what a viewer already sees for the same card. Returns "" (never None) when no rung
        resolves, since both ES fields expect a plain string.
        """
        if self.canonical_artist is not None:
            return self.canonical_artist.name
        if self.canonical_card is not None:
            return self.canonical_card.artist.name
        if self.printing_tag_status == PrintingTagStatus.RESOLVED and self.inferred_canonical_card is not None:
            return self.inferred_canonical_card.artist.name
        if self.inferred_canonical_artist is not None:
            return self.inferred_canonical_artist.name
        return ""

    def _get_indexed_printing_metadata(self) -> Optional["CanonicalPrintingMetadata"]:
        """
        Same precedence as `get_expansion_code`/`get_collector_number` above (`canonical_card`
        first, falling back to `inferred_canonical_card` only once printing-tag consensus has
        actually RESOLVED) - shared by the `border_color`/`frame`/`frame_effects`/`full_art`
        ES-field getters below, so they can't drift from each other or from the pre-existing
        expansion_code/collector_number fallback rule.
        """
        printing = self.canonical_card
        if printing is None and self.printing_tag_status == PrintingTagStatus.RESOLVED:
            printing = self.inferred_canonical_card
        if printing is None:
            return None
        return getattr(printing, "printing_metadata", None)

    def get_border_color(self) -> str:
        metadata = self._get_indexed_printing_metadata()
        # lowercased here (not in documents.py) so the ES `border_color` KeywordField is
        # case-insensitive by construction - mirrors get_expansion_code's own choice to
        # `.upper()` inline rather than relying on an ES normalizer.
        return metadata.border_color.lower() if metadata is not None else ""

    def get_frame(self) -> str:
        metadata = self._get_indexed_printing_metadata()
        return metadata.frame.lower() if metadata is not None else ""

    def get_frame_effects(self) -> list[str]:
        metadata = self._get_indexed_printing_metadata()
        return metadata.frame_effects if metadata is not None else []

    def get_full_art(self) -> bool:
        metadata = self._get_indexed_printing_metadata()
        return metadata.full_art if metadata is not None else False

    def get_layout(self) -> str | None:
        metadata = self._get_indexed_printing_metadata()
        return metadata.layout or None if metadata is not None else None

    class Meta:
        ordering = ["-priority"]


class VoteSource(models.TextChoices):
    """
    Shared `source` enum for every `AbstractWeightedVote` subclass (`CardPrintingTag`,
    `CardArtistVote`, `CardTagVote`) - not printing-tag-specific despite the historical name
    this replaced (`CardPrintingTagSource`).

    `AI` (a single umbrella value) was split 2026-07-15 into `DEDUCTION` and `OCR` - both were
    genuinely different mechanisms sharing one label: DEDUCTION is pure logical inference from
    already-trusted structured data (cardpicker.deductive_backfill - zero image inspection),
    while OCR (kept as an umbrella name, not literal-OCR-only) covers everything in
    cardpicker.local_identify_printing_tags/local_fallback that actually looks at the card
    image - Tesseract text extraction, perceptual-hash art matching, and the border/artist/
    symbol evidence-combination fallback. The individual technique within OCR's umbrella is
    still distinguishable via `anonymous_id` (local-ocr-v1/local-phash-v1/local-fallback-v1) -
    a third split wasn't worth it for that reason alone. Every existing production `source="ai"`
    row predates this split entirely (deductive_backfill's own 28,112-vote production run, sole
    source of "ai" rows at split time) - see migration 0060 for the one-time backfill.
    Weight/gate treatment for both new values is identical to the old AI's (see
    vote_consensus.py's _SOURCE_WEIGHTS and is_human_backed_source) - this was a label split,
    not a policy change.
    """

    USER = "user", gettext_lazy("User")
    ADMIN = "admin", gettext_lazy("Admin")
    DEDUCTION = "deduction", gettext_lazy("Deduction")
    OCR = "ocr", gettext_lazy("OCR")
    FEDERATED = "federated", gettext_lazy("Federated")
    # A passive by-product of a card *selection* under active /editor filter chips (2026-07-22
    # vote-weight scenario matrix, owner-ratified): never a deliberate "yes this tag applies"
    # tap. Tiny per-vote weight, capped per (card, tag, polarity) group, never human-backed, never
    # privileged - see vote_consensus.py's _SOURCE_WEIGHTS/_MACHINE_DERIVED_SOURCES and
    # docs/features/printing-tags.md's implicit-vote section. Written only via
    # views.post_cast_implicit_vote/post_retract_implicit_vote, distinguished from every other
    # source's vote_surface values by always carrying "display-editor-filter" there.
    IMPLICIT = "implicit", gettext_lazy("Implicit")


CALCULATOR_VERSION_RE = re.compile(r"^(?P<family>.+)-v\d+$")


def calculator_family(anonymous_id: str) -> "str | None":
    """Return the versionless family prefix of a machine calculator
    anonymous_id (e.g. 'local-ocr' for 'local-ocr-v1'), or None if the
    id does not follow the machine naming convention (human voters use
    UUIDs, which never match)."""
    m = CALCULATOR_VERSION_RE.match(anonymous_id)
    return m.group("family") if m else None


def purge_stale_machine_votes(
    model_class: Any,
    anonymous_id: str,
    target_field: str,
    target_ids: Sequence[Any],
    *,
    superseded_by_run_id: "str | None" = None,
) -> int:
    """Before a calculator writes votes for target_ids, delete existing
    rows from the SAME CALCULATOR FAMILY (any version, including the
    current one) for those targets. Returns rows deleted.

    ARCHIVE-BEFORE-DELETE (owner ruling, 2026-07-29: "keep at least one
    prior generation of votes, whose votes are NOT counted"). For a model
    that has an archive table (`vote_archive_model` — `CardPrintingTag`
    only, today) every row this function is about to delete is copied into
    it first. This is THE choke point for that ruling deliberately: it is
    the single place a machine vote is superseded by a later machine vote,
    so putting the copy here means no caller can supersede a vote without
    archiving it, and no new caller has to remember to. `superseded_by_run_id`
    is stamped onto the archived copies to record WHICH run overwrote them —
    `vote_write.purge_and_write_votes` derives it from the batch it is about
    to insert, and passes None if that batch carries anything other than
    exactly one run_id.

    The copy and the delete are two statements. Every production caller
    reaches this through `vote_write.purge_and_write_votes`, whose
    `transaction.atomic()` already covers both plus the insert, so a
    process killed mid-purge cannot leave rows archived-but-not-deleted or
    deleted-but-not-archived — the same cancel-safety property that
    function's own docstring documents, now covering one more statement.


    Purges nothing and returns 0 if calculator_family() returns None
    (i.e. anonymous_id is a UUID — human votes are never touched).

    DELIBERATELY STILL FAMILY-KEYED after the 2026-07-29 re-scoping of the
    deductive-backfill zero-weight ruling (which moved THAT rule from the
    calculator family to one specific run's `run_id`). The two are about
    different things and must not be aligned for the sake of symmetry: this
    purge is about AGENT IDENTITY — "replace what this calculator previously
    said about these targets" — and a version bump does not make a calculator
    a second, independent agent whose stale rows should be left lying beside
    the fresh ones. Narrowing this to a run_id would leave every previous
    run's rows behind on every re-run.

    Note the interaction with the frozen 2026-07-14 deductive-backfill cohort,
    which is real but cannot bite: a fresh run of that calculator purges the
    family's rows for the cards it is about to write, and cohort rows are in
    that family. It never reaches them, because deductive_backfill's own
    `_eligible_base_queryset` admits only cards with ZERO existing votes of any
    kind, and every cohort card by definition already carries one. Retiring or
    re-versioning a caster does not rewrite history; this is the one path that
    could, and it is closed upstream."""
    family = calculator_family(anonymous_id)
    if family is None:
        return 0
    escaped = re.escape(family)
    doomed = model_class.objects.filter(
        anonymous_id__regex=rf"^{escaped}-v\d+$",
        **{f"{target_field}__in": list(target_ids)},
    )
    archive_model = vote_archive_model(model_class)
    if archive_model is not None:
        # Materialised BEFORE the DELETE, obviously, and deliberately as a `bulk_create` of full
        # copies rather than an `INSERT ... SELECT`: the archive table's columns are a superset of
        # the live table's (`original_id`, `superseded_by_run_id`, `archived_at`), so there is no
        # column-for-column SELECT to write, and the batch here is bounded by the caller's own
        # chunk size (500 in BULK mode, 25 per Stage E micro-batch), not by the table.
        archive_model.objects.bulk_create(
            [
                archive_model(
                    card_id=vote.card_id,
                    printing_id=vote.printing_id,
                    is_no_match=vote.is_no_match,
                    anonymous_id=vote.anonymous_id,
                    user_id=vote.user_id,
                    source=vote.source,
                    confidence=vote.confidence,
                    peer=vote.peer,
                    run_id=vote.run_id,
                    vote_surface=vote.vote_surface,
                    created_at=vote.created_at,
                    original_id=vote.pk,
                    superseded_by_run_id=superseded_by_run_id,
                )
                for vote in doomed
            ],
            batch_size=1000,
        )
    deleted, _ = doomed.delete()
    return deleted


class AbstractWeightedVote(models.Model):
    """
    Shared fields for every weighted-consensus vote model in this app (`CardPrintingTag`,
    `CardArtistVote`, `CardTagVote`) - see `cardpicker.vote_consensus.resolve_weighted_consensus`
    for how these are reconciled into a single resolved outcome per card. Purely a field
    container (no DB table of its own - `abstract = True`), so adding a field here changes
    the schema of every subclass's own table simultaneously; a comment here is the only thing
    that makes that non-obvious fact visible from any single subclass's own definition.
    """

    # a client-generated identifier (see `frontend/src/common/anonymousId.ts`), not a real Django
    # session key - cross-origin frontend/backend means a session cookie never round-trips here.
    anonymous_id = models.CharField(max_length=40)
    # set (in addition to anonymous_id, never instead of it) when the submitting request
    # carried an authenticated session - today that means a Discord-authenticated moderator
    # (see cardpicker.moderation / docs/features/moderation.md). Whether the vote counts as
    # privileged is decided at *resolution* time from current group membership, not stored
    # here, so revoking a moderator retroactively de-privileges their votes.
    user = models.ForeignKey(to=User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    source = models.CharField(max_length=10, choices=VoteSource.choices, default=VoteSource.USER)
    confidence = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # federation-readiness stub (see docs/federation-v1.md) - no import path sets this yet.
    peer = models.CharField(
        max_length=64, null=True, blank=True, help_text="Federation peer name; set only when source='federated'"
    )
    # Iteration-safety revocability (docs/features/catalog-completion-plan.md's Part 1): set on
    # every MACHINE-cast vote from local_identify_printing_tags.py/local_fallback.py's engines -
    # one fresh value generated once per run_pilot()/run_name_frequency_elimination() invocation
    # and threaded through every vote that invocation writes. NEVER set on a human-submitted
    # vote (views.py's post_submit_* views construct votes with no run_id kwarg, so it stays
    # NULL there). Deliberately separate from anonymous_id, whose EXACT-MATCH reuse across
    # invocations is load-bearing for _eligible_base_queryset's idempotence/resume logic and
    # must never change - confirmed via direct investigation that every production call site
    # depends on that exact-match reuse, and that anonymous_id's own max_length=40 would hard-
    # block a stamped value for at least two engines anyway. This field exists purely so one bad
    # invocation's votes can be identified and purged (management command purge_machine_votes
    # --run-id <id>) without touching any other invocation's votes under the same anonymous_id.
    # Indexed since the purge command filters on it directly.
    run_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    # Which UI surface cast this vote (e.g. "deckbuilder-confirm", "question-feed") - client-
    # supplied, optional, persisted verbatim with no server-side vocabulary enforced here (the
    # frontend owns what surface names exist; a new surface needs no backend change to start
    # sending it). Never affects consensus weighting or resolution today - purely an evidence-
    # source label. Exists for future per-surface reliability estimation (docs/theory.md's
    # Dawid-Skene addendum): a deckbuilder-confirm ("is this the right art?", already-selected
    # context) and a cold question-feed vote (no prior context) are different evidence channels
    # with plausibly different reliability, and this field is what would let that be measured
    # rather than assumed. Optional and ignore-if-absent on every submission endpoint - an old
    # frontend build that's never heard of this field keeps working unchanged, NULL here.
    vote_surface = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        abstract = True


class CardPrintingTag(AbstractWeightedVote):
    """
    A vote that a given `Card` (an image in this fork's catalogue) depicts a specific
    Scryfall printing (`CanonicalCard`), or definitively depicts no known printing
    (`is_no_match=True`). See `cardpicker.printing_consensus.resolve_printing` for how
    these votes are reconciled into a single resolved printing per card.
    """

    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="printing_tags")
    printing = models.ForeignKey(to=CanonicalCard, on_delete=models.CASCADE, null=True, blank=True, related_name="tags")
    is_no_match = models.BooleanField(default=False)
    # Issue #797: `local_calculate_verdicts.calculate_fallback_verdict`'s own border/artist/
    # symbol(/collector_line) evidence list, carried onto the vote it justifies instead of
    # discarded. `CardScanLog.evidence_types_used` (that field's own docstring) is this field's
    # sibling on the SKIP side; a MATCH never writes a `CardScanLog` row at all
    # (`local_calculate_verdicts.run_fallback_calculator`), which is exactly why
    # `question_feed._evidence_justifies_confirmation` reads THIS field, off the specific vote
    # being confirmed, rather than that table. Null (not `default=list`) distinguishes "no writer
    # has ever populated this vote" - every vote cast before this field existed, every human vote,
    # every join-key/deductive-backfill vote, none of which share the fallback calculator's
    # border/artist/symbol vocabulary - from "the fallback calculator looked and recorded
    # something"; both read as "evidence does not justify confirmation" at the one call site that
    # reads this field, so the distinction is for a future backfill pass to act on, not for
    # today's gate to branch on. No `survivor_pks` sibling here: `FallbackVerdict.survivor_pks` is
    # only ever populated alongside a SKIP (see that dataclass's own docstring) - on a MATCH it is
    # always `None`, so a vote-side copy would carry zero information for every row that could
    # ever write one.
    evidence_types_used = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(printing__isnull=False, is_no_match=False)
                    | models.Q(printing__isnull=True, is_no_match=True)
                ),
                name="cardprintingtag_printing_xor_no_match",
            ),
            models.UniqueConstraint(
                fields=["card", "printing", "anonymous_id"],
                condition=models.Q(is_no_match=False),
                name="cardprintingtag_unique_printing_vote",
            ),
            models.UniqueConstraint(
                fields=["card", "anonymous_id"],
                condition=models.Q(is_no_match=True),
                name="cardprintingtag_unique_no_match_vote",
            ),
        ]

    def __str__(self) -> str:
        outcome = "NO MATCH" if self.is_no_match else str(self.printing)
        return f"[{self.source}] {self.card.name} -> {outcome}"


class ArchivedCardPrintingTag(models.Model):
    """
    A `CardPrintingTag` row that a LATER machine vote superseded - moved here by
    `purge_stale_machine_votes` instead of being destroyed (owner ruling, 2026-07-29: "keep at
    least one prior generation of votes, whose votes are NOT counted").

    WHY AN ARCHIVE TABLE AND NOT RETAINED GENERATIONS IN THE LIVE TABLE. This is a measured
    decision, not a stylistic one. Thirteen modules read `CardPrintingTag.objects` (or walk
    `Card.printing_tags`); NINE of them bypass `vote_consensus.resolve_vote_weight` entirely -
    `views.py`, `catalog_stats.py`, `local_calculate_verdicts.py`, `models.py` (this file's own
    `suggested_printing_votes_prefetch`), `local_identify_printing_tags.py`, `soak_gate.py`,
    `harvest_probe.py`, `illustration_vote.py`, `local_lands_identify.py`. So the "give the old
    generation zero weight, keyed on run_id" pattern that migration 0097 established for the
    frozen deductive-backfill cohort protects only the four consumers that route through weight
    resolution. A retained generation left sitting in the live table would still be DISPLAYED by
    the views layer, still COUNTED by catalog-stats, and - fatally for the work this table exists
    to enable - would still make `_eligible_cards_queryset`'s `.exclude(printing_tags__...)` treat
    the card as already voted, re-creating exactly the suppression run-scoped eligibility removes.

    Keeping the live table strictly single-generation means no consumer can be wrong about it: no
    unique-constraint change, no audit of thirteen modules, and no new rule any future reader has
    to know. Rows here are unreachable from `Card` (`related_name="+"` on both FKs), are not an
    `AbstractWeightedVote` subclass, and are read by exactly one thing today - the opt-in
    `--generation-diff` debug report on `manage.py local_calculate_verdicts`. Nothing in
    `vote_consensus`/`printing_consensus`/`catalog_stats`/`views` can see them even by accident.

    APPEND-ONLY, NO UNIQUE CONSTRAINTS - deliberately the same shape as `CardScanLog`. A card
    superseded by five successive runs holds five archive rows, in `archived_at` order; that IS
    the paper trail. Growth is a retention question, and it is issue #575's janitor's ("keep the N
    most recent runs per calculator, sweep the oldest, operator-authorised with a dry run") - both
    `run_id` (the superseded generation's own run) and `superseded_by_run_id` (the run that
    overwrote it) are indexed so that janitor can select a generation without a table scan.

    NOT A RETRACTION LOG. Only the family-keyed machine purge in `purge_stale_machine_votes`
    writes here, so a row appearing means "some later run of this calculator family said something
    else about this card". Human votes never reach it (`calculator_family` returns None for the
    UUID anonymous_ids humans use, and that path returns before any purge). Deliberate operator
    retractions - `purge_machine_votes`, `retract_stage_d_by_run_id` - are a different act with
    their own audit trail and are not routed here.
    """

    # `related_name="+"` on BOTH FKs is load-bearing, not tidiness: it is what makes these rows
    # structurally unreachable from a `Card`/`CanonicalCard` instance, so no existing consumer can
    # traverse into them and no future `prefetch_related`/`filter(...__...)` can pick them up by
    # guessing an accessor name. CASCADE matches the live table: when a card leaves the catalogue
    # its votes go with it, and an archive of votes for a card that no longer exists is not a
    # paper trail anybody can read.
    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="+")
    printing = models.ForeignKey(to=CanonicalCard, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    is_no_match = models.BooleanField(default=False)
    # Every remaining field is a verbatim copy of the superseded row's own value - including
    # `created_at`, which is copied rather than re-stamped (this is NOT `auto_now_add`) so the
    # archived row still records when the VOTE was cast, not when it was archived. `archived_at`
    # below is the separate, honest answer to "when did this stop being live".
    anonymous_id = models.CharField(max_length=40)
    user = models.ForeignKey(to=User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    source = models.CharField(max_length=10, choices=VoteSource.choices, default=VoteSource.USER)
    confidence = models.FloatField(null=True, blank=True)
    peer = models.CharField(max_length=64, null=True, blank=True)
    run_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    vote_surface = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField()
    # The live row's primary key before it was deleted. Kept so a debug report can tie an archive
    # row back to a `run_id`-scoped query somebody ran against the live table earlier; the pk is
    # NOT reused by Postgres, so it stays a stable historical identifier rather than a live one.
    original_id = models.BigIntegerField()
    # The run whose write superseded this row, where knowable - `purge_and_write_votes` derives it
    # from the rows it is about to insert, and leaves it NULL if that batch somehow carries more
    # than one run_id (or none). Indexed because the `--generation-diff` report and issue #575's
    # janitor both select by it.
    superseded_by_run_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    archived_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            # The generation-diff read: "everything ever archived for this card by this identity",
            # newest first. Also the shape a per-calculator retention sweep needs.
            models.Index(fields=["card", "anonymous_id"], name="archived_printing_tag_idx"),
        ]

    def __str__(self) -> str:
        outcome = "NO MATCH" if self.is_no_match else str(self.printing)
        return f"[archived {self.source}] card={self.card_id} -> {outcome}"


# Which live vote model archives its superseded rows where. Consulted by
# `purge_stale_machine_votes`; a model absent from this mapping keeps the pre-2026-07-29 behaviour
# of deleting outright. Only `CardPrintingTag` is in it today, and that is the scope of the owner
# ruling that created the archive - `CardTagVote`/`CardArtistVote`/`PrintingTagVote`/
# `CardIllustrationVote` are deliberately NOT archived, since nothing has asked to diff their
# generations and four more append-only tables is real storage for a hypothetical.
#
# Populated lazily via a function rather than a module-level dict literal only because
# `ArchivedCardPrintingTag` has to be defined before it can be referenced, and
# `purge_stale_machine_votes` sits ABOVE it in this file (it is a helper the vote models'
# docstrings refer to, and moving it below them would make those references read backwards).
def vote_archive_model(model_class: Any) -> Any:
    """The archive model for `model_class`, or None if that model's superseded rows are deleted
    outright. See `VOTE_ARCHIVE_MODELS`' own comment above for why only `CardPrintingTag` has one."""
    return {CardPrintingTag: ArchivedCardPrintingTag}.get(model_class)


def suggested_printing_votes_prefetch() -> models.Prefetch:
    """
    `Prefetch` object for `Card.objects.prefetch_related(...)`, making
    `Card.serialise(include_suggested_printing=True)` populate `suggestedCanonicalCard`
    without an extra query per card (Proposal H §4.4′, issue #184) - attach this to any
    queryset feeding `serialise(include_suggested_printing=True)` across more than a single
    row (today: `post_cards`/`post_explore_search` in views.py, the two endpoints that serve
    bulk Card payloads to the search/picker surface this field is for).

    Filters to `VoteSource.DEDUCTION`/`OCR` (machine-cast votes only - "machine-suggested" per
    the issue's own wording, deliberately not any contested-but-human-voted state) and orders
    by `pk` to match Django's own implicit `.first()` ordering (what
    `question_feed.py::_confirm_suggestion_item`'s equivalent, un-prefetched `ai_vote` lookup
    uses), so a card with more than one machine vote surfaces the same "first" vote via either
    code path.
    """
    return models.Prefetch(
        "printing_tags",
        queryset=CardPrintingTag.objects.filter(source__in=[VoteSource.DEDUCTION, VoteSource.OCR], is_no_match=False)
        .select_related("printing__expansion")
        .order_by("pk"),
        to_attr=SUGGESTED_PRINTING_VOTES_ATTR,
    )


def attach_suggested_filter_tags_overlay(cards: Sequence["Card"]) -> None:
    """
    Batches `tag_consensus.get_suggested_filter_tags_overlay` across `cards` (one overlay
    computation - two queries total, see that function's own implementation - for the entire
    list, not one per card) and stamps each instance with its own precomputed
    `suggestedFilterTagNames` result via `SUGGESTED_FILTER_TAG_NAMES_ATTR`, so
    `Card.serialise(include_suggested_filter_tags=True)` finds it already there.

    This field's underlying query isn't `Prefetch`-shaped the way `suggested_printing_votes_prefetch()`
    is (it isn't a single related-queryset walk - see `get_suggested_filter_tags_overlay`'s own
    two-query implementation across `Card.tag_vote_statuses` and `CardTagVote`), so it's a plain
    call-then-stamp helper instead of a `Prefetch` object. Call this on the fully-realized list
    of `Card` instances a response will serialise with `include_suggested_filter_tags=True`
    BEFORE calling `.serialise(...)` on any of them (today: `post_cards` in views.py, the
    endpoint feeding the /display grid-selector candidate list) - mutates `cards` in place and
    returns nothing, same shape as `bulk_sync_objects`' own `get_resolved_tag_overlay` attach step.
    """
    from cardpicker.tag_consensus import (
        get_suggested_filter_tags_overlay,  # local import - avoids a cycle
    )

    overlay = get_suggested_filter_tags_overlay([card.pk for card in cards])
    for card in cards:
        setattr(card, SUGGESTED_FILTER_TAG_NAMES_ATTR, overlay.get(card.pk, []))


class CardArtistVote(AbstractWeightedVote):
    """
    A vote that a given `Card` was illustrated by a specific `CanonicalArtist`, or
    definitively by an unknown/unlisted artist (`is_unknown=True`). Only meaningful once a
    card's printing-tag consensus hasn't already resolved a printing - see
    `cardpicker.artist_consensus` and the artist fallback chain in `Card.serialise()`, where a
    resolved printing's own artist always takes precedence over this vote's outcome.
    """

    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="artist_votes")
    artist = models.ForeignKey(
        to=CanonicalArtist, on_delete=models.CASCADE, null=True, blank=True, related_name="votes"
    )
    is_unknown = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(artist__isnull=False, is_unknown=False) | models.Q(artist__isnull=True, is_unknown=True)
                ),
                name="cardartistvote_artist_xor_unknown",
            ),
            # not the sole enforcement of "one active vote per (card, anonymous_id)" - the
            # submit view deletes any existing vote for this (card, anonymous_id) before
            # creating the new one (same pattern as CardPrintingTag). This constraint is a
            # safety net against a double-submit race, not the primary mechanism.
            models.UniqueConstraint(
                fields=["card", "artist", "anonymous_id"],
                condition=models.Q(is_unknown=False),
                name="cardartistvote_unique_artist_vote",
            ),
            models.UniqueConstraint(
                fields=["card", "anonymous_id"],
                condition=models.Q(is_unknown=True),
                name="cardartistvote_unique_unknown_vote",
            ),
        ]

    def __str__(self) -> str:
        outcome = "UNKNOWN" if self.is_unknown else str(self.artist)
        return f"[{self.source}] {self.card.name} -> {outcome}"


class CardIllustrationVote(AbstractWeightedVote):
    """
    A vote that a given `Card` (an image in this fork's catalogue) depicts a specific Scryfall
    ARTWORK, identified by `illustration_id`, or definitively depicts an artwork with no known
    illustration identity (`is_unknown=True`). Issue #524.

    WHY THIS GRAIN EXISTS AT ALL. `illustration_id` identifies an ARTWORK, and artwork-to-printing
    is 1:N — roughly 2.2 printings share each illustration across the catalogue. Identifying the
    artwork therefore NARROWS the printing but usually does not determine it, so the claim "this
    card depicts illustration X" is genuinely not expressible as any number of `CardPrintingTag`
    rows: one row picks a printing the evidence does not support, and N rows assert N mutually
    exclusive printings at once. The knowledge is real and had nowhere to live until this model.

    NOT A FOREIGN KEY, AND DELIBERATELY SO. `illustration_id` is a plain indexed `UUIDField`, not
    an FK, because there is no `CanonicalIllustration` table and this model must not cause one to
    exist. The value is Scryfall's own identifier, already imported onto
    `CanonicalPrintingMetadata.illustration_id` (also a plain indexed `UUIDField`). The narrowing
    from an illustration to its candidate printings is a READ — a join through
    `CanonicalPrintingMetadata` (see `local_illustration.printings_for_illustration`) — and must
    never be materialised as implied printing votes.

    THE UNIQUENESS CONSTRAINT IS UNCONDITIONAL, AND THAT DIVERGENCE IS THE POINT (issue #525).
    `UniqueConstraint(fields=["card", "anonymous_id"])` carries NO `condition=`, so ONE identity
    can hold at most ONE illustration opinion per card, full stop — including across the
    known/unknown split. Both sibling identity-vote models are keyed more loosely:
    `CardPrintingTag` on (card, printing, anonymous_id) and `CardArtistVote`'s artist branch on
    (card, artist, anonymous_id), each with a partial `condition=`. Both therefore rely on the
    SUBMIT VIEW deleting the voter's prior rows for the card before creating the new one to get
    one-vote-per-card; `CardArtistVote`'s own comment concedes as much, calling its constraint
    "a safety net against a double-submit race, not the primary mechanism".

    That works only for voters who go through a view. MACHINE writers do not: they `bulk_create`,
    which bypasses the submit path entirely — and that is exactly how the illustration calculator
    came to cast several mutually exclusive `CardPrintingTag` votes for one card under a single
    `anonymous_id` (issue #525: N full-machine-weight rows for N competing printings, all
    persisted, because the constraint's `printing` term let them coexist and the `BASE_CONFIDENCE
    / N` discount never reached the tally). The remedy chosen there was to make the calculator
    abstain; the remedy chosen HERE is structural — under an unconditional (card, anonymous_id)
    key a self-contradiction is not merely discouraged by convention in a view, it is
    UNREPRESENTABLE in the table, for every writer, human or machine, forever.

    DO NOT "FIX" THIS TO MATCH ITS SIBLINGS. Adding `illustration_id` to the constraint's fields,
    or attaching a `condition=Q(is_unknown=False)`, would re-open precisely the hole #525 closed:
    it would let one identity hold two contradictory illustration claims (or one known plus one
    unknown claim) for the same card simultaneously. The cost of the strict key is that a writer
    with a CHANGED answer must UPDATE the existing row rather than insert alongside it — see
    `local_illustration._purge_and_write_illustration_votes`, which compares the stored
    `illustration_id` VALUE and not merely the (card, anonymous_id) key for exactly this reason.
    That cost is intended: an update is what a corrected answer actually is.
    """

    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="illustration_votes")
    # Scryfall's artwork identifier, matching `CanonicalPrintingMetadata.illustration_id` in both
    # type and indexing. Nullable because `is_unknown=True` rows carry no identity (the XOR check
    # below is what keeps "null" and "unknown" from drifting apart).
    illustration_id = models.UUIDField(null=True, blank=True, db_index=True)
    is_unknown = models.BooleanField(default=False)

    class Meta:
        constraints = [
            # Mirrors `cardartistvote_artist_xor_unknown` exactly: a row either names an
            # illustration or declares the illustration unknown, never both and never neither.
            models.CheckConstraint(
                check=(
                    models.Q(illustration_id__isnull=False, is_unknown=False)
                    | models.Q(illustration_id__isnull=True, is_unknown=True)
                ),
                name="cardillustrationvote_illustration_xor_unknown",
            ),
            # UNCONDITIONAL — no `condition=`, and no `illustration_id` in `fields`. This is the
            # deliberate divergence from `CardPrintingTag`/`CardArtistVote` documented at length in
            # the class docstring above (issue #525): it is the PRIMARY mechanism for
            # one-illustration-opinion-per-(card, identity), not a race safety net behind a view
            # that machine writers never call.
            models.UniqueConstraint(
                fields=["card", "anonymous_id"],
                name="cardillustrationvote_unique_vote",
            ),
        ]

    def __str__(self) -> str:
        outcome = "UNKNOWN" if self.is_unknown else str(self.illustration_id)
        return f"[{self.source}] {self.card.name} -> illustration {outcome}"


class CardIllustrationRejection(AbstractWeightedVote):
    """
    A vote that a given `Card` does NOT depict a specific Scryfall ARTWORK (issue #524's "Not
    this art" follow-up) - the negative counterpart to `CardIllustrationVote`, and deliberately
    a SEPARATE model rather than a polarity flag on that one.

    WHY NOT A POLARITY FLAG ON `CardIllustrationVote`. That model's (card, anonymous_id) unique
    constraint is UNCONDITIONAL BY DESIGN (issue #525 - see its own docstring): one identity
    holds AT MOST ONE illustration opinion per card, full stop. A rejection is not that opinion -
    it is the opposite kind of claim, "one of these artworks is wrong", and a voter must be able
    to reject several candidate artworks for one card while still affirming a different one, or
    affirming none at all. Consuming the same unconditional slot for a rejection would mean
    rejecting one artwork could block ever affirming the right one - backwards from the intent,
    and exactly the failure this model exists to avoid. So this is its own table, its own
    constraint, unrelated to `CardIllustrationVote`'s.

    THE CONSTRAINT IS (card, anonymous_id, illustration_id) - conditional in the sense that
    matters (per-artwork, not per-card): one identity may hold many rejections for one card (one
    per rejected artwork), but at most one rejection of any GIVEN artwork. No XOR/unknown split
    either - a rejection always names the artwork it rejects (`illustration_id` is NOT NULL);
    "I don't know what this artwork is" is `CardIllustrationVote.is_unknown`'s claim, not this
    model's, and rejecting "unknown" is not a meaningful statement.

    NARROWS BY ELIMINATION, NEVER BY ELECTION. This model competes for nothing:
    `illustration_consensus.eliminated_illustration_ids` runs `vote_consensus.
    resolve_weighted_consensus` independently per `illustration_id`, over just that artwork's
    own rejection rows, with a single possible outcome - so the function reduces to the same
    weighted-quorum-plus-human-backed-gate test every other vote model here already uses, applied
    per candidate rather than across candidates. It never assigns a winner and never touches
    `CardIllustrationVote.resolve_illustration`'s own tally; see that function's module for the
    full read-side design. Nothing here is ever expanded into `CardPrintingTag` rows either - the
    illustration-to-printing narrowing stays the same READ (`local_illustration.
    printings_for_illustration`) it always was; a rejected ARTWORK says nothing about which
    PRINTINGS sharing it are themselves rejected.

    WEIGHT IS UNCHANGED MACHINERY. A rejection's weight resolves through the exact same
    `vote_consensus.resolve_vote_weight(source, anonymous_id, run_id)` every other
    `AbstractWeightedVote` subclass uses - there is no separate rejection weight scale. A vote's
    weight is a property of WHO cast it and BY WHAT METHOD, never of which way it points; see
    that function's own docstring for the argument against a weight ever depending on the claim
    itself.

    MACHINE-CAST ROWS (`local_illustration.run_illustration_calculator`) are written alongside
    every accepted `CardIllustrationVote`: one positive implies a rejection for every OTHER
    illustration candidate available for that card (`get_ranked_printing_candidates` - the same
    candidate space `illustration_vote.printings_for_card_and_illustration` already draws on),
    so the elimination space stays dense even though human rejections alone are sparse. Retracted
    the same way every other Stage D write is: `models.purge_stale_machine_votes`, family-scoped
    on `ILLUSTRATION_ANONYMOUS_ID`, re-run each time the calculator's positive for that card
    changes - see that function's own call site in `local_illustration.py` for the exact
    ordering/idempotence contract.
    """

    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="illustration_rejections")
    # Always set - a rejection names the artwork it rejects. Not nullable, unlike
    # `CardIllustrationVote.illustration_id`: there is no "unknown" analogue here (see the
    # docstring above).
    illustration_id = models.UUIDField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["card", "anonymous_id", "illustration_id"],
                name="cardillustrationrejection_unique_vote",
            ),
        ]
        indexes = [
            # Covers `illustration_consensus.eliminated_illustration_ids`' per-group read
            # (`WHERE card_id IN (<md5 group>) ORDER BY card_id, id`, then bucketed by
            # illustration_id in Python) - card_id-first because the query is always scoped by
            # card/group first and only ever fans out to illustration_id afterwards in-memory,
            # never filtered by illustration_id alone at the DB layer.
            models.Index(fields=["card", "illustration_id"], name="cardillusrej_card_illus_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.source}] {self.card.name} -> NOT illustration {self.illustration_id}"


class ArtboxPhashExemplarSeedKind(models.TextChoices):
    """
    How an `ArtboxPhashExemplar` row was seeded (issue #508 phase 1) - the provenance distinction
    the owner made mandatory at seeding time (2026-08-05): a machine-derived seed and a
    human-backed one must stay distinguishable forever, so a later decision to trust only the
    latter is a query over this field, not a migration.
    """

    HUMAN_RESOLUTION = "human_resolution", gettext_lazy("Human-backed printing resolution")
    JOIN_KEY_MACHINE = "join_key_machine", gettext_lazy("High-confidence join-key vote")


class ArtboxPhashExemplar(models.Model):
    """
    Second illustration-deduction path's reference index (issue #508 phase 1, "self-referential
    exemplar index" - owner-shaped 2026-07-28, seeding extended by the owner 2026-08-05 to include
    machine seeds). An exemplar is a labelled association: a card's own CURRENT `artbox_phash`
    (`ImageEvidence.artbox_phash` - see that field's own docstring, issue #480) -> the
    `illustration_id` of the printing that scan was identified as (via
    `CanonicalPrintingMetadata.illustration_id`, reached through the resolved/matched
    `CanonicalCard`).

    NEVER SOURCED FROM SCRYFALL IMAGES (binding, #508's design section). phash comparability
    requires identical crop geometry/preprocessing - our own `artbox_phash` extractor is
    self-consistent; Scryfall's `art_crop` framing differs and would make cross-source Hamming
    distances unreliable (this is also why PR #694 was closed and deferred to #697 - do not
    reintroduce a Scryfall fetch anywhere a seed for this table is computed).

    SEED SOURCES (owner decision 2026-08-05, extending #508's original human-only spec, which
    would have left this index dormant - only 12 human-backed resolutions exist catalogue-wide
    at seeding time):

    - `HUMAN_RESOLUTION`: `card.printing_tag_status == RESOLVED`. Resolution ALWAYS requires a
      human-backed vote (`vote_consensus.resolve_weighted_consensus`'s non-machine-alone gate,
      untouched by this work) - so every RESOLVED card is human-backed by construction, and no
      per-vote inspection is needed to classify one as such.
    - `JOIN_KEY_MACHINE`: an individual `CardPrintingTag` vote cast by the join-key calculator
      (`local_calculate_verdicts.JOIN_KEY_ANONYMOUS_ID`) at or above
      `artbox_exemplar_backfill.JOIN_KEY_SEED_CONFIDENCE_FLOOR` - see that constant's own comment
      for why the floor excludes the artist-disagreement confidence tier (0.65) along with the
      no-match tier (0.6, which is not an identification at all and can never seed regardless of
      any floor).

    `is_human_backed` is a plain denormalised copy of `seed_kind`'s own implication (never
    `HUMAN_RESOLUTION` with `is_human_backed=False` or vice versa - enforced by the CheckConstraint
    below), kept as its own column so a reader who only needs the human/machine split never has to
    know the seed-kind vocabulary.

    RETRACTION (owner directive 2026-08-05: "a bad seed must be retractable together with
    everything it seeded"). `seed_group_key` is the stable identity of the SOURCE EVENT that
    produced this row, not of the row itself: every exemplar traceable to the same md5-identity-
    group resolution, or to the same source `CardPrintingTag` vote, shares one key, so retracting
    a bad seed is `ArtboxPhashExemplar.objects.filter(seed_group_key=...).delete()` - one query, no
    per-row reasoning about what else that source touched. See `artbox_exemplar_backfill.
    human_resolution_seed_group_key`/`join_key_seed_group_key` for the exact format (the human-
    resolution case mirrors `printing_consensus.md5_group_key`'s own group identity, so retracting
    "this resolved identity group" here means the same set of cards `printing_consensus` itself
    would call one group). `source_vote` is `SET_NULL` on the vote's own deletion (a purge doesn't
    orphan this row's retractability - `seed_group_key` carries it independently of the FK's
    referential integrity).

    INDEX-NOT-STORE (CLAUDE.md's governing premise): this table holds a hash and a UUID, nothing
    fetched or decodable back into pixels - `content_hash` records the source card's own
    `content_phash` AT SEED TIME purely as a staleness audit trail (so a later reader can tell
    whether the source card's image has since changed), never a second copy of anything
    image-shaped.

    PHASE 1 SCOPE: this table is read by nothing yet. No matching calculator, no vote, no
    consensus, no change to `resolve_weighted_consensus`/the human-backed gate - see
    `docs/identification-pipeline.md`'s "Parallel detectors" section for what this deliberately
    does NOT do.
    """

    illustration_id = models.UUIDField(db_index=True)
    artbox_phash = models.BigIntegerField(db_index=True)
    card = models.OneToOneField(to=Card, on_delete=models.CASCADE, related_name="artbox_phash_exemplar")
    printing = models.ForeignKey(to=CanonicalCard, on_delete=models.CASCADE, related_name="artbox_phash_exemplars")
    seed_kind = models.CharField(max_length=32, choices=ArtboxPhashExemplarSeedKind.choices)
    is_human_backed = models.BooleanField()
    # SET_NULL, not CASCADE - see class docstring's RETRACTION section for why losing this FK
    # on the source vote's own deletion is fine (seed_group_key carries retractability instead).
    source_vote = models.ForeignKey(
        to=CardPrintingTag, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Purely informational, mirroring `CardPrintingTag.confidence`'s own "not read by any
    # resolution math" convention (`JOIN_KEY_CONFIDENCE_BOTH`'s comment in
    # local_calculate_verdicts.py makes the identical point for that field). Null for
    # HUMAN_RESOLUTION seeds - a resolution is a consensus outcome, not a single confidence value.
    confidence = models.FloatField(null=True, blank=True)
    seed_group_key = models.CharField(max_length=128, db_index=True)
    content_hash = models.BigIntegerField()
    run_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(seed_kind=ArtboxPhashExemplarSeedKind.HUMAN_RESOLUTION, is_human_backed=True)
                    | models.Q(seed_kind=ArtboxPhashExemplarSeedKind.JOIN_KEY_MACHINE, is_human_backed=False)
                ),
                name="artboxphashexemplar_seed_kind_matches_human_backed",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.seed_kind}] card={self.card_id} -> illustration {self.illustration_id}"


class TagModerationClass(models.TextChoices):
    """
    Whether consensus on this tag resolves like any other (STANDARD) or requires a privileged
    co-sign before it can resolve (SENSITIVE) - see cardpicker.tag_consensus and
    docs/features/moderation.md. Sensitive tags carry consequences (e.g. NSFW excludes a card
    from default search), so a crowd alone can only ever move them to `pending_approval`.
    """

    STANDARD = "standard", gettext_lazy("Standard")
    SENSITIVE = "sensitive", gettext_lazy("Sensitive")


class Tag(models.Model):
    name = models.CharField(unique=True)
    moderation_class = models.CharField(
        max_length=10, choices=TagModerationClass.choices, default=TagModerationClass.STANDARD
    )
    display_name = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Presentation only — freely editable. `name` is the immutable machine key "
        "used by votes, tag_vote_statuses, Card.tags, and federation; NEVER rename a Tag "
        "after creation.",
    )
    # null=True is just for admin panel
    aliases = ArrayField(models.CharField(max_length=200), default=list, blank=True)
    is_enabled_by_default = models.BooleanField(default=True)
    parent = models.ForeignKey(to="Tag", null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self) -> str:
        return self.name

    def serialise(self) -> SerialisedTag:
        return SerialisedTag(
            name=self.name,
            displayName=self.display_name,
            aliases=self.aliases,
            isEnabledByDefault=self.is_enabled_by_default,
            parent=(self.parent.name if self.parent else None),
            # recursively serialise each child tag
            children=(
                [ChildElement(**x.to_dict()) for x in self.tag_set.order_by("name").all()]
                if self.pk is not None
                else []
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.serialise().model_dump()

    @classmethod
    def get_tags(cls) -> dict[str, list[str]]:
        return {tag.name: tag.aliases for tag in Tag.objects.all()}


class VotePolarity(models.IntegerChoices):
    APPLY = 1, gettext_lazy("Apply")
    NOT_APPLICABLE = -1, gettext_lazy("Not applicable")


class CardTagVote(AbstractWeightedVote):
    """
    A vote on whether a given descriptor `Tag` applies to a `Card` (`polarity=APPLY`) or not
    (`polarity=NOT_APPLICABLE`). Unlike `CardPrintingTag`/`CardArtistVote` (mutually exclusive
    outcomes - a card has exactly one real printing/artist), a card can carry independent,
    simultaneous votes across many different tags at once, so uniqueness here is scoped to
    (card, tag, anonymous_id) rather than just (card, anonymous_id) - changing your mind about
    one tag is an update to that one row (`update_or_create` in the submit view), not a
    delete-and-recreate of every vote this person has cast on this card.
    """

    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="tag_votes")
    tag = models.ForeignKey(to=Tag, on_delete=models.CASCADE, related_name="votes")
    polarity = models.SmallIntegerField(choices=VotePolarity.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["card", "tag", "anonymous_id"], name="cardtagvote_unique_vote"),
        ]

    def __str__(self) -> str:
        return f"[{self.source}] {self.card.name} -> {self.tag} ({VotePolarity(self.polarity).label})"


# RETIRED 2026-07-29 (owner ruling): `PrintingTagVote` used to sit here - a vote keyed
# (CanonicalCard, Tag, anonymous_id) asserting "this descriptor tag applies to this Scryfall
# printing". It is gone, model and table (migration 0101). It held 0 rows in production, 0 of
# them human, had no consensus resolver anywhere in the codebase, no reader outside the Django
# admin, and no frontend caller; its one machine writer (`import_external_ip_tags`) never ran.
# The full evidence is PR #599 (report: `2026-07-29-printing-vs-illustration-tag-grain.md`, which
# lands under docs/reports/ when that PR merges; it was still open when this was written);
# the replacement is `CanonicalPrintingMetadata.promo_types` for imported Scryfall facts (an
# imported fact is not a disputable claim, so it is not a vote) plus `CardTagVote` at card grain
# for anything a human genuinely disputes.
#
# THE TWO MODELS WITH CONFUSINGLY SIMILAR NAMES ARE BOTH LOAD-BEARING AND STILL HERE:
#   * `CardPrintingTag` (above) - (Card, CanonicalCard, anonymous_id), "this catalogue IMAGE
#     depicts this Scryfall PRINTING". 167k rows, read by `printing_consensus` into
#     `Card.printing_tag_status` / `inferred_canonical_card` / Elasticsearch.
#   * `CardTagVote` (above) - (Card, Tag, anonymous_id), "this descriptor TAG applies to this
#     catalogue IMAGE". 224k rows, read by `tag_consensus` into `Card.tags`.
# Likewise `PRINTING_TAG_MIN_VOTES` / `PRINTING_TAG_IMPLICIT_CAP` / `PRINTING_TAG_MACHINE_WEIGHT`
# and `local_calculate_verdicts._split_new_printing_tag_votes` never governed the retired model -
# the first three are the app-wide consensus weights and the fourth is a `CardPrintingTag`
# collision guard. Do not "finish the job" by touching any of them.


class CardReportReason(models.TextChoices):
    """
    Why a user reported a card (the report button on the card detail modal - see
    docs/features/moderation.md). The first three map onto sensitive tags (see
    cardpicker.sensitive_tags.REPORT_REASON_TO_TAG_NAME) and cast a CardTagVote alongside the
    report; BROKEN_IMAGE and OTHER are report-row-only.
    """

    NSFW = "nsfw", gettext_lazy("NSFW")
    LOW_QUALITY = "low_quality", gettext_lazy("Low quality")
    WRONG_CARD = "wrong_card", gettext_lazy("Wrong card info")
    BROKEN_IMAGE = "broken_image", gettext_lazy("Broken image")
    OTHER = "other", gettext_lazy("Other")


class CardReport(models.Model):
    """
    The audit trail behind the report button: one row per report, regardless of whether the
    reason also cast a tag vote. Deliberately append-only from the API (no update/delete
    path) - moderators review these via the moderation queue's excerpts and the admin panel.
    """

    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="reports")
    # same client-generated identifier the vote tables use - see AbstractWeightedVote
    anonymous_id = models.CharField(max_length=40)
    user = models.ForeignKey(to=User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reason = models.CharField(max_length=20, choices=CardReportReason.choices, db_index=True)
    # free text from the "Other" chip (bounded at the schema layer too); blank for most reasons
    text = models.CharField(max_length=280, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.card.name} -> {self.reason} ({self.anonymous_id})"


class HiddenCard(models.Model):
    """
    A durable per-anonymous_id record that `card` should be excluded from that identity's own
    future question-feed items (see docs/features/moderation.md's hidden-card section). Written
    by `views.post_report_card` when the report carries `hide=True` (`ReportCardRequest.hide`,
    additive to the existing report payload) - always alongside a `CardReport` row, in the same
    transaction, never in place of one. Scoped to the client-generated anonymous_id only, same
    as every other vote/report table here - no account linkage yet (see that doc section for
    what this deliberately does not do). `get_or_create`d at the write site, so a repeat report
    with `hide=True` for the same (card, anonymous_id) is a no-op rather than an IntegrityError.
    """

    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="hidden_by")
    anonymous_id = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["card", "anonymous_id"], name="hiddencard_unique_hide"),
        ]

    def __str__(self) -> str:
        return f"{self.card.name} hidden for {self.anonymous_id}"


class TagSuggestionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    AUTO_ACCEPTED = "auto_accepted", "Auto-accepted"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"


class TagAliasSuggestion(models.Model):
    """
    A bracketed token found in source filenames (e.g. "Fullart") that fuzzily but not
    exactly matched a known Tag's name/alias. Keyed on the raw text itself rather than
    per-card, since the same token recurs across thousands of cards - reviewing (or
    auto-accepting) it once promotes it to a real Tag alias, which every subsequent
    reindex then picks up via the existing exact-match path.
    """

    raw_text = models.CharField(max_length=200, unique=True)
    suggested_tag = models.ForeignKey(to=Tag, on_delete=models.SET_NULL, null=True, blank=True)
    confidence = models.FloatField()
    occurrence_count = models.IntegerField(default=1)
    status = models.CharField(max_length=20, choices=TagSuggestionStatus.choices, default=TagSuggestionStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.raw_text!r} -> {self.suggested_tag} ({self.status}, {self.confidence:.2f})"


class DFCPair(models.Model):
    front = models.CharField(max_length=200, unique=True)
    back = models.CharField(max_length=200)

    def __str__(self) -> str:
        return "{} // {}".format(self.front, self.back)


# https://simpleisbetterthancomplex.com/article/2021/07/08/what-you-should-know-about-the-django-user-model.html


def get_default_cardback() -> Optional[Card]:
    return Card.objects.filter(card_type=CardTypes.CARDBACK).order_by("-priority").first()


class Project(models.Model):
    key = models.UUIDField(default=uuid.uuid4, unique=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    user = models.ForeignKey(to=User, on_delete=models.CASCADE)
    date_created = models.DateTimeField(default=timezone.now)
    date_modified = models.DateTimeField(default=timezone.now)
    cardback = models.ForeignKey(to=Card, on_delete=models.SET_NULL, null=True, default=get_default_cardback)
    cardstock = models.CharField(max_length=20, choices=Cardstocks.choices, default=Cardstocks.S30_NONFOIL)

    def get_project_size(self) -> int:
        max_slot: Optional[int] = ProjectMember.objects.filter(project=self).aggregate(models.Max("slot"))["slot__max"]
        if max_slot is None:
            return 0
        return max_slot + 1

    def get_project_members(self) -> dict[str, dict[str, list[dict[str, Any]]]]:  # TODO: horrific typing
        members = list(ProjectMember.objects.filter(project=self))
        # TODO: consider rewriting this to groupby in SQL
        return {
            face: {
                query: [value.to_dict() for value in more_values]
                for query, more_values in itertools.groupby(values, key=lambda x: x.query)
            }
            for face, values in itertools.groupby(
                sorted(members, key=lambda x: (x.face, x.query)), key=lambda x: x.face
            )
        }

    def set_project_members(self, records: dict[str, dict[str, list[dict[str, Any]]]]) -> None:
        """
        Synchronise the members of this project with the contents of `records`.

        :param records: A set of records which follow the schema of `get_project_members`.
        :return: None
        """
        # TODO: protection against bad data here

        card_identifiers = set()
        for face in records.keys():
            for query in records[face].keys():
                for record in records[face][query]:
                    if (card_identifier := record.get("card_identifier"), None) is not None:
                        card_identifiers.add(card_identifier)

        card_identifiers_to_pk: dict[str, Card] = {
            x.identifier: x for x in Card.objects.filter(identifier__in=card_identifiers)
        }
        members: list[ProjectMember] = [
            ProjectMember(
                card=(
                    card_identifiers_to_pk[card_identifier]
                    if (card_identifier := value.get("card_identifier", None)) is not None
                    else None
                ),
                slot=value["slot"],
                query=query,
                face=face,
            )
            for face in Faces
            if (face_members := records.get(face, None)) is not None
            for query, values in face_members.items()
            for value in values
        ]
        with transaction.atomic():
            ProjectMember.objects.filter(project=self).delete()
            ProjectMember.objects.bulk_create(members)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "user_username": self.user.username,
            "date_created": dateformat.format(self.date_created, DATE_FORMAT),
            "date_modified": dateformat.format(self.date_modified, DATE_FORMAT),
            "project_size": self.get_project_size(),
        }

    def __str__(self) -> str:
        project_size = self.get_project_size()
        return f"{self.name}: Belongs to {self.user}, has {project_size} card{'s' if project_size != 1 else ''}"


class ProjectMember(models.Model):
    card = models.ForeignKey(to=Card, on_delete=models.SET_NULL, null=True, blank=True)
    project = models.ForeignKey(to=Project, on_delete=models.CASCADE)
    query = models.CharField(max_length=200)
    slot = models.IntegerField()
    face = models.CharField(max_length=5, choices=Faces.choices, default=Faces.FRONT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["card", "project", "slot", "face"], name="projectmember_unique")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_identifier": self.card.identifier if self.card else None,
            "query": self.query,
            "slot": self.slot,
            "face": self.face,
        }


class PilotRunLedger(models.Model):
    """
    One row per local-pilot invocation (run_pilot/run_name_frequency_elimination), written at
    start (status=RUNNING) and updated at end (status=COMPLETED/FAILED) - the durable, queryable
    record purge_machine_votes and any future tooling consult by run_id (see
    docs/features/catalog-completion-plan.md's Part 1). Purely an audit/context layer: the
    actual purge target set is always found by querying CardPrintingTag/CardArtistVote/
    CardTagVote directly by run_id, never by trusting this table's row count - a missing or
    inconsistent ledger row must never block a purge.
    """

    class Status(models.TextChoices):
        RUNNING = "running", gettext_lazy("Running")
        COMPLETED = "completed", gettext_lazy("Completed")
        FAILED = "failed", gettext_lazy("Failed")

    run_id = models.CharField(max_length=64, unique=True)
    command = models.CharField(max_length=64)
    dry_run = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    # best-effort visibility only (see AbstractWeightedVote.run_id's own docstring for why this
    # is never a hard gate) - the image's baked-in git SHA, if the build-time ARG was set.
    git_sha = models.CharField(max_length=40, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    votes_written = models.IntegerField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)
    # Free-form aggregate counters for commands whose completion shape doesn't fit votes_written
    # (e.g. run_image_evidence_cohort's Stage C fetch/compute counts - cohort_size/completed/
    # fetch_failures/short_circuited/lockout_hit/rss_limit_hit/elapsed_s/peak_rss_mb) - added so a
    # future command's own counters never need a fresh migration, matching CardScanLog's own
    # survivor_pks JSONField convention elsewhere in this file. Never interpreted by any
    # purge/consensus code path, purely a queryable audit payload.
    #
    # `peak_rss_mb` (2026-07-24, docs/proposals/stage-e-streaming.md §3 decision (6)/§1's
    # observability-gap finding) and `failure_reason` (same section, the "empty-failed-row" gap -
    # see `cardpicker.pilot_run_lifecycle.mark_ledger_failed`'s own docstring) are two counters
    # keys every long-running command's own ledger self-recording now aims to populate - documented
    # here, not migrated in as real columns, since both fit the existing free-form JSON convention
    # this field already exists for.
    counters = models.JSONField(null=True, blank=True)

    def __str__(self) -> str:
        return f"[{self.status}] {self.command} run_id={self.run_id}"


def _generate_envelope_trip_id() -> str:
    """Same shape as `local_identify_printing_tags.generate_run_id` (a UTC-timestamp prefix for
    human scannability, plus a short random suffix so two trips recorded in the same second never
    collide) - deliberately not reusing that function directly, since it lives in a different
    module for a different id kind and this model should not import a management-adjacent module
    just for an id-generation helper."""
    return f"envtrip-{timezone.now().strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


class EnvelopeTrip(models.Model):
    """
    A ledger-ADJACENT record (docs/proposals/stage-e-streaming.md §3 decision (5)/§10(a)'s
    ratified PASSIVE-mode operating envelope) - deliberately NOT a `PilotRunLedger` row or a
    `PilotRunLedger.counters` entry, unlike this file's other Stage E additions
    (`peak_rss_mb`/`failure_reason`), because a trip is a genuinely different shape: it needs to be
    looked up by a short human-facing id (`trip_id`, for the resume command's own `--acknowledge-
    trip <trip-id>` flag), queried for "is anything currently open" cheaply and often (every
    dispatch decision in the eventual phase-2 streaming loop), and mutated exactly once
    (acknowledged) after creation - none of which fits `PilotRunLedger`'s RUNNING/COMPLETED/FAILED
    lifecycle or its free-form, never-queried-by-key `counters` JSON blob.

    One row per BREACH, not per bar - a bar that trips twice (once, gets acknowledged, trips again
    later) gets two rows, an honest history of every pause the envelope ever enforced. See
    `cardpicker.operating_envelope`'s own module docstring for the four ratified bars this model's
    `bar` field names and the halt/resume mechanism this model persists one half of (the HALT+
    RECORD side - the RESUME side is `resolve_envelope_trip`'s own management command, which is the
    only code path permitted to set `acknowledged_at`).

    `run_id` is nullable and best-effort (matches `AbstractWeightedVote.run_id`'s own "never a hard
    gate" convention elsewhere in this file) - useful audit context for which streaming
    invocation was live when the trip fired, never load-bearing for whether the trip gates
    dispatch (see `operating_envelope.current_trip`'s own docstring for the exact scoping rule).
    """

    class Bar(models.TextChoices):
        HOST_LOAD = "host_load", gettext_lazy("Host load average")
        RSS = "rss", gettext_lazy("RSS per worker")
        FETCH_FAILURE_RATE = "fetch_failure_rate", gettext_lazy("Fetch failure rate")
        GOOGLE_LOCKOUT = "google_lockout", gettext_lazy("Google fetch lockout")

    trip_id = models.CharField(max_length=40, unique=True, default=_generate_envelope_trip_id)
    bar = models.CharField(max_length=32, choices=Bar.choices)
    # The observed values that crossed the bar (e.g. {"load_avg": 8.2, "ceiling": 7.0}) - free-form
    # JSON, same "queryable audit payload, never interpreted by any gate/consensus code path"
    # convention as PilotRunLedger.counters, scoped down to just this one breach's own numbers.
    detail = models.JSONField(null=True, blank=True)
    run_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    tripped_at = models.DateTimeField(auto_now_add=True)
    # Both null together (the open/gating state) or both set together (the closed/acknowledged
    # state) - enforced by operating_envelope.acknowledge_trip, the only code path that ever sets
    # either field; never enforced at the DB layer since this table has no other writer to guard
    # against.
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_note = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["acknowledged_at", "tripped_at"])]

    def __str__(self) -> str:
        state = "acknowledged" if self.acknowledged_at is not None else "OPEN"
        return f"[{state}] {self.bar} trip_id={self.trip_id}"


class StageEThrottleCounter(models.Model):
    """
    Stage E Phase 2 companion - a SINGLETON, always-exactly-one-row atomic counter for
    `cardpicker.stage_e_concurrency`'s "throttled-concurrency-cap" outcome (Tron gate round-1
    "COMPANION" review, observability anomaly 4, 2026-07-25: a throttled dispatch wrote no ledger
    row and emitted only a `logger.info` line, so the runbook's own "tune
    STAGE_E_MAX_CONCURRENT_DISPATCHES against the observed throttle rate"
    (docs/features/stage-e-operations.md) instruction had nothing queryable to check against).

    Deliberately NOT a `PilotRunLedger` row and NOT `EnvelopeTrip`-shaped (one row per event) -
    see `EnvelopeTrip`'s own docstring for the same "different shape needs a different table"
    reasoning this mirrors. A per-throttle-event row would WRITE-AMPLIFY under exactly the
    failure shape this whole feature exists to guard against: a burst of concurrent dispatches
    hitting an exhausted cap can throttle far more often than any dispatch ever completes -
    unlike `PilotRunLedger`'s one-row-per-invocation cadence or `EnvelopeTrip`'s one-row-per-
    breach cadence, both of which stay bounded by how often real work actually runs.

    Exactly one row, ever - `singleton_key` is `unique=True` so a first-ever-throttle race
    between two worker processes resolves to a single winning row via `record()`'s own
    `get_or_create` fallback (Django/Postgres serialize the losing INSERT into an
    `IntegrityError`, which `get_or_create` already retries as a fetch). `count` is only ever
    advanced via an atomic `F("count") + 1` UPDATE - race-safe under Postgres row-level locking
    even with many worker processes throttling at once, never a Python-side read-modify-write
    (which would silently lose increments under that exact concurrency).
    """

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True)
    count = models.PositiveIntegerField(default=0)
    last_throttled_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Stage E throttle count={self.count} (last {self.last_throttled_at})"

    @classmethod
    def record(cls) -> None:
        """Called once per `"throttled-concurrency-cap"` dispatch outcome
        (`cardpicker.stage_e_dispatch.dispatch_micro_batch`). Prefers the atomic `UPDATE` path
        (the common case, after the singleton row exists); only falls back to `get_or_create` the
        first time this counter is ever touched on a given deployment."""
        from django.db.models import F
        from django.utils import timezone

        updated = cls.objects.filter(singleton_key=1).update(count=F("count") + 1, last_throttled_at=timezone.now())
        if not updated:
            cls.objects.get_or_create(singleton_key=1, defaults={"count": 1, "last_throttled_at": timezone.now()})


class StageESweepCursor(models.Model):
    """
    Issue #458 - the persistent sweep cursor `cardpicker.stage_e_dispatch`'s chunked backlog walk
    (`_cursor_chunk_walk`, shared by `_select_micro_batch`'s Stage C fill and
    `stream_backstop_sweep._next_stage_d_backlog_ids`'s Stage D fill - issue #460) reads and
    advances, replacing a per-batch full-catalog anti-join (`Card.objects.exclude(pk__in=
    ImageEvidence.objects...)`, O(catalog) and re-run from scratch on every dispatch - see
    `_select_micro_batch`'s own docstring for the incident this fixes).

    KEYED, not a singleton (issue #460): `name` (`STAGE_C`/`STAGE_D` below) identifies which of the
    two independent backlog walks a row belongs to - Stage C's "no current ImageEvidence row yet"
    sweep and Stage D's "evidence complete, no join-key vote yet" sweep cover different pk-space
    progress and must never share one cursor's `position`/`wrap_count`, or advancing one walk would
    silently skip pk ranges the other walk hasn't examined yet. `get_cursor(name)` is the
    `get_or_create`-on-first-use entry point every classmethod below keys off; each name's own row
    is otherwise the exact one-row-per-key analogue of `StageEThrottleCounter`'s singleton pattern
    immediately above.

    `position` is the last Card pk this cursor's own walk has fully examined - the backlog fill
    always resumes at `pk__gt=position`, a pure pk-index range scan, never a full-table scan.
    `wrap_count` counts how many times this cursor's walk has reached the end of the pk space and
    restarted at 0 (a healthy, expected event on a near-complete catalog, not an error - see
    `_cursor_chunk_walk`'s own docstring and docs/features/stage-e-operations.md's Phase 2 section
    for the full semantics).

    CAS OWNERSHIP, not a lock: `_cursor_chunk_walk` claims a chunk via an optimistic
    compare-and-swap UPDATE (`filter(name=<key>, position=<expected>).update(position=<new>)`)
    BEFORE verifying it - rows-updated == 0 means a concurrent dispatch already claimed that range,
    so the loser discards the chunk and retries against the now-current position. Two concurrent
    dispatches walking the SAME cursor therefore sweep DISJOINT ranges instead of duplicating
    verification work, with no dedicated lock/transaction needed - the single-row UPDATE's own
    atomicity is the whole mechanism, same "never a Python-side read-modify-write" posture
    `StageEThrottleCounter.record` documents for its own counter. Two dispatches walking DIFFERENT
    cursors never contend at all - they update different rows.
    """

    # Issue #460 - the two backlog walks this cursor model serves. Defined here (the model that
    # owns the `name` field's value space) rather than duplicated as string literals in
    # `stage_e_dispatch.py`/`stream_backstop_sweep.py`, so the two call sites can never drift on
    # spelling.
    STAGE_C = "stage_c"
    STAGE_D = "stage_d"

    name = models.CharField(max_length=16, unique=True)
    position = models.BigIntegerField(default=0)
    wrap_count = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Stage E sweep cursor name={self.name} position={self.position} wrap_count={self.wrap_count}"

    @classmethod
    def get_cursor(cls, name: str) -> "StageESweepCursor":
        """Ensures `name`'s own row exists and returns it - the first-ever call for a given name on
        a fresh deployment creates it at `position=0`, `wrap_count=0`; every later call is a plain
        fetch. `stage_d`'s row is created lazily this way the first time the backstop sweep's own
        backlog (b) path runs; `stage_c`'s row is seeded by issue #460's own data migration
        (renamed from the pre-#460 singleton row, position preserved) rather than created fresh."""
        cursor, _ = cls.objects.get_or_create(name=name)
        return cursor

    @classmethod
    def try_advance(cls, name: str, from_position: int, to_position: int) -> bool:
        """The CAS claim described in the class docstring - `True` iff this call's own UPDATE
        matched `name`'s own row (i.e. `position` was still `from_position` the instant this ran),
        meaning this caller now owns the `(from_position, to_position]` range of `name`'s walk.
        `False` means a concurrent dispatch already moved `position` first - the caller must
        discard whatever it read for that range and retry against a freshly-read `position`, never
        assume ownership."""
        return cls.objects.filter(name=name, position=from_position).update(position=to_position) == 1

    @classmethod
    def try_wrap(cls, name: str, from_position: int) -> bool:
        """Same CAS discipline as `try_advance`, for the end-of-pk-space case: resets `name`'s own
        `position` to `0` and increments its `wrap_count` iff `position` was still `from_position`.
        Callers stop this dispatch regardless of the return value (`_cursor_chunk_walk`'s own
        docstring: "never continue scanning from 0 in the same dispatch") - a losing race here just
        means another concurrent dispatch already performed the same wrap, which is harmless
        either way."""
        return (
            cls.objects.filter(name=name, position=from_position).update(
                position=0, wrap_count=models.F("wrap_count") + 1
            )
            == 1
        )


class StageEFullCatalogCursor(models.Model):
    """
    2026-07-28 - the resume high-water mark for `management/commands/stream_full_catalog.py`'s
    full-catalog streaming pass. One row, ever (`singleton_key` is `unique=True`, the same
    singleton shape `StageEThrottleCounter` immediately above uses).

    DELIBERATELY NOT A `StageESweepCursor` ROW, and the distinction is the whole reason this model
    exists. That model's semantics are BACKLOG-sweep semantics: its `position` is a claim token
    advanced by an optimistic CAS so concurrent dispatches sweep disjoint ranges, and reaching the
    end of the pk space WRAPS it back to 0 and increments `wrap_count` - a lap counter over a
    backlog that is expected to be mostly-empty and re-swept forever. `stream_full_catalog` is not
    a backlog sweep: it drives an EXPLICIT, fully-enumerated cohort (every card with a
    `content_phash`, in pk order, nothing skipped for being already done), it must never wrap (a
    wrap would silently restart a 230k-card pass from the beginning instead of ending it), and it
    must never CAS-claim ranges away from the sweep cursors that the event-driven trigger and the
    cron backstop sweep depend on. Reusing `StageESweepCursor` would have coupled a full-catalog
    pass's own progress to those two live mechanisms' progress - advancing this pass would make the
    backstop sweep skip pk ranges it had never actually examined.

    `position` is the highest Card pk belonging to a batch this command has COMPLETED (dispatched
    without a halt/throttle) - the next invocation resumes at `pk__gt=position`. Advanced
    monotonically (`advance` below only ever moves it forward), so an out-of-order or replayed
    completion can never rewind a pass's progress; `reset_to` is the explicit operator override
    behind `--start-pk`, the only thing that can move it backwards. `cards_dispatched` is a
    cumulative, best-effort progress counter across every invocation - audit/observability only,
    never read back as control state.

    NOT WRITTEN BY `--sample` OR `--dry-run` RUNS (see that command's own module docstring): a
    sample run walks a pseudo-random subset spread across the whole pk space, so letting it advance
    this mark would jump a real catalog pass's resume point to near the end of the pk space after
    a single measurement batch.

    KEYED BY SCOPE, not a singleton - `stream_full_catalog`'s `--source <key>` flag means a run can
    traverse either the WHOLE catalog (`scope="full-catalog"`) or one source's cards
    (`scope="source:<key>"`), and those two walks cover different pk space. One shared mark would
    corrupt both directions: a `--source X` run whose cards happen to live high in the pk space
    would leave a mark that made a later full-catalog run skip everything below it (silently
    never-processed cards, the worst possible failure for a pass whose entire purpose is total
    coverage), and a completed full-catalog run would leave a mark that made a later `--source Y`
    run believe it had already finished. This is exactly the reasoning `StageESweepCursor`'s own
    docstring gives for being keyed rather than singleton, applied to a different key space.

    `scope` is derived by the command, never operator-supplied free text - see
    `stream_full_catalog.resume_scope_for`.
    """

    scope = models.CharField(max_length=64, unique=True)
    position = models.BigIntegerField(default=0)
    cards_dispatched = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return (
            f"Stage E full-catalog cursor scope={self.scope} position={self.position} "
            f"cards_dispatched={self.cards_dispatched}"
        )

    @classmethod
    def get_position(cls, scope: str) -> int:
        """`scope`'s own stored high-water mark, `0` when that scope has never been run (no row
        yet) - `0` is also the correct "start from the very beginning" value, since the walk
        resumes at `pk__gt=position` and Card pks are positive."""
        row = cls.objects.filter(scope=scope).first()
        return row.position if row is not None else 0

    @classmethod
    def advance(cls, scope: str, to_position: int, cards_dispatched: int = 0) -> None:
        """Record a completed batch against `scope`. MONOTONIC - a `to_position` that is not ahead
        of the stored one leaves `position` alone (the `position__lt` guard in the UPDATE's own
        filter), so this is safe to call unconditionally after every completed batch without a
        read-modify-write race. Creates `scope`'s row on first use."""
        now = timezone.now()
        updated = cls.objects.filter(scope=scope, position__lt=to_position).update(
            position=to_position,
            cards_dispatched=models.F("cards_dispatched") + cards_dispatched,
            updated_at=now,
        )
        if updated:
            return
        if cls.objects.filter(scope=scope).exists():
            # Row exists but is already at or ahead of `to_position` - monotonic no-op by design.
            return
        cls.objects.get_or_create(scope=scope, defaults={"position": to_position, "cards_dispatched": cards_dispatched})

    @classmethod
    def reset_to(cls, scope: str, position: int) -> None:
        """The `--start-pk` override (`stream_full_catalog`): the ONLY way `position` ever moves
        backwards. An explicit operator instruction to resume from a specific pk must win over
        whatever a prior invocation stored, otherwise `--start-pk 0` (restart the whole pass) would
        run its first batch and then silently snap back to the old mark on the next invocation."""
        updated = cls.objects.filter(scope=scope).update(position=position, updated_at=timezone.now())
        if not updated:
            cls.objects.get_or_create(scope=scope, defaults={"position": position})


class CardScanLog(models.Model):
    """
    Persists ABSTENTION evidence exactly like `AbstractWeightedVote` subclasses persist assent
    evidence (docs/features/catalog-completion-plan.md's addendum item 3, upgraded from
    propose-to-hold to build 2026-07-16) - one row per (card, engine) an engine actually looked
    at and did NOT cast a vote for. This restores the originally-intended design: the bleed
    engine's negative-only votes and Part 5's evidence-gathered-and-negative guard both
    presuppose a durable negative record existing somewhere, not just a positive one.

    Deliberately slim and additive-only - no vote-semantics change, the human-backed resolution
    gate is completely untouched by this model's existence. `skip_reason` uses the pipeline's
    own existing reason strings verbatim (see local_identify_printing_tags.py's skip_counts
    call sites) - not a separately-invented vocabulary - so a `grep` for a skip reason in the
    log output and a `WHERE skip_reason = '...'` query agree on what string to look for.

    MACHINE abstention only. `CardQuestionAbstention` (below) is this model's HUMAN counterpart -
    issue #712's "Not sure" signal on a `cardpicker.question_feed` item - and is deliberately a
    separate model rather than a shared one: this model's `run_id`/`skip_reason`/
    `evidence_types_used`/`survivor_pks` are all calculator-run bookkeeping with no human
    equivalent, and the resume-exclusion query this model serves
    (`local_identify_printing_tags._eligible_base_queryset`) must never be satisfied by a human
    tapping "Not sure" - the two express different facts ("this engine did not vote" vs. "this
    person looked and could not tell") and conflating them would let one silently stand in for
    the other in either direction.

    A card can have at most one CURRENT scan-log row per (card, anonymous_id) that actually
    matters for the resume-exclusion query (see local_identify_printing_tags._eligible_base_
    queryset) - older rows for the same pair are historical (multiple runs can each abstain on
    the same card for different or the same reason over time), not deduplicated away, since the
    resume query only cares whether ANY non-re-scannable row exists, and the scan_log table
    itself is a append-only audit trail like the vote tables are.

    Note (issue #207): a skip_reason that turned out to carry genuine whole-candidate-set
    no-match evidence (OCR's "parsed-but-no-match", fallback's "eliminated") no longer gets a
    row here at all - it gets a real `CardPrintingTag(is_no_match=True)` vote instead, same "the
    vote IS the record, no scan-log row needed" convention a positive vote already followed (see
    `TestScanLog.test_a_voted_card_gets_no_scan_log_row`). Only genuine abstention reasons
    (no evidence either way, or evidence against a single candidate/pair rather than the whole
    set) still land here.
    """

    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="scan_logs")
    # same field, same width, same semantics as AbstractWeightedVote.anonymous_id - this is
    # deliberately NOT a subclass of AbstractWeightedVote (a scan-log row is not a vote, has no
    # source/confidence/user, and should never be reachable via vote_consensus's resolution
    # machinery even by accident).
    anonymous_id = models.CharField(max_length=40)
    run_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    skip_reason = models.CharField(max_length=64)
    scanned_at = models.DateTimeField(auto_now_add=True)
    # Instrumentation for a future ranked-vote decision (issue #207, docs/theory.md's
    # Dawid-Skene addendum) - code-only, no schema for that future decision built here. Always
    # `[]` for a non-fallback row (OCR/phash have no sub-check concept of their own) and for
    # local_calculate_verdicts.calculate_fallback_verdict's own "no-sub-check-evidence" row (by
    # definition, nothing fired) - populated (issue #433) with whichever of "border"/"artist"/
    # "symbol" produced a reading for that same calculator's "eliminated" and "ambiguous" rows.
    evidence_types_used = models.JSONField(default=list, blank=True)
    # The candidate pks fallback's evidence intersection left standing (issue #433) - populated
    # for every skip local_calculate_verdicts.calculate_fallback_verdict itself returns: the
    # card's full candidate set for "no-sub-check-evidence" (nothing filtered anything), `[]` for
    # "eliminated", the actual shortlist for "ambiguous". That calculator computes this set to
    # pick its own skip_reason in the first place (`survivors` in calculate_fallback_verdict) -
    # this field just carries it out to the row instead of discarding it, no protected-core
    # reimplementation involved (docs/upstreaming/license-provenance.md §2: `filter_by_border_
    # color`/`match_artist` are called, not reimplemented; the symbol sub-check's own arithmetic
    # reimplementation predates this field). Still deliberately `null` for the LIVE PILOT engine's
    # own fallback rows (`local_fallback.run_fallback_for_card` / `FallbackOutcome`, a different
    # caller from the one above) - recovering its survivor set would mean either reimplementing
    # its border/artist/symbol sub-checks a second time here or having `FallbackOutcome` expose
    # the survivor set itself, and the latter touches protected core - still an open item, not
    # built by issue #433. Never populated for an OCR/phash row, or for a missing-`ImageEvidence`
    # skip (`calculate_fallback_verdict` is never reached, so no candidate set was ever resolved).
    survivor_pks = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["card", "anonymous_id"]),
            # Serves cardpicker.catalog_stats's skip-breakdown-by-engine aggregate
            # (compute_skip_breakdown's byReasonAndEngine, and any future query shaped the same
            # way - e.g. a distinct-cards-routed-to-review count) which filters/groups on
            # anonymous_id + skip_reason with no `card` in the predicate at all. The (card,
            # anonymous_id) index above is useless for that query - `card` is its LEADING column,
            # and Postgres can only use a leading prefix of a composite btree index, so a query
            # that never mentions `card` gets no help from it and falls back to a sequential scan.
            # Added by migration 0096 (see that migration's own docstring for the full reasoning,
            # including why anonymous_id leads) because `warm_catalog_stats` runs this query
            # HOURLY - a sequential scan here is a recurring, scheduled cost, not a one-off.
            # Explicit name (rather than Django's default hash-derived one), same convention
            # QuestionFeedServedLog.Meta uses further down this file for its own index, so
            # migration 0096 can be hand-written and verified against this file without a live
            # `makemigrations` run.
            models.Index(fields=["anonymous_id", "skip_reason"], name="card_scan_log_anon_skip_idx"),
        ]

    def __str__(self) -> str:
        return f"card={self.card_id} anonymous_id={self.anonymous_id} skip_reason={self.skip_reason}"


class CardQuestionAbstention(models.Model):
    """
    Issue #712. Records that a voter ENGAGED with a `cardpicker.question_feed` item and found it
    genuinely ambiguous ("Not sure") - real information about the card (this question is hard
    to answer for this specific image), unlike a "Skip" tap, which carries no signal about the
    card at all and writes nothing here or anywhere else (see QuestionFeed.tsx's `skip`).

    This is a HUMAN abstention - the counterpart to `CardScanLog`'s MACHINE abstention (see that
    model's own docstring for why the two are deliberately separate models). Like `CardScanLog`,
    deliberately NOT a subclass of `AbstractWeightedVote`: an abstention is not a vote, carries
    no source/confidence/user/polarity, and must never be reachable via `vote_consensus`'s
    resolution machinery even by accident.

    `question_type` mirrors `QuestionFeedItem.type` (e.g. "confirm_suggestion" /
    "identify_printing") - the same free-text convention `QuestionFeedServedLog.question_type`
    already uses, for the same reason: the question feed's own type vocabulary is the single
    source of truth, and duplicating it as a second closed enum here would just be a second
    place for the two to drift apart.

    `reason` is an optional coded why for the abstention (e.g. the border question's "Can't
    tell from this scan." answer sends `cannot-tell` - the scan genuinely doesn't show the
    border, which a bare "Not sure" tap cannot distinguish). Nullable and additive-only: a
    reason-carrying abstention is still this model, never a separate model or vote type.

    Unique on (card, anonymous_id, question_type); the write path is `get_or_create`, so a voter
    tapping "Not sure" more than once on the same pair (e.g. across repeat serves) records the
    fact once, not once per tap. This is also exactly the shape a future exclusion query needs
    (issue #713, not built here): "has this anonymous_id already abstained on this card for this
    question_type" is a single indexed equality lookup against this table's own unique
    constraint, e.g. `CardQuestionAbstention.objects.filter(card_id=..., anonymous_id=...,
    question_type=...).exists()`.
    """

    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="question_abstentions")
    anonymous_id = models.CharField(max_length=40)
    question_type = models.CharField(max_length=32)
    reason = models.CharField(max_length=32, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["card", "anonymous_id", "question_type"], name="cardquestionabstention_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"card={self.card_id} anonymous_id={self.anonymous_id} question_type={self.question_type}"


class SavedDeckKind(models.TextChoices):
    """
    See docs/proposals/proposal-g-user-accounts-saved-decks.md §3/decision 7. DECK rows are
    what a user explicitly named and saved, subject to SAVED_DECK_MAX_PER_USER; SNAPSHOT rows
    are the load-flow's auto-generated safety copies, deliberately outside that cap and pruned
    to a fixed 5-per-user FIFO ring by the view layer (2/saveDeck/) rather than by a setting -
    the ring size is an implementation safety valve, not a user-facing quota.
    """

    DECK = "deck"
    SNAPSHOT = "snapshot"


class UserCryptoProfile(models.Model):
    """
    Per-user zero-knowledge crypto parameters (docs/proposals/proposal-g-user-accounts-saved-decks.md
    §8). Created at first save, alongside that first SavedDeck row. Everything stored here is
    either public-safe (a salt/iteration-count strengthens key derivation - it isn't secret) or
    itself opaque ciphertext (the two wrapped-master-key slots) - the server can retain all of
    it forever without ever being able to derive or unwrap the actual master key.

    TWO independent wrapped copies of the same master key: one wrapped by the user's
    passphrase-derived key, one wrapped by their user-held recovery key. Both wrap the *same*
    master key, so a passphrase change only re-wraps the passphrase slot (the recovery slot,
    generated earlier, keeps unwrapping the same master key correctly - see §8's "Recovery key"
    section). Losing both means every owned SavedDeck's ciphertext is permanently unreadable -
    see §8's account-reset flow, which deletes rather than attempts recovery.
    """

    owner = models.OneToOneField(to=User, on_delete=models.CASCADE, related_name="saved_deck_crypto_profile")
    # PBKDF2-SHA256 parameters. Not secret - salt defends against precomputation, not disclosure.
    # iterations is stored per-profile (not read from a live setting) so raising the default
    # later never invalidates an existing user's already-derived key.
    salt = models.BinaryField()
    kdf_iterations = models.PositiveIntegerField()
    passphrase_wrapped_master_key = models.BinaryField()
    passphrase_wrapped_master_key_nonce = models.BinaryField()
    recovery_wrapped_master_key = models.BinaryField()
    recovery_wrapped_master_key_nonce = models.BinaryField()
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"crypto profile for owner={self.owner_id}"


class SavedDeck(models.Model):
    """
    A user's saved editor project, encrypted client-side (docs/proposals/proposal-g-user-
    accounts-saved-decks.md §8 - supersedes this model's originally-specified plaintext
    `name`/`state` fields). Deliberately a fresh model, not a resurrection of the dead
    Project/ProjectMember pair above (see the proposal's §3 "note on prior art" for why - a
    normalized per-card-row schema is a poor match for the frontend's actual Redux project
    shape, and keeping a Django schema in lockstep with every future frontend change is the
    wrong trade).

    `ciphertext` is the ENTIRE frontend Project shape, including the deck's own title - the
    server never sees a plaintext name anywhere, and therefore cannot enforce name-uniqueness
    (that becomes a client-side-only check - see §8's Consequences). `wrapped_dek` is this
    deck's own AES-256-GCM key, wrapped by the owner's master key (see UserCryptoProfile) -
    every deck has its own DEK so a passphrase change only ever re-wraps small key material,
    never re-encrypts any deck body. There is no separate "salt reference" field: the owner FK
    already identifies which UserCryptoProfile (and therefore which salt/iteration-count) this
    row's wrapped_dek was wrapped under.

    Named "SavedDeck", not "Project", specifically to avoid a third meaning of "Project" in this
    codebase (the frontend's own Project TypeScript type, and the legacy backend Project model
    above, are the other two).
    """

    key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(to=User, on_delete=models.CASCADE, related_name="saved_decks")
    kind = models.CharField(max_length=20, choices=SavedDeckKind.choices, default=SavedDeckKind.DECK)
    # opaque to the backend by design - never decrypted, inspected, or searched server-side.
    ciphertext = models.BinaryField()
    ciphertext_nonce = models.BinaryField()
    wrapped_dek = models.BinaryField()
    wrapped_dek_nonce = models.BinaryField()
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"SavedDeck {self.key} ({self.kind}): owner={self.owner_id}"


class SavedDeckShare(models.Model):
    """
    A per-deck, key-in-URL-fragment share link (docs/proposals/proposal-g-user-accounts-saved-
    decks.md's "PR-5, post-v1: per-deck share links"). Additive to the §3/§8 schema - does not
    touch SavedDeck/UserCryptoProfile.

    `id` is the public, unauthenticated-lookup `shareId` embedded in the share URL's path; the
    `shareKey` that actually unwraps `wrapped_dek` travels only in that URL's fragment (`#...`),
    which browsers never send to the server (see the spec section) - this row, and every view
    that serves it, never sees or stores that key.

    DELIBERATE DEVIATION from the spec's literal prose ("unwraps that deck's existing DEK ...
    re-wraps that same DEK with the new shareKey", implying a share reads the deck's *live*
    ciphertext going forward): `ciphertext`/`ciphertext_nonce` here are a FROZEN COPY taken from
    the referenced SavedDeck at share-creation time, not a live reference. This is required, not
    optional, given an already-shipped invariant this table builds on top of - every ordinary
    deck save (post_save_deck, via the frontend's encryptDeckPayloadForSave) unconditionally
    mints a FRESH DEK, including on an ordinary content-editing update, not just first save. A
    share that wrapped the deck's DEK once and then re-read the deck's current ciphertext on
    every future fetch would silently break the instant the owner made one ordinary edit to a
    shared deck - ordinary editing is expected far more often than an explicit share-revoke, so
    that would make sharing a deck you might ever edit again effectively unusable. Precedent for
    a frozen point-in-time ciphertext copy already exists in this schema (SavedDeckKind.SNAPSHOT
    rows on SavedDeck itself); this table applies the same idea. One consequence, also
    deliberate: revoking-with-rotation (re-encrypting the live deck under a fresh DEK, done via
    the ordinary saveDeck path - see MyDecksPage's rotate flow) does NOT invalidate any other
    still-outstanding share on that same deck, since each share's snapshot is fully self-
    contained and was never coupled to the live deck's key material in the first place. See
    docs/features/saved-decks.md and docs/troubleshooting.md for the full writeup.
    """

    id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, primary_key=True)
    deck = models.ForeignKey(to=SavedDeck, on_delete=models.CASCADE, related_name="shares")
    # frozen at share-creation time - a copy of `deck.ciphertext`/`deck.ciphertext_nonce` as they
    # stood at that moment, deliberately decoupled from any later edit to the live deck (see the
    # deviation note above).
    ciphertext = models.BinaryField()
    ciphertext_nonce = models.BinaryField()
    # this share's own DEK wrapping - the SAME deck DEK that was current at share-creation time,
    # wrapped under a fresh, share-specific `shareKey` that never reaches the server (only its
    # wrapping result does). Independent of every other share's wrapping and of the owner's own
    # master-key-wrapped copy - leaking one share's key material reveals nothing about any other.
    wrapped_dek = models.BinaryField()
    wrapped_dek_nonce = models.BinaryField()
    created_at = models.DateTimeField(default=timezone.now)
    # optional - null means "never expires". Enforced at fetch time only (get_shared_deck), not
    # by a proactive cleanup job; an expired-but-not-yet-deleted row still shows up in the
    # owner's own share listing (get_deck_shares) so they can see and revoke it like any other.
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"SavedDeckShare {self.id} for deck={self.deck_id}"

    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at < timezone.now()


class LandsAmbiguousResidue(models.Model):
    """
    Routing data, not votes (docs/features/catalog-completion-plan.md's Part 4 addendum,
    2026-07-19): one row per LANDS card where artist extraction succeeded but phash still
    couldn't pick a unique winner within the artist-narrowed candidate set
    (local_lands_identify.identify_land_printing's "phash-*" skip reasons). The artist match
    already paid the real cost of narrowing a name's full candidate pool (sometimes hundreds of
    printings, see BASIC_LAND_NAMES) down to a handful sharing that artist - throwing that work
    away and letting the human funnel start from the full pool again wastes it. Persisted here so
    a future funnel surface can serve "which of these N?" directly from `candidate_pks` instead
    of recomputing narrowing from scratch. Explicitly NOT a vote: no `AbstractWeightedVote`
    subclass, no consensus/resolution-gate interaction, no anonymous_id - a resolver skimming
    votes for this card sees nothing here, by design, until something explicitly reads this table.
    """

    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="lands_ambiguous_residue")
    run_id = models.CharField(max_length=64, db_index=True)
    artist_name = models.CharField(max_length=200)
    # the artist-matched surviving candidate set (CanonicalCard pks) - what the human funnel
    # would narrow a "which of these?" prompt to, instead of the name's full candidate pool.
    candidate_pks = models.JSONField()
    # {str(candidate_pk): hamming_distance} for every candidate in candidate_pks that had a
    # computable hash - lets a future consumer re-rank without recomputing phash distances,
    # and shows directly why phash couldn't pick a winner (e.g. two candidates within margin).
    phash_distances = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"LandsAmbiguousResidue card={self.card_id} artist={self.artist_name!r} candidates={self.candidate_pks}"


class ImageEvidence(models.Model):
    """
    Stage C's evidence store (docs/features/catalog-completion-plan.md's "Harvest-calculate
    pipeline" section, task #145, built per the owner's FINAL POSTURE directive 2026-07-19):
    persists ONLY derived facts about a card's image - hashes, OCR text, geometry, quality
    signals - never the image pixels themselves ("we index, we do not store images", see
    CLAUDE.md's "Governing premise"). Crop PIXELS exist only in memory during an extraction
    pass and are discarded; crop COORDINATES (geometry + TSV terms) are what persist here.

    Keyed by (card, content_hash) rather than card alone - `content_hash` is a copy of
    `Card.content_phash` taken AT EXTRACTION TIME, not a live reference. If the card's own
    uploaded image later changes (a new content_phash), a NEW row is created for the new hash
    rather than overwriting this one - the old row simply stops being "current" for that card
    (found by comparing against the card's live `content_phash`), it is not deleted or mutated.
    This is what makes the evidence store genuinely "computed-once-forever": re-extraction is
    only ever triggered by a real content change, and the audit trail of what was measured for
    a prior version of a card's image is preserved for free, matching CardScanLog/
    PilotRunLedger's own append-only conventions elsewhere in this file.

    `extractor_versions` is a per-field completion/versioning map (`{extractor_name: version}`)
    - no precedent for this existed in the codebase before this model; the closest prior art is
    `VoteSource`'s single flat `anonymous_id` version tag (e.g. "local-ocr-v1"), generalized here
    to one entry per extractor so a single extractor's failure or version bump degrades only its
    own fields, never blocks or invalidates fields other extractors already wrote (task #145's
    "extractor failure degrades only that field"). A field written by extractor X should only be
    trusted by a reader if `extractor_versions` contains a current-enough entry for X - readers
    that skip this check risk trusting a stale or partially-written field.

    RECONCILIATION LEDGER (owner directive 2026-07-19, task #155's fields folded into this
    substrate now rather than retrofitted per-extractor): "attempted = voted + each named
    skip-reason + dropped" is computed, not separately stored, from two existing sources - no
    parallel ledger table. "Voted" = a card whose `extractor_versions` contains that extractor's
    key AND has no matching `CardScanLog` row. "Skipped" = `extractor_versions` contains the key
    AND a `CardScanLog` row exists (`anonymous_id=<extractor name>`, `skip_reason=<why>`) -
    CardScanLog is reused as-is (its own docstring already anticipates exactly this: "a durable
    negative record existing somewhere, not just a positive one"), not duplicated. "Dropped" = a
    card in the attempted set with NEITHER an `extractor_versions` entry nor a `CardScanLog` row
    for that extractor (it crashed before completing). See `image_evidence.build_reconciliation_
    report()` for the query that assembles this and asserts it sums correctly.

    `run_id` records which run most recently wrote this row (Part 1's run_id convention,
    reused) - unlike `AbstractWeightedVote`/`CardScanLog`'s append-only "one row per event"
    use of run_id, this is a single mutable "last writer" field, since ImageEvidence itself is
    not append-only (see the content_hash-keyed "computed-once-forever" design above). It exists
    for reconciliation-report scoping ("what did run X actually touch"), not as a full history.

    This PR intentionally ships the model, the per-card callable extraction unit (see
    `image_evidence.py`), and the golden-set fixture (`cardpicker/golden_set.py`) together, with
    only the trivial `fetch_health` extractor riding along as end-to-end proof - NOT the full
    extractor manifest. Every subsequent extractor (geometry/bleed, OCR, phash, etc.) lands as
    its own PR, golden-set-tested before merge, per task #145's explicit hard-gate sequencing.

    geometry_bleed (task #147, first real manifest extractor, merged after this substrate PR):
    raw pixel dimensions + the SAME geometric aspect-ratio bleed classification
    `local_fallback.classify_bleed_edge` already uses for the live pilot/harvest vote path -
    called from `image_evidence.py`, not re-derived, so this extractor's output is guaranteed
    consistent with the shipped classifier rather than a second implementation that could drift
    from it. Deliberately first in the manifest order (docs/features/catalog-completion-plan.md):
    every later crop-coordinate extractor (#148+) needs `width`/`height` (to turn a fixed-fraction
    crop box into pixel coordinates) and `bleed_class` (to remap that box via
    `local_fallback.normalize_crop_box` before converting) - this extractor is what makes those
    two inputs available from stored evidence instead of a live re-fetch.

    geometry-group (public issue #148, second manifest extractor group): `layout_class` plus
    the three `*_crop_px` fields. See `image_evidence.py`'s module docstring for why
    `layout_class` reuses `local_fallback.classify_border_color` rather than
    `classify_frame_style` (the latter needs OCR outputs not available until issue #149's PR).
    `back_face_flag`, also named in issue #148's title, was deliberately NOT built in that PR -
    no signal for it was found anywhere in `Card`/`CanonicalCard` metadata or in
    `local_fallback.py`'s exported helpers. The owner later settled it (issue #199) as
    NAME-based, not image-based, so it never landed as a field here: see
    `cardpicker.printing_metadata_import.get_back_face_names`/`is_back_face` for the actual
    implementation and `docs/features/catalog-completion-plan.md`'s "back-face flag" paragraph
    for why no `ImageEvidence`/`CanonicalCard` field was added.

    OCR-group (public issue #149, third manifest extractor group): `collector_line_ocr` (raw
    text + `local_ocr.parse_collector_line`'s tolerant set-code/collector-number parse),
    `artist_ocr` (raw text + `local_fallback.extract_artist_name`'s tolerant "Illus. <name>"
    parse + `illus_anchor_fired`), and `collector_line_tsv` (word-level bounding boxes via
    `local_ocr.run_tesseract_tsv`, new in this PR). All three consume the `*_crop_px` pixel boxes
    the geometry-group extractor already computed rather than recomputing them, and none of them
    perform candidate matching (`local_ocr.validate_against_candidates`/`local_fallback.
    match_artist` both need a card's real `CandidatePrinting` list, which this per-card function
    never receives) - that comparison is Stage D calculator territory (task #151's
    pipeline-fidelity gate), not Stage C extraction. See `image_evidence.py`'s module docstring
    for the full rationale.

    symbol_region (public issue #160, "Part 4b: symbol harness"): `symbol_crop_px` turns
    `local_fallback.SYMBOL_STRIP_BOX` into pixel coordinates the same way the geometry-group's
    `*_crop_px` fields do; `symbol_phash` is a perceptual hash of that region ONLY - crop PIXELS
    are hashed in memory and discarded, never persisted (FINAL POSTURE item 2: "store the math,
    not the strip"). A raw content signal for Stage D's Scryfall lookup (the SET half of the
    collector+set join key), not a verdict - no candidate matching happens here, same reasoning
    the OCR-group paragraph above gives. See `image_evidence.py`'s module docstring for why this
    is a raw hash rather than `local_fallback.find_symbol_matches`'s own per-candidate comparison.

    legal_line (public issue #151, "Legal-line extractor + moderator flag + volume report (task
    #159)" - this PR builds the extractor + moderator-flag signal only, NOT the volume report,
    which stays out of scope per that issue's own held task #159 half): `legal_line_crop_px`
    turns a new `local_ocr.LEGAL_LINE_CROP_BOX` into pixel coordinates the same way every other
    `*_crop_px` field does - a NEW, dedicated crop region (not a reuse of `collector_line_crop_px`),
    verified against real fetched production images before being locked in (see `local_ocr.py`'s
    own comment on that constant). `legal_line_raw_text` + `local_ocr.parse_legal_line`'s tolerant
    parse of it (`legal_line_copyright_year`, `legal_line_proxy_marker_detected`) - metadata only,
    no candidate matching, same convention as every prior OCR-group field. The real motivating
    case (task #151/#159): a "MTG★EN ... NOT FOR SALE ©2022" watermark reads as plausible
    collector-line-shaped text to a tolerant parser - `legal_line_proxy_marker_detected` is the
    signal that lets Stage D's calculator reject that false-accept instead of trusting it.

    color_profile / quality_signals (public issue #150's re-spec, "Stage C visual-signal
    extractors" - the phash half of the original issue is DROPPED per the owner's 2026-07-20
    re-spec comment, superseded by user-submitted phash, task #203; set-symbol phash already
    shipped separately as symbol_region above): the LAST Stage C manifest extractor group.
    `color_mean_rgb`/`color_stddev_rgb` were per-channel (R, G, B) mean/stddev over the FULL
    fetched image via `cardpicker.local_image_quality.compute_color_profile` - the color_profile
    extractor was RETIRED 2026-07-27 (never consumed downstream; "stop extracting first, migrate
    later" - the two fields remain, simply never written anymore, until a future migration drops
    them). `blur_variance`/`image_entropy` are raw
    sharpness/histogram-entropy signals (`local_image_quality.compute_blur_variance`/
    `compute_entropy`) - Stage D's job to decide what counts as "too blurry"/"too flat," never
    this extractor's. `image_is_truncated` is a genuine integrity fact
    (`local_image_quality.is_image_truncated` forces a full pixel decode and catches the
    `OSError` Pillow raises for a genuinely truncated download) - checked BEFORE blur/entropy
    are computed, since a truncated image's partial pixel data would produce
    meaningless numbers rather than a real reading (see `image_evidence.py`'s module docstring
    for the exact ordering). `local_image_quality.py` is NOT protected core - new helpers land
    there directly, same convention `local_ocr.py` already established for OCR-adjacent
    (non-protected) additions.

    fetch_health completion (same re-spec): `fetch_latency_ms` (wall-clock time for the
    `image_cdn_fetch.fetch_card_image` call) and `fetch_image_format` (the fetched image's own
    `PIL.Image.format`, e.g. `"JPEG"`, blank-string-as-sentinel on fetch failure - same
    convention as `fetch_error_class`) complete the trivial substrate-PR version of this
    extractor, which only ever recorded `fetch_ok`/`fetch_error_class`. `fetch_error_class`'s
    own value space is deliberately UNCHANGED (still only `""`/`"fetch_failed"`) - widening it
    would cross into inventing a new skip-reason vocabulary entry, which
    `docs/features/catalog-completion-plan.md`'s own `CardScanLog` design explicitly warns
    against ("the pipeline's own existing strings verbatim... not a separately-invented
    vocabulary"); a truncated download (see `image_is_truncated` above) is reported through the
    SAME `"fetch_failed"` skip reason for the same reason - Stage D doesn't need a finer bucket
    than "no usable image data" to treat it correctly.

    artbox_phash (public issue #480, "Artbox perceptual-hash extractor: evidence-only, rides the
    next whole-catalog pass" - EVIDENCE ONLY, every consumer explicitly out of scope for this
    extractor): `artbox_crop_px` is one of two fixed-fraction boxes (`image_evidence.
    ARTBOX_MODERN_CROP_BOX`/`ARTBOX_OLD_CROP_BOX`), chosen by `artbox_frame_class` and remapped/
    scaled the same way every other `*_crop_px` field above is (crop COORDINATES only, never crop
    pixels). `artbox_frame_class` mirrors `local_fallback.classify_frame_style`'s own return
    convention ("old"/"modern"), same blank-string-as-sentinel convention as `bleed_class`/
    `layout_class` for the ambiguous/not-yet-run case - unlike `layout_class` (issue #148), which
    predates the OCR group and had to use `classify_border_color` as a stand-in, this extractor
    lands after issue #149's OCR group and can call the real frame classifier. `artbox_phash` is
    a perceptual hash (`imagehash.phash`, same family/size as `symbol_phash` above) of that
    region, stored the same signed-64-bit-int way.     Null when not yet computed (fetch failure, an
    unclassifiable frame, or a degenerate crop box - see `image_evidence.py`'s module docstring).

    pinline_inset (Stage C pinline-inset measurement, MEASURE-AND-PERSIST-ONLY - no consumer of
    any kind is built or wired in this PR): four per-edge inset-fraction measurements
    (`pinline_inset_frac_*`), four per-edge calls (`pinline_inset_call_*`, `local_pinline_
    inset.CALL_*`), and one whole-image verdict (`pinline_inset_verdict`, `local_pinline_
    inset.VERDICT_*`) - see `local_pinline_inset.py`'s own module docstring for what the number
    means, its two guards (the uniformity gate against measuring a borderless card's own artwork,
    and the black-on-black abstention that keeps an unreadable edge from ever reading as a
    measured zero), and what it deliberately does not do. Every `*_frac` field is a fraction of
    the relevant dimension, not a pixel count - `width`/`height` already on this row make pixels
    trivially derivable, while a fraction stays valid even if a later extraction pass fetches the
    same upload at a different resolution.
    """

    card = models.ForeignKey(to=Card, on_delete=models.CASCADE, related_name="image_evidence")
    content_hash = models.BigIntegerField(db_index=True)
    extractor_versions = models.JSONField(default=dict, blank=True)
    run_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    # fetch_health (the first, trivial extractor - see image_evidence.py)
    fetch_ok = models.BooleanField(null=True, blank=True)
    fetch_error_class = models.CharField(max_length=64, blank=True, default="")

    # geometry_bleed (task #147) - width/height are the fetched image's own pixel dimensions
    # (a function of the dpi the extraction pass fetched at, not a fixed catalog constant);
    # aspect_ratio is width/height, stored alongside rather than only derivable, since later
    # readers comparing against BLEED_ASPECT_RATIO/TRIM_ASPECT_RATIO shouldn't need to redo the
    # division themselves. bleed_class mirrors local_fallback.classify_bleed_edge's own return
    # convention ("bleed"/"trimmed"), stored as "" rather than null for the ambiguous/
    # not-yet-run case, matching fetch_error_class's own blank-string-as-sentinel convention
    # above.
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    aspect_ratio = models.FloatField(null=True, blank=True)
    bleed_class = models.CharField(max_length=16, blank=True, default="")
    bleed_diff_mm = models.FloatField(null=True, blank=True)

    # geometry-group (issue #148) - layout_class mirrors local_fallback.classify_border_color's
    # own return convention ("black"/"white"/"silver"/"borderless"), same blank-string-as-
    # sentinel convention as bleed_class above for the ambiguous/not-yet-run case.
    layout_class = models.CharField(max_length=16, blank=True, default="")
    # Pixel-coordinate crop boxes (issue #148's "crop coordinates") - each a [left, top, right,
    # bottom] int list in the fetched image's own pixel space, derived from an existing
    # fixed-fraction crop-box constant (local_ocr.DEFAULT_CROP_BOX / local_fallback.
    # ARTIST_CROP_BOX / local_phash.ART_CROP_BOX) remapped via local_fallback.normalize_crop_box
    # for this row's own bleed_class, then multiplied out by width/height. Crop COORDINATES
    # only - crop PIXELS are never persisted (CLAUDE.md's "Governing premise"). Null when not
    # yet computed (fetch failure - see image_evidence.py).
    collector_line_crop_px = models.JSONField(null=True, blank=True)
    artist_crop_px = models.JSONField(null=True, blank=True)
    art_crop_px = models.JSONField(null=True, blank=True)

    # art_edge (issue #830 defect 3) - local_art_edge.classify_art_edge_continuity's own return
    # convention ("framed"/"extended"/"mixed"), same blank-string-as-sentinel convention as
    # layout_class above for the ambiguous/not-yet-run case. EVIDENCE-ONLY: nothing votes on this
    # column yet (see local_art_edge.cast_art_edge_continuity_vote's own docstring).
    art_edge_class = models.CharField(max_length=16, blank=True, default="")

    # OCR-group (issue #149) - collector_line_ocr/artist_ocr/collector_line_tsv. Raw text +
    # local_ocr.parse_collector_line's tolerant parse of it (blank-string-as-sentinel for "no
    # OCR run yet, or nothing plausible found", same convention as bleed_class/layout_class
    # above) - no candidate matching happens here (that's Stage D's job, see image_evidence.py's
    # module docstring); this is metadata only, per FINAL POSTURE item 2.
    collector_line_raw_text = models.TextField(blank=True, default="")
    collector_line_set_code = models.CharField(max_length=16, blank=True, default="")
    collector_line_collector_number = models.CharField(max_length=16, blank=True, default="")
    # Word-level bounding boxes from tesseract's own TSV output (local_ocr.run_tesseract_tsv) for
    # whichever preprocessing variant produced collector_line_raw_text above - a list of
    # {text, left, top, width, height, conf} dicts, coordinates in that crop's own pixel space.
    # Crop COORDINATES only, never crop pixels (CLAUDE.md's "Governing premise"). Null when not
    # yet computed (fetch failure); an empty list is a real "nothing recognized" outcome, not the
    # same as null - same distinction geometry-group's *_crop_px fields draw.
    collector_line_word_boxes = models.JSONField(null=True, blank=True)
    # artist_ocr: local_fallback.extract_artist_name's tolerant "Illus. <name>" parse, run first
    # against collector_line_ocr's own raw text (reuse-before-recompute, see image_evidence.py)
    # then against a fresh crop+OCR pass over artist_crop_px. illus_anchor_fired mirrors
    # local_fallback.detect_illus_anchor's own (fired, name) return convention - True/False once
    # computed, null only if the fetch itself failed (same null-vs-blank convention as
    # fetch_ok above).
    artist_ocr_raw_text = models.TextField(blank=True, default="")
    artist_ocr_name = models.CharField(max_length=64, blank=True, default="")
    illus_anchor_fired = models.BooleanField(null=True, blank=True)

    # symbol_region (issue #160, "Part 4b: symbol harness") - symbol_crop_px is
    # local_fallback.SYMBOL_STRIP_BOX remapped/scaled the same way the geometry-group's *_crop_px
    # fields above are (crop COORDINATES only, never crop pixels). symbol_phash is a perceptual
    # hash (imagehash.phash) of that region, stored as a signed 64-bit int via twos_complement -
    # the same representation local_phash.py's own private _hash_to_int uses for
    # Card.content_phash/CanonicalCard.image_hash. Null when not yet computed (fetch failure or a
    # degenerate crop box - see image_evidence.py's module docstring).
    symbol_crop_px = models.JSONField(null=True, blank=True)
    symbol_phash = models.BigIntegerField(null=True, blank=True)

    # legal_line (issue #151, task #159's extractor half) - legal_line_crop_px is
    # local_ocr.LEGAL_LINE_CROP_BOX remapped/scaled the same way every other *_crop_px field is
    # (crop COORDINATES only, never crop pixels). legal_line_raw_text + local_ocr.
    # parse_legal_line's tolerant parse of it - same blank-string-as-sentinel convention as
    # collector_line_raw_text/collector_line_set_code above for "no OCR run yet, or nothing
    # plausible found". legal_line_proxy_marker_detected mirrors illus_anchor_fired's own
    # True/False-once-computed/null-only-on-fetch-failure convention - the moderator-flag signal
    # (task #151/#159): True when a "NOT FOR SALE"/"PROXY" watermark was detected in this card's
    # legal-line region, consumed by Stage D (not acted on here - this extractor emits the raw
    # signal only, same "extractors emit signals, Stage D calculators/consumers act on them"
    # discipline every prior extractor in this file follows).
    legal_line_crop_px = models.JSONField(null=True, blank=True)
    legal_line_raw_text = models.TextField(blank=True, default="")
    legal_line_copyright_year = models.CharField(max_length=4, blank=True, default="")
    legal_line_proxy_marker_detected = models.BooleanField(null=True, blank=True)

    # fetch_health completion (issue #150's re-spec) - fetch_latency_ms/fetch_image_format
    # complete the trivial substrate-PR version of this extractor (fetch_ok/fetch_error_class
    # above). fetch_image_format uses the same blank-string-as-sentinel convention as
    # fetch_error_class for the not-yet-computed/fetch-failed case.
    fetch_latency_ms = models.FloatField(null=True, blank=True)
    fetch_image_format = models.CharField(max_length=16, blank=True, default="")

    # quality_signals (issue #150's re-spec) - image_is_truncated is a genuine integrity fact
    # (null only if the fetch itself failed, same null-vs-blank convention as fetch_ok/
    # illus_anchor_fired above); blur_variance/image_entropy are only computed when the image
    # loaded cleanly (null on fetch failure OR a truncated image - see image_evidence.py's
    # module docstring for the exact ordering).
    image_is_truncated = models.BooleanField(null=True, blank=True)
    blur_variance = models.FloatField(null=True, blank=True)
    image_entropy = models.FloatField(null=True, blank=True)

    # color_profile (issue #150's re-spec) - per-channel (R, G, B) mean/stddev over the full
    # fetched image, each a 3-element float list. EXTRACTOR RETIRED 2026-07-27 (never consumed
    # downstream): these fields are kept for backwards compatibility, simply never written
    # anymore - "stop extracting first, migrate later" (a future migration drops them).
    color_mean_rgb = models.JSONField(null=True, blank=True)
    color_stddev_rgb = models.JSONField(null=True, blank=True)

    # artbox_phash (issue #480) - artbox_crop_px is one of ARTBOX_MODERN_CROP_BOX/
    # ARTBOX_OLD_CROP_BOX (image_evidence.py), chosen by artbox_frame_class and remapped/scaled
    # the same way every other *_crop_px field above is (crop COORDINATES only, never crop
    # pixels). artbox_frame_class mirrors local_fallback.classify_frame_style's own return
    # convention ("old"/"modern"), blank-string-as-sentinel like bleed_class/layout_class above.
    # artbox_phash is a perceptual hash (imagehash.phash) of that region, stored as a signed
    # 64-bit int via twos_complement - the same representation symbol_phash above uses. Null when
    # not yet computed (fetch failure, an unclassifiable frame, or a degenerate crop box).
    artbox_crop_px = models.JSONField(null=True, blank=True)
    artbox_frame_class = models.CharField(max_length=16, blank=True, default="")
    artbox_phash = models.BigIntegerField(null=True, blank=True)

    # pinline_inset (local_pinline_inset.measure_pinline_inset, MEASURE-AND-PERSIST-ONLY - no
    # existing crop box computation above reads these fields yet): four per-edge measurements of
    # how far the first sustained colour transition inward from this image's own edge sits - on a
    # bordered card, the pinline where the border's ink meets the frame/art, not a canvas
    # boundary. See local_pinline_inset.py's own module docstring for what the number means and
    # how it was validated, and its two guards.
    #
    # Stored as FRACTIONS of the relevant dimension, not pixels: width/height are already on this
    # row, so a pixel value stays trivially derivable, while a fraction is a property of the
    # UPLOAD itself and stays valid even if a later extraction pass fetches the same upload at a
    # different resolution.
    #
    # Each *_frac field is null when that edge's own reading is INDETERMINATE, never zero -
    # distinguishing "not measured" from "measured a zero-distance inset" matters most exactly
    # where it's easy to get wrong: a black canvas around a black-bordered card produces no colour
    # departure at all, so the null is the honest reading, and the paired *_call field (local_
    # pinline_inset.CALL_*) says why. A consumer that defaulted a null fraction to zero would
    # silently mislocate a black-on-black card's pinline instead of correctly declining to.
    pinline_inset_frac_top = models.FloatField(null=True, blank=True)
    pinline_inset_frac_bottom = models.FloatField(null=True, blank=True)
    pinline_inset_frac_left = models.FloatField(null=True, blank=True)
    pinline_inset_frac_right = models.FloatField(null=True, blank=True)
    # local_pinline_inset.CALL_* - measured/indeterminate_black/no_transition. Blank-string-as-
    # sentinel for "not yet computed", same convention as bleed_class/layout_class above.
    pinline_inset_call_top = models.CharField(max_length=24, blank=True, default="")
    pinline_inset_call_bottom = models.CharField(max_length=24, blank=True, default="")
    pinline_inset_call_left = models.CharField(max_length=24, blank=True, default="")
    pinline_inset_call_right = models.CharField(max_length=24, blank=True, default="")
    # local_pinline_inset.VERDICT_* - measured/ambiguous/indeterminate. Blank-string-as-sentinel
    # for "not yet computed", same convention as the per-edge calls above.
    pinline_inset_verdict = models.CharField(max_length=16, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Evidence transfer (issue #473 PR-2, folded with issue #472) - stamped at BOTH real
    # extraction time (image_evidence.compute_card_evidence, copied from the source card's own
    # live Card.md5_checksum/sha256_checksum at the moment this row was computed) and transfer
    # time (evidence_transfer.transfer_evidence, copied from the TARGET card - the one whose
    # (card, content_hash) row this is - never from the sibling the fields were copied from,
    # since find_transfer_source already verified the target's own value agrees). Used two ways:
    # (1) evidence CURRENCY (image_evidence.current_evidence_queryset) additionally requires
    # md5_checksum == Card.md5_checksum whenever BOTH are non-null - closes the silent
    # in-place-file-replacement hole a content_phash-only currency check can miss. NULL-TOLERANT:
    # a legacy row written before this field existed (md5_checksum is None here) stays current
    # under the content_hash check alone until it's naturally re-extracted - no forced mass
    # recompute. (2) evidence_transfer.find_transfer_source's own sibling-pairing search, which
    # additionally requires sha256_checksum to match whenever BOTH sides carry one (the binding
    # 2026-07-25 pairing rule on issue #473 - md5 collisions are constructible, sha256 is the
    # cryptographic backstop). sha256_checksum mirrors Card.sha256_checksum's own nullability
    # (both are NULL for exactly the same reasons - LOCAL_FILE sources, or a Drive listing walked
    # before this field existed - never invented, never backfilled from image bytes we don't hold).
    md5_checksum = models.CharField(max_length=32, null=True, blank=True, db_index=True)
    sha256_checksum = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    # transferred: True iff this row's own field values were COPIED from an md5-sibling's own
    # current evidence (evidence_transfer.transfer_evidence) rather than produced by a real
    # fetch+extraction pass against this card's own image. Until issue #473 PR-3 merged
    # (2026-07-25), `local_calculate_verdicts`'s two MACHINE-VOTING Stage D calculators (join-key/
    # fallback, IN THEIR OWN LOOP BODIES - not `_eligible_cards_queryset`, which never read this
    # field) excluded any card whose CURRENT evidence carried this flag from machine voting
    # outright: a transferred row's own machine "observation" is the SAME underlying bytes a
    # sibling card already voted from, not an independent one, and casting a vote from it would
    # have fabricated independence the vote-weight matrix assumes is real (docs/theory.md's
    # independence-assumptions section). That interim guard is RETIRED as of PR-3
    # (`TRANSFERRED_INTERIM_GUARD_SKIP_REASON`'s own module-level comment in
    # `local_calculate_verdicts.py` carries the full history) - the independence concern is now
    # handled at the GROUP tally level instead, by `vote_consensus.pool_group_votes` deduping a
    # transferred card's vote against the sibling's it was copied from (both cast under the same
    # calculator's fixed `anonymous_id`, so they share a `dedupe_key`), which is strictly more
    # correct than excluding the vote outright: a transferred card can still contribute when a
    # DIFFERENT agent is the one voting on the sibling. This field remains a plain, still-accurate
    # provenance flag, read by no calculator anymore. `transferred_from_card_id` is a plain
    # (non-FK) audit trail of which sibling card's row this one was copied from, kept only for a
    # future incident's own "why does this row look like that one" question.
    transferred = models.BooleanField(default=False)
    transferred_from_card_id = models.IntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["card", "content_hash"], name="unique_image_evidence_per_card_hash")
        ]
        indexes = [models.Index(fields=["card", "content_hash"])]

    def __str__(self) -> str:
        return f"ImageEvidence card={self.card_id} content_hash={self.content_hash} extractors={sorted(self.extractor_versions)}"


class QuestionFeedServedPool(models.TextChoices):
    """Which side of `question_feed.py`'s >=51% mix-composition split a served question came
    from - see `QuestionFeedServedLog`'s own docstring."""

    LIKELY_RESOLVE = "likely_resolve", gettext_lazy("Likely resolve")
    REMAINDER = "remainder", gettext_lazy("Remainder")


class QuestionFeedServedLog(models.Model):
    """
    One row per `GET 2/questionFeed/` response that actually served a question - the mix-
    composition record `cardpicker.question_feed`'s >=51%-likely-resolve serving policy
    requires (2026-07-24 data brief, SOUNDNESS NOTE: "Recommend ... log served-mix composition
    (ratio + family/reason per served question) per session, so a future audit can correlate
    click latency/agreement-rate against a session's easy-question exposure" - see
    docs/features/printing-tags.md's "Unified question feed" section for the full citation).
    This is a selection-layer bias-conditioning record ONLY - it is never read by
    `vote_consensus.resolve_weighted_consensus` or any consensus computation, and writing a
    row here changes no vote's weight, threshold, or gate. Append-only, same convention as
    `CardScanLog` (a durable audit trail, not a mutated cache) - the serving path's own read of
    this table (`question_feed._served_mix_ratio`) is a cheap two-count aggregate over
    `anonymous_id`, not a full-row scan.

    `pool` records which side of the mix split this item came from;`question_type` mirrors
    `QuestionFeedItem.type` (e.g. "confirm_suggestion"/"identify_printing"/"artist"/"tag");
    `origin_reason` is a short, human-readable tag for which specific ranked-order rule matched
    (e.g. "printing_one_vote_from_resolving", "tier_2_contested", "tier_4_quick_negative_to_
    review", "tier_4_fresh") - free text rather than a closed enum, since the ranked order
    itself is expected to keep evolving (see this module's own module-level TextChoices for
    values that ARE meant to be a closed set; this one deliberately isn't).
    """

    anonymous_id = models.CharField(max_length=40, db_index=True)
    pool = models.CharField(max_length=16, choices=QuestionFeedServedPool.choices)
    question_type = models.CharField(max_length=32)
    origin_reason = models.CharField(max_length=64, blank=True, default="")
    served_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # explicit name (rather than Django's default hash-derived one) so the migration below
        # can be hand-written and verified against this file without needing a live `makemigrations`
        # run to discover what hash Django would have picked.
        indexes = [models.Index(fields=["anonymous_id", "served_at"], name="qf_served_log_anon_served_idx")]

    def __str__(self) -> str:
        return f"anonymous_id={self.anonymous_id} pool={self.pool} question_type={self.question_type}"


__all__ = [
    "Faces",
    "CardTypes",
    "Cardstocks",
    "Games",
    "CanonicalArtist",
    "CanonicalExpansion",
    "CanonicalCard",
    "Source",
    "summarise_contributions",
    "Card",
    "Tag",
    "DFCPair",
    "get_default_cardback",
    "Project",
    "ProjectMember",
    "PilotRunLedger",
    "CardScanLog",
    "CardQuestionAbstention",
    "SavedDeckKind",
    "SavedDeck",
    "UserCryptoProfile",
    "LandsAmbiguousResidue",
    "ImageEvidence",
    "QuestionFeedServedPool",
    "QuestionFeedServedLog",
]

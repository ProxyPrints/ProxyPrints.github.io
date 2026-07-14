import itertools
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

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
from cardpicker.sources.source_types import SourceTypeChoices


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
            frame=metadata.frame if metadata is not None else "",
            releasedAt=metadata.released_at.isoformat() if metadata is not None and metadata.released_at else None,
        )


class CanonicalPrintingMetadata(models.Model):
    """
    Additive sidecar holding Scryfall printing-level fields not already captured by
    `CanonicalCard` (which already stores scryfall_id/oracle_id/set/collector_number/
    artist/image data via its `identifier`/`canonical_id`/`expansion`/`collector_number`
    fields). One row per `CanonicalCard`, populated by `import_scryfall_printing_metadata`.
    """

    canonical_card = models.OneToOneField(
        to=CanonicalCard, on_delete=models.CASCADE, primary_key=True, related_name="printing_metadata"
    )
    full_art = models.BooleanField(default=False)
    border_color = models.CharField(max_length=20, blank=True)
    frame = models.CharField(max_length=10, blank=True)
    frame_effects = models.JSONField(default=list, blank=True)
    promo_types = models.JSONField(default=list, blank=True)
    edhrec_rank = models.IntegerField(null=True, blank=True)
    printings_count = models.IntegerField(default=0)
    released_at = models.DateField(null=True, blank=True)
    lang = models.CharField(max_length=5, default="en")

    def __str__(self) -> str:
        return f"Printing metadata for {self.canonical_card}"


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
        (qty_total, qty_cards, qty_cardbacks, qty_tokens, _) = self.count()
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
    # Per-tag vote status, written by cardpicker.tag_consensus.resolve_and_persist_tag_votes:
    # {tag.name: "resolved_apply" | "resolved_reject" | "contested" | "unresolved"}. An absent
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
    image_hash = models.BigIntegerField()

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

    def serialise(self) -> SerialisedCard:
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
            canonicalArtist=resolved_artist.serialise() if resolved_artist is not None else None,
            canonicalArtistIsFromVoteOnly=artist_source == "inferred_canonical_artist",
            canonicalArtistSource=artist_source,
            printingTagStatus=SerialisedPrintingTagStatus(self.printing_tag_status),
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

    class Meta:
        ordering = ["-priority"]


class VoteSource(models.TextChoices):
    """
    Shared `source` enum for every `AbstractWeightedVote` subclass (`CardPrintingTag`,
    `CardArtistVote`, `CardTagVote`) - not printing-tag-specific despite the historical name
    this replaced (`CardPrintingTagSource`). The stored string values are unchanged.
    """

    USER = "user", gettext_lazy("User")
    ADMIN = "admin", gettext_lazy("Admin")
    AI = "ai", gettext_lazy("AI")
    FEDERATED = "federated", gettext_lazy("Federated")


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
    source = models.CharField(max_length=10, choices=VoteSource.choices, default=VoteSource.USER)
    confidence = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # federation-readiness stub (see docs/federation-v1.md) - no import path sets this yet.
    peer = models.CharField(
        max_length=64, null=True, blank=True, help_text="Federation peer name; set only when source='federated'"
    )

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


class Tag(models.Model):
    name = models.CharField(unique=True)
    # null=True is just for admin panel
    aliases = ArrayField(models.CharField(max_length=200), default=list, blank=True)
    is_enabled_by_default = models.BooleanField(default=True)
    parent = models.ForeignKey(to="Tag", null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self) -> str:
        return self.name

    def serialise(self) -> SerialisedTag:
        return SerialisedTag(
            name=self.name,
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
                card=card_identifiers_to_pk[card_identifier]
                if (card_identifier := value.get("card_identifier", None)) is not None
                else None,
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
]

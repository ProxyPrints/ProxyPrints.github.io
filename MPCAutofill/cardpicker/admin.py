from functools import reduce
from operator import or_

from django.contrib import admin
from django.db.models import Q, QuerySet
from django.http import HttpRequest

from .artist_consensus import get_contested_artist_card_ids
from .models import (
    CanonicalArtist,
    CanonicalCard,
    CanonicalExpansion,
    CanonicalPrintingMetadata,
    Card,
    CardArtistVote,
    CardPrintingTag,
    CardReport,
    CardTagVote,
    DFCPair,
    Project,
    ProjectMember,
    Source,
    Tag,
    TagAliasSuggestion,
    TagSuggestionStatus,
)
from .printing_consensus import get_contested_card_ids
from .sources.update_database import update_database
from .tag_consensus import get_contested_tag_pairs


# Register your models here.
@admin.register(Tag)
class AdminTag(admin.ModelAdmin[Tag]):
    list_display = ("name", "display_name")
    search_fields = ("name", "display_name")


@admin.register(Card)
class AdminCard(admin.ModelAdmin[Card]):
    list_display = ("identifier", "name", "source", "dpi", "date_created", "tags")
    search_fields = ("identifier", "name")
    raw_id_fields = ["canonical_card", "inferred_canonical_card"]


@admin.register(DFCPair)
class AdminDFCPair(admin.ModelAdmin[DFCPair]):
    list_display = ("front", "back")
    search_fields = ("front",)


@admin.register(Source)
class AdminSource(admin.ModelAdmin[Source]):
    list_display = ("name", "identifier", "contribution", "description")
    search_fields = ("name", "identifier")
    actions = ["rescan_sources"]

    def contribution(self, obj: Source) -> str:
        qty_all, qty_cards, qty_cardbacks, qty_tokens, avgdpi = obj.count()

        return "{} images - {} cards, {} cardbacks, and {} tokens @ {} DPI on average".format(
            qty_all, qty_cards, qty_cardbacks, qty_tokens, avgdpi
        )

    @admin.action(description="Re-scan selected sources for new/updated/removed images")
    def rescan_sources(self, request: HttpRequest, queryset: QuerySet[Source]) -> None:
        for source in queryset:
            update_database(source_key=source.key)


@admin.register(Project)
class AdminProject(admin.ModelAdmin[Project]):
    list_display = ("key", "name", "user", "date_created", "date_modified", "cardback", "cardstock")


@admin.register(ProjectMember)
class AdminCardProjectMembership(admin.ModelAdmin[ProjectMember]):
    list_display = ("card_id", "project", "query", "slot", "face")


@admin.register(CanonicalArtist)
class AdminCanonicalArtist(admin.ModelAdmin[CanonicalArtist]):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(CanonicalExpansion)
class AdminCanonicalExpansion(admin.ModelAdmin[CanonicalExpansion]):
    list_display = ("code", "name", "game")
    search_fields = ("code", "name")


@admin.register(CanonicalCard)
class AdminCanonicalCard(admin.ModelAdmin[CanonicalCard]):
    list_display = ("identifier", "name", "expansion", "collector_number", "is_default")
    search_fields = ("name",)


@admin.register(CanonicalPrintingMetadata)
class AdminCanonicalPrintingMetadata(admin.ModelAdmin[CanonicalPrintingMetadata]):
    list_display = (
        "canonical_card",
        "full_art",
        "border_color",
        "frame",
        "edhrec_rank",
        "printings_count",
        "released_at",
        "lang",
    )
    list_filter = ("full_art", "border_color", "frame", "lang")
    search_fields = ("canonical_card__name",)
    raw_id_fields = ["canonical_card"]


class ContestedCardFilter(admin.SimpleListFilter):
    """
    Admin-triage wrapper around cardpicker.printing_consensus.get_contested_card_ids -
    see that function's docstring for what "contested" means here.
    """

    title = "contested"
    parameter_name = "contested"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin[CardPrintingTag]) -> list[tuple[str, str]]:
        return [("yes", "Yes")]

    def queryset(self, request: HttpRequest, queryset: QuerySet[CardPrintingTag]) -> QuerySet[CardPrintingTag]:
        if self.value() != "yes":
            return queryset
        return queryset.filter(card_id__in=get_contested_card_ids())


@admin.register(CardPrintingTag)
class AdminCardPrintingTag(admin.ModelAdmin[CardPrintingTag]):
    list_display = ("card", "printing", "is_no_match", "source", "confidence", "anonymous_id", "created_at")
    list_filter = ("source", "is_no_match", ContestedCardFilter)
    search_fields = ("card__name",)
    raw_id_fields = ["card", "printing"]


class ContestedArtistFilter(admin.SimpleListFilter):
    """Admin-triage wrapper around `cardpicker.artist_consensus.get_contested_artist_card_ids` -
    mirrors `ContestedCardFilter` exactly, generalized to artist votes."""

    title = "contested"
    parameter_name = "contested"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin[CardArtistVote]) -> list[tuple[str, str]]:
        return [("yes", "Yes")]

    def queryset(self, request: HttpRequest, queryset: QuerySet[CardArtistVote]) -> QuerySet[CardArtistVote]:
        if self.value() != "yes":
            return queryset
        return queryset.filter(card_id__in=get_contested_artist_card_ids())


class ContestedTagFilter(admin.SimpleListFilter):
    """Admin-triage wrapper around `cardpicker.tag_consensus.get_contested_tag_pairs` - same
    idea as `ContestedCardFilter`, but the unit is a (card, tag) pair rather than just a card,
    so the queryset filter is an OR of per-pair conditions rather than a plain `card_id__in`."""

    title = "contested"
    parameter_name = "contested"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin[CardTagVote]) -> list[tuple[str, str]]:
        return [("yes", "Yes")]

    def queryset(self, request: HttpRequest, queryset: QuerySet[CardTagVote]) -> QuerySet[CardTagVote]:
        if self.value() != "yes":
            return queryset
        pairs = get_contested_tag_pairs()
        if not pairs:
            return queryset.none()
        condition = reduce(or_, (Q(card_id=card_id, tag_id=tag_id) for card_id, tag_id in pairs))
        return queryset.filter(condition)


@admin.register(CardArtistVote)
class AdminCardArtistVote(admin.ModelAdmin[CardArtistVote]):
    list_display = (
        "card",
        "artist",
        "is_unknown",
        "source",
        "peer",
        "confidence",
        "anonymous_id",
        "created_at",
    )
    list_filter = ("source", "is_unknown", "peer", ContestedArtistFilter)
    search_fields = ("card__name",)
    raw_id_fields = ["card", "artist"]


@admin.register(CardTagVote)
class AdminCardTagVote(admin.ModelAdmin[CardTagVote]):
    list_display = ("card", "tag", "polarity", "source", "peer", "confidence", "anonymous_id", "created_at")
    list_filter = ("source", "polarity", "peer", ContestedTagFilter)
    search_fields = ("card__name", "tag__name")
    raw_id_fields = ["card", "tag"]


@admin.register(CardReport)
class AdminCardReport(admin.ModelAdmin[CardReport]):
    list_display = ("card", "reason", "text", "anonymous_id", "user", "created_at")
    list_filter = ("reason", ("created_at", admin.DateFieldListFilter))
    search_fields = ("card__name", "card__identifier", "text")
    raw_id_fields = ["card"]


@admin.register(TagAliasSuggestion)
class AdminTagAliasSuggestion(admin.ModelAdmin[TagAliasSuggestion]):
    list_display = ("raw_text", "suggested_tag", "confidence", "occurrence_count", "status")
    list_filter = ("status",)
    search_fields = ("raw_text",)
    ordering = ("-occurrence_count",)
    actions = ["accept_suggestions", "reject_suggestions"]

    @admin.action(description="Accept selected suggestions (adds raw text as a tag alias)")
    def accept_suggestions(self, request: HttpRequest, queryset: QuerySet[TagAliasSuggestion]) -> None:
        for suggestion in queryset.select_related("suggested_tag"):
            tag = suggestion.suggested_tag
            if tag is not None and suggestion.raw_text not in tag.aliases:
                tag.aliases = [*tag.aliases, suggestion.raw_text]
                tag.save(update_fields=["aliases"])
            suggestion.status = TagSuggestionStatus.ACCEPTED
            suggestion.save(update_fields=["status"])

    @admin.action(description="Reject selected suggestions (undoes any auto-applied alias)")
    def reject_suggestions(self, request: HttpRequest, queryset: QuerySet[TagAliasSuggestion]) -> None:
        for suggestion in queryset.select_related("suggested_tag"):
            tag = suggestion.suggested_tag
            if tag is not None and suggestion.status in (
                TagSuggestionStatus.AUTO_ACCEPTED,
                TagSuggestionStatus.ACCEPTED,
            ):
                if suggestion.raw_text in tag.aliases:
                    tag.aliases = [alias for alias in tag.aliases if alias != suggestion.raw_text]
                    tag.save(update_fields=["aliases"])
            suggestion.status = TagSuggestionStatus.REJECTED
            suggestion.save(update_fields=["status"])

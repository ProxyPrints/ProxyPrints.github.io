from django.contrib import admin
from django.db.models import Case, Count, IntegerField, Q, QuerySet, When
from django.http import HttpRequest

from .models import (
    CanonicalArtist,
    CanonicalCard,
    CanonicalExpansion,
    CanonicalPrintingMetadata,
    Card,
    CardPrintingTag,
    DFCPair,
    Project,
    ProjectMember,
    Source,
    Tag,
)
from .sources.update_database import update_database


# Register your models here.
@admin.register(Tag)
class AdminTag(admin.ModelAdmin[Tag]):
    list_display = ("name",)
    search_fields = ("name",)


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
    Cheap SQL-level proxy for "this card has conflicting printing votes on record" -
    flags cards with more than one distinct printing voted for, or both a printing vote
    and a no-match vote. This is coarser than cardpicker.printing_consensus.resolve_printing
    (a card can show as contested here yet still resolve if one side dominates on weight)
    but avoids running the full consensus calculation per row for an admin triage view.
    """

    title = "contested"
    parameter_name = "contested"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin[CardPrintingTag]) -> list[tuple[str, str]]:
        return [("yes", "Yes")]

    def queryset(self, request: HttpRequest, queryset: QuerySet[CardPrintingTag]) -> QuerySet[CardPrintingTag]:
        if self.value() != "yes":
            return queryset
        contested_card_ids = (
            CardPrintingTag.objects.values("card_id")
            .annotate(
                distinct_printings=Count("printing_id", distinct=True),
                has_no_match=Count(Case(When(is_no_match=True, then=1), output_field=IntegerField())),
            )
            .filter(Q(distinct_printings__gt=1) | (Q(distinct_printings__gte=1) & Q(has_no_match__gt=0)))
            .values_list("card_id", flat=True)
        )
        return queryset.filter(card_id__in=contested_card_ids)


@admin.register(CardPrintingTag)
class AdminCardPrintingTag(admin.ModelAdmin[CardPrintingTag]):
    list_display = ("card", "printing", "is_no_match", "source", "confidence", "session_key", "created_at")
    list_filter = ("source", "is_no_match", ContestedCardFilter)
    search_fields = ("card__name",)
    raw_id_fields = ["card", "printing"]

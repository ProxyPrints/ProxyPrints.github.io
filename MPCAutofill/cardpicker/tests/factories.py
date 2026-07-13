import datetime as dt
import uuid

import factory

from cardpicker import models
from cardpicker.models import Games
from cardpicker.search.sanitisation import to_searchable


class DFCPairFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.DFCPair
        django_get_or_create = ("front",)

    front = factory.Sequence(lambda n: f"Front {n}")
    back = factory.Sequence(lambda n: f"Back {n}")


class SourceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Source

    identifier = factory.Sequence(lambda n: f"source_{n}")
    key = factory.Sequence(lambda n: f"source_{n}")
    name = factory.Sequence(lambda n: f"Source {n}")
    source_type = models.SourceTypeChoices.GOOGLE_DRIVE
    description = factory.LazyAttribute(lambda o: f"Description for {o.key}")
    ordinal = factory.Sequence(lambda n: n)
    external_link = factory.LazyAttribute(lambda o: f"https://example.com/{o.identifier}")


class CardFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Card

    card_type = models.CardTypes.CARD
    date_created = factory.LazyFunction(lambda: dt.datetime(2023, 1, 1))  # for snapshot consistency
    date_modified = factory.LazyAttribute(lambda o: o.date_created)
    identifier = factory.Sequence(lambda n: f"card_{n}")
    name = factory.Sequence(lambda n: f"Card {n}")
    priority = factory.Sequence(lambda n: n)
    source = factory.SubFactory(SourceFactory)
    source_verbose = factory.LazyAttribute(lambda o: f"{o.source.name} but verbose")
    folder_location = factory.LazyFunction(lambda: "path")
    dpi = factory.LazyFunction(lambda: 800)
    searchq = factory.LazyAttribute(lambda o: to_searchable(o.name))
    extension = factory.LazyFunction(lambda: "png")
    size = factory.LazyFunction(lambda: 100)
    language = factory.LazyAttribute(lambda o: "en")
    image_hash = 0


class TagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Tag

    name = factory.Sequence(lambda n: f"Tag {n}")
    parent = factory.LazyFunction(lambda: None)
    aliases = factory.LazyAttribute(lambda o: [o.name.replace(" ", "")])


class CanonicalArtistFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.CanonicalArtist

    name = factory.Sequence(lambda n: f"Artist {n}")


class CanonicalExpansionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.CanonicalExpansion

    identifier = factory.LazyFunction(uuid.uuid4)
    code = factory.Sequence(lambda n: f"Code {n}")
    name = factory.Sequence(lambda n: f"Canonical Expansion {n}")
    game = Games.MTG


class CanonicalCardFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.CanonicalCard

    identifier = factory.LazyFunction(uuid.uuid4)
    canonical_id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Canonical Card {n}")
    artist = factory.SubFactory(CanonicalArtistFactory)
    expansion = factory.SubFactory(CanonicalExpansionFactory)
    collector_number = factory.Sequence(lambda n: f"{n:03}")
    is_default = False
    image_hash = 0
    small_thumbnail_url = ""
    medium_thumbnail_url = ""


class CanonicalPrintingMetadataFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.CanonicalPrintingMetadata

    canonical_card = factory.SubFactory(CanonicalCardFactory)
    full_art = False
    border_color = "black"
    frame = "2015"
    frame_effects = factory.LazyFunction(list)
    promo_types = factory.LazyFunction(list)
    edhrec_rank = None
    printings_count = 1
    released_at = None
    lang = "en"


class CardPrintingTagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.CardPrintingTag

    card = factory.SubFactory(CardFactory)
    printing = factory.SubFactory(CanonicalCardFactory)
    is_no_match = False
    anonymous_id = factory.Sequence(lambda n: f"anonymous_{n}")
    source = models.VoteSource.USER
    confidence = None


class CardArtistVoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.CardArtistVote

    card = factory.SubFactory(CardFactory)
    artist = factory.SubFactory(CanonicalArtistFactory)
    is_unknown = False
    anonymous_id = factory.Sequence(lambda n: f"anonymous_{n}")
    source = models.VoteSource.USER
    confidence = None


class CardTagVoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.CardTagVote

    card = factory.SubFactory(CardFactory)
    tag = factory.SubFactory(TagFactory)
    polarity = models.VotePolarity.APPLY
    anonymous_id = factory.Sequence(lambda n: f"anonymous_{n}")
    source = models.VoteSource.USER
    confidence = None

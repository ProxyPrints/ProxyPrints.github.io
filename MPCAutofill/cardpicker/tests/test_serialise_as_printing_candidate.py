import uuid

from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalPrintingMetadataFactory,
)

# Issue #503 (WTC phase C1) - `serialise_as_printing_candidate`'s `illustrationId` field lets
# the frontend group the `identify_printing` candidate grid by shared Scryfall artwork.
# `CanonicalPrintingMetadata.illustration_id` is a nullable UUIDField (see local_illustration.py
# :137's `illustration_id__isnull=False` filter, which exists precisely because some rows lack
# one), so this exercises all three shapes that field can take relative to a `CanonicalCard`.


class TestSerialiseAsPrintingCandidateIllustrationId:
    def test_emits_str_illustration_id_when_metadata_has_one(self, db):
        card = CanonicalCardFactory()
        illustration_id = uuid.uuid4()
        CanonicalPrintingMetadataFactory(canonical_card=card, illustration_id=illustration_id)

        candidate = card.serialise_as_printing_candidate()

        assert candidate.illustrationId == str(illustration_id)

    def test_emits_none_when_metadata_sidecar_is_missing_entirely(self, db):
        # deliberately no `CanonicalPrintingMetadataFactory` row for this card at all - the
        # `getattr(self, "printing_metadata", None)` fallback in serialise_as_printing_candidate
        # covers this shape, same as the other metadata-derived fields it already handles.
        card = CanonicalCardFactory()

        candidate = card.serialise_as_printing_candidate()

        assert candidate.illustrationId is None

    def test_emits_none_when_metadata_exists_but_illustration_id_is_null(self, db):
        card = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=card, illustration_id=None)

        candidate = card.serialise_as_printing_candidate()

        assert candidate.illustrationId is None

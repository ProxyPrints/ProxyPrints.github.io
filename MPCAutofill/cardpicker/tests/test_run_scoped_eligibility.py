"""
Run-scoped eligibility, the vote archive, and the two properties that make them safe (2026-07-29).

THE DIRECTIVE THIS FILE PINS, verbatim:

    "Prior runs must not suppress work in a new run. The CURRENT run's own output must, so a
    killed run resumes rather than redoing completed batches."

and, ratified separately:

    "Keep at least one prior generation of votes, whose votes are NOT counted."

WHY THERE ARE FOUR SUBJECTS HERE AND NOT ONE. The change is only correct as a bundle, and each
piece is individually useless or actively misleading without the others:

 1. LAYER 1, eligibility (`_eligible_cards_queryset` and friends). Stops a PRIOR run's votes and
    abstentions from removing a card from a NEW run's pool, while keeping the CURRENT run's own
    output suppressing so a killed run resumes.
 2. LAYER 2, the pre-write split (`_split_new_printing_tag_votes`). Bypassing layer 1 alone buys
    NOTHING: the calculator recomputes the verdict and the split then drops it before the write,
    and because `purge_and_write_votes` scopes its purge to the rows being written, a dropped row
    purges nothing and the stale vote survives verbatim. Layer 2 is where a CHANGED answer
    actually lands.
 3. The ARCHIVE. Once layer 2 lets an overwrite happen, something has to keep the superseded
    generation. It is a separate table, not retained rows in the live one, because nine of the
    thirteen modules that read `CardPrintingTag` never consult `resolve_vote_weight` - a
    zero-weight rule would not stop a retained generation being displayed, counted, or treated as
    "already voted" by the very eligibility query this work un-suppresses.
 4. DEPENDENCY ORDER. Three of the four Stage D calculators select POSITIVELY from join-key's
    output, so "purge everything, then run them in parallel" gives three of them an EMPTY eligible
    set - a silent near-no-op that looks like it worked. `TestDependencyOrdering` reproduces that
    failure deliberately, because a passing suite that never runs the calculators out of order is
    not evidence that the order matters.
"""

import pytest

from cardpicker.local_calculate_verdicts import (
    JOIN_KEY_ANONYMOUS_ID,
    STAGE_D_FALLBACK_ANONYMOUS_ID,
    _eligible_cards_queryset,
    _fallback_eligible_cards_queryset,
    _slow_path_eligible_cards_queryset,
    run_fallback_calculator,
    run_join_key_calculator,
    run_slow_path_calculator,
)
from cardpicker.local_illustration import (
    ILLUSTRATION_ANONYMOUS_ID,
    _eligible_illustration_cards_queryset,
    run_illustration_calculator,
)
from cardpicker.models import (
    ArchivedCardPrintingTag,
    CardPrintingTag,
    CardScanLog,
    VoteSource,
    purge_stale_machine_votes,
)
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    ImageEvidenceFactory,
)
from cardpicker.vote_write import purge_and_write_votes

RUN_A = "run-a"
RUN_B = "run-b"


def _evidence(card, **overrides):
    """A CURRENT `ImageEvidence` row for `card` - same shape as `test_local_calculate_verdicts`'
    own helper, duplicated rather than imported so this file does not depend on that module's
    private test scaffolding."""
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions={"collector_line_ocr": "collector-line-ocr-v1"},
        collector_line_raw_text="",
        collector_line_set_code="",
        collector_line_collector_number="",
        legal_line_proxy_marker_detected=False,
        symbol_phash=None,
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


def _join_key_hit_card(set_code="mom", collector_number="158"):
    """A card the join-key calculator will confidently resolve, plus the printing it resolves to."""
    card = CardFactory(name="Some Card", content_phash=42)
    printing = CanonicalCardFactory(name="Some Card", expansion__code=set_code, collector_number=collector_number)
    _evidence(card, collector_line_set_code=set_code, collector_line_collector_number=collector_number)
    return card, printing


class TestPriorRunDoesNotSuppress:
    """Directive half 1. Asserted at the QUERYSET level (what is eligible) rather than only
    through a full calculator run, so a failure names the mechanism rather than an outcome."""

    def test_a_prior_run_s_vote_leaves_the_card_eligible(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card")
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id=RUN_A,
        )

        eligible = set(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID, run_id=RUN_B).values_list("pk", flat=True))

        assert card.pk in eligible

    def test_a_prior_run_s_non_rescannable_abstention_leaves_the_card_eligible(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="border-mismatch", run_id=RUN_A
        )

        eligible = set(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID, run_id=RUN_B).values_list("pk", flat=True))

        assert card.pk in eligible

    def test_an_unstamped_historical_row_never_suppresses_any_run(self, db):
        """`run_id` is nullable and a great many historical rows carry NULL - the 28,112
        deductive-backfill votes migration 0097 had to stamp are the documented case. A NULL can
        never equal a live run_id, so those rows are simply history now: they suppress nothing,
        which is the correct outcome and needed no backfill to achieve."""
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card")
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id=None,
        )

        eligible = set(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID, run_id=RUN_A).values_list("pk", flat=True))

        assert card.pk in eligible

    def test_legacy_unscoped_callers_are_unchanged(self, db):
        """`run_id=None` must remain byte-for-byte the pre-2026-07-29 behaviour - `stream_backstop_
        sweep.verify_chunk` asks "is there ANY Stage D backlog", a question about the catalogue and
        not about a run, and answering it run-scoped would report the whole catalogue as backlog."""
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card")
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id=RUN_A,
        )

        eligible = set(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID).values_list("pk", flat=True))

        assert card.pk not in eligible


class TestCurrentRunDoesSuppress:
    """Directive half 2 - resumption. A run that is killed and restarted under the SAME run_id
    must not redo batches it already committed."""

    def test_this_run_s_own_vote_removes_the_card(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card")
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id=RUN_A,
        )

        eligible = set(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID, run_id=RUN_A).values_list("pk", flat=True))

        assert card.pk not in eligible

    def test_this_run_s_own_non_rescannable_abstention_removes_the_card(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="border-mismatch", run_id=RUN_A
        )

        eligible = set(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID, run_id=RUN_A).values_list("pk", flat=True))

        assert card.pk not in eligible

    def test_a_rescannable_abstention_still_does_not_suppress_even_in_this_run(self, db):
        """Run-scoping narrows WHOSE abstentions count; it does not change which reasons are
        re-scannable. `no-evidence` stays transient in both worlds."""
        card = CardFactory(name="Some Card", content_phash=42)
        CardScanLog.objects.create(
            card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-evidence", run_id=RUN_A
        )

        eligible = set(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID, run_id=RUN_A).values_list("pk", flat=True))

        assert card.pk in eligible


class TestTheCompiledSqlTrap:
    """THE BUG THIS CHANGE ALMOST SHIPPED WITH, pinned so it cannot come back.

    The obvious spelling of a run-scoped vote exclusion is
    `.exclude(printing_tags__anonymous_id=X, printing_tags__run_id=Y)`. Django does NOT compile
    that into one subquery the same related row must satisfy - it emits two INDEPENDENT `EXISTS`
    clauses ANDed inside one `NOT`. A card carrying THIS identity's vote from an OLD run plus some
    OTHER identity's vote from THIS run then satisfies both halves and is wrongly excluded, which
    silently re-creates the cross-run suppression this work removes, in the hardest direction to
    notice: fewer cards processed, no error, no counter."""

    def test_the_scoped_exclusion_is_one_subquery_over_both_columns(self, db):
        sql = str(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID, run_id=RUN_B).query)
        vote_subqueries = [fragment for fragment in sql.split("SELECT") if "cardpicker_cardprintingtag" in fragment]
        assert len(vote_subqueries) == 1, sql
        assert JOIN_KEY_ANONYMOUS_ID in vote_subqueries[0]
        assert RUN_B in vote_subqueries[0]

    def test_another_identity_s_vote_from_this_run_does_not_exclude_the_card(self, db):
        """The behavioural form of the same assertion - this is what the two-EXISTS compilation
        got wrong, and it fails against it even though the SQL-shape test above would too."""
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card")
        # this identity, an OLD run
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id=RUN_A,
        )
        # a DIFFERENT identity, THIS run
        CardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            source=VoteSource.OCR,
            run_id=RUN_B,
        )

        eligible = set(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID, run_id=RUN_B).values_list("pk", flat=True))

        assert card.pk in eligible


class TestIllustrationRunScoping:
    """`local_illustration` carries its own duplicated copy of the eligibility shape rather than
    calling `_eligible_cards_queryset`, so run-scoping had to be applied there separately and is
    asserted separately. This calculator is also the worked example of WHY: `stage-d-illustration`
    had to be version-bumped v1 -> v2 purely to escape its own non-rescannable scan-log rows after
    a bug was fixed, stranding 3,409 wrongly-skipped cards behind an exclusion that a repair alone
    could not lift."""

    def _illustration_candidate(self):
        """A card in the join-key no-hit population, which is the pool this calculator draws from."""
        card = CardFactory(name="Some Card", content_phash=42)
        CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="ambiguous")
        return card

    def _eligible(self, run_id):
        return set(
            _eligible_illustration_cards_queryset(
                join_key_voted_card_ids=CardPrintingTag.objects.filter(
                    anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=True
                ).values_list("card_id", flat=True),
                join_key_scanned_card_ids=CardScanLog.objects.filter(
                    anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason__in=["ambiguous"]
                ).values_list("card_id", flat=True),
                run_id=run_id,
            ).values_list("pk", flat=True)
        )

    def test_a_prior_run_s_abstention_leaves_the_card_eligible(self, db):
        card = self._illustration_candidate()
        CardScanLog.objects.create(
            card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID, skip_reason="multiple-illustrations", run_id=RUN_A
        )

        assert card.pk in self._eligible(RUN_B)

    def test_this_run_s_own_abstention_removes_the_card(self, db):
        card = self._illustration_candidate()
        CardScanLog.objects.create(
            card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID, skip_reason="multiple-illustrations", run_id=RUN_A
        )

        assert card.pk not in self._eligible(RUN_A)

    def test_a_prior_run_s_vote_leaves_the_card_eligible(self, db):
        card = self._illustration_candidate()
        CardPrintingTag.objects.create(
            card=card,
            printing=CanonicalCardFactory(name="Some Card"),
            is_no_match=False,
            anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
            source=VoteSource.DEDUCTION,
            run_id=RUN_A,
        )

        assert card.pk in self._eligible(RUN_B)

    def test_this_run_s_own_vote_removes_the_card(self, db):
        card = self._illustration_candidate()
        CardPrintingTag.objects.create(
            card=card,
            printing=CanonicalCardFactory(name="Some Card"),
            is_no_match=False,
            anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
            source=VoteSource.DEDUCTION,
            run_id=RUN_A,
        )

        assert card.pk not in self._eligible(RUN_A)

    def test_the_calculator_itself_forwards_its_run_id(self, db):
        """END TO END, not just at the queryset seam. The queryset tests above stay green even if
        `run_illustration_calculator` forgets to pass `run_id=` at its single call site, which is
        precisely the mistake that would ship a no-op: every exclusion correctly implemented and
        nothing wired to it. Driven through an ABSTENTION rather than a vote, because that needs
        no illustration index and still exercises both the scan-log write and the exclusion it
        feeds."""
        card = self._illustration_candidate()
        _evidence(card, artist_ocr_name="Nobody At All")

        first = run_illustration_calculator(run_id=RUN_A, dry_run=False)
        assert first.cards_considered == 1
        assert CardScanLog.objects.filter(card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 1

        # Same run: resumed, not redone.
        resumed = run_illustration_calculator(run_id=RUN_A, dry_run=False)
        assert resumed.cards_considered == 0

        # New run: reconsidered.
        second = run_illustration_calculator(run_id=RUN_B, dry_run=False)
        assert second.cards_considered == 1

    def test_the_scoped_exclusion_is_one_subquery_over_both_columns(self, db):
        """Same compiled-SQL trap as `TestTheCompiledSqlTrap` - this module has its own copy of
        the exclusion and therefore its own copy of the way to get it wrong."""
        # Non-empty join-key populations: an empty `pk__in=[]` makes the whole query compile to
        # `EmptyResultSet` and there is no SQL to inspect at all.
        sql = str(
            _eligible_illustration_cards_queryset(
                join_key_voted_card_ids=[1], join_key_scanned_card_ids=[2], run_id=RUN_B
            ).query
        )
        vote_subqueries = [f for f in sql.split("SELECT") if "cardpicker_cardprintingtag" in f]
        assert len(vote_subqueries) == 1, sql
        assert ILLUSTRATION_ANONYMOUS_ID in vote_subqueries[0]
        assert RUN_B in vote_subqueries[0]


class TestChangedVerdictOverwritesAndArchives:
    """Layer 2 defeated, end to end through the real calculator - and the superseded generation
    landing in the archive rather than being destroyed."""

    def test_a_changed_verdict_overwrites_and_the_old_row_is_archived(self, db):
        card, printing_a = _join_key_hit_card()
        stale = CardPrintingTag.objects.create(
            card=card,
            printing=CanonicalCardFactory(name="Some Card", expansion__code="won", collector_number="1"),
            is_no_match=False,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            confidence=0.5,
            run_id=RUN_A,
        )

        result = run_join_key_calculator(run_id=RUN_B, dry_run=False)

        # The recomputed verdict reached the write: one live row, the NEW printing, this run's id.
        assert result.cards_considered == 1
        assert result.votes_written == 1
        assert result.already_voted == 0
        live = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert live.printing_id == printing_a.pk
        assert live.run_id == RUN_B

        # ...and the superseded generation is in the archive, verbatim, with the run that
        # overwrote it recorded.
        archived = ArchivedCardPrintingTag.objects.get(card=card)
        assert archived.original_id == stale.pk
        assert archived.printing_id == stale.printing_id
        assert archived.anonymous_id == JOIN_KEY_ANONYMOUS_ID
        assert archived.confidence == 0.5
        assert archived.run_id == RUN_A
        assert archived.superseded_by_run_id == RUN_B
        assert archived.created_at == stale.created_at

    def test_an_unchanged_verdict_archives_nothing(self, db):
        """The archive records changes of mind, not passes. A converged catalogue must not grow it
        on every run - that would make the retention question (issue #575) unanswerable and the
        `--generation-diff` report useless noise."""
        card, printing = _join_key_hit_card()
        run_join_key_calculator(run_id=RUN_A, dry_run=False)
        assert CardPrintingTag.objects.filter(card=card).count() == 1

        run_join_key_calculator(run_id=RUN_B, dry_run=False)

        assert ArchivedCardPrintingTag.objects.count() == 0
        assert CardPrintingTag.objects.get(card=card).run_id == RUN_A


class TestArchiveIsNotALiveVote:
    """The load-bearing property of choosing a separate table: nothing that reads printing tags
    can see an archived row, so none of the thirteen consumer modules had to be audited."""

    def test_no_reverse_accessor_exists_from_card(self, db):
        card = CardFactory(name="Some Card")
        ArchivedCardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            created_at=card.date_created,
            original_id=1,
        )

        # `related_name="+"` - the archive is unreachable from the Card side by any accessor name,
        # so no prefetch, serialiser or `filter(...__...)` traversal can pick it up.
        assert not any(
            getattr(getattr(card, attr, None), "model", None) is ArchivedCardPrintingTag
            for attr in dir(card)
            if not attr.startswith("__")
        )
        assert card.printing_tags.count() == 0

    def test_an_archived_row_does_not_make_a_card_ineligible(self, db):
        """The failure mode that ruled out keeping retained generations in the live table: they
        would still read as "already voted"."""
        card = CardFactory(name="Some Card", content_phash=42)
        ArchivedCardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
            created_at=card.date_created,
            original_id=1,
            run_id=RUN_A,
        )

        for run_id in (None, RUN_A, RUN_B):
            eligible = set(_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID, run_id=run_id).values_list("pk", flat=True))
            assert card.pk in eligible, run_id

    def test_a_human_vote_is_never_archived(self, db):
        """`purge_stale_machine_votes` returns before touching anything when `calculator_family`
        is None, which is every human voter (they use UUIDs). The archive must not become a place
        human votes can quietly end up."""
        card = CardFactory(name="Some Card")
        printing = CanonicalCardFactory(name="Some Card")
        CardPrintingTag.objects.create(
            card=card, printing=printing, is_no_match=False, anonymous_id="a-human-uuid", source=VoteSource.USER
        )

        deleted = purge_stale_machine_votes(CardPrintingTag, "a-human-uuid", "card_id", [card.pk])

        assert deleted == 0
        assert ArchivedCardPrintingTag.objects.count() == 0
        assert CardPrintingTag.objects.filter(card=card).count() == 1


class TestSupersedingRunIdStamping:
    def test_a_mixed_run_id_batch_records_no_superseding_run_rather_than_guessing(self, db):
        """A wrong run stamp is worse than a missing one: the `--generation-diff` report and issue
        #575's janitor both select on it, and a plausible wrong value is indistinguishable from a
        right one after the fact. See `vote_write._superseding_run_id`."""
        card_a = CardFactory(name="Card A")
        card_b = CardFactory(name="Card B")
        printing = CanonicalCardFactory(name="Card A")
        for card in (card_a, card_b):
            CardPrintingTag.objects.create(
                card=card,
                printing=printing,
                is_no_match=False,
                anonymous_id=JOIN_KEY_ANONYMOUS_ID,
                source=VoteSource.OCR,
                run_id=RUN_A,
            )

        purge_and_write_votes(
            CardPrintingTag,
            [
                CardPrintingTag(
                    card_id=card_a.pk,
                    printing_id=None,
                    is_no_match=True,
                    anonymous_id=JOIN_KEY_ANONYMOUS_ID,
                    source=VoteSource.OCR,
                    run_id=RUN_B,
                ),
                CardPrintingTag(
                    card_id=card_b.pk,
                    printing_id=None,
                    is_no_match=True,
                    anonymous_id=JOIN_KEY_ANONYMOUS_ID,
                    source=VoteSource.OCR,
                    run_id="a-third-run",
                ),
            ],
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
        )

        assert ArchivedCardPrintingTag.objects.count() == 2
        assert set(ArchivedCardPrintingTag.objects.values_list("superseded_by_run_id", flat=True)) == {None}


class TestDependencyOrdering:
    """ORDER IS A CORRECTNESS CONSTRAINT, NOT A PERFORMANCE ONE.

    `fallback`, `illustration` and `slow-path` all select POSITIVELY from join-key's output - they
    consume the cards join-key routed to no-hit. So "purge everything, then run the calculators in
    parallel" leaves three of the four with an EMPTY eligible set: a silent near-no-op that reports
    success. These tests construct that failure on purpose, because a suite that only ever runs
    them in the right order is not evidence that the order matters."""

    def _no_hit_card(self):
        """A card whose join-key pass produces a no-hit outcome fallback and slow-path can consume,
        with the border evidence fallback needs to resolve it."""
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black")
        _evidence(card, collector_line_raw_text="garbled", layout_class="black")
        return card, printing

    def test_fallback_before_join_key_sees_an_empty_pool(self, db):
        card, _printing = self._no_hit_card()

        # OUT OF ORDER: fallback first, against a catalogue join-key has not run over.
        early = run_fallback_calculator(run_id=RUN_A, dry_run=False)

        assert early.cards_considered == 0
        assert early.votes_written == 0
        assert CardPrintingTag.objects.filter(anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).count() == 0
        assert set(_fallback_eligible_cards_queryset(run_id=RUN_A).values_list("pk", flat=True)) == set()

        # IN ORDER: join-key first, then fallback - the same call now has work to do.
        run_join_key_calculator(run_id=RUN_A, dry_run=False)
        assert card.pk in set(_fallback_eligible_cards_queryset(run_id=RUN_A).values_list("pk", flat=True))
        ordered = run_fallback_calculator(run_id=RUN_A, dry_run=False)
        assert ordered.cards_considered == 1
        assert ordered.votes_written == 1

    def test_slow_path_before_join_key_sees_an_empty_pool(self, db):
        self._no_hit_card()

        early = run_slow_path_calculator(run_id=RUN_A, dry_run=False)

        assert early.cards_considered == 0
        assert early.routed_written == 0
        assert set(_slow_path_eligible_cards_queryset(run_id=RUN_A).values_list("pk", flat=True)) == set()

    def test_slow_path_before_fallback_routes_a_card_fallback_would_have_solved(self, db):
        """The other ordering failure, and the one that is not merely a no-op: run slow-path before
        fallback and a card fallback resolves moments later has already been sent to a human. This
        is why `_slow_path_eligible_cards_queryset` excludes fallback-voted cards AND why that
        exclusion must stay UNSCOPED by run - a run-scoped version would be empty on a converged
        catalogue and the guarantee would evaporate."""
        card, _printing = self._no_hit_card()
        run_join_key_calculator(run_id=RUN_A, dry_run=False)

        # OUT OF ORDER: slow-path before fallback.
        run_slow_path_calculator(run_id=RUN_A, dry_run=False)
        assert CardScanLog.objects.filter(card=card, anonymous_id="stage-d-slow-path-v1").exists()

        # Fallback then resolves the card the reviewer was just handed.
        fallback = run_fallback_calculator(run_id=RUN_A, dry_run=False)
        assert fallback.votes_written == 1

    def test_in_order_slow_path_leaves_a_fallback_solved_card_alone(self, db):
        card, _printing = self._no_hit_card()
        run_join_key_calculator(run_id=RUN_A, dry_run=False)
        run_fallback_calculator(run_id=RUN_A, dry_run=False)

        result = run_slow_path_calculator(run_id=RUN_A, dry_run=False)

        assert result.cards_considered == 0
        assert not CardScanLog.objects.filter(card=card, anonymous_id="stage-d-slow-path-v1").exists()

    def test_the_fallback_exclusion_survives_a_new_run(self, db):
        """A card fallback solved in run A must still not be routed to review by slow-path in run
        B. If the fallback exclusion were run-scoped it would be empty here and the card would be
        wrongly routed - undoing a solved card, which is worse than the empty-pool no-op."""
        card, _printing = self._no_hit_card()
        run_join_key_calculator(run_id=RUN_A, dry_run=False)
        run_fallback_calculator(run_id=RUN_A, dry_run=False)

        result = run_slow_path_calculator(run_id=RUN_B, dry_run=False)

        assert result.cards_considered == 0
        assert not CardScanLog.objects.filter(card=card, anonymous_id="stage-d-slow-path-v1").exists()


class TestIdempotenceConverges:
    """Two identical from-scratch passes must CONVERGE, not oscillate. This is the property most
    at risk from run-scoping: once prior runs stop suppressing, every pass reconsiders every card,
    and only the value-comparing split stops that becoming an overwrite-everything churn machine."""

    @pytest.mark.parametrize("passes", [2, 3])
    def test_repeated_full_passes_converge(self, db, passes):
        card, printing = _join_key_hit_card()

        for index in range(passes):
            run_join_key_calculator(run_id=f"pass-{index}", dry_run=False)

        votes = list(CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID))
        assert len(votes) == 1
        assert votes[0].printing_id == printing.pk
        # Written by the FIRST pass and never touched again - not rewritten under each new run_id,
        # which is what "converge, not oscillate" means at the row level.
        assert votes[0].run_id == "pass-0"
        assert ArchivedCardPrintingTag.objects.count() == 0

    def test_the_full_four_calculator_sequence_converges(self, db):
        """The whole Stage D sequence in its required order, twice. Second pass writes nothing new
        and archives nothing; the only growth is slow-path's append-only abstention trail, which
        `CardScanLog`'s own model docstring already declares normal and issue #575's janitor
        bounds."""
        card, _printing = TestDependencyOrdering()._no_hit_card()

        def one_pass(run_id):
            run_join_key_calculator(run_id=run_id, dry_run=False)
            run_fallback_calculator(run_id=run_id, dry_run=False)
            run_slow_path_calculator(run_id=run_id, dry_run=False)

        one_pass("pass-0")
        first_state = sorted(
            CardPrintingTag.objects.values_list("card_id", "anonymous_id", "printing_id", "is_no_match", "run_id")
        )

        one_pass("pass-1")
        second_state = sorted(
            CardPrintingTag.objects.values_list("card_id", "anonymous_id", "printing_id", "is_no_match", "run_id")
        )

        assert second_state == first_state
        assert ArchivedCardPrintingTag.objects.count() == 0

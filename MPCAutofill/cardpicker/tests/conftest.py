import datetime as dt
import os
import uuid
from typing import Type

import pytest
from pytest_elasticsearch import factories
from testcontainers.elasticsearch import ElasticSearchContainer
from testcontainers.postgres import PostgresContainer

from django.conf import settings as conf_settings
from django.contrib.auth.models import Group, User
from django.core.management import call_command

from cardpicker.integrations.game.base import GameIntegration
from cardpicker.models import Card, CardTypes, DFCPair, Source, Tag
from cardpicker.tests.constants import Cards, DummyIntegration, Sources
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
    DFCPairFactory,
    SourceFactory,
    TagFactory,
)

# Host ports the session-scoped testcontainers bind to. Overridable from the environment so that
# two suites can run CONCURRENTLY on one host (2026-07-28: several agents share this box; a second
# run against the same fixed ports dies at container start with "port is already allocated", which
# surfaces as mass collection errors that look like catastrophic breakage rather than a port
# clash). The defaults are the historical fixed values, so CI and a single local run are unchanged.
#
#   TEST_POSTGRES_PORT=47001 TEST_ELASTICSEARCH_PORT=9301 pytest ...
#
# NOTE both must be moved together with the same offset if you want two full suites side by side -
# the two containers are independent, so a collision on either one fails the whole session.
POSTGRES_PORT = int(os.environ.get("TEST_POSTGRES_PORT", 47000))
ELASTICSEARCH_PORT = int(os.environ.get("TEST_ELASTICSEARCH_PORT", 9300))  # `elasticsearch_nooproc`'s own default


def pytest_configure(config):
    """
    Thread `ELASTICSEARCH_PORT` through to pytest-elasticsearch's own config, which is where
    `elasticsearch_nooproc` reads its port from (`pytest_elasticsearch.config.get_config` ->
    `config.getoption("elasticsearch_port") or config.getini("elasticsearch_port")`, falling back
    to a hardcoded 9300 - the "default expected by `elasticsearch_nooproc`" the constant above used
    to silently rely on). Nothing in this suite currently RESOLVES that fixture (the `elasticsearch`
    fixture below shadows the plugin's and never requests the noproc process), so this is belt-and-
    braces: without it, overriding `TEST_ELASTICSEARCH_PORT` would leave a latent 9300 behind for
    any future test that does request `elasticsearch_nooproc`. Setting it to 9300 when the
    environment variable is unset is a no-op against the plugin's own fallback.
    """
    if hasattr(config.option, "elasticsearch_port") and not config.option.elasticsearch_port:
        config.option.elasticsearch_port = str(ELASTICSEARCH_PORT)


# The host load average every test sees, unless it opts out with `@pytest.mark.real_host_load`.
# Deliberately well under `operating_envelope.HOST_LOAD_CEILING` (7.0, a RATIFIED number - not
# changed here, and not to be changed to accommodate tests).
#
# Why this exists (2026-07-28): `stage_e_dispatch._sample_envelope_signals` samples the REAL
# `os.getloadavg()[0]` before every dispatch decision, exactly as it should in production. Under
# test that made every Stage E dispatch test a function of whatever ELSE was running on the box -
# on a shared machine at load 8.67 an observed 18 tests failed with `halted-new-trip`, all of which
# pass at load 3.4. Those failures are the worst kind: plausible, specific, and entirely about the
# neighbouring process, so they burn hours pointing at an envelope bug that does not exist.
#
# The seam is `os.getloadavg` itself rather than `_sample_envelope_signals`, deliberately: stubbing
# the whole sampler would also flatten `_window.failures_and_total()` and `get_process_rss_mb()`,
# which several dispatch tests legitimately drive (the fetch-failure-rate bar in particular). Only
# the ambient host signal is pinned; every other envelope input still comes from the real code
# path, and production sampling is untouched.
#
# Override with TEST_HOST_LOAD_AVG to prove a test is genuinely load-sensitive:
#   TEST_HOST_LOAD_AVG=20 pytest cardpicker/tests/test_stage_e_dispatch.py   # -> load-bar trips
TEST_HOST_LOAD_AVG = float(os.environ.get("TEST_HOST_LOAD_AVG", 0.5))


@pytest.fixture(autouse=True)
def deterministic_host_load(request, monkeypatch):
    """
    Pins `os.getloadavg()` for the duration of every test, so no assertion depends on ambient host
    load. Opt out with `@pytest.mark.real_host_load` if a test genuinely needs to observe the real
    machine (nothing does today - `test_process_metrics.py` samples real RSS, not load).
    """
    if "real_host_load" in request.keywords:
        return
    monkeypatch.setattr(
        os,
        "getloadavg",
        lambda: (TEST_HOST_LOAD_AVG, TEST_HOST_LOAD_AVG, TEST_HOST_LOAD_AVG),
        raising=False,
    )


# The per-worker RSS every test sees, unless it opts out with `@pytest.mark.real_process_rss`.
# Deliberately well under `operating_envelope.RSS_MB_PER_WORKER_CEILING` (768.0, a RATIFIED number
# - not changed here, and not to be changed to accommodate tests).
#
# Why this exists (2026-07-29): the envelope has ONE gate with TWO ambient sensors. The load one was
# pinned above; this is the other. `stage_e_dispatch._sample_envelope_signals` reads this process's
# REAL resident set size before every dispatch decision, exactly as it should in production, which
# left every Stage E dispatch test a function of how much memory the pytest process happened to be
# holding (38 tests are RSS-sensitive as of this commit: 25 in test_stage_e_dispatch, 6 in
# test_stage_e_shakedown, 7 in test_stream_full_catalog - the same split as the load-sensitive set,
# because it is one gate with two sensors. Re-measure with the override below rather than trusting
# that count; it was 37 a few PRs ago and #545 added one). The
# measured margin is comfortable today (the suite peaks around 348MB VmHWM against the 768MB bar,
# ~2.2x) but it is a margin, not a guarantee: it moves with fixture growth, with a bigger
# testcontainers footprint, and with whatever else the three agents commonly sharing this box are
# doing. An RSS-driven failure looks exactly like an envelope bug and costs the same hours the load
# flakes did.
#
# Override with TEST_PROCESS_RSS_MB to prove a test is genuinely RSS-sensitive:
#   TEST_PROCESS_RSS_MB=900 pytest cardpicker/tests/test_stage_e_dispatch.py   # -> RSS-bar trips
TEST_PROCESS_RSS_MB = float(os.environ.get("TEST_PROCESS_RSS_MB", 128.0))


@pytest.fixture(autouse=True)
def deterministic_process_rss(request, monkeypatch):
    """
    Pins the per-worker RSS the ENVELOPE samples, so no assertion depends on this process's ambient
    memory. Opt out with `@pytest.mark.real_process_rss`.

    THE SEAM IS `stage_e_dispatch.get_process_rss_mb`, NOT `process_metrics.get_process_rss_mb`,
    and the difference is the whole change: `deterministic_host_load` above can patch `os.getloadavg`
    because `stage_e_dispatch` does `import os` and resolves the attribute at CALL time, whereas
    `stage_e_dispatch.py` does `from cardpicker.process_metrics import get_process_rss_mb`, binding
    the function object into its own namespace at IMPORT time. Patching `process_metrics` afterwards
    would rebind a name nobody reads and this fixture would silently do nothing - which is why
    `test_harness_isolation.py` asserts the value the PRODUCTION sampler returns rather than merely
    that the fixture ran, and separately proves the `process_metrics`-side patch does NOT bite.
    That one module-local name covers both consumers: the envelope sample in
    `_sample_envelope_signals` and the ledger's `peak_rss_mb`.

    `stage_e_dispatch` is the only production importer of the helper, so nothing else is affected.
    `test_process_metrics.py` imports from `process_metrics` directly and never reaches
    `stage_e_dispatch`, so its real-RSS coverage keeps sampling /proc for real with no opt-out
    needed - the primitive itself stays honestly tested. (`run_image_evidence_cohort._get_rss_mb` is
    a separate, deliberately duplicated implementation with its own tests; untouched.)
    """
    if "real_process_rss" in request.keywords:
        return
    # String target so importing `stage_e_dispatch` stays lazy, and `raising=True` (the default) so
    # this fails LOUDLY if that module-local name is ever renamed or removed rather than degrading
    # back into ambient sampling.
    monkeypatch.setattr(
        "cardpicker.stage_e_dispatch.get_process_rss_mb",
        lambda: TEST_PROCESS_RSS_MB,
    )


def google_drive_credentials_available() -> bool:
    """
    CI baseline cleanup, 2026-07-19: a real capability probe (mirrors the
    `shutil.which("tesseract") is None` pattern already used for the OCR skip below) for the
    two independent things known to break a real Google Drive call in this codebase (see
    docs/troubleshooting.md) - a missing/invalid `client_secrets.json` (CI, no
    GOOGLE_DRIVE_API_KEY repo secret configured -> `jsdaniell/create-json` writes an empty
    file -> `json.decoder.JSONDecodeError` at credential-parse time) and a pyOpenSSL version
    without `OpenSSL.crypto.sign` (local dev venvs, a drifted transitive dependency -> that
    specific `AttributeError` only surfaces on the FIRST REAL API CALL's JWT signing, not at
    credential-parse time, which is why the two environments fail with different exception
    types for the same root problem: "no working real Google Drive credentials here").

    No network call is made - the OpenSSL check catches the local case directly, and credential
    *parsing* (not signing) already fails before any request would be sent in the CI case.
    pyOpenSSL itself may not even be installed in a given environment (confirmed in this fork's
    CI - it's only pulled in transitively by whatever locally resolves oauth2client's optional
    signing backend, and CI's failure happens at JSON-parse time, before OpenSSL would ever be
    imported for real) - that is itself a valid "credentials unavailable" state, not an error.
    """
    try:
        import OpenSSL.crypto

        if not hasattr(OpenSSL.crypto, "sign"):
            return False
    except ImportError:
        return False
    try:
        from cardpicker.sources.api import find_or_create_google_drive_service

        find_or_create_google_drive_service()
    except Exception:
        return False
    return True


@pytest.fixture(scope="session")
def postgres_container():
    postgres = PostgresContainer("postgres:16.0-alpine").with_bind_ports(5432, POSTGRES_PORT)
    postgres.start()
    yield postgres
    postgres.stop()


@pytest.fixture(scope="session")
def elasticsearch_container():
    elasticsearch = ElasticSearchContainer("elasticsearch:7.17.23", mem_limit="1G").with_bind_ports(
        9200, ELASTICSEARCH_PORT
    )
    elasticsearch.start()
    yield elasticsearch
    elasticsearch.stop()


@pytest.fixture(scope="session")
def django_db_modify_db_settings(postgres_container):
    # customise settings to point to testcontainers db
    conf_settings.DATABASES["default"]["HOST"] = postgres_container.get_container_host_ip()
    conf_settings.DATABASES["default"]["PORT"] = POSTGRES_PORT
    conf_settings.DATABASES["default"]["NAME"] = postgres_container.dbname
    conf_settings.DATABASES["default"]["USER"] = postgres_container.username
    conf_settings.DATABASES["default"]["PASSWORD"] = postgres_container.password


@pytest.fixture()
def django_settings(db, settings):
    settings.DEBUG = True
    settings.DEFAULT_CARDBACK_FOLDER_PATH = "MPC Autofill Sample 1 / Cardbacks"
    settings.DEFAULT_CARDBACK_IMAGE_NAME = Cards.SIMPLE_CUBE.value.name
    settings.TIME_ZONE = "UTC"


@pytest.fixture()
def integration_setter(settings, monkeypatch):
    # this uses a neat lil trick i picked up at work for creating "parametrised fixtures"
    def _setter(integration: Type[GameIntegration]) -> Type[GameIntegration]:
        settings.GAME = integration.__class__.__name__
        monkeypatch.setattr("cardpicker.views.get_configured_game_integration", lambda: integration)
        monkeypatch.setattr("cardpicker.dfc_pairs.get_configured_game_integration", lambda: integration)
        return integration

    return _setter


@pytest.fixture()
def dummy_integration(integration_setter) -> Type[GameIntegration]:
    return integration_setter(DummyIntegration)


@pytest.fixture(scope="session", autouse=True)
def elasticsearch(elasticsearch_container):
    conf_settings.ELASTICSEARCH_DSL["default"][
        "hosts"
    ] = f"{elasticsearch_container.get_container_host_ip()}:{ELASTICSEARCH_PORT}"
    conf_settings.ELASTICSEARCH_PORT = ELASTICSEARCH_PORT
    return factories.elasticsearch("elasticsearch_nooproc")


# region Source fixtures


@pytest.fixture()
def example_drive_1(db) -> Source:
    return SourceFactory(
        pk=Sources.EXAMPLE_DRIVE_1.value.pk,
        key=Sources.EXAMPLE_DRIVE_1.value.key,
        name=Sources.EXAMPLE_DRIVE_1.value.name,
        identifier=Sources.EXAMPLE_DRIVE_1.value.identifier,
        source_type=Sources.EXAMPLE_DRIVE_1.value.source_type,
        external_link=f"https://drive.google.com/open?id={Sources.EXAMPLE_DRIVE_1.value.identifier}",
    )


@pytest.fixture()
def example_drive_2(db) -> Source:
    return SourceFactory(
        pk=Sources.EXAMPLE_DRIVE_2.value.pk,
        key=Sources.EXAMPLE_DRIVE_2.value.key,
        name=Sources.EXAMPLE_DRIVE_2.value.name,
        identifier=Sources.EXAMPLE_DRIVE_2.value.identifier,
        source_type=Sources.EXAMPLE_DRIVE_2.value.source_type,
    )


@pytest.fixture()
def all_sources(example_drive_1, example_drive_2):
    pass


# endregion

# region Card fixtures


@pytest.fixture()
def ice_expansion(db):
    return CanonicalExpansionFactory(
        identifier=uuid.UUID("a4a0db50-8826-4e73-833c-3fd934375f96"), code="ice", name="Ice Age"
    )


@pytest.fixture()
def brainstorm_canonical_card(ice_expansion):
    return CanonicalCardFactory(
        identifier=uuid.UUID("8d42d7aa-7f53-4cfc-842a-086aab2448d1"),
        canonical_id=uuid.UUID("36cd2364-d113-47d1-b2c4-b088d9eb88dd"),
        expansion=ice_expansion,
        collector_number="61",
    )


@pytest.fixture()
def brainstorm(example_drive_1, brainstorm_canonical_card) -> Card:
    return CardFactory(
        pk=0,
        card_type=CardTypes.CARD,
        identifier=Cards.BRAINSTORM.value.identifier,
        name=Cards.BRAINSTORM.value.name,
        dpi=Cards.BRAINSTORM.value.dpi,
        source=example_drive_1,
        priority=2,
        size=Cards.BRAINSTORM.value.size,
        date_created=dt.datetime(2023, 1, 1),
        canonical_card=brainstorm_canonical_card,
    )


@pytest.fixture()
def island(example_drive_1) -> Card:
    return CardFactory(
        pk=Cards.ISLAND.value.pk,
        card_type=CardTypes.CARD,
        identifier=Cards.ISLAND.value.identifier,
        name=Cards.ISLAND.value.name,
        dpi=Cards.ISLAND.value.dpi,
        source=example_drive_1,
        priority=7,
        size=Cards.ISLAND.value.size,
        date_created=dt.datetime(2023, 1, 1),
    )


@pytest.fixture()
def island_classical(example_drive_1) -> Card:
    return CardFactory(
        pk=Cards.ISLAND_CLASSICAL.value.pk,
        card_type=CardTypes.CARD,
        identifier=Cards.ISLAND_CLASSICAL.value.identifier,
        name=Cards.ISLAND_CLASSICAL.value.name,
        dpi=Cards.ISLAND_CLASSICAL.value.dpi,
        source=example_drive_1,
        priority=6,
        size=Cards.ISLAND_CLASSICAL.value.size,
        date_created=dt.datetime(2023, 1, 1),
        language="FR",
    )


@pytest.fixture()
def mountain(example_drive_1) -> Card:
    return CardFactory(
        pk=Cards.MOUNTAIN.value.pk,
        card_type=CardTypes.CARD,
        identifier=Cards.MOUNTAIN.value.identifier,
        name=Cards.MOUNTAIN.value.name,
        dpi=Cards.MOUNTAIN.value.dpi,
        source=example_drive_1,
        priority=7,
        size=Cards.MOUNTAIN.value.size,
        date_created=dt.datetime(2023, 1, 1),
    )


@pytest.fixture()
def simple_cube(example_drive_1, tag_in_data, another_tag_in_data) -> Card:
    return CardFactory(
        pk=Cards.SIMPLE_CUBE.value.pk,
        card_type=CardTypes.CARDBACK,
        identifier=Cards.SIMPLE_CUBE.value.identifier,
        name=Cards.SIMPLE_CUBE.value.name,
        dpi=Cards.SIMPLE_CUBE.value.dpi,
        source=example_drive_1,
        priority=17,
        size=Cards.SIMPLE_CUBE.value.size,
        date_created=dt.datetime(2023, 1, 1),
        tags=[tag_in_data.name, another_tag_in_data.name],
        language="DE",
    )


@pytest.fixture()
def simple_lotus(example_drive_2, tag_in_data) -> Card:
    return CardFactory(
        pk=Cards.SIMPLE_LOTUS.value.pk,
        card_type=CardTypes.CARDBACK,
        identifier=Cards.SIMPLE_LOTUS.value.identifier,
        name=Cards.SIMPLE_LOTUS.value.name,
        dpi=Cards.SIMPLE_LOTUS.value.dpi,
        source=example_drive_2,
        priority=7,
        size=Cards.SIMPLE_LOTUS.value.size,
        date_created=dt.datetime(2023, 1, 1),
        tags=[tag_in_data.name],
        language="EN",
    )


@pytest.fixture()
def huntmaster_of_the_fells(example_drive_1) -> Card:
    return CardFactory(
        pk=Cards.HUNTMASTER_OF_THE_FELLS.value.pk,
        card_type=CardTypes.CARD,
        identifier=Cards.HUNTMASTER_OF_THE_FELLS.value.identifier,
        name=Cards.HUNTMASTER_OF_THE_FELLS.value.name,
        dpi=Cards.HUNTMASTER_OF_THE_FELLS.value.dpi,
        source=example_drive_1,
        priority=2,
        size=Cards.HUNTMASTER_OF_THE_FELLS.value.size,
        date_created=dt.datetime(2023, 1, 1),
    )


@pytest.fixture()
def ravager_of_the_fells(example_drive_1) -> Card:
    return CardFactory(
        pk=Cards.RAVAGER_OF_THE_FELLS.value.pk,
        card_type=CardTypes.CARD,
        identifier=Cards.RAVAGER_OF_THE_FELLS.value.identifier,
        name=Cards.RAVAGER_OF_THE_FELLS.value.name,
        dpi=Cards.RAVAGER_OF_THE_FELLS.value.dpi,
        source=example_drive_1,
        priority=2,
        size=Cards.RAVAGER_OF_THE_FELLS.value.size,
        date_created=dt.datetime(2023, 1, 1),
    )


@pytest.fixture()
def past_in_flames_1(example_drive_1, tag_in_data) -> Card:
    return CardFactory(
        pk=Cards.PAST_IN_FLAMES_1.value.pk,
        card_type=CardTypes.CARD,
        identifier=Cards.PAST_IN_FLAMES_1.value.identifier,
        name=Cards.PAST_IN_FLAMES_1.value.name,
        dpi=Cards.PAST_IN_FLAMES_1.value.dpi,
        source=example_drive_1,
        priority=2,
        size=Cards.PAST_IN_FLAMES_1.value.size,
        date_created=dt.datetime(2023, 1, 1),
        tags=[tag_in_data.name],
        language="EN",
    )


@pytest.fixture()
def past_in_flames_2(example_drive_2, tag_in_data, another_tag_in_data) -> Card:
    return CardFactory(
        pk=Cards.PAST_IN_FLAMES_2.value.pk,
        card_type=CardTypes.CARD,
        identifier=Cards.PAST_IN_FLAMES_2.value.identifier,
        name=Cards.PAST_IN_FLAMES_2.value.name,
        dpi=Cards.PAST_IN_FLAMES_2.value.dpi,
        source=example_drive_2,
        priority=2,
        size=Cards.PAST_IN_FLAMES_2.value.size,
        date_created=dt.datetime(2023, 1, 1),
        tags=[tag_in_data.name, another_tag_in_data.name],
        language="DE",
    )


@pytest.fixture()
def delver_of_secrets(example_drive_1) -> Card:
    return CardFactory(
        pk=Cards.DELVER_OF_SECRETS.value.pk,
        card_type=CardTypes.CARD,
        identifier=Cards.DELVER_OF_SECRETS.value.identifier,
        name=Cards.DELVER_OF_SECRETS.value.name,
        dpi=Cards.DELVER_OF_SECRETS.value.dpi,
        source=example_drive_1,
        priority=2,
        size=Cards.DELVER_OF_SECRETS.value.size,
        date_created=dt.datetime(2023, 1, 1),
    )


@pytest.fixture()
def insectile_aberration(example_drive_1) -> Card:
    return CardFactory(
        pk=Cards.INSECTILE_ABERRATION.value.pk,
        card_type=CardTypes.CARD,
        identifier=Cards.INSECTILE_ABERRATION.value.identifier,
        name=Cards.INSECTILE_ABERRATION.value.name,
        dpi=Cards.INSECTILE_ABERRATION.value.dpi,
        source=example_drive_1,
        priority=2,
        size=Cards.INSECTILE_ABERRATION.value.size,
        date_created=dt.datetime(2023, 1, 1),
    )


@pytest.fixture()
def goblin(example_drive_1) -> Card:
    return CardFactory(
        pk=Cards.GOBLIN.value.pk,
        card_type=CardTypes.TOKEN,
        identifier=Cards.GOBLIN.value.identifier,
        name=Cards.GOBLIN.value.name,
        dpi=Cards.GOBLIN.value.dpi,
        source=example_drive_1,
        priority=2,
        size=Cards.GOBLIN.value.size,
        date_created=dt.datetime(2023, 1, 1),
    )


@pytest.fixture()
def all_cards(
    brainstorm,
    island,
    island_classical,
    mountain,
    simple_cube,
    simple_lotus,
    huntmaster_of_the_fells,
    ravager_of_the_fells,
    past_in_flames_1,
    past_in_flames_2,
    delver_of_secrets,
    insectile_aberration,
    goblin,
) -> None:
    pass


# endregion

# region DFCPair fixtures


@pytest.fixture()
def dfc_pairs(db) -> list[DFCPair]:
    return [
        DFCPairFactory(
            pk=0, front=Cards.HUNTMASTER_OF_THE_FELLS.value.name, back=Cards.RAVAGER_OF_THE_FELLS.value.name
        ),
        DFCPairFactory(pk=1, front=Cards.DELVER_OF_SECRETS.value.name, back=Cards.INSECTILE_ABERRATION.value.name),
    ]


# endregion


# region tag fixtures


@pytest.fixture()
def tag_in_data(db) -> Tag:
    return TagFactory(name="Tag in Data")


@pytest.fixture()
def extended_tag(db) -> Tag:
    return TagFactory(name="Extended")


@pytest.fixture()
def full_art_tag(db) -> Tag:
    return TagFactory(name="Full Art")


@pytest.fixture()
def child_tag(db, tag_in_data) -> Tag:
    return TagFactory(name="Child Tag", parent=tag_in_data)


@pytest.fixture()
def grandchild_tag(db, child_tag) -> Tag:
    return TagFactory(name="Grandchild Tag", parent=child_tag)


@pytest.fixture()
def another_tag_in_data(db) -> Tag:
    return TagFactory(name="Another Tag in Data")


# endregion

# region auth/moderation fixtures


@pytest.fixture()
def moderators_group(db) -> Group:
    return Group.objects.create(name=conf_settings.MODERATORS_GROUP_NAME)


@pytest.fixture()
def moderator_user(db, moderators_group) -> User:
    user = User.objects.create_user(username="mod", password="password")
    user.groups.add(moderators_group)
    return user


@pytest.fixture()
def plain_user(db) -> User:
    return User.objects.create_user(username="pleb", password="password")


# endregion


@pytest.fixture(scope="function")  # must be function scoped because the `db` fixture is fn-scoped
def populated_database(django_settings, elasticsearch, all_sources, all_cards):
    call_command("search_index", "--rebuild", "-f")

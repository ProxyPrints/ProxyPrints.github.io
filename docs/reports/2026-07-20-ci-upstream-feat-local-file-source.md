```
TASK: Upstream branch verification (automated) — upstream-feat-local-file-source
Ref checked: upstream-feat-local-file-source @ 93874645890d4067bbed48dca232534940e11eb3
Trigger: schedule, run 29732866324

WHAT RAN:
1. pre-commit run --all-files (upstream's pinned hook versions) — exit 1
2. pytest . in MPCAutofill/ (upstream's test-backend recipe) — exit 1

PRE-COMMIT OUTPUT (tail):
```
 stderr)
                              ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repodz8iwfct/py_env-python3.13/lib/python3.13/site-packages/mypy/main.py", line 178, in run_build
    res = build.build(sources, options, None, flush_errors, fscache, stdout, stderr)
  File "/home/runner/.cache/pre-commit/repodz8iwfct/py_env-python3.13/lib/python3.13/site-packages/mypy/build.py", line 189, in build
    result = _build(
        sources, options, alt_lib_path, flush_errors, fscache, stdout, stderr, extra_plugins
    )
  File "/home/runner/.cache/pre-commit/repodz8iwfct/py_env-python3.13/lib/python3.13/site-packages/mypy/build.py", line 234, in _build
    plugin, snapshot = load_plugins(options, errors, stdout, extra_plugins)
                       ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repodz8iwfct/py_env-python3.13/lib/python3.13/site-packages/mypy/build.py", line 498, in load_plugins
    custom_plugins, snapshot = load_plugins_from_config(options, errors, stdout)
                               ~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repodz8iwfct/py_env-python3.13/lib/python3.13/site-packages/mypy/build.py", line 479, in load_plugins_from_config
    custom_plugins.append(plugin_type(options))
                          ~~~~~~~~~~~^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repodz8iwfct/py_env-python3.13/lib/python3.13/site-packages/mypy_django_plugin/main.py", line 64, in __init__
    self.django_context = DjangoContext(self.plugin_config.django_settings_module)
                          ~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repodz8iwfct/py_env-python3.13/lib/python3.13/site-packages/mypy_django_plugin/django/context.py", line 98, in __init__
    apps, settings = initialize_django(self.django_settings_module)
                     ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repodz8iwfct/py_env-python3.13/lib/python3.13/site-packages/mypy_django_plugin/django/context.py", line 82, in initialize_django
    apps.populate(settings.INSTALLED_APPS)
    ~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repodz8iwfct/py_env-python3.13/lib/python3.13/site-packages/django/apps/registry.py", line 116, in populate
    app_config.import_models()
    ~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/home/runner/.cache/pre-commit/repodz8iwfct/py_env-python3.13/lib/python3.13/site-packages/django/apps/config.py", line 269, in import_models
    self.models_module = import_module(models_module_name)
                         ~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/importlib/__init__.py", line 88, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 1395, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1331, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 935, in _load_unlocked
  File "<frozen importlib._bootstrap_external>", line 1023, in exec_module
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "/home/runner/work/ProxyPrints.github.io/ProxyPrints.github.io/MPCAutofill/cardpicker/models.py", line 21, in <module>
    from cardpicker.sources.source_types import SourceTypeChoices
  File "/home/runner/work/ProxyPrints.github.io/ProxyPrints.github.io/MPCAutofill/cardpicker/sources/source_types.py", line 9, in <module>
    from PIL import Image as PILImage
ModuleNotFoundError: No module named 'PIL'

prettier.................................................................Passed
eslint...................................................................Passed
```

BACKEND TEST OUTPUT (tail):
```
warnings.warn(

cardpicker/tests/test_dfc_pairs.py::TestSyncDFCs::test_comprehensive_snapshot
  /opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/site-packages/django/db/models/fields/__init__.py:1595: RuntimeWarning: DateTimeField Card.date_modified received a naive datetime (2026-07-20 05:53:02.202482) while time zone support is active.
    warnings.warn(

cardpicker/tests/test_integrations.py::TestMTGIntegration::test_import_canonical_cards_and_artists[card with an expansion code not in db is skipped]
cardpicker/tests/test_local_file_source.py::TestGetLocalFileImageView::test_identifier_outside_current_root_is_not_found
  /opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/site-packages/sentry_sdk/integrations/logging.py:285: DeprecationWarning: datetime.datetime.utcfromtimestamp() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.fromtimestamp(timestamp, datetime.UTC).
    "timestamp": datetime.datetime.utcfromtimestamp(record.created),

cardpicker/tests/test_local_file_source.py: 2 warnings
cardpicker/tests/test_sources.py: 8 warnings
cardpicker/tests/test_views.py: 58 warnings
  /opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/site-packages/elasticsearch/connection/base.py:200: ElasticsearchWarning: Elasticsearch built-in security features are not enabled. Without authentication, your cluster could be accessible to anyone. See https://www.elastic.co/guide/en/elasticsearch/reference/7.17/security-minimal-setup.html to enable security.
    warnings.warn(message, category=ElasticsearchWarning)

cardpicker/tests/test_local_file_source.py: 4 warnings
cardpicker/tests/test_views.py: 102 warnings
  /opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/site-packages/django/db/models/fields/__init__.py:1595: RuntimeWarning: DateTimeField Card.date_created received a naive datetime (2023-01-01 00:00:00) while time zone support is active.
    warnings.warn(

cardpicker/tests/test_local_file_source.py: 4 warnings
cardpicker/tests/test_views.py: 102 warnings
  /opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/site-packages/django/db/models/fields/__init__.py:1595: RuntimeWarning: DateTimeField Card.date_modified received a naive datetime (2023-01-01 00:00:00) while time zone support is active.
    warnings.warn(

cardpicker/tests/test_views.py::TestGetSources::test_get_multiple_sources
cardpicker/tests/test_views.py::TestGetSources::test_get_source_with_private_identifier
cardpicker/tests/test_views.py::TestGetDFCPairs::test_get_multiple_rows
cardpicker/tests/test_views.py::TestGetContributions::test_get_contribution_with_private_identifier
cardpicker/tests/test_views.py::TestGetImportSites::test_get_multiple_sites
  /opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/site-packages/sentry_sdk/integrations/django/middleware.py:134: UserWarning: No directory at: /home/runner/work/ProxyPrints.github.io/ProxyPrints.github.io/static/
    self._inner = middleware(get_response, *args, **kwargs)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
--------------------------- snapshot report summary ----------------------------
129 snapshots passed. 3 snapshots unused.

Re-run pytest with --snapshot-update to delete unused snapshots.
=========================== short test summary info ============================
FAILED cardpicker/tests/test_integrations.py::TestMTGIntegration::test_valid_url[moxfield] - assert None
FAILED cardpicker/tests/test_integrations.py::TestMTGIntegration::test_valid_url[moxfield_without_www] - assert None
FAILED cardpicker/tests/test_sources.py::TestUpdateDatabase::test_comprehensive_snapshot - json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
FAILED cardpicker/tests/test_sources.py::TestUpdateDatabase::test_upsert - json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
=========== 4 failed, 262 passed, 54549 warnings in 76.74s (0:01:16) ===========
```

INTERPRETATION: do not treat a failure here as a regression
without first cross-referencing this branch's own draft doc
(docs/upstreaming/drafts/<branch>.md) for its documented
expected-green baseline — known environmental gaps in this
fork's own CI (e.g. missing GOOGLE_DRIVE_API_KEY/
MOXFIELD_SECRET secrets) produce real, expected failures
unrelated to the branch's own code.
```

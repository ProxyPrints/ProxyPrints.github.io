```
TASK: Upstream branch verification (automated) — upstream-feat-local-file-source
Ref checked: upstream-feat-local-file-source @ 93874645890d4067bbed48dca232534940e11eb3
Trigger: schedule, run 31369631995

WHAT RAN:
1. pre-commit run --all-files (upstream's pinned hook versions) — exit 1
2. pytest . in MPCAutofill/ (upstream's test-backend recipe) — exit 1

PRE-COMMIT OUTPUT (tail):
```
 stderr)
                              ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repod6gldjs6/py_env-python3.13/lib/python3.13/site-packages/mypy/main.py", line 178, in run_build
    res = build.build(sources, options, None, flush_errors, fscache, stdout, stderr)
  File "/home/runner/.cache/pre-commit/repod6gldjs6/py_env-python3.13/lib/python3.13/site-packages/mypy/build.py", line 189, in build
    result = _build(
        sources, options, alt_lib_path, flush_errors, fscache, stdout, stderr, extra_plugins
    )
  File "/home/runner/.cache/pre-commit/repod6gldjs6/py_env-python3.13/lib/python3.13/site-packages/mypy/build.py", line 234, in _build
    plugin, snapshot = load_plugins(options, errors, stdout, extra_plugins)
                       ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repod6gldjs6/py_env-python3.13/lib/python3.13/site-packages/mypy/build.py", line 498, in load_plugins
    custom_plugins, snapshot = load_plugins_from_config(options, errors, stdout)
                               ~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repod6gldjs6/py_env-python3.13/lib/python3.13/site-packages/mypy/build.py", line 479, in load_plugins_from_config
    custom_plugins.append(plugin_type(options))
                          ~~~~~~~~~~~^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repod6gldjs6/py_env-python3.13/lib/python3.13/site-packages/mypy_django_plugin/main.py", line 64, in __init__
    self.django_context = DjangoContext(self.plugin_config.django_settings_module)
                          ~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repod6gldjs6/py_env-python3.13/lib/python3.13/site-packages/mypy_django_plugin/django/context.py", line 98, in __init__
    apps, settings = initialize_django(self.django_settings_module)
                     ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repod6gldjs6/py_env-python3.13/lib/python3.13/site-packages/mypy_django_plugin/django/context.py", line 82, in initialize_django
    apps.populate(settings.INSTALLED_APPS)
    ~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/.cache/pre-commit/repod6gldjs6/py_env-python3.13/lib/python3.13/site-packages/django/apps/registry.py", line 116, in populate
    app_config.import_models()
    ~~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/home/runner/.cache/pre-commit/repod6gldjs6/py_env-python3.13/lib/python3.13/site-packages/django/apps/config.py", line 269, in import_models
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
RROR cardpicker/tests/test_views.py::TestGetInfo::test_post_request - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestGetSearchEngineHealth::test_elasticsearch_healthy - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestGetSearchEngineHealth::test_post_request - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsFirstPages::test_basic_case - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsFirstPages::test_no_data_in_date_range - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsFirstPages::test_no_cards - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsFirstPages::test_no_sources - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsFirstPages::test_post_request - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_get_full_first_page - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_get_partial_first_page - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_get_full_second_page - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_no_data_in_date_range - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_post_request - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_response_to_malformed_json_body[no params] - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_response_to_malformed_json_body[invalid source] - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_response_to_malformed_json_body[zero page] - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_response_to_malformed_json_body[negative page] - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_response_to_malformed_json_body[non-number page] - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_response_to_malformed_json_body[no source field] - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_response_to_malformed_json_body[no page field] - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
ERROR cardpicker/tests/test_views.py::TestNewCardsPage::test_response_to_malformed_json_body[page out of range for source] - AttributeError: type object 'PytestDjangoTestCase' has no attribute '_pre_setup_ran_eagerly'
=========== 1 failed, 24 passed, 1688 warnings, 241 errors in 50.15s ===========
```

INTERPRETATION: do not treat a failure here as a regression
without first cross-referencing this branch's own draft doc
(docs/upstreaming/drafts/<branch>.md) for its documented
expected-green baseline — known environmental gaps in this
fork's own CI (e.g. missing GOOGLE_DRIVE_API_KEY/
MOXFIELD_SECRET secrets) produce real, expected failures
unrelated to the branch's own code.
```

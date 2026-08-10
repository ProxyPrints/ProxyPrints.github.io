```
TASK: Upstream branch verification (automated) — upstream-fix-pdf-eager-wasm-load
Ref checked: upstream-fix-pdf-eager-wasm-load @ 6c693eff5078b329559fbbe681fb74f0d7cbef13
Trigger: schedule, run 31369631995

WHAT RAN:
1. pre-commit run --all-files (upstream's pinned hook versions) — exit 0
2. pytest . in MPCAutofill/ (upstream's test-backend recipe) — exit 1

PRE-COMMIT OUTPUT (tail):
```
[INFO] Initializing environment for https://github.com/charliermarsh/ruff-pre-commit.
[INFO] Initializing environment for https://github.com/pycqa/isort.
[INFO] Initializing environment for https://github.com/pre-commit/pre-commit-hooks.
[WARNING] repo `https://github.com/pre-commit/pre-commit-hooks` uses deprecated stage names (commit, push) which will be removed in a future version.  Hint: often `pre-commit autoupdate --repo https://github.com/pre-commit/pre-commit-hooks` will fix this.  if it does not -- consider reporting an issue to that repo.
[INFO] Initializing environment for https://github.com/psf/black.
[INFO] Initializing environment for https://github.com/pre-commit/mirrors-mypy.
[INFO] Initializing environment for https://github.com/pre-commit/mirrors-mypy:django-stubs[compatible-mypy],types-Markdown,types-selenium,types-requests,types-chardet,pytest~=7.3,ratelimit~=2.2,attrs~=23.1,click==8.0.4,enlighten~=1.11,Django~=4.2.3,django-cors-headers~=3.14.0,django-elasticsearch-dsl~=7.3.0,django-bulk-sync~=3.3.0,django-environ~=0.10.0,django-q2~=1.8.0,google-api-python-client~=2.86,Levenshtein~=0.27.3,oauth2client~=4.1,Markdown~=3.4,psycopg2-binary~=2.9.6,pycountry~=22.3.0,pydantic~=2.10.0,sentry-sdk~=1.30.0,tqdm~=4.65.
[INFO] Initializing environment for https://github.com/pre-commit/mirrors-prettier.
[INFO] Initializing environment for https://github.com/pre-commit/mirrors-prettier:prettier@2.7.1.
[INFO] Initializing environment for https://github.com/pre-commit/mirrors-eslint.
[INFO] Initializing environment for https://github.com/pre-commit/mirrors-eslint:eslint@8.24.0,typescript@4.9.4,eslint-config-prettier@v8.5.0,eslint-config-next@v14.2.16,eslint-plugin-promise@v6.0.1,eslint-plugin-n@v15.3.0,eslint-plugin-import@v2.26.0,eslint-config-standard@v17.0.0,eslint-plugin-simple-import-sort@10.0.0,@typescript-eslint/eslint-plugin@6.5.0,@typescript-eslint/parser@5.49.0.
[INFO] Installing environment for https://github.com/charliermarsh/ruff-pre-commit.
[INFO] Once installed this environment will be reused.
[INFO] This may take a few minutes...
[INFO] Installing environment for https://github.com/pycqa/isort.
[INFO] Once installed this environment will be reused.
[INFO] This may take a few minutes...
[INFO] Installing environment for https://github.com/pre-commit/pre-commit-hooks.
[INFO] Once installed this environment will be reused.
[INFO] This may take a few minutes...
[INFO] Installing environment for https://github.com/psf/black.
[INFO] Once installed this environment will be reused.
[INFO] This may take a few minutes...
[INFO] Installing environment for https://github.com/pre-commit/mirrors-mypy.
[INFO] Once installed this environment will be reused.
[INFO] This may take a few minutes...
[INFO] Installing environment for https://github.com/pre-commit/mirrors-prettier.
[INFO] Once installed this environment will be reused.
[INFO] This may take a few minutes...
[INFO] Installing environment for https://github.com/pre-commit/mirrors-eslint.
[INFO] Once installed this environment will be reused.
[INFO] This may take a few minutes...
ruff.....................................................................Passed
isort (python)...........................................................Passed
Check Yaml...............................................................Passed
Fix End of Files.........................................................Passed
Trim Trailing Whitespace.................................................Passed
black....................................................................Passed
mypy.....................................................................Passed
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
=========== 1 failed, 16 passed, 1648 warnings, 232 errors in 47.60s ===========
```

INTERPRETATION: do not treat a failure here as a regression
without first cross-referencing this branch's own draft doc
(docs/upstreaming/drafts/<branch>.md) for its documented
expected-green baseline — known environmental gaps in this
fork's own CI (e.g. missing GOOGLE_DRIVE_API_KEY/
MOXFIELD_SECRET secrets) produce real, expected failures
unrelated to the branch's own code.
```

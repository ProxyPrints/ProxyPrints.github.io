```
TASK: Upstream branch verification (automated) — upstream-fix-image-cdn-cors
Ref checked: upstream-fix-image-cdn-cors @ 08b9d2be49a81103e9af6f53497c42c85484978c
Trigger: schedule, run 29732866324

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
::test_comprehensive_snapshot
  /opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/site-packages/django/db/models/fields/__init__.py:1595: RuntimeWarning: DateTimeField Card.date_modified received a naive datetime (2026-07-20 06:01:01.077326) while time zone support is active.
    warnings.warn(

cardpicker/tests/test_dfc_pairs.py::TestSyncDFCs::test_comprehensive_snapshot
  /opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/site-packages/django/db/models/fields/__init__.py:1595: RuntimeWarning: DateTimeField Card.date_modified received a naive datetime (2026-07-20 06:01:01.077354) while time zone support is active.
    warnings.warn(

cardpicker/tests/test_integrations.py::TestMTGIntegration::test_import_canonical_cards_and_artists[card with an expansion code not in db is skipped]
  /opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/site-packages/sentry_sdk/integrations/logging.py:285: DeprecationWarning: datetime.datetime.utcfromtimestamp() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.fromtimestamp(timestamp, datetime.UTC).
    "timestamp": datetime.datetime.utcfromtimestamp(record.created),

cardpicker/tests/test_sources.py: 8 warnings
cardpicker/tests/test_views.py: 58 warnings
  /opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/site-packages/elasticsearch/connection/base.py:200: ElasticsearchWarning: Elasticsearch built-in security features are not enabled. Without authentication, your cluster could be accessible to anyone. See https://www.elastic.co/guide/en/elasticsearch/reference/7.17/security-minimal-setup.html to enable security.
    warnings.warn(message, category=ElasticsearchWarning)

cardpicker/tests/test_views.py: 102 warnings
  /opt/hostedtoolcache/Python/3.13.14/x64/lib/python3.13/site-packages/django/db/models/fields/__init__.py:1595: RuntimeWarning: DateTimeField Card.date_created received a naive datetime (2023-01-01 00:00:00) while time zone support is active.
    warnings.warn(

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
=========== 4 failed, 245 passed, 52212 warnings in 69.70s (0:01:09) ===========
```

INTERPRETATION: do not treat a failure here as a regression
without first cross-referencing this branch's own draft doc
(docs/upstreaming/drafts/<branch>.md) for its documented
expected-green baseline — known environmental gaps in this
fork's own CI (e.g. missing GOOGLE_DRIVE_API_KEY/
MOXFIELD_SECRET secrets) produce real, expected failures
unrelated to the branch's own code.
```

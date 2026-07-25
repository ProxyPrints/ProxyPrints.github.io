# Docker to serve Django via Unicorn
FROM python:3.13-slim AS builder

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1
# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Install tools and additional dependencies
#
# tesserocr (issue #423, 2026-07-25 spike): g++ and libtesseract-dev/libleptonica-dev are added
# here even though the tesserocr 2.10.0 wheel below is prebuilt for aarch64 (no source build of
# tesserocr itself needed) - the spike's own throwaway harness included them and measured the
# whole build at ~94s, dominated by apt fetch/install, not compilation; kept here to match that
# verified recipe rather than trim untested. g++ specifically covers cysignals (a tesserocr
# dependency) building its small C++ extension from source.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        dos2unix \
        gcc g++ netcat-traditional curl libpq-dev \
        tesseract-ocr tesseract-ocr-eng \
        libtesseract-dev libleptonica-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt
COPY MPCAutofill/requirements.txt /MPCAutofill/
WORKDIR /MPCAutofill

# Install pip requirements
RUN pip3 install gunicorn wheel
RUN pip3 install -r requirements.txt

# tesserocr (issue #423): pinned to the exact version the 2026-07-25 spike validated (2.10.0,
# aarch64 wheel `tesserocr-2.10.0-cp313-cp313-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl`
# confirmed available). This image now carries BOTH OCR engines - `settings.OCR_ENGINE`
# (cardpicker/local_ocr.py) controls which one actually runs, default "pytesseract" (unchanged
# behavior) in every deployed environment as of this PR. NOT flipped here: the wheel vendors its
# own tesseract 5.5.1/leptonica 1.85.0, a different compiled build than this image's apt
# `tesseract-ocr` package (5.5.0/1.84.1) - see local_ocr.py's own module docstring for why that
# gates the flip on `ocr_engine_ab`'s real-image validation, bundled with the extractor-version
# bump at issue #480's combined whole-catalog pass, not shipped dark-but-live here.
RUN pip3 install "tesserocr==2.10.0"

# Copy relevant files from repository
COPY docker /MPCAutofill/docker
COPY MPCAutofill /MPCAutofill/MPCAutofill

# Iteration safety (docs/features/catalog-completion-plan.md's Part 1): .git is excluded from
# the build context (.dockerignore), so the SHA must be passed in from the host via
# --build-arg, computed before the build starts (see the required GIT_SHA=... prefix on the
# documented rebuild command) - it can't be computed from inside this Dockerfile. Best-effort
# visibility only (cardpicker.utils.get_baked_git_sha) - the hard staleness gate
# (find_stale_applied_migrations) is deliberately independent of this and can't be bypassed by
# a forgotten build-arg the way this file's own freshness could be.
ARG GIT_SHA=unknown
RUN echo "$GIT_SHA" > /MPCAutofill/MPCAutofill/GIT_SHA

# Handle environment variables - write out `.env` with the variables passed from the
# compose file (and overwrite `.env` as copied from the host machine in the process)
RUN touch /MPCAutofill/MPCAutofill/MPCAutofill/.env
RUN echo "DATABASE_HOST=$DATABASE_HOST" > /MPCAutofill/MPCAutofill/MPCAutofill/.env  # using > to overwrite the file
RUN echo "ELASTICSEARCH_HOST=$ELASTICSEARCH_HOST" >> /MPCAutofill/MPCAutofill/MPCAutofill/.env
RUN echo "DEBUG=$DEBUG" >> /MPCAutofill/MPCAutofill/MPCAutofill/.env
RUN echo "ALLOWED_HOSTS=$ALLOWED_HOSTS" >> /MPCAutofill/MPCAutofill/MPCAutofill/.env
RUN echo "GAME=$GAME" >> /MPCAutofill/MPCAutofill/MPCAutofill/.env
RUN echo "MOXFIELD_SECRET=$MOXFIELD_SECRET" >> /MPCAutofill/MPCAutofill/MPCAutofill/.env

# Make sure that all scripts are executable, and in case we
# checked out under Windows with CRLF, convert line endings
RUN chmod +x docker/django/*.sh && \
    find . -type f -name "*.sh" -exec dos2unix {} \;

# Let's be nice to the user and give some clear error message
# if they missed to install any of the mandatory files.
RUN ./docker/django/check_client_secrets.sh && \
    ./docker/django/check_drives.sh

# Create a non-root user and add permission to access the /MPCAutofill folder
RUN adduser -u 5678 --disabled-password --gecos "" mpcautofill && \
    chown -R mpcautofill /MPCAutofill
USER mpcautofill

# Place environment file if one does not already exist
RUN ./docker/django/copy_env_file.sh

# Prepare folder for static files (create now as user for permissions)
RUN mkdir -p static


FROM builder AS webserver

EXPOSE 8000
WORKDIR /MPCAutofill/MPCAutofill
ENTRYPOINT ["/MPCAutofill/docker/django/entrypoint.sh"]
CMD ["gunicorn", "MPCAutofill.wsgi:application", "--bind", "0.0.0.0:8000"]

FROM builder AS worker

WORKDIR /MPCAutofill/MPCAutofill
ENTRYPOINT ["/MPCAutofill/docker/django/entrypoint.sh"]
CMD ["python3", "manage.py", "qcluster"]

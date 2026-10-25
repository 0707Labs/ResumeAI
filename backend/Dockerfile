# The API and its scheduled jobs (docs/deploy.md, "Railway"). Build from backend/:
#   docker build -t resume-tailor-api backend
# Runs `python -m app.serve` as an unprivileged user on $PORT (default 8000).

FROM python:3.11-slim-bookworm AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /build
# Dependencies only, so this layer is rebuilt only when pyproject.toml changes. The app
# itself runs from source (billing.toml and alembic/ are read relative to it).
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
 && pip install --upgrade pip \
 && pip install . \
 && pip uninstall --yes resume-tailor

FROM python:3.11-slim-bookworm AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000
RUN useradd --system --uid 10001 --user-group --home-dir /nonexistent --shell /usr/sbin/nologin app
COPY --from=deps /opt/venv /opt/venv
WORKDIR /srv/backend
# Owned by root and read-only to the app user: nothing in the image is writable at runtime.
COPY alembic.ini billing.toml ./
COPY alembic ./alembic
COPY app ./app
USER app
EXPOSE 8000
CMD ["python", "-m", "app.serve"]

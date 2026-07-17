# syntax=docker/dockerfile:1
# {{ project_name }} backend — FastAPI. Image bakes source + dev deps so the
# same image serves the app (default command) and the `tools` profile
# (ruff/mypy/pytest, command overridden at call time).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Deps first for layer caching. The BuildKit cache mount keeps pip's download
# cache OUT of the image while avoiding re-downloads when this layer busts, so a
# pyproject change re-resolves without re-fetching every unchanged wheel. The
# editable install runs before `COPY . .` (setuptools maps zero packages now);
# its egg-link picks up app/ once the source is copied below — see the
# [tool.pytest.ini_options] note in pyproject.toml.
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e ".[dev]"

COPY . .

# Deploy provenance — kept as the LAST layers so changing them never busts the
# dependency/source cache. Empty on a plain `docker build`; `make up` passes the
# real values. Surfaced at GET /health so you can verify which commit is live.
ARG BUILD_TIME=""
ARG GIT_SHA=""
ENV APP_BUILD_TIME=$BUILD_TIME \
    APP_GIT_SHA=$GIT_SHA

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

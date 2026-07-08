# {{ project_name }} backend — FastAPI. Image bakes source + dev deps so the
# same image serves the app (default command) and the `tools` profile
# (ruff/mypy/pytest, command overridden at call time).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

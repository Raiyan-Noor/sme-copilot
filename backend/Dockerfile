# Build from the repo root (docker-compose.yml sets the context): the backend needs the skills/ library too.
FROM python:3.12-slim

WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/sandboxpay ./sandboxpay
# app/config.py resolves the repo root two levels above app/, which is / here, so the built-in skills go to /skills.
COPY skills /skills
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

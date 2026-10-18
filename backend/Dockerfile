FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The app resolves REPO_ROOT as parents[3] of backend/app/core/config.py,
# so the image keeps the same layout as the repository: /app/{backend,pipeline,samples,data}.
WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/ /app/backend/
COPY pipeline/ /app/pipeline/
COPY samples/ /app/samples/
COPY scripts/ /app/scripts/

RUN mkdir -p /app/data/uploads /app/data/generated

WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

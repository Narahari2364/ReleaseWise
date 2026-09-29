FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY data/ data/

# Bake the embedding model and the vector index into the image,
# so the container starts instantly and retrieval works with no network access
RUN python -m src.app ingest

# Don't run as root
RUN useradd --create-home app && chown -R app /app
USER app

# ANTHROPIC_API_KEY is passed at runtime (--env-file .env), never baked into the image
ENTRYPOINT ["python", "-m", "src.app"]
CMD ["chat"]

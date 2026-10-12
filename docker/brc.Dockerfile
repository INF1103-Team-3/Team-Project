# Container 2: BRC. Runs the halal-check service that BRNS calls over the
# Docker network, and also holds the scraper and the BRC checker, which you
# start inside it with `docker compose exec brc ...`.
# Build from the repository root:  docker compose build brc
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HALAL_SERVICE_HOST=0.0.0.0 \
    HALAL_SERVICE_PORT=8000

WORKDIR /app

COPY BRC/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && useradd --create-home --uid 1000 app

COPY BRC ./BRC
COPY shared ./shared
# Runtime folders are bind-mounted by docker-compose.yml; create them so the
# image also works on its own.
RUN mkdir -p /app/BRC/data /app/data /app/logs \
    && chown -R app:app /app/BRC/data /app/data /app/logs

USER app
EXPOSE 8000

# Healthy once the service answers; docker-compose makes bis-brns wait for it.
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["python", "BRC/halal_service.py"]

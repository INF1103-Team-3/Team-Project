# Container 1: BIS + BRNS. BIS calls BRNS in-process, so they share one
# container. BRNS asks the BRC container (http://brc:8000) for halal checks.
# Build from the repository root:  docker compose build bis-brns
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/requirements-bis-brns.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && useradd --create-home --uid 1000 app

COPY BIS ./BIS
COPY BRNS ./BRNS
COPY shared ./shared
# BRNS imports only BRC's shared halal-matching module, not the BRC app.
COPY BRC/halal_checker.py ./BRC/halal_checker.py
RUN mkdir -p /app/BIS/data /app/BRNS/data /app/data /app/logs \
    && chown -R app:app /app/BIS/data /app/BRNS/data /app/data /app/logs

USER app

CMD ["python", "BIS/main.py"]

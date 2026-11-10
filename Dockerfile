FROM python:3.11-slim-bookworm AS source
ARG SEED_ACCOUNTS=yes
WORKDIR /src
COPY . .
RUN set -eux; \
    mkdir -p BIS/data BRC/data BRNS/data data logs /seed; \
    find data logs -mindepth 1 -delete; \
    find BIS/data BRC/data BRNS/data \
        \( -name '.gitkeep' -o -name '*.lock' -o -name '*.tmp' -o -name '*.bak' \) -delete; \
    if [ "$SEED_ACCOUNTS" != "yes" ]; then \
        rm -f BIS/data/users.json BIS/data/profile_state.json; \
    fi; \
    cp -a BIS/data /seed/bis; \
    cp -a BRNS/data /seed/brns; \
    cp -a BRC/data /seed/brc; \
    find BIS/data BRNS/data BRC/data -mindepth 1 -delete


FROM python:3.11-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY <<'EOF' /usr/local/bin/docker-entrypoint.sh
#!/bin/sh
set -e
mkdir -p /data/logs
for src in /opt/seed/*/; do
    [ -d "$src" ] || continue
    name=${src%/}
    name=${name##*/}
    mkdir -p "/data/$name"
done
if [ ! -e /data/.seeded ]; then
    for src in /opt/seed/*/; do
        [ -d "$src" ] || continue
        name=${src%/}
        name=${name##*/}
        (cd "$src" && find . -type f) | while IFS= read -r file; do
            target="/data/$name/${file#./}"
            if [ ! -e "$target" ]; then
                mkdir -p "${target%/*}"
                cp -p "$src${file#./}" "$target"
            fi
        done
    done
    touch /data/.seeded
fi
exec "$@"
EOF
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod 0755 /usr/local/bin/docker-entrypoint.sh


FROM base AS brc

COPY --from=source --chown=10001:10001 /src/BRC /app/BRC
COPY --from=source --chown=10001:10001 /src/shared /app/shared

RUN mkdir -p /opt/seed/brc
COPY --from=source --chown=10001:10001 /seed/brc/ /opt/seed/brc/

RUN set -eux; \
    mkdir -p /data/brc /data/logs; \
    cp -a /opt/seed/brc/. /data/brc/; \
    rm -rf /app/BRC/data /app/logs; \
    ln -s /data/brc  /app/BRC/data; \
    ln -s /data/logs /app/logs; \
    chown -R 10001:10001 /data


VOLUME ["/data"]
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "BRC.classes.brc_http_server"]


FROM base AS bis-brns

COPY --from=source --chown=10001:10001 /src/ /app/


RUN mkdir -p /opt/seed/bis /opt/seed/brns
COPY --from=source --chown=10001:10001 /seed/bis/ /opt/seed/bis/
COPY --from=source --chown=10001:10001 /seed/brns/ /opt/seed/brns/
RUN set -eux; \
    mkdir -p /data/bis /data/brns /data/logs; \
    cp -a /opt/seed/bis/. /data/bis/; \
    cp -a /opt/seed/brns/. /data/brns/; \
    rm -rf /app/BIS/data /app/BRNS/data /app/data /app/logs; \
    mkdir -p /app/BRC/data; \
    ln -s /data/bis  /app/BIS/data; \
    ln -s /data/brns /app/BRNS/data; \
    ln -s /data/brns /app/data; \
    ln -s /data/logs /app/logs; \
    chown -R 10001:10001 /data /app/BRC/data


ENV PYTHONPATH=/app


VOLUME ["/data"]
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "main.py"]


FROM bis-brns AS api
USER root
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt
USER 10001:10001
CMD ["uvicorn", "web_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM api AS web-test
USER root
COPY requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt
USER 10001:10001
CMD ["python", "tests/run_tests.py", "web"]

# Preserve the standalone CLI as the default build target.
FROM bis-brns AS default

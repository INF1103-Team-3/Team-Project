
# BiteFinder: one image for BIS, BRNS and BRC (BRNS imports BRC in-process).
#
# Persistence: every folder the apps write to is a symlink into ONE volume
# mounted at /data, so a single -v flag keeps accounts, search history, the
# MUIS halal database, the geocode cache and logs across containers:
    
# Run
# docker build -t bitefinder .
# docker run --rm -it --env-file .env -v bitefinder-data:/data bitefinder

# ---------------------------------------------------------------------------
# Stage 1: copy the project (honouring .dockerignore) and strip local runtime
# data, so a developer's accounts, caches and logs never ship inside the image.
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS source
WORKDIR /src
COPY . .
RUN set -eux; \
    mkdir -p BIS/data BRC/data BRNS/data data logs; \
    find BIS/data BRC/data data logs -mindepth 1 -delete; \
    rm -f BRNS/data/search_history.json

# ---------------------------------------------------------------------------
# Stage 2: runtime image
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=source --chown=10001:10001 /src/ /app/

# Persistent layout inside the single volume:
#   /data/bis     <- BIS/data      users.json, profile_state.json
#   /data/brns    <- BRNS/data     restaurants.json, search_history.json
#   /data/brc     <- BRC/data      MUIS database and caches
#   /data/shared  <- data          geocode cache (shared by BIS, BRNS, BRC)
#   /data/logs    <- logs          bitefinder.log
# BRNS's bundled restaurants.json is placed in /data/brns (so a new volume is
# seeded automatically) and kept at /opt/seed (so the entrypoint can re-seed a
# volume that already exists but lacks it).
RUN set -eux; \
    mkdir -p /opt/seed /data/bis /data/brns /data/brc /data/shared /data/logs; \
    if [ -f /app/BRNS/data/restaurants.json ]; then \
        cp /app/BRNS/data/restaurants.json /opt/seed/restaurants.json; \
        cp /app/BRNS/data/restaurants.json /data/brns/restaurants.json; \
    fi; \
    rm -rf /app/BIS/data /app/BRNS/data /app/BRC/data /app/data /app/logs; \
    ln -s /data/bis    /app/BIS/data; \
    ln -s /data/brns   /app/BRNS/data; \
    ln -s /data/brc    /app/BRC/data; \
    ln -s /data/shared /app/data; \
    ln -s /data/logs   /app/logs; \
    chown -R 10001:10001 /data /opt/seed

# Runs before every command: recreates folders in a volume that was created
# empty or by an older image, and seeds the restaurant fallback once.
COPY <<'EOF' /usr/local/bin/docker-entrypoint.sh
#!/bin/sh
set -e
mkdir -p /data/bis /data/brns /data/brc /data/shared /data/logs
if [ -f /opt/seed/restaurants.json ] && [ ! -e /data/brns/restaurants.json ]; then
    cp /opt/seed/restaurants.json /data/brns/restaurants.json
fi
exec "$@"
EOF
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

# Declared after the chown above so the volume starts owned by the app user.
VOLUME ["/data"]

USER 10001:10001

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "BIS/main.py"]

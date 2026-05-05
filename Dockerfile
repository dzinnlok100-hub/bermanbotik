# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Playwright runtime deps (Chromium needs these on slim base images)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libxkbcommon0 libxcomposite1 libxrandr2 libxdamage1 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
        fonts-liberation fonts-noto-cjk fonts-noto-color-emoji \
        ca-certificates curl wget tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN pip install --upgrade pip \
 && pip install . \
 && playwright install --with-deps chromium

# Persistent data lives in /app/data (mount a volume here)
RUN mkdir -p /app/data/images
VOLUME ["/app/data"]

ENV DB_PATH=/app/data/bot.db \
    IMAGES_DIR=/app/data/images

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "berman_bot"]

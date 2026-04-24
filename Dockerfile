FROM python:3.11-slim AS runtime

ARG FTL_GIT_SHA=unknown
ARG FTL_BUILT_AT=unknown
ARG FTL_IMAGE_TAG=unknown

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    FTL_GIT_SHA=$FTL_GIT_SHA \
    FTL_BUILT_AT=$FTL_BUILT_AT \
    FTL_IMAGE_TAG=$FTL_IMAGE_TAG

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/inbox data/archive data/logs data/config

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", "-w", "1", "-k", "sync", "--graceful-timeout", "30", \
     "-b", "0.0.0.0:8000", "wsgi:app"]

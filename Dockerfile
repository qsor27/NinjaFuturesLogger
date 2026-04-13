FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

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

ARG BASE_IMAGE=python:3.11-slim-bookworm
FROM ${BASE_IMAGE}

ARG APP_VERSION=dev

LABEL org.opencontainers.image.title="Bearer Token API Proxy" \
    org.opencontainers.image.description="Generic bearer-token API proxy" \
    org.opencontainers.image.version="$APP_VERSION"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The image contains application code only. Runtime configuration and optional
# CA certificates are bind-mounted by compose.yml and are not baked into layers.
COPY app.py /app/app.py
COPY bearer_proxy /app/bearer_proxy

RUN python -m py_compile /app/app.py /app/bearer_proxy/*.py \
    && mkdir -p /app/config /app/certs

EXPOSE 8787
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/readyz', timeout=3).read()" || exit 1

CMD ["python", "/app/app.py", "--env-file", "/app/config/proxy.env", "--config-file", "/app/config/proxy.json"]

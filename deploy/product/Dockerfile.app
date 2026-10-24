# P2 API / Worker / publisher runtime. Build context is the repository root.
FROM python:3.11-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && node --version

RUN python3 -m venv /opt/product
COPY deploy/product/requirements.lock /tmp/requirements.lock
RUN /opt/product/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock

COPY server /app/server
COPY tools /app/tools
COPY internal /app/internal
# API/Worker generate pages with these assets; Nginx serves the public site separately.
COPY site/assets /app/site/assets
COPY site/data/knowledge-next /app/site/data/knowledge-next
COPY site/data/graph-walk/quadratic-always-q01.source.json /app/site/data/graph-walk/quadratic-always-q01.source.json
COPY site/knowledge/graph.json /app/site/knowledge/graph.json
RUN test -f /app/server/uv.lock \
 && test -f /app/tools/build-lesson-page.mjs \
 && test -f /app/internal/templates/interactive-problem-page.template.html \
 && test -f /app/site/data/knowledge-next/execution/milestones.json \
 && test -f /app/site/data/graph-walk/quadratic-always-q01.source.json \
 && test -f /app/site/knowledge/graph.json

WORKDIR /app/server
ENV PATH="/opt/product/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/server \
    PRODUCT_IN_CONTAINER=1 \
    REVIEW_BACKEND=product

CMD ["uvicorn", "shuxueshuo_server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--forwarded-allow-ips", "172.16.0.0/12"]

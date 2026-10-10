FROM ghcr.io/maxrink/litellm-otel-cache-fix@sha256:d544bc8c2000be45030b07c23959de3877420e2df4cffe57d8d87d9e33c70ee2
COPY base-d544-1227bd.caching.py /tmp/base-d544-1227bd.caching.py
COPY verify_base.py /tmp/verify_base.py
RUN python /tmp/verify_base.py /tmp/base-d544-1227bd.caching.py
COPY caching.py /app/.venv/lib/python3.13/site-packages/litellm/caching/caching.py

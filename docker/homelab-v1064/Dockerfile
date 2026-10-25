# Homelab overlay on the official LiteLLM v1.106.4 image.
# Build context: the repository root of this branch, so the overlaid modules
# are exactly the fork's rebased sources (no copied snapshot to drift).
#   docker build -f docker/homelab-v1064/Dockerfile -t <tag> .
# v1.106.4 already ships certifi 2026.10.19 (no eMudhra roots), grpcio 1.84.1,
# OpenTelemetry 1.45.1, pypdf 6.21.2, GitPython 3.2.1 and graphql-core 3.2.12,
# so the v1062 runtime-deps stage is gone. The v1062 overlay of
# litellm/responses/ is dropped too: it carried no fork change and replaced
# v1.106.2+ responses/main.py with the v1.106.1 copy, which lacks
# provider_stores_the_conversation (imported by proxy/db/db_spend_update_writer).
ARG BASE_IMAGE=ghcr.io/berriai/litellm:v1.106.4@sha256:c169fb3adc514fcf210377c203f3de406d54f10bfdacf13948a4a839db9af7de
FROM ${BASE_IMAGE}
ARG SITE=/app/.venv/lib/python3.13/site-packages/litellm
COPY litellm/caching/caching_handler.py ${SITE}/caching/caching_handler.py
COPY litellm/completion_extras/litellm_responses_transformation/transformation.py ${SITE}/completion_extras/litellm_responses_transformation/transformation.py
COPY litellm/experimental_mcp_client/tools.py ${SITE}/experimental_mcp_client/tools.py
COPY litellm/integrations/prometheus.py ${SITE}/integrations/prometheus.py
COPY litellm/integrations/opentelemetry.py ${SITE}/integrations/opentelemetry.py
COPY litellm/proxy/proxy_server.py ${SITE}/proxy/proxy_server.py
COPY docker/homelab-v1064/litellm-forwardport.py /tmp/litellm-forwardport.py
RUN python /tmp/litellm-forwardport.py \
      --cache ${SITE}/caching/caching.py \
      --otel ${SITE}/integrations/opentelemetry.py \
    && rm /tmp/litellm-forwardport.py \
    && python -m py_compile \
      ${SITE}/caching/caching.py \
      ${SITE}/caching/caching_handler.py \
      ${SITE}/integrations/opentelemetry.py \
      ${SITE}/integrations/prometheus.py \
      ${SITE}/completion_extras/litellm_responses_transformation/transformation.py \
      ${SITE}/experimental_mcp_client/tools.py \
      ${SITE}/proxy/proxy_server.py

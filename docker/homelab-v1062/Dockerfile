ARG BASE_IMAGE=ghcr.io/berriai/litellm:v1.106.2

FROM python:3.13-slim AS runtime-deps
RUN pip install --no-cache-dir --target /install \
      certifi==2026.10.19 \
      pypdf==6.21.2 \
      GitPython==3.2.1 \
      graphql-core==3.2.12

FROM ${BASE_IMAGE}
COPY source/litellm/caching/caching_handler.py /app/.venv/lib/python3.13/site-packages/litellm/caching/caching_handler.py
COPY source/litellm/completion_extras/litellm_responses_transformation/transformation.py /app/.venv/lib/python3.13/site-packages/litellm/completion_extras/litellm_responses_transformation/transformation.py
COPY source/litellm/responses/ /app/.venv/lib/python3.13/site-packages/litellm/responses/
COPY source/litellm/experimental_mcp_client/tools.py /app/.venv/lib/python3.13/site-packages/litellm/experimental_mcp_client/tools.py
COPY source/litellm/integrations/prometheus.py /app/.venv/lib/python3.13/site-packages/litellm/integrations/prometheus.py
COPY source/litellm/integrations/opentelemetry.py /app/.venv/lib/python3.13/site-packages/litellm/integrations/opentelemetry.py
COPY source/litellm/proxy/proxy_server.py /app/.venv/lib/python3.13/site-packages/litellm/proxy/proxy_server.py
COPY litellm-v1062-forwardport.py /tmp/litellm-v1062-forwardport.py
# Keep the runtime aligned with the fork's security-validated lockfile.  The
# upstream image does not install these optional proxy/runtime packages.
RUN rm -rf /app/.venv/lib/python3.13/site-packages/pypdf \
      /app/.venv/lib/python3.13/site-packages/pypdf-*.dist-info \
      /app/.venv/lib/python3.13/site-packages/certifi \
      /app/.venv/lib/python3.13/site-packages/certifi-*.dist-info
COPY --from=runtime-deps /install/ /app/.venv/lib/python3.13/site-packages/
RUN python /tmp/litellm-v1062-forwardport.py \
      --cache /app/.venv/lib/python3.13/site-packages/litellm/caching/caching.py \
      --otel /app/.venv/lib/python3.13/site-packages/litellm/integrations/opentelemetry.py \
    && python -m py_compile \
      /app/.venv/lib/python3.13/site-packages/litellm/caching/caching.py \
      /app/.venv/lib/python3.13/site-packages/litellm/caching/caching_handler.py \
      /app/.venv/lib/python3.13/site-packages/litellm/integrations/opentelemetry.py \
      /app/.venv/lib/python3.13/site-packages/litellm/completion_extras/litellm_responses_transformation/transformation.py \
      /app/.venv/lib/python3.13/site-packages/litellm/responses/main.py \
      /app/.venv/lib/python3.13/site-packages/litellm/experimental_mcp_client/tools.py

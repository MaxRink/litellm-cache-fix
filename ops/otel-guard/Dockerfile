ARG BASE_IMAGE=ghcr.io/maxrink/homelab-litellm-otel-guard@sha256:ff115da7fdf79dc9ba34ef481b791729bd329767ede1093369d3cbc05ded59c1
FROM ${BASE_IMAGE}
LABEL org.opencontainers.image.description="LiteLLM fallback caller attribution"
LABEL org.opencontainers.image.source="https://github.com/MaxRink/litellm-cache-fix"
LABEL org.opencontainers.image.base.digest="sha256:ff115da7fdf79dc9ba34ef481b791729bd329767ede1093369d3cbc05ded59c1"
LABEL com.maxrink.patch.prometheus.sha256="cf4093a37a7fe18cbaab6a06d86e792fab5a7b528c3135d552d2b2b86353608f"
COPY litellm/integrations/prometheus.py /app/.venv/lib/python3.13/site-packages/litellm/integrations/prometheus.py

#!/usr/bin/env bash
set -euo pipefail

base_image=${1:?image digest required}
workdir=$(mktemp -d)
trap 'docker rm -f otel-qa-base otel-qa-guarded >/dev/null 2>&1 || true; rm -rf "$workdir"' EXIT

cat >"$workdir/config.yaml" <<'YAML'
model_list:
  - model_name: qa-unused
    litellm_params:
      model: openai/unused
      api_base: http://127.0.0.1:9/v1
      api_key: qa-unused
general_settings:
  master_key: qa-master
litellm_settings:
  callbacks: [otel]
YAML

run_case() {
  local name=$1 image=$2
  docker run -d --rm --name "$name" --network none \
    -p 127.0.0.1:4010:4000 \
    -e LITELLM_MASTER_KEY=qa-master \
    -e LITELLM_OTEL_V2=true \
    -e LITELLM_OTEL_INTEGRATION_ENABLE_METRICS=true \
    -e LITELLM_OTEL_INTEGRATION_ENABLE_EVENTS=false \
    -e OTEL_EXPORTER=console \
    -v "$workdir/config.yaml:/tmp/config.yaml:ro" \
    "$image" --config /tmp/config.yaml --host 0.0.0.0 --port 4000 >/dev/null

  for _ in $(seq 1 60); do
    if docker exec "$name" python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:4000/health/readiness", timeout=1)' >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  docker exec "$name" python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:4000/metrics", timeout=5); body=r.read(); assert r.status == 200 and body, r.status' \
    >/dev/null
  sleep 2
  docker logs "$name" >"$workdir/$name.log" 2>&1 || true
  local warning_count
  warning_count=$(grep -c "Setting attribute on ended span" "$workdir/$name.log" || true)
  docker rm -f "$name" >/dev/null 2>&1 || true
  printf '%s\n' "$warning_count"
}

echo "baseline_warning_count=$(run_case otel-qa-base "$base_image" | tail -1)"

cat >"$workdir/Dockerfile" <<'DOCKERFILE'
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
RUN python - <<'PY'
from pathlib import Path
import sys

needle = "primitive_value: Final = self._cast_as_primitive_value_type(value)\n        span.set_attribute(key, primitive_value)"
replacement = "if hasattr(span, \"is_recording\") and not span.is_recording():\n            return\n        primitive_value: Final = self._cast_as_primitive_value_type(value)\n        span.set_attribute(key, primitive_value)"
for root in sys.path:
    path = Path(root) / "litellm/integrations/opentelemetry.py"
    if path.exists():
        text = path.read_text()
        if needle not in text:
            raise SystemExit(f"guard insertion point not found: {path}")
        path.write_text(text.replace(needle, replacement, 1))
        break
else:
    raise SystemExit("installed LiteLLM source not found")
PY
DOCKERFILE
docker build --build-arg BASE_IMAGE="$base_image" -t otel-qa-guarded "$workdir" >/dev/null
echo "guarded_warning_count=$(run_case otel-qa-guarded otel-qa-guarded | tail -1)"

for log in "$workdir"/*.log; do
  grep -E "^.*(Setting attribute on ended span|Traceback|ERROR).*" "$log" | sed -E 's/(Authorization|api_key|token|prompt|messages)[^ ]*/[redacted]/Ig' | head -20 || true
done

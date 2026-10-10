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
      api_base: http://127.0.0.1:18080/v1
      api_key: qa-unused
general_settings:
  master_key: qa-master
litellm_settings:
  callbacks: [prometheus, otel]
YAML

cat >"$workdir/provider.py" <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        body = {"id": "qa-completion", "object": "chat.completion", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
    def log_message(self, *_args):
        pass

HTTPServer(("127.0.0.1", 18080), Handler).serve_forever()
PY

cat >"$workdir/prom_fixture.py" <<'PY'
import asyncio
import hashlib
from datetime import datetime, timedelta
from prometheus_client import REGISTRY, generate_latest
import litellm
from litellm.integrations.prometheus import PrometheusLogger

metadata = {
    "user_api_key_user_id": "qa-user",
    "user_api_key_hash": "qa-key-hash",
    "user_api_key_alias": "qa-alias",
    "user_api_key_team_id": "qa-team",
    "user_api_key_team_alias": "qa-team-alias",
    "user_api_key_user_email": "qa@example.invalid",
    "requester_ip_address": "127.0.0.1",
    "user_api_key_org_id": None,
    "user_api_key_org_alias": None,
    "user_api_key_request_route": "/v1/chat/completions",
}
payload = {
    "metadata": metadata,
    "completion_tokens": 1,
    "prompt_tokens": 1,
    "total_tokens": 2,
    "response_cost": 0.0,
    "request_tags": [],
    "model_group": "qa-unused",
    "model_id": "qa-deployment",
    "api_base": "http://127.0.0.1:18080/v1",
    "custom_llm_provider": "openai",
    "stream": False,
    "hidden_params": {"additional_headers": {}, "litellm_overhead_time_ms": 0},
}
logger = PrometheusLogger()
litellm.callbacks = [logger]
end_time = datetime.now()
asyncio.run(logger.async_log_success_event({"model": "qa-unused", "litellm_params": {"metadata": metadata}, "standard_logging_object": payload}, {"model": "qa-unused"}, end_time - timedelta(milliseconds=25), end_time))
text = generate_latest(REGISTRY).decode()
samples = [line for line in text.splitlines() if line.startswith("litellm_")]
assert samples, "production Prometheus callback emitted no litellm samples"
metadata_lines = sorted(line for line in text.splitlines() if line.startswith("# HELP ") or line.startswith("# TYPE "))
stable_samples = sorted(
    line for line in samples
    if (line.startswith("litellm_proxy_total_requests_metric") or line.startswith("litellm_requests_metric"))
    and "_created{" not in line
)
assert stable_samples, "production Prometheus callback emitted no stable request counter"
assert any('team="qa-team"' in line and 'user="qa-user"' in line and 'api_key_alias="qa-alias"' in line for line in stable_samples), "production Prometheus samples omitted caller/team metadata"
print(f"fixture_metric_sample_count={len(samples)}")
print(f"fixture_metric_metadata_sha256={hashlib.sha256(('\\n'.join(metadata_lines)).encode()).hexdigest()}")
print(f"fixture_counter_values_sha256={hashlib.sha256(('\\n'.join(stable_samples)).encode()).hexdigest()}")
for line in stable_samples:
    print(f"fixture_counter_sample={line}")
print("fixture_team_metadata=true")
PY

cat >"$workdir/sitecustomize.py" <<'PY'
import sys
import traceback
from opentelemetry.sdk.trace import Span

_original_set_attribute = Span.set_attribute

def _capture_ended_span_write(self, key, value):
    if not self.is_recording():
        frames = traceback.extract_stack(limit=18)
        rendered = "".join(traceback.format_list(frames[-10:]))
        print("ENDED_SPAN_CALLSITE\n" + rendered, file=sys.stderr)
    return _original_set_attribute(self, key, value)

Span.set_attribute = _capture_ended_span_write
PY

run_case() {
  local name=$1 image=$2
  docker run -d --rm --name "$name" --network none \
    -p 127.0.0.1:4010:4000 \
    -e LITELLM_MASTER_KEY=qa-master \
    -e LITELLM_OTEL_V2=true \
    -e LITELLM_OTEL_INTEGRATION_ENABLE_METRICS=true \
    -e LITELLM_OTEL_INTEGRATION_ENABLE_EVENTS=false \
    -e OTEL_EXPORTER=console \
    -e PYTHONPATH=/tmp/qa-hooks \
    -v "$workdir/config.yaml:/tmp/config.yaml:ro" \
    -v "$workdir/provider.py:/tmp/provider.py:ro" \
    -v "$workdir/prom_fixture.py:/tmp/prom_fixture.py:ro" \
    -v "$workdir/sitecustomize.py:/tmp/qa-hooks/sitecustomize.py:ro" \
    "$image" --config /tmp/config.yaml --host 0.0.0.0 --port 4000 >/dev/null

  for _ in $(seq 1 60); do
    if docker exec "$name" python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:4000/health/readiness", timeout=1)' >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  docker exec -d "$name" python /tmp/provider.py >/dev/null
  sleep 1
  docker exec "$name" python /tmp/prom_fixture.py >"$workdir/$name.fixture" 2>&1
  cat "$workdir/$name.fixture" >&2
  local runtime_sha
  runtime_sha=$(docker exec "$name" python -c 'import hashlib, importlib.util; s=importlib.util.find_spec("litellm.integrations.opentelemetry"); p=s.origin; print(hashlib.sha256(open(p,"rb").read()).hexdigest())')
  echo "runtime_otel_path=$(docker exec "$name" python -c 'import importlib.util; print(importlib.util.find_spec("litellm.integrations.opentelemetry").origin)')" >&2
  echo "runtime_otel_sha256=$runtime_sha" >&2
  echo "runtime_otel_logger_path=$(docker exec "$name" python -c 'import importlib.util; print(importlib.util.find_spec("litellm.integrations.otel.logger").origin)')" >&2
  echo "runtime_otel_logger_sha256=$(docker exec "$name" python -c 'import hashlib, importlib.util; p=importlib.util.find_spec("litellm.integrations.otel.logger").origin; print(hashlib.sha256(open(p,"rb").read()).hexdigest())')" >&2
  if [[ "$name" == otel-qa-base && "$runtime_sha" != a0b304266e1d9a516e29a24e47ad340385525abd064ef3cda12e17a84121703d ]]; then
    echo "unexpected_base_runtime_sha=$runtime_sha" >&2
    return 1
  fi
  if [[ "$name" == otel-qa-guarded && "$runtime_sha" != 25fc3957e53e5ba129dc77e4d58e88728b99a2970729de11062d850f0b7b9ec8 ]]; then
    echo "unexpected_guarded_runtime_sha=$runtime_sha" >&2
    return 1
  fi
  docker exec "$name" python -c 'import urllib.request, json; req=urllib.request.Request("http://127.0.0.1:4000/v1/chat/completions", data=json.dumps({"model":"qa-unused","messages":[{"role":"user","content":"qa"}]}).encode(), headers={"Authorization":"Bearer qa-master","Content-Type":"application/json"}); status=urllib.request.urlopen(req, timeout=5).status; assert status == 200, status; print(status)' >"$workdir/$name.provider" 2>&1
  cat "$workdir/$name.provider" >&2
  sleep 3
  docker exec "$name" python -c 'from opentelemetry.sdk.trace import TracerProvider; from litellm.integrations.opentelemetry import OpenTelemetry; p=TracerProvider(); s=p.get_tracer("qa").start_span("team"); o=OpenTelemetry(tracer_provider=p); o.safe_set_attribute(s, "team.id", "qa-team"); assert s.attributes.get("team.id") == "qa-team"; s.end(); print("team_attribute_preserved=true")' >&2
  local body
  if ! body=$(docker exec "$name" python -c 'import urllib.request; req=urllib.request.Request("http://127.0.0.1:4000/metrics/", headers={"Authorization":"Bearer qa-master"}); r=urllib.request.urlopen(req, timeout=5); body=r.read(); assert r.status == 200 and body, r.status; print(body.decode(), end="")'); then
    echo "metrics_scrape_failed=$name" >&2
    docker logs "$name" >&2 || true
    return 1
  fi
  if [[ -z "$body" ]]; then
    echo "metrics_scrape_empty=$name" >&2
    return 1
  fi
  printf '%s\n' "$body" >"$workdir/$name.metrics"
  sed -n '1,30p' "$workdir/$name.metrics" | sed -E 's/(Authorization|api_key|token|prompt|messages)[^ ]*/[redacted]/Ig' >&2
  sleep 2
  docker logs "$name" >"$workdir/$name.log" 2>&1 || true
  local warning_count
  warning_count=$(grep -c "Setting attribute on ended span" "$workdir/$name.log" || true)
  awk '/^# (HELP|TYPE) /{print}' "$workdir/$name.metrics" | sort -u | sha256sum | awk -v n="$name" '{print "metric_metadata_sha256[" n "]=" $1}' >&2
  local sample_count fixture_sample_count
  sample_count=$(grep -E '^litellm_[a-zA-Z0-9_:]+([ {]|$)' "$workdir/$name.metrics" | wc -l | tr -d ' ')
  fixture_sample_count=$(sed -n 's/^fixture_metric_sample_count=//p' "$workdir/$name.fixture")
  if [[ -z "$fixture_sample_count" || "$fixture_sample_count" -eq 0 ]]; then
    echo "fixture_metric_sample_count_zero=$name" >&2
    return 1
  fi
  echo "metric_sample_count[$name]=$sample_count" >&2
  echo "fixture_metric_sample_count[$name]=$fixture_sample_count" >&2
  docker rm -f "$name" >/dev/null 2>&1 || true
  printf '%s\n' "$warning_count"
}

if ! baseline_warning_count=$(run_case otel-qa-base "$base_image" | tail -1); then
  exit 1
fi
echo "baseline_warning_count=$baseline_warning_count"
if [[ "$baseline_warning_count" -le 0 ]]; then
  echo "baseline_warning_not_reproduced=$baseline_warning_count" >&2
  exit 1
fi

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
        import hashlib
        if hashlib.sha256(path.read_bytes()).hexdigest() != "a0b304266e1d9a516e29a24e47ad340385525abd064ef3cda12e17a84121703d":
            raise SystemExit(f"unexpected base OTEL source: {path}")
        if needle not in text:
            raise SystemExit(f"guard insertion point not found: {path}")
        path.write_text(text.replace(needle, replacement, 1))
        break
else:
    raise SystemExit("installed LiteLLM source not found")

for root in sys.path:
    path = Path(root) / "litellm/integrations/otel/logger.py"
    if path.exists():
        text = path.read_text()
        import hashlib
        if hashlib.sha256(path.read_bytes()).hexdigest() != "53ea87fd204b58e2f75fbb3175e17538676a55b1edf3114241b57d9b02b356c8":
            raise SystemExit(f"unexpected base OTEL logger source: {path}")
        needle = "                    for key, value in bag.items():\n                        server_span.set_attribute(key, value)"
        replacement = "                    for key, value in bag.items():\n                        if is_recordable_span(server_span) and server_span.is_recording():\n                            server_span.set_attribute(key, value)"
        if needle not in text:
            raise SystemExit(f"logger guard insertion point not found: {path}")
        path.write_text(text.replace(needle, replacement, 1))
        break
else:
    raise SystemExit("installed LiteLLM OTEL logger source not found")

print("OTEL_SOURCE_IDENTITY")
try:
    from importlib.metadata import version
    for package in ("opentelemetry-api", "opentelemetry-sdk", "opentelemetry-instrumentation-asgi", "opentelemetry-instrumentation-fastapi"):
        try:
            print(f"{package}={version(package)}")
        except Exception:
            pass
except Exception:
    pass
PY
DOCKERFILE
docker build --build-arg BASE_IMAGE="$base_image" -t otel-qa-guarded "$workdir" >/dev/null
if ! guarded_warning_count=$(run_case otel-qa-guarded otel-qa-guarded | tail -1); then
  exit 1
fi
echo "guarded_warning_count=$guarded_warning_count"
if [[ "$guarded_warning_count" -ne 0 ]]; then
  echo "guarded_warning_persisted=$guarded_warning_count" >&2
  exit 1
fi

base_metadata=$(awk '/^# (HELP|TYPE) /{print}' "$workdir/otel-qa-base.metrics" | sort -u | sha256sum | awk '{print $1}')
guarded_metadata=$(awk '/^# (HELP|TYPE) /{print}' "$workdir/otel-qa-guarded.metrics" | sort -u | sha256sum | awk '{print $1}')
if [[ "$base_metadata" != "$guarded_metadata" ]]; then
  echo "metric_metadata_changed=true" >&2
  exit 1
fi
echo "metric_metadata_equal=true"
base_fixture_metadata=$(sed -n 's/^fixture_metric_metadata_sha256=//p' "$workdir/otel-qa-base.fixture")
guarded_fixture_metadata=$(sed -n 's/^fixture_metric_metadata_sha256=//p' "$workdir/otel-qa-guarded.fixture")
if [[ -z "$base_fixture_metadata" || "$base_fixture_metadata" != "$guarded_fixture_metadata" ]]; then
  echo "fixture_metric_metadata_changed=true" >&2
  exit 1
fi
echo "fixture_metric_metadata_equal=true"
base_counter_values=$(sed -n 's/^fixture_counter_values_sha256=//p' "$workdir/otel-qa-base.fixture")
guarded_counter_values=$(sed -n 's/^fixture_counter_values_sha256=//p' "$workdir/otel-qa-guarded.fixture")
if [[ -z "$base_counter_values" || "$base_counter_values" != "$guarded_counter_values" ]]; then
  echo "fixture_counter_values_changed=true" >&2
  exit 1
fi
echo "fixture_counter_values_equal=true"

for log in "$workdir"/*.log; do
  awk '/ENDED_SPAN_CALLSITE/{show=1; left=34} show && left-- > 0 {print}' "$log" \
    | sed -E 's/(Authorization|api_key|token|prompt|messages)[^ ]*/[redacted]/Ig' || true
done

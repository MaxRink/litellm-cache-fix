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
    -v "$workdir/provider.py:/tmp/provider.py:ro" \
    "$image" --config /tmp/config.yaml --host 0.0.0.0 --port 4000 >/dev/null

  for _ in $(seq 1 60); do
    if docker exec "$name" python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:4000/health/readiness", timeout=1)' >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  docker exec -d "$name" python /tmp/provider.py >/dev/null
  sleep 1
  docker exec "$name" python -c 'import hashlib, importlib.util; s=importlib.util.find_spec("litellm.integrations.opentelemetry"); p=s.origin; print(f"runtime_otel_path={p}"); print(f"runtime_otel_sha256={hashlib.sha256(open(p,"rb").read()).hexdigest()}")' >&2
  docker exec "$name" python -c 'import urllib.request, json; req=urllib.request.Request("http://127.0.0.1:4000/v1/chat/completions", data=json.dumps({"model":"qa-unused","messages":[{"role":"user","content":"qa"}]}).encode(), headers={"Authorization":"Bearer qa-master","Content-Type":"application/json"}); urllib.request.urlopen(req, timeout=5)' >/dev/null
  docker exec "$name" python -c 'from opentelemetry.sdk.trace import TracerProvider; from litellm.integrations.opentelemetry import OpenTelemetry; p=TracerProvider(); s=p.get_tracer("qa").start_span("team"); o=OpenTelemetry(tracer_provider=p); o.safe_set_attribute(s, "team.id", "qa-team"); assert s.attributes.get("team.id") == "qa-team"; s.end(); print("team_attribute_preserved=true")' >&2
  if ! docker exec "$name" python -c 'import urllib.request; req=urllib.request.Request("http://127.0.0.1:4000/metrics/", headers={"Authorization":"Bearer qa-master"}); r=urllib.request.urlopen(req, timeout=5); body=r.read(); assert r.status == 200 and body, r.status' \
    >"$workdir/$name.metrics"; then
    echo "metrics_scrape_failed=$name" >&2
    docker logs "$name" >&2 || true
    return 1
  fi
  sleep 2
  docker logs "$name" >"$workdir/$name.log" 2>&1 || true
  local warning_count
  warning_count=$(grep -c "Setting attribute on ended span" "$workdir/$name.log" || true)
  awk '/^# (HELP|TYPE) /{print}' "$workdir/$name.metrics" | sort -u | sha256sum | awk -v n="$name" '{print "metric_metadata_sha256[" n "]=" $1}' >&2
  local sample_count
  sample_count=$(grep -E '^litellm_[a-zA-Z0-9_:]+([ {]|$)' "$workdir/$name.metrics" | wc -l | tr -d ' ')
  if [[ "$sample_count" -eq 0 ]]; then
    echo "metric_sample_count_zero=$name" >&2
    return 1
  fi
  echo "metric_sample_count[$name]=$sample_count" >&2
  docker rm -f "$name" >/dev/null 2>&1 || true
  printf '%s\n' "$warning_count"
}

if ! baseline_warning_count=$(run_case otel-qa-base "$base_image" | tail -1); then
  exit 1
fi
echo "baseline_warning_count=$baseline_warning_count"

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

# Diagnostic-only overlay: retain the original SDK behavior while recording
# the sanitized caller stack for ended-span writes. No attribute keys/values
# or request data are emitted.
for root in sys.path:
    path = Path(root) / "opentelemetry/sdk/trace/__init__.py"
    if path.exists():
        text = path.read_text()
        needle = "    def set_attribute(self, key: str, value: types.AttributeValue) -> None:\n"
        replacement = needle + "        if not self.is_recording():\n            import sys, traceback\n            print('ENDED_SPAN_CALLSITE\\n' + ''.join(traceback.format_stack(limit=30)), file=sys.stderr)\n"
        if needle not in text:
            raise SystemExit(f"SDK set_attribute insertion point not found: {path}")
        path.write_text(text.replace(needle, replacement, 1))
        break
else:
    raise SystemExit("installed OpenTelemetry SDK source not found")

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
for root in sys.path:
    for source_root in (Path(root) / "opentelemetry/instrumentation", Path(root) / "litellm"):
        if not source_root.exists():
            continue
        for path in sorted(source_root.rglob("*.py")):
            if "/site-packages/litellm/" not in str(path) and "opentelemetry/instrumentation" not in str(path):
                continue
            lines = path.read_text(errors="replace").splitlines(keepends=True)
            rewritten = []
            for lineno, line in enumerate(lines, 1):
                if ".set_attribute(" in line:
                    indent = line[: len(line) - len(line.lstrip())]
                    rewritten.append(f'{indent}print("OTEL_CALLSITE {path}:{lineno}", file=sys.stderr)\n')
                rewritten.append(line)
            path.write_text("".join(rewritten))

for root in sys.path:
    path = Path(root) / "opentelemetry/instrumentation/asgi/__init__.py"
    if path.exists():
        text = path.read_text()
        for expression, replacement in (
            ("                    receive_span.set_attribute(\n", "                    print(\"ASGI_SET_ATTRIBUTE_RECEIVE\", file=sys.stderr)\n                    receive_span.set_attribute(\n"),
            ("                send_span.set_attribute(\"asgi.event.type\", message[\"type\"])\n", "                print(\"ASGI_SET_ATTRIBUTE_SEND\", file=sys.stderr)\n                send_span.set_attribute(\"asgi.event.type\", message[\"type\"])\n"),
            ("                        current_span.set_attribute(key, value)\n", "                        print(\"ASGI_SET_ATTRIBUTE_SERVER\", file=sys.stderr)\n                        current_span.set_attribute(key, value)\n"),
        ):
            text = text.replace(expression, replacement, 1)
        path.write_text(text)
        break
PY
DOCKERFILE
docker build --build-arg BASE_IMAGE="$base_image" -t otel-qa-guarded "$workdir" >/dev/null
if ! guarded_warning_count=$(run_case otel-qa-guarded otel-qa-guarded | tail -1); then
  exit 1
fi
echo "guarded_warning_count=$guarded_warning_count"

base_metadata=$(awk '/^# (HELP|TYPE) /{print}' "$workdir/otel-qa-base.metrics" | sort -u | sha256sum | awk '{print $1}')
guarded_metadata=$(awk '/^# (HELP|TYPE) /{print}' "$workdir/otel-qa-guarded.metrics" | sort -u | sha256sum | awk '{print $1}')
if [[ "$base_metadata" != "$guarded_metadata" ]]; then
  echo "metric_metadata_changed=true" >&2
  exit 1
fi
echo "metric_metadata_equal=true"

for log in "$workdir"/*.log; do
  awk '/ENDED_SPAN_CALLSITE/{show=1; left=34} show && left-- > 0 {print}' "$log" \
    | sed -E 's/(Authorization|api_key|token|prompt|messages)[^ ]*/[redacted]/Ig' || true
done

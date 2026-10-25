#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fake_bin="$(mktemp -d)"
trap 'rm -rf "$fake_bin"' EXIT

cat >"$fake_bin/gh" <<'EOF'
#!/usr/bin/env bash
case "${FAKE_FILES:-}" in
  docs) printf '%s\n' README.md docs/usage.md ;;
  backend) printf '%s\n' litellm/router.py ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$fake_bin/gh"

run_case() {
  local expected="$1" files="$2" output
  output="$(PATH="$fake_bin:$PATH" FAKE_FILES="$files" CATEGORY=backend REPO=x PR_NUMBER=1 CHANGED_FILE_COUNT=2 bash "$root/.github/scripts/detect_changes.sh")"
  grep -q "decision=$expected" <<<"$output"
}

run_case skip docs
run_case run backend
output="$(PATH="$fake_bin:$PATH" CATEGORY=backend bash "$root/.github/scripts/detect_changes.sh")"
grep -q 'decision=run' <<<"$output"
echo "detect_changes behavioral cases passed"

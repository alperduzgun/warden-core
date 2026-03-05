#!/usr/bin/env bash
# CI Simulator entrypoint
# 1. Waits for Ollama (CPU-throttled)
# 2. Pulls qwen2.5-coder:3b if missing (persisted in named volume)
# 3. Creates a writable workspace with config patched to reach Docker Ollama
# 4. Runs warden scan — exposes benchmark_timeout → budget=20 → skipped cascade

set -euo pipefail

OLLAMA_URL="${OLLAMA_SERVICE_URL:-http://ollama:11434}"
SCAN_TARGET="${SCAN_TARGET:-src/warden/llm/}"
MODEL="qwen2.5-coder:3b"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Warden CI Simulator"
echo "  Ollama : ${OLLAMA_URL}  (CPU limit: 0.5 cores)"
echo "  Model  : ${MODEL}"
echo "  Target : ${SCAN_TARGET}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Wait for Ollama ──────────────────────────────────────────────────────
echo ""
echo "[1/3] Waiting for Ollama..."
until python3 -c "
import urllib.request, sys
try:
    urllib.request.urlopen('${OLLAMA_URL}', timeout=3)
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
    printf "."
    sleep 2
done
echo " up!"

# ── 2. Pull model if not present ────────────────────────────────────────────
echo ""
echo "[2/3] Checking model ${MODEL}..."
INSTALLED=$(python3 -c "
import urllib.request, json
r = urllib.request.urlopen('${OLLAMA_URL}/api/tags')
data = json.loads(r.read())
print('\n'.join(m['name'] for m in data.get('models',[])))
" 2>/dev/null || echo "")

if echo "${INSTALLED}" | grep -qF "${MODEL}"; then
    echo "      ${MODEL} already present — skipping pull"
else
    echo "      Pulling ${MODEL} (large download — stored in named volume for reuse)..."
    python3 -u -c "
import urllib.request, json, sys
req = urllib.request.Request(
    '${OLLAMA_URL}/api/pull',
    data=json.dumps({'name': '${MODEL}', 'stream': True}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with urllib.request.urlopen(req) as resp:
    for line in resp:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            status = d.get('status', '')
            total  = d.get('total', 0)
            done   = d.get('completed', 0)
            if total and done:
                pct = int(done * 100 / total)
                print(f'\r      {status} {pct}%', end='', flush=True)
            elif status:
                print(f'\r      {status}        ', end='', flush=True)
        except Exception:
            pass
    print()
"
    echo "      Pull complete."
fi

# Warm up inference engine — mirrors the CI warmup step in ci.yml.
# ollama list / /api/tags passing does NOT mean the generation pipeline is
# initialised (thread pools, KV cache, computation graphs).  The first real
# inference call would otherwise bear the cold-start cost and potentially
# exceed the benchmark timeout.  Generating 1 token here fully initialises
# the execution engine; keep_alive=-1 keeps the model resident.
echo "      Warming up inference engine (1 token)..."
python3 -c "
import urllib.request, json, sys
req = urllib.request.Request(
    '${OLLAMA_URL}/api/generate',
    data=json.dumps({'model': '${MODEL}', 'prompt': 'hi', 'stream': False,
                     'options': {'num_predict': 1}, 'keep_alive': -1}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()
    print('      ready.')
except Exception as e:
    print(f'      (warmup failed: {e} — proceeding anyway)')
    sys.exit(0)
" 2>&1

# ── 3. Build writable CI workspace ──────────────────────────────────────────
echo ""
echo "[3/3] Preparing workspace..."
CI_WS="/ci-workspace"
mkdir -p "${CI_WS}/.warden"

# Patch Ollama URL so warden talks to the Docker service, not localhost
sed "s|http://localhost:11434|${OLLAMA_URL}|g" \
    /source/.warden/config.yaml > "${CI_WS}/.warden/config.yaml"

# Copy source into workspace (symlinks trigger warden's path-traversal guard)
echo "      Copying source tree (this takes a few seconds)..."
cp -r /source/src "${CI_WS}/src"

# Carry over baseline if it exists (for incremental scan behaviour)
if [ -f /source/.warden/baseline.json ]; then
    cp /source/.warden/baseline.json "${CI_WS}/.warden/baseline.json"
fi

echo "      Ollama URL patched → ${OLLAMA_URL}"
echo "      Scan root          → ${CI_WS}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Starting warden scan (watch for benchmark_failed / llm_skipped)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd "${CI_WS}"
exec warden scan "${SCAN_TARGET}" --level standard --no-preflight

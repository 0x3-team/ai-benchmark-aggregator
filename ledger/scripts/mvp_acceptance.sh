#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# MVP acceptance test for the benchmark-ledger CLI.
#
# Exercises:
#   1. init-db            — create ledger tables
#   2. seed-registry      — load curated benchmarks, models, official sources
#   3. ingest (fake)      — run ingestion once (creates snapshot + claims)
#   4. ingest (fake)      — run again to verify idempotency (0 new claims)
#   5. claims list        — show stored claims
#   6. review queue       — show claims needing review (e.g. unmatched models)
#
# Usage:  bash scripts/mvp_acceptance.sh
# ---------------------------------------------------------------------------
set -euo pipefail

LEDGER_CLI="benchmark-ledger"
FIXTURE="tests/fixtures/fake_source.json"

# Resolve project root (script location → parent)
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/.." && pwd)"
cd "$PROJECT"

echo "=== MVP Acceptance — $(date) ==="
echo "Project: $PROJECT"
echo ""

# ---- helpers ---------------------------------------------------------------
run() {
    echo "> $*"
    "$@"
    echo ""
}

check_grep() {
    local label="$1" pattern="$2"
    if grep -q "$pattern" /dev/stdin 2>/dev/null; then
        :  # matched via pipe
    elif echo "$3" | grep -q "$pattern" 2>/dev/null; then
        :  # matched via arg
    else
        echo "FAIL: $label — expected /$pattern/ not found"
        exit 1
    fi
}

# Ensure the CLI is on PATH (prefer project .venv)
if ! command -v "$LEDGER_CLI" &>/dev/null; then
    if [ -f "$PROJECT/.venv/bin/$LEDGER_CLI" ]; then
        PATH="$PROJECT/.venv/bin:$PATH"
    else
        echo "FATAL: $LEDGER_CLI not found on PATH or in .venv/bin"
        exit 1
    fi
fi

# Clean slate — remove old DB & snapshots
rm -f data/benchmark_ledger.db
rm -rf data/snapshots
mkdir -p data/snapshots

# ---------------------------------------------------------------------- STEP 1
echo "────────────────────────────────────────────────────────────────────────"
echo "STEP 1: init-db"
echo "────────────────────────────────────────────────────────────────────────"
run $LEDGER_CLI init-db

# ---------------------------------------------------------------------- STEP 2
echo "────────────────────────────────────────────────────────────────────────"
echo "STEP 2: seed-registry"
echo "────────────────────────────────────────────────────────────────────────"
output=$($LEDGER_CLI seed-registry 2>&1)
echo "$output"
# Expect all categories populated
echo ""
grep -qE "benchmarks.*[1-9]" <<<"$output" || { echo "FAIL: no benchmarks seeded"; exit 1; }
grep -qE "models.*[1-9]" <<<"$output" || { echo "FAIL: no models seeded"; exit 1; }
grep -qE "sources.*[1-9]" <<<"$output" || { echo "FAIL: no sources seeded"; exit 1; }
echo "  ✓ Registry seeded"

# ---------------------------------------------------------------------- STEP 3
echo "────────────────────────────────────────────────────────────────────────"
echo "STEP 3: ingest (first run — fake source with fixture)"
echo "────────────────────────────────────────────────────────────────────────"
output=$($LEDGER_CLI ingest --source fake_local_fixture --fixture "$FIXTURE" 2>&1)
echo "$output"
echo ""
grep -q "Snapshots created: [1-9]" <<<"$output" || { echo "FAIL: no snapshot created"; exit 1; }
grep -q "Claims inserted: [1-9]" <<<"$output" || { echo "FAIL: no claims inserted"; exit 1; }
echo "  ✓ First ingest OK"

# ---------------------------------------------------------------------- STEP 4
echo "────────────────────────────────────────────────────────────────────────"
echo "STEP 4: ingest (idempotency — second run must reuse snapshot + no new claims)"
echo "────────────────────────────────────────────────────────────────────────"
output=$($LEDGER_CLI ingest --source fake_local_fixture --fixture "$FIXTURE" 2>&1)
echo "$output"
echo ""
grep -q "Snapshots reused: [1-9]" <<<"$output" || { echo "FAIL: snapshot should be reused"; exit 1; }
grep -q "Claims inserted: 0" <<<"$output" || { echo "FAIL: second ingest inserted claims (not idempotent)"; exit 1; }
grep -q "Claims unchanged: [1-9]" <<<"$output" || { echo "FAIL: expected unchanged claims"; exit 1; }
echo "  ✓ Second ingest is idempotent"

# ---------------------------------------------------------------------- STEP 5
echo "────────────────────────────────────────────────────────────────────────"
echo "STEP 5: claims list"
echo "────────────────────────────────────────────────────────────────────────"
output=$($LEDGER_CLI claims list --limit 10 2>&1)
echo "$output"
echo ""
grep -q "Fake-Model-1" <<<"$output" || { echo "FAIL: Fake-Model-1 not found in claims"; exit 1; }
grep -q "42.50" <<<"$output" || { echo "FAIL: score 42.50 not found in claims"; exit 1; }
echo "  ✓ Claims listed"

# ---------------------------------------------------------------------- STEP 6
echo "────────────────────────────────────────────────────────────────────────"
echo "STEP 6: review queue"
echo "────────────────────────────────────────────────────────────────────────"
output=$($LEDGER_CLI review queue 2>&1)
echo "$output"
echo ""
# Unknown-Model-X has no alias → should be in review queue
grep -q "Unknown-Model-X" <<<"$output" || { echo "FAIL: Unknown-Model-X should be in review queue"; exit 1; }
echo "  ✓ Review queue populated"

# ---------------------------------------------------------------------- DONE
echo "========================================"
echo "MVP ACCEPTANCE — ALL CHECKS PASSED"
echo "========================================"

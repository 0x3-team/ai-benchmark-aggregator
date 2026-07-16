#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Containment acceptance smoke for the benchmark-ledger CLI.
#
# This script deliberately uses a temporary database and proves the safe
# current behavior: versioned empty-db initialization, registry seeding,
# read-only migration status, and fail-closed ingestion.  It never removes a
# user's data directory, contacts a source, or creates a benchmark claim.
#
# Usage: bash scripts/mvp_acceptance.sh
# ---------------------------------------------------------------------------
set -euo pipefail

LEDGER_CLI="benchmark-ledger"
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/.." && pwd)"
cd "$PROJECT"

if ! command -v "$LEDGER_CLI" &>/dev/null; then
    if [ -x "$PROJECT/.venv/bin/$LEDGER_CLI" ]; then
        PATH="$PROJECT/.venv/bin:$PATH"
    else
        echo "FATAL: benchmark-ledger not found on PATH or in .venv/bin" >&2
        exit 1
    fi
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
export DATABASE_URL="sqlite:///$work_dir/benchmark_ledger.db"
export SNAPSHOT_LOCAL_ROOT="$work_dir/snapshots"

echo "=== Ledger containment smoke — $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "Temporary database: $DATABASE_URL"

echo "> $LEDGER_CLI init-db"
"$LEDGER_CLI" init-db

echo "> $LEDGER_CLI seed-registry"
seed_output="$("$LEDGER_CLI" seed-registry 2>&1)"
echo "$seed_output"
grep -qE "benchmarks.*[1-9]" <<<"$seed_output"
grep -qE "models.*[1-9]" <<<"$seed_output"
grep -qE "sources.*[1-9]" <<<"$seed_output"

echo "> $LEDGER_CLI db preflight"
preflight_output="$("$LEDGER_CLI" db preflight 2>&1)"
echo "$preflight_output"
grep -q '"kind": "current"' <<<"$preflight_output"
grep -q '"integrity_ok": true' <<<"$preflight_output"

echo "> $LEDGER_CLI ingest --source fake_local_fixture --dry-run (expected block)"
if blocked_output="$("$LEDGER_CLI" ingest --source fake_local_fixture --dry-run 2>&1)"; then
    echo "$blocked_output"
    echo "FAIL: quarantined fixture ingestion unexpectedly succeeded" >&2
    exit 1
fi
echo "$blocked_output"
grep -q "Ingestion blocked:" <<<"$blocked_output"
grep -q "Ingestion complete\." <<<"$blocked_output" && {
    echo "FAIL: blocked ingestion reported completion" >&2
    exit 1
}

echo "CONTAINMENT SMOKE PASSED"

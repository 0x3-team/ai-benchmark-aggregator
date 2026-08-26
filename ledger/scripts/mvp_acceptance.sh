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

HERE="$(cd "$(dirname "$0")" && pwd -P)"
PROJECT="$(cd "$HERE/.." && pwd -P)"
cd "$PROJECT"

# Resolve the repository virtualenv executable by absolute path and require it.
# Never fall back to a PATH lookup: a ``benchmark-ledger`` found earlier on
# PATH could impersonate the intended CLI (CWE-427/CWE-426).  Fail closed if
# the pinned binary is missing, not a regular file, or a symbolic link (a link
# could redirect to an arbitrary executable) so an impostor can never run.
LEDGER_CLI="$PROJECT/.venv/bin/benchmark-ledger"
if [ -L "$LEDGER_CLI" ]; then
    echo "FATAL: benchmark-ledger at $LEDGER_CLI must be a regular file, not a symbolic link" >&2
    exit 1
fi
if [ ! -f "$LEDGER_CLI" ] || [ ! -x "$LEDGER_CLI" ]; then
    echo "FATAL: benchmark-ledger not found at $LEDGER_CLI (repo virtualenv is required)" >&2
    exit 1
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
# Canonicalize the temp directory to its fully physical path (no symlink
# ancestors).  On macOS, /var is a symlink to /private/var, and init-db's
# descriptor-relative O_NOFOLLOW parent walk fails closed when any ancestor is
# a symlink.  Resolving to the physical path keeps the SQLite URL symlink-free.
work_dir="$(cd "$work_dir" && pwd -P)"
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

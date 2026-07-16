# Operational persistence and runtime-composition rehearsal

**Status:** local/disposable acceptance only  
**Last updated:** 2026-07-15  
**Applies to:** DATA-09 and CFG-01

This runbook validates durable operational truth and inert dependency
composition. It does not start a scheduler, fetch a source, send a
notification, provision a provider, migrate the protected legacy database,
publish an artifact, or activate Official mode.

## Containment first

- Never point any migration or target test at
  `ledger/data/benchmark_ledger.db`. Record its SHA-256, byte size, nanosecond
  mtime, inode, and sidecar set before and after the rehearsal.
- Use a fresh temporary SQLite file or a PostgreSQL database whose name
  visibly contains `test`, `disposable`, or `phase2b`. PostgreSQL tests refuse
  an unmarked target and require a separate reset acknowledgement.
- Keep local PostgreSQL on a Unix socket without a TCP listener where
  practical. Do not record passwords, provider credentials, source tokens, or
  object bytes in test output.
- An unset PostgreSQL target is an honest skip, not DATA-09 target evidence.
  Do not describe SQLite, a mock, or static SQL rendering as PostgreSQL proof.

## Fresh SQLite proof

Run from the ledger virtual environment:

```bash
cd ledger
.venv/bin/pytest -q \
  tests/test_operational_persistence.py \
  tests/test_operational_persistence_adversarial.py \
  tests/test_runtime_dependencies.py \
  tests/test_ingestion_runner_transactions.py
```

The accepted result must demonstrate:

1. a fresh database upgrades through the single Alembic head
   `0010_operational_persistence`, with no foreign-key violations;
2. deterministic cycle/job intents replay exactly while conflicting replay
   fails, and terminalization requires complete attempts and outputs;
3. lease acquisition, heartbeat, takeover, and accepted-current attempt commits
   enforce ownership, interval, monotonic fencing, trusted-clock, and
   database-clock expiry rules;
4. source attempt and source-check receipt composition is atomic and binds the
   exact contract, certification, snapshot, extraction, job, attempt, and
   fencing identities;
5. operational rows are immutable except for the guarded current-lease
   projection, and incident, work-item, identity, notification, and outbox
   chains reject stale/branched/underfilled/late changes;
6. unsupported terminal receipt types fail explicitly rather than persisting
   opaque references; and
7. default/disabled and dry-run ingestion call no network, DNS, storage,
   scheduler, incident, rate-limit, or run-row side effects. Adapters retain no
   HTTP client.

## Real PostgreSQL proof

The PostgreSQL suites reset only the marked disposable database they receive:

```bash
export TEST_POSTGRESQL_URL='postgresql+psycopg://USER@/benchmark_disposable_phase2b?host=/absolute/socket&port=PORT'
export TEST_POSTGRESQL_ALLOW_RESET=1
cd ledger
.venv/bin/pytest -q \
  tests/test_operational_persistence_postgresql.py \
  tests/test_postgresql_portability.py
```

In addition to the SQLite invariants, require real concurrent-writer evidence
for monotonic fencing and one-current-lease behavior. Strict status must fail
when a reviewed constraint, deferral flag, index, user trigger/function, role
boundary, or any internal FK referential-integrity trigger is changed or
disabled. A forged application clock and a transaction that reaches commit
after the database lease expiry must both be rejected.

The bounded role result is intentional: ingestion can write only its reviewed
scheduler/evidence/operational surfaces and the current lease projection;
governance has benchmark/subject/identity/review-work authority only, not
source certification, claim review, or publication authority. Artifact and
audit remain non-writing, and the public SPA has no database role.

## Static and regression gates

```bash
cd ledger
.venv/bin/python -m compileall -q app tests
.venv/bin/alembic heads
.venv/bin/pytest -q

cd ..
npm run verify:official-artifact
npm run typecheck
npm test -- --run
npm run build
git diff --check
```

`alembic heads` must print exactly `0010_operational_persistence (head)`. The
frontend verifier must continue to accept only the tracked unavailable
artifact; operational tables and contracts are never frontend inputs.

## Target cleanup receipt

After target tests, verify both disposable databases have zero public tables
and relations and that no test roles or schemas remain. Stop only the
PostgreSQL process started for this rehearsal, remove only its exact temporary
root, and verify:

- its process and Unix socket are absent;
- its chosen TCP port refuses connections, even if the server was configured
  socket-only; and
- the protected SQLite fingerprint and empty sidecar set are unchanged.

Do not use broad process kills, temporary-directory globs, downgrade, delete,
or reset commands as recovery.

## Stop conditions

Stop and preserve the failing receipt if the protected database changes, an
immutable operational row can be updated/deleted, a stale or expired worker
can commit, a terminal denominator can be underfilled, a source receipt can
detach from its exact evidence, strict PostgreSQL status accepts disabled
enforcement, ordinary construction enables a side effect, or cleanup cannot
account for every disposable resource. Do not weaken the invariant or enable a
live capability to make the rehearsal pass.

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
from typing import Optional
import unicodedata

import typer

from app.config import get_settings
from app.discovery import (
    DiscoveryControllerError,
    DiscoveryManifestError,
    DiscoveryPlannerError,
    build_discovery_status,
    build_fixture_connectors,
    load_manifest,
    plan_dispositions,
    render_status_markdown,
    run_discovery_cycle,
)
from app.db.operational_repositories import OperationalPersistenceError
from app.runtime.dependencies import (
    RuntimeDependencyError,
    contained_runtime_dependencies,
)
from app.scheduling.slots import ScheduleSlotError, slot_for_ordinal
from app.backup import (
    LocalRecoveryStore,
    RecoveryContractError,
    RecoveryError,
    RecoveryPartialFailure,
    create_checkpoint_with_driver,
    create_sqlite_checkpoint,
    restore_checkpoint_with_driver,
    restore_sqlite_checkpoint,
    validate_checkpoint_manifest,
)
from app.db.engine import get_session, init_db
from app.db.migrate import (
    DatabaseMigrationError,
    inspect_database,
    migrate_legacy_copy,
    redacted_database_url,
    supports_copy_migration,
    upgrade_postgresql_database,
)
from app.db import repositories as repo
from app.ingestion.runner import IngestionBlockedError, run_ingestion
from app.ingestion.safe_fetch import SafeFetchError
from app.registry.seed_loader import seed_registry
from app.recovery_io import (
    RecoveryFileError,
    read_canonical_recovery_document,
    read_json_object,
    reserve_new_recovery_output,
)
from app.reporting.legacy_inventory import (
    LegacyInventoryError,
    build_legacy_inventory_report,
    canonical_legacy_inventory_json,
)
from app.reporting.coverage_census import (
    CoverageCensusError,
    build_coverage_census,
    canonical_coverage_json,
    render_coverage_markdown,
)
from app.reporting.identity_review import build_identity_review_csv


def _terminal_render(value: object) -> str:
    """Render one durable value for the terminal without leaking control bytes.

    Only the *terminal projection* changes; durable values are never rewritten.
    ``str(value)`` is taken first so dicts/lists render through their repr
    (which still contains the raw characters), then:

    - literal backslash renders visibly as ``\\\\`` (two characters),
    - LF/CR/TAB/BS/FF render as the short visible escapes ``\\n``/``\\r``/
      ``\\t``/``\\b``/``\\f`` (a source embedded newline is text, not layout),
    - every other Unicode ``Cc`` or ``Cf`` code point (ESC, BEL, DEL, C1
      CSI/OSC, bidi controls, …) renders as a lowercase visible escape:
      ``\\xNN`` when <= 0xff, ``\\uNNNN`` when <= 0xffff, ``\\UNNNNNNNN``
      otherwise.

    Ordinary printable Unicode passes through unchanged.
    """
    text = str(value)
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif _is_control_or_format(code):
            if code <= 0xFF:
                out.append(f"\\x{code:02x}")
            elif code <= 0xFFFF:
                out.append(f"\\u{code:04x}")
            else:
                out.append(f"\\U{code:08x}")
        else:
            out.append(ch)
    return "".join(out)


def _is_control_or_format(code: int) -> bool:
    """True for Unicode Cc (control) and Cf (format) categories."""
    return unicodedata.category(chr(code)) in ("Cc", "Cf")


app = typer.Typer(name="benchmark-ledger", help="Official benchmark result capture ledger", no_args_is_help=True)
claims_app = typer.Typer(help="Inspect result claims")
snapshots_app = typer.Typer(help="Inspect source snapshots")
review_app = typer.Typer(help="Review queue")
aliases_app = typer.Typer(help="Alias management")
db_app = typer.Typer(
    help="Inspect versioned SQLite/PostgreSQL schemas and run explicit recovery-safe upgrades"
)
reports_app = typer.Typer(help="Read-only reconciliation reports; never changes ledger evidence")
coverage_app = typer.Typer(
    help="Read-only bounded coverage census; configuration and legacy facts are not certification"
)
recovery_app = typer.Typer(
    help=(
        "Create authority-free recovery checkpoints and new-target restore receipts; "
        "never authorizes cutover or Official publication"
    )
)
discovery_app = typer.Typer(
    help=(
        "Fixture-only discovery planning and candidate reconnaissance; "
        "never certifies sources or writes claims"
    )
)
app.add_typer(claims_app, name="claims")
app.add_typer(snapshots_app, name="snapshots")
app.add_typer(review_app, name="review")
app.add_typer(aliases_app, name="aliases")
app.add_typer(db_app, name="db")
app.add_typer(reports_app, name="reports")
app.add_typer(coverage_app, name="coverage")
app.add_typer(recovery_app, name="recovery")
app.add_typer(discovery_app, name="discovery")


def _default_registry_dir() -> Path:
    return Path(__file__).resolve().parent / "registry"


def _recovery_utc_now() -> str:
    """Return the operator clock at canonical second precision."""

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_existing_recovery_root(path: Path) -> Path:
    """Admit an existing regular directory without following a symlink."""

    candidate = Path(path).expanduser()
    try:
        metadata = candidate.lstat()
    except OSError:
        raise RecoveryFileError(
            "Recovery source-object root must be an existing regular directory."
        ) from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RecoveryFileError(
            "Recovery source-object root must be an existing regular directory."
        )
    try:
        return candidate.resolve(strict=True)
    except OSError:
        raise RecoveryFileError(
            "Recovery source-object root cannot be resolved safely."
        ) from None


def _admit_local_recovery_target_root(path: Path) -> Path:
    """Admit a missing or regular local root without following a symlink parent."""

    candidate = Path(path).expanduser()
    try:
        if candidate.exists() or candidate.is_symlink():
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RecoveryFileError(
                    "Recovery target-object root is not a regular directory."
                )
        else:
            parent = candidate.parent
            metadata = parent.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RecoveryFileError(
                    "Recovery target-object parent is not a regular directory."
                )
    except RecoveryFileError:
        raise
    except OSError:
        raise RecoveryFileError(
            "Recovery target-object root cannot be admitted safely."
        ) from None
    return candidate.resolve(strict=False)


def _admit_recovery_output_outside_roots(
    path: Path,
    *,
    protected_roots: tuple[Path, ...],
    relational_target: Path | None = None,
) -> Path:
    """Resolve one output without allowing it to mutate protected inputs.

    The final parent must already be a regular, non-symlink directory because
    output reservation is intentionally create-exclusive. Resolving that
    admitted parent also makes an ancestor symlink into a protected root
    visible to the containment comparison.
    """

    candidate = Path(path).expanduser()
    if candidate.name in {"", ".", ".."}:
        raise RecoveryFileError("Recovery contract output path is invalid.")
    try:
        parent_metadata = candidate.parent.lstat()
        if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(
            parent_metadata.st_mode
        ):
            raise RecoveryFileError(
                "Recovery contract output parent is not a regular directory."
            )
        resolved = candidate.parent.resolve(strict=True) / candidate.name
    except RecoveryFileError:
        raise
    except OSError:
        raise RecoveryFileError(
            "Recovery contract output path cannot be admitted safely."
        ) from None

    for root in protected_roots:
        canonical_root = Path(root).resolve(strict=False)
        if resolved == canonical_root or canonical_root in resolved.parents:
            raise RecoveryFileError(
                "Recovery contract output cannot mutate a protected recovery root."
            )
    if relational_target is not None:
        target = Path(relational_target).expanduser().resolve(strict=False)
        if resolved == target:
            raise RecoveryFileError(
                "Recovery receipt output cannot be the relational restore target."
            )
    return resolved


def _recovery_failure_payload(exc: BaseException) -> dict[str, object]:
    """Map failures to bounded telemetry without retaining locators or secrets."""

    payload: dict[str, object] = {
        "availability": "recovery_evidence_only",
        "status": "failed_closed",
        "successReceiptEmitted": False,
        "partialStateMayRemain": True,
    }
    if isinstance(exc, RecoveryPartialFailure):
        payload.update(
            {
                "reasonCode": exc.reason_code,
                "phase": exc.phase,
                "completedObjectCount": exc.completed_object_count,
                "relationalTargetCreated": exc.relational_target_created,
            }
        )
    elif isinstance(exc, RecoveryFileError):
        payload["reasonCode"] = "RECOVERY_FILE_REJECTED"
    elif isinstance(exc, RecoveryContractError):
        payload["reasonCode"] = "RECOVERY_CONTRACT_REJECTED"
    elif isinstance(exc, RecoveryError):
        payload["reasonCode"] = "RECOVERY_CONTRACT_OR_TARGET_REJECTED"
    else:
        payload["reasonCode"] = "RECOVERY_INTERNAL_FAILURE"
    return payload


def _fail_recovery(exc: BaseException) -> None:
    typer.echo(json.dumps(_recovery_failure_payload(exc), sort_keys=True), err=True)
    raise typer.Exit(code=2) from None


def _checkpoint_success_payload(checkpoint: dict[str, object]) -> dict[str, object]:
    trigger = checkpoint["triggerCycle"]
    manifest = checkpoint["manifest"]
    objects = checkpoint["objectManifest"]
    if not isinstance(trigger, dict) or not isinstance(manifest, dict) or not isinstance(objects, dict):
        raise RecoveryFileError("Recovery checkpoint output has an invalid shape.")
    return {
        "availability": "recovery_evidence_only",
        "status": "completed",
        "checkpointId": checkpoint["checkpointId"],
        "contentSha256": manifest["contentSha256"],
        "triggerCycleId": trigger["cycleId"],
        "objectReferenceCount": objects["objectReferenceCount"],
        "authorizesCutover": False,
        "authorizesPublication": False,
        "provesProductionRpoRto": False,
    }


def _restore_success_payload(receipt: dict[str, object]) -> dict[str, object]:
    checkpoint = receipt["checkpoint"]
    target = receipt["target"]
    objects = receipt["objectRestore"]
    assessment = receipt["recoveryAssessment"]
    manifest = receipt["manifest"]
    if not all(
        isinstance(value, dict)
        for value in (checkpoint, target, objects, assessment, manifest)
    ):
        raise RecoveryFileError("Recovery restore receipt has an invalid shape.")
    return {
        "availability": "recovery_evidence_only",
        "status": "completed",
        "receiptId": receipt["receiptId"],
        "contentSha256": manifest["contentSha256"],
        "checkpointId": checkpoint["checkpointId"],
        "targetId": target["targetId"],
        "durationMs": receipt["durationMs"],
        "objectReferenceCount": objects["objectReferenceCount"],
        "rpoStatus": assessment["rpoStatus"],
        "rtoStatus": assessment["rtoStatus"],
        "providerIndependenceStatus": assessment["providerIndependenceStatus"],
        "cutoverAuthorized": False,
        "authorizesPublication": False,
    }


def _postgresql_recovery_url(environment_name: str) -> str:
    value = os.environ.get(environment_name)
    if not value:
        raise RecoveryFileError(
            "Required PostgreSQL recovery connection environment is unavailable."
        )
    return value


@recovery_app.command("checkpoint-sqlite")
def recovery_checkpoint_sqlite(
    database_source: Path = typer.Option(
        ...,
        "--database-source",
        help="Explicit existing SQLite source; DATABASE_URL is never consulted",
    ),
    trigger: Path = typer.Option(
        ...,
        "--trigger",
        help="Exact terminal scheduled-cycle-v1 JSON captured in the source database",
    ),
    primary_root: Path = typer.Option(
        ...,
        "--primary-root",
        help="Existing local root containing source snapshot bytes",
    ),
    primary_domain_id: str = typer.Option(..., "--primary-domain-id"),
    recovery_root: Path = typer.Option(
        ...,
        "--recovery-root",
        help="Distinct local root for immutable recovery copies",
    ),
    recovery_domain_id: str = typer.Option(..., "--recovery-domain-id"),
    manifest_output: Path = typer.Option(
        ...,
        "--manifest-output",
        help="New mode-0600 canonical checkpoint path; never overwritten",
    ),
) -> None:
    """Checkpoint one explicit SQLite source into a distinct local recovery map."""

    reservation = None
    try:
        trigger_document = read_json_object(trigger)
        primary = LocalRecoveryStore(
            _require_existing_recovery_root(primary_root),
            failure_domain_id=primary_domain_id,
        )
        recovery = LocalRecoveryStore(
            _admit_local_recovery_target_root(recovery_root),
            failure_domain_id=recovery_domain_id,
        )
        admitted_output = _admit_recovery_output_outside_roots(
            manifest_output,
            protected_roots=(primary.root, recovery.root),
        )
        reservation = reserve_new_recovery_output(admitted_output)
        checkpoint = create_sqlite_checkpoint(
            database_path=Path(database_source),
            trigger_cycle=trigger_document,
            primary_store=primary,
            recovery_store=recovery,
            created_at=_recovery_utc_now(),
        )
        reservation.publish(checkpoint)
        typer.echo(json.dumps(_checkpoint_success_payload(checkpoint), sort_keys=True))
    except typer.Exit:
        raise
    except BaseException as exc:
        _fail_recovery(exc)
    finally:
        if reservation is not None:
            reservation.close()


@recovery_app.command("checkpoint-postgresql")
def recovery_checkpoint_postgresql(
    trigger: Path = typer.Option(..., "--trigger"),
    primary_root: Path = typer.Option(..., "--primary-root"),
    primary_domain_id: str = typer.Option(..., "--primary-domain-id"),
    recovery_root: Path = typer.Option(..., "--recovery-root"),
    recovery_domain_id: str = typer.Option(..., "--recovery-domain-id"),
    inspection_target_id: str = typer.Option(..., "--inspection-target-id"),
    manifest_output: Path = typer.Option(..., "--manifest-output"),
) -> None:
    """Checkpoint PostgreSQL through fixed PG16 tools and one fresh inspection DB.

    Connection material is accepted only through
    ``LEDGER_RECOVERY_POSTGRESQL_SOURCE_URL`` and
    ``LEDGER_RECOVERY_POSTGRESQL_INSPECTION_URL``. The command does not create,
    drop, clean, or reset a database.
    """

    reservation = None
    try:
        from app.backup.postgresql_driver import (
            PostgreSQLBackupRestoreDriver,
            PostgreSQLConnectionSpec,
        )

        trigger_document = read_json_object(trigger)
        primary = LocalRecoveryStore(
            _require_existing_recovery_root(primary_root),
            failure_domain_id=primary_domain_id,
        )
        recovery = LocalRecoveryStore(
            _admit_local_recovery_target_root(recovery_root),
            failure_domain_id=recovery_domain_id,
        )
        admitted_output = _admit_recovery_output_outside_roots(
            manifest_output,
            protected_roots=(primary.root, recovery.root),
        )
        reservation = reserve_new_recovery_output(admitted_output)
        source = PostgreSQLConnectionSpec.from_url(
            _postgresql_recovery_url("LEDGER_RECOVERY_POSTGRESQL_SOURCE_URL")
        )
        inspection_target = PostgreSQLConnectionSpec.from_url(
            _postgresql_recovery_url(
                "LEDGER_RECOVERY_POSTGRESQL_INSPECTION_URL"
            )
        )
        driver = PostgreSQLBackupRestoreDriver()
        checkpoint = create_checkpoint_with_driver(
            driver=driver,
            database_source=source,
            trigger_cycle=trigger_document,
            primary_store=primary,
            recovery_store=recovery,
            created_at=_recovery_utc_now(),
            inspection_target=inspection_target,
            inspection_target_id=inspection_target_id,
        )
        reservation.publish(checkpoint)
        typer.echo(json.dumps(_checkpoint_success_payload(checkpoint), sort_keys=True))
    except typer.Exit:
        raise
    except BaseException as exc:
        _fail_recovery(exc)
    finally:
        if reservation is not None:
            reservation.close()


@recovery_app.command("restore-sqlite")
def recovery_restore_sqlite(
    checkpoint_manifest: Path = typer.Option(..., "--checkpoint-manifest"),
    recovery_root: Path = typer.Option(..., "--recovery-root"),
    recovery_domain_id: str = typer.Option(..., "--recovery-domain-id"),
    restore_root: Path = typer.Option(..., "--restore-root"),
    restore_domain_id: str = typer.Option(..., "--restore-domain-id"),
    database_target: Path = typer.Option(
        ...,
        "--database-target",
        help="New SQLite file path; an existing or attempted target is never reused",
    ),
    target_id: str = typer.Option(..., "--target-id"),
    receipt_output: Path = typer.Option(
        ...,
        "--receipt-output",
        help="New mode-0600 canonical restore-receipt path; never overwritten",
    ),
) -> None:
    """Restore a published SQLite checkpoint to new relational and object targets."""

    reservation = None
    try:
        checkpoint = read_canonical_recovery_document(checkpoint_manifest)
        validate_checkpoint_manifest(checkpoint)
        recovery = LocalRecoveryStore(
            _require_existing_recovery_root(recovery_root),
            failure_domain_id=recovery_domain_id,
        )
        restore = LocalRecoveryStore(
            _admit_local_recovery_target_root(restore_root),
            failure_domain_id=restore_domain_id,
        )
        admitted_output = _admit_recovery_output_outside_roots(
            receipt_output,
            protected_roots=(recovery.root, restore.root),
            relational_target=database_target,
        )
        reservation = reserve_new_recovery_output(admitted_output)
        receipt = restore_sqlite_checkpoint(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=restore,
            database_target=Path(database_target),
            target_id=target_id,
        )
        reservation.publish(receipt)
        typer.echo(json.dumps(_restore_success_payload(receipt), sort_keys=True))
    except typer.Exit:
        raise
    except BaseException as exc:
        _fail_recovery(exc)
    finally:
        if reservation is not None:
            reservation.close()


@recovery_app.command("restore-postgresql")
def recovery_restore_postgresql(
    checkpoint_manifest: Path = typer.Option(..., "--checkpoint-manifest"),
    recovery_root: Path = typer.Option(..., "--recovery-root"),
    recovery_domain_id: str = typer.Option(..., "--recovery-domain-id"),
    restore_root: Path = typer.Option(..., "--restore-root"),
    restore_domain_id: str = typer.Option(..., "--restore-domain-id"),
    target_id: str = typer.Option(..., "--target-id"),
    receipt_output: Path = typer.Option(..., "--receipt-output"),
) -> None:
    """Restore PostgreSQL to an already-created fresh DB from a fixed env URL.

    ``LEDGER_RECOVERY_POSTGRESQL_RESTORE_URL`` is the only connection input.
    The command never creates, drops, cleans, or resets a database and the
    emitted receipt never authorizes runtime cutover.
    """

    reservation = None
    try:
        from app.backup.postgresql_driver import (
            PostgreSQLBackupRestoreDriver,
            PostgreSQLConnectionSpec,
        )

        checkpoint = read_canonical_recovery_document(checkpoint_manifest)
        validate_checkpoint_manifest(checkpoint)
        recovery = LocalRecoveryStore(
            _require_existing_recovery_root(recovery_root),
            failure_domain_id=recovery_domain_id,
        )
        restore = LocalRecoveryStore(
            _admit_local_recovery_target_root(restore_root),
            failure_domain_id=restore_domain_id,
        )
        admitted_output = _admit_recovery_output_outside_roots(
            receipt_output,
            protected_roots=(recovery.root, restore.root),
        )
        reservation = reserve_new_recovery_output(admitted_output)
        target = PostgreSQLConnectionSpec.from_url(
            _postgresql_recovery_url("LEDGER_RECOVERY_POSTGRESQL_RESTORE_URL")
        )
        driver = PostgreSQLBackupRestoreDriver()
        receipt = restore_checkpoint_with_driver(
            driver=driver,
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=restore,
            relational_target=target,
            target_id=target_id,
        )
        reservation.publish(receipt)
        typer.echo(json.dumps(_restore_success_payload(receipt), sort_keys=True))
    except typer.Exit:
        raise
    except BaseException as exc:
        _fail_recovery(exc)
    finally:
        if reservation is not None:
            reservation.close()


@app.command("init-db")
def init_db_cmd() -> None:
    """Initialize a new empty database through versioned migrations."""
    try:
        init_db()
    except DatabaseMigrationError as exc:
        typer.echo(f"Database initialization blocked: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Initialized database: {redacted_database_url(get_settings().database_url)}")


@db_app.command("status")
def db_status() -> None:
    """Read the migration/integrity state without opening the database for write."""
    database_url = get_settings().database_url
    try:
        status = inspect_database(database_url).as_dict()
    except DatabaseMigrationError as exc:
        typer.echo(f"Database status unavailable: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    status["database_url"] = redacted_database_url(database_url)
    typer.echo(json.dumps(status, sort_keys=True))


@db_app.command("preflight")
def db_preflight() -> None:
    """Run the read-only safety checks required before a copied-DB rehearsal."""
    database_url = get_settings().database_url
    try:
        status = inspect_database(database_url)
    except DatabaseMigrationError as exc:
        typer.echo(f"Database preflight blocked: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    payload = status.as_dict()
    payload["database_url"] = redacted_database_url(database_url)
    typer.echo(json.dumps(payload, sort_keys=True))
    eligible_versioned_state = status.kind == "versioned_but_not_head" and (
        status.path is None or supports_copy_migration(status)
    )
    if (
        not status.integrity_ok
        or status.foreign_key_violations != 0
        or (
            status.kind not in {"empty", "current", "legacy_unversioned"}
            and not eligible_versioned_state
        )
    ):
        raise typer.Exit(code=2)


@db_app.command("migrate")
def db_migrate(
    backup_dir: Path = typer.Option(..., "--backup-dir", file_okay=False, help="Directory for the verified pre-migration SQLite backup"),
) -> None:
    """Migrate an integrity-clean disposable legacy or known-versioned copy."""
    database_url = get_settings().database_url
    try:
        receipt = migrate_legacy_copy(database_url, backup_dir=backup_dir)
    except DatabaseMigrationError as exc:
        typer.echo(f"Database migration blocked: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    payload = receipt.as_dict()
    payload["database_url"] = redacted_database_url(database_url)
    typer.echo(json.dumps(payload, sort_keys=True))


@db_app.command("upgrade-postgresql")
def db_upgrade_postgresql(
    expected_revision: str = typer.Option(
        ...,
        "--expected-revision",
        help="Exact known Alembic revision observed during PostgreSQL preflight",
    ),
) -> None:
    """Advance one explicit PostgreSQL target under the migration lock.

    This is not a SQLite-to-PostgreSQL copy tool and does not create a backup.
    Operators must retain separately verified recovery evidence before invoking
    it against a populated disposable or authorized target.
    """
    database_url = get_settings().database_url
    try:
        status = upgrade_postgresql_database(
            database_url,
            expected_revision=expected_revision,
        )
    except DatabaseMigrationError as exc:
        typer.echo(f"PostgreSQL upgrade blocked: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    payload = status.as_dict()
    payload["database_url"] = redacted_database_url(database_url)
    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("seed-registry")
def seed_registry_cmd(
    benchmarks: Path = typer.Option(_default_registry_dir() / "benchmarks.yaml", exists=True),
    models: Path = typer.Option(_default_registry_dir() / "models.yaml", exists=True),
    sources: Path = typer.Option(_default_registry_dir() / "official_sources.yaml", exists=True),
) -> None:
    """Reconcile curated registry YAML files through immutable source revisions."""
    init_db()
    with get_session() as session:
        counts = seed_registry(
            session,
            benchmarks_path=benchmarks,
            models_path=models,
            sources_path=sources,
            retire_missing=True,
        )
    typer.echo(f"Seeded: {counts}")


@app.command("ingest")
def ingest_cmd(
    all_sources: bool = typer.Option(False, "--all", help="Ingest all active sources"),
    source: Optional[str] = typer.Option(None, "--source", help="Official source id"),
    benchmark: Optional[str] = typer.Option(None, "--benchmark", help="Benchmark id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    fail_fast: bool = typer.Option(False, "--fail-fast"),
    fixture: Optional[Path] = typer.Option(None, "--fixture", help="Fixture path for fake adapter"),
) -> None:
    """Run ingestion for selected sources."""
    if not all_sources and not source and not benchmark:
        raise typer.BadParameter("Provide --all, --source, or --benchmark")

    # Ingestion never initializes or migrates its target.  Inspecting first is
    # deliberately read-only so a refused source or unavailable fetch cannot
    # leave a newly created ledger behind.
    try:
        database_status = inspect_database(get_settings().database_url)
    except DatabaseMigrationError as exc:
        label = "Dry-run blocked" if dry_run else "Ingestion blocked"
        typer.echo(f"{label}: {_terminal_render(exc)}", err=True)
        raise typer.Exit(code=2) from exc
    if database_status.kind != "current":
        label = "Dry-run blocked" if dry_run else "Ingestion blocked"
        typer.echo(
            f"{label}: an existing, integrity-clean current ledger database is required; "
            f"{'dry-run' if dry_run else 'ingest'} will not initialize or migrate one.",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        with get_session() as session:
            summary = run_ingestion(
                session,
                source_id=source,
                benchmark_id=benchmark,
                dry_run=dry_run,
                fail_fast=fail_fast,
                fixture_path=fixture,
            )
    except IngestionBlockedError as exc:
        typer.echo(f"Ingestion blocked: {_terminal_render(exc)}", err=True)
        raise typer.Exit(code=2) from exc
    except SafeFetchError as exc:
        # SafeFetchError details are intentionally not operator output: the
        # stable code is enough to diagnose the bounded failure and cannot
        # echo a URL, provider response, or credential-like value.
        typer.echo(f"Ingestion blocked: safe fetch failed closed ({_terminal_render(exc.code)})", err=True)
        raise typer.Exit(code=2) from None
    terminal = "Ingestion complete." if summary.status == "completed" else f"Ingestion {_terminal_render(summary.status)}."
    typer.echo(terminal + (" (dry-run)" if dry_run else ""))
    typer.echo(f"Sources checked: {summary.sources_checked}")
    typer.echo(f"Snapshots created: {summary.snapshots_created}")
    typer.echo(f"Snapshots reused: {summary.snapshots_reused}")
    typer.echo(f"Claims extracted: {summary.claims_extracted}")
    typer.echo(f"Claims inserted: {summary.claims_inserted}")
    typer.echo(f"Claims unchanged: {summary.claims_unchanged}")
    typer.echo(f"Claims needing review: {summary.claims_needing_review}")
    typer.echo(f"Errors: {len(summary.errors)}")
    for e in summary.errors:
        typer.echo(f"  - {_terminal_render(e)}")
    if dry_run and summary.dry_run_claims:
        typer.echo(f"Sample claims ({min(5, len(summary.dry_run_claims))}):")
        for c in summary.dry_run_claims[:5]:
            typer.echo(
                f"  {_terminal_render(c['model_raw'])} | {_terminal_render(c['score_raw'])} "
                f"| {_terminal_render(c['capture_status'])}"
            )
    if summary.status != "completed":
        raise typer.Exit(code=1)


@claims_app.command("list")
def claims_list(benchmark: Optional[str] = typer.Option(None, "--benchmark"), limit: int = 20) -> None:
    with get_session() as session:
        rows = repo.list_claims(session, benchmark_id=benchmark, limit=limit)
        for c in rows:
            typer.echo(
                f"{_terminal_render(c.id)} | {_terminal_render(c.benchmark_id or c.benchmark_raw)} "
                f"| {_terminal_render(c.model_raw)} | {_terminal_render(c.score_raw)} "
                f"| {_terminal_render(c.capture_status)}"
            )


@claims_app.command("show")
def claims_show(claim_id: str) -> None:
    with get_session() as session:
        c = repo.get_claim(session, claim_id)
        if not c:
            raise typer.Exit(code=1)
        projection = repo.get_claim_review_projection(session, c)
        typer.echo(f"id: {_terminal_render(c.id)}")
        typer.echo(f"model_raw: {_terminal_render(c.model_raw)}")
        typer.echo(f"captured_model_entity_id: {_terminal_render(c.model_entity_id)}")
        typer.echo(f"effective_model_entity_id: {_terminal_render(projection.model_entity_id)}")
        if projection.chain_error:
            typer.echo(f"review_chain_error: {_terminal_render(projection.chain_error)}")
        typer.echo(f"benchmark_raw: {_terminal_render(c.benchmark_raw)}")
        typer.echo(f"benchmark_id: {_terminal_render(c.benchmark_id)}")
        typer.echo(f"score_raw: {_terminal_render(c.score_raw)}")
        typer.echo(f"capture_status: {_terminal_render(c.capture_status)}")
        typer.echo(f"evidence_location: {_terminal_render(c.evidence_location)}")
        typer.echo(f"source_snapshot_id: {_terminal_render(c.source_snapshot_id)}")
        typer.echo(f"official_source_id: {_terminal_render(c.official_source_id)}")


@snapshots_app.command("list")
def snapshots_list(source: str = typer.Option(..., "--source")) -> None:
    with get_session() as session:
        rows = repo.list_snapshots(session, source)
        for s in rows:
            typer.echo(f"{s.id} | {s.content_hash[:12]} | {s.captured_at} | {s.raw_content_uri}")


def _render_review_queue_item_reason(c, projection) -> list[str]:
    """Build the raw review-reason list for one claim; preserves prior reasons.

    Returns *unrendered* strings; the single terminal render happens once in
    ``_render_review_queue_item`` so an escaped value is never re-escaped.
    """
    reason = []
    if projection.chain_error:
        reason.append(f"review chain invalid: {projection.chain_error}")
    elif projection.model_entity_id is None:
        reason.append("model_entity_id is null")
    elif c.model_entity_id is None:
        reason.append("model identity resolved by append-only review decision")
    if c.capture_status == "needs_review":
        reason.append("capture_status=needs_review")
    return reason


def _render_review_queue_item(c, projection) -> None:
    reason = _render_review_queue_item_reason(c, projection)
    typer.echo(f"Claim ID: {_terminal_render(c.id)}")
    typer.echo(f"Benchmark: {_terminal_render(c.benchmark_raw)}")
    typer.echo(f"Model raw: {_terminal_render(c.model_raw)}")
    typer.echo(f"Score raw: {_terminal_render(c.score_raw)}")
    typer.echo(f"Reason: {_terminal_render(', '.join(reason)) or 'unspecified'}")
    typer.echo(f"Evidence: {_terminal_render(c.evidence_location)}")
    typer.echo("---")


@review_app.command("queue")
def review_queue(limit: int = 50, cursor: Optional[str] = None) -> None:
    """Print a bounded review-queue page with explicit continuation.

    ``cursor`` is an opaque token returned as ``Next cursor`` on a prior page;
    pass it back to fetch the following page.  Output reasons and the queue
    review containment rules are unchanged.
    """
    with get_session() as session:
        try:
            page = repo.list_review_queue_page(
                session,
                limit=limit,
                cursor=cursor,
            )
        except ValueError as exc:
            typer.echo(f"Invalid review queue cursor: {_terminal_render(exc)}", err=True)
            raise typer.Exit(code=2) from exc
        if not page.items and not page.next_cursor:
            # A truly empty queue (no claims at all).  This is distinct from a
            # bounded page that happens to hold zero eligible items while more
            # rows remain — that case falls through to the continuation line.
            typer.echo("Review queue empty.")
            return
        for item in page.items:
            _render_review_queue_item(item.claim, item.projection)
        if page.next_cursor:
            typer.echo(f"Scanned: {page.scanned} | Next cursor: {_terminal_render(page.next_cursor)}")
            typer.echo(
                "Continuation available; pass the cursor above as --cursor to fetch the next page."
            )
        elif page.exhausted:
            typer.echo("Scanned: {page.scanned} | Review queue exhausted (no more claims).".format(page=page))


@review_app.command("export-csv")
def review_export_csv(
    limit: str = typer.Option("50", "--limit"),
    cursor: Optional[str] = typer.Option(None, "--cursor"),
) -> None:
    """Export one bounded identity-review page as deterministic CSV.

    The export is a read-only decision-support view.  It uses the same strict
    limit and cursor validation as ``review queue`` and never changes claims,
    review decisions, or publication decisions.
    """
    try:
        # Keep the raw option as text until this guarded parser.  If Typer
        # annotated this option as ``int``, Click would emit its own value
        # (and potentially echo the supplied token) before our fixed,
        # redacted error boundary could run.
        if isinstance(limit, str):
            if not limit or not limit.isascii() or not limit.isdecimal():
                raise ValueError("limit must be an ASCII decimal")
            parsed_limit = int(limit, 10)
        elif isinstance(limit, int) and not isinstance(limit, bool):
            # Direct Python callers of this command are kept strict too.
            parsed_limit = limit
        else:
            raise ValueError("limit must be an ASCII decimal")
        with get_session() as session:
            page = repo.list_review_queue_page(
                session,
                limit=parsed_limit,
                cursor=cursor,
            )
            # Build all bytes while the read-only session is still open, but do
            # not write anything until serialization has completed successfully.
            payload = build_identity_review_csv(page)
    except ValueError:
        # Do not echo the caller's limit/cursor or repository parser details.
        # In particular, an opaque cursor may contain sensitive data in a
        # future implementation.  Invalid requests have one stable response.
        typer.echo(
            "Identity review CSV export blocked: invalid limit or cursor.",
            err=True,
        )
        raise typer.Exit(code=2) from None
    # Write the already-complete bytes directly.  Going through ``typer.echo``
    # would permit a text wrapper to normalize the required CRLF delimiters.
    output = getattr(sys.stdout, "buffer", None)
    if output is None:  # pragma: no cover - defensive for unusual embedders
        sys.stdout.write(payload.decode("utf-8"))
    else:
        output.write(payload)
        output.flush()


@review_app.command("show")
def review_show(claim_id: str) -> None:
    claims_show(claim_id)


@review_app.command("auto-verify-matched")
def review_auto_verify() -> None:
    """Permanently blocked during Official-mode containment."""
    typer.echo(
        "review auto-verify-matched is disabled during Official-mode containment; "
        "bulk mapping must never promote validation, capture status, or publication.",
        err=True,
    )
    raise typer.Exit(code=2)


#: Hard bound for the persisted actor string: ClaimReviewDecision.actor is
#: String(128), so an overlong principal must fail closed rather than truncate.
_ACTOR_MAX_BYTES = 128


def _os_principal() -> str:
    """Resolve the trusted invoking OS principal for audit provenance.

    Returns a canonical value ``posix:euid=<decimal>;name=<name>`` built from
    the numeric effective UID and the passwd database record for that exact
    UID.  The passwd lookup is performed lazily inside this helper so the full
    CLI stays importable on a platform without ``pwd``; only map-model fails
    closed.  ``USER``/``LOGNAME``/``getpass`` are never consulted.  The passwd
    record's ``pw_uid`` must exactly equal the requested effective UID, the
    name must be nonempty and free of control/format characters, and the
    canonical value must fit the persisted ``String(128)`` field.  Any failure
    raises one stable ``LookupError`` so the caller fails closed before a DB
    session or write.
    """
    if not hasattr(os, "geteuid"):
        raise LookupError("no trusted local principal available on this platform")
    euid = os.geteuid()
    try:
        import pwd
    except ImportError:
        raise LookupError("no trusted local principal available on this platform") from None
    try:
        record = pwd.getpwuid(euid)
    except KeyError:
        raise LookupError(f"no passwd entry for effective uid {euid}") from None
    if record.pw_uid != euid:
        raise LookupError(
            f"passwd record uid mismatch for effective uid {euid}"
        ) from None
    name = record.pw_name
    if not isinstance(name, str) or not name:
        raise LookupError("passwd principal name is empty") from None
    if any(_is_control_or_format(ord(ch)) for ch in name):
        raise LookupError("passwd principal name contains control or format characters") from None
    actor = f"posix:euid={euid};name={name}"
    if len(actor.encode("utf-8")) > _ACTOR_MAX_BYTES:
        raise LookupError("passwd principal exceeds the persisted actor field bound") from None
    return actor


@review_app.command("map-model")
def review_map_model(
    claim_id: str,
    model_entity_id: str,
) -> None:
    """Append a manual model-identity decision without promoting the claim.

    The persisted actor is bound to the invoking OS principal (never a
    caller-supplied value), so audit provenance cannot be forged via --actor
    or environment variables.
    """
    try:
        actor = _os_principal()
    except LookupError as exc:
        typer.echo(f"Review mapping blocked: {_terminal_render(exc)}", err=True)
        raise typer.Exit(code=2) from exc
    try:
        with get_session() as session:
            decision = repo.append_manual_model_mapping(
                session,
                result_claim_id=claim_id,
                model_entity_id=model_entity_id,
                actor=actor,
            )
            decision_id = decision.id
    except (ValueError, repo.ClaimReviewChainError) as exc:
        typer.echo(f"Review mapping blocked: {_terminal_render(exc)}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        f"Recorded manual model mapping {_terminal_render(claim_id)} -> "
        f"{_terminal_render(model_entity_id)} "
        f"as review decision {_terminal_render(decision_id)}; "
        "captured claim and validation status are unchanged."
    )

@review_app.command("mark-human-verified")
def review_human(claim_id: str) -> None:
    """Retained only to fail closed for callers of the legacy shortcut."""
    del claim_id
    typer.echo(
        "review mark-human-verified is disabled during Official-mode containment; "
        "a governed validation-review decision workflow is required before any status promotion.",
        err=True,
    )
    raise typer.Exit(code=2)


@reports_app.command("legacy-inventory")
def reports_legacy_inventory() -> None:
    """Print a deterministic, read-only legacy/candidate reconciliation report."""
    # Opening a missing SQLite URL through SQLAlchemy would create an empty
    # database. Inspect it first through the migration service's read-only URI
    # so this diagnostic command cannot create, initialize, or upgrade one.
    try:
        status = inspect_database(get_settings().database_url)
    except DatabaseMigrationError as exc:
        typer.echo(f"Legacy inventory blocked: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if status.kind != "current":
        typer.echo(
            "Legacy inventory blocked: an existing, integrity-clean current ledger database is required; "
            "this read-only report will not initialize or migrate one.",
            err=True,
        )
        raise typer.Exit(code=2)
    with get_session() as session:
        try:
            report = build_legacy_inventory_report(session)
        except LegacyInventoryError:
            # One fixed terminal-safe refusal, exit 2.  Never interpolate the
            # exception (its text can carry raw DB/cap/input detail).
            typer.echo("Legacy inventory refused: report exceeds the bounded resource limits.", err=True)
            raise typer.Exit(code=2)
    typer.echo(canonical_legacy_inventory_json(report))


@coverage_app.command("status")
def coverage_status(
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Output format: json or markdown",
    ),
    registry_dir: Path = typer.Option(
        _default_registry_dir(),
        "--registry-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Directory containing the executable YAML registries",
    ),
    universe: Path = typer.Option(
        _default_registry_dir() / "coverage_universe.yaml",
        "--universe",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Versioned bounded Coverage Universe manifest",
    ),
    database_url: Optional[str] = typer.Option(
        None,
        "--database-url",
        help="Optional file-backed SQLite evidence target; defaults to DATABASE_URL",
    ),
) -> None:
    """Print a deterministic census without creating, migrating, or changing a ledger."""
    normalized_format = output_format.strip().lower()
    if normalized_format not in {"json", "markdown"}:
        # Keep this validation failure stable across Typer/Click versions.
        # Rendering a BadParameter through the framework can produce styled
        # usage-only output in newer releases, hiding the actionable message.
        typer.echo("--format must be either 'json' or 'markdown'", err=True)
        raise typer.Exit(code=2)

    try:
        report = build_coverage_census(
            registry_dir=registry_dir,
            universe_path=universe,
            database_url=database_url or get_settings().database_url,
        )
    except CoverageCensusError as exc:
        typer.echo(f"Coverage census unavailable: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    if normalized_format == "json":
        typer.echo(canonical_coverage_json(report))
    else:
        typer.echo(render_coverage_markdown(report), nl=False)

    # A blocked census is still a valid, complete operator report.  Exit 1 so
    # automation cannot mistake known collisions or quarantined database state
    # for launch readiness; malformed/unreadable inputs use exit 2 above.
    if report["readiness"] != "ready":
        raise typer.Exit(code=1)


def _fail_discovery(exc: BaseException) -> None:
    # Never surface raw exception text: the fixture/parser/database boundary is
    # operator-controlled input, and a malformed manifest or hostile fixture can
    # embed private paths, filenames, provider details, secrets, or terminal
    # control bytes in an exception message. Emit exactly one bounded JSON
    # object with a stable generic detail so stderr stays parseable and free of
    # raw bytes. Exit 2 preserves the existing fail-closed contract.
    typer.echo(
        json.dumps(
            {
                "availability": "candidate_only",
                "status": "failed_closed",
                "reasonCode": "DISCOVERY_INPUT_REJECTED",
                "detail": "Discovery input was rejected.",
            },
            sort_keys=True,
        ),
        err=True,
    )
    raise typer.Exit(code=2) from None


def _load_discovery_inputs(fixture_root: Path, slot_ordinal: int):
    try:
        manifest = load_manifest(fixture_root)
        slot = slot_for_ordinal(
            manifest.anchor_utc, manifest.cadence_seconds, slot_ordinal
        )
    except (DiscoveryManifestError, ScheduleSlotError) as exc:
        _fail_discovery(exc)
    return manifest, slot


@discovery_app.command("plan")
def discovery_plan(
    fixture_root: Path = typer.Option(
        ...,
        "--fixture-root",
        help="Directory holding manifest.json, coverage-universe.json, and targets/",
    ),
    slot_ordinal: int = typer.Option(
        ..., "--slot-ordinal", min=0, help="Deterministic slot ordinal from the anchor"
    ),
) -> None:
    """Print one slot's planner dispositions without touching any database."""
    manifest, slot = _load_discovery_inputs(fixture_root, slot_ordinal)
    try:
        dispositions = plan_dispositions(
            manifest.targets,
            anchor_utc=manifest.anchor_utc,
            cadence_seconds=manifest.cadence_seconds,
            slot=slot,
        )
    except DiscoveryPlannerError as exc:
        _fail_discovery(exc)
    counts = {"due": 0, "not_due": 0, "blocked": 0}
    for disposition in dispositions:
        counts[disposition.due_disposition] += 1
    document = {
        "schemaVersion": "1.0.0",
        "policyVersion": "discovery-plan-v1",
        "availability": "candidate_only",
        "cycleId": slot.cycle_id(
            manifest.environment,
            manifest.lane,
            manifest.schedule_policy_revision_id,
        ),
        "environment": manifest.environment,
        "lane": manifest.lane,
        "schedulePolicyRevisionId": manifest.schedule_policy_revision_id,
        "mode": manifest.mode,
        "slot": slot.slot_document(),
        "counts": {
            "expectedTargetCount": len(dispositions),
            "dueCount": counts["due"],
            "notDueCount": counts["not_due"],
            "blockedCount": counts["blocked"],
        },
        "targets": [
            {
                "targetRevisionId": disposition.target_revision_id,
                "targetId": disposition.target_id,
                "dueDisposition": disposition.due_disposition,
                "dispositionReasonCode": disposition.disposition_reason_code,
            }
            for disposition in dispositions
        ],
        "authority": {
            "classification": "candidate_reconnaissance_only",
            "certifiesSources": False,
            "authorizesCapture": False,
            "authorizesPublication": False,
            "frontendLoadable": False,
        },
    }
    typer.echo(json.dumps(document, indent=2, sort_keys=True))


@discovery_app.command("run")
def discovery_run(
    fixture_root: Path = typer.Option(
        ...,
        "--fixture-root",
        help="Directory holding manifest.json, coverage-universe.json, targets/, connectors/",
    ),
    slot_ordinal: int = typer.Option(
        ..., "--slot-ordinal", min=0, help="Deterministic slot ordinal from the anchor"
    ),
) -> None:
    """Run one deterministic fixture cycle against the configured DATABASE_URL.

    The cycle is idempotent: replaying the same manifest at the same slot
    re-derives identical intents and candidates.  Operational rows only —
    no snapshots, claims, source decisions, or certification writes.
    """
    manifest, slot = _load_discovery_inputs(fixture_root, slot_ordinal)
    try:
        connectors = build_fixture_connectors(contained_runtime_dependencies())
    except (RuntimeDependencyError, DiscoveryControllerError) as exc:
        _fail_discovery(exc)
    try:
        with get_session() as session:
            report = run_discovery_cycle(
                session,
                manifest=manifest,
                slot=slot,
                connectors=connectors,
                fixture_root=Path(fixture_root),
            )
    except (
        DiscoveryControllerError,
        DiscoveryPlannerError,
        OperationalPersistenceError,
    ) as exc:
        _fail_discovery(exc)
    typer.echo(json.dumps(report.to_document(), indent=2, sort_keys=True))
    if any(record.run_outcome == "failed" for record in report.records):
        raise typer.Exit(code=1)


@discovery_app.command("report")
def discovery_report(
    output_format: str = typer.Option(
        "json", "--format", help="Output format: json or markdown"
    ),
) -> None:
    """Print a read-only projection of discovery cycles and candidates."""
    normalized_format = output_format.strip().lower()
    if normalized_format not in {"json", "markdown"}:
        raise typer.BadParameter("--format must be either 'json' or 'markdown'.")
    with get_session() as session:
        document = build_discovery_status(session)
    if normalized_format == "json":
        typer.echo(json.dumps(document, indent=2, sort_keys=True))
    else:
        typer.echo(render_status_markdown(document), nl=False)


@aliases_app.command("add")
def aliases_add(
    entity_type: str = typer.Option(..., "--entity-type"),
    entity_id: str = typer.Option(..., "--entity-id"),
    alias: str = typer.Option(..., "--alias"),
) -> None:
    with get_session() as session:
        row = repo.add_alias(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            alias_text=alias,
            is_official_alias=False,
            alias_source="cli",
        )
        typer.echo(f"Alias added: {row.id} {entity_type}/{entity_id} <- {alias}")


@app.command("export-official-json")
def export_cmd(
    out: Path = typer.Option(
        Path("../src/data/official/export.from-ledger.json"),
        "--out",
        help="Retained for compatibility; Official export is unavailable during containment",
    )
) -> None:
    typer.echo(
        "Official export is disabled during containment. The SPA ships a tracked "
        "unavailable artifact until the governed publication/export gate is implemented.",
        err=True,
    )
    raise typer.Exit(code=2)


if __name__ == "__main__":
    app()

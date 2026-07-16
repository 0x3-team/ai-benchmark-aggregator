from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from typing import Optional

import typer

from app.config import get_settings
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
from app.registry.seed_loader import seed_registry
from app.recovery_io import (
    RecoveryFileError,
    read_canonical_recovery_document,
    read_json_object,
    reserve_new_recovery_output,
)
from app.reporting.legacy_inventory import (
    build_legacy_inventory_report,
    canonical_legacy_inventory_json,
)
from app.reporting.coverage_census import (
    CoverageCensusError,
    build_coverage_census,
    canonical_coverage_json,
    render_coverage_markdown,
)

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
app.add_typer(claims_app, name="claims")
app.add_typer(snapshots_app, name="snapshots")
app.add_typer(review_app, name="review")
app.add_typer(aliases_app, name="aliases")
app.add_typer(db_app, name="db")
app.add_typer(reports_app, name="reports")
app.add_typer(coverage_app, name="coverage")
app.add_typer(recovery_app, name="recovery")


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
    if dry_run:
        # A preview is not permission to initialize or migrate a database.
        # `inspect_database` uses SQLite read-only mode and refuses a missing,
        # invalid, or non-current target before the ORM can open it.
        try:
            database_status = inspect_database(get_settings().database_url)
        except DatabaseMigrationError as exc:
            typer.echo(f"Dry-run blocked: {exc}", err=True)
            raise typer.Exit(code=2) from exc
        if database_status.kind != "current":
            typer.echo(
                "Dry-run blocked: an existing, integrity-clean current ledger database is required; "
                "dry-run will not initialize or migrate one.",
                err=True,
            )
            raise typer.Exit(code=2)
    else:
        init_db()
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
        typer.echo(f"Ingestion blocked: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    terminal = "Ingestion complete." if summary.status == "completed" else f"Ingestion {summary.status}."
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
        typer.echo(f"  - {e}")
    if dry_run and summary.dry_run_claims:
        typer.echo(f"Sample claims ({min(5, len(summary.dry_run_claims))}):")
        for c in summary.dry_run_claims[:5]:
            typer.echo(f"  {c['model_raw']} | {c['score_raw']} | {c['capture_status']}")
    if summary.status != "completed":
        raise typer.Exit(code=1)


@claims_app.command("list")
def claims_list(benchmark: Optional[str] = typer.Option(None, "--benchmark"), limit: int = 20) -> None:
    with get_session() as session:
        rows = repo.list_claims(session, benchmark_id=benchmark, limit=limit)
        for c in rows:
            typer.echo(
                f"{c.id} | {c.benchmark_id or c.benchmark_raw} | {c.model_raw} | {c.score_raw} | {c.capture_status}"
            )


@claims_app.command("show")
def claims_show(claim_id: str) -> None:
    with get_session() as session:
        c = repo.get_claim(session, claim_id)
        if not c:
            raise typer.Exit(code=1)
        projection = repo.get_claim_review_projection(session, c)
        typer.echo(f"id: {c.id}")
        typer.echo(f"model_raw: {c.model_raw}")
        typer.echo(f"captured_model_entity_id: {c.model_entity_id}")
        typer.echo(f"effective_model_entity_id: {projection.model_entity_id}")
        if projection.chain_error:
            typer.echo(f"review_chain_error: {projection.chain_error}")
        typer.echo(f"benchmark_raw: {c.benchmark_raw}")
        typer.echo(f"benchmark_id: {c.benchmark_id}")
        typer.echo(f"score_raw: {c.score_raw}")
        typer.echo(f"capture_status: {c.capture_status}")
        typer.echo(f"evidence_location: {c.evidence_location}")
        typer.echo(f"source_snapshot_id: {c.source_snapshot_id}")
        typer.echo(f"official_source_id: {c.official_source_id}")


@snapshots_app.command("list")
def snapshots_list(source: str = typer.Option(..., "--source")) -> None:
    with get_session() as session:
        rows = repo.list_snapshots(session, source)
        for s in rows:
            typer.echo(f"{s.id} | {s.content_hash[:12]} | {s.captured_at} | {s.raw_content_uri}")


@review_app.command("queue")
def review_queue(limit: int = 50) -> None:
    with get_session() as session:
        rows = repo.list_review_queue(session, limit=limit)
        if not rows:
            typer.echo("Review queue empty.")
            return
        for c in rows:
            reason = []
            projection = repo.get_claim_review_projection(session, c)
            if projection.chain_error:
                reason.append(f"review chain invalid: {projection.chain_error}")
            elif projection.model_entity_id is None:
                reason.append("model_entity_id is null")
            elif c.model_entity_id is None:
                reason.append("model identity resolved by append-only review decision")
            if c.capture_status == "needs_review":
                reason.append("capture_status=needs_review")
            typer.echo(f"Claim ID: {c.id}")
            typer.echo(f"Benchmark: {c.benchmark_raw}")
            typer.echo(f"Model raw: {c.model_raw}")
            typer.echo(f"Score raw: {c.score_raw}")
            typer.echo(f"Reason: {', '.join(reason) or 'unspecified'}")
            typer.echo(f"Evidence: {c.evidence_location}")
            typer.echo("---")


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


@review_app.command("map-model")
def review_map_model(
    claim_id: str,
    model_entity_id: str,
    actor: str = typer.Option("cli", "--actor", help="Recorded decision actor"),
) -> None:
    """Append a manual model-identity decision without promoting the claim."""
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
        typer.echo(f"Review mapping blocked: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        f"Recorded manual model mapping {claim_id} -> {model_entity_id} "
        f"as review decision {decision_id}; captured claim and validation status are unchanged."
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
        report = build_legacy_inventory_report(session)
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
        raise typer.BadParameter("--format must be either 'json' or 'markdown'.")

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

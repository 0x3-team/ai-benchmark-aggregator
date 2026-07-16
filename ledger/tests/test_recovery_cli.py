from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.backup.errors import RecoveryPartialFailure
from app.cli import app
from app import recovery_io
from app.recovery_io import (
    RecoveryFileError,
    read_canonical_recovery_document,
    read_json_object,
    reserve_new_recovery_output,
    write_new_canonical_recovery_document,
)
from app.schemas.recovery_contracts import canonical_recovery_json


runner = CliRunner()


def _tree_fingerprint(root: Path) -> tuple[tuple[object, ...], ...]:
    paths = (root, *sorted(root.rglob("*")))
    rows: list[tuple[object, ...]] = []
    for path in paths:
        metadata = path.lstat()
        rows.append(
            (
                path.relative_to(root).as_posix(),
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file()
                else None,
            )
        )
    return tuple(rows)


def _checkpoint_result() -> dict[str, object]:
    return {
        "availability": "recovery_evidence_only",
        "checkpointId": "recovery-checkpoint_" + "a" * 64,
        "triggerCycle": {"cycleId": "cycle-fixture"},
        "objectManifest": {"objectReferenceCount": 0},
        "manifest": {"contentSha256": "b" * 64},
    }


def _restore_result() -> dict[str, object]:
    return {
        "availability": "recovery_evidence_only",
        "receiptId": "recovery-restore_" + "c" * 64,
        "durationMs": 2000,
        "checkpoint": {"checkpointId": "recovery-checkpoint_" + "a" * 64},
        "target": {"targetId": "cli-target", "cutoverAuthorized": False},
        "objectRestore": {"objectReferenceCount": 0},
        "recoveryAssessment": {
            "rpoStatus": "target_not_proven",
            "rtoStatus": "target_not_proven",
            "providerIndependenceStatus": "external_evidence_required",
        },
        "manifest": {"contentSha256": "d" * 64},
    }


def test_recovery_contract_file_is_private_canonical_and_never_overwritten(
    tmp_path: Path,
) -> None:
    output = tmp_path / "checkpoint.json"
    document = {"kind": "fixture", "nested": {"count": 1, "ready": False}}

    byte_length = write_new_canonical_recovery_document(output, document)

    expected = canonical_recovery_json(document).encode("ascii")
    assert output.read_bytes() == expected
    assert byte_length == len(expected)
    assert output.stat().st_mode & 0o777 == 0o600
    assert read_canonical_recovery_document(output) == document

    with pytest.raises(RecoveryFileError, match="will not be overwritten"):
        write_new_canonical_recovery_document(output, {"replacement": True})
    assert output.read_bytes() == expected


def test_recovery_output_can_be_reserved_before_target_work(tmp_path: Path) -> None:
    output = tmp_path / "restore-receipt.json"

    reservation = reserve_new_recovery_output(output)
    assert output.exists()
    assert output.read_bytes() == b""
    assert output.stat().st_mode & 0o777 == 0o600

    assert reservation.publish({"receipt": "fixture"}) == len(
        b'{"receipt":"fixture"}'
    )
    assert output.read_bytes() == b'{"receipt":"fixture"}'
    with pytest.raises(RecoveryFileError, match="closed"):
        reservation.publish({"receipt": "second"})


def test_recovery_file_reads_reject_symlink_directory_duplicate_key_and_nonfinite(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text('{"value":1}', encoding="utf-8")
    symlink = tmp_path / "linked.json"
    symlink.symlink_to(valid)
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"value":1,"value":2}', encoding="utf-8")
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")

    for path in (symlink, tmp_path):
        with pytest.raises(RecoveryFileError):
            read_json_object(path)
    with pytest.raises(RecoveryFileError, match="duplicate"):
        read_json_object(duplicate)
    with pytest.raises(RecoveryFileError, match="non-finite"):
        read_json_object(nonfinite)


def test_recovery_canonical_reader_rejects_pretty_or_trailing_bytes(
    tmp_path: Path,
) -> None:
    for index, raw in enumerate((b'{"a": 1}', b'{"a":1}\n', b'{"b":2,"a":1}')):
        path = tmp_path / f"noncanonical-{index}.json"
        path.write_bytes(raw)
        with pytest.raises(RecoveryFileError, match="canonical"):
            read_canonical_recovery_document(path)


def test_recovery_file_read_has_an_enforced_bound(tmp_path: Path) -> None:
    path = tmp_path / "too-large.json"
    path.write_bytes(b'{"value":"1234567890"}')

    with pytest.raises(RecoveryFileError, match="bounded size"):
        read_json_object(path, maximum_bytes=8)
    with pytest.raises(RecoveryFileError, match="bound is invalid"):
        read_json_object(path, maximum_bytes=0)


def test_recovery_output_rejects_symlink_parent_and_keeps_redacted_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(RecoveryFileError) as symlink_failure:
        write_new_canonical_recovery_document(
            linked_parent / "must-not-exist.json", {"value": 1}
        )
    assert not (real_parent / "must-not-exist.json").exists()
    assert str(linked_parent) not in str(symlink_failure.value)

    output = real_parent / "partial-secret-name.json"
    real_write = os.write
    writes = 0

    def fail_after_one_byte(descriptor: int, raw: bytes) -> int:
        nonlocal writes
        writes += 1
        if writes == 1:
            return real_write(descriptor, raw[:1])
        raise OSError("provider-password-must-not-escape")

    monkeypatch.setattr(recovery_io.os, "write", fail_after_one_byte)
    with pytest.raises(RecoveryFileError) as partial_failure:
        write_new_canonical_recovery_document(output, {"value": "long-enough"})
    assert output.exists()
    assert output.read_bytes() == b"{"
    assert "provider-password-must-not-escape" not in str(partial_failure.value)
    assert str(output) not in str(partial_failure.value)


def test_sqlite_checkpoint_cli_uses_only_explicit_inputs_and_publishes_canonical_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "explicit-source.db"
    source.write_bytes(b"fixture")
    primary = tmp_path / "primary"
    primary.mkdir()
    recovery = tmp_path / "recovery"
    trigger = tmp_path / "trigger.json"
    trigger.write_text('{"cycleId":"fixture"}', encoding="utf-8")
    output = tmp_path / "checkpoint.json"
    configured_secret = tmp_path / "must-not-be-opened-secret.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{configured_secret}")
    observed: dict[str, object] = {}

    def fake_checkpoint(**kwargs):  # type: ignore[no-untyped-def]
        observed.update(kwargs)
        assert output.exists() and output.read_bytes() == b""
        return _checkpoint_result()

    monkeypatch.setattr("app.cli.create_sqlite_checkpoint", fake_checkpoint)
    monkeypatch.setattr("app.cli._recovery_utc_now", lambda: "2026-07-16T12:00:00Z")

    result = runner.invoke(
        app,
        [
            "recovery",
            "checkpoint-sqlite",
            "--database-source",
            str(source),
            "--trigger",
            str(trigger),
            "--primary-root",
            str(primary),
            "--primary-domain-id",
            "cli-primary",
            "--recovery-root",
            str(recovery),
            "--recovery-domain-id",
            "cli-recovery",
            "--manifest-output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed["database_path"] == source
    assert observed["trigger_cycle"] == {"cycleId": "fixture"}
    assert observed["created_at"] == "2026-07-16T12:00:00Z"
    assert not configured_secret.exists()
    assert output.read_bytes() == canonical_recovery_json(_checkpoint_result()).encode(
        "ascii"
    )
    payload = json.loads(result.stdout)
    assert payload == {
        "authorizesCutover": False,
        "authorizesPublication": False,
        "availability": "recovery_evidence_only",
        "checkpointId": "recovery-checkpoint_" + "a" * 64,
        "contentSha256": "b" * 64,
        "objectReferenceCount": 0,
        "provesProductionRpoRto": False,
        "status": "completed",
        "triggerCycleId": "cycle-fixture",
    }
    assert str(source) not in result.output
    assert str(primary) not in result.output
    assert str(recovery) not in result.output


def test_checkpoint_cli_failure_is_redacted_and_retains_reserved_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "password-in-source-name.db"
    source.write_bytes(b"fixture")
    primary = tmp_path / "primary-secret-root"
    primary.mkdir()
    trigger = tmp_path / "trigger-secret.json"
    trigger.write_text('{"cycleId":"fixture"}', encoding="utf-8")
    output = tmp_path / "reserved-failure.json"

    def fail_after_reservation(**_kwargs):  # type: ignore[no-untyped-def]
        assert output.read_bytes() == b""
        raise RecoveryPartialFailure(
            "SQLITE_BACKUP_FAILED",
            phase="relational_backup",
        )

    monkeypatch.setattr("app.cli.create_sqlite_checkpoint", fail_after_reservation)
    result = runner.invoke(
        app,
        [
            "recovery",
            "checkpoint-sqlite",
            "--database-source",
            str(source),
            "--trigger",
            str(trigger),
            "--primary-root",
            str(primary),
            "--primary-domain-id",
            "cli-primary",
            "--recovery-root",
            str(tmp_path / "recovery-secret-root"),
            "--recovery-domain-id",
            "cli-recovery",
            "--manifest-output",
            str(output),
        ],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    failure = json.loads(result.stderr)
    assert failure["reasonCode"] == "SQLITE_BACKUP_FAILED"
    assert failure["phase"] == "relational_backup"
    assert failure["successReceiptEmitted"] is False
    assert output.exists() and output.read_bytes() == b""
    for secret in (str(source), str(primary), str(output), "password-in-source-name"):
        assert secret not in result.output


def test_checkpoint_cli_never_overwrites_manifest_or_follows_primary_root_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.db"
    source.write_bytes(b"fixture")
    actual_primary = tmp_path / "actual-primary"
    actual_primary.mkdir()
    linked_primary = tmp_path / "linked-primary"
    linked_primary.symlink_to(actual_primary, target_is_directory=True)
    trigger = tmp_path / "trigger.json"
    trigger.write_text('{"cycleId":"fixture"}', encoding="utf-8")
    existing = tmp_path / "existing.json"
    existing.write_bytes(b"operator-evidence")
    called = False

    def must_not_run(**_kwargs):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        return _checkpoint_result()

    monkeypatch.setattr("app.cli.create_sqlite_checkpoint", must_not_run)
    base_args = [
        "recovery",
        "checkpoint-sqlite",
        "--database-source",
        str(source),
        "--trigger",
        str(trigger),
        "--primary-domain-id",
        "cli-primary",
        "--recovery-root",
        str(tmp_path / "recovery"),
        "--recovery-domain-id",
        "cli-recovery",
        "--manifest-output",
        str(existing),
    ]

    linked = runner.invoke(
        app,
        base_args + ["--primary-root", str(linked_primary)],
    )
    assert linked.exit_code == 2
    assert not called
    assert existing.read_bytes() == b"operator-evidence"

    regular = runner.invoke(
        app,
        base_args + ["--primary-root", str(actual_primary)],
    )
    assert regular.exit_code == 2
    assert not called
    assert existing.read_bytes() == b"operator-evidence"


@pytest.mark.parametrize("command", ["checkpoint-sqlite", "checkpoint-postgresql"])
@pytest.mark.parametrize(
    "protected_output_root",
    ["primary", "recovery", "primary_via_ancestor_symlink"],
)
def test_checkpoint_cli_rejects_manifest_inside_any_object_root_before_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    protected_output_root: str,
) -> None:
    source = tmp_path / "source.db"
    source.write_bytes(b"fixture")
    trigger = tmp_path / "trigger.json"
    trigger.write_text('{"cycleId":"fixture"}', encoding="utf-8")
    primary = tmp_path / "primary"
    primary.mkdir()
    (primary / "retained-source-byte").write_bytes(b"immutable-primary")
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    if protected_output_root == "primary_via_ancestor_symlink":
        protected_child = primary / "existing-child"
        protected_child.mkdir()
        primary_alias = tmp_path / "primary-alias"
        primary_alias.symlink_to(primary, target_is_directory=True)
        output = primary_alias / protected_child.name / "must-not-be-created.json"
    else:
        protected_root = primary if protected_output_root == "primary" else recovery
        output = protected_root / "must-not-be-created.json"
    before = {
        "primary": _tree_fingerprint(primary),
        "recovery": _tree_fingerprint(recovery),
    }
    called: list[str] = []

    def must_not_checkpoint(**_kwargs):  # type: ignore[no-untyped-def]
        called.append("service")
        return _checkpoint_result()

    monkeypatch.setattr("app.cli.create_sqlite_checkpoint", must_not_checkpoint)
    monkeypatch.setattr("app.cli.create_checkpoint_with_driver", must_not_checkpoint)
    args = [
        "recovery",
        command,
        "--trigger",
        str(trigger),
        "--primary-root",
        str(primary),
        "--primary-domain-id",
        "cli-primary",
        "--recovery-root",
        str(recovery),
        "--recovery-domain-id",
        "cli-recovery",
        "--manifest-output",
        str(output),
    ]
    if command == "checkpoint-sqlite":
        args.extend(("--database-source", str(source)))
    else:
        args.extend(("--inspection-target-id", "must-not-be-consumed"))

    result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert json.loads(result.stderr)["reasonCode"] == "RECOVERY_FILE_REJECTED"
    assert called == []
    assert not output.exists()
    assert _tree_fingerprint(primary) == before["primary"]
    assert _tree_fingerprint(recovery) == before["recovery"]
    assert str(primary) not in result.output
    assert str(recovery) not in result.output


def test_postgresql_checkpoint_cli_reads_connections_only_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.backup.postgresql_driver as postgresql_driver

    primary = tmp_path / "primary"
    primary.mkdir()
    trigger = tmp_path / "trigger.json"
    trigger.write_text('{"cycleId":"fixture"}', encoding="utf-8")
    output = tmp_path / "checkpoint.json"
    source_secret = "postgresql+psycopg://user:source-secret@db.test:5432/source"
    inspection_secret = (
        "postgresql+psycopg://user:inspection-secret@db.test:5432/inspection"
    )
    monkeypatch.setenv("LEDGER_RECOVERY_POSTGRESQL_SOURCE_URL", source_secret)
    monkeypatch.setenv(
        "LEDGER_RECOVERY_POSTGRESQL_INSPECTION_URL", inspection_secret
    )
    parsed: list[str] = []

    class FakeSpec:
        @classmethod
        def from_url(cls, value: str):  # type: ignore[no-untyped-def]
            parsed.append(value)
            return object()

    fake_driver = object()
    monkeypatch.setattr(postgresql_driver, "PostgreSQLConnectionSpec", FakeSpec)
    monkeypatch.setattr(
        postgresql_driver, "PostgreSQLBackupRestoreDriver", lambda: fake_driver
    )

    def fake_checkpoint(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["driver"] is fake_driver
        assert kwargs["inspection_target_id"] == "inspection-target-01"
        return _checkpoint_result()

    monkeypatch.setattr("app.cli.create_checkpoint_with_driver", fake_checkpoint)
    result = runner.invoke(
        app,
        [
            "recovery",
            "checkpoint-postgresql",
            "--trigger",
            str(trigger),
            "--primary-root",
            str(primary),
            "--primary-domain-id",
            "cli-primary",
            "--recovery-root",
            str(tmp_path / "recovery"),
            "--recovery-domain-id",
            "cli-recovery",
            "--inspection-target-id",
            "inspection-target-01",
            "--manifest-output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert parsed == [source_secret, inspection_secret]
    assert "source-secret" not in result.output
    assert "inspection-secret" not in result.output
    help_result = runner.invoke(app, ["recovery", "checkpoint-postgresql", "--help"])
    assert help_result.exit_code == 0
    assert "database-source" not in help_result.output


def test_sqlite_restore_cli_reserves_receipt_then_uses_measured_service_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_bytes(canonical_recovery_json(_checkpoint_result()).encode("ascii"))
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    restore = tmp_path / "restore"
    database_target = tmp_path / "restore.db"
    receipt_output = tmp_path / "receipt.json"
    observed: dict[str, object] = {}
    monkeypatch.setattr("app.cli.validate_checkpoint_manifest", lambda _value: None)

    def fake_restore(**kwargs):  # type: ignore[no-untyped-def]
        observed.update(kwargs)
        assert receipt_output.exists() and receipt_output.read_bytes() == b""
        assert not database_target.exists()
        return _restore_result()

    monkeypatch.setattr("app.cli.restore_sqlite_checkpoint", fake_restore)
    result = runner.invoke(
        app,
        [
            "recovery",
            "restore-sqlite",
            "--checkpoint-manifest",
            str(checkpoint),
            "--recovery-root",
            str(recovery),
            "--recovery-domain-id",
            "cli-recovery",
            "--restore-root",
            str(restore),
            "--restore-domain-id",
            "cli-restore",
            "--database-target",
            str(database_target),
            "--target-id",
            "cli-target",
            "--receipt-output",
            str(receipt_output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed["database_target"] == database_target
    assert observed["target_id"] == "cli-target"
    assert "started_at" not in observed and "finished_at" not in observed
    assert receipt_output.read_bytes() == canonical_recovery_json(
        _restore_result()
    ).encode("ascii")
    success = json.loads(result.stdout)
    assert success["durationMs"] == 2000
    assert success["rpoStatus"] == "target_not_proven"
    assert success["rtoStatus"] == "target_not_proven"
    assert success["cutoverAuthorized"] is False
    for locator in (checkpoint, recovery, restore, database_target, receipt_output):
        assert str(locator) not in result.output


def test_restore_cli_rejects_invalid_manifest_before_reservation_or_target_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = tmp_path / "invalid-checkpoint.json"
    checkpoint.write_bytes(canonical_recovery_json(_checkpoint_result()).encode("ascii"))
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    receipt_output = tmp_path / "must-not-be-reserved.json"
    database_target = tmp_path / "must-not-exist.db"
    called = False

    def reject(_value):  # type: ignore[no-untyped-def]
        from app.backup import RecoveryContractError

        raise RecoveryContractError("secret-invalid-contract-detail")

    def must_not_restore(**_kwargs):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True

    monkeypatch.setattr("app.cli.validate_checkpoint_manifest", reject)
    monkeypatch.setattr("app.cli.restore_sqlite_checkpoint", must_not_restore)
    result = runner.invoke(
        app,
        [
            "recovery",
            "restore-sqlite",
            "--checkpoint-manifest",
            str(checkpoint),
            "--recovery-root",
            str(recovery),
            "--recovery-domain-id",
            "cli-recovery",
            "--restore-root",
            str(tmp_path / "restore"),
            "--restore-domain-id",
            "cli-restore",
            "--database-target",
            str(database_target),
            "--target-id",
            "cli-target",
            "--receipt-output",
            str(receipt_output),
        ],
    )

    assert result.exit_code == 2
    assert not called
    assert not receipt_output.exists()
    assert not database_target.exists()
    assert json.loads(result.stderr)["reasonCode"] == "RECOVERY_CONTRACT_REJECTED"
    assert "secret-invalid-contract-detail" not in result.output
    assert str(checkpoint) not in result.output


@pytest.mark.parametrize("command", ["restore-sqlite", "restore-postgresql"])
@pytest.mark.parametrize("protected_output_root", ["recovery", "restore"])
def test_restore_cli_rejects_receipt_inside_any_object_root_before_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    protected_output_root: str,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_bytes(canonical_recovery_json(_checkpoint_result()).encode("ascii"))
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    (recovery / "retained-recovery-byte").write_bytes(b"immutable-recovery")
    restore = tmp_path / "restore"
    restore.mkdir()
    protected_root = recovery if protected_output_root == "recovery" else restore
    receipt_output = protected_root / "must-not-be-created.json"
    database_target = tmp_path / "must-not-be-created.db"
    before = {
        "recovery": _tree_fingerprint(recovery),
        "restore": _tree_fingerprint(restore),
    }
    called: list[str] = []
    monkeypatch.setattr("app.cli.validate_checkpoint_manifest", lambda _value: None)

    def must_not_restore(**_kwargs):  # type: ignore[no-untyped-def]
        called.append("service")
        return _restore_result()

    monkeypatch.setattr("app.cli.restore_sqlite_checkpoint", must_not_restore)
    monkeypatch.setattr("app.cli.restore_checkpoint_with_driver", must_not_restore)
    args = [
        "recovery",
        command,
        "--checkpoint-manifest",
        str(checkpoint),
        "--recovery-root",
        str(recovery),
        "--recovery-domain-id",
        "cli-recovery",
        "--restore-root",
        str(restore),
        "--restore-domain-id",
        "cli-restore",
        "--target-id",
        "must-not-be-consumed",
        "--receipt-output",
        str(receipt_output),
    ]
    if command == "restore-sqlite":
        args.extend(("--database-target", str(database_target)))

    result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert json.loads(result.stderr)["reasonCode"] == "RECOVERY_FILE_REJECTED"
    assert called == []
    assert not receipt_output.exists()
    assert not database_target.exists()
    assert _tree_fingerprint(recovery) == before["recovery"]
    assert _tree_fingerprint(restore) == before["restore"]
    assert str(recovery) not in result.output
    assert str(restore) not in result.output


def test_sqlite_restore_cli_rejects_receipt_equal_to_relational_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_bytes(canonical_recovery_json(_checkpoint_result()).encode("ascii"))
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    restore = tmp_path / "restore"
    target_and_receipt = tmp_path / "must-remain-absent.db"
    monkeypatch.setattr("app.cli.validate_checkpoint_manifest", lambda _value: None)
    called = False

    def must_not_restore(**_kwargs):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        return _restore_result()

    monkeypatch.setattr("app.cli.restore_sqlite_checkpoint", must_not_restore)
    result = runner.invoke(
        app,
        [
            "recovery",
            "restore-sqlite",
            "--checkpoint-manifest",
            str(checkpoint),
            "--recovery-root",
            str(recovery),
            "--recovery-domain-id",
            "cli-recovery",
            "--restore-root",
            str(restore),
            "--restore-domain-id",
            "cli-restore",
            "--database-target",
            str(target_and_receipt),
            "--target-id",
            "must-not-be-consumed",
            "--receipt-output",
            str(target_and_receipt),
        ],
    )

    assert result.exit_code == 2
    assert not called
    assert not target_and_receipt.exists()
    assert not restore.exists()


def test_postgresql_restore_cli_uses_only_fixed_environment_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.backup.postgresql_driver as postgresql_driver

    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_bytes(canonical_recovery_json(_checkpoint_result()).encode("ascii"))
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    receipt_output = tmp_path / "receipt.json"
    target_secret = "postgresql+psycopg://user:restore-secret@db.test:5432/restore"
    monkeypatch.setenv("LEDGER_RECOVERY_POSTGRESQL_RESTORE_URL", target_secret)
    monkeypatch.setattr("app.cli.validate_checkpoint_manifest", lambda _value: None)
    parsed: list[str] = []

    class FakeSpec:
        @classmethod
        def from_url(cls, value: str):  # type: ignore[no-untyped-def]
            parsed.append(value)
            return object()

    fake_driver = object()
    monkeypatch.setattr(postgresql_driver, "PostgreSQLConnectionSpec", FakeSpec)
    monkeypatch.setattr(
        postgresql_driver, "PostgreSQLBackupRestoreDriver", lambda: fake_driver
    )

    def fake_restore(**kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["driver"] is fake_driver
        assert kwargs["target_id"] == "cli-target"
        return _restore_result()

    monkeypatch.setattr("app.cli.restore_checkpoint_with_driver", fake_restore)
    result = runner.invoke(
        app,
        [
            "recovery",
            "restore-postgresql",
            "--checkpoint-manifest",
            str(checkpoint),
            "--recovery-root",
            str(recovery),
            "--recovery-domain-id",
            "cli-recovery",
            "--restore-root",
            str(tmp_path / "restore"),
            "--restore-domain-id",
            "cli-restore",
            "--target-id",
            "cli-target",
            "--receipt-output",
            str(receipt_output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert parsed == [target_secret]
    assert "restore-secret" not in result.output
    help_result = runner.invoke(app, ["recovery", "restore-postgresql", "--help"])
    assert help_result.exit_code == 0
    assert "database-target" not in help_result.output


def test_sqlite_checkpoint_and_measured_restore_cli_end_to_end_on_fresh_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from sqlalchemy.orm import Session

    from app.backup import validate_checkpoint_manifest, validate_restore_receipt
    from app.db import operational_repositories
    from tests.test_recovery_foundations import (
        _alembic_config,
        _engine,
        _terminal_cycle,
    )

    source = tmp_path / "source.db"
    command.upgrade(_alembic_config(f"sqlite:///{source}"), "head")
    trigger_document = _terminal_cycle()
    engine = _engine(source)
    try:
        with Session(engine) as session, session.begin():
            intent, jobs = operational_repositories.append_scheduled_cycle_intent(
                session,
                environment=trigger_document["environment"],
                lane=trigger_document["lane"],
                scheduled_for=trigger_document["slot"]["scheduledFor"],
                schedule_policy_revision_id=trigger_document[
                    "schedulePolicyRevisionId"
                ],
                mode=trigger_document["mode"],
                job_targets=[],
            )
            assert intent.cycle_id == trigger_document["cycleId"] and jobs == ()
            operational_repositories.append_scheduled_cycle(session, trigger_document)
    finally:
        engine.dispose()

    trigger = tmp_path / "trigger.json"
    trigger.write_text(json.dumps(trigger_document), encoding="utf-8")
    primary = tmp_path / "primary"
    primary.mkdir()
    recovery = tmp_path / "recovery"
    checkpoint_path = tmp_path / "checkpoint.json"
    forbidden_configured_db = tmp_path / "configured-must-not-exist.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{forbidden_configured_db}")

    checkpoint_result = runner.invoke(
        app,
        [
            "recovery",
            "checkpoint-sqlite",
            "--database-source",
            str(source),
            "--trigger",
            str(trigger),
            "--primary-root",
            str(primary),
            "--primary-domain-id",
            "e2e-primary",
            "--recovery-root",
            str(recovery),
            "--recovery-domain-id",
            "e2e-recovery",
            "--manifest-output",
            str(checkpoint_path),
        ],
    )
    assert checkpoint_result.exit_code == 0, checkpoint_result.output
    checkpoint = read_canonical_recovery_document(checkpoint_path)
    validate_checkpoint_manifest(checkpoint)
    assert checkpoint["triggerCycle"]["cycleId"] == trigger_document["cycleId"]

    restore_root = tmp_path / "restore-objects"
    restored_database = tmp_path / "restored.db"
    receipt_path = tmp_path / "receipt.json"
    restore_result = runner.invoke(
        app,
        [
            "recovery",
            "restore-sqlite",
            "--checkpoint-manifest",
            str(checkpoint_path),
            "--recovery-root",
            str(recovery),
            "--recovery-domain-id",
            "e2e-recovery",
            "--restore-root",
            str(restore_root),
            "--restore-domain-id",
            "e2e-restore",
            "--database-target",
            str(restored_database),
            "--target-id",
            "e2e-fresh-target",
            "--receipt-output",
            str(receipt_path),
        ],
    )
    assert restore_result.exit_code == 0, restore_result.output
    receipt = read_canonical_recovery_document(receipt_path)
    validate_restore_receipt(receipt)
    assert receipt["target"]["freshRelationalTarget"] is True
    assert receipt["target"]["cutoverAuthorized"] is False
    assert receipt["durationMs"] >= 0
    assert restored_database.is_file()
    assert not forbidden_configured_db.exists()

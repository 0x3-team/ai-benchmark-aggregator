"""Public DATA-10 recovery foundation boundary."""

from app.schemas.recovery_contracts import (
    RecoveryContractError,
    canonical_recovery_json,
    parse_canonical_recovery_bytes,
    recovery_contract_digest,
    recovery_cycle_set_digest,
    recovery_object_set_digest,
    recovery_table_inventory_digest,
    validate_checkpoint_manifest,
    validate_restore_receipt,
)

from .errors import (
    RecoveryCancelled,
    RecoveryError,
    RecoveryIntegrityError,
    RecoveryPartialFailure,
    RecoveryReplayConflict,
    RecoveryTargetError,
    UnsupportedRecoveryArtifact,
)
from .protocols import (
    RelationalBackupArtifact,
    RelationalBackupRestoreDriver,
    RelationalInspectionResult,
)
from .service import (
    assert_checkpoint_replay,
    create_checkpoint_with_driver,
    create_sqlite_checkpoint,
    restore_checkpoint_with_driver,
    restore_sqlite_checkpoint,
)
from .sqlite_driver import SQLiteBackupRestoreDriver, redact_database_locator
from .stores import LocalRecoveryStore, RecoveryDomain


__all__ = [
    "LocalRecoveryStore",
    "RecoveryCancelled",
    "RecoveryContractError",
    "RecoveryDomain",
    "RecoveryError",
    "RecoveryIntegrityError",
    "RecoveryPartialFailure",
    "RecoveryReplayConflict",
    "RecoveryTargetError",
    "RelationalBackupArtifact",
    "RelationalBackupRestoreDriver",
    "RelationalInspectionResult",
    "SQLiteBackupRestoreDriver",
    "UnsupportedRecoveryArtifact",
    "assert_checkpoint_replay",
    "canonical_recovery_json",
    "create_checkpoint_with_driver",
    "create_sqlite_checkpoint",
    "parse_canonical_recovery_bytes",
    "recovery_contract_digest",
    "recovery_cycle_set_digest",
    "recovery_object_set_digest",
    "recovery_table_inventory_digest",
    "redact_database_locator",
    "restore_checkpoint_with_driver",
    "restore_sqlite_checkpoint",
    "validate_checkpoint_manifest",
    "validate_restore_receipt",
]

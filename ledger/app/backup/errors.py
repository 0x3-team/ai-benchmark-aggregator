"""Typed, redacted DATA-10 failures.

No exception embeds raw database URLs, credentials, source bytes, or arbitrary
provider error text.  Partial state is retained rather than deleted and never
returned as a successful checkpoint/restore receipt.
"""

from __future__ import annotations


class RecoveryError(RuntimeError):
    """Base class for provider-neutral backup/recovery failures."""


class RecoveryIntegrityError(RecoveryError):
    """Immutable bytes, inventories, contracts, or lineage did not re-resolve."""


class RecoveryTargetError(RecoveryError):
    """A target is not fresh, safe, or supported for restore."""


class UnsupportedRecoveryArtifact(RecoveryIntegrityError):
    """A database reference has no typed digest-restorable DATA-10 representation."""


class RecoveryReplayConflict(RecoveryIntegrityError):
    """One deterministic trigger identity was presented with conflicting bytes."""


class RecoveryPartialFailure(RecoveryError):
    """An operation stopped after leaving immutable partial state and no success receipt."""

    def __init__(
        self,
        reason_code: str,
        *,
        phase: str,
        completed_object_count: int = 0,
        relational_target_created: bool = False,
    ) -> None:
        self.reason_code = reason_code
        self.phase = phase
        self.completed_object_count = completed_object_count
        self.relational_target_created = relational_target_created
        super().__init__(
            f"{reason_code}: recovery stopped during {phase}; "
            "partial immutable state was retained and no success receipt was emitted"
        )


class RecoveryCancelled(RecoveryPartialFailure):
    """The injected cancellation fence stopped work; no success receipt exists."""

    def __init__(
        self,
        *,
        phase: str,
        completed_object_count: int = 0,
        relational_target_created: bool = False,
    ) -> None:
        super().__init__(
            "RECOVERY_CANCELLED",
            phase=phase,
            completed_object_count=completed_object_count,
            relational_target_created=relational_target_created,
        )


__all__ = [
    "RecoveryCancelled",
    "RecoveryError",
    "RecoveryIntegrityError",
    "RecoveryPartialFailure",
    "RecoveryReplayConflict",
    "RecoveryTargetError",
    "UnsupportedRecoveryArtifact",
]

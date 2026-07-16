"""Contained PostgreSQL 16 custom-archive recovery driver for DATA-10.

The driver accepts only explicit typed connection specifications, executes the
real PostgreSQL 16 binaries by fixed absolute path, and restores into an
already-created but otherwise empty database.  A target is durably consumed by
an autocommit database comment before ``pg_restore``; the marker is never
cleared, including after cancellation or failure.

Archive and schema-equivalence operations deliberately exclude owners, role
memberships, grants, ACLs, and provider configuration.  After a successful
restore the driver applies one literal safety floor -- revoking PUBLIC execute
on restored functions -- so the existing strict executable-schema inspection
can run.  It does not create roles, alter owners, grant privileges, or claim
that production access posture was recovered.
"""

from __future__ import annotations

import hashlib
import os
import re
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from sqlalchemy.engine import URL, make_url

from app.db.migrate import head_revision, inspect_database
from app.db.postgresql import (
    POSTGRESQL_OPERATIONAL_CONSTRAINT_INVENTORY_SHA256,
    POSTGRESQL_OPERATIONAL_INDEX_INVENTORY_SHA256,
    POSTGRESQL_OPERATIONAL_TABLES,
    POSTGRESQL_REQUIRED_CONSTRAINTS,
    POSTGRESQL_REQUIRED_CONSTRAINT_TABLES,
    POSTGRESQL_REQUIRED_FUNCTIONS,
    POSTGRESQL_REQUIRED_INDEXES,
)
from app.schemas.recovery_contracts import canonical_recovery_json
from app.storage.base import compute_content_hash

from .errors import (
    RecoveryCancelled,
    RecoveryIntegrityError,
    RecoveryPartialFailure,
    RecoveryTargetError,
    UnsupportedRecoveryArtifact,
)
from .protocols import (
    RelationalBackupArtifact,
    RelationalInspectionResult,
    RelationalIntegrityResult,
)
from .semantic_inspection import (
    audit_semantic_lineages,
    build_cycle_inventory,
    build_table_inventory,
    enumerate_referenced_objects,
    expected_head_columns,
    table_inventory_digest,
)


PG_DUMP_PATH = Path("/usr/lib/postgresql/16/bin/pg_dump")
PG_RESTORE_PATH = Path("/usr/lib/postgresql/16/bin/pg_restore")

_DRIVER_ID = "postgresql-pg-tools"
_DRIVER_VERSION = "1.0.0"
_ENGINE_NAME = "postgresql"
_TOOL_NAME = "pg_dump-pg_restore"
_ARTIFACT_TYPE = "postgresql_database"
_FORMAT = "postgresql_custom_archive"
_FORMAT_VERSION = "pg_dump-custom-v1"
_ARCHIVE_HEADER = b"PGDMP"
_SUPPORTED_MAJOR = 16
_FIRST_NORMAL_OBJECT_ID = 16_384
_STABLE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_NUMERIC_ID = re.compile(r"[0-9]+")
_TOOL_VERSION = re.compile(
    rb"^pg_(?:dump|restore) \(PostgreSQL\) (16\.\d+(?:\.\d+)?)"
)
_RESTRICT_LINE = re.compile(rb"^\\(restrict|unrestrict) ([^\r\n ]+)$")
_PUBLIC_SCHEMA_TOC = re.compile(
    r"^[0-9]+;\s+[0-9]+\s+[0-9]+\s+SCHEMA\s+-\s+public(?:\s+\S+)?$"
)
_TABLE_TOC = re.compile(
    r"^[0-9]+;\s+[0-9]+\s+[0-9]+\s+TABLE\s+public\s+alembic_version(?:\s+\S+)?$"
)
_TABLE_DATA_TOC = re.compile(
    r"^[0-9]+;\s+[0-9]+\s+[0-9]+\s+TABLE DATA\s+public\s+alembic_version(?:\s+\S+)?$"
)
_SCHEMA_NONCE = b"DATA10_RESTRICT_NONCE"
_SAFETY_FLOOR_SQL = (
    "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC"
)
_CONNECT_TIMEOUT_SECONDS = 10
_STATEMENT_TIMEOUT_MS = 60_000
_LOCK_TIMEOUT_MS = 5_000
_IDLE_TRANSACTION_TIMEOUT_MS = 60_000
_DEFAULT_COMMAND_TIMEOUT_SECONDS = 600.0
_MAX_COMMAND_TIMEOUT_SECONDS = 3600.0
_PROCESS_STOP_GRACE_SECONDS = 2.0
_POLL_SECONDS = 0.1

_ALLOWED_QUERY_OPTIONS = frozenset(
    {
        "host",
        "port",
        "sslmode",
        "sslrootcert",
        "sslcert",
        "sslkey",
        "channel_binding",
    }
)
_SSL_PATH_OPTIONS = ("sslrootcert", "sslcert", "sslkey")
_FORBIDDEN_SCHEMA_STATEMENTS = (
    re.compile(rb"(?im)^\s*ALTER\s+.+\s+OWNER\s+TO\s+"),
    re.compile(rb"(?im)^\s*GRANT\s+"),
    re.compile(rb"(?im)^\s*REVOKE\s+"),
    re.compile(rb"(?im)^\s*SET\s+SESSION\s+AUTHORIZATION\s+"),
    re.compile(rb"(?im)^\s*ALTER\s+DEFAULT\s+PRIVILEGES\s+"),
)


def _control_free(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise RecoveryTargetError(f"{label} must be non-empty control-free text.")
    return value


def _query_value(query: Mapping[str, Any], name: str) -> str | None:
    value = query.get(name)
    if value is None:
        return None
    if type(value) is not str:
        raise RecoveryTargetError(
            "Repeated or non-text PostgreSQL connection options are unsupported."
        )
    return _control_free(value, label=f"PostgreSQL {name}")


@dataclass(frozen=True, slots=True)
class PostgreSQLConnectionSpec:
    """Explicit connection material that never renders a DSN in diagnostics."""

    database: str
    user: str
    host: str
    port: int
    password: str | None = field(default=None, repr=False)
    sslmode: str = "disable"
    sslrootcert: str | None = field(default=None, repr=False)
    sslcert: str | None = field(default=None, repr=False)
    sslkey: str | None = field(default=None, repr=False)
    channel_binding: str | None = None

    def __post_init__(self) -> None:
        _control_free(self.database, label="PostgreSQL database")
        _control_free(self.user, label="PostgreSQL user")
        host = _control_free(self.host, label="PostgreSQL host")
        if type(self.port) is not int or type(self.port) is bool or not 1 <= self.port <= 65535:
            raise RecoveryTargetError("PostgreSQL port is outside the supported range.")
        if self.password is not None:
            _control_free(self.password, label="PostgreSQL password")
        unix_socket = host.startswith("/")
        if unix_socket and self.sslmode != "disable":
            raise RecoveryTargetError(
                "Unix-socket PostgreSQL recovery requires sslmode=disable."
            )
        if not unix_socket and self.sslmode != "verify-full":
            raise RecoveryTargetError(
                "Network PostgreSQL recovery requires explicit sslmode=verify-full."
            )
        if not unix_socket and self.sslrootcert is None:
            raise RecoveryTargetError(
                "Network PostgreSQL recovery requires an explicit sslrootcert."
            )
        if unix_socket and any(
            value is not None for value in (self.sslrootcert, self.sslcert, self.sslkey)
        ):
            raise RecoveryTargetError(
                "Unix-socket recovery cannot carry unused TLS file options."
            )
        for name, value in (
            ("sslrootcert", self.sslrootcert),
            ("sslcert", self.sslcert),
            ("sslkey", self.sslkey),
        ):
            if value is not None and (
                not Path(_control_free(value, label=f"PostgreSQL {name}")).is_absolute()
            ):
                raise RecoveryTargetError(f"PostgreSQL {name} must be an absolute path.")
        if self.channel_binding not in {None, "disable", "prefer", "require"}:
            raise RecoveryTargetError("PostgreSQL channel_binding value is unsupported.")
        if not unix_socket and self.channel_binding == "disable":
            raise RecoveryTargetError(
                "Network PostgreSQL recovery cannot disable channel binding."
            )

    @classmethod
    def from_url(cls, database_url: str) -> "PostgreSQLConnectionSpec":
        """Parse one reviewed psycopg URL without retaining its raw DSN."""

        if type(database_url) is not str:
            raise RecoveryTargetError("PostgreSQL connection URL must be text.")
        try:
            parsed = make_url(database_url)
        except Exception:
            raise RecoveryTargetError("PostgreSQL connection URL is invalid.") from None
        if parsed.drivername != "postgresql+psycopg":
            raise RecoveryTargetError(
                "PostgreSQL recovery requires the explicit postgresql+psycopg driver."
            )
        unsupported = sorted(set(parsed.query) - _ALLOWED_QUERY_OPTIONS)
        if unsupported:
            raise RecoveryTargetError(
                "URL contains an unsupported PostgreSQL connection option."
            )
        database = _control_free(parsed.database, label="PostgreSQL database")
        user = _control_free(parsed.username, label="PostgreSQL user")
        if parsed.password is not None:
            password = _control_free(parsed.password, label="PostgreSQL password")
        else:
            password = None

        query_host = _query_value(parsed.query, "host")
        if parsed.host is not None and query_host is not None:
            raise RecoveryTargetError("PostgreSQL host must have one explicit source.")
        host = _control_free(parsed.host or query_host, label="PostgreSQL host")
        query_port = _query_value(parsed.query, "port")
        try:
            authority_port = parsed.port
        except ValueError:
            raise RecoveryTargetError(
                "PostgreSQL port must be explicit and numeric."
            ) from None
        if authority_port is not None and query_port is not None:
            raise RecoveryTargetError("PostgreSQL port must have one explicit source.")
        raw_port: object = authority_port if authority_port is not None else query_port
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            raise RecoveryTargetError("PostgreSQL port must be explicit and numeric.") from None
        if not 1 <= port <= 65535:
            raise RecoveryTargetError("PostgreSQL port is outside the supported range.")

        sslmode = _query_value(parsed.query, "sslmode")
        is_unix_socket = host.startswith("/")
        if sslmode is None:
            if not is_unix_socket:
                raise RecoveryTargetError(
                    "Network PostgreSQL recovery requires explicit sslmode=verify-full."
                )
            sslmode = "disable"
        if is_unix_socket:
            if sslmode != "disable":
                raise RecoveryTargetError(
                    "Unix-socket PostgreSQL recovery requires sslmode=disable."
                )
        elif sslmode != "verify-full":
            raise RecoveryTargetError(
                "Network PostgreSQL recovery requires explicit sslmode=verify-full."
            )

        ssl_values = {
            name: _query_value(parsed.query, name) for name in _SSL_PATH_OPTIONS
        }
        if sslmode == "verify-full" and ssl_values["sslrootcert"] is None:
            raise RecoveryTargetError(
                "Network PostgreSQL recovery requires an explicit sslrootcert."
            )
        if sslmode == "disable" and any(ssl_values.values()):
            raise RecoveryTargetError(
                "Unix-socket recovery cannot carry unused TLS file options."
            )
        for name, value in ssl_values.items():
            if value is not None and not Path(value).is_absolute():
                raise RecoveryTargetError(
                    f"PostgreSQL {name} must be an absolute path."
                )
        channel_binding = _query_value(parsed.query, "channel_binding")
        if channel_binding not in {None, "disable", "prefer", "require"}:
            raise RecoveryTargetError("PostgreSQL channel_binding value is unsupported.")
        if not is_unix_socket and channel_binding == "disable":
            raise RecoveryTargetError(
                "Network PostgreSQL recovery cannot disable channel binding."
            )
        return cls(
            database=database,
            user=user,
            host=host,
            port=port,
            password=password,
            sslmode=sslmode,
            sslrootcert=ssl_values["sslrootcert"],
            sslcert=ssl_values["sslcert"],
            sslkey=ssl_values["sslkey"],
            channel_binding=channel_binding,
        )

    def libpq_environment(self, *, application_name: str) -> dict[str, str]:
        """Build a closed allowlist; no caller or process environment is inherited."""

        app_name = _control_free(application_name, label="PostgreSQL application name")
        environment = {
            "LANG": "C",
            "LC_ALL": "C",
            "PGAPPNAME": app_name,
            "PGCONNECT_TIMEOUT": str(_CONNECT_TIMEOUT_SECONDS),
            "PGDATABASE": self.database,
            "PGHOST": self.host,
            "PGPORT": str(self.port),
            "PGSSLMODE": self.sslmode,
            "PGUSER": self.user,
            "TZ": "UTC",
        }
        if self.password is not None:
            environment["PGPASSWORD"] = self.password
        for name, value in (
            ("PGSSLROOTCERT", self.sslrootcert),
            ("PGSSLCERT", self.sslcert),
            ("PGSSLKEY", self.sslkey),
            ("PGCHANNELBINDING", self.channel_binding),
        ):
            if value is not None:
                environment[name] = value
        return environment

    def connection_kwargs(self, *, application_name: str) -> dict[str, object]:
        """Return explicit psycopg kwargs after rejecting ambient libpq state."""

        _assert_no_ambient_libpq_environment()
        kwargs: dict[str, object] = {
            "dbname": self.database,
            "user": self.user,
            "host": self.host,
            "port": self.port,
            "connect_timeout": _CONNECT_TIMEOUT_SECONDS,
            "application_name": _control_free(
                application_name, label="PostgreSQL application name"
            ),
            "sslmode": self.sslmode,
            # Fixed options replace (rather than inherit) PGOPTIONS and bound
            # every catalog/row query and lock wait performed in-process.
            "options": (
                f"-c statement_timeout={_STATEMENT_TIMEOUT_MS} "
                f"-c lock_timeout={_LOCK_TIMEOUT_MS} "
                f"-c idle_in_transaction_session_timeout={_IDLE_TRANSACTION_TIMEOUT_MS}"
            ),
        }
        if self.password is not None:
            kwargs["password"] = self.password
        for name, value in (
            ("sslrootcert", self.sslrootcert),
            ("sslcert", self.sslcert),
            ("sslkey", self.sslkey),
            ("channel_binding", self.channel_binding),
        ):
            if value is not None:
                kwargs[name] = value
        return kwargs

    def _sqlalchemy_url(self) -> str:
        """Render only for the existing in-process strict status inspector."""

        query: dict[str, str] = {
            "sslmode": self.sslmode,
            "options": (
                f"-c statement_timeout={_STATEMENT_TIMEOUT_MS} "
                f"-c lock_timeout={_LOCK_TIMEOUT_MS} "
                f"-c idle_in_transaction_session_timeout={_IDLE_TRANSACTION_TIMEOUT_MS}"
            ),
        }
        host: str | None = self.host
        port: int | None = self.port
        if self.host.startswith("/"):
            host = None
            port = None
            query.update({"host": self.host, "port": str(self.port)})
        for name, value in (
            ("sslrootcert", self.sslrootcert),
            ("sslcert", self.sslcert),
            ("sslkey", self.sslkey),
            ("channel_binding", self.channel_binding),
        ):
            if value is not None:
                query[name] = value
        return URL.create(
            "postgresql+psycopg",
            username=self.user,
            password=self.password,
            host=host,
            port=port,
            database=self.database,
            query=query,
        ).render_as_string(hide_password=False)


def _assert_no_ambient_libpq_environment() -> None:
    inherited = sorted(name for name in os.environ if name.startswith("PG"))
    if inherited:
        raise RecoveryTargetError(
            "Ambient PG* connection variables are forbidden; use only the explicit typed target."
        )


def _coerce_connection_spec(value: object, *, role: str) -> PostgreSQLConnectionSpec:
    if not isinstance(value, PostgreSQLConnectionSpec):
        raise RecoveryTargetError(
            f"PostgreSQL {role} must be an explicit PostgreSQLConnectionSpec."
        )
    return value


def _canonical_database_identity_sha256(
    system_identifier: str, database_oid: str
) -> str:
    if (
        type(system_identifier) is not str
        or _NUMERIC_ID.fullmatch(system_identifier) is None
        or type(database_oid) is not str
        or _NUMERIC_ID.fullmatch(database_oid) is None
    ):
        raise RecoveryIntegrityError("PostgreSQL database identity is malformed.")
    identity = {
        "databaseOid": database_oid,
        "systemIdentifier": system_identifier,
    }
    return hashlib.sha256(canonical_recovery_json(identity).encode("ascii")).hexdigest()


def _require_target_id(target_id: object) -> str:
    if type(target_id) is not str or _STABLE_ID.fullmatch(target_id) is None:
        raise RecoveryTargetError("PostgreSQL restore target ID is not canonical.")
    return target_id


def _consumed_target_marker(target_id: str, archive_sha256: str) -> str:
    target = _require_target_id(target_id)
    if type(archive_sha256) is not str or _SHA256.fullmatch(archive_sha256) is None:
        raise RecoveryTargetError("PostgreSQL archive digest is not a full SHA-256.")
    return canonical_recovery_json(
        {
            "archiveSha256": archive_sha256,
            "kind": "ai_benchmark_recovery_consumed_v1",
            "targetId": target,
        }
    )


def _cancel(
    cancel_requested: Callable[[], bool] | None,
    *,
    phase: str,
    target_created: bool = False,
) -> None:
    if cancel_requested is None:
        return
    try:
        requested = bool(cancel_requested())
    except Exception:
        requested = True
    if requested:
        raise RecoveryCancelled(
            phase=phase,
            relational_target_created=target_created,
        )


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_PROCESS_STOP_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=_PROCESS_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        # The process is already isolated and SIGKILLed.  Do not attempt to
        # signal any broader process tree or turn stderr into a receipt.
        pass


def _run_pg_tool(
    argv: Sequence[str],
    *,
    environment: Mapping[str, str],
    phase: str,
    timeout_seconds: float,
    cancel_requested: Callable[[], bool] | None = None,
    target_created: bool = False,
    cwd: Path | None = None,
) -> bytes:
    if (
        type(timeout_seconds) not in {int, float}
        or not 0 < float(timeout_seconds) <= _MAX_COMMAND_TIMEOUT_SECONDS
    ):
        raise RecoveryTargetError("PostgreSQL tool timeout is outside the bounded range.")
    if not argv or argv[0] not in {str(PG_DUMP_PATH), str(PG_RESTORE_PATH)}:
        raise RecoveryTargetError("PostgreSQL tool invocation is not on the fixed allowlist.")
    if set(environment) & {"PGOPTIONS", "PGSERVICE", "PGSERVICEFILE", "PGPASSFILE"}:
        raise RecoveryTargetError("PostgreSQL tool environment includes a forbidden libpq input.")
    if any(name.startswith("PG") and name not in {
        "PGAPPNAME", "PGCHANNELBINDING", "PGCONNECT_TIMEOUT", "PGDATABASE",
        "PGHOST", "PGPASSWORD", "PGPORT", "PGSSLCERT", "PGSSLKEY",
        "PGSSLMODE", "PGSSLROOTCERT", "PGUSER"
    } for name in environment):
        raise RecoveryTargetError("PostgreSQL tool environment is outside the allowlist.")
    _cancel(cancel_requested, phase=phase, target_created=target_created)
    try:
        process = subprocess.Popen(
            tuple(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            # Provider/libpq diagnostics can echo locators or credentials and
            # are not acceptance evidence.  Discard them at the descriptor
            # boundary instead of buffering or attaching them to exceptions.
            stderr=subprocess.DEVNULL,
            env=dict(environment),
            cwd=str(cwd) if cwd is not None else "/",
            close_fds=True,
            start_new_session=True,
        )
    except (OSError, ValueError):
        raise RecoveryPartialFailure(
            "POSTGRESQL_TOOL_START_FAILED",
            phase=phase,
            relational_target_created=target_created,
        ) from None
    deadline = time.monotonic() + float(timeout_seconds)
    try:
        while True:
            try:
                _cancel(
                    cancel_requested,
                    phase=phase,
                    target_created=target_created,
                )
            except RecoveryCancelled:
                _terminate_process_group(process)
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_group(process)
                raise RecoveryPartialFailure(
                    "POSTGRESQL_TOOL_TIMEOUT",
                    phase=phase,
                    relational_target_created=target_created,
                )
            try:
                stdout, _discarded_stderr = process.communicate(
                    timeout=min(_POLL_SECONDS, remaining)
                )
                break
            except subprocess.TimeoutExpired:
                continue
    except Exception as exc:
        if process.poll() is None:
            _terminate_process_group(process)
        if isinstance(exc, (RecoveryCancelled, RecoveryPartialFailure)):
            raise
        raise RecoveryPartialFailure(
            "POSTGRESQL_TOOL_RUNTIME_FAILED",
            phase=phase,
            relational_target_created=target_created,
        ) from None
    except BaseException:
        if process.poll() is None:
            _terminate_process_group(process)
        raise
    if process.returncode != 0:
        raise RecoveryPartialFailure(
            "POSTGRESQL_TOOL_FAILED",
            phase=phase,
            relational_target_created=target_created,
        )
    _cancel(cancel_requested, phase=phase, target_created=target_created)
    return stdout


def _private_write(path: Path, raw_bytes: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(raw_bytes)
        offset = 0
        while offset < len(view):
            count = os.write(descriptor, view[offset:])
            if count <= 0:
                raise OSError("short private write")
            offset += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_tool_binary(path: Path) -> None:
    if not path.is_absolute() or path.resolve(strict=False) != path:
        raise RecoveryTargetError("PostgreSQL tool path is not the fixed canonical binary.")
    try:
        metadata = path.lstat()
    except OSError:
        raise RecoveryTargetError("Required PostgreSQL 16 tool is unavailable.") from None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not os.access(path, os.X_OK)
    ):
        raise RecoveryTargetError("PostgreSQL 16 tool binary posture is unsafe.")


def _parse_tool_version(path: Path, *, timeout_seconds: float) -> str:
    _require_tool_binary(path)
    output = _run_pg_tool(
        (str(path), "--version"),
        environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        phase="postgresql_tool_version",
        timeout_seconds=min(timeout_seconds, 30.0),
    )
    match = _TOOL_VERSION.match(output.strip())
    if match is None:
        raise UnsupportedRecoveryArtifact("PostgreSQL tool version output is unsupported.")
    version = match.group(1).decode("ascii")
    if int(version.split(".", 1)[0]) != _SUPPORTED_MAJOR:
        raise UnsupportedRecoveryArtifact("PostgreSQL tool major version is unsupported.")
    return version


def _toolchain_version(*, timeout_seconds: float) -> str:
    dump_version = _parse_tool_version(PG_DUMP_PATH, timeout_seconds=timeout_seconds)
    restore_version = _parse_tool_version(PG_RESTORE_PATH, timeout_seconds=timeout_seconds)
    if dump_version != restore_version:
        raise UnsupportedRecoveryArtifact("pg_dump and pg_restore versions do not match.")
    return dump_version


def _archive_restore_argv(
    *, database_name: str, archive_path: str, toc_path: str
) -> tuple[str, ...]:
    database = _control_free(database_name, label="PostgreSQL database")
    return (
        str(PG_RESTORE_PATH),
        "--dbname",
        database,
        "--exit-on-error",
        "--single-transaction",
        "--schema=public",
        "--no-owner",
        "--no-privileges",
        "--use-list",
        toc_path,
        archive_path,
    )


def _filter_public_schema_toc(raw_bytes: bytes) -> bytes:
    """Reject recoverable security/database posture and omit one schema entry."""

    if type(raw_bytes) is not bytes:
        raise RecoveryIntegrityError("PostgreSQL archive TOC is not bytes.")
    try:
        document = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise RecoveryIntegrityError("PostgreSQL archive TOC is not UTF-8.") from None
    if "\x00" in document or "\r" in document:
        raise RecoveryIntegrityError("PostgreSQL archive TOC encoding is noncanonical.")
    lines = document.splitlines()
    public_schema_indexes: list[int] = []
    table_count = 0
    table_data_count = 0
    for index, line in enumerate(lines):
        if not line or line.startswith(";"):
            continue
        if _PUBLIC_SCHEMA_TOC.fullmatch(line):
            public_schema_indexes.append(index)
            continue
        if _TABLE_TOC.fullmatch(line):
            table_count += 1
        if _TABLE_DATA_TOC.fullmatch(line):
            table_data_count += 1
        upper = f" {line.upper()} "
        if (
            " ACL " in upper
            or " DEFAULT ACL " in upper
            or re.search(r";\s+[0-9]+\s+[0-9]+\s+DATABASE\s", line, re.IGNORECASE)
            or re.search(r";\s+[0-9]+\s+[0-9]+\s+COMMENT\s+-\s+DATABASE\s", line, re.IGNORECASE)
            or re.search(r";\s+[0-9]+\s+[0-9]+\s+(?:BLOB|LARGE OBJECT)", line, re.IGNORECASE)
            or re.search(r";\s+[0-9]+\s+[0-9]+\s+EXTENSION\s", line, re.IGNORECASE)
        ):
            raise UnsupportedRecoveryArtifact(
                "PostgreSQL archive carries excluded role/ACL/database/opaque-object posture."
            )
    if len(public_schema_indexes) != 1:
        raise RecoveryIntegrityError(
            "PostgreSQL archive must contain exactly one public SCHEMA create entry."
        )
    if table_count != 1 or table_data_count != 1:
        raise RecoveryIntegrityError(
            "PostgreSQL archive lacks the exact Alembic table/data denominator."
        )
    omitted = public_schema_indexes[0]
    filtered = [line for index, line in enumerate(lines) if index != omitted]
    return ("\n".join(filtered) + "\n").encode("utf-8")


def _normalize_schema_dump(raw_bytes: bytes) -> bytes:
    """Canonicalize only the paired pg_dump restrict nonce."""

    if type(raw_bytes) is not bytes or b"\x00" in raw_bytes:
        raise RecoveryIntegrityError("PostgreSQL schema dump is not canonical bytes.")
    normalized_newlines = raw_bytes.replace(b"\r\n", b"\n")
    if b"\r" in normalized_newlines:
        raise RecoveryIntegrityError("PostgreSQL schema dump has unsupported line endings.")
    for pattern in _FORBIDDEN_SCHEMA_STATEMENTS:
        if pattern.search(normalized_newlines):
            raise UnsupportedRecoveryArtifact(
                "PostgreSQL schema equivalence input contains excluded owner/ACL posture."
            )
    lines = normalized_newlines.splitlines()
    restrict: list[tuple[int, bytes]] = []
    unrestrict: list[tuple[int, bytes]] = []
    for index, line in enumerate(lines):
        match = _RESTRICT_LINE.fullmatch(line)
        if match is None:
            continue
        destination = restrict if match.group(1) == b"restrict" else unrestrict
        destination.append((index, match.group(2)))
    if len(restrict) != 1 or len(unrestrict) != 1 or restrict[0][1] != unrestrict[0][1]:
        raise RecoveryIntegrityError(
            "PostgreSQL schema dump restrict/unrestrict nonce pair is invalid."
        )
    lines[restrict[0][0]] = b"\\restrict " + _SCHEMA_NONCE
    lines[unrestrict[0][0]] = b"\\unrestrict " + _SCHEMA_NONCE
    return b"\n".join(lines) + b"\n"


def _open_connection(
    spec: PostgreSQLConnectionSpec,
    *,
    application_name: str,
    autocommit: bool,
) -> psycopg.Connection[Any]:
    try:
        connection = psycopg.connect(
            **spec.connection_kwargs(application_name=application_name),
            autocommit=autocommit,
        )
    except (psycopg.Error, OSError, ValueError):
        raise RecoveryTargetError(
            "PostgreSQL connection failed closed; no locator detail is retained."
        ) from None
    return connection


def _server_version(version_number: object) -> str:
    if type(version_number) not in {str, int}:
        raise RecoveryIntegrityError("PostgreSQL server version is malformed.")
    try:
        numeric = int(version_number)
    except ValueError:
        raise RecoveryIntegrityError("PostgreSQL server version is malformed.") from None
    major = numeric // 10000
    patch = numeric % 10000
    if major != _SUPPORTED_MAJOR:
        raise UnsupportedRecoveryArtifact(
            "PostgreSQL recovery supports only server major version 16."
        )
    return f"{major}.{patch}"


@dataclass(frozen=True, slots=True)
class _DatabaseScopeFacts:
    """Exact PostgreSQL 16 empty-database side-effect denominator.

    Namespaced application objects are inspected separately.  This census
    covers database-local objects with no namespace plus database-targeted
    shared/runtime state.  Cluster-global roles/memberships, parameter ACLs,
    physical replication slots, replication origins, tablespaces, locale and
    transaction-maintenance counters are deliberately excluded: they cannot
    be attributed to one restore target and remain provider/operator posture,
    not recoverable database content.  Active sessions and locks are also
    excluded because this inspection connection necessarily creates them.
    """

    database_acl_is_null: bool
    database_allows_connections: bool
    database_connection_limit: int
    public_schema_acl_is_canonical: bool
    extension_baseline_is_canonical: bool
    language_baseline_is_canonical: bool
    publication_count: int
    publication_relation_count: int
    publication_namespace_count: int
    subscription_count: int
    subscription_relation_count: int
    event_trigger_count: int
    large_object_count: int
    large_object_page_count: int
    database_role_setting_count: int
    foreign_data_wrapper_count: int
    foreign_server_count: int
    user_mapping_count: int
    default_acl_count: int
    security_label_count: int
    database_security_label_count: int
    transform_count: int
    non_initdb_cast_count: int
    non_initdb_access_method_count: int
    row_security_policy_count: int
    non_initdb_rewrite_count: int
    prepared_transaction_count: int
    logical_replication_slot_count: int

    @property
    def material(self) -> dict[str, bool | int]:
        return {
            name: getattr(self, name)
            for name in _DATABASE_SCOPE_FIELD_NAMES
        }

    @property
    def fingerprint_sha256(self) -> str:
        return hashlib.sha256(
            canonical_recovery_json(self.material).encode("ascii")
        ).hexdigest()

    @property
    def is_canonical_empty(self) -> bool:
        return self == _CANONICAL_EMPTY_DATABASE_SCOPE

    @property
    def is_safe_backup_source(self) -> bool:
        """Allow provider ACL/routing posture, reject every omitted side effect."""

        return all(
            getattr(self, name) == getattr(_CANONICAL_EMPTY_DATABASE_SCOPE, name)
            for name in _DATABASE_SCOPE_FIELD_NAMES
            if name not in _SOURCE_SCOPE_PROVIDER_POSTURE_FIELDS
        )


@dataclass(frozen=True, slots=True)
class _DatabaseFacts:
    database_name: str
    identity_sha256: str
    engine_version: str
    database_comment: str | None
    database_owner: str
    current_user: str
    is_template: bool
    public_object_count: int
    extra_non_system_schema_count: int
    database_scope: _DatabaseScopeFacts

    @property
    def database_scope_sha256(self) -> str:
        return self.database_scope.fingerprint_sha256


@dataclass(frozen=True, slots=True)
class _StrictHeadProof:
    """Capability token issued only by the reviewed strict status inspector."""

    schema_revision: str
    operational_constraint_inventory_sha256: str
    operational_index_inventory_sha256: str


_PUBLIC_OBJECT_COUNT_SQL = """
WITH target_namespace AS (
    SELECT oid FROM pg_namespace WHERE nspname = 'public'
)
SELECT
      (SELECT COUNT(*) FROM pg_class WHERE relnamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_proc WHERE pronamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_type WHERE typnamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_collation WHERE collnamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_conversion WHERE connamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_operator WHERE oprnamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_opclass WHERE opcnamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_opfamily WHERE opfnamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_ts_config WHERE cfgnamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_ts_dict WHERE dictnamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_ts_parser WHERE prsnamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_ts_template WHERE tmplnamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_statistic_ext WHERE stxnamespace IN (SELECT oid FROM target_namespace))
    + (SELECT COUNT(*) FROM pg_extension WHERE extnamespace IN (SELECT oid FROM target_namespace))
"""


_DATABASE_SCOPE_FIELD_NAMES = (
    "database_acl_is_null",
    "database_allows_connections",
    "database_connection_limit",
    "public_schema_acl_is_canonical",
    "extension_baseline_is_canonical",
    "language_baseline_is_canonical",
    "publication_count",
    "publication_relation_count",
    "publication_namespace_count",
    "subscription_count",
    "subscription_relation_count",
    "event_trigger_count",
    "large_object_count",
    "large_object_page_count",
    "database_role_setting_count",
    "foreign_data_wrapper_count",
    "foreign_server_count",
    "user_mapping_count",
    "default_acl_count",
    "security_label_count",
    "database_security_label_count",
    "transform_count",
    "non_initdb_cast_count",
    "non_initdb_access_method_count",
    "row_security_policy_count",
    "non_initdb_rewrite_count",
    "prepared_transaction_count",
    "logical_replication_slot_count",
)
_SOURCE_SCOPE_PROVIDER_POSTURE_FIELDS = frozenset(
    {
        "database_acl_is_null",
        "database_allows_connections",
        "database_connection_limit",
        "public_schema_acl_is_canonical",
    }
)
_DATABASE_SCOPE_BOOLEAN_FIELDS = frozenset(
    {
        "database_acl_is_null",
        "database_allows_connections",
        "public_schema_acl_is_canonical",
        "extension_baseline_is_canonical",
        "language_baseline_is_canonical",
    }
)
_CANONICAL_EMPTY_DATABASE_SCOPE = _DatabaseScopeFacts(
    database_acl_is_null=True,
    database_allows_connections=True,
    database_connection_limit=-1,
    public_schema_acl_is_canonical=True,
    extension_baseline_is_canonical=True,
    language_baseline_is_canonical=True,
    publication_count=0,
    publication_relation_count=0,
    publication_namespace_count=0,
    subscription_count=0,
    subscription_relation_count=0,
    event_trigger_count=0,
    large_object_count=0,
    large_object_page_count=0,
    database_role_setting_count=0,
    foreign_data_wrapper_count=0,
    foreign_server_count=0,
    user_mapping_count=0,
    default_acl_count=0,
    security_label_count=0,
    database_security_label_count=0,
    transform_count=0,
    non_initdb_cast_count=0,
    non_initdb_access_method_count=0,
    row_security_policy_count=0,
    non_initdb_rewrite_count=0,
    prepared_transaction_count=0,
    logical_replication_slot_count=0,
)


# PostgreSQL's FirstNormalObjectId is the deterministic initdb/user boundary.
# Built-in PG16 casts, access methods and rewrite rules are pinned below it;
# pg_upgrade preserves those OIDs.  The same census separately requires the
# one accepted extension to be stock plpgsql, which contributes none of these
# object kinds, so an extension row cannot be mistaken for accepted baseline.
_DATABASE_SCOPE_SQL = f"""
WITH current_database_catalog AS (
    SELECT database_catalog.*
    FROM pg_database AS database_catalog
    WHERE database_catalog.datname = current_database()
)
SELECT
    database_catalog.datacl IS NULL AS database_acl_is_null,
    database_catalog.datallowconn AS database_allows_connections,
    database_catalog.datconnlimit AS database_connection_limit,
    (
        SELECT
            COUNT(*) = 3
            AND COUNT(*) FILTER (
                WHERE acl.grantor = namespace.nspowner
            ) = 3
            AND COUNT(*) FILTER (
                WHERE acl.grantee = 0
                  AND acl.privilege_type = 'USAGE'
                  AND NOT acl.is_grantable
            ) = 1
            AND COUNT(*) FILTER (
                WHERE acl.grantee = namespace.nspowner
                  AND acl.privilege_type IN ('CREATE', 'USAGE')
                  AND NOT acl.is_grantable
            ) = 2
        FROM pg_namespace AS namespace
        CROSS JOIN LATERAL aclexplode(namespace.nspacl) AS acl
        WHERE namespace.nspname = 'public'
          AND pg_get_userbyid(namespace.nspowner) = 'pg_database_owner'
    ) AS public_schema_acl_is_canonical,
    (
        SELECT
            COUNT(*) = 1
            AND COUNT(*) FILTER (
                WHERE extension_object.extname = 'plpgsql'
                  AND namespace.nspname = 'pg_catalog'
                  AND extension_object.extversion = '1.0'
                  AND NOT extension_object.extrelocatable
                  AND extension_object.extconfig IS NULL
                  AND extension_object.extcondition IS NULL
            ) = 1
        FROM pg_extension AS extension_object
        JOIN pg_namespace AS namespace
          ON namespace.oid = extension_object.extnamespace
    ) AS extension_baseline_is_canonical,
    (
        SELECT
            COUNT(*) = 4
            AND COUNT(*) FILTER (
                WHERE language_object.lanname = 'internal'
                  AND NOT language_object.lanispl
                  AND NOT language_object.lanpltrusted
                  AND language_object.lanacl IS NULL
            ) = 1
            AND COUNT(*) FILTER (
                WHERE language_object.lanname = 'c'
                  AND NOT language_object.lanispl
                  AND NOT language_object.lanpltrusted
                  AND language_object.lanacl IS NULL
            ) = 1
            AND COUNT(*) FILTER (
                WHERE language_object.lanname = 'sql'
                  AND NOT language_object.lanispl
                  AND language_object.lanpltrusted
                  AND language_object.lanacl IS NULL
            ) = 1
            AND COUNT(*) FILTER (
                WHERE language_object.lanname = 'plpgsql'
                  AND language_object.lanispl
                  AND language_object.lanpltrusted
                  AND language_object.lanacl IS NULL
            ) = 1
        FROM pg_language AS language_object
    ) AS language_baseline_is_canonical,
    (SELECT COUNT(*) FROM pg_publication) AS publication_count,
    (SELECT COUNT(*) FROM pg_publication_rel) AS publication_relation_count,
    (SELECT COUNT(*) FROM pg_publication_namespace) AS publication_namespace_count,
    (
        SELECT COUNT(*)
        FROM pg_subscription AS subscription
        WHERE subscription.subdbid = database_catalog.oid
    ) AS subscription_count,
    (
        SELECT COUNT(*)
        FROM pg_subscription_rel AS subscription_relation
        JOIN pg_subscription AS subscription
          ON subscription.oid = subscription_relation.srsubid
        WHERE subscription.subdbid = database_catalog.oid
    ) AS subscription_relation_count,
    (SELECT COUNT(*) FROM pg_event_trigger) AS event_trigger_count,
    (SELECT COUNT(*) FROM pg_largeobject_metadata) AS large_object_count,
    (SELECT COUNT(*) FROM pg_largeobject) AS large_object_page_count,
    (
        SELECT COUNT(*)
        FROM pg_db_role_setting AS role_setting
        WHERE role_setting.setdatabase = database_catalog.oid
    ) AS database_role_setting_count,
    (SELECT COUNT(*) FROM pg_foreign_data_wrapper) AS foreign_data_wrapper_count,
    (SELECT COUNT(*) FROM pg_foreign_server) AS foreign_server_count,
    (SELECT COUNT(*) FROM pg_user_mapping) AS user_mapping_count,
    (SELECT COUNT(*) FROM pg_default_acl) AS default_acl_count,
    (SELECT COUNT(*) FROM pg_seclabel) AS security_label_count,
    (
        SELECT COUNT(*)
        FROM pg_shseclabel AS security_label
        WHERE security_label.classoid = 'pg_database'::regclass
          AND security_label.objoid = database_catalog.oid
    ) AS database_security_label_count,
    (SELECT COUNT(*) FROM pg_transform) AS transform_count,
    (
        SELECT COUNT(*) FROM pg_cast
        WHERE oid >= {_FIRST_NORMAL_OBJECT_ID}
    ) AS non_initdb_cast_count,
    (
        SELECT COUNT(*) FROM pg_am
        WHERE oid >= {_FIRST_NORMAL_OBJECT_ID}
    ) AS non_initdb_access_method_count,
    (SELECT COUNT(*) FROM pg_policy) AS row_security_policy_count,
    (
        SELECT COUNT(*) FROM pg_rewrite
        WHERE oid >= {_FIRST_NORMAL_OBJECT_ID}
    ) AS non_initdb_rewrite_count,
    (
        SELECT COUNT(*)
        FROM pg_prepared_xacts AS prepared_transaction
        WHERE prepared_transaction.database = current_database()
    ) AS prepared_transaction_count,
    (
        SELECT COUNT(*)
        FROM pg_replication_slots AS replication_slot
        WHERE replication_slot.database = current_database()
    ) AS logical_replication_slot_count
FROM current_database_catalog AS database_catalog
"""


def _database_scope_facts(raw: object) -> _DatabaseScopeFacts:
    if not isinstance(raw, (tuple, list)) or len(raw) != len(
        _DATABASE_SCOPE_FIELD_NAMES
    ):
        raise RecoveryIntegrityError(
            "PostgreSQL database-scope census returned a malformed denominator."
        )
    values = dict(zip(_DATABASE_SCOPE_FIELD_NAMES, raw, strict=True))
    for name, value in values.items():
        if name in _DATABASE_SCOPE_BOOLEAN_FIELDS:
            if type(value) is not bool:
                raise RecoveryIntegrityError(
                    "PostgreSQL database-scope boolean fact is malformed."
                )
        elif type(value) is not int or (
            name != "database_connection_limit" and value < 0
        ):
            raise RecoveryIntegrityError(
                "PostgreSQL database-scope count fact is malformed."
            )
    return _DatabaseScopeFacts(**values)


def _database_facts(connection: psycopg.Connection[Any]) -> _DatabaseFacts:
    try:
        identity = connection.execute(
            """
            SELECT
                current_database(),
                (pg_control_system()).system_identifier::text,
                database_catalog.oid::text,
                current_setting('server_version_num'),
                shobj_description(database_catalog.oid, 'pg_database'),
                pg_get_userbyid(database_catalog.datdba),
                current_user,
                database_catalog.datistemplate
            FROM pg_database AS database_catalog
            WHERE database_catalog.datname = current_database()
            """
        ).fetchone()
        public_namespaces = int(
            connection.execute(
                "SELECT COUNT(*) FROM pg_namespace WHERE nspname = 'public'"
            ).fetchone()[0]
        )
        public_object_count = int(connection.execute(_PUBLIC_OBJECT_COUNT_SQL).fetchone()[0])
        extra_non_system_schema_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM pg_namespace
                WHERE nspname <> 'public'
                  AND nspname <> 'information_schema'
                  AND nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
                """
            ).fetchone()[0]
        )
        database_scope = _database_scope_facts(
            connection.execute(_DATABASE_SCOPE_SQL).fetchone()
        )
    except (psycopg.Error, TypeError, ValueError, IndexError):
        raise RecoveryIntegrityError(
            "PostgreSQL database identity/catalog inspection failed closed."
        ) from None
    if identity is None or len(identity) != 8 or public_namespaces != 1:
        raise RecoveryIntegrityError(
            "PostgreSQL target lacks one canonical public schema or database identity."
        )
    database_name = _control_free(identity[0], label="PostgreSQL current database")
    comment = identity[4]
    if comment is not None and type(comment) is not str:
        raise RecoveryIntegrityError("PostgreSQL database comment has an invalid type.")
    return _DatabaseFacts(
        database_name=database_name,
        identity_sha256=_canonical_database_identity_sha256(identity[1], identity[2]),
        engine_version=_server_version(identity[3]),
        database_comment=comment,
        database_owner=_control_free(identity[5], label="PostgreSQL database owner"),
        current_user=_control_free(identity[6], label="PostgreSQL current user"),
        is_template=bool(identity[7]),
        public_object_count=public_object_count,
        extra_non_system_schema_count=extra_non_system_schema_count,
        database_scope=database_scope,
    )


def _read_database_facts(
    spec: PostgreSQLConnectionSpec, *, application_name: str
) -> _DatabaseFacts:
    connection = _open_connection(
        spec,
        application_name=application_name,
        autocommit=True,
    )
    try:
        return _database_facts(connection)
    finally:
        connection.close()


def _assert_safe_backup_source_scope(facts: _DatabaseFacts) -> None:
    if not facts.database_scope.is_safe_backup_source:
        raise RecoveryTargetError(
            "PostgreSQL backup source contains executable, external, or "
            "opaque database-scoped state omitted by the contained archive."
        )


def _consume_fresh_target(
    spec: PostgreSQLConnectionSpec,
    *,
    artifact: RelationalBackupArtifact,
    target_id: str,
) -> tuple[_DatabaseFacts, str]:
    archive_sha256 = compute_content_hash(artifact.raw_bytes)
    marker = _consumed_target_marker(target_id, archive_sha256)
    connection = _open_connection(
        spec,
        application_name="ai-benchmark-recovery-target-fence",
        autocommit=True,
    )
    try:
        before = _database_facts(connection)
        if before.identity_sha256 == artifact.source_database_identity_sha256:
            raise RecoveryTargetError(
                "PostgreSQL restore target is the immutable backup source database."
            )
        if before.is_template:
            raise RecoveryTargetError(
                "PostgreSQL restore target must not be a template database."
            )
        if before.current_user != before.database_owner:
            raise RecoveryTargetError(
                "PostgreSQL restore requires the explicit target database owner."
            )
        if before.database_comment is not None:
            raise RecoveryTargetError(
                "PostgreSQL restore target was already consumed or carries a database comment."
            )
        if before.public_object_count != 0:
            raise RecoveryTargetError(
                "PostgreSQL restore target public schema is not empty."
            )
        if before.extra_non_system_schema_count != 0:
            raise RecoveryTargetError(
                "PostgreSQL restore target contains an extra non-system schema."
            )
        if not before.database_scope.is_canonical_empty:
            raise RecoveryTargetError(
                "PostgreSQL restore target database-scoped state is not the "
                "canonical empty PostgreSQL 16 baseline."
            )
        # COMMENT is its own autocommit transaction.  It intentionally remains
        # after every later cancellation/failure so this target cannot be
        # mistaken for fresh or silently reused.
        connection.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(before.database_name),
                sql.Literal(marker),
            )
        )
        after = _database_facts(connection)
    except (RecoveryTargetError, RecoveryIntegrityError):
        raise
    except psycopg.Error:
        raise RecoveryPartialFailure(
            "POSTGRESQL_TARGET_MARKER_FAILED",
            phase="relational_target_fence",
            relational_target_created=False,
        ) from None
    finally:
        connection.close()
    if (
        after.identity_sha256 != before.identity_sha256
        or after.database_comment != marker
        or after.public_object_count != 0
        or after.is_template
        or after.database_owner != before.database_owner
        or after.current_user != before.current_user
        or after.extra_non_system_schema_count != 0
        or not after.database_scope.is_canonical_empty
        or after.database_scope_sha256 != before.database_scope_sha256
    ):
        raise RecoveryIntegrityError(
            "PostgreSQL consumed-target marker did not durably re-resolve."
        )
    return after, marker


def _assert_target_marker(
    spec: PostgreSQLConnectionSpec,
    *,
    expected_identity_sha256: str,
    expected_marker: str,
    expected_database_scope_sha256: str,
) -> _DatabaseFacts:
    facts = _read_database_facts(
        spec, application_name="ai-benchmark-recovery-target-verify"
    )
    if (
        facts.identity_sha256 != expected_identity_sha256
        or facts.database_comment != expected_marker
        or facts.is_template
        or facts.database_owner != facts.current_user
        or facts.extra_non_system_schema_count != 0
        or not facts.database_scope.is_canonical_empty
        or facts.database_scope_sha256 != expected_database_scope_sha256
    ):
        raise RecoveryIntegrityError(
            "PostgreSQL restore target identity or durable marker changed."
        )
    return facts


def _apply_restore_safety_floor(
    spec: PostgreSQLConnectionSpec,
    *,
    expected_identity_sha256: str,
    expected_marker: str,
    expected_database_scope_sha256: str,
) -> None:
    connection = _open_connection(
        spec,
        application_name="ai-benchmark-recovery-safety-floor",
        autocommit=True,
    )
    try:
        facts = _database_facts(connection)
        if (
            facts.identity_sha256 != expected_identity_sha256
            or facts.database_comment != expected_marker
            or not facts.database_scope.is_canonical_empty
            or facts.database_scope_sha256 != expected_database_scope_sha256
        ):
            raise RecoveryIntegrityError(
                "PostgreSQL restore safety floor target binding changed."
            )
        # This is deliberately literal, grants nothing, and is not evidence
        # that archive owners, role memberships, ACLs, or provider access
        # posture were restored.
        connection.execute(_SAFETY_FLOOR_SQL)
    except RecoveryIntegrityError:
        raise
    except psycopg.Error:
        raise RecoveryPartialFailure(
            "POSTGRESQL_RESTORE_SAFETY_FLOOR_FAILED",
            phase="relational_restore_safety_floor",
            relational_target_created=True,
        ) from None
    finally:
        connection.close()


def _strict_current_head(spec: PostgreSQLConnectionSpec) -> _StrictHeadProof:
    _assert_no_ambient_libpq_environment()
    try:
        status = inspect_database(spec._sqlalchemy_url())
        expected_revision = head_revision()
    except Exception:
        raise RecoveryIntegrityError(
            "Restored PostgreSQL target strict inspection failed closed."
        ) from None
    if (
        status.kind != "current"
        or status.revision != expected_revision
        or not status.integrity_ok
        or status.foreign_key_violations != 0
    ):
        raise RecoveryIntegrityError(
            "Restored PostgreSQL target failed strict current-head inspection."
        )
    return _StrictHeadProof(
        schema_revision=expected_revision,
        operational_constraint_inventory_sha256=(
            POSTGRESQL_OPERATIONAL_CONSTRAINT_INVENTORY_SHA256
        ),
        operational_index_inventory_sha256=(
            POSTGRESQL_OPERATIONAL_INDEX_INVENTORY_SHA256
        ),
    )


def _validate_public_relation_rows(
    relations: Sequence[tuple[str, str, str | None]],
    *,
    strict_head_proof: _StrictHeadProof,
) -> None:
    """Bind full relations to explicit legacy names plus pinned DATA-09 proof."""

    if (
        not isinstance(strict_head_proof, _StrictHeadProof)
        or strict_head_proof.schema_revision != head_revision()
        or strict_head_proof.operational_constraint_inventory_sha256
        != POSTGRESQL_OPERATIONAL_CONSTRAINT_INVENTORY_SHA256
        or strict_head_proof.operational_index_inventory_sha256
        != POSTGRESQL_OPERATIONAL_INDEX_INVENTORY_SHA256
    ):
        raise RecoveryIntegrityError(
            "PostgreSQL relation census lacks the pinned strict-head proof."
        )
    normalized = [(str(name), str(kind), owner) for name, kind, owner in relations]
    if len({name for name, _kind, _owner in normalized}) != len(normalized):
        raise RecoveryIntegrityError("PostgreSQL public relation identity is duplicated.")
    table_rows = {
        name for name, kind, owner in normalized if kind == "r" and owner is None
    }
    if table_rows != set(expected_head_columns()):
        raise RecoveryIntegrityError(
            "PostgreSQL public table relation denominator differs from reviewed head."
        )
    if any(kind not in {"r", "i"} for _name, kind, _owner in normalized):
        raise RecoveryIntegrityError(
            "PostgreSQL public schema contains an unsupported relation kind."
        )
    if any(
        owner is not None for _name, kind, owner in normalized if kind == "r"
    ):
        raise RecoveryIntegrityError("PostgreSQL table relation has index ownership metadata.")
    index_rows = {
        name: owner for name, kind, owner in normalized if kind == "i"
    }
    if any(owner is None for owner in index_rows.values()):
        raise RecoveryIntegrityError("PostgreSQL index lacks its owning table identity.")
    expected_nonoperational_indexes = {
        name: definition[0]
        for name, definition in POSTGRESQL_REQUIRED_INDEXES.items()
    }
    expected_nonoperational_indexes.update(
        {
            name: POSTGRESQL_REQUIRED_CONSTRAINT_TABLES[name]
            for name, definition in POSTGRESQL_REQUIRED_CONSTRAINTS.items()
            if definition.startswith(("PRIMARY KEY", "UNIQUE"))
        }
    )
    actual_nonoperational_indexes = {
        name: owner
        for name, owner in index_rows.items()
        if owner not in POSTGRESQL_OPERATIONAL_TABLES
    }
    if actual_nonoperational_indexes != expected_nonoperational_indexes:
        raise RecoveryIntegrityError(
            "PostgreSQL non-operational index denominator differs from reviewed head."
        )
    # Every remaining index belongs to a DATA-09 operational table.  Its exact
    # constraint/non-constraint catalog row was already checked by the two
    # pinned inventory digests represented by strict_head_proof.  This avoids
    # inventing a second, incomplete list of the 0010 relation names.
    if any(
        owner not in POSTGRESQL_OPERATIONAL_TABLES
        for name, owner in index_rows.items()
        if name not in expected_nonoperational_indexes
    ):
        raise RecoveryIntegrityError(
            "PostgreSQL index is outside the reviewed operational/legacy domains."
        )


def _strict_public_object_denominator(
    spec: PostgreSQLConnectionSpec,
    *,
    strict_head_proof: _StrictHeadProof,
) -> None:
    """Reject every public catalog object outside the reviewed schema head."""

    connection = _open_connection(
        spec,
        application_name="ai-benchmark-recovery-executable-denominator",
        autocommit=True,
    )
    try:
        functions = [
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                """
                SELECT function_object.proname, function_object.prokind
                FROM pg_proc AS function_object
                JOIN pg_namespace AS namespace
                  ON namespace.oid = function_object.pronamespace
                WHERE namespace.nspname = 'public'
                ORDER BY function_object.proname, function_object.oid
                """
            ).fetchall()
        ]
        public_extensions = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM pg_extension AS extension_object
                JOIN pg_namespace AS namespace
                  ON namespace.oid = extension_object.extnamespace
                WHERE namespace.nspname = 'public'
                """
            ).fetchone()[0]
        )
        relations = [
            (str(row[0]), str(row[1]), str(row[2]) if row[2] is not None else None)
            for row in connection.execute(
                """
                SELECT relation.relname, relation.relkind, owning_table.relname
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                LEFT JOIN pg_index AS index_catalog
                  ON index_catalog.indexrelid = relation.oid
                LEFT JOIN pg_class AS owning_table
                  ON owning_table.oid = index_catalog.indrelid
                WHERE namespace.nspname = 'public'
                ORDER BY relation.relname, relation.oid
                """
            ).fetchall()
        ]
        public_type_count, unattached_type_count = (
            int(value)
            for value in connection.execute(
                """
                WITH relation_types AS (
                    SELECT relation.reltype
                    FROM pg_class AS relation
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relkind = 'r'
                )
                SELECT
                    COUNT(*),
                    COUNT(*) FILTER (
                        WHERE type_object.oid NOT IN (SELECT reltype FROM relation_types)
                          AND type_object.typelem NOT IN (SELECT reltype FROM relation_types)
                    )
                FROM pg_type AS type_object
                JOIN pg_namespace AS namespace
                  ON namespace.oid = type_object.typnamespace
                WHERE namespace.nspname = 'public'
                """
            ).fetchone()
        )
        other_public_objects = int(
            connection.execute(
                """
                WITH target_namespace AS (
                    SELECT oid FROM pg_namespace WHERE nspname = 'public'
                )
                SELECT
                      (SELECT COUNT(*) FROM pg_collation WHERE collnamespace IN (SELECT oid FROM target_namespace))
                    + (SELECT COUNT(*) FROM pg_conversion WHERE connamespace IN (SELECT oid FROM target_namespace))
                    + (SELECT COUNT(*) FROM pg_operator WHERE oprnamespace IN (SELECT oid FROM target_namespace))
                    + (SELECT COUNT(*) FROM pg_opclass WHERE opcnamespace IN (SELECT oid FROM target_namespace))
                    + (SELECT COUNT(*) FROM pg_opfamily WHERE opfnamespace IN (SELECT oid FROM target_namespace))
                    + (SELECT COUNT(*) FROM pg_ts_config WHERE cfgnamespace IN (SELECT oid FROM target_namespace))
                    + (SELECT COUNT(*) FROM pg_ts_dict WHERE dictnamespace IN (SELECT oid FROM target_namespace))
                    + (SELECT COUNT(*) FROM pg_ts_parser WHERE prsnamespace IN (SELECT oid FROM target_namespace))
                    + (SELECT COUNT(*) FROM pg_ts_template WHERE tmplnamespace IN (SELECT oid FROM target_namespace))
                    + (SELECT COUNT(*) FROM pg_statistic_ext WHERE stxnamespace IN (SELECT oid FROM target_namespace))
                """
            ).fetchone()[0]
        )
    except (psycopg.Error, TypeError, ValueError, IndexError):
        raise RecoveryIntegrityError(
            "Restored PostgreSQL executable-object census failed closed."
        ) from None
    finally:
        connection.close()
    expected = sorted((name, "f") for name in POSTGRESQL_REQUIRED_FUNCTIONS)
    _validate_public_relation_rows(relations, strict_head_proof=strict_head_proof)
    expected_type_count = 2 * len(expected_head_columns())
    if (
        functions != expected
        or public_type_count != expected_type_count
        or unattached_type_count != 0
        or public_extensions != 0
        or other_public_objects != 0
    ):
        raise RecoveryIntegrityError(
            "Restored PostgreSQL public catalog object denominator differs from reviewed head."
        )


def _rows_by_table(
    spec: PostgreSQLConnectionSpec,
) -> tuple[dict[str, list[dict[str, Any]]], str]:
    expected = expected_head_columns()
    connection = _open_connection(
        spec,
        application_name="ai-benchmark-recovery-semantic-inspection",
        autocommit=False,
    )
    try:
        with connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            actual_tables = {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                    """
                ).fetchall()
            }
            if actual_tables != set(expected):
                raise RecoveryIntegrityError(
                    "Restored PostgreSQL table denominator is missing or has extras."
                )
            rows_by_table: dict[str, list[dict[str, Any]]] = {}
            for table_name in sorted(expected):
                actual_columns = tuple(
                    sorted(
                        str(row[0])
                        for row in connection.execute(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = %s
                            """,
                            (table_name,),
                        ).fetchall()
                    )
                )
                if actual_columns != expected[table_name]:
                    raise RecoveryIntegrityError(
                        "Restored PostgreSQL table column denominator changed."
                    )
                projection = sql.SQL(", ").join(
                    sql.Identifier(column_name)
                    for column_name in expected[table_name]
                )
                statement = sql.SQL("SELECT {} FROM {}.{}").format(
                    projection,
                    sql.Identifier("public"),
                    sql.Identifier(table_name),
                )
                cursor = connection.cursor(row_factory=dict_row)
                cursor.execute(statement)
                rows_by_table[table_name] = [dict(row) for row in cursor.fetchall()]
                cursor.close()
            engine_version = _server_version(
                connection.execute("SHOW server_version_num").fetchone()[0]
            )
        return rows_by_table, engine_version
    except (RecoveryIntegrityError, UnsupportedRecoveryArtifact):
        raise
    except (psycopg.Error, TypeError, ValueError, IndexError):
        raise RecoveryIntegrityError(
            "Restored PostgreSQL semantic inventory failed closed."
        ) from None
    finally:
        connection.close()


def _schema_sha256(
    spec: PostgreSQLConnectionSpec,
    *,
    tool_version: str,
    timeout_seconds: float,
    cancel_requested: Callable[[], bool] | None,
) -> str:
    observed_tool_version = _toolchain_version(timeout_seconds=timeout_seconds)
    if observed_tool_version != tool_version:
        raise UnsupportedRecoveryArtifact(
            "PostgreSQL schema inspection tool version changed."
        )
    environment = spec.libpq_environment(
        application_name="ai-benchmark-recovery-schema-digest"
    )
    output = _run_pg_tool(
        (
            str(PG_DUMP_PATH),
            "--schema-only",
            "--schema=public",
            "--no-owner",
            "--no-privileges",
            "--no-comments",
            "--no-security-labels",
            "--no-publications",
            "--no-subscriptions",
        ),
        environment=environment,
        phase="postgresql_schema_digest",
        timeout_seconds=timeout_seconds,
        cancel_requested=cancel_requested,
        target_created=True,
    )
    return hashlib.sha256(_normalize_schema_dump(output)).hexdigest()


def _inspect_restored_target(
    spec: PostgreSQLConnectionSpec,
    *,
    artifact: RelationalBackupArtifact,
    target_identity_sha256: str,
    target_marker: str,
    target_database_scope_sha256: str,
    tool_version: str,
    timeout_seconds: float,
    cancel_requested: Callable[[], bool] | None,
) -> RelationalInspectionResult:
    _assert_target_marker(
        spec,
        expected_identity_sha256=target_identity_sha256,
        expected_marker=target_marker,
        expected_database_scope_sha256=target_database_scope_sha256,
    )
    strict_proof = _strict_current_head(spec)
    _strict_public_object_denominator(spec, strict_head_proof=strict_proof)
    rows_by_table, engine_version = _rows_by_table(spec)
    tables = build_table_inventory(rows_by_table)
    lineages = audit_semantic_lineages(rows_by_table)
    cycles, cycle_payloads = build_cycle_inventory(rows_by_table["scheduled_cycles"])
    references = enumerate_referenced_objects(rows_by_table["source_snapshots"])
    schema_sha256 = _schema_sha256(
        spec,
        tool_version=tool_version,
        timeout_seconds=timeout_seconds,
        cancel_requested=cancel_requested,
    )
    final_strict_proof = _strict_current_head(spec)
    _strict_public_object_denominator(
        spec, strict_head_proof=final_strict_proof
    )
    final_rows, final_engine_version = _rows_by_table(spec)
    final_tables = build_table_inventory(final_rows)
    final_lineages = audit_semantic_lineages(final_rows)
    final_cycles, final_cycle_payloads = build_cycle_inventory(
        final_rows["scheduled_cycles"]
    )
    final_references = enumerate_referenced_objects(final_rows["source_snapshots"])
    if (
        final_engine_version != engine_version
        or final_tables != tables
        or final_lineages != lineages
        or final_cycles != cycles
        or final_cycle_payloads != cycle_payloads
        or final_references != references
    ):
        raise RecoveryIntegrityError(
            "Restored PostgreSQL target changed during semantic/schema inspection."
        )
    _assert_target_marker(
        spec,
        expected_identity_sha256=target_identity_sha256,
        expected_marker=target_marker,
        expected_database_scope_sha256=target_database_scope_sha256,
    )
    return RelationalInspectionResult(
        artifact=artifact,
        inspection_engine_version=engine_version,
        inspection_tool_version=tool_version,
        schema_revision=head_revision(),
        schema_sha256=schema_sha256,
        table_inventory_sha256=table_inventory_digest(tables),
        tables=tables,
        integrity=RelationalIntegrityResult(
            backend="postgresql",
            consistency_check="passed",
            foreign_key_violation_count=0,
            lineage_families=lineages,
        ),
        cycles=cycles,
        cycle_payloads=cycle_payloads,
        referenced_objects=references,
        governed_artifact_count=0,
    )


class PostgreSQLBackupRestoreDriver:
    """PostgreSQL 16 backup/restore driver with no old-target mutation path."""

    driver_id = _DRIVER_ID
    driver_version = _DRIVER_VERSION
    engine_name = _ENGINE_NAME
    engine_version = "16.0"
    tool_name = _TOOL_NAME
    artifact_type = _ARTIFACT_TYPE
    format = _FORMAT
    format_version = _FORMAT_VERSION

    def __init__(
        self,
        *,
        command_timeout_seconds: float = _DEFAULT_COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        if (
            type(command_timeout_seconds) not in {int, float}
            or not 0 < float(command_timeout_seconds) <= _MAX_COMMAND_TIMEOUT_SECONDS
        ):
            raise RecoveryTargetError(
                "PostgreSQL command timeout is outside the bounded range."
            )
        self._command_timeout_seconds = float(command_timeout_seconds)
        self.tool_version = _toolchain_version(
            timeout_seconds=self._command_timeout_seconds
        )

    def _current_tool_version(self) -> str:
        current = _toolchain_version(timeout_seconds=self._command_timeout_seconds)
        if current != self.tool_version:
            raise UnsupportedRecoveryArtifact(
                "PostgreSQL recovery toolchain changed during the operation."
            )
        return current

    def _require_artifact(self, artifact: RelationalBackupArtifact) -> None:
        if not isinstance(artifact, RelationalBackupArtifact):
            raise UnsupportedRecoveryArtifact(
                "PostgreSQL recovery artifact is not the typed relational artifact."
            )
        expected = (
            self.driver_id,
            self.driver_version,
            self.engine_name,
            self.tool_name,
            self.artifact_type,
            self.format,
            self.format_version,
        )
        actual = (
            artifact.driver_id,
            artifact.driver_version,
            artifact.engine_name,
            artifact.tool_name,
            artifact.artifact_type,
            artifact.format,
            artifact.format_version,
        )
        if actual != expected:
            raise UnsupportedRecoveryArtifact(
                "PostgreSQL artifact driver/engine/format metadata is unsupported."
            )
        if (
            re.fullmatch(r"16\.\d+(?:\.\d+)?", artifact.engine_version) is None
            or re.fullmatch(r"16\.\d+(?:\.\d+)?", artifact.tool_version) is None
            or artifact.tool_version != self._current_tool_version()
            or type(artifact.source_database_identity_sha256) is not str
            or _SHA256.fullmatch(artifact.source_database_identity_sha256) is None
        ):
            raise UnsupportedRecoveryArtifact(
                "PostgreSQL artifact version or source identity metadata is unsupported."
            )
        if (
            type(artifact.raw_bytes) is not bytes
            or not artifact.raw_bytes.startswith(_ARCHIVE_HEADER)
        ):
            raise RecoveryIntegrityError(
                "PostgreSQL custom archive lacks the typed PGDMP header."
            )

    def _archive_toc(
        self,
        artifact: RelationalBackupArtifact,
        *,
        temporary_root: Path,
        cancel_requested: Callable[[], bool] | None,
        target_created: bool,
    ) -> tuple[Path, Path]:
        archive_path = temporary_root / "relational-backup.dump"
        toc_path = temporary_root / "relational-backup.list"
        _private_write(archive_path, artifact.raw_bytes)
        raw_toc = _run_pg_tool(
            (str(PG_RESTORE_PATH), "--list", str(archive_path)),
            environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            phase="postgresql_archive_list",
            timeout_seconds=self._command_timeout_seconds,
            cancel_requested=cancel_requested,
            target_created=target_created,
            cwd=temporary_root,
        )
        _private_write(toc_path, _filter_public_schema_toc(raw_toc))
        return archive_path, toc_path

    def create_backup(
        self,
        source: object,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> RelationalBackupArtifact:
        spec = _coerce_connection_spec(source, role="backup source")
        _assert_no_ambient_libpq_environment()
        tool_version = self._current_tool_version()
        _cancel(cancel_requested, phase="before_postgresql_backup")
        source_facts = _read_database_facts(
            spec, application_name="ai-benchmark-recovery-source-identity"
        )
        _assert_safe_backup_source_scope(source_facts)
        source_strict_proof = _strict_current_head(spec)
        _strict_public_object_denominator(
            spec, strict_head_proof=source_strict_proof
        )
        environment = spec.libpq_environment(
            application_name="ai-benchmark-recovery-pg-dump"
        )
        with tempfile.TemporaryDirectory(
            prefix="ledger-recovery-postgresql-backup-"
        ) as temporary:
            root = Path(temporary)
            archive_path = root / "relational-backup.dump"
            # pg_dump truncates the already-created private regular file; it
            # never chooses permissions from a process umask or follows a
            # caller-controlled path.
            _private_write(archive_path, b"")
            _run_pg_tool(
                (
                    str(PG_DUMP_PATH),
                    "--format=custom",
                    "--schema=public",
                    "--no-owner",
                    "--no-privileges",
                    "--no-comments",
                    "--no-security-labels",
                    "--no-publications",
                    "--no-subscriptions",
                    "--serializable-deferrable",
                    f"--file={archive_path}",
                ),
                environment=environment,
                phase="postgresql_relational_backup",
                timeout_seconds=self._command_timeout_seconds,
                cancel_requested=cancel_requested,
                cwd=root,
            )
            try:
                metadata = archive_path.lstat()
                raw_bytes = archive_path.read_bytes()
            except OSError:
                raise RecoveryPartialFailure(
                    "POSTGRESQL_BACKUP_READ_FAILED",
                    phase="postgresql_relational_backup",
                ) from None
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
                or not raw_bytes.startswith(_ARCHIVE_HEADER)
            ):
                raise RecoveryIntegrityError(
                    "PostgreSQL backup artifact file/header posture is invalid."
                )
            artifact = RelationalBackupArtifact(
                driver_id=self.driver_id,
                driver_version=self.driver_version,
                engine_name=self.engine_name,
                engine_version=source_facts.engine_version,
                tool_name=self.tool_name,
                tool_version=tool_version,
                artifact_type=self.artifact_type,
                format=self.format,
                format_version=self.format_version,
                source_database_identity_sha256=source_facts.identity_sha256,
                raw_bytes=raw_bytes,
            )
            # Re-list the immutable archive bytes rather than trusting pg_dump
            # success output.  The filter proves ACL/database posture is absent
            # and that the exact public schema collision is understood.
            list_root = root / "list-verification"
            list_root.mkdir(mode=0o700)
            self._archive_toc(
                artifact,
                temporary_root=list_root,
                cancel_requested=cancel_requested,
                target_created=False,
            )
            final_source_facts = _read_database_facts(
                spec,
                application_name="ai-benchmark-recovery-source-final-identity",
            )
            if (
                final_source_facts.identity_sha256
                != source_facts.identity_sha256
                or final_source_facts.engine_version
                != source_facts.engine_version
            ):
                raise RecoveryIntegrityError(
                    "PostgreSQL backup source identity changed during archive capture."
                )
            _assert_safe_backup_source_scope(final_source_facts)
        return artifact

    def _restore_and_inspect(
        self,
        artifact: RelationalBackupArtifact,
        target: object,
        *,
        target_id: str,
        cancel_requested: Callable[[], bool] | None,
    ) -> RelationalInspectionResult:
        self._require_artifact(artifact)
        spec = _coerce_connection_spec(target, role="restore target")
        _assert_no_ambient_libpq_environment()
        stable_target_id = _require_target_id(target_id)
        _cancel(cancel_requested, phase="before_postgresql_restore")
        target_facts, marker = _consume_fresh_target(
            spec,
            artifact=artifact,
            target_id=stable_target_id,
        )
        _cancel(
            cancel_requested,
            phase="after_postgresql_target_fence",
            target_created=True,
        )
        with tempfile.TemporaryDirectory(
            prefix="ledger-recovery-postgresql-restore-"
        ) as temporary:
            root = Path(temporary)
            archive_path, toc_path = self._archive_toc(
                artifact,
                temporary_root=root,
                cancel_requested=cancel_requested,
                target_created=True,
            )
            # Re-resolve the durable marker and the exact database-scope
            # baseline immediately before the first target-writing tool call.
            _assert_target_marker(
                spec,
                expected_identity_sha256=target_facts.identity_sha256,
                expected_marker=marker,
                expected_database_scope_sha256=(
                    target_facts.database_scope_sha256
                ),
            )
            environment = spec.libpq_environment(
                application_name="ai-benchmark-recovery-pg-restore"
            )
            _run_pg_tool(
                _archive_restore_argv(
                    database_name=spec.database,
                    archive_path=str(archive_path),
                    toc_path=str(toc_path),
                ),
                environment=environment,
                phase="postgresql_relational_restore",
                timeout_seconds=self._command_timeout_seconds,
                cancel_requested=cancel_requested,
                target_created=True,
                cwd=root,
            )
        _assert_target_marker(
            spec,
            expected_identity_sha256=target_facts.identity_sha256,
            expected_marker=marker,
            expected_database_scope_sha256=target_facts.database_scope_sha256,
        )
        _apply_restore_safety_floor(
            spec,
            expected_identity_sha256=target_facts.identity_sha256,
            expected_marker=marker,
            expected_database_scope_sha256=target_facts.database_scope_sha256,
        )
        _cancel(
            cancel_requested,
            phase="after_postgresql_restore",
            target_created=True,
        )
        return _inspect_restored_target(
            spec,
            artifact=artifact,
            target_identity_sha256=target_facts.identity_sha256,
            target_marker=marker,
            target_database_scope_sha256=target_facts.database_scope_sha256,
            tool_version=self.tool_version,
            timeout_seconds=self._command_timeout_seconds,
            cancel_requested=cancel_requested,
        )

    def inspect_artifact(
        self,
        artifact: RelationalBackupArtifact,
        *,
        inspection_target: object | None = None,
        target_id: str | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> RelationalInspectionResult:
        if inspection_target is None or target_id is None:
            raise RecoveryTargetError(
                "PostgreSQL archive inspection requires an explicit fresh inspection target and ID."
            )
        return self._restore_and_inspect(
            artifact,
            inspection_target,
            target_id=target_id,
            cancel_requested=cancel_requested,
        )

    def restore_new_target(
        self,
        artifact: RelationalBackupArtifact,
        target: object,
        *,
        target_id: str,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> RelationalInspectionResult:
        return self._restore_and_inspect(
            artifact,
            target,
            target_id=target_id,
            cancel_requested=cancel_requested,
        )


__all__ = [
    "PG_DUMP_PATH",
    "PG_RESTORE_PATH",
    "PostgreSQLBackupRestoreDriver",
    "PostgreSQLConnectionSpec",
]

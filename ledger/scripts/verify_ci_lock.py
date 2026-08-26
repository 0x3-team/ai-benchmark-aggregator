#!/usr/bin/env python3
"""Verify that CI requirements are an exact export of the checked uv lock.

Regenerate ``requirements-ci.lock`` with:

    uv export --format requirements.txt --locked --all-extras \
      --no-emit-project --output-file requirements-ci.lock

The export is derived from ``uv.lock`` and ``pyproject.toml``; this script
never uses the requirements file as an input.  It also exercises the gate with
a temporary, deliberately tampered version, hash, and environment marker so
that a future weakening of the comparison cannot silently pass. The exact
export requires uv 0.11.18.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path


PACKAGE_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*==")
HASH_LINE = re.compile(r"--hash=(sha256:[0-9a-f]{64})\b")
UV_VERSION = "0.11.18"


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class Requirement:
    name: str
    version: str
    marker: str
    hashes: frozenset[str]


class LockMismatch(RuntimeError):
    """Raised when the requirements export does not match uv.lock."""


def parse_requirements(path: Path) -> dict[str, Requirement]:
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed: dict[str, Requirement] = {}
    index = 0
    while index < len(lines):
        raw = lines[index].strip()
        if not raw.startswith("#") and (
            raw.startswith(("-e ", "--editable ")) or "benchmark-ledger @" in raw
        ):
            raise LockMismatch("requirements export contains an editable project entry")
        if not PACKAGE_LINE.match(raw):
            index += 1
            continue

        spec = raw.removesuffix("\\").strip()
        requirement, separator, marker = spec.partition(";")
        name, version = requirement.strip().split("==", 1)
        hashes: set[str] = set()
        index += 1
        while index < len(lines) and not PACKAGE_LINE.match(lines[index].strip()):
            match = HASH_LINE.search(lines[index])
            if match:
                hashes.add(match.group(1))
            index += 1

        key = canonical_name(name)
        if key in parsed:
            raise LockMismatch(f"duplicate requirement: {name}")
        if not hashes:
            raise LockMismatch(f"requirement has no sha256 hashes: {name}")
        parsed[key] = Requirement(
            name=key,
            version=version.strip(),
            marker=marker.strip() if separator else "",
            hashes=frozenset(hashes),
        )
    return parsed


def parse_uv_lock(path: Path) -> dict[str, Requirement]:
    lock = tomllib.loads(path.read_text(encoding="utf-8"))
    parsed: dict[str, Requirement] = {}
    for package in lock.get("package", []):
        source = package.get("source", {})
        if "editable" in source:
            continue
        hashes: set[str] = set()
        if package.get("sdist"):
            hashes.add(package["sdist"]["hash"])
        hashes.update(wheel["hash"] for wheel in package.get("wheels", []))
        name = canonical_name(package["name"])
        if not hashes:
            raise LockMismatch(f"uv.lock package has no distribution hashes: {name}")
        if name in parsed:
            raise LockMismatch(f"duplicate uv.lock package: {name}")
        parsed[name] = Requirement(
            name=name,
            version=package["version"],
            marker="",
            hashes=frozenset(hashes),
        )
    return parsed


def verify(requirements_path: Path, uv_lock_path: Path) -> None:
    expected = parse_uv_lock(uv_lock_path)
    actual = parse_requirements(requirements_path)

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"extra: {', '.join(extra)}")
        raise LockMismatch("package graph drift (" + "; ".join(details) + ")")

    for name in sorted(expected):
        wanted = expected[name]
        found = actual[name]
        if found.version != wanted.version:
            raise LockMismatch(
                f"version drift for {name}: requirements={found.version}, "
                f"uv.lock={wanted.version}"
            )
        if found.hashes != wanted.hashes:
            missing_hashes = sorted(wanted.hashes - found.hashes)
            extra_hashes = sorted(found.hashes - wanted.hashes)
            raise LockMismatch(
                f"hash drift for {name}: missing={missing_hashes}, extra={extra_hashes}"
            )


def verify_exact_export(requirements_path: Path, uv_lock_path: Path) -> None:
    """Regenerate from uv.lock in isolation and compare every output byte."""
    version = subprocess.run(
        ["uv", "--version"], check=True, capture_output=True, text=True
    ).stdout.split()
    if len(version) < 2 or version[1] != UV_VERSION:
        found = " ".join(version) if version else "no version output"
        raise LockMismatch(f"uv version drift: expected {UV_VERSION}, found {found}")

    with tempfile.TemporaryDirectory(prefix="verify-ci-export-") as directory:
        staging = Path(directory)
        for filename in ("pyproject.toml", "uv.lock", "README.md"):
            shutil.copy2(uv_lock_path.parent / filename, staging / filename)
        exported = staging / "requirements-ci.lock"
        result = subprocess.run(
            [
                "uv",
                "export",
                "--format",
                "requirements.txt",
                "--locked",
                "--all-extras",
                "--no-emit-project",
                "--output-file",
                "requirements-ci.lock",
            ],
            cwd=staging,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise LockMismatch(result.stderr.strip() or "uv export failed")
        if exported.read_bytes() != requirements_path.read_bytes():
            raise LockMismatch("requirements-ci.lock differs from exact uv export")


def verify_tamper_rejection(requirements_path: Path, uv_lock_path: Path) -> None:
    original = requirements_path.read_text(encoding="utf-8")
    match = re.search(r"(--hash=sha256:)([0-9a-f]{64})", original)
    if not match:
        raise LockMismatch("cannot exercise tamper gate: no hash found")
    replacement = (
        match.group(1)
        + ("0" if match.group(2)[0] != "0" else "1")
        + match.group(2)[1:]
    )
    tampered = original[: match.start()] + replacement + original[match.end() :]

    with tempfile.TemporaryDirectory(prefix="verify-ci-lock-") as directory:
        candidate = Path(directory) / "requirements-ci.lock"
        candidate.write_text(tampered, encoding="utf-8")
        try:
            verify(candidate, uv_lock_path)
        except LockMismatch:
            return
    raise LockMismatch("tampered hash was accepted")


def verify_marker_rejection(requirements_path: Path, uv_lock_path: Path) -> None:
    original = requirements_path.read_text(encoding="utf-8")
    marker = " ; sys_platform == 'win32'"
    if marker not in original:
        raise LockMismatch("cannot exercise marker gate: colorama marker not found")
    tampered = original.replace(marker, " ; sys_platform == 'linux'", 1)

    with tempfile.TemporaryDirectory(prefix="verify-ci-marker-") as directory:
        candidate = Path(directory) / "requirements-ci.lock"
        candidate.write_text(tampered, encoding="utf-8")
        try:
            verify_exact_export(candidate, uv_lock_path)
        except LockMismatch:
            return
    raise LockMismatch("tampered environment marker was accepted")


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, default=project / "requirements-ci.lock")
    parser.add_argument("--uv-lock", type=Path, default=project / "uv.lock")
    args = parser.parse_args()

    try:
        verify_exact_export(args.requirements, args.uv_lock)
        verify(args.requirements, args.uv_lock)
        verify_tamper_rejection(args.requirements, args.uv_lock)
        verify_marker_rejection(args.requirements, args.uv_lock)
    except (LockMismatch, OSError, KeyError, ValueError) as error:
        parser.error(str(error))
    package_count = len(parse_requirements(args.requirements))
    print(
        f"CI lock verified: {package_count} packages; exact export and "
        "version/hash/marker tamper rejection passed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

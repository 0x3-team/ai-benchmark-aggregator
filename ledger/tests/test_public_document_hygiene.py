from __future__ import annotations

import json
from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REMOVED_LOCAL_RECEIPTS = (
    "docs/audits/2026-08-26-launch-orchestration-receipts.jsonl",
    "docs/audits/2026-08-26-wave1-model-routing.json",
    "docs/audits/2026-08-26-wave2-model-routing.jsonl",
)
PUBLIC_CHECKPOINT_DOCUMENTS = (
    "docs/handover/2026-08-26-real-data-only-launch-local-continuation.md",
    "docs/plans/2026-08-09-comprehensive-checkpoint-remediation-plan.md",
    "docs/plans/2026-08-26-real-data-only-production-launch-execution-plan.md",
    "docs/plans/2026-08-26-real-data-only-production-launch-execution-plan-implementation-ledger.jsonl",
    "docs/receipts/2026-08-26-p11-permalinks-local-acceptance.md",
)
PUBLIC_ORCHESTRATION_SKILLS = (
    ".agents/skills/quality-orchestration/SKILL.md",
    ".agents/skills/release-verification/SKILL.md",
)
FORBIDDEN_OPERATIONAL_FRAGMENTS = (
    '"cost_tier":',
    '"effective_effort":',
    '"fast_status":',
    '"model":',
    '"orca_run":',
    '"permission_mode":',
    '"provider":',
    '"requested_effort":',
    '"route":',
    ".commandcode/",
    "codex in-app browser",
    "codex native worker",
    "computer use used gpt-",
    "devin cli",
    "luna high",
    "orca native browser",
    "provider log attestation",
    "sol max",
)
FORBIDDEN_SKILL_ROUTE_FRAGMENTS = (
    "anthropic/",
    "capy api",
    "codex/gpt-",
    "deepseek/",
    "gpt-5.6-",
    "moonshotai/",
    "price appendix",
    "supergrok/",
    "xai/",
    "zai/",
)
LOCAL_RUNTIME_ID = re.compile(r"\b(?:ctx|run|task|term)_[0-9a-f]{6,}\b", re.IGNORECASE)


def test_local_orchestration_receipts_are_absent_and_ignored() -> None:
    ignore_text = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

    for relative_path in REMOVED_LOCAL_RECEIPTS:
        assert not (REPOSITORY_ROOT / relative_path).exists()
        assert relative_path in ignore_text


def test_public_checkpoint_documents_omit_local_routing_evidence() -> None:
    combined_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPOSITORY_ROOT / "docs").rglob("*")
        if path.is_file() and path.suffix in {".md", ".json", ".jsonl"}
    )
    for relative_path in REMOVED_LOCAL_RECEIPTS:
        assert relative_path not in combined_text

    for relative_path in (*PUBLIC_CHECKPOINT_DOCUMENTS, *PUBLIC_ORCHESTRATION_SKILLS):
        text = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        lowered = text.lower()
        for fragment in FORBIDDEN_OPERATIONAL_FRAGMENTS:
            assert fragment not in lowered, f"{relative_path} contains {fragment!r}"
        assert LOCAL_RUNTIME_ID.search(text) is None

    for relative_path in PUBLIC_ORCHESTRATION_SKILLS:
        lowered = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8").lower()
        for fragment in FORBIDDEN_SKILL_ROUTE_FRAGMENTS:
            assert fragment not in lowered, f"{relative_path} contains {fragment!r}"


def test_redacted_implementation_ledger_remains_valid_json_lines() -> None:
    path = REPOSITORY_ROOT / PUBLIC_CHECKPOINT_DOCUMENTS[3]
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert len(records) == 7
    assert all(record["source_artifact"].endswith("execution-plan.md") for record in records)


def test_public_skills_keep_route_neutral_acceptance_contracts() -> None:
    quality = (REPOSITORY_ROOT / PUBLIC_ORCHESTRATION_SKILLS[0]).read_text(
        encoding="utf-8"
    )
    release = (REPOSITORY_ROOT / PUBLIC_ORCHESTRATION_SKILLS[1]).read_text(
        encoding="utf-8"
    )

    assert "owner inspects every delegated result" in quality
    assert re.search(
        r"record the routing decision in the\s+orchestration system before "
        r"every delegation",
        quality,
    )
    assert re.search(
        r"reviewer whose underlying model vendor\s+differs from the author's "
        r"underlying model vendor",
        quality,
    )
    assert re.search(
        r"Paid model, tool, compute, and other orchestration operations are "
        r"prohibited\s+for this repository",
        quality,
    )
    assert "must remain public" in release
    assert "Pin the exact candidate commit SHA" in release
    assert re.search(
        r"Never change visibility as a\s+CI workaround",
        release,
    )

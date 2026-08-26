from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from app import cli as cli_module
from app.cli import app
from app.discovery.manifest import DiscoveryManifestError
from discovery_fixtures import standard_observations, write_manifest_root

runner = CliRunner()


def _root(tmp_path: Path) -> Path:
    return write_manifest_root(
        tmp_path / "fx", observations=standard_observations("example-target-v1")
    )


def test_plan_is_side_effect_free_and_never_touches_a_database(tmp_path) -> None:
    root = _root(tmp_path)
    missing = tmp_path / "missing.db"
    result = runner.invoke(
        app,
        [
            "discovery",
            "plan",
            "--fixture-root",
            str(root),
            "--slot-ordinal",
            "0",
        ],
        env={"DATABASE_URL": f"sqlite:///{missing}"},
    )
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["policyVersion"] == "discovery-plan-v1"
    assert document["availability"] == "candidate_only"
    assert document["counts"] == {
        "expectedTargetCount": 1,
        "dueCount": 1,
        "notDueCount": 0,
        "blockedCount": 0,
    }
    assert document["targets"][0]["dueDisposition"] == "due"
    assert document["targets"][0]["dispositionReasonCode"] == "DUE_BY_SCHEDULE"
    assert document["authority"]["certifiesSources"] is False
    assert document["authority"]["frontendLoadable"] is False
    assert not missing.exists()


def test_run_replay_and_report_round_trip(tmp_db, tmp_path) -> None:
    root = _root(tmp_path)
    first = runner.invoke(
        app,
        ["discovery", "run", "--fixture-root", str(root), "--slot-ordinal", "0"],
    )
    assert first.exit_code == 0, first.output
    receipt = json.loads(first.stdout)
    assert receipt["policyVersion"] == "discovery-run-receipt-v1"
    assert receipt["counts"]["newCandidateCount"] == 1
    assert receipt["counts"]["changedCount"] == 1
    assert receipt["slot"]["scheduledFor"] == "2026-01-01T00:00:00Z"

    replay = runner.invoke(
        app,
        ["discovery", "run", "--fixture-root", str(root), "--slot-ordinal", "0"],
    )
    assert replay.exit_code == 0, replay.output
    replayed = json.loads(replay.stdout)
    assert replayed["cycleId"] == receipt["cycleId"]
    assert replayed["counts"]["newCandidateCount"] == 0
    assert replayed["counts"]["unchangedCount"] == 1

    second_slot = runner.invoke(
        app,
        ["discovery", "run", "--fixture-root", str(root), "--slot-ordinal", "1"],
    )
    assert second_slot.exit_code == 0, second_slot.output
    assert json.loads(second_slot.stdout)["cycleId"] != receipt["cycleId"]

    report = runner.invoke(app, ["discovery", "report", "--format", "json"])
    assert report.exit_code == 0, report.output
    document = json.loads(report.stdout)
    assert document["availability"] == "report_only"
    assert len(document["cycles"]) == 2
    assert {cycle["cycleId"] for cycle in document["cycles"]} == {
        receipt["cycleId"],
        json.loads(second_slot.stdout)["cycleId"],
    }
    assert document["candidates"]["total"] == 1
    assert document["candidates"]["byState"] == {"observed": 1}

    markdown = runner.invoke(app, ["discovery", "report", "--format", "markdown"])
    assert markdown.exit_code == 0, markdown.output
    assert receipt["cycleId"] in markdown.stdout
    assert "Quarantined candidates" in markdown.stdout


def test_run_with_a_failed_target_exits_one_but_still_emits_the_receipt(
    tmp_db, tmp_path
) -> None:
    root = write_manifest_root(tmp_path / "fx", observations={})
    result = runner.invoke(
        app,
        ["discovery", "run", "--fixture-root", str(root), "--slot-ordinal", "0"],
    )
    assert result.exit_code == 1, result.output
    receipt = json.loads(result.stdout)
    assert receipt["counts"]["failedCount"] == 1
    assert receipt["targets"][0]["failureReasonCode"] == "MISSING_FIXTURE_OBSERVATION"


def test_invalid_manifest_exits_two_with_bounded_error(tmp_path) -> None:
    root = write_manifest_root(tmp_path / "fx", mode="shadow")
    result = runner.invoke(
        app,
        ["discovery", "plan", "--fixture-root", str(root), "--slot-ordinal", "0"],
    )
    assert result.exit_code == 2
    payload = json.loads(result.stderr)
    assert payload["reasonCode"] == "DISCOVERY_INPUT_REJECTED"
    assert payload["availability"] == "candidate_only"
    assert payload["status"] == "failed_closed"


def test_discovery_failure_never_discloses_raw_exception_detail(tmp_path, monkeypatch) -> None:
    """F3 regression: the discovery failure payload must never expose raw
    exception detail (private paths, filenames, provider/DB detail, terminal
    escape bytes) and must be exactly one bounded JSON object with the four
    stable keys, exit 2, and no traceback."""
    sentinel_path = "/private/tmp/secret-ops/credentials.json"
    sentinel_filename = "provider-auth-secret.json"
    sentinel_provider = "smtp-relay-internal-vendor"
    sentinel_db = "postgres://user:secret@10.0.0.8/prod"
    sentinel_control = "\x1b]0;evil-title\x07\x1b[31m"
    sentinel = (
        f"{sentinel_path} {sentinel_filename} {sentinel_provider} "
        f"{sentinel_db} {sentinel_control}"
    )

    def _boom(fixture_root):
        raise DiscoveryManifestError(sentinel)

    monkeypatch.setattr(cli_module, "load_manifest", _boom)
    result = runner.invoke(
        app,
        ["discovery", "plan", "--fixture-root", str(tmp_path), "--slot-ordinal", "0"],
    )
    assert result.exit_code == 2
    payload = json.loads(result.stderr)
    assert payload == {
        "availability": "candidate_only",
        "status": "failed_closed",
        "reasonCode": "DISCOVERY_INPUT_REJECTED",
        "detail": "Discovery input was rejected.",
    }
    for component in (
        sentinel_path,
        sentinel_filename,
        sentinel_provider,
        sentinel_db,
        sentinel_control,
        "\x1b",
    ):
        assert component not in result.stderr
        assert component not in result.stdout

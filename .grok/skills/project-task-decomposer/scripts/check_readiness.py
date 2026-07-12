#!/usr/bin/env python3
"""Aggregate readiness gates for a task corpus."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> int:
    return subprocess.run(cmd, capture_output=True, text=True).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_root", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    root = args.corpus_root.resolve()
    scripts = Path(__file__).resolve().parent
    py = sys.executable

    gates = {
        "schema_structure": run([py, str(scripts / "validate_task_corpus.py"), str(root), "--json", "--write-report"]) == 0,
        "cycles": run([py, str(scripts / "detect_cycles.py"), str(root)]) == 0,
        "coverage": run([py, str(scripts / "audit_coverage.py"), str(root), "--write"]) == 0,
        "granularity": run([py, str(scripts / "audit_granularity.py"), str(root), "--write"]) == 0,
        "duplicates": run([py, str(scripts / "audit_duplicates.py"), str(root), "--write"]) == 0,
        "waves": run([py, str(scripts / "calculate_execution_waves.py"), str(root), "--write"]) == 0,
        "indexes": run([py, str(scripts / "build_indexes.py"), str(root)]) == 0,
    }

    hard = ["schema_structure", "cycles", "coverage", "granularity"]
    if not all(gates[g] for g in hard):
        readiness = "NOT_READY"
        status = "FAIL"
    elif not all(gates.values()):
        readiness = "CONDITIONALLY_READY"
        status = "WARN"
    else:
        readiness = "READY"
        status = "PASS"

    # coverage WARN softens READY
    cov_path = root / "audits" / "coverage-report.json"
    if cov_path.exists():
        cov = json.loads(cov_path.read_text(encoding="utf-8"))
        if cov.get("status") == "WARN" and readiness == "READY":
            readiness = "CONDITIONALLY_READY"
            status = "WARN"
        if cov.get("status") == "FAIL":
            readiness = "NOT_READY"
            status = "FAIL"

    report = {
        "audit_type": "READINESS",
        "status": status,
        "readiness": readiness,
        "generated_at": "",
        "gates": {k: {"pass": v} for k, v in gates.items()},
        "findings": [],
        "metrics": {},
        "thresholds": {
            "schema_validity": "100%",
            "dependency_refs": "100%",
            "cycles": 0,
            "dispatchable_L_XL": 0,
        },
    }
    if args.write:
        out = root / "audits" / "readiness-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        man = root / "manifest.json"
        if man.exists():
            m = json.loads(man.read_text(encoding="utf-8"))
            m["readiness"] = readiness
            m.setdefault("audits", {})
            m["audits"]["readiness"] = status
            m["audits"]["schema"] = "PASS" if gates["schema_structure"] else "FAIL"
            m["audits"]["coverage"] = "PASS" if gates["coverage"] else "FAIL"
            m["audits"]["graph"] = "PASS" if gates["cycles"] and gates["waves"] else "FAIL"
            m["audits"]["granularity"] = "PASS" if gates["granularity"] else "FAIL"
            m["audits"]["duplication"] = "PASS" if gates["duplicates"] else "WARN"
            man.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out} readiness={readiness}")
    else:
        print(json.dumps(report, indent=2))
    return 0 if readiness != "NOT_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())

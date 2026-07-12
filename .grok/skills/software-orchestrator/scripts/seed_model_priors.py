#!/usr/bin/env python3
"""Seed capability store + model registry from model-registry.seed.json priors."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed(db: Path, seed_path: Path, *, force: bool = False) -> None:
    data = json.loads(seed_path.read_text())
    con = sqlite3.connect(db)
    try:
        existing = con.execute("SELECT COUNT(*) FROM capability_profiles").fetchone()[0]
        if existing and not force:
            print(f"skip: {existing} profiles already present (use --force to re-seed empty categories only)")
            # still ensure meta pointer
            con.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("model_priors_seed_version", str(data.get("version", 1))),
            )
            con.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("model_priors_researched_at", data.get("researched_at", "")),
            )
            con.commit()
            return

        now = utcnow()
        n_models = 0
        n_profiles = 0
        adapters = data.get("adapters") or {}
        for adapter_name, adapter in adapters.items():
            harness = adapter.get("harness") or adapter_name
            provider = adapter.get("provider") or adapter_name
            for m in adapter.get("models") or []:
                mid = m.get("model_id") or m.get("cli_model")
                if not mid:
                    continue
                version = mid
                con.execute(
                    """
                    INSERT OR REPLACE INTO models(
                      model_id, provider, version, harness, reasoning_setting,
                      modalities, context_window, pricing_json, privacy_json, metadata_json, last_verified
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        mid,
                        provider,
                        version,
                        harness,
                        "",
                        json.dumps(m.get("capabilities") or m.get("reasoning") or []),
                        m.get("context_window"),
                        json.dumps(m.get("pricing") or {}),
                        json.dumps({"notes": m.get("notes")}),
                        json.dumps(
                            {
                                "name": m.get("name") or m.get("label"),
                                "fit": m.get("fit"),
                                "strengths": m.get("strengths"),
                                "weaknesses": m.get("weaknesses"),
                                "adapter": adapter_name,
                                "cli_model": m.get("cli_model"),
                                "prior_source": "model-registry.seed.json",
                            }
                        ),
                        data.get("researched_at") or now,
                    ),
                )
                n_models += 1
                seeds = m.get("beta_seeds") or {"other": [1, 1]}
                for category, ab in seeds.items():
                    if not isinstance(ab, (list, tuple)) or len(ab) != 2:
                        continue
                    a, b = float(ab[0]), float(ab[1])
                    con.execute(
                        """
                        INSERT OR REPLACE INTO capability_profiles(
                          model_id, provider, version, harness, reasoning_setting, category, stack_key,
                          sample_count, success_alpha, success_beta, reliability, strengths_json, weaknesses_json,
                          drift_status, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            mid,
                            provider,
                            version,
                            harness,
                            "",
                            category,
                            "",
                            0,  # sample_count 0 = still prior-only
                            a,
                            b,
                            0.7,
                            json.dumps(m.get("strengths") or []),
                            json.dumps(m.get("weaknesses") or []),
                            "unknown",
                            now,
                        ),
                    )
                    n_profiles += 1

        con.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("model_priors_seed_version", str(data.get("version", 1))),
        )
        con.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("model_priors_researched_at", data.get("researched_at", "")),
        )
        con.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("model_priors_seeded_at", now),
        )
        con.commit()
        print(json.dumps({"ok": True, "models": n_models, "profiles": n_profiles, "db": str(db)}))
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument(
        "--seed",
        default=str(Path(__file__).resolve().parent.parent / "references" / "model-registry.seed.json"),
    )
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    seed(Path(args.db), Path(args.seed), force=args.force)


if __name__ == "__main__":
    main()

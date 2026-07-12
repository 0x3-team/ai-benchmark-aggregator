#!/usr/bin/env python3
"""Expected-utility model selection for Software Orchestrator.

Cold-start uses Beta(1,1) unless prior_success/prior_fail provided.
Does not hardcode permanent model rankings.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_WEIGHTS = {
    "w_quality": 0.35,
    "w_fit": 0.15,
    "w_tools": 0.08,
    "w_context": 0.07,
    "w_reliability": 0.10,
    "w_exploration": 0.05,
    "w_cost": 0.10,
    "w_latency": 0.05,
    "w_review": 0.03,
    "w_retry": 0.02,
    "w_integration": 0.03,
    "w_security": 0.02,
}

DEFAULT_MARGIN = 0.08


@dataclass
class Candidate:
    model_id: str
    is_self: bool = False
    eligible: bool = True
    reasons: list[str] | None = None
    alpha: float = 1.0
    beta: float = 1.0
    fit: float = 0.5
    tool_fit: float = 0.5
    ctx_fit: float = 1.0
    reliability: float = 0.7
    expected_cost: float = 0.05
    expected_latency_s: float = 60.0
    expected_review: float = 0.3
    expected_retry: float = 0.2
    integration_risk: float = 0.2
    policy_risk: float = 0.0
    sample_count: int = 0


def beta_mean(a: float, b: float) -> float:
    return a / (a + b)


def beta_sample(a: float, b: float, rng: random.Random) -> float:
    # Thompson sample via gamma ratio
    x = rng.gammavariate(a, 1.0) if a > 0 else 0.0
    y = rng.gammavariate(b, 1.0) if b > 0 else 0.0
    if x + y == 0:
        return 0.5
    return x / (x + y)


def utility(c: Candidate, w: dict[str, float], p_success: float, explore_bonus: float) -> float:
    # normalize cost/latency roughly into [0,1] penalties
    cost_pen = min(1.0, c.expected_cost / 1.0)
    lat_pen = min(1.0, c.expected_latency_s / 600.0)
    return (
        w["w_quality"] * p_success
        + w["w_fit"] * c.fit
        + w["w_tools"] * c.tool_fit
        + w["w_context"] * c.ctx_fit
        + w["w_reliability"] * c.reliability
        + w["w_exploration"] * explore_bonus
        - w["w_cost"] * cost_pen
        - w["w_latency"] * lat_pen
        - w["w_review"] * c.expected_review
        - w["w_retry"] * c.expected_retry
        - w["w_integration"] * c.integration_risk
        - w["w_security"] * c.policy_risk
    )


def load_profile(con: sqlite3.Connection, model_id: str, category: str) -> tuple[float, float, int]:
    row = con.execute(
        """
        SELECT success_alpha, success_beta, sample_count FROM capability_profiles
        WHERE model_id=? AND category=?
        ORDER BY updated_at DESC LIMIT 1
        """,
        (model_id, category),
    ).fetchone()
    if not row:
        return 1.0, 1.0, 0
    return float(row[0]), float(row[1]), int(row[2] or 0)


def select(
    candidates: list[Candidate],
    *,
    category: str,
    risk: str,
    explore: bool,
    margin: float,
    weights: dict[str, float],
    seed: int | None = None,
    db: Path | None = None,
) -> dict[str, Any]:
    rng = random.Random(seed)
    con = sqlite3.connect(db) if db and db.exists() else None
    scored = []
    for c in candidates:
        if con and not c.is_self:
            a, b, n = load_profile(con, c.model_id, category)
            c.alpha, c.beta, c.sample_count = a, b, n
        if not c.eligible:
            scored.append({**c.__dict__, "utility": None, "p_success": None})
            continue
        if explore and risk in ("low", "medium") and not c.is_self:
            p = beta_sample(c.alpha, c.beta, rng)
            explore_bonus = 1.0 / math.sqrt(1 + c.sample_count)
        else:
            p = beta_mean(c.alpha, c.beta)
            explore_bonus = 0.0
            if risk in ("high", "critical"):
                explore_bonus = 0.0
        u = utility(c, weights, p, explore_bonus)
        scored.append(
            {
                "model_id": c.model_id,
                "is_self": c.is_self,
                "eligible": c.eligible,
                "ineligibility_reasons": c.reasons or [],
                "predicted_success": p,
                "predicted_cost_usd": c.expected_cost,
                "predicted_latency_ms": int(c.expected_latency_s * 1000),
                "risk_estimate": c.integration_risk,
                "exploration_bonus": explore_bonus,
                "utility": u,
                "sample_count": c.sample_count,
            }
        )
    if con:
        con.close()

    eligible = [s for s in scored if s["eligible"] and s["utility"] is not None]
    if not eligible:
        raise SystemExit("no eligible candidates")

    self_rows = [s for s in eligible if s["is_self"]]
    self_u = self_rows[0]["utility"] if self_rows else -1e9
    best = max(eligible, key=lambda s: s["utility"])

    # only delegate if beats self by margin
    if best["is_self"] or best["utility"] < self_u + margin:
        # pick self if available else best
        selected = self_rows[0] if self_rows else best
        exploration = False
    else:
        selected = best
        exploration = bool(selected.get("exploration_bonus", 0) > 0)

    return {
        "candidates": scored,
        "selected": {
            "model_id": selected["model_id"],
            "utility": selected["utility"],
            "is_self": selected["is_self"],
        },
        "self_execution_utility": self_u if self_u > -1e8 else None,
        "delegation_margin": margin,
        "exploration": exploration,
        "reason": (
            "self_execution" if selected["is_self"] else f"delegate:{selected['model_id']}"
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates-json", required=True, help="JSON list of candidates")
    ap.add_argument("--category", required=True)
    ap.add_argument("--risk", default="medium")
    ap.add_argument("--explore", action="store_true")
    ap.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    raw = json.loads(Path(args.candidates_json).read_text() if args.candidates_json.endswith(".json") and Path(args.candidates_json).exists() else args.candidates_json)
    # allow file path or inline json
    if isinstance(raw, str):
        raw = json.loads(raw)
    cands = [Candidate(**x) for x in raw]
    out = select(
        cands,
        category=args.category,
        risk=args.risk,
        explore=args.explore,
        margin=args.margin,
        weights=DEFAULT_WEIGHTS,
        seed=args.seed,
        db=args.db,
    )
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Append outcome event and update Beta-Binomial capability profile."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_profile(
    con: sqlite3.Connection,
    *,
    model_id: str,
    provider: str,
    version: str,
    harness: str,
    category: str,
    accepted: bool,
    first_attempt: bool,
    takeover: bool,
    review_score: float | None,
    cost: float | None,
    latency_ms: float | None,
    attribution: str,
    half_life_days: float = 21.0,
) -> None:
    row = con.execute(
        """
        SELECT id, sample_count, success_alpha, success_beta, pass_first, eventual_success,
               retry_rate, takeover_rate, mean_review, latency_ewma_ms, cost_ewma_usd
        FROM capability_profiles
        WHERE model_id=? AND provider=? AND version=? AND harness=? AND category=?
        """,
        (model_id, provider, version, harness, category),
    ).fetchone()

    # mild recency: treat each new sample as weight 1; optional decay of counts via alpha/beta shrink
    decay = 0.98  # soft aging of prior each update
    if row:
        (
            pid,
            n,
            a,
            b,
            pass_first,
            eventual,
            retry_rate,
            takeover_rate,
            mean_review,
            lat,
            cost_e,
        ) = row
        a = float(a) * decay
        b = float(b) * decay
        n = int(n)
    else:
        pid = None
        n, a, b = 0, 1.0, 1.0
        pass_first = eventual = retry_rate = takeover_rate = mean_review = lat = cost_e = None

    if accepted:
        a += 1.0
    else:
        b += 1.0
    n += 1

    def ewma(prev, new, alpha=0.2):
        if new is None:
            return prev
        if prev is None:
            return new
        return (1 - alpha) * prev + alpha * new

    # rates
    if pass_first is None:
        pass_first = 1.0 if (accepted and first_attempt) else 0.0
    else:
        pass_first = ewma(pass_first, 1.0 if (accepted and first_attempt) else 0.0)
    if eventual is None:
        eventual = 1.0 if accepted else 0.0
    else:
        eventual = ewma(eventual, 1.0 if accepted else 0.0)
    if takeover_rate is None:
        takeover_rate = 1.0 if takeover else 0.0
    else:
        takeover_rate = ewma(takeover_rate, 1.0 if takeover else 0.0)
    if mean_review is None:
        mean_review = review_score
    else:
        mean_review = ewma(mean_review, review_score)
    lat = ewma(lat, latency_ms)
    cost_e = ewma(cost_e, cost)

    # attribution does not always penalize model
    if attribution not in ("model_capability", "success") and not accepted:
        # reverse pure capability hit: soften beta increment
        b = max(1.0, b - 0.5)

    now = utcnow()
    if pid:
        con.execute(
            """
            UPDATE capability_profiles SET
              sample_count=?, success_alpha=?, success_beta=?,
              pass_first=?, eventual_success=?, takeover_rate=?,
              mean_review=?, latency_ewma_ms=?, cost_ewma_usd=?, updated_at=?
            WHERE id=?
            """,
            (n, a, b, pass_first, eventual, takeover_rate, mean_review, lat, cost_e, now, pid),
        )
    else:
        con.execute(
            """
            INSERT INTO capability_profiles(
              model_id, provider, version, harness, category, sample_count,
              success_alpha, success_beta, pass_first, eventual_success, takeover_rate,
              mean_review, latency_ewma_ms, cost_ewma_usd, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                model_id,
                provider,
                version,
                harness,
                category,
                n,
                a,
                b,
                pass_first,
                eventual,
                takeover_rate,
                mean_review,
                lat,
                cost_e,
                now,
            ),
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--event-json", required=True, help="path to outcome event JSON")
    args = ap.parse_args()
    event = json.loads(Path(args.event_json).read_text())
    if "event_id" not in event:
        event["event_id"] = str(uuid4())
    if "timestamp" not in event:
        event["timestamp"] = utcnow()

    con = sqlite3.connect(args.db)
    try:
        con.execute(
            "INSERT OR REPLACE INTO outcome_events(event_id, timestamp, project_id, task_id, attempt_id, payload_json) VALUES (?,?,?,?,?,?)",
            (
                event["event_id"],
                event["timestamp"],
                event["project_id"],
                event["task_id"],
                event["attempt_id"],
                json.dumps(event),
            ),
        )
        m = event.get("model") or {}
        ar = event.get("actual_result") or {}
        update_profile(
            con,
            model_id=m.get("model_id", "unknown"),
            provider=m.get("provider", "unknown"),
            version=m.get("version", "unknown"),
            harness=m.get("harness", "unknown"),
            category=(event.get("task_features") or {}).get("category", "other"),
            accepted=bool(ar.get("accepted")),
            first_attempt=bool(ar.get("first_attempt_pass")),
            takeover=(ar.get("action") == "TAKE_OVER"),
            review_score=(event.get("review_findings") or {}).get("mean_score"),
            cost=event.get("cost_usd"),
            latency_ms=event.get("latency_ms"),
            attribution=event.get("causal_attribution", "success" if ar.get("accepted") else "model_capability"),
        )
        con.commit()
    finally:
        con.close()
    print(json.dumps({"ok": True, "event_id": event["event_id"]}))


if __name__ == "__main__":
    main()

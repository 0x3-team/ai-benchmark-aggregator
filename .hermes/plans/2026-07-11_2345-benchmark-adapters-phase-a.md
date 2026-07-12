# Benchmark Adapters Phase A — 4 Easy Wins (24 → 28 live-score benchmarks)

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Raise ledger live-score coverage from 24 → ~28 benchmarks by building 4 small custom adapters (τ-bench, HELM, IMO-AnswerBench, FrontierMath) — all no-auth, no API key, no fabricated data.

**Architecture:** Each adapter subclasses `SourceAdapter` (see `ledger/app/ingestion/adapters/base.py`), is registered in `ledger/app/ingestion/adapters/__init__.py` under a new `source_type`, and is referenced by a new entry in `ledger/app/registry/official_sources.yaml` (`status: active`). The runner (`runner.py`) already handles fetch→snapshot→extract→match→insert; we only add the adapter + YAML + a test. Existing adapter patterns to copy: `generic_json.py`, `generic_csv.py`, `github_yaml.py` (just added).

**Tech Stack:** Python 3.11, httpx, SQLAlchemy, pytest. No new third-party deps (S3/XML/GCS parsed with stdlib `xml.etree` + httpx).

---

## Phase A — Four adapters

### Task 1: Discover & pin exact live endpoints (read-only)
**Objective:** Confirm the real, currently-200 URLs before writing any adapter. No code yet.

**Step 1:** Run read-only probes (do NOT edit files):
```bash
export PATH="/srv/hermes/.npm-global/bin:/srv/hermes/.local/bin:$PATH"
cd /srv/hermes/development/ai-benchmark-aggregator/ledger && source .venv/bin/activate
# τ-bench: list public S3 bucket
curl -s "https://sierra-tau-bench-public.s3.amazonaws.com/?list-type=2&prefix=submissions/" | head -c 600
# HELM: confirm groups.json endpoint (discover via curl; do not invent — verify 200)
curl -s -o /dev/null -w "helm: %{http_code}\n" "<HELM_GROUPS_JSON_URL>"
# IMO-AnswerBench: HF datasets-server first-rows for google-deepmind/superhuman
curl -s -o /dev/null -w "imo: %{http_code}\n" "https://datasets-server.huggingface.co/first-rows?dataset=google-deepmind/superhuman&config=<cfg>&split=<split>"
# FrontierMath: Epoch AI public CSV bundle URL (discover; verify 200)
curl -s -o /dev/null -w "fm: %{http_code}\n" "<EPOCH_FRONTIERMATH_CSV_URL>"
```
**Step 2:** Record the 4 confirmed URLs + config/split into a scratch note. If any 404s, refine the URL (check the research map: `BENCHMARK-DATA-SOURCES.md`).
**Step 3:** Commit nothing. Report the 4 pinned URLs to the user before building.
**Verification:** 4 URLs return HTTP 200 with machine-readable bodies.

---

### Task 2: τ-bench — `taubench_s3` adapter
**Objective:** Parse the public S3 bucket and emit one claim per model (aggregated pass-rate).

**Files:**
- Create: `ledger/app/ingestion/adapters/taubench_s3.py`
- Modify: `ledger/app/ingestion/adapters/__init__.py` (register `taubench_s3`)
- Test: `ledger/tests/test_taubench_s3.py`

**Step 1: Write failing test** (`ledger/tests/test_taubench_s3.py`):
```python
from app.ingestion.adapters.taubench_s3 import TauBenchS3Adapter

def test_extract_claims_from_sample():
    # minimal submission.json body
    body = b'''{"model":"gpt-5.6","results":{"banking":{"pass_1":0.9,"pass_2":0.85},"retail":{"pass_1":0.8}}}'''
    src = type("S", (), {"id":"t","benchmark_id":"tau_bench","parser_config":{}})()
    snap = type("X", (), {"id":"00000000-0000-0000-0000-000000000000"})()
    claims = TauBenchS3Adapter().extract_claims(src, snap, body)
    assert len(claims) == 1
    assert claims[0].model_raw == "gpt-5.6"
    assert claims[0].score_numeric is not None
```
**Step 2:** Run: `python -m pytest ledger/tests/test_taubench_s3.py -q` → FAIL (module missing).

**Step 3: Implement** (`ledger/app/ingestion/adapters/taubench_s3.py`):
```python
from __future__ import annotations
import xml.etree.ElementTree as ET
import json
from typing import Any
import httpx
from app.config import get_settings
from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import OfficialSource, ResultClaimInput, SourceFetchResult

NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

class TauBenchS3Adapter(SourceAdapter):
    source_type = "taubench_s3"

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        settings = get_settings()
        bucket = source.parser_config.get("bucket", "sierra-tau-bench-public")
        prefix = source.parser_config.get("prefix", "submissions/")
        url = f"https://{bucket}.s3.amazonaws.com/?list-type=2&prefix={prefix}"
        with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as c:
            listing = c.get(url, headers={"User-Agent": settings.http_user_agent}).text
        root = ET.fromstring(listing)
            keys = [k.text for k in root.iter(f"{NS}Key") if k.text and k.text.endswith("submission.json")]
            bodies = []
            for k in keys:
                r = c.get(f"https://{bucket}.s3.amazonaws.com/{k}")
                if r.status_code == 200:
                    bodies.append(r.content)
        raw = b"\n".join(bodies)
        return SourceFetchResult(raw_bytes=raw, content_type="application/x-ndjson", http_status=200, final_url=url)

    def extract_claims(self, source, snapshot: SourceSnapshot, raw_bytes: bytes) -> list[ResultClaimInput]:
        claims = []
        for line in raw_bytes.split(b"\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue
            model = data.get("model") or data.get("model_name") or data.get("model_id")
            results = data.get("results", {})
            if not model or not results:
                continue
            # aggregate mean of all pass_k across domains
            vals = []
            for dom in results.values():
                if isinstance(dom, dict):
                    for key, v in dom.items():
                        if key.startswith("pass_") and isinstance(v, (int, float)):
                            vals.append(float(v))
            if not vals:
                continue
            score = sum(vals) / len(vals)
            claims.append(ResultClaimInput(
                official_source_id=source.id, source_snapshot_id=snapshot.id,
                benchmark_id=source.benchmark_id, model_raw=str(model),
                benchmark_raw=source.benchmark_id, score_raw=f"{score:.4f}",
                metric_raw="mean_pass_rate", score_numeric=score,
                evidence_location={"type":"s3_submission","model":str(model)},
                capture_method="taubench_s3_parser", capture_confidence=0.9,
                capture_status="parser_verified", officialness_level=source.officialness_level,
            ))
        return claims

    def validate_claim(self, claim, raw_bytes):
        from app.schemas.boundary import ClaimValidationInput
        return [ClaimValidationInput(validation_type="taubench_agg", outcome="pass", validator="TauBenchS3Adapter")]
```

**Step 4:** Register in `__init__.py`:
```python
from app.ingestion.adapters.taubench_s3 import TauBenchS3Adapter
ADAPTERS["taubench_s3"] = TauBenchS3Adapter
```
**Step 5:** Run test → PASS. Add YAML entry (Task 6). Commit.

---

### Task 3: HELM — `helm_json` adapter
**Objective:** Parse the HELM `groups.json` leaderboard into per-model claims.

**Files:** Create `ledger/app/ingestion/adapters/helm_json.py`; register `helm_json`; test `ledger/tests/test_helm_json.py`.

**Step 1:** Write failing test with a sample `groups.json` slice (one model, one metric).
**Step 2:** Implement `HelmJSONAdapter(source_type="helm_json")`:
- `fetch`: httpx GET `source.source_url` (the confirmed groups.json URL).
- `extract_claims`: navigate the HELM schema (groups → runs → metrics). HELM's `groups.json` has `groups[].runs[].metrics[]` with `name` + `value`, plus `run_name`/`model`. Emit one claim per (model, metric) we care about (accuracy-style). Keep `metric_raw` = metric name.
- Match `model_field`/`score_field`/`metric_field` from `parser_config`.
**Step 3:** Register, test PASS, commit.

---

### Task 4: IMO-AnswerBench — `imo_answerbench` adapter
**Objective:** Aggregate the HF `google-deepmind/superhuman` `answerbench_v2.csv` by model → accuracy.

**Files:** Create `ledger/app/ingestion/adapters/imo_answerbench.py`; register `imo_answerbench`; test `ledger/tests/test_imo_answerbench.py`.

**Step 1:** Failing test: sample CSV rows with `model,problem_id,correct` → expect one aggregated claim per model (mean correct).
**Step 2:** Implement `ImoAnswerBenchAdapter(source_type="imo_answerbench")`:
- `fetch`: httpx GET the HF first-rows or raw CSV URL pinned in Task 1.
- `extract_claims`: `csv.DictReader`, group by `model`, compute mean of `correct` (bool/0-1) → accuracy. `metric_raw="accuracy_over_400"`.
**Step 3:** Register, test PASS, commit.

---

### Task 5: FrontierMath — `frontiermath_epoch` adapter
**Objective:** Parse the Epoch AI FrontierMath CSV bundle into per-model claims.

**Files:** Create `ledger/app/ingestion/adapters/frontiermath_epoch.py`; register `frontiermath_epoch`; test `ledger/tests/test_frontiermath_epoch.py`.

**Step 1:** Failing test: sample rows `model,score` (or `model,pass_rate`) → one claim each.
**Step 2:** Implement `FrontierMathEpochAdapter(source_type="frontiermath_epoch")`:
- `fetch`: httpx GET the pinned Epoch CSV bundle URL.
- `extract_claims`: `csv.DictReader`, `model_field`/`score_field` from `parser_config` (default `model`/`score`). Metric = accuracy.
**Step 3:** Register, test PASS, commit.

---

### Task 6: Add 4 active YAML entries + ingest + verify
**Objective:** Register the 4 sources and confirm live claims flow.

**Files:** Modify `ledger/app/registry/official_sources.yaml`.

Add (append under `sources:`), using the URLs pinned in Task 1:
```yaml
  - id: tau_bench_s3
    benchmark_id: tau_bench
    source_name: τ-Bench Official (S3)
    source_url: https://sierra-tau-bench-public.s3.amazonaws.com/
    source_type: taubench_s3
    officialness_level: O1
    machine_readable: true
    requires_auth: false
    parser_name: taubench_s3
    status: active
    parser_config: {bucket: sierra-tau-bench-public, prefix: submissions/}

  - id: helm_leaderboard
    benchmark_id: helm
    source_name: HELM Leaderboard
    source_url: <HELM_GROUPS_JSON_URL>
    source_type: helm_json
    officialness_level: O2
    machine_readable: true
    requires_auth: false
    parser_name: helm_json
    status: active
    parser_config: {model_field: run_name, score_field: value, metric_field: name}

  - id: imo_answerbench_hf
    benchmark_id: imo_answerbench
    source_name: IMO-AnswerBench (DeepMind superhuman)
    source_url: <IMO_CSV_URL>
    source_type: imo_answerbench
    officialness_level: O2
    machine_readable: true
    requires_auth: false
    parser_name: imo_answerbench
    status: active
    parser_config: {}

  - id: frontiermath_epoch
    benchmark_id: frontiermath
    source_name: FrontierMath (Epoch AI)
    source_url: <EPOCH_FM_CSV_URL>
    source_type: frontiermath_epoch
    officialness_level: O2
    machine_readable: true
    requires_auth: false
    parser_name: frontiermath_epoch
    status: active
    parser_config: {model_field: model, score_field: score}
```

**Step 1:** `benchmark-ledger seed-registry | tail -1` (expect `sources: 54`).
**Step 2:** `benchmark-ledger ingest --all 2>&1 | tail -8` (expect new claims from the 4, 0 errors).
**Step 3:** `benchmark-ledger review auto-verify-matched 2>&1 | tail -1`.
**Step 4:** `benchmark-ledger export-official-json 2>&1 | tail -1`.
**Step 5:** Verify gates:
```bash
cd /srv/hermes/development/ai-benchmark-aggregator/ledger && python -m pytest -q 2>&1 | tail -2
cd /srv/hermes/development/ai-benchmark-aggregator
npm run typecheck 2>&1 | tail -1 && npm run build 2>&1 | tail -1 && npm test 2>&1 | tail -2
python3 -c "import json;d=json.load(open('src/data/official/export.from-ledger.json'));print('benchmarks',len(d['benchmarks']),'scores',len(d['scores']))"
```
**Expected:** benchmarks ≥ 28, scores > 2715, ledger tests pass, FE gates green.

---

## Phase B — Artificial Analysis API (blocked until key exists)
**Trigger:** user provides `ARTIFICIAL_ANALYSIS_API_KEY`.
- Set `requires_auth: true` + key in `.env` for: `gpqa_diamond_aa`, `hle` (AA), `math500_aa`, `aime2024_aa`, `aime2025_aa` (already in YAML as `status: inactive`).
- The `artificial_analysis_api` adapter already exists; just flip `status: active` and supply the key.
- Unlocks GPQA, HLE, MATH500, AIME 2024/2025 → ~33 benchmarks with scores.

## Phase C — Review-queue hardening (no score change)
- 2,505 `needs_review` claims are mostly unmatched raws. Improve `ledger/app/matching/aliases.py` (alias coverage) and re-run `review auto-verify-matched` to push more to `parser_verified`.
- Optional: add a `review reject-unmatched` CLI to prune stale noise.
- Does NOT change the live Official-mode score count; improves trust signal.

---

## Risks / Open Questions
- **HELM & FrontierMath exact URLs** must be discovered (Task 1) — do not invent; if a source can't be pinned to a 200, leave it `status: inactive`.
- **τ-bench aggregation** assumes `results.<domain>.pass_k` schema; verify against a real fetched `submission.json` before committing.
- **Model-name matching:** new claims must match existing `model_entity_id` via aliases or they'll sit in `needs_review`. Run `auto-verify-matched` after ingest; manually map any high-value unmatched models in `models*.yaml`.
- **S3 rate/volume:** τ-bench submissions could be many; cap listing depth if slow (add `max_keys` to parser_config).

## Success Criteria
- 4 new adapters + tests committed.
- `official_sources.yaml` → 54 sources, 4 new active.
- Ledger tests pass; FE gates green; export benchmarks ≥ 28, scores > 2715.
- Zero fabricated numbers; every score traceable to a live source snapshot.

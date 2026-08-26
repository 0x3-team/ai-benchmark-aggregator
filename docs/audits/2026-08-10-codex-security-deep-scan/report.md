# Security Review: ai-benchmark-aggregator

## Scope

Read-only repository analysis across frontend trust boundaries, Python ledger/backend, services and integrations, business logic/data flows, tests/supply chain, and local Cloudflare Pages implementation.

- Scan mode: deep_repository
- Target kind: git_worktree
- Target ID: target_sha256_84edfa7af9b45f8e095a021ce2a62a522a2cbddde35225e5f0fc50667e6292ed
- Revision: 5eb3b35e35867e6b56837d7fc9b67e120c423b45
- Snapshot digest: codex-security-snapshot/v1:sha256:98c204ee7a725ad579ff8094d80bf962a181e6ffd2e6fd07f4376bfad26c2ee4
- Inventory strategy: repository
- Included paths: .
- Excluded paths: none
- Runtime or test status: Source review and centralized semantic validation only; no live Cloudflare, GitHub, database, deployment, paid service, Official publication, external account, authenticated browser, or external URL mutation/read.
- Artifacts reviewed: coordinator-manifest.json, in_scope_files.txt, candidate_ledger.jsonl, artifacts/01_context/threat_model.md, 60 ordered worker threat-model artifacts, 404 canonical review items, 120 canonical candidates
- Scan context: Comprehensive repository-wide security audit requested by the user, preserving exact userContext as untrusted analysis data.

Limitations and exclusions:
- Discovery terminal reason was capped at maxDiscoveryRuns=60 with noNewStreak=4.
- Live provider, deployment, database, network, and authenticated runtime state were intentionally excluded.
- No exploit execution or external source read was performed.
- Excluded live Cloudflare account, Pages deployment, CDN/cache state, and response headers: User explicitly prohibited live Cloudflare mutation and the scan did not perform a live provider read.
- Excluded live GitHub branch protection, repository secrets, actions state, and provider configuration: User explicitly prohibited GitHub mutation and live external account access.
- Excluded live SQLite/PostgreSQL databases, storage buckets, deployments, paid services, Official publication, and external accounts: User explicitly required read-only repository analysis with no external state mutation.
- Excluded authenticated browser flows, exploit execution, external URL reads, and network/service mutation: The scan was source-backed and read-only; no external URL was authorized or fetched.

### Scan Summary

| Field | Value |
| --- | --- |
| Reportable DSS findings | 20 |
| Report instances | 20 |
| Report severity mix | medium: 20 |
| Report confidence mix | medium: 20 |
| Coverage | partial |
| Validation mode | Deep Scan compact candidate validation and centralized attack-path analysis |

Canonical artifacts: `scan-manifest.json`, `findings.json`, and `coverage.json`. This report is a deterministic projection of those files.

## Threat Model

Repository-wide validation threat model covering browser/Pages, governed Official artifacts, hostile source ingestion, CLI/operator inputs, SQLite/PostgreSQL and storage/recovery, CI/dependencies, and inert future operations. Preserve raw claims and append-only authority; fail closed when source, authorization, provenance, bounds, or activation proof is absent.

### Assets

- Raw source snapshots and claims
- Append-only governance and publication decisions
- Ledger databases, recovery bytes, credentials, and operator paths
- Demo/awaiting/Official UI state and published artifacts
- CI, dependency, workflow, and Pages release integrity

### Trust Boundaries

- Browser to static Pages
- Remote source/network to ingestion and snapshots
- Operator/CLI to filesystems and databases
- Ledger to storage/recovery providers
- Repository/build/CI to Pages publication
- Separate governance authorities

### Attacker Capabilities

- Anonymous browser control
- Malicious remote source content and network metadata
- Hostile pull requests, dependencies, actions, fixtures, and build inputs
- Mistaken or over-privileged local operators and same-host filesystem races
- Compromised provider, database, storage, or CI execution boundary

### Security Objectives

- Preserve exact provenance and raw values
- Prevent unauthorized claim/publication authority
- Bound resource use and prevent code/data disclosure
- Keep Official selection and release artifacts fail-closed
- Maintain append-only, attributable governance and recovery evidence

## Findings

| Findings | Reports | Severity | Confidence | Detailed write-up |
| --- | --- | --- | --- | --- |
| Review-only model output promoted through registry globbing | [occ_07221ff28767fb263bcf680a](#finding-1) | medium | medium | occ_07221ff28767fb263bcf680a: inline below |
| Duplicate model IDs block deterministic registry seeding | [occ_2ddb38775b08ca60780469b0](#finding-2) | medium | medium | occ_2ddb38775b08ca60780469b0: inline below |
| Raw discovery exception disclosure to CLI output | [occ_2eb9113574659e19e25f6741](#finding-3) | medium | medium | occ_2eb9113574659e19e25f6741: inline below |
| PATH-hijacked acceptance smoke executable | [occ_3498067ccad1626d6f469101](#finding-4) | medium | medium | occ_3498067ccad1626d6f469101: inline below |
| Malformed review candidates silently omitted | [occ_42c2012e01b16257b2eef603](#finding-5) | medium | medium | occ_42c2012e01b16257b2eef603: inline below |
| Unvalidated alias target can poison identity matching | [occ_440e9d0139879284d2ccfa4f](#finding-6) | medium | medium | occ_440e9d0139879284d2ccfa4f: inline below |
| Unbounded official candidate report database amplification | [occ_6ca7ddd69179ebb14ce2db0b](#finding-7) | medium | medium | occ_6ca7ddd69179ebb14ce2db0b: inline below |
| Unbounded local snapshot materialization before integrity verification | [occ_7957646c4a3a09911211528b](#finding-8) | medium | medium | occ_7957646c4a3a09911211528b: inline below |
| Unbounded PostgreSQL recovery backup materialization | [occ_848209a33f7f4be66b908614](#finding-9) | medium | medium | occ_848209a33f7f4be66b908614: inline below |
| CI Python dependency installation lacks artifact hashes | [occ_89e7e630115e0a63949e21bc](#finding-10) | medium | medium | occ_89e7e630115e0a63949e21bc: inline below |
| Legacy boolean coercion changes source revision identity | [occ_9a79a7336cde545d994ae4d0](#finding-11) | medium | medium | occ_9a79a7336cde545d994ae4d0: inline below |
| Silent partial registry reconciliation | [occ_9aea26568c5ca71863bf2f20](#finding-12) | medium | medium | occ_9aea26568c5ca71863bf2f20: inline below |
| Published build artifact is not bound to source provenance | [occ_b1a4ecb0ed03cca1530f2f95](#finding-13) | medium | medium | occ_b1a4ecb0ed03cca1530f2f95: inline below |
| Terminal control injection in raw claim and review output | [occ_bf5fc2403e720e1aa29e0f91](#finding-14) | medium | medium | occ_bf5fc2403e720e1aa29e0f91: inline below |
| Unbounded review queue pagination and malformed cursor crash | [occ_c3d5343ebccc827966734b00](#finding-15) | medium | medium | occ_c3d5343ebccc827966734b00: inline below |
| Mutable SQLite ingestion-run terminal history | [occ_ce5c3179ebcaa0a346f30b29](#finding-16) | medium | medium | occ_ce5c3179ebcaa0a346f30b29: inline below |
| Caller-controlled review actor attribution | [occ_d059a59adf0f369a1f16ab92](#finding-17) | medium | medium | occ_d059a59adf0f369a1f16ab92: inline below |
| Bundle freshness gate accepts stale output after deletion | [occ_f048ba2874ab8824eb4f3be6](#finding-18) | medium | medium | occ_f048ba2874ab8824eb4f3be6: inline below |
| Unbounded SQLite recovery backup materialization | [occ_f0c26100c8808ff91d568e3b](#finding-19) | medium | medium | occ_f0c26100c8808ff91d568e3b: inline below |
| Unbounded discovery fixture materialization | [occ_f90d7b2e7833150ed43bd91a](#finding-20) | medium | medium | occ_f90d7b2e7833150ed43bd91a: inline below |

### Confidence Scale

| Label | Meaning |
| --- | --- |
| high | Direct evidence supports the finding with no material unresolved blocker. |
| medium | Evidence supports a plausible issue, but material runtime or reachability proof remains. |
| low | Evidence is incomplete and the item is retained only for explicit follow-up. |

<a id="finding-1"></a>

### [1] Review-only model output promoted through registry globbing

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | supply-chain-integrity |
| CWE | CWE-284, CWE-829 |
| Affected lines | ledger/scripts/seed_models_from_hf.py:137-172, ledger/scripts/seed_models_from_hf.py:96-125, ledger/app/registry/seed_loader.py:45-58, ledger/app/registry/seed_loader.py:162-173, ledger/app/registry/models_hf_seed.yaml:1-8 |

#### Summary

The HF model tool emits rows marked active into a supposedly review-only file, while registry seeding automatically globs every sibling models\*.yaml file and treats it as authoritative input. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/scripts/seed_models_from_hf.py:137-151`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
        "--output",\n        type=Path,\n        required=True,\n        help="New review queue file to write. Refuses to overwrite an existing file.",\n    )\n    parser.add_argument(\n        "--registry-dir",\n        type=Path,\n        default=Path(__file__).resolve().parent.parent / "app" / "registry",\n        help="Registry directory to scan for existing (read-only) model IDs.",\n    )\n    args = parser.parse_args()\n\n    try:\n        candidates = _read_review_input(args.input)
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/scripts/seed_models_from_hf.py:137-151`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
        "--output",\n        type=Path,\n        required=True,\n        help="New review queue file to write. Refuses to overwrite an existing file.",\n    )\n    parser.add_argument(\n        "--registry-dir",\n        type=Path,\n        default=Path(__file__).resolve().parent.parent / "app" / "registry",\n        help="Registry directory to scan for existing (read-only) model IDs.",\n    )\n    args = parser.parse_args()\n\n    try:\n        candidates = _read_review_input(args.input)
```

#### Dataflow

The canonical finding records the affected path at ledger/scripts/seed_models_from_hf.py:137-172, ledger/scripts/seed_models_from_hf.py:96-125, ledger/app/registry/seed_loader.py:45-58, ledger/app/registry/seed_loader.py:162-173, ledger/app/registry/models_hf_seed.yaml:1-8, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Quarantine review output, require explicit promotion, and consume only allowlisted authoritative registry files.

Tests:
- Add a regression fixture covering Review-only model output promoted through registry globbing at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-2"></a>

### [2] Duplicate model IDs block deterministic registry seeding

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | availability-integrity |
| CWE | CWE-20 |
| Affected lines | ledger/app/registry/seed_loader.py:212-225, ledger/app/registry/models.yaml:22-64, ledger/app/registry/models_frontier.yaml:237, ledger/app/registry/models_frontier.yaml:423, ledger/app/registry/models_frontier.yaml:757, ledger/app/registry/seed_loader.py:45-89 |

#### Summary

The default registry seed and reseed path is unavailable because deterministic expansion of models\*.yaml finds three duplicate model IDs across the checked-in manifests and fails before any durable write. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/registry/seed_loader.py:212-225`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
    source_entries, source_ids = _validated_source_entries(_load_yaml(sources_path))\n    # Reject cross-file benchmark/model identity collisions before any durable\n    # write so a contradictory registry cannot silently seed a "first file\n    # wins" definition and drop the others. Selecting these files (and their\n    # deterministic ordering) happens here, once, and is reused by the change\n    # loop below.\n    benchmark_files = _registry_files(benchmarks_path, "benchmarks*.yaml")\n    model_files = _registry_files(models_path, "models*.yaml")\n    _validate_entity_ids(benchmark_files, "benchmarks")\n    _validate_entity_ids(model_files, "models")\n    # Preserve all-or-nothing behavior for the complete seed operation, even\n    # when a library caller catches an error and keeps using its outer session.\n    with session.begin_nested():\n        return _seed_registry_changes(
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/registry/seed_loader.py:212-225`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
    source_entries, source_ids = _validated_source_entries(_load_yaml(sources_path))\n    # Reject cross-file benchmark/model identity collisions before any durable\n    # write so a contradictory registry cannot silently seed a "first file\n    # wins" definition and drop the others. Selecting these files (and their\n    # deterministic ordering) happens here, once, and is reused by the change\n    # loop below.\n    benchmark_files = _registry_files(benchmarks_path, "benchmarks*.yaml")\n    model_files = _registry_files(models_path, "models*.yaml")\n    _validate_entity_ids(benchmark_files, "benchmarks")\n    _validate_entity_ids(model_files, "models")\n    # Preserve all-or-nothing behavior for the complete seed operation, even\n    # when a library caller catches an error and keeps using its outer session.\n    with session.begin_nested():\n        return _seed_registry_changes(
```

#### Dataflow

The canonical finding records the affected path at ledger/app/registry/seed_loader.py:212-225, ledger/app/registry/models.yaml:22-64, ledger/app/registry/models_frontier.yaml:237, ledger/app/registry/models_frontier.yaml:423, ledger/app/registry/models_frontier.yaml:757, ledger/app/registry/seed_loader.py:45-89, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Resolve duplicate model ownership and add pre-commit/CI uniqueness checks.

Tests:
- Add a regression fixture covering Duplicate model IDs block deterministic registry seeding at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-3"></a>

### [3] Raw discovery exception disclosure to CLI output

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | sensitive-error-disclosure |
| CWE | CWE-209 |
| Affected lines | ledger/app/cli.py:971-995, ledger/app/discovery/manifest.py:151-160, ledger/app/discovery/manifest.py:201-204, ledger/app/cli.py:978-984, ledger/app/discovery/manifest.py:151-160 |

#### Summary

Discovery failures are marked failed_closed but serialize raw exception text into JSON stderr, which can disclose filesystem paths, filenames, parser details, or underlying OS messages. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/cli.py:971-985`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
def _fail_discovery(exc: BaseException) -> None:\n    typer.echo(\n        json.dumps(\n            {\n                "availability": "candidate_only",\n                "status": "failed_closed",\n                "reasonCode": "DISCOVERY_INPUT_REJECTED",\n                "detail": str(exc),\n            },\n            sort_keys=True,\n        ),\n        err=True,\n    )\n    raise typer.Exit(code=2) from None\n
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/cli.py:971-985`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
def _fail_discovery(exc: BaseException) -> None:\n    typer.echo(\n        json.dumps(\n            {\n                "availability": "candidate_only",\n                "status": "failed_closed",\n                "reasonCode": "DISCOVERY_INPUT_REJECTED",\n                "detail": str(exc),\n            },\n            sort_keys=True,\n        ),\n        err=True,\n    )\n    raise typer.Exit(code=2) from None\n
```

#### Dataflow

The canonical finding records the affected path at ledger/app/cli.py:971-995, ledger/app/discovery/manifest.py:151-160, ledger/app/discovery/manifest.py:201-204, ledger/app/cli.py:978-984, ledger/app/discovery/manifest.py:151-160, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Replace raw exception text with stable bounded reason codes and redact paths, filenames, and provider details.

Tests:
- Add a regression fixture covering Raw discovery exception disclosure to CLI output at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-4"></a>

### [4] PATH-hijacked acceptance smoke executable

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | path-hijacking |
| CWE | CWE-427, CWE-426 |
| Affected lines | ledger/scripts/mvp_acceptance.sh:14-21, ledger/scripts/mvp_acceptance.sh:37-53, ledger/scripts/mvp_acceptance.sh:14-25, ledger/scripts/mvp_acceptance.sh:36-53, ledger/scripts/mvp_acceptance.sh:14-25, ledger/scripts/mvp_acceptance.sh:19-26, ledger/scripts/mvp_acceptance.sh:36-57 |

#### Summary

The acceptance smoke script prefers any benchmark-ledger found earlier on PATH instead of requiring the repository virtualenv executable. Additional discovery summary: The MVP acceptance script prefers any benchmark-ledger executable found on PATH over the project virtual-environment binary. Additional reducer summary: The acceptance smoke script selects the first benchmark-ledger executable from PATH and invokes it repeatedly, so a PATH-preceding executable can impersonate the intended CLI. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/scripts/mvp_acceptance.sh:14-21`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```shell
LEDGER_CLI="benchmark-ledger"\nHERE="$(cd "$(dirname "$0")" && pwd)"\nPROJECT="$(cd "$HERE/.." && pwd)"\ncd "$PROJECT"\n\nif ! command -v "$LEDGER_CLI" &>/dev/null; then\n    if [ -x "$PROJECT/.venv/bin/$LEDGER_CLI" ]; then\n        PATH="$PROJECT/.venv/bin:$PATH"
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/scripts/mvp_acceptance.sh:14-21`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```shell
LEDGER_CLI="benchmark-ledger"\nHERE="$(cd "$(dirname "$0")" && pwd)"\nPROJECT="$(cd "$HERE/.." && pwd)"\ncd "$PROJECT"\n\nif ! command -v "$LEDGER_CLI" &>/dev/null; then\n    if [ -x "$PROJECT/.venv/bin/$LEDGER_CLI" ]; then\n        PATH="$PROJECT/.venv/bin:$PATH"
```

#### Dataflow

The canonical finding records the affected path at ledger/scripts/mvp_acceptance.sh:14-21, ledger/scripts/mvp_acceptance.sh:37-53, ledger/scripts/mvp_acceptance.sh:14-25, ledger/scripts/mvp_acceptance.sh:36-53, ledger/scripts/mvp_acceptance.sh:14-25, ledger/scripts/mvp_acceptance.sh:19-26, ledger/scripts/mvp_acceptance.sh:36-57, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Resolve and invoke the repository virtualenv executable by absolute path and fail on mismatch.

Tests:
- Add a regression fixture covering PATH-hijacked acceptance smoke executable at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-5"></a>

### [5] Malformed review candidates silently omitted

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | input-omission |
| CWE | CWE-20 |
| Affected lines | ledger/scripts/seed_models_from_hf.py:45-46, ledger/scripts/seed_models_from_hf.py:64-66, ledger/scripts/seed_models_from_hf.py:169-172, ledger/scripts/seed_models_from_hf.py:105-107 |

#### Summary

The Hugging Face review-input parser silently drops malformed or id-less candidate entries instead of rejecting the input with an omission receipt. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/scripts/seed_models_from_hf.py:45-46`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
    The file is a list of model candidate maps, each carrying at least ``id``.\n    A malformed doc fails closed rather than generating a partial queue.
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/scripts/seed_models_from_hf.py:45-46`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
    The file is a list of model candidate maps, each carrying at least ``id``.\n    A malformed doc fails closed rather than generating a partial queue.
```

#### Dataflow

The canonical finding records the affected path at ledger/scripts/seed_models_from_hf.py:45-46, ledger/scripts/seed_models_from_hf.py:64-66, ledger/scripts/seed_models_from_hf.py:169-172, ledger/scripts/seed_models_from_hf.py:105-107, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Reject malformed or id-less review entries with an omission receipt and account for every input row.

Tests:
- Add a regression fixture covering Malformed review candidates silently omitted at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-6"></a>

### [6] Unvalidated alias target can poison identity matching

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | authorization-integrity |
| CWE | CWE-862, CWE-863, CWE-20 |
| Affected lines | ledger/app/cli.py:1123-1138, ledger/app/db/repositories.py:176-203, ledger/app/matching/aliases.py:38-60, ledger/app/ingestion/runner.py:377-390, ledger/app/cli.py:1123, ledger/app/cli.py:1130, ledger/app/db/models.py:106, ledger/app/matching/aliases.py:48, ledger/app/db/repositories.py:194, ledger/app/db/repositories.py:1158 |

#### Summary

The aliases add CLI path lacks explicit authorization and target existence/type validation, while matching trusts the polymorphic alias row during ingestion. Additional reducer summary: CLI alias insertion accepts arbitrary entity types and nonexistent entity IDs, while model resolution trusts the alias entity_id. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/cli.py:1123-1137`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
@aliases_app.command("add")\ndef aliases_add(\n    entity_type: str = typer.Option(..., "--entity-type"),\n    entity_id: str = typer.Option(..., "--entity-id"),\n    alias: str = typer.Option(..., "--alias"),\n) -> None:\n    with get_session() as session:\n        row = repo.add_alias(\n            session,\n            entity_type=entity_type,\n            entity_id=entity_id,\n            alias_text=alias,\n            is_official_alias=False,\n            alias_source="cli",\n        )
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/cli.py:1123-1137`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
@aliases_app.command("add")\ndef aliases_add(\n    entity_type: str = typer.Option(..., "--entity-type"),\n    entity_id: str = typer.Option(..., "--entity-id"),\n    alias: str = typer.Option(..., "--alias"),\n) -> None:\n    with get_session() as session:\n        row = repo.add_alias(\n            session,\n            entity_type=entity_type,\n            entity_id=entity_id,\n            alias_text=alias,\n            is_official_alias=False,\n            alias_source="cli",\n        )
```

#### Dataflow

The canonical finding records the affected path at ledger/app/cli.py:1123-1138, ledger/app/db/repositories.py:176-203, ledger/app/matching/aliases.py:38-60, ledger/app/ingestion/runner.py:377-390, ledger/app/cli.py:1123, ledger/app/cli.py:1130, ledger/app/db/models.py:106, ledger/app/matching/aliases.py:48, ledger/app/db/repositories.py:194, ledger/app/db/repositories.py:1158, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Validate entity type and target existence before alias insertion and test poisoned aliases cannot affect official matching.

Tests:
- Add a regression fixture covering Unvalidated alias target can poison identity matching at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-7"></a>

### [7] Unbounded official candidate report database amplification

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | resource-exhaustion |
| CWE | CWE-400 |
| Affected lines | ledger/app/export/official_json.py:524-538, ledger/app/reporting/legacy_inventory.py:341-371, ledger/app/export/official_json.py:366-412, ledger/app/reporting/legacy_inventory.py:396-415 |

#### Summary

Official candidate and legacy inventory reports materialize all claims and perform repeated per-claim database queries without a cardinality or paging guard. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/export/official_json.py:524-538`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
def analyze_official_feed_candidates(session: Session) -> FeedCandidateAnalysis:\n    """Account for every claim under the deterministic candidate policy.\n\n    This is an offline read model.  It does not choose a winner for a\n    conflicting display cell and it does not write an assessment back to the\n    ledger.  Callers that need a candidate feed must reject conflicts rather\n    than treating this analysis as a partial export.\n    """\n    with session.no_autoflush:\n        claims = list(session.scalars(select(models.ResultClaim).order_by(models.ResultClaim.id)))\n        eligible_by_cell: dict[str, list[_EligibleClaim]] = defaultdict(list)\n        excluded_claims: list[dict[str, str]] = []\n        for claim in claims:\n            candidate, reason = _eligible_claim(session, claim)\n            if candidate is None:
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/export/official_json.py:524-538`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
def analyze_official_feed_candidates(session: Session) -> FeedCandidateAnalysis:\n    """Account for every claim under the deterministic candidate policy.\n\n    This is an offline read model.  It does not choose a winner for a\n    conflicting display cell and it does not write an assessment back to the\n    ledger.  Callers that need a candidate feed must reject conflicts rather\n    than treating this analysis as a partial export.\n    """\n    with session.no_autoflush:\n        claims = list(session.scalars(select(models.ResultClaim).order_by(models.ResultClaim.id)))\n        eligible_by_cell: dict[str, list[_EligibleClaim]] = defaultdict(list)\n        excluded_claims: list[dict[str, str]] = []\n        for claim in claims:\n            candidate, reason = _eligible_claim(session, claim)\n            if candidate is None:
```

#### Dataflow

The canonical finding records the affected path at ledger/app/export/official_json.py:524-538, ledger/app/reporting/legacy_inventory.py:341-371, ledger/app/export/official_json.py:366-412, ledger/app/reporting/legacy_inventory.py:396-415, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Page/batch claims, bound report cardinality and per-claim queries, and add large-ledger tests.

Tests:
- Add a regression fixture covering Unbounded official candidate report database amplification at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-8"></a>

### [8] Unbounded local snapshot materialization before integrity verification

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | resource-exhaustion |
| CWE | CWE-400 |
| Affected lines | ledger/app/ingestion/runner.py:268-280, ledger/app/storage/local.py:537-542, ledger/app/storage/local.py:487-496, ledger/app/backup/service.py:728-745, ledger/app/storage/local.py:487-542, ledger/app/backup/service.py:1043-1066 |

#### Summary

Local snapshot verification reads a complete backing file into memory before digest verification or an effective bounded read. Additional discovery summary: Local immutable recovery objects are read as complete files and repeatedly materialized without a bounded cumulative checkpoint or decoded-memory limit. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/ingestion/runner.py:268-280`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
        if existing:\n            # A matching database hash is not proof that its URI still\n            # contains the recorded immutable bytes.  Do not reuse a\n            # snapshot unless storage verifies the full digest.\n            verification = storage.verify_snapshot(\n                uri=existing.raw_content_uri,\n                content_sha256=content_hash,\n            )\n            _require_verification_receipt(\n                verification,\n                uri=existing.raw_content_uri,\n                content_hash=content_hash,\n                byte_length=len(snap_input.raw_bytes),
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/ingestion/runner.py:268-280`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
        if existing:\n            # A matching database hash is not proof that its URI still\n            # contains the recorded immutable bytes.  Do not reuse a\n            # snapshot unless storage verifies the full digest.\n            verification = storage.verify_snapshot(\n                uri=existing.raw_content_uri,\n                content_sha256=content_hash,\n            )\n            _require_verification_receipt(\n                verification,\n                uri=existing.raw_content_uri,\n                content_hash=content_hash,\n                byte_length=len(snap_input.raw_bytes),
```

#### Dataflow

The canonical finding records the affected path at ledger/app/ingestion/runner.py:268-280, ledger/app/storage/local.py:537-542, ledger/app/storage/local.py:487-496, ledger/app/backup/service.py:728-745, ledger/app/storage/local.py:487-542, ledger/app/backup/service.py:1043-1066, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Use bounded streaming reads for local snapshot verification and cap retained-object size before digesting.

Tests:
- Add a regression fixture covering Unbounded local snapshot materialization before integrity verification at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-9"></a>

### [9] Unbounded PostgreSQL recovery backup materialization

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | resource-exhaustion |
| CWE | CWE-400 |
| Affected lines | ledger/app/cli.py:369-384, ledger/app/backup/postgresql_driver.py:1928-1959, ledger/app/backup/service.py:673-723, ledger/app/backup/postgresql_driver.py:506-600, ledger/app/backup/postgresql_driver.py:1957-1960 |

#### Summary

PostgreSQL recovery backups retain complete pg_dump artifacts as bytes through inspection and storage without an archive-size bound or streaming path. Additional discovery summary: PostgreSQL recovery buffers tool output and later loads complete dump bytes without a bounded cumulative limit. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/cli.py:369-383`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
@recovery_app.command("checkpoint-postgresql")\ndef recovery_checkpoint_postgresql(\n    trigger: Path = typer.Option(..., "--trigger"),\n    primary_root: Path = typer.Option(..., "--primary-root"),\n    primary_domain_id: str = typer.Option(..., "--primary-domain-id"),\n    recovery_root: Path = typer.Option(..., "--recovery-root"),\n    recovery_domain_id: str = typer.Option(..., "--recovery-domain-id"),\n    inspection_target_id: str = typer.Option(..., "--inspection-target-id"),\n    manifest_output: Path = typer.Option(..., "--manifest-output"),\n) -> None:\n    """Checkpoint PostgreSQL through fixed PG16 tools and one fresh inspection DB.\n\n    Connection material is accepted only through\n    ``LEDGER_RECOVERY_POSTGRESQL_SOURCE_URL`` and\n    ``LEDGER_RECOVERY_POSTGRESQL_INSPECTION_URL``. The command does not create,
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/cli.py:369-383`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
@recovery_app.command("checkpoint-postgresql")\ndef recovery_checkpoint_postgresql(\n    trigger: Path = typer.Option(..., "--trigger"),\n    primary_root: Path = typer.Option(..., "--primary-root"),\n    primary_domain_id: str = typer.Option(..., "--primary-domain-id"),\n    recovery_root: Path = typer.Option(..., "--recovery-root"),\n    recovery_domain_id: str = typer.Option(..., "--recovery-domain-id"),\n    inspection_target_id: str = typer.Option(..., "--inspection-target-id"),\n    manifest_output: Path = typer.Option(..., "--manifest-output"),\n) -> None:\n    """Checkpoint PostgreSQL through fixed PG16 tools and one fresh inspection DB.\n\n    Connection material is accepted only through\n    ``LEDGER_RECOVERY_POSTGRESQL_SOURCE_URL`` and\n    ``LEDGER_RECOVERY_POSTGRESQL_INSPECTION_URL``. The command does not create,
```

#### Dataflow

The canonical finding records the affected path at ledger/app/cli.py:369-384, ledger/app/backup/postgresql_driver.py:1928-1959, ledger/app/backup/service.py:673-723, ledger/app/backup/postgresql_driver.py:506-600, ledger/app/backup/postgresql_driver.py:1957-1960, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Stream or cap PostgreSQL backup bytes and inspection output; enforce archive, TOC, and database-size budgets.

Tests:
- Add a regression fixture covering Unbounded PostgreSQL recovery backup materialization at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-10"></a>

### [10] CI Python dependency installation lacks artifact hashes

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | dependency-integrity |
| CWE | CWE-494 |
| Affected lines | .github/workflows/verify.yml:59, ledger/requirements-ci.lock:10, .github/workflows/verify.yml:64 |

#### Summary

CI installs exact-version Python dependencies without artifact hash verification. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `.github/workflows/verify.yml:59`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```text
          python-version: '3.11'
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `.github/workflows/verify.yml:59`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```text
          python-version: '3.11'
```

#### Dataflow

The canonical finding records the affected path at .github/workflows/verify.yml:59, ledger/requirements-ci.lock:10, .github/workflows/verify.yml:64, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Install from the hashed lock and verify artifact hashes or trusted package provenance before CI execution.

Tests:
- Add a regression fixture covering CI Python dependency installation lacks artifact hashes at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-11"></a>

### [11] Legacy boolean coercion changes source revision identity

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | data-integrity |
| CWE | CWE-20, CWE-345 |
| Affected lines | ledger/migrations/versions/0002_governance_history.py:145-155, ledger/migrations/versions/0002_governance_history.py:160-197 |

#### Summary

Legacy evidence backfill converts boolean fields with Python bool(), treating textual false values as true and changing source revision identity. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/migrations/versions/0002_governance_history.py:145-155`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
def _backfill_legacy_evidence() -> None:\n    bind = op.get_bind()\n    source_rows = bind.execute(sa.text("SELECT * FROM official_sources ORDER BY id")).mappings().all()\n    source_revisions: dict[str, str] = {}\n\n    for source in source_rows:\n        definition = {field: _json_value(source[field], {}) if field == "parser_config" else source[field] for field in _SOURCE_FIELDS}\n        definition["parser_config"] = _json_value(definition["parser_config"], {})\n        for boolean_field in ("machine_readable", "requires_auth", "supports_history"):\n            definition[boolean_field] = bool(definition[boolean_field])\n        encoded_definition = _canonical_json(definition)
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/migrations/versions/0002_governance_history.py:145-155`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
def _backfill_legacy_evidence() -> None:\n    bind = op.get_bind()\n    source_rows = bind.execute(sa.text("SELECT * FROM official_sources ORDER BY id")).mappings().all()\n    source_revisions: dict[str, str] = {}\n\n    for source in source_rows:\n        definition = {field: _json_value(source[field], {}) if field == "parser_config" else source[field] for field in _SOURCE_FIELDS}\n        definition["parser_config"] = _json_value(definition["parser_config"], {})\n        for boolean_field in ("machine_readable", "requires_auth", "supports_history"):\n            definition[boolean_field] = bool(definition[boolean_field])\n        encoded_definition = _canonical_json(definition)
```

#### Dataflow

The canonical finding records the affected path at ledger/migrations/versions/0002_governance_history.py:145-155, ledger/migrations/versions/0002_governance_history.py:160-197, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Parse legacy booleans strictly and quarantine ambiguous textual values instead of coercing identity inputs.

Tests:
- Add a regression fixture covering Legacy boolean coercion changes source revision identity at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-12"></a>

### [12] Silent partial registry reconciliation

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | partial-reconciliation |
| CWE | CWE-20 |
| Affected lines | ledger/app/cli.py:651-667, ledger/app/registry/seed_loader.py:61-89, ledger/app/registry/seed_loader.py:119-184, ledger/app/registry/seed_loader.py:119-184 |

#### Summary

Registry seeding fails closed for non-mapping documents but silently skips malformed or wrong-type models/benchmarks collections and rows, allowing a partial registry reconciliation to report success. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/cli.py:651-665`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
@app.command("seed-registry")\ndef seed_registry_cmd(\n    benchmarks: Path = typer.Option(_default_registry_dir() / "benchmarks.yaml", exists=True),\n    models: Path = typer.Option(_default_registry_dir() / "models.yaml", exists=True),\n    sources: Path = typer.Option(_default_registry_dir() / "official_sources.yaml", exists=True),\n) -> None:\n    """Reconcile curated registry YAML files through immutable source revisions."""\n    init_db()\n    with get_session() as session:\n        counts = seed_registry(\n            session,\n            benchmarks_path=benchmarks,\n            models_path=models,\n            sources_path=sources,\n            retire_missing=True,
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/cli.py:651-665`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
@app.command("seed-registry")\ndef seed_registry_cmd(\n    benchmarks: Path = typer.Option(_default_registry_dir() / "benchmarks.yaml", exists=True),\n    models: Path = typer.Option(_default_registry_dir() / "models.yaml", exists=True),\n    sources: Path = typer.Option(_default_registry_dir() / "official_sources.yaml", exists=True),\n) -> None:\n    """Reconcile curated registry YAML files through immutable source revisions."""\n    init_db()\n    with get_session() as session:\n        counts = seed_registry(\n            session,\n            benchmarks_path=benchmarks,\n            models_path=models,\n            sources_path=sources,\n            retire_missing=True,
```

#### Dataflow

The canonical finding records the affected path at ledger/app/cli.py:651-667, ledger/app/registry/seed_loader.py:61-89, ledger/app/registry/seed_loader.py:119-184, ledger/app/registry/seed_loader.py:119-184, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Reject malformed or wrong-type registry collections with an omission receipt and fail closed before publication preparation.

Tests:
- Add a regression fixture covering Silent partial registry reconciliation at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-13"></a>

### [13] Published build artifact is not bound to source provenance

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | artifact-provenance |
| CWE | CWE-345 |
| Affected lines | .github/workflows/verify.yml:160-165, scripts/verify-bundle-budget.mjs:300-365, scripts/verify-pages-static.mjs:91-108 |

#### Summary

Build checks validate shape, freshness, containment, and size but do not bind the published dist artifact to a source digest or authorized signed manifest. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `.github/workflows/verify.yml:160-165`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```text
      - name: Build\n        run: npm run build\n      - name: Verify static Pages artifact\n        run: npm run verify:pages-static\n      - name: Verify bundle budget\n        run: npm run verify:bundle-budget
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `.github/workflows/verify.yml:160-165`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```text
      - name: Build\n        run: npm run build\n      - name: Verify static Pages artifact\n        run: npm run verify:pages-static\n      - name: Verify bundle budget\n        run: npm run verify:bundle-budget
```

#### Dataflow

The canonical finding records the affected path at .github/workflows/verify.yml:160-165, scripts/verify-bundle-budget.mjs:300-365, scripts/verify-pages-static.mjs:91-108, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Bind dist to a source digest and authorized signed manifest and verify that binding in CI and Pages publication.

Tests:
- Add a regression fixture covering Published build artifact is not bound to source provenance at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-14"></a>

### [14] Terminal control injection in raw claim and review output

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | terminal-output-injection |
| CWE | CWE-116, CWE-150, CWE-117 |
| Affected lines | ledger/app/schemas/boundary.py:51-69, ledger/app/cli.py:739-746, ledger/app/cli.py:749-768, ledger/app/cli.py:793-800, ledger/app/ingestion/json_lexemes.py:117-122, ledger/app/cli.py:739-768, ledger/app/ingestion/adapters/generic_json.py:78-108, ledger/app/ingestion/admission.py:654-657, ledger/app/cli.py:745, ledger/app/schemas/boundary.py:51-69, ledger/app/cli.py:793-801, ledger/app/cli.py:796-800, ledger/app/cli.py:704-736, ledger/app/cli.py:734, ledger/app/cli.py:757-766, ledger/app/cli.py:744-746, ledger/app/cli.py:744-746, ledger/app/cli.py:756-768, ledger/app/cli.py:756-768, ledger/app/cli.py:731-734, ledger/app/schemas/boundary.py:51-75, ledger/app/cli.py:795-800, ledger/app/cli.py:795-800, ledger/app/ingestion/json_lexemes.py:117-122, ledger/app/schemas/boundary.py:51-69, ledger/app/cli.py:739-800, ledger/app/ingestion/adapters/generic_json.py:69-106, ledger/app/cli.py:793-801, ledger/app/cli.py:731-734, ledger/app/schemas/boundary.py:51-75, ledger/app/db/models.py:249-261, ledger/app/ingestion/adapters/generic_json.py:66-80, ledger/app/ingestion/json_lexemes.py:117-122, ledger/app/schemas/boundary.py:57-64, ledger/app/cli.py:757-764, ledger/app/ingestion/json_lexemes.py:117-128, ledger/app/ingestion/admission.py:656-680, ledger/app/cli.py:731-768 |

#### Summary

Admitted raw claim fields are emitted directly to terminal output without control-character escaping, permitting terminal escape/control injection for an operator viewing claims or review queues. Also: The claims-list CLI renders source-controlled raw claim fields directly to the terminal without control-character neutralization, allowing terminal escape-sequence injection. Also: The claims-show CLI renders source-controlled raw claim fields directly to the terminal without control-character neutralization, allowing terminal escape-sequence injection. Also: The dry-run sample CLI prints source-controlled model_raw, benchmark_raw, and score_raw fields directly to the terminal without control-character neutralization, allowing terminal escape-sequence injection. Also: The review-queue CLI renders source-controlled raw claim fields directly to the terminal without control-character neutralization, allowing terminal escape-sequence injection. Additional reducer evidence: Claims list output does not neutralize persisted source-controlled raw fields. Claims show output does not neutralize persisted source-controlled fields or evidence locations. Ingestion dry-run output interpolates source-controlled model and score strings without terminal/log neutralization. Review queue output does not neutralize persisted source-controlled fields. Additional reducer summary: CLI commands emit attacker-controlled raw source and evidence strings directly to the operator terminal without control or ANSI/newline neutralization. Additional manifestation: Raw model, benchmark, and score fields are Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/schemas/boundary.py:51-65`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
class ResultClaimInput(BaseModel):\n    source_snapshot_id: UUID | None = None\n    source_revision_decision_id: UUID | None = None\n    official_source_id: str\n    benchmark_id: str | None = None\n    model_entity_id: str | None = None\n    model_raw: StrictStr\n    benchmark_raw: StrictStr\n    score_raw: StrictStr\n    metric_raw: StrictStr | None = None\n    split_raw: StrictStr | None = None\n    setting_raw: StrictStr | None = None\n    evaluation_version_raw: StrictStr | None = None\n    rank_raw: StrictStr | None = None\n    date_raw: StrictStr | None = None
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/schemas/boundary.py:51-65`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
class ResultClaimInput(BaseModel):\n    source_snapshot_id: UUID | None = None\n    source_revision_decision_id: UUID | None = None\n    official_source_id: str\n    benchmark_id: str | None = None\n    model_entity_id: str | None = None\n    model_raw: StrictStr\n    benchmark_raw: StrictStr\n    score_raw: StrictStr\n    metric_raw: StrictStr | None = None\n    split_raw: StrictStr | None = None\n    setting_raw: StrictStr | None = None\n    evaluation_version_raw: StrictStr | None = None\n    rank_raw: StrictStr | None = None\n    date_raw: StrictStr | None = None
```

#### Dataflow

The canonical finding records the affected path at ledger/app/schemas/boundary.py:51-69, ledger/app/cli.py:739-746, ledger/app/cli.py:749-768, ledger/app/cli.py:793-800, ledger/app/ingestion/json_lexemes.py:117-122, ledger/app/cli.py:739-768, ledger/app/ingestion/adapters/generic_json.py:78-108, ledger/app/ingestion/admission.py:654-657, ledger/app/cli.py:745, ledger/app/schemas/boundary.py:51-69, ledger/app/cli.py:793-801, ledger/app/cli.py:796-800, ledger/app/cli.py:704-736, ledger/app/cli.py:734, ledger/app/cli.py:757-766, ledger/app/cli.py:744-746, ledger/app/cli.py:744-746, ledger/app/cli.py:756-768, ledger/app/cli.py:756-768, ledger/app/cli.py:731-734, ledger/app/schemas/boundary.py:51-75, ledger/app/cli.py:795-800, ledger/app/cli.py:795-800, ledger/app/ingestion/json_lexemes.py:117-122, ledger/app/schemas/boundary.py:51-69, ledger/app/cli.py:739-800, ledger/app/ingestion/adapters/generic_json.py:69-106, ledger/app/cli.py:793-801, ledger/app/cli.py:731-734, ledger/app/schemas/boundary.py:51-75, ledger/app/db/models.py:249-261, ledger/app/ingestion/adapters/generic_json.py:66-80, ledger/app/ingestion/json_lexemes.py:117-122, ledger/app/schemas/boundary.py:57-64, ledger/app/cli.py:757-764, ledger/app/ingestion/json_lexemes.py:117-128, ledger/app/ingestion/admission.py:656-680, ledger/app/cli.py:731-768, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Escape control characters and render terminal output through a safe representation; add ANSI and OSC fixtures for every raw claim field.

Tests:
- Add a regression fixture covering Terminal control injection in raw claim and review output at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-15"></a>

### [15] Unbounded review queue pagination and malformed cursor crash

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | resource-exhaustion |
| CWE | CWE-20, CWE-400 |
| Affected lines | ledger/app/cli.py:804-821, ledger/app/db/repositories.py:1342-1359, ledger/app/db/repositories.py:1414-1419, ledger/app/cli.py:804-817, ledger/app/db/repositories.py:1313-1317, ledger/app/cli.py:739-742, ledger/app/db/repositories.py:1276-1285, ledger/app/db/repositories.py:1414-1419 |

#### Summary

Review queue cursor parsing calls .get() on any JSON value without first requiring an object, so a caller-supplied array/number can raise an uncaught AttributeError; positive page limits also have no upper bound. Additional discovery summary: CLI pagination limits are described or implemented as bounded but have no upper bound, allowing very large SQL result windows to be materialized in memory. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/cli.py:804-818`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
@review_app.command("queue")\ndef review_queue(limit: int = 50, cursor: Optional[str] = None) -> None:\n    """Print a bounded review-queue page with explicit continuation.\n\n    ``cursor`` is an opaque token returned as ``Next cursor`` on a prior page;\n    pass it back to fetch the following page.  Output reasons and the queue\n    review containment rules are unchanged.\n    """\n    with get_session() as session:\n        try:\n            page = repo.list_review_queue_page(\n                session,\n                limit=limit,\n                cursor=cursor,\n            )
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/cli.py:804-818`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
@review_app.command("queue")\ndef review_queue(limit: int = 50, cursor: Optional[str] = None) -> None:\n    """Print a bounded review-queue page with explicit continuation.\n\n    ``cursor`` is an opaque token returned as ``Next cursor`` on a prior page;\n    pass it back to fetch the following page.  Output reasons and the queue\n    review containment rules are unchanged.\n    """\n    with get_session() as session:\n        try:\n            page = repo.list_review_queue_page(\n                session,\n                limit=limit,\n                cursor=cursor,\n            )
```

#### Dataflow

The canonical finding records the affected path at ledger/app/cli.py:804-821, ledger/app/db/repositories.py:1342-1359, ledger/app/db/repositories.py:1414-1419, ledger/app/cli.py:804-817, ledger/app/db/repositories.py:1313-1317, ledger/app/cli.py:739-742, ledger/app/db/repositories.py:1276-1285, ledger/app/db/repositories.py:1414-1419, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Require an object cursor, bound page limits, and return stable CLI errors for malformed input.

Tests:
- Add a regression fixture covering Unbounded review queue pagination and malformed cursor crash at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-16"></a>

### [16] Mutable SQLite ingestion-run terminal history

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | mutable-audit-history |
| CWE | CWE-284, CWE-345, CWE-693, CWE-915 |
| Affected lines | ledger/migrations/versions/0011_ingestion_run_hardening.py:21-24, ledger/app/db/repositories.py:1237-1255, ledger/migrations/versions/0003_snapshot_revision_identity.py:84-92, ledger/app/config.py:17-20, ledger/migrations/versions/0003_snapshot_revision_identity.py:84-92, ledger/app/db/repositories.py:1237-1255, ledger/migrations/versions/0011_ingestion_run_hardening.py:25-57, ledger/migrations/versions/0011_ingestion_run_hardening.py:1-5, ledger/migrations/versions/0011_ingestion_run_hardening.py:21-23, ledger/migrations/versions/0011_ingestion_run_hardening.py:21-23, ledger/app/ingestion/runner.py:663-671, ledger/migrations/versions/0003_snapshot_revision_identity.py:84-92, ledger/migrations/versions/0003_snapshot_revision_identity.py:84-93, ledger/migrations/versions/0010_operational_persistence.py:29-51, ledger/migrations/versions/0011_ingestion_run_hardening.py:21-23, ledger/migrations/versions/0010_operational_persistence.py:912-933 |

#### Summary

SQLite ingestion-run terminal history remains mutable after creation because finalize-once and terminal-row immutability hardening is PostgreSQL-only; repeated application finalization or a SQLite writer can rewrite terminal status, evidence, counters, errors, or metadata. Additional reducer summary: Migration 0011 installs the one-time ingestion-run finalization trigger only on PostgreSQL; SQLite retains only a delete guard, while finish_ingestion_run accepts arbitrary counter keys via hasattr and can update identity/history fields. Additional reducer summary: SQLite does not receive the PostgreSQL ingestion-run finalization guard, leaving local terminal run history mutable. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/migrations/versions/0011_ingestion_run_hardening.py:21-24`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
def upgrade() -> None:\n    if not is_postgresql():\n        return\n
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/migrations/versions/0011_ingestion_run_hardening.py:21-24`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
def upgrade() -> None:\n    if not is_postgresql():\n        return\n
```

#### Dataflow

The canonical finding records the affected path at ledger/migrations/versions/0011_ingestion_run_hardening.py:21-24, ledger/app/db/repositories.py:1237-1255, ledger/migrations/versions/0003_snapshot_revision_identity.py:84-92, ledger/app/config.py:17-20, ledger/migrations/versions/0003_snapshot_revision_identity.py:84-92, ledger/app/db/repositories.py:1237-1255, ledger/migrations/versions/0011_ingestion_run_hardening.py:25-57, ledger/migrations/versions/0011_ingestion_run_hardening.py:1-5, ledger/migrations/versions/0011_ingestion_run_hardening.py:21-23, ledger/migrations/versions/0011_ingestion_run_hardening.py:21-23, ledger/app/ingestion/runner.py:663-671, ledger/migrations/versions/0003_snapshot_revision_identity.py:84-92, ledger/migrations/versions/0003_snapshot_revision_identity.py:84-93, ledger/migrations/versions/0010_operational_persistence.py:29-51, ledger/migrations/versions/0011_ingestion_run_hardening.py:21-23, ledger/migrations/versions/0010_operational_persistence.py:912-933, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Apply SQLite finalize-once and terminal-row immutability constraints and add repeated-finalization/direct-writer tests.

Tests:
- Add a regression fixture covering Mutable SQLite ingestion-run terminal history at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-17"></a>

### [17] Caller-controlled review actor attribution

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | audit-integrity |
| CWE | CWE-345 |
| Affected lines | ledger/app/cli.py:853-866, ledger/app/db/repositories.py:1095-1139, ledger/app/db/models.py:288-295 |

#### Summary

The review map-model command persists a caller-supplied --actor string as review-decision provenance without identity binding or authentication. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/cli.py:853-866`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
def review_map_model(\n    claim_id: str,\n    model_entity_id: str,\n    actor: str = typer.Option("cli", "--actor", help="Recorded decision actor"),\n) -> None:\n    """Append a manual model-identity decision without promoting the claim."""\n    try:\n        with get_session() as session:\n            decision = repo.append_manual_model_mapping(\n                session,\n                result_claim_id=claim_id,\n                model_entity_id=model_entity_id,\n                actor=actor,\n            )
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/cli.py:853-866`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
def review_map_model(\n    claim_id: str,\n    model_entity_id: str,\n    actor: str = typer.Option("cli", "--actor", help="Recorded decision actor"),\n) -> None:\n    """Append a manual model-identity decision without promoting the claim."""\n    try:\n        with get_session() as session:\n            decision = repo.append_manual_model_mapping(\n                session,\n                result_claim_id=claim_id,\n                model_entity_id=model_entity_id,\n                actor=actor,\n            )
```

#### Dataflow

The canonical finding records the affected path at ledger/app/cli.py:853-866, ledger/app/db/repositories.py:1095-1139, ledger/app/db/models.py:288-295, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Bind actor identity to the invoking principal or trusted environment and reject arbitrary provenance strings.

Tests:
- Add a regression fixture covering Caller-controlled review actor attribution at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-18"></a>

### [18] Bundle freshness gate accepts stale output after deletion

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | stale-artifact |
| CWE | CWE-345, CWE-59, CWE-693 |
| Affected lines | scripts/verify-bundle-budget.mjs:408-413, scripts/verify-bundle-budget.mjs:300-310, scripts/verify-bundle-budget.mjs:251-280, scripts/verify-bundle-budget.mjs:357-365, scripts/verify-bundle-budget.mjs:251-281, scripts/verify-bundle-budget.mjs:300-310, package.json:16, scripts/verify-bundle-budget.mjs:62-71, scripts/verify-bundle-budget.mjs:300-309, scripts/verify-bundle-budget.mjs:265-281, scripts/verify-bundle-budget-node-tests.mjs:267-289 |

#### Summary

The bundle freshness gate walks only existing source files and can accept stale dist output after a source or public file is deleted. Additional discovery summary: Bundle freshness ignores symlink entries under src or public, so changes to a symlink target can leave stale dist output accepted. Additional discovery summary: Bundle freshness verification omits postcss, Tailwind, and TypeScript configuration inputs, so a dist artifact can remain accepted after changes to those build inputs. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `scripts/verify-bundle-budget.mjs:408-413`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```javascript
    const result = await verifyBundleBudget(options);\n    console.log(\n      `Bundle budget passed: eagerJs=${result.eagerJsBytes} totalJs=${result.totalJsBytes} ` +\n        `(eager<=${result.budget.eagerBytes} total<=${result.budget.totalBytes}).\n` +\n        result.chunks\n    );
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `scripts/verify-bundle-budget.mjs:408-413`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```javascript
    const result = await verifyBundleBudget(options);\n    console.log(\n      `Bundle budget passed: eagerJs=${result.eagerJsBytes} totalJs=${result.totalJsBytes} ` +\n        `(eager<=${result.budget.eagerBytes} total<=${result.budget.totalBytes}).\n` +\n        result.chunks\n    );
```

#### Dataflow

The canonical finding records the affected path at scripts/verify-bundle-budget.mjs:408-413, scripts/verify-bundle-budget.mjs:300-310, scripts/verify-bundle-budget.mjs:251-280, scripts/verify-bundle-budget.mjs:357-365, scripts/verify-bundle-budget.mjs:251-281, scripts/verify-bundle-budget.mjs:300-310, package.json:16, scripts/verify-bundle-budget.mjs:62-71, scripts/verify-bundle-budget.mjs:300-309, scripts/verify-bundle-budget.mjs:265-281, scripts/verify-bundle-budget-node-tests.mjs:267-289, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Include deleted/symlinked inputs and all build configuration in freshness accounting; require a fresh build.

Tests:
- Add a regression fixture covering Bundle freshness gate accepts stale output after deletion at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-19"></a>

### [19] Unbounded SQLite recovery backup materialization

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | resource-exhaustion |
| CWE | CWE-400 |
| Affected lines | ledger/app/cli.py:303-308, ledger/app/backup/sqlite_driver.py:303-321, ledger/app/backup/service.py:673-723, ledger/app/backup/sqlite_driver.py:321, ledger/app/backup/sqlite_driver.py:197-205, ledger/app/backup/service.py:630-667 |

#### Summary

SQLite recovery backups materialize complete database artifacts as bytes through inspection and storage without an archive-size bound or streaming path. Additional discovery summary: SQLite recovery loads complete database bytes and fetches complete table inspection results without a pre-read or cumulative memory bound. Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/cli.py:303-308`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
@recovery_app.command("checkpoint-sqlite")\ndef recovery_checkpoint_sqlite(\n    database_source: Path = typer.Option(\n        ...,\n        "--database-source",\n        help="Explicit existing SQLite source; DATABASE_URL is never consulted",
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/cli.py:303-308`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
@recovery_app.command("checkpoint-sqlite")\ndef recovery_checkpoint_sqlite(\n    database_source: Path = typer.Option(\n        ...,\n        "--database-source",\n        help="Explicit existing SQLite source; DATABASE_URL is never consulted",
```

#### Dataflow

The canonical finding records the affected path at ledger/app/cli.py:303-308, ledger/app/backup/sqlite_driver.py:303-321, ledger/app/backup/service.py:673-723, ledger/app/backup/sqlite_driver.py:321, ledger/app/backup/sqlite_driver.py:197-205, ledger/app/backup/service.py:630-667, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Stream or cap SQLite backup and inspection bytes before storage and test oversized fixtures.

Tests:
- Add a regression fixture covering Unbounded SQLite recovery backup materialization at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

<a id="finding-20"></a>

### [20] Unbounded discovery fixture materialization

| Field | Value |
| --- | --- |
| Severity | medium |
| Confidence | medium |
| Confidence rationale | Direct source locations support the control gap and consequence, but no live exploit, authenticated deployment, live database, GitHub setting, or Cloudflare state was exercised. |
| Category | resource-exhaustion |
| CWE | CWE-400, CWE-770, CWE-59 |
| Affected lines | ledger/app/discovery/manifest.py:144-159, ledger/app/discovery/manifest.py:227-231, ledger/app/discovery/connectors/base.py:74-76, ledger/app/discovery/connectors/base.py:74-76, ledger/app/discovery/controller.py:238-243, ledger/app/discovery/connectors/base.py:94-100, ledger/app/schemas/coverage_contracts.py:923-944, ledger/app/discovery/controller.py:238-245, ledger/app/discovery/connectors/base.py:74-99, ledger/app/discovery/connectors/base.py:65-78, ledger/app/discovery/connectors/base.py:74-80, ledger/app/cli.py:987-1010, ledger/app/cli.py:1063-1081, ledger/app/discovery/manifest.py:149-163, ledger/app/discovery/manifest.py:149-163, ledger/app/discovery/controller.py:209-218, ledger/app/discovery/connectors/base.py:73-76, ledger/app/discovery/connectors/base.py:76-105, ledger/app/discovery/connectors/base.py:76-105, ledger/app/discovery/manifest.py:228-236, ledger/app/discovery/connectors/base.py:74-99, ledger/app/discovery/manifest.py:145-160, ledger/app/discovery/controller.py:215-218, ledger/app/discovery/connectors/base.py:74-78, ledger/app/discovery/manifest.py:145-163, ledger/app/cli.py:998-1010, ledger/app/discovery/manifest.py:219-237, ledger/app/discovery/manifest.py:135-163, ledger/app/cli.py:1080, ledger/app/discovery/connectors/base.py:76, ledger/app/discovery/manifest.py:149, ledger/app/discovery/manifest.py:158, ledger/app/cli.py:1063-1093, ledger/app/discovery/connectors/base.py:54-76, ledger/app/discovery/manifest.py:120-155, ledger/app/discovery/connectors/base.py:94-105, ledger/app/discovery/manifest.py:135-163, ledger/app/discovery/connectors/base.py:74-78, ledger/app/cli.py:1063-1100, ledger/app/discovery/manifest.py:135-163, ledger/app/discovery/connectors/base.py:74-105, ledger/app/discovery/connectors/base.py:65-78, ledger/app/discovery/connectors/base.py:74-102, ledger/app/discovery/manifest.py:211-219, ledger/app/discovery/manifest.py:228-245, ledger/app/discovery/manifest.py:92-163, ledger/app/discovery/manifest.py:135-150, ledger/app/discovery/connectors/base.py:65-76, ledger/app/discovery/manifest.py:228-231, ledger/app/discovery/controller.py:236-243, ledger/app/discovery/manifest.py:135-163, ledger/app/discovery/manifest.py:219-237, ledger/app/discovery/manifest.py:245-255, ledger/app/discovery/connectors/base.py:79-105, ledger/app/discovery/controller.py:235-245, ledger/app/discovery/manifest.py:240-255, ledger/app/cli.py:998-1008, ledger/app/discovery/manifest.py:144-163 |

#### Summary

Discovery JSON inputs are read and decoded without byte, decoded-object, file-count, or enumeration limits, allowing operator-selected fixture data to consume excessive memory or work. The canonical issue explicitly includes StaticFixtureConnector's unbounded static.json read/parse, tuple materialization, and controller persistence path. Additional reducer evidence: The StaticFixtureConnector specifically reads connectors/static.json with no byte, candidate-count, or parsing budget before assembly. Additional reducer evidence: Caller-selected discovery manifest files are read and parsed without byte or structural resource budgets. Static discovery connector JSON and candidate materialization are unbounded. Discovery fixture loading materializes JSON and candidate collections without byte, nesting, file-count, or candidate-count limits despite the connector contract claiming bounded observations. Additional reducer summary: Discovery fixture JSON is fully read and parsed without an explicit byte bound before candidate assembly. Additional reducer summary: Discovery fixture JSON is buffered and parsed without file-size, target-count, or aggregate fixture limits. Additional reducer summary: Fixture JSON loading has no byte or structural resource bound. Additional reducer detail: The static fixture connector reopens fixture data by raw path and parses it without the descriptor-safe root and byte-boundary protections used by manifest loading. Additional reducer summary: Static discovery fixture input and candidate fan-out are unbounded Additional merged manifestation: Discovery Validated as a reportable source-level finding; no live external state was assumed.

#### Root Cause

A source- or operator-controlled value reaches a security-relevant consumer without the required bound, authorization, provenance, or immutable-state check.

**Source evidence for the candidate control** — `ledger/app/discovery/manifest.py:144-158`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
    try:\n        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)\n    except OSError:\n        _fail(f"{label}: cannot read {name}")\n    try:\n        with os.fdopen(descriptor, "rb", closefd=True) as handle:\n            raw = handle.read()\n    except OSError as exc:\n        _fail(f"{label}: cannot read {name}: {exc.strerror or exc}")\n    try:\n        text = raw.decode("utf-8")\n    except UnicodeDecodeError as exc:\n        _fail(f"{label}: {name} is not valid UTF-8: {exc}")\n    try:\n        payload = json.loads(text)
```

#### Validation

Direct source evidence supports the control gap and stated consequence; runtime and external-state limitations remain explicit.

Validation method: centralized static source validation over the canonical candidate, exact locations, ordered worker evidence, and parent threat model.

**Source evidence for the candidate control** — `ledger/app/discovery/manifest.py:144-158`

The cited implementation is the candidate's source boundary; the downstream consumer relies on it to preserve the stated security invariant.

```python
    try:\n        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)\n    except OSError:\n        _fail(f"{label}: cannot read {name}")\n    try:\n        with os.fdopen(descriptor, "rb", closefd=True) as handle:\n            raw = handle.read()\n    except OSError as exc:\n        _fail(f"{label}: cannot read {name}: {exc.strerror or exc}")\n    try:\n        text = raw.decode("utf-8")\n    except UnicodeDecodeError as exc:\n        _fail(f"{label}: {name} is not valid UTF-8: {exc}")\n    try:\n        payload = json.loads(text)
```

#### Dataflow

The canonical finding records the affected path at ledger/app/discovery/manifest.py:144-159, ledger/app/discovery/manifest.py:227-231, ledger/app/discovery/connectors/base.py:74-76, ledger/app/discovery/connectors/base.py:74-76, ledger/app/discovery/controller.py:238-243, ledger/app/discovery/connectors/base.py:94-100, ledger/app/schemas/coverage_contracts.py:923-944, ledger/app/discovery/controller.py:238-245, ledger/app/discovery/connectors/base.py:74-99, ledger/app/discovery/connectors/base.py:65-78, ledger/app/discovery/connectors/base.py:74-80, ledger/app/cli.py:987-1010, ledger/app/cli.py:1063-1081, ledger/app/discovery/manifest.py:149-163, ledger/app/discovery/manifest.py:149-163, ledger/app/discovery/controller.py:209-218, ledger/app/discovery/connectors/base.py:73-76, ledger/app/discovery/connectors/base.py:76-105, ledger/app/discovery/connectors/base.py:76-105, ledger/app/discovery/manifest.py:228-236, ledger/app/discovery/connectors/base.py:74-99, ledger/app/discovery/manifest.py:145-160, ledger/app/discovery/controller.py:215-218, ledger/app/discovery/connectors/base.py:74-78, ledger/app/discovery/manifest.py:145-163, ledger/app/cli.py:998-1010, ledger/app/discovery/manifest.py:219-237, ledger/app/discovery/manifest.py:135-163, ledger/app/cli.py:1080, ledger/app/discovery/connectors/base.py:76, ledger/app/discovery/manifest.py:149, ledger/app/discovery/manifest.py:158, ledger/app/cli.py:1063-1093, ledger/app/discovery/connectors/base.py:54-76, ledger/app/discovery/manifest.py:120-155, ledger/app/discovery/connectors/base.py:94-105, ledger/app/discovery/manifest.py:135-163, ledger/app/discovery/connectors/base.py:74-78, ledger/app/cli.py:1063-1100, ledger/app/discovery/manifest.py:135-163, ledger/app/discovery/connectors/base.py:74-105, ledger/app/discovery/connectors/base.py:65-78, ledger/app/discovery/connectors/base.py:74-102, ledger/app/discovery/manifest.py:211-219, ledger/app/discovery/manifest.py:228-245, ledger/app/discovery/manifest.py:92-163, ledger/app/discovery/manifest.py:135-150, ledger/app/discovery/connectors/base.py:65-76, ledger/app/discovery/manifest.py:228-231, ledger/app/discovery/controller.py:236-243, ledger/app/discovery/manifest.py:135-163, ledger/app/discovery/manifest.py:219-237, ledger/app/discovery/manifest.py:245-255, ledger/app/discovery/connectors/base.py:79-105, ledger/app/discovery/controller.py:235-245, ledger/app/discovery/manifest.py:240-255, ledger/app/cli.py:998-1008, ledger/app/discovery/manifest.py:144-163, but no expanded source-to-sink narrative was recorded.

#### Reachability

Reachability was not recorded beyond the canonical finding summary and affected locations.

#### Severity

**Medium** — The source evidence supports a concrete integrity, availability, audit, or release consequence at a constrained local, CLI, CI, ingestion, registry, or build boundary.

Confirm the affected execution mode and preserve the source-to-sink proof in a regression test before remediation.

#### Remediation

Bound fixture bytes, decoded object size, file count, and enumeration before JSON decoding.

Tests:
- Add a regression fixture covering Unbounded discovery fixture materialization at the cited source boundary.
- Run the relevant ledger, CI, or build path with adversarial input and verify fail-closed behavior.

Preventive controls:
- Keep the boundary-specific invariant in the contract and review checklist.
- Require provenance and runtime/deployment evidence before promoting dormant or conditional paths.

## Reviewed Surfaces

| Surface | Risk Area | Outcome | Notes |
| --- | --- | --- | --- |
| Frontend browser and dataset trust boundaries | artifact selection, provenance, DOM/CSS safety | Reported | Reportable dataset/build findings were retained; dormant Official and chart-input candidates remain conditional where no active caller exists. |
| Local Cloudflare Pages headers and static verification | release artifact and served metadata integrity | Reported | Build freshness/provenance gaps survived; header and metadata parser candidates remain follow-up where live serving was not verified. |
| Python ledger ingestion and source adapters | hostile source parsing, provenance, resource bounds | Needs follow-up | Parser and transport candidates are deferred because default transport and Official publication are disabled; local report paths survived. |
| CLI, registry, review, and governance flows | authorization, identity, omission, audit lineage | Reported | Registry, review, alias, actor, output, and acceptance-tool findings survived; other operator-only candidates remain conditional. |
| SQLite/PostgreSQL persistence, migrations, backup, and recovery | append-only state, path safety, integrity, availability | Reported | SQLite terminal history and local recovery materialization survived; race, direct-writer, PostgreSQL role, and provider candidates remain deferred. |
| Storage, recovery, and object-provider integrations | bounded reads, target containment, restore integrity | Needs follow-up | Local paths were reviewed; R2/provider and race conditions require runtime proof excluded by scope. |
| CI, dependencies, tests, and supply chain | untrusted code execution, dependency and tool provenance | Reported | Dependency, PATH, review-output, and registry promotion controls were reviewed; live GitHub settings and secrets were not checked. |
| Contracts, schemas, and future operational services | semantic drift, dormant activation, notification and scheduling | Needs follow-up | Schema-only, draft-design, and inactive provider candidates remain deferred rather than current runtime vulnerabilities. |

## Open Questions And Follow Up

- Which deferred ingestion parsers and transports will be enabled when Official capture is authorized, and what decoded-work budgets will apply?
- Which live CI/GitHub secrets, branch protections, runner restrictions, and package provenance controls are configured?
- What signed manifest, cache/withdrawal behavior, and browser-loader authorization will bind a future Official artifact?
- Which database roles and direct-writer paths are deployed for PostgreSQL governance and operational tables?
- Remote source content is attacker-influenced if an approved source is compromised or serves malicious bytes; impact is ingestion-worker availability rather than frontend data integrity. The related BigCodeBench manifestation requires a crafted high-expansion Parquet artifact and runtime measurement. Remote source content is attacker-controlled once a source revision is admitted. Accepted or locally supplied Parquet source processed by the ingestion path. Current default SafeFetch transport is disabled and the repository treats live ingestion as dormant, so reachability is conditional on an approved transport/adapter activation. The current fixture/test path can still invoke the resolver locally. The supplied discovery also identifies the BigCodeBench adapter as a concrete reachable manifestation of the Parquet resolver boundary. Future certified remote Parquet path; current transport is disabled. Additional reducer context: A raw snapshot byte bound does not constrain decompressed size or Python object cardinality; a crafted accepted Parquet artifact could exhaust memory or CPU. The resolver is run-scoped and closed, which limits lifetime but not peak allocation or decompression wo
  - Follow-up prompt: Review deferred unit candidate-8ebf270b0d26904c and close its stated proof gap.
- This is a documentation/procedure supply-chain candidate; no external URL was opened or fetched during discovery. Additional discovery context: A compromised upstream or repository process could inject code into the application build. The path is a documented/process-controlled supply-chain boundary and requires validation of whether the plan is still used. Additional discovery context: Documentation-only supply-chain candidate. Validate whether the procedure is still used, whether the checked-in vendored files are independently reviewed, and whether immutable archive verification exists outside this plan.
  - Follow-up prompt: Review deferred unit candidate-e68df7652fbc4d8c and close its stated proof gap.
- Local contributor/operator supply-chain candidate; the documentation recommends a disposable environment and this does not directly alter the production runtime. Additional reducer context: CI uses hash-locked installation, but maintainers following README/CONTRIBUTING can execute unreviewed dependency versions or build hooks. Additional discovery context: This is a supply-chain reproducibility candidate; the CI workflow has a separate lock-verification control. Additional discovery context: The repository contains a reviewed lockfile and lock verification script; this candidate applies to installation or deployment paths that follow the README command rather than the locked CI path. Additional discovery context: This is a developer/operator supply-chain candidate, not evidence that a dependency is currently compromised.
  - Follow-up prompt: Review deferred unit candidate-653e4428221101c5 and close its stated proof gap.
- CI-only candidate. The workflow grants contents: read and declares no production credentials, which limits impact but does not make the package provenance deterministic. Additional reducer context: Actions and the PostgreSQL image are pinned, but this system package installation remains a mutable privileged supply-chain input. Additional context: Candidate supply-chain integrity issue (CWE-494). Reachability depends on the GitHub-hosted runner image missing the preinstalled binaries and on compromise or malicious package publication in the configured apt supply chain; no CI run was executed. Additional discovery context: This is a CI supply-chain candidate on pull-request verification runners; the job uses the installed client immediately afterward, but no exact package version, repository snapshot, or digest is asserted. Additional discovery context: The workflow has read-only GitHub permissions and no production credentials; runner/apt signature behavior remains external. Additional discovery context: The workflow grants contents:read and does not provide production credentials, limiting potential impact to the verification runner and build integrity. Additional discovery context
  - Follow-up prompt: Review deferred unit candidate-83459d3ed9f0db57 and close its stated proof gap.
- The default transport is disabled and a real runner transport is not present, so exploitability requires the future NETWORK_FETCH path or an injected transport that does not independently enforce peer pinning. The related transport-contract candidate identifies the same missing binding from DNS preflight to the connected peer and TLS endpoint. Current policy has no production-eligible source and the default transport is disabled, limiting present reachability. Enabled custom network transport used for an ingestion route. The ordinary runtime currently disables the default transport, so this remains conditional on an enabled or injected network transport. Requires deployment of a non-disabled transport; the current repository default does not provide one. Additional reducer context: The current DisabledNetworkTransport fails closed and explicitly says a runner-specific peer-pinning transport is required. Treat this as deferred until a real transport is introduced; validate the actual transport and egress controls before reporting it as exploitable. Additional reducer context: Treat as a future/explicit-network candidate, not proof that the current default makes outbound requests. Va
  - Follow-up prompt: Review deferred unit candidate-e9636866cb04f53e and close its stated proof gap.
- A forged direct INSERT was not executed; observed impact is potentially falsified persisted notification/recovery evidence, not demonstrated outbound delivery. Additional reducer context: Direct database insertion boundary; application validators require a recovery predecessor, but trigger behavior permits a null predecessor branch. Additional reducer context (candidate-56d3854323e4bbf8): Requires access to the privileged ingestion database role or an equivalent direct-write path; static evidence only. The affected row is operational evidence, but its integrity can affect recovery/notification accounting and downstream trust.
  - Follow-up prompt: Review deferred unit candidate-e407df5951a71cd8 and close its stated proof gap.
- The seam is dormant: loadOfficialData still parses the tracked unavailable artifact, and no v2 artifact or authorization wiring exists. Deferred before REL-05 activation; current runtime does not accept an external Official artifact. Deferred future-activation candidate. The parser is deliberately dormant during containment and loadOfficialData does not call it. This candidate becomes reachable when the planned v2 publication path is enabled and must be resolved by the parent against the governed release-process boundary. Additional discovery context: This cannot activate Official data while availability remains unavailable and arrays are empty, but a standalone build can carry stale or tampered containment metadata unless verification is a mandatory release prerequisite. Additional discovery context: Validate whether any future governed Official artifact can reach runtime without the CI gate or whether deployment always guarantees the exact verified bytes.
  - Follow-up prompt: Review deferred unit candidate-f53fee12db85e4d1 and close its stated proof gap.
- No enabled transport implementation exists in the reviewed repository; an external runner may enforce limits independently. Latent transport-contract weakness; current default composition fails closed. The default transport is disabled and the real peer-pinning transport is an unimplemented runner dependency, so this candidate is conditional on a future or injected transport implementation. The missing pre-buffer limit is nevertheless at the central network trust boundary. Additional reducer context: The default transport is disabled and the observed impact is resource consumption in a custom/enabled transport; the limit still protects downstream parsing after materialization. The default DisabledNetworkTransport currently fails closed, but this remains a future runner-specific transport boundary; any enabled transport must enforce the bound while reading. Additional reducer context: The default runtime transport is disabled, so reachability currently requires an enabled custom transport. A remote response larger than the certified limit can nevertheless be allocated before rejection. Additional reducer context: The default network transport is disabled and the normal runtime requi
  - Follow-up prompt: Review deferred unit candidate-e6f5e2bec602dab6 and close its stated proof gap.
- Requires local ability to swap the fixture root or connector path during execution; no network-facing discovery caller was established. Operational discovery is designed read-only but its resulting candidates are persisted as operational read-model data. Local fixture-root attacker with write access during discovery execution. This is a local/operator-triggered or shared-fixture attack, not an anonymous public route. It matters if fixture roots are writable by another account/process or are used as a future discovery input boundary. The new evidence distinguishes the controller wrapper, manifest validation, and connector sink while preserving the local fixture-only reachability and persisted-candidate impact. Requires local fixture-root mutation or a planted symlink; discovery output is candidate/quarantine data and does not itself authorize capture or publication. Requires local fixture-root mutation or a planted symlink; no publication authority is granted by this path. Additional reducer evidence: The fixture connector feeds candidate assembly and persistence; the root is intended to be a closed fixture-only trust boundary. Exploitability depends on another actor being able to m
  - Follow-up prompt: Review deferred unit candidate-d2c2d0f1e991cf6a and close its stated proof gap.
- The current public/_headers contains the expected directives; no malicious fixture or deployed-header check was run. Additional reducer detail: The verifier is a release control rather than a request-time boundary; validation should reproduce a false-positive header fixture and compare it with the generated/deployed header semantics. Additional discovery context: This is a build/release control candidate. Validate against an actual Pages parser or response from the deployed artifact before assigning impact.
  - Follow-up prompt: Review deferred unit candidate-f16f847761289252 and close its stated proof gap.
- No current attacker-controlled XSS flow was established; this is a defense-in-depth and future-reachability candidate, with no live header verification performed. Edge/CDN headers outside the repository were not inspected. This is a client-side destination-control candidate, not a server-side SSRF path. It requires a malicious or compromised governed artifact; no server-side fetch was found. Additional reducer evidence: The repository comment makes this a deliberate pre-domain posture, but it remains a concrete production defense-in-depth gap for a public static application. Additional reducer context: This is a deployment configuration weakness; current verification explicitly accepts the report-only header. Additional discovery context: The repository deliberately defers enforcing CSP pending real domain/browser/deployment evidence, and current callers may not expose a direct injection source. Additional discovery context: Shipped static URLs are repository-controlled HTTPS values, and Official artifact source URLs use stricter validation; reachability is conditional on catalog integrity or future untrusted input. Additional discovery context: Configuration-level evidence only; l
  - Follow-up prompt: Review deferred unit candidate-6d1d7c5be30eea86 and close its stated proof gap.
- Current adapters use fixed keys and colors; no attacker-controlled flow was established. Later validation should exercise the exported component directly. Dormant/deferred generic-component hazard. Before chart configuration or color data can come from an Official/remote artifact, constrain CSS identifiers and color grammar or construct styles without HTML injection. Additional reducer context: Current adapters use React-generated IDs, fixed config keys, and fixed palette colors; an attacker-controlled path into these values was not established. Additional merged context: No current untrusted caller was confirmed; validate whether the vendored component is reachable with remote or artifact-controlled ChartConfig. Additional discovery context: Conditional candidate; no external dataset value was evidenced reaching this vendored chart sink. Additional discovery context: Current application call sites use static palette values, so this remains a latent trust-boundary candidate unless an attacker-controlled or tampered ChartConfig reaches the exported helper. Additional discovery context: Conditional frontend CSS injection candidate; no untrusted ChartConfig source was identified and n
  - Follow-up prompt: Review deferred unit candidate-eb0edabf7619e0ab and close its stated proof gap.
- Test/tooling candidate; current safe-fetch default remains disabled but future helper changes could bypass the lexical gate. Test/control-coverage candidate; current helper scripts are retired stubs. No assigned symlink was present; this is a conditional test coverage gap. Conditional test coverage gap; no current alternate archive directory was observed. Additional reducer context: Policy/test-control candidate; validate whether all runnable Python is guaranteed to live under the two roots and whether another static or runtime gate closes alias and root-level coverage. Additional discovery context: No concrete bypass file was observed and current tracked helpers are documented as retired or stubbed. This is a security-test coverage candidate requiring validation, not an established product runtime path.
  - Follow-up prompt: Review deferred unit candidate-b50c98e6e4fd2bd0 and close its stated proof gap.
- Separate instances affect benchmark statistics/best-model maps and model rank/category-leader maps. Additional discovery context: Demo-only candidate; current catalog contains no colliding identifier, but a tracked catalog change could corrupt lead counts or presentation. Additional discovery context: Future Official v2 path; current loadOfficialData imports only the unavailable containment artifact, so this is not active today. Additional discovery context: Conditional frontend data-integrity candidate; no runtime exploit path was validated.
  - Follow-up prompt: Review deferred unit candidate-f155e019a1e0c75b and close its stated proof gap.
- Separate receipt instance from source-approval envelope; parent validation should determine whether this is only a test contract or an authority used by runtime.
  - Follow-up prompt: Review deferred unit candidate-de6ab7b19944621c and close its stated proof gap.
- Distinct resource-exhaustion instances are unbounded collections and unbounded identifier/string lengths. Deferred before accepting externally supplied Official artifacts; no active runtime caller. Additional reducer context: The v2 published parser is currently dormant because loadOfficialData only loads the unavailable containment artifact, so current production reachability is deferred. The missing bound remains a release-boundary availability risk when Official mode is enabled or when a governed artifact is maliciously oversized. Additional reducer context: Deferred future-artifact candidate; current runtime loads only the unavailable v1 artifact, and existing tracked artifacts are small. Additional discovery context: Future governed Official v2 path; an oversized authorized artifact could consume browser CPU/memory, but no current production caller loads published v2 data.
  - Follow-up prompt: Review deferred unit candidate-9cd2ffe39a0f9ceb and close its stated proof gap.
- A separate local-storage instance uses full-file read before digest verification at ledger/app/storage/local.py:487-496 and 537-542. Additional reducer evidence: Fetch admission bounds source artifacts, but object storage reads also serve existing and artifact objects and need an independent read bound. The storage client/provider is injected and external storage is not activated by default; this remains a deferred R2 integration risk unless that boundary is enabled. Additional reducer context: Reachability depends on the external snapshot-storage capability; local content-addressed storage is the default. Additional discovery context: Requires an oversized or malicious local snapshot/provider response and a reachable storage implementation; validate provider and caller limits. Additional discovery context: The injected R2 client/provider is an application-only boundary and normal source admission caps fetched bytes, but a malicious or compromised provider response can cause memory exhaustion before digest/metadata checks fail.
  - Follow-up prompt: Review deferred unit candidate-bf75463228150c8a and close its stated proof gap.
- Dormant until REL-05; distinct validators may make different publication decisions for the same artifact. Additional discovery context: The parser is dormant: loadOfficialData currently loads only the unavailable artifact and no v2 authorization caller or artifact was observed. Impact is Official metadata contract integrity if the future governed path is activated.
  - Follow-up prompt: Review deferred unit candidate-c4a738d8489b0695 and close its stated proof gap.
- Local operator filesystem threat; existing checks reduce but do not eliminate ancestor/path races. Additional reducer evidence: This is a source-integrity and provenance boundary for recovery artifacts. Exploitability depends on another actor being able to mutate the selected SQLite path during backup. Additional reducer context: Local filesystem race affecting recovery evidence placement and target isolation. Requires a local actor able to replace or race the target parent during restore. Requires local control of the restore target's parent path. Additional reducer context: CLI callers perform additional path admission, but direct library callers supplying paths remain conditional on attacker control of an ancestor directory or a race during path traversal. This is an operator-invoked recovery route with a user-selected fresh target; the source artifact is trusted recovery data, so path redirection can leak or misplace it. Additional reducer context: The recovery CLI is an operator or administrator path. Validate attacker control over the target path and the exact filesystem boundary that the command is expected to enforce. Additional reducer context: Reachable through explicit l
  - Follow-up prompt: Review deferred unit candidate-e7c51e1f82e62aea and close its stated proof gap.
- Custom transport or caller-controlled fetch metadata in an ingestion execution. Attacker or corrupted source definition able to supply parser_config marker values.
  - Follow-up prompt: Review deferred unit candidate-01c880fca9d55cb4 and close its stated proof gap.
- Accepted CSV source reaching generic or FrontierMath extraction. The source byte limit is the only visible input bound at these parser and evidence paths. Additional reducer context: The risk is amplified when many claims resolve against the same CSV and when the source is enabled through the explicit network runtime. Parent validation should determine whether source-specific contracts or operational limits reduce reachability. Additional reducer context: Static_csv is not in the current blocked source types, but only raw bytes are bounded and no row, cell, column, or output budget is enforced. Additional reducer context (dedup-0028): This is deferred to the enabled remote ingestion runner; validation should provide a byte-limit-compliant CSV with many rows/columns and measure memory/latency before considering severity. Additional discovery context: The wire artifact is capped at 64 MiB but row count and field sizes remain unbounded; the generic CSV route is present in active registry entries even though malformed contract bindings may later fail closed. Additional discovery context: The source is expected to be governed, but remote content is attacker-controlled once a future cert
  - Follow-up prompt: Review deferred unit candidate-a669a50e91ca6b5a and close its stated proof gap.
- Source or fixture routed through the GitHub YAML adapter. Future certified remote YAML path; current transport is disabled. The raw source byte cap does not constrain YAML expansion, aliases, nesting, or row count. Additional discovery context: Potentially availability-only. The adapter emits yaml_path evidence while certified locator types are limited to json_path_v1, json_script_path_v1, csv_cell_v1, and parquet_cell_v1; claim persistence may therefore reject the output after extraction. The adapter is present in the active registry, but normal production reachability still requires the immutable source-contract admission path and an enabled runner transport.
  - Follow-up prompt: Review deferred unit candidate-6804794d2c66d57f and close its stated proof gap.
- Accepted JSON source with many claims or deeply nested structure. The source admission byte cap limits transfer size but not JSON expansion, container structure, row count, or repeated decoding. Additional reducer context: This requires an enabled network source or another path that admits attacker-controlled artifact bytes. Parent validation should account for the actual source policy and worker memory limits. Additional reducer context: Static_json is not in the current blocked source types, but raw response bytes are the main cap and no JSON depth, node, row, or output budget is enforced. Additional reducer context: Conditional on a certified remote source or fixture reaching this adapter; the current default transport is disabled, but a future private runner is explicitly expected to supply transport. Additional discovery context: A source response within the certified byte limit can still cause excessive memory or CPU use. The default runtime currently disables live transport and source admission requires a certified immutable revision; the path becomes reachable when a static JSON source is certified and a runner transport is enabled. Additional discovery context: This route
  - Follow-up prompt: Review deferred unit candidate-832a1c31b62a90d8 and close its stated proof gap.
- This is dormant: loadOfficialData() currently loads only the tracked unavailable artifact, and the published parser requires a separately supplied release authorization. Treat as a pre-REL-05 hardening candidate rather than a current anonymous SSRF finding; client navigation is not a server-side request.
  - Follow-up prompt: Review deferred unit candidate-6d7c5e73e90ffb0d and close its stated proof gap.
- Future certified remote HTML path; current transport is disabled. The source byte cap does not bound DOM size, traversal, table/row/cell count, or parser CPU. Additional discovery context: The adapter is used for untrusted source content; a large or parser-pathological HTML document can consume excessive CPU or memory during ingestion. source_admission_reason currently quarantines html_table sources before this adapter runs; this remains a latent re-enablement risk for any future certified HTML route. Additional discovery context: This adapter is not the central typed evidence contract and appears legacy/fixture-oriented, so reachability into certified ingestion is conditional. If re-enabled for admitted sources, attacker-controlled HTML could cause parser resource exhaustion. Additional discovery context: The repository’s source policy currently blocks some HTML source types and network is disabled by default; this remains a reachable local/future-adapter parser path that needs explicit limits or isolation before activation.
  - Follow-up prompt: Review deferred unit candidate-10408e51a6a1ff53 and close its stated proof gap.
- The ordinary containment runtime currently disables network fetch, so live exploitation requires a future certified source runner or an equivalent local execution path. The gap remains in the source-admission execution boundary that the threat model reserves for governed ingestion. Future certified remote artifact path; current transport is disabled. The source is a certified remote artifact in the future ingestion path; current transport is disabled. Deferred future-activation candidate; no live transport is enabled. The source byte cap bounds transfer size but not script count, HTML parser work, collected content, decoded result count, or repeated validation work. Additional merged context: Current production routes are policy-contained; confirm whether any future admitted structured source can supply a large bounded body and whether downstream quotas make the resource exhaustion materially reachable. Additional merged context: Deferred/reachability-dependent candidate for the future network-enabled ingestion path; the 64 MiB cap limits bytes but does not bound rows, claims, or per-claim work. Additional reducer context: Distinct CSV and HTML parser routes share the missing struc
  - Follow-up prompt: Review deferred unit candidate-7a0b95fcca13e8a0 and close its stated proof gap.
- Disclosure depends on attacker-influenced parser/provider errors or local filesystem failures. Additional reducer context: The path is reachable from ingestion failure handling and is most relevant once an admitted source or injected integration can raise an exception whose text contains attacker-controlled or secret-bearing data. Parent validation should confirm which concrete adapters/providers preserve such details. Additional discovery context: Conditional confidentiality/logging candidate; impact depends on an exception implementation or provider exposing sensitive details, but the sinks are active ingestion and CLI paths. Additional reducer context: Ledger operational-error disclosure candidate; SafeFetchError is reduced to stable codes, but generic adapter/parser/database/provider exceptions are handled separately. Additional merged context: The contained default runtime disables live transport and current contracts forbid source credentials, but injected/future adapters and runtime integrations are explicitly part of the composition boundary. The issue is information exposure through durable local ledger receipts and terminal/log capture. Additional reducer context: Validat
  - Follow-up prompt: Review deferred unit candidate-13ec2bf313835612 and close its stated proof gap.
- Additional reducer context: The current published-source path is separately constrained and rel=noreferrer limits referrer leakage; validation should determine whether any reachable caller can supply sensitive query or fragment data. Additional discovery context: The Official parser separately rejects search and hash components, so this candidate is limited to manual/alternate data and requires a secret-bearing URL to be supplied. Additional discovery context: The official artifact parser has a stricter query/hash-free URL check, but the exported component and Demo dataset path do not preserve that invariant. Additional discovery context: Current benchmark JSON URLs have no query or fragment and Official parsing is stricter; validate whether future Demo or fixture data can be attacker-influenced.
  - Follow-up prompt: Review deferred unit candidate-fcedb9aeacb050f8 and close its stated proof gap.
- The official parser is currently dormant because loadOfficialData() loads an unavailable artifact; requires a separately supplied authorized v2 artifact. Additional reducer context: Reachability is dormant until a governed v2 Official artifact is enabled; current Official loading is unavailable/empty. Additional discovery context: This can misrepresent official metrics whose domain is not 0..scaleMax or whose values should remain raw. Additional discovery context: The same score may therefore appear as a small raw integer on /100 surfaces while being represented as a percentage in chart surfaces.
  - Follow-up prompt: Review deferred unit candidate-65bfb1d757519148 and close its stated proof gap.
- Requires a separately supplied authorized v2 artifact; no published artifact is active. Additional reducer context: Reachability is dormant until Official publication is enabled; current Official loading is unavailable/empty. Additional reducer context: Deferred future-artifact candidate; current runtime loads only the unavailable v1 artifact and no v2 authorization was present. Additional discovery context: A malformed published score can affect raw rankings while being omitted from normalized charts. Additional discovery context: Impact is primarily integrity/misleading-public-data unless an attacker can influence an Official artifact; validate the full artifact admission and benchmark scale contract.
  - Follow-up prompt: Review deferred unit candidate-3add880358d17a77 and close its stated proof gap.
- Requires a local actor able to swap the source while the staged copy is in progress. Requires a local actor able to swap the migration source during the read window; deterministic drift checks do not prove race resistance. Additional merged context: Requires local filesystem mutation during migration and is platform-dependent; validate whether earlier inspection or operating-system policy makes special files unreachable.
  - Follow-up prompt: Review deferred unit candidate-a120ce507ae33046 and close its stated proof gap.
- Requires a local actor able to replace the checkpoint source during the validation/open window.
  - Follow-up prompt: Review deferred unit candidate-76eeeb8b3410ed95 and close its stated proof gap.
- Requires an operator-supplied local recovery path with a planted ancestor symlink. Additional reducer evidence: The helper documentation claims symlink-parent containment, but the admission check does not pin every ancestor inode through the later write. The default runtime is offline/inert and reachability depends on an activated runner or local filesystem attacker controlling the configured storage root. Additional reducer context: The restore-root is operator-supplied. Validate missing-root and ancestor-symlink cases, including whether the command is available to a lower-trust actor. Additional merged context: Static symlink cases are covered, but concurrent ancestor replacement is not; validate each caller's path binding and platform-specific descriptor semantics. Additional discovery context: Live checkpoint/restore path; requires a local actor able to rename or replace the admitted root's parent between preflight and use. Additional discovery context: Attacker control of configuration is not established; this remains a conditional local containment candidate. Additional discovery context: Requires local filesystem control of the configured path or its ancestors before runtime
  - Follow-up prompt: Review deferred unit candidate-73d5b16d74c0d403 and close its stated proof gap.
- No current external reference was found; the candidate concerns the build verification boundary. Additional reducer detail: This is a conditional release-integrity candidate, not proof that the current build contains an external executable reference; later validation must inspect actual build inputs and deployment policy. Additional merged context: Current source HTML references local modules and the Official artifact is unavailable; validate whether any build/plugin can introduce executable external URLs and whether an enforcing deployment CSP exists. Additional discovery context: No current external script was observed; this is a release/build-boundary candidate if an upstream or contributor-controlled build adds one.
  - Follow-up prompt: Review deferred unit candidate-aa00e4dcbf71d3f9 and close its stated proof gap.
- This is distinct from object-store root handling because it affects receipt/manifest evidence output. Additional discovery context: Requires local control of or a race against an ancestor in the requested recovery output path.
  - Follow-up prompt: Review deferred unit candidate-913e8dc5da1ac1d5 and close its stated proof gap.
- The intended control is descriptor-relative publication, but the two-parent acquisition and later path-based verification leave a directory-swap window.
  - Follow-up prompt: Review deferred unit candidate-58d0dcf031cefb06 and close its stated proof gap.
- The staging directory is mode 0700, but that protects against other users, not a same-UID local actor or a compromised cooperating process. Additional reducer context: Local migration/backup path; final publication is descriptor-relative and hardened, but earlier staging-directory creation and SQLite staging reopen the destination parent by path. Additional discovery context: This is most relevant to automation or a compromised local operator account with control over the backup path. Additional discovery context: Impact depends on attacker control of the backup-dir path or concurrent filesystem manipulation.
  - Follow-up prompt: Review deferred unit candidate-5956e60df2a80df4 and close its stated proof gap.
- Deferred future-activation candidate; current SafeFetch transport and Official publication are disabled.
  - Follow-up prompt: Review deferred unit candidate-450d58a082e64160 and close its stated proof gap.
- Deferred future-activation candidate; current transport remains disabled. Additional reducer context: The default DisabledNetworkTransport prevents real requests, so this candidate requires an enabled or injected transport implementation and a DNS/connection race or mismatch. Additional reducer context: The default network transport is disabled and the implementation comments defer peer proof to a future runner. This is a contract-level hazard if network ingestion is enabled. Additional reducer context: The default DisabledNetworkTransport blocks ordinary live fetching. This candidate applies when an explicit custom transport and network capability are enabled. Additional discovery context: Conditional/deferred: the ordinary runtime composition uses DisabledNetworkTransport, and source contracts separately describe peer proof, but this interface does not enforce or carry that proof. Additional reducer detail: Candidate is repository-context risk in the dormant/future network acquisition boundary; validation should determine whether any enabled transport can connect to a peer different from the checked address. Additional discovery context: Conditional candidate: the default transpo
  - Follow-up prompt: Review deferred unit candidate-e9636866cb04f53 and close its stated proof gap.
- Local/operator-controlled input; impact is conditional on an untrusted registry path.
  - Follow-up prompt: Review deferred unit candidate-4104bbc8ad15344e and close its stated proof gap.
- Impact depends on whether a less-trusted local actor or compromised automation can invoke seed-registry with chosen paths. Additional discovery context: Live governance write path if another actor can add files to the selected registry directory; intentional overlay behavior makes directory ownership decisive. Additional discovery context: Requires an operator or lower-trust caller to control the selected path or its directory; validation should determine the exact CLI authorization and publication reachability.
  - Follow-up prompt: Review deferred unit candidate-6245f55460ee8a26 and close its stated proof gap.
- This is a deferred semantic-integrity candidate, not a claim that the current fail-closed typed-admission gate is bypassed. It matters because the adapter is registered and an active github_yaml registry route exists.
  - Follow-up prompt: Review deferred unit candidate-a6221b9b70d0e813 and close its stated proof gap.
- This is an integrity/provenance candidate for source-controlled CSV content; the parent should verify which certified source policies and production paths can reach csv_cell_v1.
  - Follow-up prompt: Review deferred unit candidate-418c5b7e099837d9 and close its stated proof gap.
- The connection is read-only and normal legacy table names are fixed, so exploitability depends on an attacker-controlled or already-modified SQLite schema reaching this verification path. Additional reducer context: This operates on an operator-supplied or disposable SQLite copy. Validate whether crafted schema names are reachable through supported inputs and whether the behavior is denial-only or can affect protected data. Additional context: A crafted local SQLite input would be required. Upstream schema-status checks may reject unknown or oddly named tables before this path, so validation should establish whether a reachable accepted database can supply a name containing a quote; otherwise suppress as unreachable. Additional discovery context: Source-level SQL-injection candidate in local migration verification; no hostile SQLite file was executed.
  - Follow-up prompt: Review deferred unit candidate-660c89a4684b7f8d and close its stated proof gap.
- The shared source byte cap does not bound the number of decoded objects or generated claims.
  - Follow-up prompt: Review deferred unit candidate-ada0a2c660d76c2f and close its stated proof gap.
- The bundled Demo dataset does not currently contain this mixed metadata; reachability requires an alternate caller/provider input or future data wiring.
  - Follow-up prompt: Review deferred unit candidate-cadbfa56b4056080 and close its stated proof gap.
- The source registry currently marks imo_answerbench_github inactive and central admission may block unsupported evidence, so this is a dormant/future-activation integrity candidate.
  - Follow-up prompt: Review deferred unit candidate-1edf03c8f1683eb1 and close its stated proof gap.
- This requires manual invocation from a different working directory when the hard-coded workspace path is absent. Additional discovery context: Operator/developer-only workflow hazard with no direct attacker-controlled argument; included for review because it can mutate an unintended repository or working tree.
  - Follow-up prompt: Review deferred unit candidate-29f09c9d7bc728af and close its stated proof gap.
- Live provider settings were not verified; candidate is conditional on the recorded branch-protection state remaining current. Additional discovery context: GitHub provider state was not checked live in this read-only worker pass. Additional discovery context: Live GitHub settings require separate verification. Official mode is currently disabled, limiting immediate publication impact, but this is a governance control candidate for future release activation. Additional discovery context: Historical live-state evidence only; network/provider verification was not permitted. Validate current GitHub branch protection and CODEOWNERS enforcement before treating this as an active finding. Additional discovery context: Governance candidate requiring live GitHub verification; local files alone cannot prove branch-protection state.
  - Follow-up prompt: Review deferred unit candidate-8b9305eff775ebd9 and close its stated proof gap.
- This is a local CLI/file-input denial-of-service candidate; no remote route was established. Additional discovery context: Local reporting CLI path; SafeLoader prevents object construction but does not itself prevent alias recursion. Existing malformed-YAML tests do not cover aliases. Additional discovery context: Local operator-supplied path; no public web or authentication boundary was observed. Validate whether untrusted automation can invoke this command.
  - Follow-up prompt: Review deferred unit candidate-c54999f77c27969c and close its stated proof gap.
- Reachability depends on an attacker-controlled or substituted recovery artifact entering the recovery domain. Additional discovery context: Deferred candidate: exploitability depends on who can write or cause publication of a PostgreSQL checkpoint archive and on the restore database role's privileges.
  - Follow-up prompt: Review deferred unit candidate-9e6bf43ab711f7e6 and close its stated proof gap.
- Conditional supply-chain/build-host candidate; validate CI PATH provenance and whether the workflow establishes a trusted uv installation before this script. Additional discovery context: Developer/CI tooling rather than application runtime; exploitability depends on PATH directory trust. Additional discovery context: The script checks the reported uv version, but does not constrain the binary path, hash, or environment; current workflow context and runner integrity affect reachability. Additional discovery context: Requires CI or another privileged automation context where PATH or an earlier PATH directory is attacker-controlled. No repository-controlled PATH mutation was observed. Additional reducer context: Requires attacker influence over the execution environment and execution of this developer/CI verification script. The risk is supply-chain/tooling integrity rather than a public application route.
  - Follow-up prompt: Review deferred unit candidate-0e15383af7d42b1d and close its stated proof gap.
- Conditional authorization/policy-integrity candidate; the header policy is operator/configuration controlled and no active request-header sink was established.
  - Follow-up prompt: Review deferred unit candidate-e4657be3dc9d4493 and close its stated proof gap.
- Conditional/deferred external-storage candidate; activation requires the future external storage composition and no tests or live provider were exercised. Additional discovery context: Future injected/provider path; provider activation is not currently live. Additional discovery context: The normal ingestion path bounds fetched artifacts, but R2SnapshotStorage is an injected external-storage implementation and can be asked to read a provider-controlled object or malformed response.
  - Follow-up prompt: Review deferred unit candidate-18933a3ff5361a54 and close its stated proof gap.
- Conditional local recovery-integrity candidate; no dynamic execution was performed and the repository's higher-level migration/recovery paths add additional containment. Additional context: A same-host concurrent filesystem attacker and a caller-selected new restore path are required. The write is descriptor-anchored only after path resolution; validation should determine whether the recovery threat model treats the restore parent as attacker-influenced. Additional merged context: This is an operator-local fresh-target recovery boundary. The target leaf is protected against a pre-existing symlink, but that does not protect symlinked ancestors or parent swaps. Additional reducer context: Conditional operator/local filesystem attack; validate whether restore roots are attacker-influenced and whether all parent components are required to be no-follow. Additional discovery context: Live local restore path; requires a local actor controlling the target parent. Additional discovery context: Live local recovery path; initial symlink tests do not cover a post-check rename/replace race. Additional discovery context: CLI-level containment checks reduce exposure, but direct driver callers sti
  - Follow-up prompt: Review deferred unit candidate-361fbd1d43f31820 and close its stated proof gap.
- Conditional API-boundary issue; reachability depends on an enabled caller constructing plans directly rather than using build_fetch_plan. Additional discovery context: The intended contract describes FetchPlan as admission-bound, but SafeFetchClient.fetch accepts any exact FetchPlan instance and does not require construction through build_fetch_plan or carry a SourceAdmission to compare source identity, revision decision, URL allowlists, byte limits, redirect limits, or MIME policy. Its per-request public-DNS and HTTPS checks still block private addresses and unsafe URL syntax, but a direct caller can authorize an arbitrary public host outside the certified source/final URL allowlist. The current runner uses build_fetch_plan and the ordinary runtime refuses all network transport, so this is a future/custom-runtime trust-boundary candidate rather than a currently reachable production path.
  - Follow-up prompt: Review deferred unit candidate-9075015e8ec7a63e and close its stated proof gap.
- This is a build/release integrity candidate; impact depends on who can influence the built dist tree or the release packaging step. Additional reducer context: Conditional CI/build-integrity candidate; validate the Pages/archive uploader behavior and whether the fresh build output is guaranteed symlink-free. Additional discovery context: A deployment uploader that dereferences symlinks could publish external bytes. This requires a build-artifact producer able to place symlinks under dist. Additional discovery context: This affects CI/deployment evidence when build artifacts or copied public files can contain symlinks; validate whether Pages packaging dereferences or rejects them. Additional discovery context: A symlink inside a checked directory can be accepted while its filesystem target is outside the intended dist or public root. Additional discovery context: Source-level build-artifact containment candidate; no symlinked build output was created or tested. Additional discovery context: The candidate is most relevant when a dependency, build hook, or untrusted build input can create symlinks; validate with a symlinked asset/manifest fixture and realpath containment. Additional d
  - Follow-up prompt: Review deferred unit candidate-fe3ee6ce537eb8a0 and close its stated proof gap.
- Helper-level candidate; normal CLI callers apply root and parent admission, so reachability outside that workflow is unestablished. Additional discovery context: Impact depends on an attacker being able to control or race path ancestors in the recovery command's execution context. Additional reducer context (dedup-0028): This is a local operator-controlled recovery destination and is therefore deferred/medium at most unless an untrusted runner controls the filesystem or a protected-root boundary is relied on; validation should exercise ancestor replacement between admission and first storage operation.
  - Follow-up prompt: Review deferred unit candidate-494942dce96ebfd7 and close its stated proof gap.
- Direct database-writer boundary; normal application ingestion resolves and validates source admission, but database permissions and writers were not verified.
  - Follow-up prompt: Review deferred unit candidate-c4513b180375570b and close its stated proof gap.
- Runtime roles are NOLOGIN group roles and downstream callers may validate before insert; validate actual role membership, trigger coverage, and whether all durable consumers revalidate.
  - Follow-up prompt: Review deferred unit candidate-06fa3052aeecb988 and close its stated proof gap.
- Provider cache behavior and a governed withdrawal route were not verified; validate whether release tooling pins immutable paths and purges/revokes stale content.
  - Follow-up prompt: Review deferred unit candidate-8b69ee49f621cfcb and close its stated proof gap.
- Upstream database/object-store limits may impose practical bounds; validate actual artifact size limits and whether pg_restore itself bounds TOC output.
  - Follow-up prompt: Review deferred unit candidate-9f22ae97c13e2b21 and close its stated proof gap.
- The retention is documented as deliberate and requires a separately audited GC policy; validate quota/GC availability and whether an attacker can induce repeated post-store failures.
  - Follow-up prompt: Review deferred unit candidate-2c339d8d15f51ec2 and close its stated proof gap.
- Requires a direct operational-table writer and depends on SQLite JSON1 duplicate-key behavior; compare with PostgreSQL JSONB and downstream revalidation.
  - Follow-up prompt: Review deferred unit candidate-22dc2e28387702c6 and close its stated proof gap.
- Validate whether terminal run history is relied on for governance, monitoring, or incident evidence and whether application-layer checks are sufficient against direct role use.
  - Follow-up prompt: Review deferred unit candidate-4dd303d5da626b81 and close its stated proof gap.
- Deferred/conditional because the assigned contract schema does not prove the runtime validator lacks an independent cap; validate the consuming implementation and enforce one canonical upper bound.
  - Follow-up prompt: Review deferred unit candidate-4af4a84f9db7f412 and close its stated proof gap.
- Conditional candidate for concurrent PostgreSQL transactions and a certified source revision. No concurrency validation was performed; the parent owns validation and attack-path analysis.
  - Follow-up prompt: Review deferred unit candidate-b00a4874ebd628b6 and close its stated proof gap.
- Library/long-lived-process path rather than ordinary one-command CLI use; test fixtures reset globals and current CLI generally uses one target per process. Additional discovery context: Reachability depends on multiple database URLs or concurrent library callers in one process.
  - Follow-up prompt: Review deferred unit candidate-d3398e745be7779f and close its stated proof gap.
- Build-boundary candidate; current default Vite output may not create nested chunks.
  - Follow-up prompt: Review deferred unit candidate-28159948097d842b and close its stated proof gap.
- A malformed or unexpected source snapshot can cause adapter availability failures; impact is primarily integrity/availability rather than code execution.
  - Follow-up prompt: Review deferred unit candidate-2e16294ab9622d18 and close its stated proof gap.
- The verifier is CI/repository tooling and the inputs are repository-controlled artifacts; a maliciously enlarged tracked file could cause disproportionate CI memory or CPU use.
  - Follow-up prompt: Review deferred unit candidate-672126c709c97729 and close its stated proof gap.
- This is dated repository evidence only; current provider state was not rechecked and the parent must validate it separately.
  - Follow-up prompt: Review deferred unit candidate-f1fd5c23489fbd03 and close its stated proof gap.
- The same documents state deployment and Official publication are disabled or unauthorized; this is a pre-activation governance candidate.
  - Follow-up prompt: Review deferred unit candidate-c0f6ee4aed3c5098 and close its stated proof gap.
- Impact depends on an attacker controlling the operator input tree or racing the local filesystem.
  - Follow-up prompt: Review deferred unit candidate-49c379ffc55c2a03 and close its stated proof gap.
- The value is normally operator/configuration controlled, so reachability depends on an attacker influencing recovery configuration or a privileged local operator workflow; parent validation should confirm pg_restore's exact --dbname parsing semantics.
  - Follow-up prompt: Review deferred unit candidate-313a2981a2aeea50 and close its stated proof gap.
- Assigned files do not establish whether an upstream platform supplies HSTS or redirects HTTP.
  - Follow-up prompt: Review deferred unit candidate-2f2ea55cc67a2a8a and close its stated proof gap.
- Reachability depends on a caller supplying mismatched manifest and fixture-root objects.
  - Follow-up prompt: Review deferred unit candidate-9c242c54ca7ccb6c and close its stated proof gap.
- Reachability depends on worker or operator-controlled operational payloads being accepted through the repository methods.
  - Follow-up prompt: Review deferred unit candidate-e8b4d21ac33c7219 and close its stated proof gap.
- This is a local operator tool and requires attacker influence over the output path or its parent directories.
  - Follow-up prompt: Review deferred unit candidate-2502b0f93731c378 and close its stated proof gap.
- Source-level PostgreSQL integrity-control candidate; no database session or exploit path was executed.
  - Follow-up prompt: Review deferred unit candidate-3dcd4352a76d7a5b and close its stated proof gap.
- Source-level PostgreSQL operational-integrity candidate; no database session or exploit path was executed.
  - Follow-up prompt: Review deferred unit candidate-028defa7518c4664 and close its stated proof gap.
- Current Python semantic validators reject unsafe URL forms, so this is a contract/interoperability candidate and not a proven current runtime bypass. Additional discovery context: Future-gated/dormant Official path; validate actual artifact producer, frontend loader, and any dereference or link-rendering behavior before assigning impact.
  - Follow-up prompt: Review deferred unit candidate-edb0b954e2180744 and close its stated proof gap.
- This is primarily a future release-governance and supply-chain candidate because no deployment job is present in the reviewed workflow.
  - Follow-up prompt: Review deferred unit candidate-36600fd018e8a1ea and close its stated proof gap.
- This is distinct from header parsing: it covers metadata and 404/robots behavior and needs response/parser validation before impact is assigned.
  - Follow-up prompt: Review deferred unit candidate-363326f8f42068f7 and close its stated proof gap.
- Validation must confirm fork/branch event token scope and whether any deployment, package, or repository secrets are present; this is distinct from the Python job because the Node dependency/build execution path differs.
  - Follow-up prompt: Review deferred unit candidate-06060e5e991dc29f and close its stated proof gap.
- Validation must confirm whether fork PRs can read any repository-sensitive state or ambient credentials; no production secrets or write permission are evident in the workflow.
  - Follow-up prompt: Review deferred unit candidate-da515511f211da0e and close its stated proof gap.
- Impact is conditional on a consumer outside the assigned schema/runbook files dereferencing the locator; the runbook states receipts do not themselves change runtime locators. Additional discovery context: Impact is conditional on an excluded runtime consumer; no dereference was observed in the assigned checkpoint schema/runbook evidence.
  - Follow-up prompt: Review deferred unit candidate-175f012ebc85fc4e and close its stated proof gap.
- Whether CI chains these scripts is a separate validation question; this candidate records the local build control gap.
  - Follow-up prompt: Review deferred unit candidate-6221c008c4cc2eb5 and close its stated proof gap.
- No external invocation path was observed; validate whether production composition can bypass the governed artifact loader.
  - Follow-up prompt: Review deferred unit candidate-8296eac8e1638850 and close its stated proof gap.
- This is conditional/dormant because the current frontend has no published Official artifact or external artifact ingestion path. An otherwise digest-authorized but incorrect artifact could present a misleading evidence trail.
  - Follow-up prompt: Review deferred unit candidate-ace831974206b96d and close its stated proof gap.
- Runtime reachability or consumer proof remains unresolved.
  - Follow-up prompt: Review deferred unit candidate-08d2191c339c52a2 and close its stated proof gap.
- Runtime reachability or consumer proof remains unresolved.
  - Follow-up prompt: Review deferred unit candidate-a3321e224c0fcd08 and close its stated proof gap.

# Canonical Validation Threat Model

## Scope and status

This is the parent-owned canonical threat model for the repository-wide Deep
Security Scan of `/Users/stevmq/Documents/ai-benchmark-aggregator`, scope `.`.
It was synthesized after discovery from the 60 ordered worker threat-model
artifacts in the terminal coordinator manifest. It is downstream validation
context, not a retroactive discovery filter and not an authorization to enable
any dormant integration.

The scan covers the React/Vite frontend and browser trust boundary, the Python
ledger and CLI, ingestion and safe-fetch adapters, SQLite/PostgreSQL and
migrations, local/object storage and recovery, schemas and contracts, tests and
fixtures, package and action supply chain, CI/build verification, and the local
Cloudflare Pages/static publication boundary. Cloudflare-hosted infrastructure,
GitHub state, live databases, deployments, paid operations, Official
publication, and external accounts are not mutated or treated as verified by
this scan.

## Assets and security objectives

- Preserve exact source bytes, raw model/benchmark/score lexemes, content
  digests, typed evidence locations, source revisions, and immutable snapshot
  bindings.
- Preserve append-only claim, identity, review, capture, publication,
  withdrawal, incident, scheduling, and recovery histories with correct
  ordering and actor attribution.
- Protect ledger databases, local and object-backed snapshots, recovery
  manifests, operator paths, DSNs, credentials, CI credentials, and future
  signing or notification material.
- Keep the frontend distinction between Demo, awaiting/unavailable, and
  governed Official data fail-closed. Presentation rankings and aggregates
  must never become Official claims.
- Prevent untrusted source data, response metadata, redirects, DNS answers,
  parser output, fixtures, dependencies, workflows, or build artifacts from
  becoming executable code, authority, unsafe network requests, or a trusted
  published artifact.
- Bound attacker-influenced bytes, rows, cells, redirects, retries, parser
  expansion, database work, report materialization, and recovery work so
  integrity and availability controls cannot be exhausted.

## Actors and capabilities

- Anonymous browser users control ordinary browser state, URL fragments,
  navigation, clicks, and locally observed DOM. They are not trusted to supply
  provenance, publication authorization, or ledger mutations.
- Remote benchmark origins control response bytes, status and headers,
  redirects, DNS answers, encodings, HTML/JSON/CSV/Parquet/YAML content,
  source revisions, and fallback or login bodies. They are hostile evidence
  inputs.
- Repository contributors, pull requests, dependencies, package/action
  registries, CI jobs, build tools, and generated/public files may be
  malicious or compromised before review and release.
- Local operators control CLI arguments, environment configuration, registry
  revisions, fixture and recovery paths, database URLs, storage targets, and
  release inputs. They may be authorized but mistaken, stale, or over-
  privileged; same-host path races and symlinks remain relevant.
- Database, filesystem, object-storage, transport, hosting, queue, and
  provider failures can cause replay, corruption, stale publication, silent
  fallback, or availability exhaustion.
- Future schedulers, operational workers, notifications, storage providers,
  browser workers, and Cloudflare integrations are design surfaces only until
  separately authorized and proven. Their draft contracts cannot be treated as
  current runtime reachability.

## Trust boundaries

1. Browser/user to static Pages assets: browser-controlled state and any future
   public artifact input are untrusted; the bundle must contain no secrets or
   executable source strings and must not label Demo or presentation data as
   Official.
2. Source/network to ledger ingestion: URLs, redirects, peers, response
   metadata, bytes, encodings, and parsed values cross safe-fetch, adapter,
   snapshot, evidence, and admission controls. Every source revision and
   snapshot must remain bound to the exact captured content.
3. Operator/CLI to filesystem, database, registry, export, backup, and
   recovery: paths, DSNs, identifiers, fixtures, and decisions are
   operator-controlled inputs but must not bypass containment, authorization,
   append-only lineage, or read-only/rehearsal boundaries.
4. Ledger database to local/object storage and recovery: rows, object bytes,
   locators, metadata, hashes, restore targets, and provider responses are
   separate persistence inputs. Read-back, size, lineage, immutability, and
   target-isolation checks must be explicit.
5. Source/build/repository to CI and Pages publication: contributors,
   workflow/action revisions, package installs, generated assets, headers,
   metadata, and release selection cross a control-plane boundary. Local build
   success is not proof of authorized deployment or Official publication.
6. Governance authorities: source certification, claim review, identity
   correction, capture status, publication, release authorization, withdrawal,
   and recovery evidence are distinct append-only decisions. A recovery
   receipt, local export, fixture, or presentation aggregate is not release
   authorization.

## Invariants and validation framing

- Snapshot before extraction; preserve raw values without coercion; reject
  uncertified, unsafe, mock/fallback/derived, nonnumeric, nonfinite, or
  unapproved inputs before claims are admitted.
- Never overwrite a claim or mutable source interpretation. New source
  revisions and review/publication decisions append history; repeated ingestion
  of one snapshot is idempotent.
- A caller-supplied status, digest, availability flag, locator, role, actor, or
  publication discriminant is not authority without independent semantic,
  lineage, and authorization checks at the consuming boundary.
- Remote fetches must remain disabled or fail closed when transport, redirect,
  peer, size, timeout, content, or source-certification proof is absent.
- SQL identifiers, filesystem locators, recovery targets, response metadata,
  and public URLs require boundary-specific validation; generic schema shape is
  not equivalent to safe runtime semantics.
- CI and Pages checks must validate served semantics and authorized artifact
  provenance, not only textual markers, file shape, bundle size, or a passing
  test process.
- Draft continuous-discovery, notification, scheduler, provider, and recovery
  designs are explicitly unapproved. Their controls and gaps are reportable
  only as current code or governance conditions with a concrete activation or
  consumer path, otherwise they remain deferred follow-up.

## Contradictions and conservative decisions

Worker models consistently identified the current frontend as fail-closed for
Official data and the forward operational system as inert or gated. Some worker
models treated permissive schemas, local CLI authorization, CI execution, or
future URI consumers as findings; others correctly noted that semantic runtime
validators, absent public endpoints, deployment configuration, or excluded
consumers were not proven. Validation must preserve those distinctions:
source evidence can establish a broken control, but reportability and severity
require an actual consumer or a clearly reachable activation path. Conditional
schema, draft-design, and provider-dependent issues remain deferred unless the
candidate evidence proves current reachability. No live exploit, authenticated
deployment, cloud account, database, or external service state is assumed.

## Security objectives for centralized validation

Centralized validation must classify every canonical candidate exactly once as
reportable, suppressed, not applicable, or deferred; preserve its candidate
identity and source provenance; and state direct evidence, counterevidence,
method, and remaining uncertainty. Attack-path analysis then evaluates only the
validated reportable/deferred set, using realistic attacker prerequisites and
the smallest dataflow from boundary to impact. Coverage remains partial when
any concrete proof gap or follow-up surface remains.

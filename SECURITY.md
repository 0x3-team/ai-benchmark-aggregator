# Security Policy

## Supported Versions

We only support the latest `main` branch. Security fixes are applied to `main` and users should update to the latest commit.

| Version | Supported |
|---------|-----------|
| main (latest) | ✅ |

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Instead, email **security@0x3.team** (or use GitHub's private vulnerability reporting via the Security tab).

We will:
1. Acknowledge within 48 hours
2. Assess impact and severity
3. Develop a fix on a private branch
4. Release the fix and notify you
5. Publicly disclose after a reasonable embargo period (typically 7-14 days)

## Scope

This policy covers:
- The ledger CLI (`ledger/`) — Python code, dependencies, data ingestion
- The frontend SPA (`src/`) — React, TypeScript, build tooling
- CI/CD pipelines (`.github/workflows/`)
- Exported data (`src/data/official/export.from-ledger.json`)

Out of scope:
- Third-party benchmark sources (we only capture their published claims)
- Infrastructure (Gitea, Cloudflare tunnel, hosting) — report to respective maintainers

## Disclosure

We follow coordinated vulnerability disclosure. Public disclosure only after a fix is available and users have had time to update.
# Task Taxonomy

## Core categories

- `DISCOVERY`: Inspect existing systems, repositories, data, or constraints.
- `DECISION`: Produce an architectural, product, security, or operational decision record.
- `CONTRACT`: Define an API, schema, event, interface, or UX contract.
- `IMPLEMENTATION`: Produce product behavior or infrastructure.
- `MIGRATION`: Change data, schema, configuration, or infrastructure state safely.
- `VERIFICATION`: Add or execute tests and other objective checks.
- `SECURITY`: Threat mitigation, authorization, secret handling, and security validation.
- `OBSERVABILITY`: Logging, metrics, traces, analytics, dashboards, and alerts.
- `DOCUMENTATION`: Product, developer, operations, support, and release documentation.
- `RELEASE`: Packaging, deployment, rollout, rollback, and post-release checks.
- `CLEANUP`: Remove obsolete paths after safe migration or rollout.
- `GOVERNANCE`: Compliance evidence, approvals, auditability, and policy controls.

## Feature expansion template

Evaluate each feature against the following. Create only applicable tasks.

1. Requirement clarification or decision
2. Domain model and invariants
3. Public contract
4. Data model and ownership
5. Schema change
6. Backfill or migration
7. Backend/domain behavior
8. API or event adapter
9. Frontend view and state
10. Loading, empty, success, and error states
11. Input validation
12. Authorization and abuse cases
13. Accessibility
14. Internationalization
15. Logging, metrics, traces, and analytics
16. Unit tests
17. Contract tests
18. Integration tests
19. End-to-end tests
20. Performance and resilience checks
21. Security checks
22. Documentation
23. Rollout and feature controls
24. Rollback
25. Post-release verification
26. Cleanup

## Suggested agent-role values

- `product-analyst`
- `software-architect`
- `backend-engineer`
- `frontend-engineer`
- `mobile-engineer`
- `data-engineer`
- `database-engineer`
- `platform-engineer`
- `devops-engineer`
- `security-engineer`
- `qa-engineer`
- `accessibility-specialist`
- `performance-engineer`
- `technical-writer`
- `release-engineer`
- `code-reviewer`

These are routing hints, not assignments.

## Derived-concern source references

Use explicit source IDs for justified cross-cutting work:

- `DERIVED-SECURITY`
- `DERIVED-PRIVACY`
- `DERIVED-RELIABILITY`
- `DERIVED-PERFORMANCE`
- `DERIVED-ACCESSIBILITY`
- `DERIVED-OBSERVABILITY`
- `DERIVED-MAINTAINABILITY`
- `DERIVED-RELEASE-SAFETY`
- `DERIVED-TESTABILITY`
- `DERIVED-COMPLIANCE`

A derived concern must still state why it applies.

# Changelog

## 1.1.0 — audit revision

### Added
- Full Grok/Hermes frontmatter (version, author, license, metadata)
- Schemas: corpus-diff, architecture-component; expanded task/requirement/audit/edge
- Scripts: stable_ids, detect_cycles, calculate_execution_waves, audit_coverage, audit_granularity, audit_duplicates, diff_corpora, check_readiness
- References: dependency-rules, granularity-rules, readiness-rules, id-stability, orchestrator-handoff
- Example mini-corpus with valid DAG + requirements + manifest
- example-requirement.json, example-manifest.json
- Tests for schema validation, cycles, stable IDs, coverage
- Goal-mode guidance and orchestrator handoff contract
- Templates: requirements-summary, task-corpus-summary, ready-for-orchestrator

### Changed
- validate_task_corpus: stronger required fields, ID format, manifest checks, optional report write
- build_indexes retained; readiness pipeline wires indexes + waves
- example-task.json aligned with corpus leaf

### Compatibility
- Follows Grok skill discovery: `.grok/skills/` and `~/.grok/skills/`, slash `/project-task-decomposer`
- Hermes-compatible SKILL.md frontmatter
- Task schema_version 1.1.0 additive fields; core required fields preserved

### Removed
- None of the original design files were dropped; content upgraded in place

# Project Task Decomposer

**Author of original design:** you (attached baseline package).  
**This revision:** audit, gap fill, validation, and production hardening.

Converts a PRD / handoff / spec / plan into a versioned, sharded task corpus for a separate **Software Orchestrator**. Does **not** implement the product or permanently assign models.

## Install

```bash
# Grok
cp -R project-task-decomposer ~/.grok/skills/

# Hermes
cp -R project-task-decomposer ~/.hermes/skills/software-development/
# or HERMES_HOME/skills/software-development/

# Agents
cp -R project-task-decomposer ~/.agents/skills/
```

## Invoke

```text
/project-task-decomposer

Input documents:
- @docs/product-handoff.md
Mode: PRD_PLUS_REPO
Target leaf range: 1,500-3,000
Output project slug: example-product
Plan version: 1.0.0
```

See `templates/invocation.md`.

## Validate example corpus

```bash
cd project-task-decomposer
python scripts/check_readiness.py examples/example-corpus --write
python -m pytest tests -q
```

## Layout

Canonical machine-readable corpus under `.orchestrator/plans/<slug>/<version>/` (see SKILL.md).  
JSONL task shards are source of truth; Markdown is human view.

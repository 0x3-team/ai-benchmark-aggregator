---
name: codebase-design
description: Use when designing module boundaries, component interfaces, seams, and testable architecture around frontend or ledger changes.
---

# Codebase design

Prefer deep modules with small, explicit interfaces. Keep UI presentation separate from official claim storage, preserve provider boundaries, and place parsing, data access, and rendering logic in their existing owners. Document a seam before introducing a new abstraction.

# ADR-002: Toast strategy during Base UI migration

**Status:** Accepted  
**Date:** 2026-07-11  
**Decision ID:** DEC-002

## Context

Base UI does not ship a Toast primitive yet. Migrating all other Radix wrappers is still desirable.

## Decision

**Keep Radix Toast** (`@radix-ui/react-toast` + `toast.tsx` / `use-toast.ts`) temporarily.  
Migrate Dialog/Sheet, Popover, Tooltip, Tabs, Switch, Separator, Slot to Base UI.  
Document Radix Toast as the only approved leftover until Base UI ships Toast or a custom toast is justified.

## Consequences

- 100% Radix-free is not a gate for MVP.
- Toast notifications on model select continue to work without rewrite risk.

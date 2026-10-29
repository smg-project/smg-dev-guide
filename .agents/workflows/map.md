---
description: Orient in the SMG codebase — crate map, subsystem ownership, invariants
---
1. Run `bash scripts/map_live.sh <path inside the SMG checkout>` from the smg-dev-guide checkout and read its output: the crate list, policies and parser counts are read from the checkout, not from a document.
2. Read `skills/map/SKILL.md` for the invariants (layering, two-path config, request flow, worker lifecycle, parsing, three transports) and the "Where things live" table; read `skills/map/reference.md` when the question is about one subsystem's internals.
3. Answer the user's question with file paths they can open. If a path from the skill does not exist, follow `skills/learn/SKILL.md` to record it.

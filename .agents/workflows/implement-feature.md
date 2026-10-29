---
description: Implement a feature in SMG with the matching subsystem recipe
---
1. Read `skills/implement/SKILL.md`. Match the request to its detection table; if several rows match, load all of them (`config-plumbing` and `bindings-update` co-apply to most features).
2. Read the recipe file(s) under `skills/implement/recipes/`. Note the front matter: `verified` is the SMG commit the recipe was last checked against; `level: anchors` means names were verified but step semantics were not re-walked, so run the recipe's `cargo check` step early.
3. Create one task per recipe step and execute them in order, running each step's verification command before moving on.
4. If a step cites a path or symbol that does not exist, or a verification fails for an unpredicted reason, follow `skills/learn/SKILL.md` to record a lesson, then continue with the corrected knowledge.
5. When every step is done, run the `verify-pr` workflow before committing.

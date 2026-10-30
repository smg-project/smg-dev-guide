---
description: "SMG development router — hands your request to the right smg skill (map, implement, review-pr, contribute, learn, sync)"
argument-hint: "<what you want to do in SMG>"
---

The user's request: $ARGUMENTS

Pick the one skill that matches and invoke it with the request:

- Codebase structure, "where does X live", how a subsystem or flow works → `smg:map`
- Implement, add, build, fix, change any behaviour or config → `smg:implement`
- A PR number/URL, "review this", diff analysis → `smg:review-pr`
- Commit, push, PR readiness, "am I ready to submit", quality gate → `smg:contribute`
- Naming, wording, performance discipline, interface design, duplication, "how do we do X here" → `smg:craft`
- The guide itself was wrong (stale path, missing step, unpredicted CI failure) → `smg:learn`
- Resync this guide against SMG HEAD (maintainers) → `smg:sync`

Default to `smg:implement` when the request involves writing code. Ask only when two readings
would lead to different work.

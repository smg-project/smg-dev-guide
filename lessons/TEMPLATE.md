---
kind: wrong-anchor        # wrong-anchor | missing-step | wrong-semantics | new-subsystem | ci-surprise | tooling
skill: implement           # map | implement | review-pr | contribute | sync | learn
recipe: config-plumbing    # recipe file stem, or "-" when the lesson is about the skill itself
smg_commit: <sha of the SMG checkout where this happened>
guide_version: <plugin.json version, or the smg-ref.json verified_commit>
status: new
---

## What the guide said

Quote the sentence or step (file:line in this repository) that was wrong or missing.

## What is actually true

The current path / symbol / behaviour, with the evidence: the command you ran and its (trimmed)
output, or the commit that changed it (`git log -S'<symbol>' -1 -- <path>` in SMG helps).

## Proposed change

The replacement text, as concretely as you can. If a whole step needs rewriting, say which
existing step it replaces.

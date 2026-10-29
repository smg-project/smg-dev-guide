---
name: learn
description: Record a lesson for the SMG dev guide when one of its skills or recipes was wrong or incomplete — a cited path or symbol that no longer exists, a missing or wrong step, a verification command or CI lane that failed for a reason the recipe did not predict, or an SMG subsystem with no recipe. Files a structured issue (or a lessons/ entry) that /smg:sync promotes into the guide.
---

# Record a lesson for the guide

The guide improves only when the agents who use it report where it failed them. A lesson takes two minutes while the evidence is in front of you and saves the next agent the same detour.

**When:** a recipe or skill pointed you at a file, type, function, flag or test that does not exist; a step was missing or in the wrong order; a verification command or CI lane failed for a reason the recipe did not predict; a subsystem you worked in has no recipe or map row.

**Not a lesson:** a bug in SMG itself (file it on `smg-project/smg`), or a question the guide answered correctly.

## Process

```
1. CAPTURE   while you still have it:
             - the skill / recipe and the exact sentence or step (file and line in the guide:
               ${CLAUDE_PLUGIN_ROOT}/skills/...)
             - the command you ran and its trimmed output, or the compiler error
             - the SMG commit:   git rev-parse HEAD
             - what is true now: git grep -nw '<symbol>' or git log -S'<symbol>' -1 -- <path>
             - the guide version: "version" in ${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json,
               and "verified_commit" in ${CLAUDE_PLUGIN_ROOT}/smg-ref.json
2. CLASSIFY  kind = wrong-anchor | missing-step | wrong-semantics | new-subsystem | ci-surprise | tooling
3. WRITE     fill the template below (same shape as lessons/TEMPLATE.md in the guide repo)
4. DEDUP     gh issue list --repo smg-project/smg-dev-guide --label lesson --search "<symbol or path>"
             — comment on an existing issue instead of opening a twin
5. FILE      preferred:
               gh issue create --repo smg-project/smg-dev-guide --label lesson \
                 --title "lesson(<recipe or skill>): <one line>" --body-file <tmpfile>
             without gh (or no permission): if a smg-dev-guide checkout is at hand
             ($SMG_DEV_GUIDE_ROOT, or ${CLAUDE_PLUGIN_ROOT} when it is a git checkout), write
             lessons/YYYY-MM-DD-<slug>.md there and tell the user to commit it; otherwise print the
             filled template and ask the user to file it.
6. CONTINUE  finish your SMG task with the corrected knowledge. Do not edit the installed plugin's
             skills in place — a plugin update overwrites them. Edit skills only inside the
             smg-dev-guide repository, where /smg:sync and lint_guide.py apply.
```

## Template

```markdown
---
kind: wrong-anchor
skill: implement
recipe: discovery-feature
smg_commit: <sha>
guide_version: <plugin version or verified_commit>
status: new
---

## What the guide said
<quote the step, with the guide file:line>

## What is actually true
<path/symbol/behaviour now, with the evidence: command + output, or the SMG commit that changed it>

## Proposed change
<replacement text, as concrete as you can; which step it replaces>
```

## Red flags — stop

- Guessing a replacement path and moving on without recording it
- Filing an SMG bug as a guide lesson, or the reverse
- Editing `${CLAUDE_PLUGIN_ROOT}/skills/...` outside a dev-guide checkout

---
name: learn
description: Record a lesson for the SMG dev guide when a skill or recipe was wrong or incomplete (a cited path or symbol that no longer exists, a missing or wrong step, a verify command or CI lane that failed for an unpredicted reason, a subsystem with no recipe). Files a structured issue the next sync promotes.
---

# Record a lesson for the guide

The guide improves only when the agents who use it report where it failed them. Two minutes while the evidence is in front of you saves the next agent the same detour.

**When:** a recipe or skill pointed you at a file, type, function, flag or test that does not exist; a step was missing or in the wrong order; a verify command or CI lane failed for a reason the recipe did not predict; the subsystem you worked in has no recipe or map row.

**Not a lesson:** a bug in SMG itself (file it on `smg-project/smg`), or a question the guide answered correctly.

## Process

```
CAPTURE   the skill or recipe and the exact sentence (${CLAUDE_PLUGIN_ROOT}/skills/...:line); the command you ran and its
          trimmed output or the compiler error; the SMG commit (git rev-parse HEAD); what is true now
          (git grep -nw '<symbol>', git log -S'<symbol>' -1 -- <path>); the guide version
          ("version" in ${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json, "verified_commit" in ${CLAUDE_PLUGIN_ROOT}/smg-ref.json)
CLASSIFY  kind = wrong-anchor | missing-step | wrong-semantics | new-subsystem | ci-surprise | tooling | vocabulary
WRITE     cat "${CLAUDE_PLUGIN_ROOT}/lessons/TEMPLATE.md" and fill it
DEDUP     gh issue list --repo smg-project/smg-dev-guide --label lesson --search "<symbol or path>"; comment on a twin instead
FILE      gh issue create --repo smg-project/smg-dev-guide --label lesson --title "lesson(<recipe or skill>): <one line>" --body-file <tmp>
          without gh: write lessons/YYYY-MM-DD-<slug>.md in a smg-dev-guide checkout ($SMG_DEV_GUIDE_ROOT, or
          ${CLAUDE_PLUGIN_ROOT} when it is a git checkout) and tell the user; else print the filled template
CONTINUE  finish the SMG task with the corrected knowledge; never edit the installed plugin's skills in place
```

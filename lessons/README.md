# Lessons inbox

A *lesson* is evidence that this guide was wrong or incomplete: a recipe cited a path or symbol
that no longer exists, a step was missing, a verification command failed for a reason the recipe
did not predict, or an SMG subsystem has no recipe at all. Lessons are how agents using the guide
improve it for the next agent.

## How a lesson flows

1. An agent working in SMG hits the gap and runs `/smg:learn` (the skill in `skills/learn/`).
2. The skill files a GitHub issue on this repository labelled `lesson`
   (`gh issue create --repo smg-project/smg-dev-guide --label lesson ...`). When `gh` is not
   available it writes a file here instead, named `YYYY-MM-DD-<slug>.md`, following `TEMPLATE.md`.
3. `/smg:sync` reads open `lesson` issues and the files in this directory, fixes the skill or
   recipe, re-runs `scripts/check_anchors.py`, and closes the issue (or deletes the file) in the
   same PR, citing it in the PR body.

Files in this directory are therefore transient: an entry should not survive the next sync.
`TEMPLATE.md` is the only permanent file.

## What is not a lesson

A bug in SMG itself belongs in `smg-project/smg` issues. A question about how SMG works that the
guide answered correctly is not a lesson either. The test: *would changing a file in this
repository have saved the agent time?* If yes, it is a lesson.

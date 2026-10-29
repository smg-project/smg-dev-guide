---
name: sync
description: Resync the smg-dev-guide against SMG HEAD — measure drift with the anchor checker and the upstream digest, fix every stale path, symbol and step, promote recorded lessons into the recipes, bump the verified commit, and open the resync PR. Maintainers run it explicitly (/smg:sync); the scheduled drift workflow can run it too.
disable-model-invocation: true
---

# Resync the guide against SMG

This is the guide's self-improvement loop. Its output is a PR to `smg-project/smg-dev-guide` whose every claim about SMG is backed by a checker run at a named commit.

## Hard gate

```
NEVER BUMP smg-ref.json WHILE check_anchors.py REPORTS A BROKEN ANCHOR
NEVER HIDE A BROKEN ANCHOR IN anchors/ignore.txt UNLESS THE SKILL CITES IT AS A NEGATIVE
```

## Inputs

- A checkout of this repository (the guide) on a branch `docs/resync-v<version>`.
- An SMG checkout at the target commit, with history reaching back to the current pin: `git fetch --shallow-since=<smg-ref.json verified_date> origin main` if it is shallow.
- `gh` authenticated for `smg-project/smg-dev-guide` (lessons live in issues labelled `lesson`).

Set `SMG=<smg checkout>` and run everything from the guide checkout.

## Process

```
1. MEASURE
   python3 scripts/check_anchors.py --smg "$SMG" --format markdown      # what is broken, where
   bash scripts/upstream_digest.sh --smg "$SMG"                          # commits since the pin by type/scope,
                                                                         # crates/dirs/workflows added or removed,
                                                                         # renamed files, churn per recipe
   gh issue list --repo smg-project/smg-dev-guide --label lesson --state open --json number,title,body
   ls lessons/*.md 2>/dev/null                                           # fallback lessons

2. TRIAGE   For each broken anchor: find the replacement in SMG
              git -C "$SMG" log --oneline -S'<symbol>' -1 -- <old path>   # the commit that moved or removed it
              git -C "$SMG" grep -nw '<symbol>'                           # where it lives now
            For each recipe with high churn (digest table): re-walk its steps against the code
              and raise `level` to full when you have, or keep anchors when you only fixed names.
            For each new crate / top-level module / CI lane in the digest: decide whether it needs
              a detection-table row (`skills/implement/SKILL.md`), a "where it lives" row
              (`skills/map/SKILL.md`, `reference.md`), a review mapping row
              (`skills/review-pr/SKILL.md`), or a new recipe (`skills/implement/recipes/`).
            For each lesson: locate the sentence it corrects.

3. FIX      Edit the skills and recipes. Rules:
            - Keep skill names (map, implement, review-pr, contribute) — SMG's REVIEW.md and its
              Claude Code Review workflow invoke them by name.
            - A recipe keeps its front matter: set `verified` to the target commit, `level` to
              what you actually did, `watch` to the paths that own the recipe's steps.
            - Add intentional negatives ("there is no X") to anchors/ignore.txt with a comment.
            - A removed subsystem's recipe is deleted (and its detection row), not left to rot.
            - Changing a recipe's name or a skill's description? Update evals/ (routing cases)
              and README.md tables.

4. VERIFY   python3 scripts/check_anchors.py --smg "$SMG"               # must print broken 0
            python3 scripts/lint_guide.py                                # must print 0 error(s)
            claude plugin validate .                                     # when the claude CLI is available
            bash scripts/map_live.sh "$SMG" | head -40                    # the live map still renders
            bash scripts/gate.sh --dry-run  (run inside $SMG)             # the gate still matches CONTRIBUTING.md
            Re-read CONTRIBUTING.md, REVIEW.md, .pre-commit-config.yaml, pr-naming-check.yml,
            clippy.toml and Cargo.toml [workspace.lints] in SMG; update contribute/review-pr if they moved.

5. RECORD   python3 scripts/check_anchors.py --smg "$SMG" --format json > /tmp/anchors.json
            Update smg-ref.json: verified_commit (full sha), verified_version
            (model_gateway/Cargo.toml), verified_date, verified_by, anchors.{checked,broken,ignored},
            and append the previous pin to history[].
            Bump version in .claude-plugin/plugin.json, .claude-plugin/marketplace.json and
            .cursor-plugin/plugin.json together (lint_guide checks they agree).

6. SHIP     git commit -s  with subject  docs: resync skills with smg HEAD (v<version>)
            PR body: the digest summary, the before/after anchor counts, the lessons promoted
            (closing each issue with "fixed in #<pr>" / deleting the lessons/ file in the same PR),
            and anything you could not verify.
```

## Prioritising a large drift

When thousands of commits separate the pin from HEAD, do not try to re-walk every recipe. Order of work:

1. Broken anchors (an agent following them fails immediately).
2. Recipes whose `watch` churn is highest in the digest table.
3. New crates with many commits (the digest's top scopes) — these need at least a map row and a detection row.
4. Removed or renamed subsystems (digest "removed" lines).
5. Lessons.

Record what was left for next time in the PR body; `level: anchors` on a recipe is an honest statement, not a failure.

## Red flags — stop

- Bumping the pin with a non-zero broken count
- Adding a real anchor to `anchors/ignore.txt` to make the run green
- Rewriting a recipe from memory instead of from the code at the target commit
- Renaming a skill

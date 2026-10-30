---
name: sync
description: Resync the smg-dev-guide against SMG HEAD. Measures drift (anchors, exemplar coverage, upstream digest, open lessons), fixes every stale path, symbol and step, promotes lessons, bumps the verified commit and opens the resync PR. Maintainers run it explicitly (/smg:sync); the scheduled drift workflow can run it too.
disable-model-invocation: true
---

# Resync the guide against SMG

Output: a PR to `smg-project/smg-dev-guide` whose every claim about SMG is backed by a checker run at a named commit.

**Hard gate:** never bump `smg-ref.json` while `check_anchors.py` reports a broken anchor, and never hide a real anchor in `anchors/ignore.txt` (only placeholders and stated negatives belong there).

## Inputs

A guide checkout on a branch `docs/resync-v<version>`; an SMG checkout at the target commit with history back to the pin (`git fetch --shallow-since=<verified_date> origin main`); `gh` authenticated for the guide repo. Set `SMG=<smg checkout>` and work from the guide checkout.

## Process

```
MEASURE   python3 scripts/check_anchors.py --smg "$SMG" --format markdown      names that no longer exist
          python3 scripts/check_coverage.py --smg "$SMG" --format markdown     areas real commits touch that a recipe never mentions
          bash scripts/upstream_digest.sh --smg "$SMG"                          commits by scope, crates/dirs/workflows added or removed, churn per recipe
          gh issue list --repo smg-project/smg-dev-guide --label lesson --state open --json number,title,body ; ls lessons/*.md
TRIAGE    broken anchor → git -C "$SMG" log -S'<symbol>' -1 -- <path> and git grep -nw '<symbol>' for the replacement
          coverage gap  → python3 scripts/check_coverage.py --smg "$SMG" --show <recipe>; read the exemplars; add the step
          new crate / top-level module / CI lane → a row in data/subsystems.json (then python3 scripts/render.py),
            a detection-table row in skills/implement/SKILL.md, a recipe when the digest shows a repeatable shape
          lesson → find the sentence it corrects
FIX       edit recipes to the template (lint_guide.py enforces it): front matter verified = target sha, level = what you did,
          watch = owning paths, exemplars = the commits you read; keep skill names (SMG's REVIEW.md invokes them)
          stated negatives → anchors/ignore.txt with a comment; removed subsystems → delete the recipe and its rows
VERIFY    python3 scripts/check_anchors.py --smg "$SMG"      → broken 0
          python3 scripts/check_coverage.py --smg "$SMG"     → read the remaining gaps; justify in the PR
          python3 scripts/render.py && python3 scripts/lint_guide.py   → 0 errors
          claude plugin validate .   (when the CLI is available)
          re-read CONTRIBUTING.md, REVIEW.md, .pre-commit-config.yaml, pr-naming-check.yml, clippy.toml, Cargo.toml [workspace.lints] in SMG;
            update data/rules.json, data/vocabulary.json and skills/craft/ when they moved
RECORD    smg-ref.json: verified_commit (full sha), verified_version, verified_date, verified_by, anchors stats
            (check_anchors --format json), previous pin appended to history[]; bump the version in the three manifests together
SHIP      git commit -s, subject "docs: resync skills with smg HEAD (v<version>)"; PR body: digest summary, anchor and coverage
            counts before/after, lessons promoted (close each issue with the PR number), what was left for next time
```

## Prioritising a large drift

Broken anchors first (an agent following them fails immediately), then recipes with the most watch-path churn, then new crates with many commits (a map row and a detection row at least), then removed or renamed subsystems, then lessons. `level: anchors` on a recipe is an honest statement; say so in the PR rather than re-walking every step from memory.

## Problem
<!-- What issue does this PR address? Link to the issue or the lesson it promotes. -->

## Solution
<!-- How does this PR solve the problem? -->

## Changes
<!-- List the files changed and what each change does. -->

-

## Affected components
<!-- Tick what this PR touches. -->

- [ ] `smg:map` (`skills/map/`)
- [ ] `smg:implement` (`skills/implement/SKILL.md`)
- [ ] Recipes (`skills/implement/recipes/` — list which)
- [ ] `smg:review-pr` (`skills/review-pr/`)
- [ ] `smg:contribute` (`skills/contribute/`)
- [ ] `smg:sync` / `smg:learn`
- [ ] Scripts (`scripts/`) or hooks (`hooks/`, `scripts/hooks/`)
- [ ] Agents (`agents/`) or the router command (`commands/`)
- [ ] Platform adapters (`.agents/`, `.cursor-plugin/`, manifests)
- [ ] Provenance (`smg-ref.json`), evals, CI

## Verification
<!-- Paste the output lines. -->

- [ ] `python3 scripts/lint_guide.py` → 0 errors
- [ ] `python3 scripts/check_anchors.py --smg <smg checkout>` → broken 0 (say which SMG commit)
- [ ] `claude plugin validate .` passes (when the CLI is available)
- [ ] Skills still trigger on their intended prompts (`claude plugin eval .` when descriptions or the detection table changed)

## Checklist

- [ ] Conventional commit title (`type(scope): summary`)
- [ ] Every commit signed off (`git commit -s`), no Claude/anthropic attribution trailers
- [ ] Recipe front matter updated (`verified`, `level`, `watch`) for recipes touched
- [ ] Lessons promoted here are closed/deleted in this PR

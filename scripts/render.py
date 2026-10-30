#!/usr/bin/env python3
"""Render data/*.json into the skills, between markers, so a table is spelled once.

A skill file carries blocks like

    <!-- render:where-things-live -->
    ...generated...
    <!-- /render -->

and this script regenerates everything between the markers. `--check` only reports files that
would change (exit 1), which lint_guide.py runs on every PR. Blocks:
  where-things-live   skills/map/SKILL.md      area → where to go → recipe
  subsystems          skills/map/reference.md  area → paths → key types
  lanes               skills/map/reference.md  CI lane → what it runs
  no-recipe-areas     skills/map/reference.md  areas without a recipe
  review-mapping      skills/review-pr/SKILL.md paths → checklists → lanes
  rules               skills/contribute/SKILL.md the naming and attribution rules
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = re.compile(r"(<!-- render:([a-z-]+) -->\n)(.*?)(<!-- /render -->)", re.S)


def load():
    sub = json.loads((ROOT / "data" / "subsystems.json").read_text(encoding="utf-8"))
    rules = json.loads((ROOT / "data" / "rules.json").read_text(encoding="utf-8"))
    return sub, rules


def code(items):
    return ", ".join(f"`{p}`" for p in items)


def block_where_things_live(sub, rules):
    rows = ["| Area | Go to | Recipe |", "|---|---|---|"]
    for a in sub["areas"]:
        recipe = f"`recipes/{a['recipe']}.md`" if a.get("recipe") else "none yet (read the code; `smg:learn` afterwards)"
        rows.append(f"| {a['name']} | {code(a['paths'])}: {a['where']} | {recipe} |")
    return "\n".join(rows) + "\n"


def block_subsystems(sub, rules):
    rows = ["| Area | Paths | Key types |", "|---|---|---|"]
    for a in sub["areas"]:
        rows.append(f"| {a['name']} | {code(a['paths'])} | {code(a['types']) if a['types'] else ''} |")
    return "\n".join(rows) + "\n"


def block_lanes(sub, rules):
    rows = ["| Lane | What it runs |", "|---|---|"]
    for lane, what in sub["lanes"].items():
        rows.append(f"| `{lane}` | {what} |")
    return "\n".join(rows) + "\n"


def block_no_recipe_areas(sub, rules):
    rows = []
    for a in sub["areas"]:
        if not a.get("recipe"):
            rows.append(f"- **{a['name']}** ({code(a['paths'])}): {a['where']}")
    return "\n".join(rows) + "\n"


def block_review_mapping(sub, rules):
    rows = ["| Files changed | Read these checklists | Lanes that run |", "|---|---|---|"]
    for a in sub["areas"]:
        cl = ", ".join(f"`checklists/{c}.md`" for c in a["checklists"]) or "sections 7–9 only"
        rows.append(f"| {code(a['paths'])} | {cl} | {code(a['lanes'])} |")
    return "\n".join(rows) + "\n"


def block_rules(sub, rules):
    r = rules["smg"]
    return "\n".join([
        f"- **Branch**: {r['branch_rule']}; regex `{r['branch_regex']}`. Never commit on {', '.join(f'`{b}`' for b in r['no_commit_to'])} (pre-commit `no-commit-to-branch`); CI closes PRs from other branch names.",
        f"- **Commit subject**: `type(scope): summary` with type in {', '.join(f'`{t}`' for t in r['commit_types'])}, lowercase scope.",
        "- **DCO**: `git commit -s`; the `Signed-off-by` trailer must equal `git config user.name <user.email>` exactly (`scripts/dco-check.sh`). Never `--no-verify`.",
        f"- **No AI attribution**: a `Co-authored-by` or `Signed-off-by` line matching `{r['ai_trailer_regex']}` fails the `no-ai-co-author` hook and CI.",
        f"- **PR title**: regex `{r['pr_title_regex']}`.",
        f"- **PR body**: the template headers {', '.join(f'`{h}`' for h in r['pr_body_headers'])}, each filled; the review bot posts the gaps otherwise.",
    ]) + "\n"


BLOCKS = {
    "where-things-live": block_where_things_live,
    "subsystems": block_subsystems,
    "lanes": block_lanes,
    "no-recipe-areas": block_no_recipe_areas,
    "review-mapping": block_review_mapping,
    "rules": block_rules,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report files that would change; exit 1 if any")
    args = ap.parse_args()
    sub, rules = load()
    changed = []
    used = set()
    for md in sorted((ROOT / "skills").rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        def sub_block(m):
            name = m.group(2)
            if name not in BLOCKS:
                raise SystemExit(f"{md}: unknown render block {name}")
            used.add(name)
            return m.group(1) + BLOCKS[name](sub, rules) + m.group(4)
        new = MARK.sub(sub_block, text)
        if new != text:
            changed.append(str(md.relative_to(ROOT)))
            if not args.check:
                md.write_text(new, encoding="utf-8")
    unused = set(BLOCKS) - used
    if args.check:
        for c in changed:
            print(f"STALE  {c}")
        print(f"render --check: {len(changed)} stale file(s); blocks unused: {', '.join(sorted(unused)) or 'none'}")
        return 1 if changed else 0
    for c in changed:
        print(f"rendered {c}")
    print(f"render: {len(changed)} file(s) updated; blocks unused: {', '.join(sorted(unused)) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

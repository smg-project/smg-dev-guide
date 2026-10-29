#!/usr/bin/env python3
"""Self-consistency lint for smg-dev-guide. Needs no SMG checkout; runs on every PR.

Checks that the guide's own plumbing holds together:
  * every @recipes/x.md or @x.md reference in a skill resolves to a file
  * every recipe is reachable from skills/implement/SKILL.md and carries front matter
    (recipe, verified, level, watch) that matches its file name
  * every SKILL.md has front matter with a name matching its directory and a description
  * .agents/skills/smg-<name> symlinks resolve to skills/<name>, one per skill
  * plugin.json / marketplace.json parse, agree on the version, and the hooks path exists
  * hooks/hooks.json parses and every ${CLAUDE_PLUGIN_ROOT}/... script it names exists
  * agents/*.md have name + description front matter
  * smg-ref.json has the provenance fields and a 40-hex verified_commit
  * anchors/ignore.txt patterns compile
  * evals cases reference skills that exist
  * no Markdown still points at the pre-move skills/implement/<recipe>.md layout

Exit 1 on any error; warnings never fail the run.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def frontmatter(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict = {}
    key = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if re.match(r"^\s+-\s+", line) and key:
            data.setdefault(key, [])
            if isinstance(data[key], list):
                data[key].append(line.split("-", 1)[1].strip().strip("\"'"))
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                data[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
            elif val == "":
                data[key] = []
            else:
                data[key] = val.strip("\"'")
    return data


def main() -> int:
    skills_dir = ROOT / "skills"
    skill_names = sorted(p.name for p in skills_dir.iterdir() if (p / "SKILL.md").is_file())
    if not skill_names:
        err("no skills found under skills/")

    # SKILL.md front matter and @references
    for name in skill_names:
        skill = skills_dir / name / "SKILL.md"
        fm = frontmatter(skill)
        if fm.get("name") != name:
            err(f"{skill.relative_to(ROOT)}: front matter name {fm.get('name')!r} != directory {name!r}")
        if not fm.get("description"):
            err(f"{skill.relative_to(ROOT)}: missing description")
        elif len(str(fm["description"])) > 1024:
            warn(f"{skill.relative_to(ROOT)}: description longer than 1024 chars")
        for md in (skills_dir / name).rglob("*.md"):
            text = md.read_text(encoding="utf-8")
            for ref in re.findall(r"@((?:recipes/)?[\w.-]+\.md)", text):
                cands = [md.parent / ref, skills_dir / name / ref]
                if not any(c.is_file() for c in cands):
                    err(f"{md.relative_to(ROOT)}: reference @{ref} does not resolve")
            if re.search(r"skills/implement/(?!recipes/|SKILL\.md)[\w-]+\.md", text):
                err(f"{md.relative_to(ROOT)}: points at the old flat skills/implement/<recipe>.md layout")

    # recipes
    recipes_dir = skills_dir / "implement" / "recipes"
    impl_skill = (skills_dir / "implement" / "SKILL.md").read_text(encoding="utf-8")
    for recipe in sorted(recipes_dir.glob("*.md")):
        rel = recipe.relative_to(ROOT)
        fm = frontmatter(recipe)
        if not fm:
            err(f"{rel}: missing front matter (recipe, verified, level, watch)")
            continue
        if fm.get("recipe") != recipe.stem:
            err(f"{rel}: front matter recipe {fm.get('recipe')!r} != file stem {recipe.stem!r}")
        if not re.fullmatch(r"[0-9a-f]{7,40}", str(fm.get("verified", ""))):
            err(f"{rel}: verified must be an SMG commit sha")
        if fm.get("level") not in ("full", "anchors", "draft"):
            err(f"{rel}: level must be full, anchors or draft")
        if not fm.get("watch"):
            err(f"{rel}: watch list is empty (paths whose churn should trigger re-verification)")
        if f"recipes/{recipe.name}" not in impl_skill:
            err(f"{rel}: not referenced from skills/implement/SKILL.md (orphan recipe)")

    # .agents/skills symlinks
    agents_skills = ROOT / ".agents" / "skills"
    if agents_skills.is_dir():
        # Codex invokes plugin skills as $smg-<name>, so the links carry the smg- prefix.
        for name in skill_names:
            link = agents_skills / f"smg-{name}"
            if not link.is_symlink():
                err(f".agents/skills/smg-{name}: missing symlink to ../../skills/{name}")
            elif not (link / "SKILL.md").is_file():
                err(f".agents/skills/smg-{name}: symlink does not resolve to a skill directory")
        for link in agents_skills.iterdir():
            if not link.name.startswith("smg-") or link.name[4:] not in skill_names:
                err(f".agents/skills/{link.name}: no matching skill under skills/")
    else:
        warn(".agents/skills/ missing: Codex, Gemini CLI and Antigravity discovery relies on it")

    # manifests
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    mver = next((p.get("version") for p in market.get("plugins", []) if p.get("name") == plugin.get("name")), None)
    if mver != plugin.get("version"):
        err(f"plugin.json version {plugin.get('version')} != marketplace.json version {mver}")
    cursor = ROOT / ".cursor-plugin" / "plugin.json"
    if cursor.is_file() and json.loads(cursor.read_text()).get("version") != plugin.get("version"):
        err("cursor-plugin/plugin.json version differs from plugin.json")
    hooks_path = plugin.get("hooks")
    if isinstance(hooks_path, str):
        if not (ROOT / hooks_path).is_file():
            err(f"plugin.json hooks path {hooks_path} does not exist")
        else:
            hooks = json.loads((ROOT / hooks_path).read_text())
            if "hooks" not in hooks:
                err(f"{hooks_path}: a hooks file needs a top-level \"hooks\" key")
            for event, groups in hooks.get("hooks", {}).items():
                for g in groups:
                    for h in g.get("hooks", []):
                        for script in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s\"']+)", h.get("command", "")):
                            p = ROOT / script
                            if not p.is_file():
                                err(f"{hooks_path}: {event} names missing script {script}")
                            elif not (p.stat().st_mode & 0o111):
                                warn(f"{script} is not executable")
    for agent in (ROOT / "agents").glob("*.md"):
        fm = frontmatter(agent)
        if not fm.get("name") or not fm.get("description"):
            err(f"{agent.relative_to(ROOT)}: agents need name and description front matter")

    # provenance
    ref = json.loads((ROOT / "smg-ref.json").read_text())
    for key in ("smg_repo", "verified_commit", "verified_version", "verified_date"):
        if key not in ref:
            err(f"smg-ref.json: missing {key}")
    if not re.fullmatch(r"[0-9a-f]{40}", str(ref.get("verified_commit", ""))):
        err("smg-ref.json: verified_commit must be a full 40-hex sha")

    # ignore patterns
    for n, raw in enumerate((ROOT / "anchors" / "ignore.txt").read_text().splitlines(), 1):
        pat = raw.split("#", 1)[0].strip()
        if pat:
            try:
                re.compile(pat)
            except re.error as e:
                err(f"anchors/ignore.txt:{n}: bad regex {pat!r}: {e}")

    # evals
    evals = ROOT / "evals"
    if evals.is_dir():
        for case in evals.rglob("case.yaml"):
            text = case.read_text(encoding="utf-8")
            for skill in re.findall(r"smg:([a-z-]+)", text):
                if skill not in skill_names:
                    err(f"{case.relative_to(ROOT)}: references unknown skill smg:{skill}")

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"lint_guide: {len(errors)} error(s), {len(warnings)} warning(s); skills: {', '.join(skill_names)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Exemplar coverage: does each recipe mention every area that real SMG commits of its kind touch?

check_anchors.py proves the names a recipe cites exist. This script asks the harder question. For
each recipe it collects exemplar commits (the `exemplars:` list in the front matter plus the most
recent `feat(...)` commits touching its `watch:` paths), reads the files each commit changed, maps
them to areas (two path components: `model_gateway/src/config`, `crates/symphony`,
`bindings/python`, `e2e_test/router`, `.github/workflows`, …), and reports the areas that at least
half of the exemplars touch but the recipe never mentions. Those are the steps a recipe is missing.

  check_coverage.py [--smg PATH] [--since DATE] [--max N] [--format text|markdown|json]
                    [--show] [--fail-on-gaps] [RECIPES...]

--show lists each exemplar commit with its files, for an agent updating a recipe. Advisory by
default (exit 0); --fail-on-gaps exits 1 when any recipe has a gap.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_anchors import SPAN, classify, expand_braces, find_smg_root, parse_frontmatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RECIPES = ROOT / "skills" / "implement" / "recipes"
IGNORED_FILES = re.compile(r"(^|/)(Cargo\.lock|CHANGELOG\.md|README\.md)$|^docs/|^deploy/helm/.*README")


def area_of(path: str) -> str:
    parts = path.split("/")
    if parts[0] in ("model_gateway", "crates", "bindings", "e2e_test", "clients") and len(parts) > 2:
        if parts[0] == "model_gateway" and parts[1] == "src" and len(parts) > 3:
            return "/".join(parts[:3])
        if parts[0] == "crates" and len(parts) > 3 and parts[2] in ("src", "tests", "benches", "docs", "proto"):
            return "/".join(parts[:3])
        return "/".join(parts[:2])
    if parts[0] == ".github":
        return "/".join(parts[:2])
    return parts[0]


def git(smg: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(smg), *args], capture_output=True, text=True).stdout


def exemplar_commits(smg: Path, fm: dict, since: str, limit: int) -> list[tuple[str, str]]:
    shas: list[str] = []
    for s in fm.get("exemplars", []) if isinstance(fm.get("exemplars"), list) else []:
        s = s.split("#")[0].strip()
        if re.fullmatch(r"[0-9a-f]{7,40}", s):
            shas.append(s)
    watch = [w for w in (fm.get("watch") or []) if isinstance(w, str)]
    if watch:
        out = git(smg, "log", "--no-merges", f"--since={since}", "--format=%h %s", "--", *watch)
        for line in out.splitlines():
            sha, _, subject = line.partition(" ")
            if subject.startswith("feat") and sha not in shas:
                shas.append(sha)
            if len(shas) >= limit:
                break
    result = []
    for sha in shas[:limit]:
        subject = git(smg, "log", "-1", "--format=%h %ad %s", "--date=short", sha).strip()
        if subject:
            result.append((sha, subject))
    return result


def commit_areas(smg: Path, sha: str) -> tuple[set[str], list[str]]:
    files = [f for f in git(smg, "show", "--name-only", "--format=", sha).split("\n") if f and not IGNORED_FILES.search(f)]
    return {area_of(f) for f in files}, files


class Resolver:
    """Normalises the paths a recipe cites: gateway-relative paths (`routers/gateway.rs`,
    `config/validation.rs`, `main.rs`) are read against `model_gateway/src/`, and a bare file name
    that exists once in the checkout resolves to that file."""

    def __init__(self, smg: Path):
        files = [f for f in git(smg, "ls-files").split("\n") if f]
        self.gateway_dirs = {p.name for p in (smg / "model_gateway" / "src").iterdir() if p.is_dir()}
        self.gateway_files = {p.name for p in (smg / "model_gateway" / "src").iterdir() if p.is_file()}
        by_base: dict[str, list[str]] = {}
        for f in files:
            by_base.setdefault(f.rsplit("/", 1)[-1], []).append(f)
        self.unique = {b: ps[0] for b, ps in by_base.items() if len(ps) == 1}

    def normalise(self, p: str) -> str:
        p = p.rstrip("/")
        if p.split("/", 1)[0] in TOP_DIRS_SET:
            return p
        head = p.split("/", 1)[0]
        if head in self.gateway_dirs or (head in self.gateway_files and "/" not in p):
            return "model_gateway/src/" + p
        if head in ("tests", "benches", "test_harness"):
            return "model_gateway/" + p          # `tests/http/...` is the gateway's integration-test tree
        if "/" not in p and p in self.unique:
            return self.unique[p]
        return p


TOP_DIRS_SET = {"model_gateway", "crates", "bindings", "e2e_test", "clients", "scripts", "grpc_servicer", "deploy", "docker", "examples", ".github"}


def recipe_mentions(text: str, resolver: Resolver, watch: list[str] = ()) -> set[str]:
    mentioned: set[str] = set()
    for w in watch:  # the recipe's declared scope counts as mentioned
        q = resolver.normalise(w)
        mentioned.add(area_of(q))
        mentioned.add(q)
    for span in SPAN.findall(text):
        span = re.sub(r"<[^<>]+>", "x", span)   # `crates/engine_servicer/src/<engine>/` mentions that crate
        for kind, value in classify(span):
            if kind == "path":
                for p in expand_braces(value):
                    q = resolver.normalise(p)
                    mentioned.add(area_of(q))
                    mentioned.add(q)  # a directory mention covers everything under it
    return mentioned


def covered(area: str, mentioned: set[str]) -> bool:
    if area in mentioned:
        return True
    return any(area.startswith(m.rstrip("/") + "/") or m.startswith(area + "/") for m in mentioned if "/" in m)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipes", nargs="*", help="recipe stems or paths (default: all)")
    ap.add_argument("--smg")
    ap.add_argument("--since", default="2026-08-20", help="look back this far for feat commits")
    ap.add_argument("--max", type=int, default=6, help="exemplars per recipe")
    ap.add_argument("--format", choices=("text", "markdown", "json"), default="text")
    ap.add_argument("--show", action="store_true", help="list each exemplar's files")
    ap.add_argument("--fail-on-gaps", action="store_true")
    args = ap.parse_args()
    smg = Path(args.smg or os.environ.get("SMG_ROOT") or "") if (args.smg or os.environ.get("SMG_ROOT")) else find_smg_root(Path.cwd())
    if not smg or not (smg / "model_gateway" / "Cargo.toml").is_file():
        print("check_coverage: no SMG checkout found; pass --smg", file=sys.stderr)
        return 2
    files = [RECIPES / (r if r.endswith(".md") else f"{r}.md") if "/" not in r else Path(r) for r in args.recipes] or sorted(RECIPES.glob("*.md"))
    report = []
    any_gap = False
    resolver = Resolver(smg)
    for f in files:
        text = f.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(text.splitlines())
        exemplars = exemplar_commits(smg, fm, args.since, args.max)
        mentioned = recipe_mentions(text, resolver, [w for w in (fm.get("watch") or []) if isinstance(w, str)])
        counts: dict[str, int] = {}
        details = []
        for sha, subject in exemplars:
            areas, flist = commit_areas(smg, sha)
            for a in areas:
                counts[a] = counts.get(a, 0) + 1
            details.append({"sha": sha, "subject": subject, "files": flist})
        n = len(exemplars)
        threshold = max(2, math.ceil(n / 2)) if n else 0
        gaps = sorted(a for a, c in counts.items() if c >= threshold and not covered(a, mentioned))
        any_gap |= bool(gaps)
        report.append({"recipe": f.stem, "exemplars": details, "gaps": [{"area": a, "touched_by": counts[a]} for a in gaps], "threshold": threshold})

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        md = args.format == "markdown"
        if md:
            print("## Exemplar coverage\n")
        for r in report:
            n = len(r["exemplars"])
            head = f"{r['recipe']}: {n} exemplar(s), {len(r['gaps'])} gap(s)"
            print(f"### {head}" if md else head)
            if args.show or md:
                for e in r["exemplars"]:
                    print(f"- {e['subject']}" if md else f"  {e['subject']}")
                    if args.show:
                        for fl in e["files"]:
                            print(f"      {fl}")
            for g in r["gaps"]:
                line = f"GAP {g['area']} (touched by {g['touched_by']} of {n} exemplars, never mentioned)"
                print(f"- **{line}**" if md else f"  {line}")
            if md:
                print()
        total = sum(len(r["gaps"]) for r in report)
        print(f"coverage: {len(report)} recipe(s), {total} gap(s); threshold = at least half of a recipe's exemplars")
    return 1 if (any_gap and args.fail_on_gaps) else 0


if __name__ == "__main__":
    sys.exit(main())

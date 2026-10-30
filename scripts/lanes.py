#!/usr/bin/env python3
"""Which SMG areas, review checklists, recipes and CI lanes a set of changed files touches.

Reads data/subsystems.json. Files come from the command line; with none, the script runs
`git diff --name-only <merge-base of origin/main> HEAD` plus the working tree inside the SMG
checkout found from the cwd (or --smg). Used by gate.sh for its lanes row and by agents to size
a change before they start.

  lanes.py [--smg PATH] [--format text|json] [FILES...]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def find_smg(start: Path) -> Path | None:
    d = start.resolve()
    while True:
        if (d / "model_gateway" / "Cargo.toml").is_file() and (d / "crates" / "protocols" / "Cargo.toml").is_file():
            return d
        if d.parent == d:
            return None
        d = d.parent


def changed_files(smg: Path, base: str) -> list[str]:
    def run(*args: str) -> list[str]:
        r = subprocess.run(["git", "-C", str(smg), *args], capture_output=True, text=True)
        return [l for l in r.stdout.split("\n") if l]
    mb = run("merge-base", base, "HEAD")
    files = set(run("diff", "--name-only", mb[0], "HEAD")) if mb else set()
    files |= set(run("diff", "--name-only"))
    files |= set(run("diff", "--name-only", "--cached"))
    return sorted(files)


def matches(path: str, prefix: str) -> bool:
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(prefix + "/")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--smg")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args()
    data = json.loads((ROOT / "data" / "subsystems.json").read_text())
    files = args.files
    if not files:
        smg = Path(args.smg) if args.smg else find_smg(Path.cwd())
        if not smg:
            print("lanes.py: no files given and no SMG checkout found", file=sys.stderr)
            return 2
        files = changed_files(smg, args.base)
    areas = [a for a in data["areas"] if any(matches(f, p) for f in files for p in a["paths"])]
    lanes = sorted({l for a in areas for l in a["lanes"]})
    checklists = sorted({c for a in areas for c in a["checklists"]})
    recipes = sorted({a["recipe"] for a in areas if a.get("recipe")})
    if any(f.endswith(".rs") for f in files):
        lanes = sorted(set(lanes) | {"rust-lint", "rust-tests", "cargo-audit"})
    out = {"files": len(files), "areas": [a["id"] for a in areas], "recipes": recipes, "checklists": checklists, "lanes": lanes}
    if args.format == "json":
        print(json.dumps(out, indent=2))
    else:
        print(f"files: {out['files']}")
        print(f"areas: {', '.join(out['areas']) or '(none matched)'}")
        print(f"recipes: {', '.join(recipes) or '(none)'}")
        print(f"review checklists: {', '.join(checklists) or '(general sections only)'}")
        print(f"CI lanes: {', '.join(lanes) or '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

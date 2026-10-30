#!/usr/bin/env python3
"""Vocabulary check: flags terms SMG's maintainers avoid and names the preferred term.

Rules live in data/vocabulary.json: `term` (whole-word match unless `regex` is given), `replace`,
`why`, `level` (error = SMG's own rule, warn = the guide's addition), `scope` (all | prose | code)
and `allow` (regexes that exempt a line, e.g. CI matrix "legs" when the PD vocabulary bans "leg").

Inputs: files on the command line; `--diff` reads a unified diff on stdin and checks added lines;
`--commits RANGE` checks commit messages (run in the repository). It reports and never rewrites.
Exit 1 when an error-level term is flagged and --strict is given, else 0.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE_SUFFIXES = {".rs", ".py", ".go", ".proto", ".wit", ".sh", ".js", ".ts", ".java"}


def load_terms(path: Path) -> list[dict]:
    terms = json.loads(path.read_text(encoding="utf-8"))["terms"]
    for t in terms:
        pat = t.get("regex") or r"\b" + re.escape(t["term"]) + r"s?\b"
        t["_re"] = re.compile(pat, re.IGNORECASE)
        t["_allow"] = [re.compile(a, re.IGNORECASE) for a in t.get("allow", [])]
        t.setdefault("scope", "all")
        t.setdefault("level", "warn")
    return terms


def scope_of(path: str) -> str:
    return "code" if Path(path).suffix.lower() in CODE_SUFFIXES else "prose"


def check_line(terms: list[dict], text: str, scope: str) -> list[tuple[dict, str]]:
    hits = []
    for t in terms:
        if t["scope"] not in ("all", scope):
            continue
        m = t["_re"].search(text)
        if m and not any(a.search(text) for a in t["_allow"]):
            hits.append((t, m.group(0)))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="files to scan")
    ap.add_argument("--diff", action="store_true", help="read a unified diff from stdin; check added lines only")
    ap.add_argument("--commits", metavar="RANGE", help="check commit messages in a git range, e.g. origin/main..HEAD")
    ap.add_argument("--vocab", default=str(ROOT / "data" / "vocabulary.json"))
    ap.add_argument("--strict", action="store_true", help="exit 1 when an error-level term is flagged")
    ap.add_argument("--quiet-warn", action="store_true", help="count warn-level hits without printing them")
    args = ap.parse_args()
    terms = load_terms(Path(args.vocab))
    counts = {"error": 0, "warn": 0}

    def report(where: str, hits: list[tuple[dict, str]]) -> None:
        for t, word in hits:
            counts[t["level"]] += 1
            if t["level"] == "warn" and args.quiet_warn:
                continue
            print(f"{t['level'].upper():5} {where}: '{word}' -> {t['replace']}  [{t['why']}]")

    if args.diff:
        path, n = "?", 0
        for line in sys.stdin:
            if line.startswith("+++ "):
                path = line[4:].strip().removeprefix("b/")
            elif line.startswith("@@"):
                m = re.search(r"\+(\d+)", line)
                n = int(m.group(1)) - 1 if m else 0
            elif line.startswith("+"):
                n += 1
                report(f"{path}:{n}", check_line(terms, line[1:], scope_of(path)))
            elif not line.startswith("-"):
                n += 1
    if args.commits:
        out = subprocess.run(["git", "log", "--no-merges", "--format=%h%x00%B%x01", args.commits], capture_output=True, text=True).stdout
        for entry in out.split("\x01"):
            if not entry.strip():
                continue
            sha, _, body = entry.partition("\x00")
            for i, line in enumerate(body.splitlines(), 1):
                report(f"commit {sha.strip()} line {i}", check_line(terms, line, "prose"))
    for f in args.files:
        p = Path(f)
        if not p.is_file():
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(lines, 1):
            report(f"{f}:{i}", check_line(terms, line, scope_of(f)))

    print(f"vocabulary: {counts['error']} error-level, {counts['warn']} warn-level hit(s); {len(terms)} rules")
    return 1 if (counts["error"] and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())

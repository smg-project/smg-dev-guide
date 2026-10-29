#!/usr/bin/env python3
"""Drift detector for the SMG dev guide.

Every repository path, Rust/Python symbol, CLI flag and CI lane name that a skill cites is an
*anchor* into the SMG codebase. This script pulls the anchors straight out of the Markdown (so
there is no manifest to keep in sync) and checks each one against an SMG checkout. A guide that
has drifted from upstream then fails loudly instead of sending an agent to a file that moved two
releases ago.

What counts as an anchor (inline code spans in prose and tables; fenced blocks are examples and
are skipped unless --include-fenced):
  path     crates/foo/src/bar.rs, model_gateway/src/policies/, e2e_test/fixtures/hooks.py,
           bare file names such as types.rs (resolved by basename), brace sets a/{b,c}.rs, globs
  symbol   CamelCase types, snake_case functions/fields (with an underscore), SCREAMING_CONSTS,
           and the segments of Type::method / module::item / value.method() spans
  flag     --kebab-case CLI flags (matched as foo_bar or foo-bar in the sources)
  literal  kebab-case names such as CI lanes (e2e-1gpu-chat-zmq) or hook ids (check-symlinks)

Placeholders (MyPolicy, mybackend.rs) and intentional negatives ("there is no handle_pod_event")
live in anchors/ignore.txt, one anchored regex per line. A Markdown line that carries
<!-- anchor-ignore --> is skipped entirely.

Recipe front matter is checked too: every entry under `watch:` must exist.

Usage:
  check_anchors.py [--smg PATH] [--guide PATH] [--paths-only] [--format text|json|markdown]
                   [--summary] [--no-fail] [--include-fenced] [FILES...]

Exit status: 0 when nothing is broken (or --no-fail), 1 when anchors are broken, 2 on usage
errors such as no SMG checkout being found.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

TOP_DIRS = (
    "crates", "model_gateway", "bindings", "clients", "e2e_test", "scripts", "examples",
    "grpc_servicer", "deploy", "docker", ".github", "assets",
)
ROOT_FILES = {
    "Cargo.toml", "Cargo.lock", "clippy.toml", "rustfmt.toml", "rust-toolchain.toml", "Makefile",
    "README.md", "REVIEW.md", "CONTRIBUTING.md", "GOVERNANCE.md", "CODE_OF_CONDUCT.md",
    "mypy.ini", "pytest.ini", "ruff.toml", ".pre-commit-config.yaml", ".gitignore",
}
# Bare file names (no slash) are resolved by basename when they carry one of these extensions.
BARE_FILE_EXTS = (".rs", ".py", ".go", ".proto", ".wit", ".yml", ".yaml", ".toml", ".sh", ".jinja", ".ini")
# Where symbols are searched in the SMG checkout.
SOURCE_GLOBS = (
    "*.rs", "*.py", "*.go", "*.proto", "*.toml", "*.yaml", "*.yml", "*.wit", "*.sh", "*.json",
    "*.md", "*.ini", "*.txt", "Makefile", "Dockerfile*",
)
SKILL_DIRS = ("skills", "commands", "agents")
# A multi-token span starting with one of these is a command of another tool: its --flags are not SMG anchors.
EXTERNAL_TOOLS = {
    "cargo", "git", "pytest", "python", "python3", "pip", "pip3", "make", "ruff", "mypy", "pre-commit", "gh",
    "kubectl", "docker", "maturin", "rustup", "curl", "go", "npm", "claude", "bash", "sh", "vllm", "ts",
    "codespell", "rg", "grep", "ln", "cd", "export",
}

CAMEL = re.compile(r"[A-Z][A-Za-z0-9]{2,}")
SNAKE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+")
SCREAM = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")
KEBAB = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
FLAG = re.compile(r"--([a-z][a-z0-9-]*[a-z0-9])(?:[= ].*)?")
PATH_CHARS = re.compile(r"[\w.@{},*/-]+")
SPAN = re.compile(r"`([^`\n]+)`")
PATH_WITH_SYMBOL = re.compile(r"^([\w./{},*-]+\.(?:rs|py|go|yml|yaml|toml|sh|proto|wit))(?:::|:)([A-Za-z_][\w:]*)$")
DOTTED = re.compile(r"^[A-Za-z_]\w*\.([A-Za-z_]\w+)$")
IGNORE_MARK = "<!-- anchor-ignore -->"


@dataclass(frozen=True)
class Anchor:
    file: str
    line: int
    kind: str
    value: str


def guide_root_default() -> Path:
    return Path(__file__).resolve().parents[1]


def find_smg_root(start: Path) -> Path | None:
    d = start.resolve()
    while True:
        if (d / "model_gateway" / "Cargo.toml").is_file() and (d / "crates" / "protocols" / "Cargo.toml").is_file():
            return d
        if d.parent == d:
            return None
        d = d.parent


def expand_braces(p: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", p)
    if not m:
        return [p]
    if "," not in m.group(1):  # a placeholder such as {ENGINE} or {name}: match any name there
        return expand_braces(p[: m.start()] + "*" + p[m.end():])
    out: list[str] = []
    for alt in m.group(1).split(","):
        out.extend(expand_braces(p[: m.start()] + alt.strip() + p[m.end():]))
    return out


def looks_like_path(tok: str) -> bool:
    if not tok or not PATH_CHARS.fullmatch(tok):
        return False
    if tok in ROOT_FILES:
        return True
    if "/" in tok:
        return tok.split("/", 1)[0] in TOP_DIRS
    return tok.endswith(BARE_FILE_EXTS) and "." in tok[:-1]


def classify(span: str) -> list[tuple[str, str]]:
    """Turn one code span into zero or more (kind, value) anchors."""
    s = span.strip().strip(",.;:")
    if len(s) < 3 or s.startswith(("smg:", "@", "/", "$", "#", "<", "-m", "!")):
        return []
    if any(ch in s for ch in " \t"):
        out: list[tuple[str, str]] = []
        toks = s.split()
        external = toks[0] in EXTERNAL_TOOLS or (toks[0].endswith("=") is False and "=" in toks[0] and len(toks) > 1 and toks[1] in EXTERNAL_TOOLS)
        for tok in toks:
            if external and tok.startswith("--"):
                continue
            tok = tok.strip("\"'`()[]{}<>,;")
            if looks_like_path(tok):
                out.append(("path", tok))
            elif tok.startswith("--"):
                m = FLAG.fullmatch(tok)
                if m:
                    out.append(("flag", m.group(1)))
        return out
    if s.endswith("()"):
        s = s[:-2]
    m = PATH_WITH_SYMBOL.match(s)
    if m and looks_like_path(m.group(1)):
        return [("path", m.group(1))] + classify(m.group(2))
    if looks_like_path(s):
        return [("path", s)]
    if s.startswith("--"):
        m = FLAG.fullmatch(s)
        return [("flag", m.group(1))] if m else []
    m = DOTTED.match(s)
    if m:
        return classify(m.group(1))
    if "::" in s:
        parts = [p.split("<")[0].rstrip("()") for p in s.split("::") if p]
        out = []
        for i, p in enumerate(parts):
            if CAMEL.fullmatch(p) or (i == len(parts) - 1 and (SNAKE.fullmatch(p) or SCREAM.fullmatch(p))):
                out.append(("symbol", p))
        return out
    s = s.split("<")[0].rstrip("()")
    if CAMEL.fullmatch(s) or SNAKE.fullmatch(s) or SCREAM.fullmatch(s):
        return [("symbol", s)]
    if KEBAB.fullmatch(s):
        return [("literal", s)]
    return []


def parse_frontmatter(lines: list[str]) -> tuple[dict, int]:
    """Minimal YAML front matter: scalars and `- item` lists. Returns (data, body_start_line)."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    data: dict = {}
    key = None
    for i in range(1, len(lines)):
        line = lines[i].rstrip("\n")
        if line.strip() == "---":
            return data, i + 1
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
    return data, 0


def extract(md_file: Path, guide_root: Path, include_fenced: bool) -> list[Anchor]:
    rel = str(md_file.relative_to(guide_root))
    lines = md_file.read_text(encoding="utf-8").splitlines()
    fm, body_start = parse_frontmatter(lines)
    anchors: list[Anchor] = []
    for p in fm.get("watch", []) if isinstance(fm.get("watch"), list) else []:
        anchors.append(Anchor(rel, 1, "watch", p))
    in_fence = False
    for n, line in enumerate(lines[body_start:], start=body_start + 1):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence and not include_fenced:
            continue
        if IGNORE_MARK in line:
            continue
        for span in SPAN.findall(line):
            for kind, value in classify(span):
                anchors.append(Anchor(rel, n, kind, value))
    # dedupe while keeping order
    seen: set[Anchor] = set()
    out = []
    for a in anchors:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def load_ignore(guide_root: Path) -> list[re.Pattern]:
    f = guide_root / "anchors" / "ignore.txt"
    pats: list[re.Pattern] = []
    if f.is_file():
        for raw in f.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                pats.append(re.compile(line))
    return pats


class Index:
    """Tracked files of the SMG checkout, plus batched symbol lookup."""

    def __init__(self, root: Path):
        self.root = root
        out = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True).stdout
        self.files = set(out.split("\n")) - {""}
        self.dirs: set[str] = set()
        self.basenames: set[str] = set()
        for f in self.files:
            self.basenames.add(f.rsplit("/", 1)[-1])
            parts = f.split("/")
            for i in range(1, len(parts)):
                self.dirs.add("/".join(parts[:i]))

    def path_exists(self, p: str) -> bool:
        for cand in expand_braces(p):
            c = cand.rstrip("/")
            if "*" in c:
                if "/" in c:
                    ok = any(fnmatch.fnmatch(f, c) or fnmatch.fnmatch(f, c + "/*") for f in self.files)
                else:
                    ok = any(fnmatch.fnmatch(b, c) for b in self.basenames)
            elif "/" in c:
                ok = c in self.files or c in self.dirs
            else:
                ok = c in self.files or c in self.basenames or c in self.dirs
            if not ok:
                return False
        return True

    def found_words(self, words: set[str]) -> set[str]:
        """Which of `words` occur as whole words anywhere in the source globs."""
        if not words:
            return set()
        rg = shutil.which("rg")
        if rg:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
                # Longest first: ripgrep's alternation is leftmost-first, so a shorter pattern that is a
                # prefix of a longer one (e2e-1gpu-chat vs e2e-1gpu-chat-zmq) would otherwise shadow it.
                tf.write("\n".join(re.escape(w) for w in sorted(words, key=lambda w: (-len(w), w))) + "\n")
                patterns = tf.name
            try:
                cmd = [rg, "-o", "-w", "-I", "-N", "--hidden", "-g", "!.git", "--no-heading", "--no-messages", "-f", patterns]
                for g in SOURCE_GLOBS:
                    cmd += ["-g", g]
                cmd.append(".")
                proc = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True)
                return set(proc.stdout.split())
            finally:
                os.unlink(patterns)
        found: set[str] = set()
        pathspecs = [f":(glob)**/{g}" for g in SOURCE_GLOBS]
        for w in words:
            r = subprocess.run(["git", "-C", str(self.root), "grep", "-q", "-w", "-F", "-e", w, "--", *pathspecs], capture_output=True)
            if r.returncode == 0:
                found.add(w)
        return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="Markdown files to check (default: every skill, command and agent file)")
    ap.add_argument("--smg", help="SMG checkout root (default: $SMG_ROOT, else found by walking up from the cwd)")
    ap.add_argument("--guide", help="dev-guide root (default: the repo this script lives in)")
    ap.add_argument("--paths-only", action="store_true", help="skip symbol/flag/literal lookups (fast; used by the session hook)")
    ap.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    ap.add_argument("--summary", action="store_true", help="print one summary line only")
    ap.add_argument("--no-fail", action="store_true", help="exit 0 even when anchors are broken")
    ap.add_argument("--include-fenced", action="store_true", help="also scan fenced code blocks")
    args = ap.parse_args()

    guide = Path(args.guide).resolve() if args.guide else guide_root_default()
    smg_arg = args.smg or os.environ.get("SMG_ROOT")
    smg = Path(smg_arg).resolve() if smg_arg else find_smg_root(Path.cwd())
    if not smg or not (smg / "model_gateway" / "Cargo.toml").is_file():
        print("check_anchors: no SMG checkout found. Pass --smg PATH, set SMG_ROOT, or run inside an SMG checkout.", file=sys.stderr)
        return 2

    if args.files:
        md_files = [Path(f).resolve() for f in args.files]
    else:
        md_files = sorted(p for d in SKILL_DIRS for p in (guide / d).rglob("*.md") if (guide / d).is_dir())

    ignore = load_ignore(guide)
    anchors: list[Anchor] = []
    for f in md_files:
        anchors.extend(extract(f, guide, args.include_fenced))

    index = Index(smg)
    guide_files = {str(p.relative_to(guide)) for p in guide.rglob("*") if ".git" not in p.parts}
    guide_basenames = {p.name for p in guide.rglob("*") if ".git" not in p.parts and p.is_file()}

    def ignored(a: Anchor) -> bool:
        return any(p.fullmatch(a.value) for p in ignore)

    checked: list[Anchor] = []
    skipped = 0
    for a in anchors:
        if ignored(a):
            skipped += 1
            continue
        if a.kind in ("path", "watch") and (a.value in guide_files or ("/" not in a.value and a.value in guide_basenames)):
            skipped += 1  # a reference to the guide's own files (gate.sh, SKILL.md), not an SMG anchor
            continue
        checked.append(a)

    words: set[str] = set()
    if not args.paths_only:
        for a in checked:
            if a.kind == "symbol" or a.kind == "literal":
                words.add(a.value)
            elif a.kind == "flag":
                words.add(a.value)
                words.add(a.value.replace("-", "_"))
    found = index.found_words(words)

    broken: list[Anchor] = []
    by_kind: dict[str, int] = {}
    for a in checked:
        if args.paths_only and a.kind not in ("path", "watch"):
            continue
        by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
        if a.kind in ("path", "watch"):
            ok = index.path_exists(a.value)
        elif a.kind == "flag":
            ok = a.value in found or a.value.replace("-", "_") in found
        else:
            ok = a.value in found
        if not ok:
            broken.append(a)

    head = subprocess.run(["git", "-C", str(smg), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True).stdout.strip()
    total = sum(by_kind.values())
    summary = (
        f"anchors: {total} checked against smg@{head or '?'} "
        f"({', '.join(f'{k} {v}' for k, v in sorted(by_kind.items()))}); broken {len(broken)}; ignored {skipped}"
    )

    if args.format == "json":
        print(json.dumps({
            "smg_root": str(smg), "smg_head": head, "checked": total, "by_kind": by_kind,
            "ignored": skipped, "broken": [asdict(b) for b in broken], "files": [str(f.relative_to(guide)) for f in md_files],
        }, indent=2))
    elif args.summary:
        print(summary)
    elif args.format == "markdown":
        print(f"## Anchor drift report\n\n{summary}\n")
        if broken:
            print("| Guide file | Line | Kind | Anchor |\n|---|---|---|---|")
            for b in sorted(broken, key=lambda x: (x.file, x.line)):
                print(f"| `{b.file}` | {b.line} | {b.kind} | `{b.value}` |")
        else:
            print("No broken anchors.")
    else:
        for b in sorted(broken, key=lambda x: (x.file, x.line)):
            print(f"BROKEN  {b.kind:<7} {b.value:<60} {b.file}:{b.line}")
        print(summary)
    return 0 if (not broken or args.no_fail) else 1


if __name__ == "__main__":
    sys.exit(main())

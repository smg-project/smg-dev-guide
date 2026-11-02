#!/usr/bin/env python3
"""Which workspace packages a set of changed files touches, for `cargo clippy -p` and `cargo test -p`.

A changed file belongs to the package whose Cargo.toml is its nearest ancestor and is a member of the
root workspace; a manifest that is no member (a nested fuzz workspace, a guest example with its own
workspace) climbs to the next ancestor. Files under no package (docs, scripts, CI) add nothing. The
workspace manifest, Cargo.lock, .cargo/, clippy.toml and rust-toolchain.toml change what every crate
compiles against, so any of them widens the scope to the whole workspace, printed as the single word
`workspace`.

Files come from the command line, from stdin with `-`, or (with neither) from `git diff --name-only
<merge-base of --base> HEAD` plus the working tree (staged, unstaged and untracked files) of the SMG
checkout found from the cwd (or --smg); a path is classified where it sits in the checkout, not where
a symlink points.
Used by gate.sh for its clippy and test rows; `--format args` prints the `-p` list cargo takes.

  crate_scope.py [--smg PATH] [--base REF] [--format lines|args] [FILES... | -]
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from lanes import BaseNotFound, changed_files, find_smg

# Root-level files whose change reaches every crate: the scope widens to the workspace.
WIDENERS = ("Cargo.toml", "Cargo.lock", "clippy.toml", "rust-toolchain.toml")
WIDENER_DIRS = (".cargo/",)


def read_manifest(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def members(root: Path) -> dict[Path, str]:
    """Manifest directory -> package name for every member of the workspace rooted at `root`."""
    manifest = read_manifest(root / "Cargo.toml")
    ws = manifest.get("workspace", {})
    dirs: set[Path] = set()
    for pattern in ws.get("members", []):
        dirs.update(p for p in root.glob(pattern) if (p / "Cargo.toml").is_file())
    for pattern in ws.get("exclude", []):
        dirs.difference_update(root.glob(pattern))
    if "package" in manifest:
        dirs.add(root)
    out: dict[Path, str] = {}
    for d in dirs:
        name = read_manifest(d / "Cargo.toml").get("package", {}).get("name")
        if name:
            out[d.resolve()] = name
    return out


def scope(root: Path, files: list[str]) -> list[str] | None:
    """Sorted package names the files touch; None when the scope is the whole workspace."""
    root = root.resolve()
    pkgs = members(root)
    out: set[str] = set()
    for f in files:
        p = Path(f)
        p = p if p.is_absolute() else root / p
        # The directories resolve (a checkout reached through a link), the last component does not: a tracked
        # symlink is a change to the crate it sits in, wherever it points (even outside the checkout).
        p = p.parent.resolve() / p.name
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue  # outside the checkout
        if rel in WIDENERS or rel.startswith(WIDENER_DIRS):
            return None
        d = p.parent
        while True:
            if d in pkgs:
                out.add(pkgs[d])
                break
            if d == root or d == d.parent:
                break
            d = d.parent
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="changed paths relative to the checkout root; '-' reads them from stdin")
    ap.add_argument("--smg")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--format", choices=("lines", "args"), default="lines")
    args = ap.parse_args()
    smg = Path(args.smg) if args.smg else find_smg(Path.cwd())
    if not smg or not (smg / "Cargo.toml").is_file():
        print("crate_scope.py: no workspace found (run inside the SMG checkout or pass --smg)", file=sys.stderr)
        return 2
    files = args.files
    if files == ["-"]:
        files = [line.strip() for line in sys.stdin if line.strip()]
    elif not files:
        try:
            files = changed_files(smg, args.base)
        except BaseNotFound:
            print(f"crate_scope.py: no merge base with {args.base} (fetch it, pass --base, or name the files)", file=sys.stderr)
            return 2
    pkgs = scope(smg, files)
    if pkgs is None:
        print("workspace")
    elif args.format == "args":
        print(" ".join(f"-p {p}" for p in pkgs))
    else:
        print("\n".join(pkgs))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""PreToolUse guard for Bash commands inside an SMG or smg-dev-guide checkout.

SMG's CI rejects, after the fact, what this hook blocks before the fact:
  * a commit without a DCO sign-off (`git commit -s`)
  * a Co-authored-by / Signed-off-by trailer naming Claude or anthropic.com
  * `--no-verify` on commit or push (pre-commit runs fmt, clippy, DCO and naming checks)
  * a commit on main (SMG's pre-commit `no-commit-to-branch`)
  * a push from a branch that does not match <type>/<desc> or <username>/<desc>
  * a push whose new commits are unsigned or carry AI attribution

Anywhere outside those two repositories the hook is a no-op. On a block it prints the
documented PreToolUse JSON with permissionDecision "deny" and a reason the agent can act on.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

SMG_BRANCH = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?(/[a-zA-Z0-9._-]+)+$")
GUIDE_BRANCH = re.compile(r"^(setup|feat|fix|docs|chore|refactor)/[A-Za-z0-9._-]+$")
AI_TRAILER = re.compile(r"(?im)^\s*(co-authored-by|signed-off-by)\s*:.*\b(claude|anthropic)\b")
SIGNOFF = re.compile(r"(?m)^Signed-off-by:")
MAIN_BRANCHES = {"main", "master"}


def repo_kind(cwd: str) -> tuple[str | None, str | None]:
    d = os.path.realpath(cwd)
    while True:
        if os.path.isfile(os.path.join(d, "model_gateway", "Cargo.toml")) and os.path.isfile(
            os.path.join(d, "crates", "protocols", "Cargo.toml")
        ):
            return "smg", d
        if (
            os.path.isfile(os.path.join(d, ".claude-plugin", "plugin.json"))
            and os.path.isfile(os.path.join(d, "skills", "map", "SKILL.md"))
            and os.path.isfile(os.path.join(d, "smg-ref.json"))
        ):
            return "guide", d
        parent = os.path.dirname(d)
        if parent == d:
            return None, None
        d = parent


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def git(root: str, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def segments(cmd: str) -> list[str]:
    return [s for s in re.split(r"&&|\|\||;|\n|\|", cmd) if s.strip()]


def tokens(seg: str) -> list[str]:
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.split()


def short_flag(tok: str, letter: str) -> bool:
    return tok.startswith("-") and not tok.startswith("--") and letter in tok[1:]


def check_commit(seg: str, toks: list[str], cmd: str, kind: str, root: str) -> None:
    if "--no-verify" in toks or any(short_flag(t, "n") for t in toks if t != "-m"):
        deny("This repository runs pre-commit hooks (rustfmt, clippy, DCO sign-off, no-AI-attribution, branch naming) that CI re-checks. Do not bypass them with --no-verify / -n; fix what the hook reports instead.")
    if AI_TRAILER.search(cmd):
        deny("CI rejects any Co-authored-by or Signed-off-by line that names Claude or anthropic.com (see .pre-commit-config.yaml `no-ai-co-author` and the PR workflow). Remove that trailer from the commit message.")
    amend_keep = "--amend" in toks and "--no-edit" in toks
    signed = "--signoff" in toks or any(short_flag(t, "s") for t in toks)
    if not signed and not amend_keep:
        deny("Every commit needs a DCO sign-off matching your git user.name/user.email (scripts/dco-check.sh; CI fails without it). Re-run as `git commit -s ...` (or `git commit --amend -s --no-edit` to sign the last commit).")
    if kind == "smg" and not re.search(r"\b(checkout\s+-b|switch\s+-c)\b", cmd):
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        if branch in MAIN_BRANCHES:
            deny(f"You are on `{branch}`. SMG's pre-commit forbids committing to it (`no-commit-to-branch`), and PRs come from branches named <type>/<desc> or <username>/<desc>. Create a branch first: `git checkout -b feat/<short-description>`.")


def check_push(seg: str, toks: list[str], kind: str, root: str) -> None:
    if "--no-verify" in toks:
        deny("Do not push with --no-verify: the pre-push hook enforces the branch naming convention that CI also checks.")
    after = toks[toks.index("push") + 1:] if "push" in toks else []
    if any(":" in t for t in after):
        return  # explicit refspec; the pushed branch name is not the local one
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        return
    if kind == "smg":
        if branch not in MAIN_BRANCHES and not SMG_BRANCH.match(branch):
            deny(f"Branch `{branch}` does not match SMG's convention `<type>/<description>` or `<username>/<description>` (regex ^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?(/[a-zA-Z0-9._-]+)+$). CI closes PRs from such branches. Rename first: `git branch -m feat/<short-description>` and push that.")
    elif kind == "guide":
        if branch not in MAIN_BRANCHES and not GUIDE_BRANCH.match(branch):
            deny(f"Branch `{branch}` does not match smg-dev-guide's convention setup/*, feat/*, fix/*, docs/*, chore/* or refactor/*. Rename first: `git branch -m docs/<short-description>`.")
    # commits that would be pushed: unsigned or AI-attributed ones fail CI
    base = ""
    for cand in ("@{u}", "origin/main", "origin/master"):
        if git(root, "rev-parse", "--verify", "--quiet", cand):
            base = cand
            break
    if not base:
        return
    shas = git(root, "rev-list", "--no-merges", "--max-count=50", f"{base}..HEAD").split()
    bad_sign, bad_ai = [], []
    for sha in shas:
        body = git(root, "log", "-1", "--format=%B", sha)
        if not SIGNOFF.search(body):
            bad_sign.append(sha[:10])
        if AI_TRAILER.search(body):
            bad_ai.append(sha[:10])
    if bad_sign or bad_ai:
        parts = []
        if bad_sign:
            parts.append(f"commits without a Signed-off-by trailer: {', '.join(bad_sign)} (fix: `git rebase --signoff {base}`)")
        if bad_ai:
            parts.append(f"commits with a Claude/anthropic attribution trailer: {', '.join(bad_ai)} (fix: amend or reword them to drop the line)")
        deny("CI will reject this push. " + "; ".join(parts) + ".")


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Bash":
        return
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if "git" not in cmd:
        return
    cwd = data.get("cwd") or os.getcwd()
    m = re.match(r"\s*cd\s+(\S+)\s*(?:&&|;)", cmd)
    if m:
        target = os.path.expanduser(m.group(1).strip("'\""))
        cwd = target if os.path.isabs(target) else os.path.join(cwd, target)
    m = re.search(r"\bgit\s+-C\s+(\S+)", cmd)
    if m:
        target = os.path.expanduser(m.group(1).strip("'\""))
        cwd = target if os.path.isabs(target) else os.path.join(cwd, target)
    kind, root = repo_kind(cwd)
    if not kind:
        return
    for seg in segments(cmd):
        toks = tokens(seg)
        if "git" not in toks:
            continue
        if "commit" in toks:
            check_commit(seg, toks, cmd, kind, root)
        if "push" in toks:
            check_push(seg, toks, kind, root)


if __name__ == "__main__":
    main()

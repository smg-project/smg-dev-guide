#!/usr/bin/env bash
# SessionStart hook. When a session opens inside an SMG checkout (or inside smg-dev-guide itself),
# tell the agent which repo it is in, how far the checkout is from the commit this guide was
# verified against, whether any path the skills cite has gone missing, and which skills and
# guard rails apply. Anywhere else it prints nothing. It never fails the session: every step
# degrades to silence.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
. "$here/../lib/detect_smg.sh"

input="$(cat 2>/dev/null || true)"
cwd="$(printf '%s' "$input" | sed -nE 's/.*"cwd" *: *"([^"]*)".*/\1/p' | head -1)"
cwd="${cwd:-$PWD}"
guide="$(guide_root)"

emit() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$1" <<'PY' 2>/dev/null && return 0
import json, sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": sys.argv[1]}}))
PY
  fi
  printf '%s\n' "$1"
}

if root="$(smg_root "$cwd")"; then
  ver="$(smg_version "$root")"; head="$(smg_head "$root")"
  branch="$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null)"
  pin="$(guide_pin)"; pinv="$(guide_pin_version)"
  drift="The smg plugin's guide was verified against SMG ${pin:0:12} (v${pinv})."
  if [ -n "$pin" ] && git -C "$root" cat-file -e "$pin" 2>/dev/null; then
    n="$(git -C "$root" rev-list --count "$pin..HEAD" 2>/dev/null || echo '?')"
    drift="$drift This checkout is $n commits past that commit."
  elif [ -n "$pin" ]; then
    drift="$drift That commit is not in this checkout's history, so drift is unknown."
  fi
  anchors=""
  if command -v python3 >/dev/null 2>&1 && [ -f "$guide/scripts/check_anchors.py" ]; then
    if command -v timeout >/dev/null 2>&1; then
      anchors="$(timeout 8 python3 "$guide/scripts/check_anchors.py" --smg "$root" --guide "$guide" --paths-only --summary --no-fail 2>/dev/null)"
    else
      anchors="$(python3 "$guide/scripts/check_anchors.py" --smg "$root" --guide "$guide" --paths-only --summary --no-fail 2>/dev/null)"
    fi
  fi
  msg="SMG checkout detected at $root (v${ver:-?}, HEAD ${head:-?}, branch ${branch:-?}). $drift"
  [ -n "$anchors" ] && msg="$msg Quick check of the paths the guide cites: $anchors. If a skill points at a path or symbol that is gone, use /smg:learn to record it rather than guessing."
  msg="$msg
Skills: /smg:map (orient: live crate map + invariants), /smg:implement (build with a subsystem recipe), /smg:review-pr (checklist review), /smg:contribute (run the pre-PR gate: scripts/gate.sh), /smg:learn (record a guide gap), /smg:sync (resync the guide; maintainers).
Guard rails this plugin enforces here with a PreToolUse hook, because SMG's CI rejects them later: every commit needs a DCO sign-off (git commit -s); no Co-authored-by/Signed-off-by line may name Claude or anthropic.com; no --no-verify; no commits on main; a pushed branch must match <type>/<desc> or <username>/<desc>."
  emit "$msg"
elif groot="$(guide_repo_root "$cwd")"; then
  emit "smg-dev-guide checkout detected at $groot: this repository IS the smg plugin (skills/, recipes, hooks, scripts). Useful here: python3 scripts/check_anchors.py --smg <smg checkout> (drift against SMG), python3 scripts/lint_guide.py (self-consistency), bash scripts/upstream_digest.sh --smg <smg checkout> (what changed upstream), /smg:sync (full resync). The same commit rules as SMG apply and are enforced by the PreToolUse hook: DCO sign-off, no AI attribution lines, branch names setup/feat/fix/docs/chore/refactor/<desc>."
fi
exit 0

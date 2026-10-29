#!/usr/bin/env bash
# Live map of the SMG checkout the agent is working in. Read-only and fast (well under a second).
# The map skill inlines this output, so the crate list, policy list and parser counts can never
# go stale: they are read from the checkout, not from the guide.
#
# Usage: map_live.sh [dir]     (dir defaults to the cwd; any directory inside an SMG checkout works)
set -u
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/lib/detect_smg.sh"

root="$(smg_root "${1:-$PWD}")" || {
  echo "(No SMG checkout found above ${1:-$PWD}. The live map is unavailable; the static sections below describe SMG as of the guide's last sync. Run this from inside an SMG checkout for a live view.)"
  exit 0
}

ver="$(smg_version "$root")"
head="$(smg_head "$root")"
branch="$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null)"
pin="$(guide_pin)"
pin_ver="$(guide_pin_version)"
drift=""
if [ -n "$pin" ]; then
  if git -C "$root" cat-file -e "$pin" 2>/dev/null; then
    n="$(git -C "$root" rev-list --count "$pin..HEAD" 2>/dev/null || echo '?')"
    drift="guide verified against ${pin:0:12} (v${pin_ver}); this checkout is ${n} commits past it"
  else
    drift="guide verified against ${pin:0:12} (v${pin_ver}); that commit is not in this checkout's history (shallow clone?), so drift is unknown"
  fi
fi

echo "### SMG checkout: $root"
echo "- version ${ver:-?}, HEAD ${head:-?}, branch ${branch:-?}"
[ -n "$drift" ] && echo "- $drift"
echo
echo "### Workspace crates (name, path, description from each Cargo.toml)"
echo
echo "| Package | Path | Description |"
echo "|---|---|---|"
sed -n '/^members *= *\[/,/\]/p' "$root/Cargo.toml" | grep -oE '"[^"]+"' | tr -d '"' | while read -r m; do
  mf="$root/$m/Cargo.toml"
  [ -f "$mf" ] || continue
  name="$(sed -nE 's/^name *= *"([^"]+)".*/\1/p' "$mf" | head -1)"
  desc="$(sed -nE 's/^description *= *"([^"]+)".*/\1/p' "$mf" | head -1)"
  echo "| \`${name:-?}\` | \`$m/\` | ${desc:-} |"
done
echo
echo "### model_gateway/src layout"
echo
echo "- directories: $(cd "$root/model_gateway/src" && ls -d */ 2>/dev/null | tr -d '/' | tr '\n' ' ')"
echo "- top-level files: $(cd "$root/model_gateway/src" && ls *.rs 2>/dev/null | tr '\n' ' ')"
echo "- routers/: $(ls "$root/model_gateway/src/routers" 2>/dev/null | tr '\n' ' ')"
echo "- endpoints/: $(ls "$root/model_gateway/src/endpoints" 2>/dev/null | tr '\n' ' ')"
echo "- middleware/: $(ls "$root/model_gateway/src/middleware" 2>/dev/null | tr '\n' ' ')"
echo "- service_discovery/: $(ls "$root/model_gateway/src/service_discovery" 2>/dev/null | tr '\n' ' ')"
echo
echo "### Routing policies (model_gateway/src/policies)"
echo
pols="$(cd "$root/model_gateway/src/policies" 2>/dev/null && ls *.rs | sed 's/\.rs$//' | grep -vE '^(mod|factory|registry|utils|test_support)$' | tr '\n' ' ')"
echo "- ${pols:-?}"
echo "- policy sub-modules: $(cd "$root/model_gateway/src/policies" 2>/dev/null && ls -d */ 2>/dev/null | tr -d '/' | tr '\n' ' ')"
echo
echo "### Parsers"
echo
if [ -d "$root/crates/symphony/src/formats" ]; then
  n_sym="$(ls "$root/crates/symphony/src/formats"/*.rs 2>/dev/null | grep -vE '/(mod|registry)\.rs$' | wc -l | tr -d ' ')"
  echo "- symphony format tables (default parser, \`--parser symphony\`): $n_sym — $(ls "$root/crates/symphony/src/formats"/*.rs | xargs -n1 basename | sed 's/\.rs$//' | grep -vE '^(mod|registry)$' | tr '\n' ' ')"
fi
[ -d "$root/crates/tool_parser/src/parsers" ] && echo "- legacy tool parsers (\`--parser legacy\`): $(ls "$root/crates/tool_parser/src/parsers"/*.rs | grep -v '/mod.rs$' | wc -l | tr -d ' ')"
[ -d "$root/crates/reasoning_parser/src/parsers" ] && echo "- legacy reasoning parsers: $(ls "$root/crates/reasoning_parser/src/parsers"/*.rs | grep -v '/mod.rs$' | wc -l | tr -d ' ')"
echo
echo "### CI and tooling"
echo
echo "- workflows: $(ls "$root/.github/workflows" 2>/dev/null | wc -l | tr -d ' ') files; PR Rust CI lanes: $(grep -hoE '^  [a-z0-9_-]+:$' "$root/.github/workflows/pr-test-rust.yml" 2>/dev/null | tr -d ' :' | tr '\n' ' ')"
echo "- make targets: $(grep -oE '^[a-zA-Z0-9_-]+:' "$root/Makefile" 2>/dev/null | tr -d ':' | tr '\n' ' ')"
echo "- e2e suites: $(ls "$root/e2e_test" 2>/dev/null | grep -vE '\.(py|toml)$' | tr '\n' ' ')"

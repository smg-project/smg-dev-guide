#!/usr/bin/env bash
# What changed in SMG since the guide was last verified. Feeds the sync skill: which recipes are
# most exposed to churn, which crates/dirs/workflows appeared or vanished, which files were renamed.
#
# Usage: upstream_digest.sh [--since <commit>] [--smg <root>] [--recipes <dir>] [--top N]
#   --since   defaults to the guide's pinned commit (smg-ref.json)
#   --smg     defaults to the SMG checkout above the cwd
#   --recipes defaults to <guide>/skills/implement/recipes
set -u
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/lib/detect_smg.sh"

since=""; root=""; recipes=""; top=25
while [ $# -gt 0 ]; do
  case "$1" in
    --since) since="$2"; shift 2;;
    --smg) root="$2"; shift 2;;
    --recipes) recipes="$2"; shift 2;;
    --top) top="$2"; shift 2;;
    -h|--help) sed -n '2,9p' "$0"; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
root="${root:-$(smg_root "$PWD")}" || { echo "no SMG checkout found; pass --smg" >&2; exit 2; }
since="${since:-$(guide_pin)}"
[ -n "$since" ] || { echo "no --since and no pin in smg-ref.json" >&2; exit 2; }
recipes="${recipes:-$(guide_root)/skills/implement/recipes}"

if ! git -C "$root" cat-file -e "${since}^{commit}" 2>/dev/null; then
  echo "Commit $since is not in this checkout's history. Deepen it first, e.g.:"
  echo "  git -C $root fetch --shallow-since=$(sed -nE 's/.*"verified_date" *: *"([^"]+)".*/\1/p' "$(guide_root)/smg-ref.json" | head -1) origin main"
  exit 2
fi

head="$(smg_head "$root")"
echo "## SMG upstream digest: ${since:0:12}..${head}"
echo
echo "- commits: $(git -C "$root" rev-list --count "$since..HEAD")"
echo "- version: $(git -C "$root" show "$since:model_gateway/Cargo.toml" 2>/dev/null | sed -nE 's/^version *= *"([^"]+)".*/\1/p' | head -1) -> $(smg_version "$root")"
echo
echo "### Commits by type"
echo
git -C "$root" log --format='%s' "$since..HEAD" | sed -E 's/^([a-z]+)(\([^)]*\))?!?:.*/\1/' | sort | uniq -c | sort -rn | awk '{printf "- %s: %s\n", $2, $1}'
echo
echo "### Top scopes"
echo
git -C "$root" log --format='%s' "$since..HEAD" | sed -nE 's/^[a-z]+\(([^)]*)\)!?:.*/\1/p' | sort | uniq -c | sort -rn | head -n "$top" | awk '{printf "- %s: %s\n", $2, $1}'
echo
echo "### Workspace members added / removed"
echo
old_members="$(git -C "$root" show "$since:Cargo.toml" 2>/dev/null | sed -n '/^members *= *\[/,/\]/p' | grep -oE '"[^"]+"' | tr -d '"' | grep -vE '^[0-9.]+$' | sort)"
new_members="$(sed -n '/^members *= *\[/,/\]/p' "$root/Cargo.toml" | grep -oE '"[^"]+"' | tr -d '"' | grep -vE '^[0-9.]+$' | sort)"
added="$(comm -13 <(echo "$old_members") <(echo "$new_members"))"
removed="$(comm -23 <(echo "$old_members") <(echo "$new_members"))"
[ -n "$added" ] && echo "$added" | sed 's/^/- added: /'
[ -n "$removed" ] && echo "$removed" | sed 's/^/- removed: /'
[ -z "$added$removed" ] && echo "- none"
echo
echo "### Top-level source directories added / removed"
echo
for base in model_gateway/src crates; do
  old_dirs="$(git -C "$root" ls-tree --name-only "$since" "$base/" 2>/dev/null | sort)"
  new_dirs="$(git -C "$root" ls-tree --name-only HEAD "$base/" 2>/dev/null | sort)"
  comm -13 <(echo "$old_dirs") <(echo "$new_dirs") | sed 's/^/- added: /'
  comm -23 <(echo "$old_dirs") <(echo "$new_dirs") | sed 's/^/- removed: /'
done
echo
echo "### Renamed or deleted source files (first 120)"
echo
git -C "$root" diff --name-status -M --diff-filter=RD "$since..HEAD" -- 'model_gateway/src' 'crates/*/src' 'bindings' 'e2e_test' '.github/workflows' 'scripts' 2>/dev/null | head -120 | awk '{ if ($1 ~ /^R/) printf "- renamed: %s -> %s\n", $2, $3; else printf "- deleted: %s\n", $2 }'
echo
echo "### CI workflows added / removed"
echo
old_wf="$(git -C "$root" ls-tree --name-only "$since" .github/workflows/ 2>/dev/null | sort)"
new_wf="$(git -C "$root" ls-tree --name-only HEAD .github/workflows/ 2>/dev/null | sort)"
comm -13 <(echo "$old_wf") <(echo "$new_wf") | sed 's/^/- added: /'
comm -23 <(echo "$old_wf") <(echo "$new_wf") | sed 's/^/- removed: /'
echo
echo "### Churn per recipe (commits touching each recipe's \`watch\` paths since its own \`verified\` commit, else since $since)"
echo
echo "| Recipe | Verified at | Commits since | Watch paths |"
echo "|---|---|---|---|"
for r in "$recipes"/*.md; do
  [ -f "$r" ] || continue
  name="$(basename "$r" .md)"
  verified="$(awk '/^---$/{c++; next} c==1 && /^verified:/{sub(/^verified:[ ]*/, ""); print; exit}' "$r")"
  mapfile -t watch < <(awk '/^---$/{c++; next} c==1 && /^watch:/{w=1; next} c==1 && w && /^[ ]+- /{sub(/^[ ]+- /, ""); print; next} c==1 && w && !/^[ ]+- /{w=0}' "$r")
  base="$since"
  if [ -n "$verified" ] && git -C "$root" cat-file -e "${verified}^{commit}" 2>/dev/null; then base="$verified"; fi
  if [ ${#watch[@]} -gt 0 ]; then
    n="$(git -C "$root" rev-list --count "$base..HEAD" -- "${watch[@]}" 2>/dev/null || echo '?')"
  else
    n="(no watch list)"
  fi
  echo "| $name | ${verified:-$since} | $n | $(printf '%s ' "${watch[@]}") |"
done

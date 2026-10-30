#!/usr/bin/env bash
# Apply the agent-orientation drafts to an SMG checkout: copy AGENTS.md and CLAUDE.md to the root
# and prepend a `//!` header to the four entry files that have none. Idempotent: a file that
# already starts with `//!` is left alone. Review the diff before committing.
#
#   bash upstream/smg/apply.sh /path/to/smg
set -euo pipefail
smg="${1:?usage: apply.sh <smg checkout>}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
[ -f "$smg/model_gateway/Cargo.toml" ] || { echo "not an SMG checkout: $smg" >&2; exit 2; }
cp "$here/AGENTS.md" "$smg/AGENTS.md"
cp "$here/CLAUDE.md" "$smg/CLAUDE.md"
echo "copied AGENTS.md and CLAUDE.md"
declare -A targets=(
  ["main.rs.header"]="model_gateway/src/main.rs"
  ["config-mod.rs.header"]="model_gateway/src/config/mod.rs"
  ["server.rs.header"]="model_gateway/src/server.rs"
  ["app_context.rs.header"]="model_gateway/src/app_context.rs"
)
for h in "${!targets[@]}"; do
  f="$smg/${targets[$h]}"
  if head -1 "$f" | grep -q '^//!'; then echo "skip ${targets[$h]}: already documented"; continue; fi
  { cat "$here/module-docs/$h"; echo; cat "$f"; } > "$f.tmp" && mv "$f.tmp" "$f"
  echo "documented ${targets[$h]}"
done
echo "now: cargo +nightly fmt --all && git diff --stat"

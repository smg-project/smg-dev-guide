#!/usr/bin/env bash
# The scope derivation gate.sh relies on (scripts/crate_scope.py), run against a fixture workspace:
# two member crates, a nested manifest that is no member, and the root files that widen the scope.
#
#   bash scripts/tests/crate_scope_test.sh        # exit 1 on the first mismatch set
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
tmp="$(mktemp -d)"
trap 'rm -r -- "$tmp"' EXIT

mkdir -p "$tmp/.cargo" "$tmp/crates/alpha/src" "$tmp/crates/alpha/fuzz/fuzz_targets" "$tmp/tools/beta/src" "$tmp/docs"
printf '[workspace]\nmembers = ["crates/*", "tools/beta"]\nresolver = "2"\n' > "$tmp/Cargo.toml"
printf '[package]\nname = "alpha-lib"\nversion = "0.1.0"\n' > "$tmp/crates/alpha/Cargo.toml"
printf '[package]\nname = "alpha-fuzz"\nversion = "0.0.0"\n\n[workspace]\nmembers = ["."]\n' > "$tmp/crates/alpha/fuzz/Cargo.toml"
printf '[package]\nname = "beta"\nversion = "0.1.0"\n' > "$tmp/tools/beta/Cargo.toml"
: > "$tmp/Cargo.lock"
: > "$tmp/.cargo/config.toml"
: > "$tmp/docs/guide.md"

fails=0
expect() {  # expect <case> <expected output, space-joined> [--format args] -- <changed files...>
  local name="$1" want="$2"; shift 2
  local fmt=()
  if [ "${1:-}" = "--format" ]; then fmt=(--format "$2"); shift 2; fi
  [ "${1:-}" = "--" ] && shift
  local got
  got="$(printf '%s\n' "$@" | python3 "$here/../crate_scope.py" --smg "$tmp" ${fmt[@]+"${fmt[@]}"} - | tr '\n' ' ' | sed 's/ $//')"
  if [ "$got" = "$want" ]; then printf 'PASS  %s: %s\n' "$name" "${got:-(nothing)}"
  else printf 'FAIL  %s: want "%s", got "%s"\n' "$name" "$want" "$got"; fails=$((fails + 1)); fi
}

expect "one file in one crate"                         "alpha-lib"      -- crates/alpha/src/lib.rs
expect "files in two crates: each once, sorted"        "alpha-lib beta" -- tools/beta/src/main.rs crates/alpha/src/lib.rs crates/alpha/README.md
expect "a nested manifest that is no member climbs"    "alpha-lib"      -- crates/alpha/fuzz/fuzz_targets/parse.rs
expect "Cargo.lock widens to the workspace"            "workspace"      -- crates/alpha/src/lib.rs Cargo.lock
expect ".cargo/ widens to the workspace"               "workspace"      -- .cargo/config.toml
expect "the workspace manifest widens"                 "workspace"      -- Cargo.toml
expect "files outside every crate add nothing"         ""               -- docs/guide.md README.md
expect "--format args prints the -p list"              "-p alpha-lib -p beta" --format args -- crates/alpha/src/lib.rs tools/beta/Cargo.toml

if [ "$fails" -gt 0 ]; then echo "crate_scope_test: $fails failure(s)"; exit 1; fi
echo "crate_scope_test: all cases pass"

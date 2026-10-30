#!/usr/bin/env bash
# The SMG pre-PR gate as one command. Mirrors CONTRIBUTING.md ("The pre-PR gate") and what
# .github/workflows/pr-test-rust.yml and pr-naming-check.yml enforce, so an agent runs this once,
# reads a PASS/FAIL table, and fixes what failed instead of reciting the checks from memory.
#
# Usage: gate.sh [--fix] [--skip-tests] [--only STEPS] [--base REF] [--dry-run]
#   --fix         let rustfmt / ruff / pre-commit rewrite files instead of only checking
#   --skip-tests  skip `cargo test` (fine while iterating; never for the last run before a push)
#   --only STEPS  comma list from: fmt,clippy,test,hooks,python,go,lock,vocab,names,lanes   (default: all)
#   --base REF    base for change detection and commit checks (default: origin/main)
#   --dry-run     print the commands each step would run and exit
# Env:
#   GATE_TEST_ARGS   extra args for cargo test, e.g. "-p smg" to scope a slow iteration
#
# Exit status: 0 when every applicable step passed, 1 otherwise.
set -u
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/lib/detect_smg.sh"

fix=0; skip_tests=0; only=""; base="origin/main"; dry=0
while [ $# -gt 0 ]; do
  case "$1" in
    --fix) fix=1;;
    --skip-tests) skip_tests=1;;
    --only) only="$2"; shift;;
    --base) base="$2"; shift;;
    --dry-run) dry=1;;
    -h|--help) sed -n '2,16p' "$0"; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
  shift
done

root="$(smg_root "$PWD")" || { echo "gate.sh: run this inside an SMG checkout" >&2; exit 2; }
cd "$root" || exit 2
guide="$(guide_root)"
branch_regex="$(python3 "$guide/scripts/rules.py" smg branch_regex 2>/dev/null)"
title_regex="$(python3 "$guide/scripts/rules.py" smg pr_title_regex 2>/dev/null)"
ai_regex="$(python3 "$guide/scripts/rules.py" smg ai_trailer_regex 2>/dev/null)"
body_headers="$(python3 "$guide/scripts/rules.py" smg pr_body_headers 2>/dev/null)"

want() { [ -z "$only" ] || [[ ",$only," == *",$1,"* ]]; }
results=(); notes=()
record() { results+=("$1|$2"); notes+=("${3:-}"); }

# Changed files relative to the base (committed + staged + unstaged), for lane applicability.
merge_base="$(git merge-base "$base" HEAD 2>/dev/null || true)"
if [ -n "$merge_base" ]; then
  changed="$( { git diff --name-only "$merge_base" HEAD; git diff --name-only; git diff --name-only --cached; } 2>/dev/null | sort -u)"
  detect_note=""
else
  changed="$(git ls-files)"
  detect_note="(base $base not found: treating every file as changed)"
fi
touched() { printf '%s\n' "$changed" | grep -qE "$1"; }

run() {  # run <step> <description> <command...>
  local step="$1" desc="$2"; shift 2
  if [ "$dry" = 1 ]; then printf '%-8s %s\n   $ %s\n' "$step" "$desc" "$*"; return 0; fi
  echo; echo "==> [$step] $desc"; echo "    $ $*"
  local start; start=$(date +%s)
  if "$@"; then record "$step" PASS "$desc ($(( $(date +%s) - start ))s)"; return 0
  else record "$step" FAIL "$desc"; return 1; fi
}
skip() { record "$1" SKIP "$2"; [ "$dry" = 1 ] && printf '%-8s SKIP: %s\n' "$1" "$2"; return 0; }
need() { command -v "$1" >/dev/null 2>&1; }

# 1. fmt ---------------------------------------------------------------------------------------
if want fmt; then
  if ! need cargo; then skip fmt "cargo not installed"; else
    if [ "$fix" = 1 ]; then run fmt "rustfmt (rewriting)" cargo +nightly fmt --all
    else run fmt "rustfmt --check" cargo +nightly fmt --all -- --check; fi
    if [ -f crates/symphony/fuzz/Cargo.toml ]; then
      if [ "$fix" = 1 ]; then run fmt "rustfmt symphony fuzz workspace (rewriting)" cargo +nightly fmt --manifest-path crates/symphony/fuzz/Cargo.toml --all
      else run fmt "rustfmt symphony fuzz workspace --check" cargo +nightly fmt --manifest-path crates/symphony/fuzz/Cargo.toml --all -- --check; fi
    fi
  fi
fi

# 2. clippy ------------------------------------------------------------------------------------
if want clippy; then
  if ! need cargo; then skip clippy "cargo not installed"; else
    if (need pkg-config && pkg-config --exists opencv4 2>/dev/null) || [ -d /usr/include/opencv4 ] || [ -d /usr/local/include/opencv4 ] || [ -d /opt/homebrew/include/opencv4 ]; then
      run clippy "clippy, all features (what the all-features CI leg runs)" cargo clippy --workspace --all-targets --all-features -- -D warnings
    else
      run clippy "clippy, default features (no system OpenCV here; CI's all-features leg also lints the opencv-video feature: install with bash scripts/install_opencv.sh)" cargo clippy --workspace --all-targets -- -D warnings
    fi
  fi
fi

# 3. test --------------------------------------------------------------------------------------
if want test; then
  if [ "$skip_tests" = 1 ]; then skip test "--skip-tests given; run without it before pushing"
  elif ! need cargo; then skip test "cargo not installed"
  else
    if touched '^(crates/wasm/|examples/wasm/)' && [ -f crates/wasm/tests/fixtures/build_fixtures.sh ]; then
      run test "build WASM guest fixtures (wasm paths changed; without them the guest tests skip silently)" bash crates/wasm/tests/fixtures/build_fixtures.sh || true
    fi
    # shellcheck disable=SC2086
    run test "cargo test ${GATE_TEST_ARGS:-}" cargo test ${GATE_TEST_ARGS:-}
  fi
fi

# 4. hooks -------------------------------------------------------------------------------------
if want hooks; then
  if need pre-commit; then
    SKIP="rustfmt,rustfmt-symphony-fuzz,clippy,dco-check,branch-name-check,no-ai-co-author" \
      run hooks "pre-commit run --all-files (codespell, whitespace, yaml/toml, symlinks, ruff; rustfmt/clippy already ran above)" pre-commit run --all-files --show-diff-on-failure
  else
    skip hooks "pre-commit not installed (pip install pre-commit && pre-commit install && pre-commit install --hook-type commit-msg)"
  fi
fi

# 5. python ------------------------------------------------------------------------------------
if want python; then
  if touched '^(model_gateway/src/config/|crates/protocols/|bindings/|e2e_test/|scripts/|grpc_servicer/)'; then
    if need ruff; then
      run python "ruff check e2e_test/ bindings/python/ scripts/" ruff check e2e_test/ bindings/python/ scripts/
      if [ "$fix" = 1 ]; then run python "ruff format" ruff format e2e_test/ bindings/python/ scripts/
      else run python "ruff format --check" ruff format --check e2e_test/ bindings/python/ scripts/; fi
    else skip python "ruff not installed (pip install ruff)"; fi
    if need mypy; then
      run python "mypy e2e_test/" mypy e2e_test/ --config-file mypy.ini
      run python "mypy bindings/python/" mypy bindings/python/ --config-file mypy.ini
    else skip python "mypy not installed (pip install mypy)"; fi
    if need pytest; then
      PYTHONPATH=e2e_test run python "e2e harness unit tests (CPU gate)" pytest -q --noconftest e2e_test/infra e2e_test/fixtures
    else skip python "pytest not installed"; fi
    if touched '^(model_gateway/src/config/|crates/protocols/|bindings/python/)'; then
      if need maturin; then
        run python "make python-dev (rebuild the wheel: a new config field must reach Router/router_args.py)" make python-dev
        if need pytest; then
          ( cd bindings/python && run python "bindings unit tests with coverage gate" pytest -q tests --cov=smg --cov-config=.coveragerc --cov-fail-under=80 )
        fi
      else skip python "maturin not installed (pip install maturin); CI's build-wheel + python-unit-tests jobs will run it"; fi
    fi
  else
    skip python "no python-lane paths changed (config/, protocols/, bindings/, e2e_test/, scripts/, grpc_servicer/)"
  fi
fi

# 6. go ----------------------------------------------------------------------------------------
if want go; then
  if touched '^bindings/golang/'; then
    if need go; then run go "Go SDK tests" make -C bindings/golang test; else skip go "go not installed"; fi
  else skip go "bindings/golang/ unchanged"; fi
fi

# 7. lock --------------------------------------------------------------------------------------
if want lock; then
  if touched '(^|/)Cargo\.toml$'; then
    if need cargo; then run lock "Cargo.lock is in sync (CI runs cargo metadata --locked first)" cargo metadata --locked --format-version 1 --quiet >/dev/null
    else skip lock "cargo not installed"; fi
    if ! touched '^Cargo\.lock$' && [ "$dry" = 0 ]; then record lock WARN "a Cargo.toml changed but Cargo.lock did not; if cargo updated it, stage it (it is tracked)"; fi
  else skip lock "no Cargo.toml changed"; fi
fi

# 8. vocabulary --------------------------------------------------------------------------------
if want vocab; then
  if [ -n "$merge_base" ] && command -v python3 >/dev/null 2>&1; then
    if [ "$dry" = 1 ]; then printf '%-8s vocabulary (PD terms, generated-sounding prose) over the diff and commit messages\n   $ git diff %s | python3 %s/scripts/check_vocabulary.py --diff --strict\n' vocab "$merge_base" "$guide"; else
      vout="$( { git diff "$merge_base" --; git diff --cached; } | python3 "$guide/scripts/check_vocabulary.py" --diff --strict --quiet-warn 2>&1; echo "rc=$?")"
      cout="$(python3 "$guide/scripts/check_vocabulary.py" --commits "$merge_base..HEAD" --strict --quiet-warn 2>&1; echo "rc=$?")"
      echo "$vout" | grep -E '^(ERROR|WARN)' | head -20; echo "$cout" | grep -E '^(ERROR|WARN)' | head -10
      if echo "$vout$cout" | grep -q 'rc=1'; then record vocab FAIL "a term SMG's docs reject (PD 'leg' / 'arm'): see data/vocabulary.json in the guide and CONTRIBUTING.md"
      elif echo "$vout$cout" | grep -qE 'WARN|[1-9][0-9]* warn-level'; then record vocab WARN "generated-sounding wording flagged above; reword or justify"
      else record vocab PASS "no banned terms in the diff or commit messages"; fi
    fi
  else skip vocab "no merge base or python3"; fi
fi

# 9. names -------------------------------------------------------------------------------------
if want names; then
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
  if [ "$dry" = 1 ]; then printf '%-8s branch/commit/PR-title rules from data/rules.json (no command; checked in-script)\n' names; else
    ok=1
    if [ "$branch" = "main" ] || [ "$branch" = "master" ]; then
      record names FAIL "on $branch: SMG's pre-commit forbids committing to it; create <type>/<desc>"; ok=0
    elif [ -n "$branch_regex" ] && ! [[ "$branch" =~ $branch_regex ]]; then
      record names FAIL "branch '$branch' must match <type>/<desc> or <username>/<desc> (CI closes the PR otherwise)"; ok=0
    fi
    name="$(git config --get user.name || true)"; email="$(git config --get user.email || true)"
    if [ -n "$merge_base" ]; then
      while read -r sha; do
        [ -z "$sha" ] && continue
        subj="$(git log -1 --format=%s "$sha")"; body="$(git log -1 --format=%B "$sha")"
        if [ -n "$title_regex" ] && ! [[ "$subj" =~ $title_regex ]]; then
          record names FAIL "commit ${sha:0:10} subject is not conventional: '$subj'"; ok=0; fi
        if ! grep -qxF "Signed-off-by: $name <$email>" <<<"$body"; then
          record names FAIL "commit ${sha:0:10} lacks 'Signed-off-by: $name <$email>' (git commit -s; must match git config exactly)"; ok=0; fi
        if [ -n "$ai_regex" ] && grep -qiE "$ai_regex" <<<"$body"; then
          record names FAIL "commit ${sha:0:10} carries an AI attribution trailer; CI rejects it"; ok=0; fi
      done < <(git rev-list --no-merges "$merge_base..HEAD")
    else
      record names WARN "could not resolve $base; commit messages not checked"
    fi
    [ "$ok" = 1 ] && record names PASS "branch '$branch' and $(git rev-list --count --no-merges "${merge_base:-HEAD}..HEAD" 2>/dev/null || echo 0) commit(s) follow the naming, DCO and attribution rules"
    record names INFO "PR title regex: $title_regex ; PR body headers: $body_headers"
  fi
fi

# 10. lanes ------------------------------------------------------------------------------------
if want lanes && [ "$dry" = 0 ] && command -v python3 >/dev/null 2>&1; then
  lanes_out="$(printf '%s\n' "$changed" | xargs -r python3 "$guide/scripts/lanes.py" 2>/dev/null | tail -3 | tr '\n' ' ')"
  [ -n "$lanes_out" ] && record lanes INFO "$lanes_out"
fi

[ "$dry" = 1 ] && exit 0
echo; echo "================ SMG pre-PR gate ================"
[ -n "$detect_note" ] && echo "$detect_note"
fail=0
for i in "${!results[@]}"; do
  IFS='|' read -r step status <<<"${results[$i]}"
  printf '%-8s %-5s %s\n' "$step" "$status" "${notes[$i]}"
  [ "$status" = FAIL ] && fail=1
done
echo "================================================="
if [ "$fail" = 1 ]; then echo "RESULT: FAIL — fix the FAIL rows above and re-run. Do not open the PR yet."; exit 1
else echo "RESULT: PASS — paste this table under the PR's Test Plan; SKIP rows name what CI still runs for you; the lanes row says which."; exit 0; fi

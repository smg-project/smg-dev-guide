---
name: contribute
description: Ship a change to the SMG repository. Use before committing, pushing or opening a PR, and when asked "am I ready to submit". Runs the whole pre-PR gate as one command (fmt, clippy, tests, pre-commit, Python/Go lanes, Cargo.lock, vocabulary, branch/commit rules) and names what CI will still run.
---

# SMG Contribution Gate

**Rule:** no PR without the gate's table from this session. "Should pass" is not output.

## Run it

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh"                          # from anywhere inside the SMG checkout
bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh" --fix                    # let rustfmt / ruff / pre-commit rewrite files
bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh" --skip-tests --only fmt,clippy,vocab,names   # while iterating
GATE_TEST_ARGS="--lib" bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh" --only test           # narrow the test run further
bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh" --scope workspace        # clippy and tests on every crate (CI's clippy; main's whole test matrix)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh" --dry-run                # print the gate's scope (the wasm-example rule included) and the commands instead of running them
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/crate_scope.py"                # the crates your diff touches by their paths; `--dry-run` above shows the gate's own scope
```

The last run before a push is a plain `gate.sh`. It prints one row per step (`fmt`, `clippy`, `test`, `hooks`, `python`, `go`, `lock`, `vocab`, `names`, `lanes`): **PASS**, **FAIL** (fix and re-run), **WARN** (generated-sounding wording or a missing `Cargo.lock` change: reword or stage), **SKIP** (a tool you lack; CI runs that lane, so say so in the PR), **INFO** (the PR-title regex, the lanes this diff triggers). The `clippy` and `test` rows are **scoped to the crates the diff touches**: the package whose `Cargo.toml` is the nearest ancestor of each changed file, one `-p` per crate, named in the row (`2 crates: smg, smg-symphony`). A change to the workspace `Cargo.toml`, `Cargo.lock`, `.cargo/`, `clippy.toml` or `rust-toolchain.toml` widens both rows to the whole workspace, `--scope workspace` asks for that explicitly, and a diff under no crate skips them. The whole-workspace runs are CI's, never the gate's: `rust-lint` runs clippy on every crate for every pull request; `rust-tests` runs the test shards a pull request's paths can affect (`detect-changes` picks them) and every shard on main. `fmt` stays workspace-wide because it costs seconds. The steps follow `CONTRIBUTING.md` ("The pre-PR gate"), whose table still names the workspace-wide clippy and test forms: the gate scopes those two rows on the maintainers' direction, and `--scope workspace` gives the table's form. Without the script, run that section's commands by hand in the same order, with `-p` for the crates you touched. Paste the table under the PR's `## Test Plan`.

## Rules SMG's CI enforces

<!-- render:rules -->
- **Branch**: <type>/<description> or <username>/<description>; regex `^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?(/[a-zA-Z0-9._-]+)+$`. Never commit on `main`, `master` (pre-commit `no-commit-to-branch`); CI closes PRs from other branch names.
- **Commit subject**: `type(scope): summary` with type in `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `perf`, `lint`, `style`, `revert`, `build`, lowercase scope.
- **DCO**: `git commit -s`; the `Signed-off-by` trailer must equal `git config user.name <user.email>` exactly (`scripts/dco-check.sh`). Never `--no-verify`.
- **No AI attribution**: a `Co-authored-by` or `Signed-off-by` line matching `^(Co-authored-by|Signed-off-by):.*(Claude|noreply@anthropic\.com)` fails the `no-ai-co-author` hook and CI.
- **PR title**: regex `^(feat|fix|chore|docs|refactor|test|ci|perf|lint|style|revert|build)(\([a-z0-9_./-]+\))?!?: .+`.
- **PR body**: the template headers `## Description`, `### Problem`, `### Solution`, `## Changes`, `## Test Plan`, each filled; the review bot posts the gaps otherwise.
<!-- /render -->

Clippy and style rules live upstream: `Cargo.toml [workspace.lints]`, `clippy.toml`, and smg-docs `code-style.md`. The four that surprise: `#[expect(lint, reason = "...")]` not `#[allow]`; `tracing` not `println!`; `Uuid::now_v7` not `new_v4`; HTTP clients only through the crate's client factory, never `reqwest::Client::new` (the TLS provider is installed there). `tokio::spawn` only for tasks that may die at shutdown, justified at the call site.

## The three agent rules (CONTRIBUTING.md)

1. You own the PR, not the agent: read every line before opening.
2. Show the gate output; paste real `cargo fmt` / `clippy` / `test` output.
3. No AI attribution in commits, PR bodies or review replies.

## Non-negotiables

- A `Cargo.toml` change ships with its `Cargo.lock` diff (CI starts every Rust job with `cargo metadata --locked`).
- A new `RouterConfig` field ships with its Python chain (the gate runs the lane whenever config, protocols or bindings changed).
- Reviewers run `smg:review-pr`; run it on your own diff first, then `smg:craft`'s review questions.

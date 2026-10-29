---
name: contribute
description: Ship a change to the SMG repository — run the pre-PR quality gate (rustfmt, clippy, tests, pre-commit, Python/Go lanes, Cargo.lock, branch/commit/PR-title rules) as one command and fix what fails. Use before committing, pushing or opening a PR, and when asked "am I ready to submit".
---

# SMG Contribution Gate

## The rule

```
NO PR WITHOUT THE GATE'S OUTPUT IN THIS SESSION
```

"Should pass" and "looks clean" are not output. Run the gate, paste its table, fix every FAIL.

## Run the gate

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh"            # from anywhere inside the SMG checkout
bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh" --fix      # let rustfmt / ruff / pre-commit rewrite files
bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh" --skip-tests --only fmt,clippy,names   # while iterating
GATE_TEST_ARGS="-p smg" bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh" --only test    # scope a slow test run
bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh" --dry-run  # show the commands without running them
```

The final run before a push is a plain `gate.sh` (no `--skip-tests`, no `--only`). It prints one row per step:

| Step | What runs | Expected |
|---|---|---|
| fmt | `cargo +nightly fmt --all -- --check` (+ the `crates/symphony/fuzz` workspace) | no diff |
| clippy | `cargo clippy --workspace --all-targets --all-features -- -D warnings` (drops `--all-features` when system OpenCV is absent; CI's `all-features` leg still runs it: `bash scripts/install_opencv.sh`) | zero warnings |
| test | `cargo test` (builds WASM guest fixtures first when `crates/wasm/` or `examples/wasm/` changed) | `test result: ok` |
| hooks | `pre-commit run --all-files` minus the steps already run | every hook Passed |
| python | when `config/`, `crates/protocols/`, `bindings/`, `e2e_test/`, `scripts/` or `grpc_servicer/` changed: `ruff check` + `ruff format --check` on `e2e_test/ bindings/python/ scripts/`, `mypy` on `e2e_test/` and `bindings/python/`, the CPU harness tests, `make python-dev` + bindings tests at ≥ 80 % coverage when bindings/config/protocols changed | clean, tests pass |
| go | `make -C bindings/golang test` when `bindings/golang/` changed | pass |
| lock | `cargo metadata --locked` when a `Cargo.toml` changed (CI starts every Rust job with it) | `Cargo.lock` staged and in sync |
| names | branch, commit subjects, DCO trailers, no AI attribution (rules below) | PASS |

SKIP rows name a tool you lack; CI will run that lane for you, so say so in the PR. Without this plugin's scripts (other agent runtimes), run the commands in the table by hand in the same order — they mirror `CONTRIBUTING.md` ("The pre-PR gate") and `.github/workflows/pr-test-rust.yml`.

## Branch, commit and PR rules (what SMG's CI enforces)

- **Branch**: `<type>/<desc>` or `<username>/<desc>` — regex `^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?(/[a-zA-Z0-9._-]+)+$` (`.github/workflows/pr-naming-check.yml`); CI comments on and closes PRs that do not match. Never commit on `main` (pre-commit `no-commit-to-branch`).
- **Commits**: conventional subject; DCO trailer `Signed-off-by: <user.name> <<user.email>>` matching git config exactly (`scripts/dco-check.sh`), so always `git commit -s`. No `Co-authored-by` / `Signed-off-by` line naming Claude or `noreply@anthropic.com` — the `no-ai-co-author` hook and CI reject it. Never `--no-verify`.
- **PR title**: `^(feat|fix|chore|docs|refactor|test|ci|perf|lint|style|revert|build)(\([a-z0-9_./-]+\))?!?: .+` — lowercase scope.
- **PR body**: the template headers `## Description`, `### Problem`, `### Solution`, `## Changes`, `## Test Plan`, each filled; the Claude review bot posts a gap list otherwise. Put the gate table under Test Plan.
- **Review**: Claude Code Review runs on every PR with this plugin's `review-pr` skill (`.github/workflows/claude-code-review.yml`); self-review with `smg:review-pr` first and expect the same checklist.

## Which CI lanes your change triggers

| You touched | Lanes that will run |
|---|---|
| Any Rust | `rust-lint` (legs `all-features`, `self-hosted`, `anthropic-only`, `default-build`), `rust-tests` (sharded), `cargo-audit`, `rust-aarch64`, `grpc-proto-build-check` |
| `config/`, `crates/protocols/`, `bindings/` | `build-wheel`, `python-unit-tests` (coverage gate 80 %) |
| `e2e_test/`, `bindings/python/`, `scripts/` | `python-lint` (ruff + mypy), `ci-tooling-tests.yml` |
| gRPC pipeline, `crates/engine_zmq_*`, `crates/mock_worker/` | `e2e-1gpu-chat-zmq`, `e2e-2gpu-chat-zmq-dp` |
| `crates/symphony/` | `e2e-1gpu-chat-symphony`, `symphony-fuzz.yml` |
| `crates/engine_servicer/` | `e2e-1gpu-chat-rust-servicer` |
| `crates/kv_index/`, `crates/radix_tree/` | `benchmark-radix-tree.yml`, `radix-tree-fuzz.yml` |
| `model_gateway/src/service_discovery/`, `e2e_test/discovery/` | `e2e-discovery.yml` (kind, consul, file, slurm) |
| `crates/multimodal/` | `rust-tests` regenerates vision golden fixtures; `e2e-1gpu-chat-mm-worker` |
| `crates/data_connector/` | `rust-tests` runs `cargo test -p data-connector --test postgres_integration -- --ignored` against a live Postgres |

## Clippy rules you will hit

Workspace lints live in `Cargo.toml` (`[workspace.lints]`) and `clippy.toml`; every warning is fatal under `-D warnings`.

| Rule | Meaning |
|---|---|
| `unwrap_used = "deny"` | no `.unwrap()` outside tests: `?`, `.ok_or()`, `.unwrap_or_else()` |
| `expect_used`, `panic` = warn | prefer `?` in production code |
| `todo`, `unimplemented`, `unreachable`, `dbg_macro` = deny | no placeholder or debug macros |
| `unsafe_code = "deny"`, `unused_qualifications = "warn"` | no `unsafe`; no needless path qualification |
| `allow_attributes = "warn"` | `#[expect(lint, reason = "...")]`, never `#[allow]` |
| `print_stdout` / `print_stderr` = warn | `tracing`, not `println!` |
| `uninlined_format_args`, `absolute_paths` (max 3 segments), `large_futures` (> 20 KB → `Box::pin`) | style lints that fail CI |
| disallowed `tokio::task::spawn` | only for tasks that may die at shutdown, justified with `#[expect(clippy::disallowed_methods, reason = "...")]`; otherwise keep and join the `JoinHandle` |
| disallowed `uuid::Uuid::new_v4` | `Uuid::now_v7` |
| disallowed `std::process::exit` | normal shutdown logic |
| disallowed `reqwest::Client::new` / `builder` / `get` (and the blocking forms) | build HTTP clients through the crate's client factory (gateway `clients` module, auth/MCP factories): it installs the TLS crypto provider first |
| cognitive complexity 25, type complexity 250 | split the function / name the type |

## Imports and errors

`rustfmt.toml` sets `group_imports = "StdExternalCrate"` and `imports_granularity = "Crate"`: std, then external crates, then `crate::` — `cargo +nightly fmt` produces it. Errors: `thiserror` enums for domain errors, `anyhow::Context` when wrapping (`parse(input).context("parsing model config")?`).

## Rationalization prevention

| Excuse | Reality |
|---|---|
| "Clippy is clean enough with a few warnings" | `-D warnings` means zero. |
| "I didn't change bindings, skip the python step" | A new `RouterConfig` field compiles and silently never reaches Python. The gate runs the lane whenever config/protocols changed. |
| "Cargo.lock is generated, don't commit it" | It is tracked; CI runs `cargo metadata --locked` before every Rust job. |
| "I'll rename the branch after review" | CI closes the PR first. |
| "It's just a docs change" | codespell and whitespace hooks still run; the title, branch and sign-off rules have no exemption. |
| "The reviewer bot will catch it" | It runs this plugin's checklist; a finding it posts is a round trip you could have skipped. |

## Red flags — stop

- Opening a PR without the gate table from this session
- `git commit` without `-s`, any `--no-verify`, a Claude/anthropic attribution trailer (the plugin's hook blocks these in SMG checkouts)
- A `Cargo.toml` change without the `Cargo.lock` diff
- Trusting a subagent's "tests pass" without the output

## Chaining

Before the PR: `smg:review-pr` on your own diff. While implementing: `smg:implement`. The gate or these rules were wrong: `smg:learn`.

---
name: contribute
description: Use when preparing to commit, open a PR, or check quality gates in the SMG repository — enforces verification before shipping
---

# SMG Contribution Workflow

## The Iron Law

```
NO PR WITHOUT PASSING ALL QUALITY GATES
```

If you haven't run the verification commands in this message, you cannot claim the code is ready.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Gate Function

```
BEFORE claiming code is ready, opening a PR, or committing:

1. FORMAT
   Run:      cargo +nightly fmt --all
   Expected: No output (silent success)
   If fails: Fix formatting, re-run

2. LINT
   Run:      cargo clippy --workspace --all-targets --all-features -- -D warnings
   Expected: No warnings, no errors
   Note:     --all-features enables multimodal's opencv-video, which links
             system OpenCV. One-time: bash scripts/install_opencv.sh (or
             make opencv-deps). Without it, drop --all-features.
   If fails: Fix all warnings, re-run

3. TEST
   Run:      cargo test
   Expected: "test result: ok" with 0 failures
   Note:     Touched any Cargo.toml? Stage the updated Cargo.lock — it is
             tracked, and every Rust CI job starts with cargo metadata --locked.
   Note:     Touched crates/wasm/ or examples/wasm/? Run
             bash crates/wasm/tests/fixtures/build_fixtures.sh first, or the
             guest integration tests skip silently.
   If fails: Fix failures, re-run

4. HOOKS
   Run:      pre-commit run --all-files
   Expected: every hook Passed — codespell, trailing-whitespace,
             end-of-file-fixer, check-yaml, check-toml, mixed-line-ending,
             ruff, ruff-format
   Setup:    pip install pre-commit && pre-commit install &&
             pre-commit install --hook-type commit-msg
   If fails: Take the hook's fixes, re-stage, re-run

5. PYTHON / GO (if config/types.rs, protocols/, bindings/, e2e_test/,
                scripts/ or grpc_servicer/ changed)
   Run:      make python-dev
   Run:      ruff check e2e_test/ bindings/python/ scripts/
             ruff format --check e2e_test/ bindings/python/ scripts/
   Run:      mypy e2e_test/ --config-file mypy.ini
             mypy bindings/python/ --config-file mypy.ini
   Run:      cd bindings/python && pytest -q tests --cov=smg
                 --cov-config=.coveragerc --cov-fail-under=80
   Run:      PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra e2e_test/fixtures
   Run:      cd bindings/golang && make test       (if bindings/golang/ changed)
   Expected: wheel builds; ruff/mypy clean; tests pass at >= 80% coverage
   If a new config field never reaches the bindings: add it to the Router
             pyclass and its to_router_config() builder chain in
             bindings/python/src/lib.rs, to RouterArgs in
             bindings/python/src/smg/router_args.py, and to Go ClientConfig.

6. NAMES AND COMMITS
   Verify:   Branch is <type>/<desc> or <username>/<desc> (e.g. feat/add-auth) —
             CI comments on and closes internal PRs that do not match
   Verify:   PR title is "type(scope): summary", scope lowercase — types
             feat/fix/docs/style/refactor/perf/test/chore/ci (PR titles also
             allow lint/revert/build); CI rejects any other title
   Verify:   Every commit DCO-signed (git commit -s), matching your git
             user.name/user.email exactly
   Verify:   No AI attribution — no Co-authored-by/Signed-off-by line naming
             Claude or noreply@anthropic.com, in commits, PR body, or review
             replies

Skip any step = not verified. Run ALL six.
```

## Clippy Rules You'll Hit

| Rule | Meaning |
|------|---------|
| `unwrap_used = "deny"` | No `.unwrap()`. Use `?`, `.ok_or()`, `.unwrap_or_else()` |
| `expect_used = "warn"`, `panic = "warn"` | Prefer `?` over `.expect()`/`panic!` in production code |
| `print_stdout/print_stderr = "warn"` | Use `tracing` crate, not `println!`/`eprintln!` |
| `todo/unimplemented/unreachable = "deny"`, `dbg_macro = "deny"` | No placeholder or debug macros |
| `unsafe_code = "deny"` (rust lints) | No `unsafe` outside crates that opt out |
| `allow_attributes = "warn"` | Use `#[expect(lint, reason = "...")]` not `#[allow]` |
| `uninlined_format_args = "warn"` | `format!("{x}")`, not `format!("{}", x)` |
| `absolute_paths = "warn"` (max 3 segments) | `use` the item; no inline `std::collections::HashMap::new()` |
| `large_futures = "warn"` (> 20 KB) | `Box::pin` an oversized future |
| Disallowed: `tokio::task::spawn` / `tokio::spawn` | Only for tasks that may die at shutdown — justify at the call site with `#[expect(clippy::disallowed_methods, reason = "...")]` (see `model_gateway/src/health.rs`); otherwise keep and join the `JoinHandle` |
| Disallowed: `uuid::Uuid::new_v4` | Use `now_v7` |
| Disallowed: `std::process::exit` | Use normal shutdown logic, not a hard process exit |

`clippy.toml` also caps cognitive complexity at 25 and type complexity at 250, and disallows the `unimplemented!` / `todo!` macros outright. Every lint above is fatal under `-D warnings`.

## Import Organization

`rustfmt.toml` sets `group_imports = "StdExternalCrate"` and `imports_granularity = "Crate"`, so step 1 produces this shape for you:

```rust
use std::collections::HashMap;              // 1. Standard library

use serde::{Deserialize, Serialize};        // 2. External crates
use tokio::sync::Mutex;

use crate::config::types::RouterConfig;     // 3. This crate
```

## Error Handling Pattern

```rust
use thiserror::Error;
use anyhow::Context;

#[derive(Error, Debug)]
pub enum MyError {
    #[error("failed to parse config: {0}")]
    ParseError(String),
}

// In functions: use ? with context
let value = parse(input).context("parsing model config")?;
```

## Where Things Live

| "I need to..." | Go to |
|-----------------|-------|
| Add CLI flag | `model_gateway/src/main.rs` (CliArgs) |
| Change config | `model_gateway/src/config/types.rs` |
| Change worker creation / registration | `model_gateway/src/worker/` (steps: `model_gateway/src/workflow/steps/{local,shared,external}/`, DAG in `steps/mod.rs`) |
| Change service discovery | `model_gateway/src/service_discovery.rs` |
| Change API types | `crates/protocols/src/` (careful — shared by all crates) |
| Add routing policy | `model_gateway/src/policies/` |
| Change request scheduling / admission | `model_gateway/src/middleware/scheduler/` |
| Change multi-tenancy | `model_gateway/src/tenant.rs`, `model_gateway/src/middleware/tenant_resolution.rs` |
| Change per-request concurrency / global token bucket | `model_gateway/src/middleware/concurrency.rs`, `model_gateway/src/middleware/token_bucket.rs` |
| Change per-tenant token/request rate limiting | `model_gateway/src/rate_limit/` (`RateLimitManager`, YAML policy via `--tenant-rate-limit-config`) |
| Add/modify a provider API | `model_gateway/src/routers/{openai,anthropic,gemini}/` |
| Change the ZMQ direct-backend path | wire structs `crates/engine_zmq_client/src/protocol/{vllm,tokenspeed}/` (append-only field order); translation `model_gateway/src/routers/grpc/zmq_client.rs` + `zmq_multimodal.rs`; dispatch `model_gateway/src/routers/grpc/backend_client.rs` (`BackendClient`, `ZmqDialect`) |
| Add tool parser | `crates/tool_parser/src/parsers/` |
| Add reasoning parser | `crates/reasoning_parser/src/parsers/` |
| Add tokenizer backend | `crates/tokenizer/src/factory.rs` (`TokenizerType`), implementing `crates/tokenizer/src/traits.rs` (`Tokenizer`); registration in `crates/tokenizer/src/registry.rs` |
| Add chat-template renderer | `crates/tokenizer/src/encoders/`, wired by `detect_renderer_from_config` in `crates/tokenizer/src/huggingface.rs` (DeepSeek) or `crates/tokenizer/src/tiktoken.rs` (Kimi); gateway autoload in `model_gateway/src/workflow/tokenizer_registration.rs` |
| Update Python bindings | `bindings/python/src/lib.rs` (`Router`) + `bindings/python/src/smg/router_args.py` (`RouterArgs`) |
| Update Go SDK | `bindings/golang/` (`ClientConfig` in `client.go`) |
| Regenerate client SDKs (after protocol changes) | `make generate-clients` (`clients/openapi-gen/`) — regenerates Python + Java types only; the Go SDK is hand-maintained |
| Add storage backend | `crates/data_connector/src/` (CI also runs `cargo test -p data-connector --test postgres_integration -- --ignored` against a live Postgres) |
| Launch engines / pick a connection mode | `bindings/python/src/smg/serve.py` (`--connection-mode grpc/http/zmq`; `_zmq_handshake_port` mirrors `zmq_client.rs::derive_handshake_port`) |
| Test routing without GPUs | `cargo run -p mock-worker -- --http-count N` / `--grpc-count N` / `--zmq-handshake <url> --zmq-count N` (`scripts/scale_test.sh`, `scripts/sim_ab.sh`) |
| Add E2E tests | `e2e_test/` (markers in `e2e_test/fixtures/hooks.py`; CPU-only harness tests in `e2e_test/infra/` and `e2e_test/fixtures/`) |
| Add WASM middleware | `examples/wasm/` (guests) + `crates/wasm/src/` (host) — build guests with `crates/wasm/tests/fixtures/build_fixtures.sh` (needs `rustup target add wasm32-wasip2`) |
| Add MCP tool support | `crates/mcp/src/` |
| Update user/contributor docs | the separate `smg-project/smg-docs` repo (`src/lib/content/`) — `docs/` and mkdocs were removed from smg; only the root Markdown (README, CONTRIBUTING, REVIEW, GOVERNANCE, CODE_OF_CONDUCT) lives here |

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Clippy is clean enough with a few warnings" | `-D warnings` means zero. One warning = not clean. |
| "I didn't change bindings, skip step 5" | A new config field compiles fine but silently never reaches Python/Go. Wire it through `Router`/`to_router_config` in `bindings/python/src/lib.rs`, `router_args.py`, and Go `ClientConfig`. Check. |
| "Cargo.lock is generated, don't commit it" | It is tracked, and CI runs `cargo metadata --locked` before every Rust job. Commit the diff. |
| "Only touched one file, don't need full gate" | The two-path config rule means a one-file change can silently break propagation. Run all six. |
| "Tests are slow, I'll run them later" | "Later" means shipping untested code. Run them now. |
| "It's just a docs change" | Step 4 still runs codespell and whitespace hooks over every file, and step 6 has no exemption for the PR title, branch name, or sign-off. |
| "I'll rename the branch after review starts" | CI comments and runs `gh pr close` on a badly named branch. Rename before you push. |

## Red Flags — STOP

- About to open a PR without running the gate function in this session
- Using "should pass" or "looks clean" without command output
- Skipping the bindings/Python check after config or protocol changes
- Changing a `Cargo.toml` without staging the updated `Cargo.lock`
- Pushing a branch that isn't `<type>/<desc>` or `<username>/<desc>`
- Committing without `-s` (DCO sign-off)
- Thinking "just this once" about any gate step
- Trusting a subagent's claim without verifying independently

## Skill Chaining

Before submitting, self-review with `smg:review-pr`.

When implementing features, use `smg:implement` for subsystem-specific guidance.

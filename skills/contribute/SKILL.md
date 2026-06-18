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
   If fails:  Fix formatting, re-run

2. LINT
   Run:      cargo clippy --workspace --all-targets --all-features -- -D warnings
   Expected: No warnings, no errors
   If fails:  Fix all warnings, re-run

3. TEST
   Run:      cargo test
   Expected: "test result: ok" with 0 failures
   If fails:  Fix failures, re-run

4. BINDINGS (if config/types.rs, protocols/, or bindings/ changed)
   Run:      make python-dev
   Expected: Successful compilation
   If fails:  Update struct literals, re-run

5. COMMIT FORMAT
   Verify:   Conventional commit (feat/fix/docs/refactor/test/perf/chore/ci)
   Verify:   DCO sign-off present (git commit -s)
   Verify:   No AI attribution

Skip any step = not verified. Run ALL five.
```

## Clippy Rules You'll Hit

| Rule | Meaning |
|------|---------|
| `unwrap_used = "deny"` | No `.unwrap()`. Use `?`, `.ok_or()`, `.unwrap_or_else()` |
| `expect_used = "warn"` | Prefer `?` over `.expect()` |
| `print_stdout/print_stderr = "warn"` | Use `tracing` crate, not `println!`/`eprintln!` |
| `todo/unimplemented/unreachable = "deny"` | No placeholder code |
| `allow_attributes = "warn"` | Use `#[expect(lint, reason = "...")]` not `#[allow]` |
| Disallowed: `tokio::task::spawn` | Use project's task spawning utilities |
| Disallowed: `uuid::Uuid::new_v4` | Use `now_v7` |
| Disallowed: `std::process::exit` | Use normal shutdown logic, not a hard process exit |

Disallowed macros (`clippy.toml`): `unimplemented!` and `todo!` — remove before merging to main.

## Import Organization

```rust
// 1. Standard library
use std::collections::HashMap;

// 2. External crates (alphabetically)
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex;

// 3. Internal crates
use crate::config::types::RouterConfig;
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
| Change worker creation | `model_gateway/src/worker/` (lifecycle steps: `model_gateway/src/workflow/steps/local/`) |
| Change service discovery | `model_gateway/src/service_discovery.rs` |
| Change API types | `crates/protocols/src/` (careful — shared by all crates) |
| Add routing policy | `model_gateway/src/policies/` |
| Change request scheduling / admission | `model_gateway/src/middleware/scheduler/` |
| Change multi-tenancy | `model_gateway/src/tenant.rs`, `model_gateway/src/middleware/tenant_resolution.rs` |
| Change rate limiting | `model_gateway/src/middleware/token_bucket.rs`, `model_gateway/src/middleware/concurrency.rs` |
| Add/modify a provider API | `model_gateway/src/routers/{openai,anthropic,gemini}/` |
| Add tool parser | `crates/tool_parser/src/parsers/` |
| Add reasoning parser | `crates/reasoning_parser/src/parsers/` |
| Update Python bindings | `bindings/python/src/lib.rs` |
| Update Go SDK | `bindings/golang/` |
| Regenerate client SDKs (after protocol changes) | `make generate-clients` (`clients/openapi-gen/`) — regenerates Python + Java types only; the Go SDK is hand-maintained |
| Add storage backend | `crates/data_connector/src/` |
| Add E2E tests | `e2e_test/` |
| Add WASM middleware | `examples/wasm/` (guests) + `crates/wasm/src/` (host) |
| Add MCP tool support | `crates/mcp/src/` |

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Clippy is clean enough with a few warnings" | `-D warnings` means zero. One warning = not clean. |
| "I didn't change bindings, skip step 4" | If you touched `config/types.rs` or `crates/protocols/`, the struct literal in `bindings/python/src/lib.rs` may need a default. Check. |
| "Only touched one file, don't need full gate" | The two-path config rule means a one-file change can silently break propagation. Run all five. |
| "Tests are slow, I'll run them later" | "Later" means shipping untested code. Run them now. |
| "It's just a docs change" | Even docs PRs need clean formatting and conventional commits. Steps 1 and 5 still apply. |

## Red Flags — STOP

- About to open a PR without running the gate function in this session
- Using "should pass" or "looks clean" without command output
- Skipping the bindings check after config changes
- Committing without `-s` (DCO sign-off)
- Thinking "just this once" about any gate step
- Trusting a subagent's claim without verifying independently

## Skill Chaining

Before submitting, self-review with `smg:review-pr`.

When implementing features, use `smg:implement` for subsystem-specific guidance.

---
name: review-pr
description: Review a pull request or diff in the SMG repository. Use for "review this PR", a PR number or URL, or a self-review before pushing. Maps changed files to per-subsystem checklists (with anti-patterns), applies the always-on error-handling, testing and craft sections, and reports REVIEW.md-severity findings with file:line.
---

# SMG PR Review

**Rule:** no verdict before every changed file is mapped to its checklists and each checklist is worked. `REVIEW.md` in SMG is the source of truth for markers and focus areas; this skill is the subsystem-aware procedure it points to.

## Process

```
FETCH   gh pr diff <number>   (or git diff <base>...HEAD)
MAP     list changed files → match the table below → read every matched checklist (they hold the
        anti-patterns too) BEFORE reading the diff in depth; sections 7–9 and the craft questions always apply
CHECK   work the checklists against the diff; read enough surrounding code to be sure
REPORT  one finding per bullet: 🔴 Important (bug, fix before merge) · 🟡 Nit · 🟣 Pre-existing;
        `path:line`; what is wrong, why it matters, the smallest fix; then counts per severity.
        A full review with zero 🔴 may approve. The PR body must carry the template headers
        (## Description, ### Problem, ### Solution, ## Changes, ## Test Plan).
```

## File-to-checklist mapping

<!-- render:review-mapping -->
| Files changed | Read these checklists | Lanes that run |
|---|---|---|
| `model_gateway/src/config/`, `model_gateway/src/main.rs`, `model_gateway/src/cli/` | `checklists/config.md` | `rust-lint`, `rust-tests`, `build-wheel`, `python-unit-tests` |
| `crates/protocols/` | `checklists/layering.md`, `checklists/config.md` | `rust-lint`, `rust-tests`, `grpc-proto-build-check`, `build-wheel` |
| `model_gateway/src/app_context.rs`, `model_gateway/src/server.rs`, `model_gateway/src/server/`, `model_gateway/src/health.rs` | `checklists/layering.md` | `rust-lint`, `rust-tests` |
| `model_gateway/src/policies/` | `checklists/routing.md` | `rust-lint`, `rust-tests`, `benchmarks` |
| `model_gateway/src/routers/` | `checklists/routing.md`, `checklists/layering.md` | `rust-lint`, `rust-tests`, `e2e-1gpu-chat`, `e2e-1gpu-chat-zmq` |
| `model_gateway/src/endpoints/` | `checklists/layering.md` | `rust-lint`, `rust-tests` |
| `model_gateway/src/middleware/scheduler/`, `model_gateway/src/middleware/concurrency.rs`, `model_gateway/src/middleware/token_bucket.rs` | `checklists/layering.md` | `rust-lint`, `rust-tests` |
| `model_gateway/src/rate_limit/`, `model_gateway/src/routers/grpc/common/stages/rate_limit.rs` | `checklists/layering.md` | `rust-lint`, `rust-tests` |
| `model_gateway/src/tenant/`, `model_gateway/src/middleware/tenant_resolution.rs`, `model_gateway/src/middleware/auth.rs` | `checklists/layering.md` | `rust-lint`, `rust-tests` |
| `crates/auth/` | `checklists/layering.md` | `rust-lint`, `rust-tests` |
| `model_gateway/src/service_discovery/` | `checklists/worker-lifecycle.md` | `rust-lint`, `rust-tests`, `e2e-discovery` |
| `model_gateway/src/worker/`, `model_gateway/src/workflow/` | `checklists/worker-lifecycle.md` | `rust-lint`, `rust-tests` |
| `crates/workflow/` | `checklists/worker-lifecycle.md` | `rust-lint`, `rust-tests` |
| `crates/symphony/` | `checklists/parsers.md` | `rust-lint`, `rust-tests`, `e2e-1gpu-chat-symphony`, `symphony-fuzz` |
| `crates/tool_parser/`, `crates/reasoning_parser/`, `crates/response_template/` | `checklists/parsers.md` | `rust-lint`, `rust-tests`, `benchmark-tool-parser` |
| `crates/tokenizer/`, `model_gateway/src/workflow/tokenizer_registration.rs`, `model_gateway/src/endpoints/tokenize/` | `checklists/parsers.md` | `rust-lint`, `rust-tests`, `benchmark-tokenizer` |
| `crates/kv_index/`, `crates/radix_tree/`, `model_gateway/src/worker/kv_event_monitor.rs`, `model_gateway/src/worker/kv_index_backend.rs` | `checklists/routing.md` | `rust-lint`, `rust-tests`, `benchmark-radix-tree`, `radix-tree-fuzz` |
| `crates/grpc_client/`, `model_gateway/src/routers/grpc/client.rs` | `checklists/routing.md`, `checklists/worker-lifecycle.md` | `rust-lint`, `rust-tests`, `grpc-proto-build-check` |
| `crates/engine_zmq_client/`, `crates/engine_zmq_adapter/`, `model_gateway/src/routers/grpc/zmq_client.rs`, `model_gateway/src/routers/grpc/backend_client.rs` | `checklists/zmq.md`, `checklists/routing.md` | `rust-lint`, `rust-tests`, `e2e-1gpu-chat-zmq`, `e2e-2gpu-chat-zmq-dp` |
| `crates/engine_servicer/`, `grpc_servicer/` | `checklists/zmq.md`, `checklists/worker-lifecycle.md` | `rust-lint`, `rust-tests`, `e2e-1gpu-chat-rust-servicer` |
| `crates/external_router/`, `model_gateway/src/routers/external.rs`, `model_gateway/src/routers/provider_support.rs` | `checklists/provider-routers.md`, `checklists/layering.md` | `rust-lint`, `rust-tests`, `e2e-vendor` |
| `crates/mcp/` | `checklists/layering.md` | `rust-lint`, `rust-tests`, `e2e-mcp-mock` |
| `crates/data_connector/` | `checklists/storage.md` | `rust-lint`, `rust-tests` |
| `crates/multimodal/`, `crates/mm_rdma/`, `model_gateway/src/routers/grpc/multimodal/` | `checklists/routing.md` | `rust-lint`, `rust-tests`, `e2e-1gpu-chat-mm-worker` |
| `crates/wasm/`, `examples/wasm/`, `model_gateway/src/wasm/`, `model_gateway/src/middleware/wasm.rs` | `checklists/layering.md` | `rust-lint`, `rust-tests` |
| `crates/mesh/`, `model_gateway/src/mesh/` | `checklists/layering.md` | `rust-lint`, `rust-tests` |
| `model_gateway/src/observability/`, `model_gateway/src/middleware/metrics.rs`, `model_gateway/src/middleware/logging.rs` | `checklists/layering.md` | `rust-lint`, `rust-tests` |
| `crates/rl/` | `checklists/layering.md` | `rust-lint`, `rust-tests` |
| `bindings/` | `checklists/config.md` | `build-wheel`, `python-unit-tests`, `python-lint`, `go-unit-tests`, `go-bindings-e2e` |
| `clients/` | sections 7–9 only | `rust-lint` |
| `e2e_test/`, `scripts/`, `.github/workflows/` | `checklists/testing.md` | `python-lint`, `ci-tooling-tests`, `e2e-cpu-mock` |
| `crates/mock_worker/`, `model_gateway/test_harness/` | `checklists/testing.md` | `rust-lint`, `rust-tests`, `e2e-cpu-mock` |
| `deploy/` | `checklists/config.md` | `build-wheel` |
<!-- /render -->

Files under none of these paths get sections 7–9 only. A PR touching three or more areas, or adding new types, also gets the architecture questions below.

## 7. Error handling (always)

- No `unwrap()` in production code (`unwrap_used = "deny"`); `?` with `anyhow::Context`, `thiserror` per domain.
- Invalid config fails loudly at startup; no silent fallback to `None` or a default.
- Streaming paths swallow nothing; a declined pass-through hands the request back unconsumed.

## 8. Testing (always)

- Unit tests for new types and parsing including error cases; existing struct literals updated.
- The test that pins the contract was updated or added (the matched checklist names it); e2e tests when user-facing behaviour changes, with `@pytest.mark.engine(...)` and `@pytest.mark.gpu(n)` (`checklists/testing.md`).
- `Cargo.lock` staged when a `Cargo.toml` changed; the lanes the change triggers were considered (`scripts/lanes.py`).

## 9. Code quality and craft (always)

- Conventional subject, DCO trailer matching git config, no Claude/anthropic attribution trailer (CI rejects all three).
- `#[expect(lint, reason = "...")]` not `#[allow]`; `tracing` not `println!`; `Uuid::now_v7`; HTTP clients from the crate's client factory, never `reqwest::Client::new`; `tokio::spawn` only for tasks that may die at shutdown, justified at the call site.
- Vocabulary: sides, role, pool; never "leg" or a dispatch "arm" (`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_vocabulary.py" --diff` over the diff).
- The craft questions in `skills/craft/SKILL.md`: clones on the hot path, bounds on new buffers and maps, a second spelling of something already spelled once, a flag without its launcher and Helm parity.

## Architecture questions (3+ areas or new types)

- Remove K8s: does it still make sense? (not `crates/protocols/`) · Can existing labels or config achieve it? · Does it compose with DP-aware mode, PD/EPD disaggregation, IGW multi-router mode, mesh HA? · `Send + Sync` under load? · HTTP, gRPC and ZMQ, Symphony and legacy parsers? · Compiles in the `self-hosted` and `anthropic-only` lint legs?

## Non-negotiables

- A config change is not approved until both conversion paths and the Python chain are verified (`checklists/config.md`).
- A parser change is not approved until the lane that exercises it (Symphony or legacy) is named.
- No finding without a marker and a `path:line`.

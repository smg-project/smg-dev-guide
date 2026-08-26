---
name: review-pr
description: Use when reviewing a pull request, checking a diff, or doing code review in the SMG repository — enforces systematic subsystem-aware review
---

# SMG PR Review

## The Iron Law

```
NO REVIEW APPROVAL WITHOUT CHECKING ALL TOUCHED SUBSYSTEMS
```

If you haven't mapped the changed files to checklist sections, you cannot start reviewing.

## The Hard Gate

<HARD-GATE>
Do NOT write review comments, approve, or provide feedback until you have:
1. Fetched the full diff
2. Listed every changed file
3. Mapped each file to the checklist sections below
4. Created a task for each applicable section
</HARD-GATE>

## Process

```
1. FETCH: Get the PR diff (gh pr diff <number>)
2. MAP: List changed files → match to sections using the file-to-section table
3. TASK: Create one review task per matched section
4. CHECK: Work through each task; prefix every inline comment with the repo's REVIEW.md severity marker — Important (bug, fix before merge) / Nit / Pre-existing (copy the exact marker glyphs from REVIEW.md)
5. ANTI-PATTERNS: Read @anti-patterns.md for the touched subsystems
6. SUMMARIZE: List all findings with marker, file:line citations, and a count per severity
```

### File-to-Section Mapping

| Files Changed | Review Sections |
|---------------|-----------------|
| `crates/protocols/src/` | 1 (Layering), 3 (Worker Lifecycle) |
| `model_gateway/src/config/`, `model_gateway/src/main.rs` | 2 (Config Plumbing) |
| `model_gateway/src/service_discovery.rs` | 3 (Worker Lifecycle) |
| `model_gateway/src/worker/`, `model_gateway/src/workflow/` (`steps/{local,shared,external}/`, `steps/mod.rs` DAG, `job_queue.rs`, `tokenizer_registration.rs`) | 3 (Worker Lifecycle) |
| `crates/workflow/src/` (wfaas engine) | 3 (Worker Lifecycle), 10 — a step `Skip` must not persist context; completion signals go out inside the tracker lock |
| `model_gateway/src/policies/` | 4 (Routing Policy) |
| `model_gateway/src/routers/` (incl. `common/`, `http/`, `grpc/`, `anthropic/`, `gemini/`, `responses/`, `conversations/`) | 1 (Layering), 4 (Routing Policy) |
| `crates/engine_zmq_client/`, `model_gateway/src/routers/grpc/{backend_client,zmq_client,zmq_multimodal}.rs`, `crates/mock_worker/` | 3 (Worker Lifecycle), 4 (Routing Policy), 8 — ZMQ is a third transport; these paths trigger the merge-blocking `e2e-*-chat-zmq*` lanes |
| `model_gateway/src/middleware/` (scheduler, concurrency, tenant_resolution), `model_gateway/src/rate_limit/`, `model_gateway/src/tenant.rs`, `crates/auth/` | 1 (Layering), 10 (Architecture) — no dedicated section yet |
| `crates/tool_parser/src/`, `crates/reasoning_parser/src/` | 5 (Parser Changes) |
| `crates/tokenizer/src/` (encoders, stop/EOS, registry) | 5 (Parser Changes — streaming/stop semantics), 8 (Testing) |
| `crates/data_connector/src/` | 6 (Storage) |
| `bindings/` | 2 (Config Plumbing) |
| `e2e_test/infra/`, `e2e_test/fixtures/` | 8 (Testing) |
| Any file | 7 (Error Handling), 8 (Testing), 9 (Code Quality) |

Sections 7, 8, 9 always apply. Section 10 applies to PRs touching 3+ files or adding new types.

## Review Checklist

### 1. Layering & Separation of Concerns

- [ ] No new fields in `crates/protocols/` types that only one crate sets
- [ ] Config types at correct layer: user-facing → `config/types.rs`, runtime → module-specific
- [ ] No raw strings parsed at runtime — parse at boundary
- [ ] WASM/MCP concerns stay in their crates, not leaking into core
- [ ] `serde(rename)` names match the OpenAI/Anthropic spec field names

### 2. Config Plumbing

- [ ] BOTH `to_router_config()` AND `to_server_config()` in main.rs updated
- [ ] CLI flag has `value_parser` validation
- [ ] `Default` impl includes new fields
- [ ] `#[serde(default, skip_serializing_if)]` for backward compat
- [ ] Python bindings threaded end to end: `config/builder.rs` setter → `router_args.py` field → `Router::new` pyo3 signature default → `.new_field(...)` on the `RouterConfig::builder()` in `to_router_config()` (`bindings/python/src/lib.rs`) — a missing builder call compiles and silently uses the Rust default
- [ ] ZMQ knobs reach `router_args.py` and `smg serve`, not just `lib.rs`; `derive_handshake_port` (`routers/grpc/zmq_client.rs`) and `_zmq_handshake_port` (`bindings/python/src/smg/serve.py`) stay in sync
- [ ] Go SDK updated if new types exposed

### 3. Worker Lifecycle & Label Pipeline

- [ ] New metadata flows through label pipeline (not parallel `_override` fields)
- [ ] Model ID resolution chain not bypassed
- [ ] WorkerSpec kept minimal at discovery time
- [ ] No post-hoc ModelCard mutation — inject via labels before `build_model_card`
- [ ] ZMQ workers: the handshake is never awaited on a request or probe path (background connect driver + `WorkerConnected` signal); `activate` leaves them Pending; `update_worker_properties` re-applies `zmq_handshake_address` / `zmq_engine_group` / `connect_signal_tx`; misconfig is rejected in `create_worker`, not at connect time

### 4. Routing Policy & Dispatch

- [ ] Works for HTTP, gRPC and ZMQ backends (`SelectWorkerInfo`; `ConnectionMode` in `crates/protocols/src/worker.rs`, `BackendClient` in `routers/grpc/backend_client.rs`)
- [ ] All state is `Send + Sync` (DashMap, Arc — no bare Mutex on hot paths)
- [ ] No `.unwrap()` on worker slices — handle empty list
- [ ] Eligibility via `w.is_available()` (health + circuit breaker + overload veto) through `policies/mod.rs:get_healthy_worker_indices`; hash policies use `w.is_healthy_and_eligible()`. A hand-rolled `is_healthy() && circuit_breaker_can_execute()` drops the overload veto
- [ ] New selection/dispatch paths shed: `overload::shed_if_all_overloaded` on the candidate pool, `overload::shed_if_worker_overloaded` on the chosen worker (`routers/common/overload.rs`)
- [ ] Policy implements `LoadBalancingPolicy` and is registered in `policies/factory.rs` with a `PolicyConfig` enum variant
- [ ] Dispatch memory: route methods take the parsed body by value and nothing outlives `RequestLease::release_dispatch()` (`routers/common/request_lease.rs`); upstream sends go through `attach_sized_body` / `serialize_json_sized` (`routers/common/mod.rs`) and upstream reads through `read_worker_body_capped` — no unbounded buffering
- [ ] Shed and other terminal responses call `retry::mark_non_retryable`; a declined streaming pass-through hands the request back with its body unconsumed
- [ ] No per-token `clone()` in the gRPC streaming path (`routers/grpc/regular/streaming.rs`, shared by Regular and PD; `routers/grpc/common/responses/streaming.rs` for the Responses SSE emitter) — `routers/grpc/common/stages/` is per-request, not per-token

### 5. Parser Changes (Tool / Reasoning)

- [ ] Implements full trait (all methods + `reset`)
- [ ] Streaming state correct (buffer, partial token detection, delta calc)
- [ ] Registered in `ParserFactory` with model pattern mapping
- [ ] Tests: single call, multiple calls, streaming at boundaries, invalid input

### 6. Storage / Data Connector

- [ ] Implements all required traits
- [ ] Schema migrations handled
- [ ] Hook system integration (audit, validation)
- [ ] Batch operations supported

### 7. Error Handling

- [ ] No `unwrap()` in production code
- [ ] Meaningful error messages with `anyhow::Context`
- [ ] Invalid config fails loudly — no silent fallback to None
- [ ] `thiserror` for domain errors, `anyhow` for wrapping

### 8. Testing

- [ ] Unit tests for new types/parsing including error cases
- [ ] Integration test for full flow
- [ ] Existing test struct literals updated with new fields
- [ ] E2E tests if user-facing behavior changes (in `e2e_test/`; `setup_backend` is class-scoped and items are ordered by (backend, model) so the session `WorkerPool` reuses workers)
- [ ] Every new e2e test carries `@pytest.mark.engine("sglang", "vllm", ...)` and `@pytest.mark.gpu(n)` — GPU lanes export `E2E_ENGINE`/`E2E_GPU_TIER` and `e2e_test/fixtures/hooks.py` deselects anything without a matching `engine` marker (a missing `gpu` marker defaults to `gpu(1)`, so it silently lands in the 1-GPU lanes instead; reported as an `e2e selection:` line; `E2E_MIN_SELECTED` fails the lane below its floor). Full marker set is registered in `hooks.py:pytest_configure` — `engine`, `vendor` (cloud), `gpu`, `model`, `skip_for_runtime`, `gateway(policy=, timeout=, extra_args=)`, `workers(count=, prefill=, decode=, gpus=, extra_engine_args=)`, `storage`, `external`, `e2e`, `slow`, `slowtest`, `nightly` — plus `kind` in `e2e_test/pyproject.toml`
- [ ] gRPC-pipeline changes also behave over ZMQ: the `e2e-*-chat-zmq*` lanes replay single-worker cases with `E2E_CONNECTION_MODE=zmq` (`hooks.py:_filter_zmq_items` drops PD/EPD/multi-worker there, so a ZMQ-only fix needs a single-worker chat case)
- [ ] Discovery changes (`service_discovery.rs`, multi-port) covered by the kind lane: `SMG_KIND_E2E=1 pytest e2e_test/kind_discovery --confcutdir e2e_test/kind_discovery -m kind` (Linux, needs kind/kubectl)
- [ ] Harness changes (`e2e_test/infra/`, `e2e_test/fixtures/`) pass the CPU gate: `PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra e2e_test/fixtures`

### 9. Code Quality

- [ ] Conventional commit format
- [ ] DCO sign-off present
- [ ] No AI attribution
- [ ] `cargo +nightly fmt --all` clean
- [ ] `cargo clippy --all-targets --all-features -- -D warnings` clean
- [ ] Uses `#[expect]` with reason, not `#[allow]`
- [ ] `tracing` for logging, not `println!`

### 10. Architecture Smell Tests

- "If I remove K8s, does this change still make sense?" → shouldn't be in `crates/protocols/`
- "Can existing config overrides or labels achieve this?" → may be unnecessary
- "Does this compose with DP-aware mode, PD disagg, mesh HA?" → don't break existing
- "Is this Send + Sync safe under concurrent load?" → all routing state thread-safe
- "Did I check HTTP, gRPC and ZMQ paths?" → three transports now
- "Does it still hold for a ZMQ worker?" → ZMQ is host-local: excluded from mesh sync, PD/EPD legs, admin RPCs (flush/profile), KV events (cache_aware only warns), and dp-aware expansion (grouped engines use `dp_size` instead). A new cross-cutting feature must support the ZMQ lane or reject it loudly at registration

See @anti-patterns.md for subsystem-specific anti-patterns.

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "This change is small, I can eyeball it" | Small changes cause the biggest bugs — the two-path config rule is a one-line omission. |
| "I know this code well" | Familiarity breeds blindness. Use the checklist. |
| "It's just a config change" | Config changes touch the most layers (CLI → types → main.rs → bindings). Check section 2. |
| "Tests pass so it's fine" | Tests don't catch layering violations, missing bindings, or one-path config bugs. |

## Red Flags — STOP

- About to approve without mapping files to sections
- Skipping a section because "it doesn't apply" without checking the mapping table
- No file:line citations in review comments, or comments missing the REVIEW.md severity marker
- Approving a config change without verifying both conversion paths
- Reviewing without fetching the actual diff first

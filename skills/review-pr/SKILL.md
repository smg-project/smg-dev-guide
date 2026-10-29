---
name: review-pr
description: Review a pull request or diff in the SMG repository with a subsystem-aware checklist — map every changed file to the sections it triggers, check layering, config plumbing, worker lifecycle, routing, parsers, storage, error handling, tests and CI lanes, and report REVIEW.md-severity findings with file:line citations. Use for "review this PR", a PR number or URL, or a self-review before pushing.
---

# SMG PR Review

## The rule

```
NO REVIEW VERDICT WITHOUT CHECKING EVERY TOUCHED SUBSYSTEM
```

<HARD-GATE>
Do NOT write review comments, approve, or give feedback until you have:
1. Fetched the full diff
2. Listed every changed file
3. Mapped each file to the checklist sections below
4. Created a task per applicable section
</HARD-GATE>

## Process

```
1. FETCH      gh pr diff <number>   (or git diff <base>...HEAD for local work)
2. MAP        changed files → sections, with the table below
3. TASK       one task per matched section
4. CHECK      work the sections; prefix every finding with the REVIEW.md marker:
              🔴 Important (bug, fix before merge) · 🟡 Nit · 🟣 Pre-existing
5. PATTERNS   read anti-patterns.md (this directory) for the touched subsystems
6. SUMMARIZE  findings with marker + file:line, then a count per severity;
              a full review with zero 🔴 may approve
```

`REVIEW.md` in SMG is the source of truth for markers and focus areas (it also tells reviewers to use this skill and the `pr-review-toolkit` agents for silent failures, test coverage and type design). The PR body must carry the template headers `## Description`, `### Problem`, `### Solution`, `## Changes`, `## Test Plan`.

## File-to-section mapping

| Files changed | Sections |
|---|---|
| `crates/protocols/src/` | 1 Layering, 3 Worker lifecycle |
| `model_gateway/src/config/`, `model_gateway/src/main.rs`, `model_gateway/src/cli/` | 2 Config plumbing |
| `model_gateway/src/service_discovery/` (providers, `reconciler.rs`) | 3 Worker lifecycle |
| `model_gateway/src/worker/`, `model_gateway/src/workflow/` (`steps/`, `job_queue.rs`, `tokenizer_registration.rs`) | 3 Worker lifecycle |
| `crates/workflow/src/` (the `wfaas` engine) | 3, 10 — a step's `Skip` must not persist context; completion signals go out inside the tracker lock |
| `model_gateway/src/policies/` (incl. `cost/`, `cache_namespace.rs`) | 4 Routing and dispatch |
| `model_gateway/src/routers/` (`gateway.rs`, `factory.rs`, `external.rs`, `common/`, `http/`, `grpc/`) | 1, 4 |
| `model_gateway/src/endpoints/` (responses, conversations, tokenize, parse, models) | 1, 7 |
| `crates/external_router/src/` | 1, 4, 11 Provider routers |
| `crates/engine_zmq_client/`, `crates/engine_zmq_adapter/`, `routers/grpc/{backend_client,zmq_client}.rs`, `crates/mock_worker/` | 3, 4, 8 — ZMQ is a third transport; these paths trigger the merge-blocking `e2e-*-chat-zmq*` lanes |
| `crates/engine_servicer/` | 3, 8 — lane `e2e-1gpu-chat-rust-servicer` |
| `model_gateway/src/middleware/` (scheduler, concurrency, tenant_resolution, auth), `model_gateway/src/rate_limit/`, `model_gateway/src/tenant/`, `crates/auth/` | 1, 10 |
| `crates/symphony/` | 5 Parsers (Symphony sub-list) |
| `crates/tool_parser/src/`, `crates/reasoning_parser/src/`, `crates/response_template/src/` | 5 Parsers |
| `crates/tokenizer/src/` | 5 (streaming / stop semantics), 8 |
| `crates/kv_index/`, `crates/radix_tree/` | 4, 8 — differential/exactness tests; `benchmark-radix-tree.yml` runs |
| `crates/data_connector/src/` | 6 Storage |
| `crates/multimodal/src/`, `routers/grpc/multimodal/` | 4, 8 — vision golden fixtures regenerate in `rust-tests` |
| `crates/rl/` | 1, 10 — inert unless `--enable-rl` |
| `bindings/` | 2 |
| `e2e_test/infra/`, `e2e_test/fixtures/`, `.github/workflows/` | 8 Testing |
| Any file | 7 Error handling, 8 Testing, 9 Code quality |

Sections 7, 8, 9 always apply. Section 10 applies to PRs touching 3+ files or adding new types.

## Checklist

### 1. Layering and separation of concerns
- [ ] No new field in `crates/protocols/` that only one crate sets
- [ ] Config types at the right layer: user-facing → `config/types.rs`, runtime → the owning module
- [ ] Strings parsed at the boundary, typed at runtime
- [ ] Provider-specific, WASM and MCP concerns stay in their crates (`crates/external_router`, `crates/wasm`, `crates/mcp`), re-exported, not re-implemented in the gateway
- [ ] `serde(rename)` names match the OpenAI / Anthropic / Gemini spec field names

### 2. Config plumbing
- [ ] `RouterConfig` field: `#[serde(default)]`, in the `Default` impl, a hand-written setter in `config/builder.rs`, used in `to_router_config` (`main.rs`); invariants in `config/validation.rs`, not only in a clap `value_parser`
- [ ] Top-level `ServerConfig` field (read by `server::startup`): set in all three literals — `main.rs:to_server_config`, `bindings/python/src/lib.rs`, the `server.rs` test helper
- [ ] A `*_flows_into_both_configs` test in `main.rs` for a new flag
- [ ] Python threaded end to end: `Router::new` pyo3 signature default (appended last) → stored on the pyclass → `.new_field(...)` on the builder in `lib.rs::to_router_config` → a keyword-only `RouterArgs` field at its alphabetical place in `router_args.py` (`bindings/python/tests/test_arg_parser.py` pins the frozen positional prefix, keyword-only-ness and alphabetical order). A missing builder call compiles and silently uses the Rust default
- [ ] New `PolicyConfig` variant: `factory.rs` **both** `create_from_config` and `create_by_name`, `validate_policy`, `--policy` value_parser lists, `PolicyType` in `lib.rs`, `policy_from_str` in `router.py`, `COMMON_POLICY_CHOICES` in `router_args.py`
- [ ] ZMQ knobs reach `router_args.py` and `smg serve`; `derive_handshake_port` and `_zmq_handshake_port` (`bindings/python/src/smg/serve.py`) stay in sync

### 3. Worker lifecycle and label pipeline
- [ ] New metadata flows as a label (discovery → `DiscoveredWorker` labels → `create_worker.rs` → `ModelCard`), not a parallel `_override` field on `WorkerSpec`
- [ ] Model-id resolution chain not bypassed; no `ModelCard` mutation after `build_model_card`
- [ ] Discovery changes work for every provider that shares the reconciler (`kubernetes.rs`, `consul.rs`, `file.rs`, `slurm.rs`) or are scoped to one on purpose
- [ ] ZMQ: the handshake is never awaited on a request or probe path (`spawn_zmq_connect_driver` + `WorkerConnected`); misconfiguration is rejected in `create_worker.rs`, not at connect time; `update_worker_properties` preserves the backend client

### 4. Routing and dispatch
- [ ] Works for HTTP, gRPC and ZMQ (`SelectWorkerInfo`; `ConnectionMode` in `crates/protocols/src/worker.rs`; `BackendClient` in `routers/grpc/backend_client.rs`)
- [ ] State is `Send + Sync` (DashMap, atomics; no bare `Mutex` on the hot path); no `.unwrap()` on worker slices
- [ ] Eligibility via `get_healthy_worker_indices` / `w.is_available()` (health + circuit breaker + overload veto); a hand-rolled `is_healthy() && circuit_breaker_can_execute()` drops the veto
- [ ] Load-aware policy: `set_load_receiver`, `needs_backend_loads() == true`, `remove_worker`, `reconcile_in_flight`
- [ ] New dispatch path sheds (`overload::shed_if_all_overloaded`, `shed_if_worker_overloaded`) and marks terminal responses `retry::mark_non_retryable`
- [ ] Dispatch memory: bodies by value, nothing outlives `RequestLease::release_dispatch()`, sized bodies (`attach_sized_body`, `serialize_json_sized`, `read_worker_body_capped`); no per-token `clone()` in `routers/grpc/regular/streaming.rs`
- [ ] A new `ZmqDialect` / `BackendClient` / `ProviderType` match writes every arm — no `_ =>`

### 5. Parsers
Symphony (`crates/symphony`), the default:
- [ ] A new table has a `tables!` row in `formats/registry.rs`, module + re-export in `formats/mod.rs`, its groups in `formats/groups.json`, a `Subject` in `tests/parser/contract.rs`, a corpus row in `tests/bellwether_parse_fixtures.rs`, and the README models table regenerated (`SYMPHONY_WRITE_README=1 cargo test -p smg-symphony --test readme`)
- [ ] Every byte lands in exactly one event; malformed regions come back whole with a `MalformedReason`, nothing is dropped silently
- [ ] The fuzz workspace (`crates/symphony/fuzz`) still formats and builds
Legacy (`crates/tool_parser`, `crates/reasoning_parser`):
- [ ] Full trait implemented (incl. `reset`); streaming state (buffer, partial token detection, deltas) correct; registered in the `ParserFactory` with model patterns; tests for single, multiple, boundary-split and invalid input
- [ ] No legacy parser added for a model Symphony's registry already reads

### 6. Storage / data connector
- [ ] Three structs implementing `ConversationStorage`, `ConversationItemStorage`, `ResponseStorage`; wrapped by `create_storage` in the `Hooked*` decorators (no hook code in the backend)
- [ ] SQL backends: versioned migrations through `versioning.rs` (`run_postgres_migrations` / `run_oracle_migrations`); per-table `TableConfig` honoured
- [ ] Gateway wiring: `HistoryBackend` variant, `--history-backend` value_parser, `RouterConfig` field, `app_context.rs` `StorageFactoryConfig` literal, Python `HistoryBackendType`

### 7. Error handling
- [ ] No `unwrap()` in production code (`unwrap_used = "deny"`); `?` with `anyhow::Context`, `thiserror` for domain errors
- [ ] Invalid config fails loudly at startup, no silent fallback to `None`/default
- [ ] No swallowed errors on the streaming path; a declined pass-through hands the request back unconsumed

### 8. Testing
- [ ] Unit tests for new types/parsing incl. error cases; existing struct literals updated
- [ ] E2E tests when user-facing behaviour changes; every new e2e test carries `@pytest.mark.engine(...)` and `@pytest.mark.gpu(n)` (a missing `gpu` marker silently lands in the 1-GPU lanes)
- [ ] gRPC-pipeline changes also behave over ZMQ (the `e2e-*-chat-zmq*` lanes replay single-worker chat cases) and, for parser changes, under both `E2E_PARSER=symphony` and `legacy`
- [ ] Discovery changes: `cargo test -p smg --test discovery_tests`; kind lane `SMG_KIND_E2E=1 pytest e2e_test/discovery/kind -m kind`
- [ ] Harness changes (`e2e_test/infra/`, `e2e_test/fixtures/`) pass `PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra e2e_test/fixtures`
- [ ] `cargo test -p <crate>` for a touched crate; `Cargo.lock` staged when a `Cargo.toml` changed (CI runs `cargo metadata --locked`)

### 9. Code quality
- [ ] Conventional commit subjects; DCO sign-off on every commit matching git config; no Claude/anthropic attribution trailers (CI rejects them)
- [ ] `cargo +nightly fmt --all` clean; `cargo clippy --workspace --all-targets --all-features -- -D warnings` clean in every lint leg (`all-features`, `self-hosted`, `anthropic-only`, `default-build`)
- [ ] `#[expect(lint, reason = "...")]`, not `#[allow]`; `tracing`, not `println!`; `Uuid::now_v7`, not `new_v4`; HTTP clients from the crate's client factory, never `reqwest::Client::new` (disallowed)
- [ ] `tokio::spawn` only for tasks that may die at shutdown, justified with `#[expect(clippy::disallowed_methods, reason = "...")]`; otherwise keep and join the `JoinHandle`

### 10. Architecture smell tests
- "If I remove K8s, does this still make sense?" → not `crates/protocols/`
- "Can existing labels or config overrides achieve this?" → may be unnecessary
- "Does this compose with DP-aware mode, PD/EPD disaggregation, IGW multi-router mode, mesh HA?"
- "Is this `Send + Sync` safe under concurrent load?"
- "Did I check HTTP, gRPC and ZMQ, and Symphony and legacy parsers?"
- "Does it compile in the `self-hosted` leg (no provider features) and the `anthropic-only` leg?"

### 11. Provider routers (`crates/external_router`)
- [ ] An OpenAI-compatible vendor is a `Provider` impl under `openai/provider/` registered in `ProviderRegistry`, not a new router family
- [ ] A new family: `ExternalRouterSpec` in `router.rs` (`all()` grows), Cargo feature in both crates, `RoutingMode` + `Backend` variants, `serves` covers its `ProviderType`; non-compiled builds return `not_compiled()`
- [ ] Shared glue reused (`sse.rs`, `retry.rs`, `mcp_utils.rs`, `openai_bridge/`, `header_utils.rs`, `upstream_body.rs`), no hand-rolled SSE framing

## Rationalization prevention

| Excuse | Reality |
|---|---|
| "Small change, I can eyeball it" | The two-path config rule and the `create_by_name` arm are one-line omissions. |
| "Tests pass, so it's fine" | Tests don't catch layering violations, a missing Python builder call, or a lane that no longer selects the test. |
| "It's just a config change" | Config touches CLI → types → builder → validation → bindings. Section 2 end to end. |

## Red flags — stop

- Approving without mapping files to sections, or without the diff in front of you
- A finding without a marker or without `file:line`
- A config change approved without both paths and the Python chain verified
- A parser change approved without asking which lane (Symphony/legacy) exercises it

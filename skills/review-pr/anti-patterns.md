# SMG Anti-Patterns Reference

Per-subsystem anti-patterns to check during PR review.

## Config Plumbing

| Anti-Pattern | Consequence | What to Look For |
|-------------|-------------|------------------|
| Only wiring `to_router_config()`, missing `to_server_config()` | Field silently ignored in one code path | `grep -n "new_field" model_gateway/src/main.rs` — must appear in BOTH functions |
| Missing `#[serde(default)]` on new optional field | Existing YAML configs fail to deserialize | Check all new `Option<T>` fields in `config/types.rs` |
| No `value_parser` on CLI flag | Invalid values accepted, crash at runtime | Check `CliArgs` in `main.rs` for new `#[arg(...)]` fields |

## Worker Lifecycle & Labels

| Anti-Pattern | Consequence | What to Look For |
|-------------|-------------|------------------|
| Adding `_override` field to WorkerSpec | Bypasses label pipeline, creates parallel data path | New fields on `WorkerSpec` in `crates/protocols/src/worker.rs` |
| Post-hoc ModelCard mutation | Race conditions, stale data in routing | `card.id = ...` (or any field write) after `build_model_card()` in `workflow/steps/local/create_worker.rs` — inject via labels (`resolve_model_id`) instead |
| Injecting K8s-specific data into `crates/protocols/` types | Tight coupling to K8s, breaks non-K8s deployments | New fields in `crates/protocols/` that reference namespaces, pods, labels |

## Routing

| Anti-Pattern | Consequence | What to Look For |
|-------------|-------------|------------------|
| Only testing HTTP path, missing gRPC/ZMQ | Feature breaks for gRPC or ZMQ backends | Router tests whose workers are all `ConnectionMode::Http` (`crates/protocols/src/worker.rs:ConnectionMode`, `worker/builder.rs:connection_mode`); e2e tests parametrized on `setup_backend` with only one of `"grpc"`/`"http"` (ZMQ runs via the `E2E_CONNECTION_MODE=zmq` lane) |
| Using `RwLock` on hot routing path | Contention under load | `RwLock` in routing policy structs (use `DashMap` instead) |
| `.unwrap()` on empty worker slice | Panic when no workers available | `workers[0]` or `.unwrap()` on worker selection |
| Skipping the eligibility check, or re-deriving it | Routing to unhealthy or overload-vetoed backends | Missing `w.is_available()` (`w.is_healthy_and_eligible()` in hash policies); a hand-written `is_healthy() && circuit_breaker_can_execute()` drops the overload veto |
| Computing overload per request | Extra worker walk on the hot path | Overload is latched once per ingested load report (`worker/overload.rs`, `Worker::is_overloaded()`); selection must only read the flag |
| Holding request memory past the lease | Per-request memory doubles under load | Parsed request / `RoutingDerivatives` / body bytes cloned out of `RequestLease` (`routers/common/request_lease.rs`) into streaming tasks, or kept after `release_dispatch()` |

## Parsers (Tool / Reasoning)

| Anti-Pattern | Consequence | What to Look For |
|-------------|-------------|------------------|
| Not resetting parser state between requests | Stale buffer from previous request bleeds into next | Missing `reset()` call or incorrect reset timing |
| Losing partial token prefix (e.g. `</` that isn't `</think>`) | Text silently dropped during streaming | Buffer handling when partial match fails |
| Missing factory registration | Parser unreachable at runtime | New parser not in `ParserFactory::new()` |

## ZMQ Direct Backend

| Anti-Pattern | Consequence | What to Look For |
|-------------|-------------|------------------|
| Reordering or inserting msgpack struct fields | Silent wire corruption against a real engine | `array_like` positional structs in `crates/engine_zmq_client/src/protocol/` (e.g. `vllm::EngineCoreRequest`) — field order is the wire contract, append only; cross-check the engine's Python msgspec struct |
| Open-ended transport dispatch | ZMQ silently takes the gRPC arm | `_ =>` arms over `BackendClient` / `ZmqDialect` (`routers/grpc/backend_client.rs`, `zmq_client.rs`); ZMQ arms bolted onto `GrpcClient` instead |
| Awaiting the handshake inline | Request or health path blocks for the whole connect timeout | `connect_handshake` reached from a request/probe path instead of `spawn_zmq_connect_driver` plus the `WorkerConnected` signal |
| Sending string stops over the ZMQ wire | EngineCore has no tokenizer — stops never fire, generation runs to the context window | Stop strings / EOS resolved anywhere but `BackendClient::finalize_generate_request` (`fold_tokenizer_eos_backstop`) — the wire is token-only |

## Bindings

| Anti-Pattern | Consequence | What to Look For |
|-------------|-------------|------------------|
| `RouterConfig` field not threaded through the Python chain | Compiles fine; Python launches silently run the Rust default | A new field needs a `model_gateway/src/config/builder.rs` setter, a `router_args.py` dataclass + argparse field, a `Router::new` pyo3 signature default, and a `.new_field(...)` call in `to_router_config()` (`bindings/python/src/lib.rs`) |
| Missing field in the `ServerConfig` struct literal | `maturin develop` build failure | `server::ServerConfig { .. }` in `bindings/python/src/lib.rs` has no `..Default::default()` |
| Missing Go type mapping | Go SDK compile failure | New enum/type not mirrored in `bindings/golang/` |

## Storage

| Anti-Pattern | Consequence | What to Look For |
|-------------|-------------|------------------|
| Bypassing the hook wrappers | Audit trail gaps | New backend handed out raw instead of wrapped in `HookedConversationStorage` / `HookedConversationItemStorage` / `HookedResponseStorage` (`hooked.rs`); new `StorageOperation` without `before()`/`after()` coverage (`hooks.rs:StorageHook`) |
| No schema migration | Data loss on upgrade | New fields without migration handling |

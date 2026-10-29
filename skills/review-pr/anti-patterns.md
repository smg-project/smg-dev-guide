# SMG anti-patterns reference

Per-subsystem anti-patterns to check during review. Each row says what to grep for; when a path here is wrong, run `/smg:learn`.

## Config plumbing

| Anti-pattern | Consequence | What to look for |
|---|---|---|
| Builder chain updated, `ServerConfig` literals not (for a top-level listener setting) | `server::startup` reads the default | the field in `main.rs:to_server_config`, `bindings/python/src/lib.rs` and the `server.rs` test helper |
| Setter missing in `config/builder.rs` | does not compile — the builder is hand-written | `RouterConfigBuilder` has no `.my_field()` |
| Missing `#[serde(default)]` on a new field | existing serialized configs stop deserializing | new fields in `config/types.rs` |
| Invariant only in a clap `value_parser` | Python bindings bypass clap | `config/validation.rs` lacks the check |
| `RouterArgs` field appended at the tail, out of alphabetical order, or made positional | `test_the_keyword_only_fields_are_in_alphabetical_order` / `test_every_other_field_is_keyword_only` fail | `bindings/python/src/smg/router_args.py` (after the `KW_ONLY` marker, alphabetical), `bindings/python/tests/test_arg_parser.py` |

## Worker lifecycle and labels

| Anti-pattern | Consequence | What to look for |
|---|---|---|
| `_override` field on `WorkerSpec` | parallel data path around the label pipeline | new fields on `WorkerSpec` in `crates/protocols/src/worker.rs` |
| `ModelCard` mutated after `build_model_card()` | stale routing data, races | field writes after the build in `workflow/steps/local/create_worker.rs` |
| K8s-specific data in `crates/protocols/` | couples every deployment to K8s | namespaces, pods, selectors in protocol types |
| Provider-specific logic in the shared reconciler | breaks Consul/file/Slurm discovery | provider checks in `service_discovery/reconciler.rs` instead of the provider file |

## Routing

| Anti-pattern | Consequence | What to look for |
|---|---|---|
| Tests with only HTTP workers | gRPC/ZMQ regress | all `ConnectionMode::Http` in router tests; e2e parametrized on one of `grpc`/`http` |
| `RwLock` / bare `Mutex` on the hot path | contention | locks in policy structs; use atomics or `DashMap` |
| `.unwrap()` on a worker slice | panic with no workers | `workers[0]`, `.unwrap()` in selection |
| Eligibility re-derived | routes to overload-vetoed workers | `is_healthy() && circuit_breaker_can_execute()` instead of `is_available()` / `get_healthy_worker_indices` |
| Overload computed per request | extra fleet walk on the hot path | overload is latched per load report (`worker/overload.rs`, `Worker::is_overloaded()`); selection only reads it |
| Request memory held past the lease | per-request memory doubles under load | clones out of `RequestLease` into streaming tasks, anything kept after `release_dispatch()` (`routers/common/request_lease.rs`) |
| Load-aware policy without `remove_worker` / `reconcile_in_flight` | tallies grow under churn, phantom in-flight | overrides missing in the policy file |
| `create_from_config` arm without `create_by_name` | a worker `policy_hint` silently falls back to the default policy | `policies/factory.rs` |

## Parsers

| Anti-pattern | Consequence | What to look for |
|---|---|---|
| Legacy parser added for a model Symphony reads | two parsers, the legacy one unused in the default lane | `crates/tool_parser` / `crates/reasoning_parser` change without a `--parser legacy` reason; check `formats/groups.json` |
| Symphony table without its registry row, group lines, contract `Subject` or corpus row | build or test fails, or the table is unreachable | `formats/registry.rs` `tables!`, `formats/groups.json`, `tests/parser/contract.rs`, `tests/bellwether_parse_fixtures.rs` |
| Bytes dropped without a `DropReason`, or a malformed region swallowed | text vanishes from the answer | event construction in `crates/symphony/src/engine.rs` and assemblers |
| Legacy: parser state not reset between requests; partial marker prefix lost (`</` that is not `</think>`) | stale buffer bleeds; text dropped mid-stream | `reset()` timing; buffer handling on a failed partial match |

## ZMQ direct backend

| Anti-pattern | Consequence | What to look for |
|---|---|---|
| Reordering or inserting msgpack struct fields | silent wire corruption against a real engine | positional structs in `crates/engine_zmq_client/src/protocol/` — append only; cross-check the engine's Python msgspec struct |
| Wildcard arm over `ZmqDialect` / `BackendClient` | a new dialect silently takes the wrong arm | `_ =>` in `routers/grpc/backend_client.rs`, `crates/engine_zmq_adapter/src/client.rs` |
| Handshake awaited inline | request or probe path blocks for the connect timeout | `connect_handshake` reached from a request/probe path instead of `spawn_zmq_connect_driver` + `WorkerConnected` (`worker/basic.rs`) |
| String stops sent over the wire | EngineCore has no tokenizer: stops never fire | stop handling outside `engine_zmq_adapter/src/stops.rs` / `eos.rs` (`fold_tokenizer_eos_backstop`) |
| ZMQ arm bolted onto `GrpcClient` | the transport seam leaks | ZMQ code in `routers/grpc/client.rs`; `BackendClient` is the seam |

## Provider routers

| Anti-pattern | Consequence | What to look for |
|---|---|---|
| New router family for an OpenAI-compatible vendor | duplicated SSE/retry/MCP glue | a module beside `openai/` where a `Provider` impl under `openai/provider/` would do |
| Provider code outside its Cargo feature | the `self-hosted` / `anthropic-only` lint legs break | `#[cfg(feature = ...)]` missing in `crates/external_router/src/router.rs` builders |
| Hand-rolled SSE framing | unbounded buffers, broken keep-alive frames | not using `crates/external_router/src/sse.rs` |

## Bindings

| Anti-pattern | Consequence | What to look for |
|---|---|---|
| `RouterConfig` field not threaded through the Python chain | compiles; Python launches silently run the Rust default | `config/builder.rs` setter, `router_args.py` field, `Router::new` signature default, `.new_field(...)` in `lib.rs::to_router_config` |
| `ServerConfig` literal in `lib.rs` missing the field | `maturin develop` fails | the `Router::start` literal has no `..Default::default()` |
| Go type mapping missing | Go SDK compile failure | `bindings/golang/` |

## Storage

| Anti-pattern | Consequence | What to look for |
|---|---|---|
| Backend handed out unwrapped | audit trail gaps | `create_storage` not wrapping in `HookedConversationStorage` / `HookedConversationItemStorage` / `HookedResponseStorage` (`hooked.rs`); a new `StorageOperation` without `before()`/`after()` coverage (`hooks.rs`) |
| Schema change without a versioned migration | data loss on upgrade | no new `Migration` in `postgres_migrations.rs` / `oracle_migrations.rs` |
| Offset pagination | cursor contract broken | ignoring `ListParams.after` |

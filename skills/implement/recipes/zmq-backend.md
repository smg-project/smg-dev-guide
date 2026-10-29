---
recipe: zmq-backend
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/engine_zmq_client/src/
  - crates/engine_zmq_adapter/src/
  - model_gateway/src/routers/grpc/zmq_client.rs
  - model_gateway/src/routers/grpc/backend_client.rs
  - model_gateway/src/worker/basic.rs
  - model_gateway/src/workflow/steps/local/create_worker.rs
---

# Extending SMG's ZMQ Direct Backend

When SMG and the engine share a host, the gRPC path (gateway → gRPC → Python servicer → ZMQ → scheduler) collapses to a direct ZMQ connection over `ipc://`. Three layers own it, and the `Mode`/pipeline/stages of the gRPC router are reused unchanged:

| Layer | Where | Key symbols |
|---|---|---|
| Wire | `crates/engine_zmq_client/` (package `engine-zmq-client`): `transport.rs`, `codec/`, `protocol/mod.rs`, `protocol/vllm/`, `protocol/tokenspeed/`, `protocol/handshake.rs`, `connector.rs`, `startup.rs`, `mock_engine.rs` (feature `mock-engine`) | `EngineProtocol`, `EngineOutput`, `EngineBatch`, `EngineLoad`, `connect_handshake`, `EngineId`, `ENGINE_CORE_DEAD_SENTINEL`, `Client<P>`, `RequestStream`, `encode_msgpack`, `decode_msgpack`, `TrailingTolerant` |
| Engine adapter | `crates/engine_zmq_adapter/` (package `engine-zmq-adapter`): each engine's own gRPC-proto request/response surface over the wire — `client.rs`, dialects `vllm.rs` + `vllm/`, `tokenspeed.rs` + `tokenspeed/`, `sglang.rs`, `trtllm.rs`; frontend duties the tokenizer-less engine cannot perform: `eos.rs`, `stops.rs`, `fanout.rs`, `embed.rs`, `structured_outputs.rs`, `context_window.rs`, `multimodal.rs`, `admin.rs`, `abort_status.rs`, `sockets.rs`, `stream.rs` | `ZmqEngineClient`, `ZmqDialect`, `connect_for_worker`, `connect_with_eos`, `ZmqModelInfo`, `ZmqServerInfo`, `fold_tokenizer_eos_backstop`, `translate_embed_request`, `translate_request_tokenspeed_for`, `translate_request_sglang`, `build_mm_features`, `MmField` |
| Gateway seam | `model_gateway/src/routers/grpc/zmq_client.rs` (seam over the adapter), `routers/grpc/backend_client.rs`, `worker/basic.rs`, `worker/event.rs`, `workflow/steps/local/create_worker.rs` | `BackendClient::{Grpc,Zmq}`, `ZmqBuilders`, `finalize_generate_request`, `build_zmq_request`, `derive_handshake_port`, `connect_zmq_backend`, `spawn_zmq_connect_driver`, `zmq_health_check`, `zmq_admin_unsupported`, `WorkerConnected`, `validate_zmq_*` |

The adapter has a second consumer: `crates/engine_servicer` (the Rust engine servicer) serves the same per-engine proto over gRPC on the engine's node through it, so a translation fix lands in both lanes.

**Topology: SMG binds, the engine dials.** SMG binds a `tcp://` handshake ROUTER plus `ipc://` input (ROUTER) and output (PULL) sockets, drives HELLO → INIT → READY per engine, then waits for each engine's `EngineCoreReadyResponse` registration on the input socket (`transport.rs::connect_handshake`). `ConnectionMode::from_url` (`crates/protocols/src/worker.rs`) classifies an `ipc://` worker URL as `ConnectionMode::Zmq`; `uses_grpc_pipeline()` is true for both gRPC and ZMQ.

**Dialects.** `ZmqDialect` (`crates/engine_zmq_adapter/src/client.rs`) is `Vllm | TokenSpeed | Sglang | Trtllm`: vLLM's EngineCore (`vllm serve --headless`), TokenSpeed's scheduler (`ts serve --headless`), SGLang's scheduler behind the SMG plugin that performs the handshake inside it, and TensorRT-LLM's LLM API behind the shim that performs it beside the API. A closed set: every `match` writes all four arms and no wildcard.

**Constraints — read the code before promising a feature.** Registration allowlists the runtimes a ZMQ worker may declare (`create_worker.rs`, the `RuntimeType` gate next to `validate_zmq_worker_type`, which also restricts the worker types, and `validate_zmq_dp` for grouped engines); admin control calls (flush/profile) follow `engine_zmq_adapter/src/admin.rs` and return `zmq_admin_unsupported` (`worker/basic.rs`) where a dialect lacks them; what a dialect supports beyond chat — embeddings (`embed.rs`), structured outputs (`structured_outputs.rs`), multimodal (`multimodal.rs`) — is decided per dialect inside the adapter. Health checks cannot be disabled (`resolve_zmq_health_config` forces them on: the probe is the only path that reconnects a restarted engine). The lane serves no `GetTokenizer` bundle, so the gateway needs `--model-path` (`workflow/tokenizer_registration.rs`).

## Recipe A: Extend a wire field

**Field order IS the wire contract.** Every data-plane message is a msgspec `array_like` struct: a positional msgpack array, not a map. Reordering or inserting silently misreads every later field.

1. Read the upstream shape first: vLLM `rust/src/engine-core-client`, TokenSpeed `runtime/engine/io_struct.py`. `engine_zmq_client` is a clean-room port, not a dependency.
2. **Append** the field at the end of the struct, never insert. vLLM structs derive `Serialize_tuple` / `Deserialize_tuple` — mark the new field `#[serde(default)]` so an older engine's shorter array still decodes.
3. TokenSpeed structs hand-roll `visit_seq`: add a `next_field(&mut seq, "name")?` (required) or `seq.next_element::<T>()?.unwrap_or_default()` (appended tail, zero from older senders) **before** the closing `drain_trailing(&mut seq)?`, and mirror it in `serialize_element` order. `expect_tag` validates element 0 (the `_tag` class name).
4. A newer engine always sends a longer array than this client models: keep the tolerance (`TrailingTolerant` / `deserialize_tolerant_seq` on the vLLM side, `drain_trailing` on TokenSpeed).
5. Add a msgpack round-trip test beside the struct, plus a short-array case proving an older sender still decodes.

**Verify:** `cargo test -p engine-zmq-client`

## Recipe B: Surface a request/response feature on the ZMQ lane

The ZMQ lane consumes the same proto `GenerateRequest` the gRPC builders produce, then the adapter translates it per dialect.

1. Request building is already shared: `BackendClient::build_{chat,messages,completion,generate}_request` dispatch through `build_zmq_request` / `build_zmq_plain_request` on `ZmqDialect` and yield the dialect's `ProtoGenerateRequest` variant.
2. Map the proto field onto the wire in the dialect module of `crates/engine_zmq_adapter/src/`: `vllm.rs` (`translate_request`, `translate_sampling`, `translate_constraint`), `tokenspeed.rs` (`translate_request_tokenspeed_for`, `translate_sampling_tokenspeed`, `apply_tokenspeed_constraint`), `sglang.rs` (`translate_request_sglang`, `translate_sampling_sglang`), `trtllm.rs`.
3. Shape the response in the dialect's `map_output` (`VllmGenerateStream::map_output` / `TokenSpeedGenerateStream::map_output`). Both implement `MappedGenerateStream`; `poll_mapped` owns the `Stream` machinery and the parked terminal `Complete` — do not re-derive `Stream` by hand.
4. Never add stop-string handling here. This is a **token-only wire**: `BackendClient::finalize_generate_request` calls `resolve_string_stops(.., token_only_wire = true)` and `fold_tokenizer_eos_backstop` (`engine_zmq_adapter/src/eos.rs`, `stops.rs`), returning the residual stop strings response processing must trim from output text. EOS ids come from `EosTokenIds` (local model dir at connect, else `adopt_tokenizer_eos`).
5. Dialect-specific behaviour matches on `ZmqDialect` — write all four arms. The existing sites are `backend_client.rs`, `routers/grpc/harmony/stages/request_building.rs`, and `routers/grpc/multimodal/assemble.rs`. Multimodal splits proto tensors into per-item `mm_features` in `engine_zmq_adapter/src/multimodal.rs::build_mm_features` (inline bytes; no SHM/RDMA on this wire).

**Verify:** `cargo test -p engine-zmq-adapter && cargo test -p smg zmq`

## Recipe C: Add a fifth dialect

1. Wire: a new `protocol/<engine>/` module in `engine_zmq_client` plus a zero-sized `EngineProtocol` impl (`add_frame`, `abort_frame`, `request_id`, `data_parallel_rank`, `validate`, `encode_add`, `encode_abort`, `encode_start_wave`, `decode_batch`), a `Client<P>` alias in `connector.rs`, re-exports in `lib.rs`. Map the engine's native scheduler stats onto `EngineLoad` or the connector cannot load-balance its ranks.
2. Adapter: a dialect module (`<engine>.rs`) with the proto → wire translation and `map_output`; a `ZmqDialect` variant; a `RuntimeType` → dialect arm in `ZmqEngineClient::connect` (`client.rs`); arms in every `match` on `ZmqDialect` (the compiler lists them — there are no wildcards).
3. Gateway: a `ProtoGenerateRequest` variant and `ZmqBuilders` arms in `backend_client.rs`, then the other `ZmqDialect` matches (harmony, multimodal).
4. Registration: the runtime allowlist in `create_worker.rs` and the unspecified-runtime default in `detect_backend.rs` (`ConnectionMode::Zmq` arm).
5. Launcher: a `WorkerLauncher` with `_build_zmq_command` in `bindings/python/src/smg/serve.py`, plus the e2e `infra/worker.py::_build_<engine>_zmq_cmd`.

**Verify:** `cargo test -p engine-zmq-client && cargo test -p engine-zmq-adapter && cargo test -p smg zmq`

## Recipe D: Lifecycle and config knobs

- Per-worker: `WorkerSpec.zmq_handshake_address` — `tcp://` only, overrides the port `derive_handshake_port` folds out of the `ipc://` path (FNV-1a into 20000..=29999). `dp_size` on a ZMQ spec means a **grouped** worker (one socket set, N engines dialing in), not dp-aware expansion.
- Gateway-wide: `RouterConfig.zmq_engine_count` (CLI `--zmq-engine-count`) and `startup_worker_runtime_type` (`--backend vllm|tokenspeed|...`, which pins a runtime **only** over ZMQ — the shared handshake carries no engine identity). Both are stamped onto startup workers by `job_queue.rs::apply_startup_worker_config`. Co-apply @config-plumbing.md and @bindings-update.md.
- New validation belongs in `create_worker.rs` beside `validate_zmq_handshake_override` / `validate_zmq_handshake_address` / `validate_zmq_worker_type` / `validate_zmq_dp` — reject at registration; a connect-time rejection strands the worker in `Pending` forever.
- Promotion is event-driven: `spawn_zmq_connect_driver` (`worker/basic.rs`) sends `WorkerConnected { url, revision }` to `manager.rs::apply_connect_signal` (wired via `registry.connect_signal_sender()`). The revision check discards a signal a same-URL replacement raced past.
- `update_worker_properties.rs` must preserve the ZMQ backend client when it rebuilds a worker.

**Verify:** `cargo test -p smg` and `cd bindings/python && pytest -q tests/test_serve.py`

## Local testing and CI

- **No GPU:** `cargo run -p mock-worker -- --zmq-handshake tcp://127.0.0.1:<port> --zmq-count 2` (`--zmq-start-index` sets the first rank's engine index). `<port>` is `derive_handshake_port` of the worker's ipc path — mirror it with `python -c "from smg.serve import _zmq_handshake_port; print(_zmq_handshake_port('ipc:///tmp/...'))"`. The gateway needs `--model-path <local model dir>` (model identity plus EOS ids), `--backend vllm`, and `--zmq-engine-count 2` for the grouped form. mock-worker speaks the vLLM dialect.
- **In-process:** `mock_engine::{connect_to_frontend, MockEngine, default_ready_response}` under the `mock-engine` feature; see the tests in `routers/grpc/zmq_client.rs`, `worker/basic.rs`, and `update_worker_properties.rs`.
- **Real engine:** `crates/engine_zmq_client/examples/live_probe.rs` against `vllm serve <model> --headless --data-parallel-address 127.0.0.1 --data-parallel-rpc-port <port>`.
- **E2E:** `E2E_CONNECTION_MODE=zmq` (plus `E2E_ZMQ_ENGINE_COUNT=2`) reruns the local chat suite over ZMQ; `fixtures/hooks.py::_filter_zmq_items` deselects PD/EPD/multi-worker cases and collapses the grpc/http twins. CI lanes `e2e-1gpu-chat-zmq` and `e2e-2gpu-chat-zmq-dp` are gated by a path filter that includes `crates/engine_zmq_client/**`; the Rust servicer lane `e2e-1gpu-chat-rust-servicer` exercises the adapter from `crates/engine_servicer`. CPU harness gate: `PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra e2e_test/fixtures`.

## Key rules

- SMG binds every socket; the engine dials in. Never invert this — the operator launches the engine second.
- Positional field order is the wire contract. Append only; `#[serde(default)]` (vLLM) or a defaulting `next_element` before `drain_trailing` (TokenSpeed).
- Never await the handshake on a request, probe, or load-poll path. `get_backend_client` peeks the `OnceCell`, kicks `spawn_zmq_connect_driver`, and returns unavailable; a model load can outlast any caller's deadline.
- ZMQ workers stay `Pending` until `WorkerConnected` lands. Anything that can fail must fail at registration instead.
- Token-only wire: string stops and EOS are resolved frontend-side (`eos.rs`, `stops.rs`); the router keeps the residual trim obligation.
- Keep `derive_handshake_port` (`routers/grpc/zmq_client.rs`) and `_zmq_handshake_port` (`serve.py`) byte-identical; `test_serve.py` pins the expected values.
- `n > 1` is fanned out into independent single-sample engine requests (`fanout.rs`), merged by `SelectAll` and tagged with the choice `index`.
- Liveness is local and latched (`is_alive`, set false on `ENGINE_CORE_DEAD_SENTINEL` or transport failure); there is no health RPC. Dropping a stream auto-aborts the engine-side request.

## Anti-patterns

- Adding a ZMQ arm to `GrpcClient` (`routers/grpc/client.rs`). The transport seam is `BackendClient`; `GrpcClient` stays pure gRPC.
- Translating in the gateway seam instead of the adapter: `routers/grpc/zmq_client.rs` adapts `engine-zmq-adapter` to the pipeline; wire translation lives in the adapter so the Rust servicer gets it too.
- Following @grpc-backend.md for a ZMQ engine: there is no proto file, no `impl_engine_client_basics!`, no `detect_grpc_backend` probe entry, and no `fetch_grpc_metadata` — the handshake reports the metadata.
- A wildcard `_ =>` arm on `ZmqDialect`. It hides the site a new dialect must update.
- Enabling `mock-engine` outside `dev-dependencies` / `mock-worker`. It is a test driver, not a shipped path.

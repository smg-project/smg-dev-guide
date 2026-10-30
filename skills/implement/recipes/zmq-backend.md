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
exemplars:
  - 2dba4435   # feat: SGLang over the direct ZMQ wire (a dialect)
  - e5583a30   # feat: TensorRT-LLM servicer and dialect
  - 400ca274   # feat: multimodal over TokenSpeed ZMQ (a feature on the lane)
  - 9ccb557c   # feat: TokenSpeed output columns (a wire field)
---

# Extend the ZMQ direct backend

When SMG and the engine share a host, the gRPC path collapses to a direct ZMQ connection over `ipc://`. Three layers: the **wire** (`crates/engine_zmq_client`: transport, msgpack codec, per-engine protocol structs), the **engine adapter** (`crates/engine_zmq_adapter`: each engine's gRPC-proto surface translated onto the wire, plus the frontend duties a tokenizer-less engine cannot do), and the **gateway seam** (`model_gateway/src/routers/grpc/zmq_client.rs`, `backend_client.rs`, `worker/basic.rs`). The adapter is shared with `crates/engine_servicer`, so a translation fix lands in both lanes. SMG binds the `tcp://` handshake and `ipc://` sockets; the engine dials in.

Not this recipe: a gRPC engine client (@grpc-backend.md); the Rust servicer itself (@engine-servicer.md); gateway knobs end to end (@config-plumbing.md).

## Inputs

| Input | Example | Used in |
|---|---|---|
| dialect | `ZmqDialect::{Vllm, TokenSpeed, Sglang, Trtllm}` (`engine_zmq_adapter/src/client.rs`), a closed set | every `match` |
| upstream wire shape | vLLM `rust/src/engine-core-client`, TokenSpeed `runtime/engine/io_struct.py` | A |
| proto field to carry | a `GenerateRequest` field the gRPC builders already produce | B |
| engine-side handshake | SGLang plugin, TRT-LLM shim (`grpc_servicer/smg_grpc_servicer/`) | C |

## Steps

### A1. Wire field (append only)

File: `crates/engine_zmq_client/src/protocol/vllm/` or `protocol/tokenspeed/` — Do: every data-plane message is a positional msgpack array (msgspec `array_like`); append the field at the end, never insert. vLLM structs derive `Serialize_tuple` / `Deserialize_tuple`: mark it `#[serde(default)]`. TokenSpeed structs hand-roll `visit_seq`: add a `next_field(&mut seq, "name")?` (required) or `seq.next_element::<T>()?.unwrap_or_default()` (appended tail) before `drain_trailing(&mut seq)?`, mirrored in `serialize_element` order; `expect_tag` checks element 0. Keep the tolerance for longer arrays from newer engines (`TrailingTolerant`, `deserialize_tolerant_seq`, `drain_trailing`; shared helpers in `protocol/positional.rs`).
Verify: `cargo test -p engine-zmq-client` with a round-trip test and a short-array test beside the struct
Trap: a field inserted mid-struct misreads every later field against a real engine, silently.

### B1. Feature on the lane: translate

File: `crates/engine_zmq_adapter/src/vllm.rs`, `tokenspeed.rs` (`translate_request_tokenspeed_for`, `translate_sampling_tokenspeed`, `apply_tokenspeed_constraint`), `sglang.rs` (`translate_request_sglang`, `translate_sampling_sglang`), `trtllm.rs` — Do: map the proto field onto the wire in each dialect the feature applies to. Request building is already shared: `BackendClient::build_{chat,messages,completion,generate}_request` dispatch through `build_zmq_request` / `build_zmq_plain_request` on the dialect.
Verify: `cargo test -p engine-zmq-adapter`

### B2. Feature on the lane: response and stops

File: the dialect's `map_output` (`VllmGenerateStream::map_output`, `TokenSpeedGenerateStream::map_output`; both implement `MappedGenerateStream`, `poll_mapped` owns the `Stream` machinery) — Do: shape the response there. Stops and EOS stay frontend-side: `BackendClient::finalize_generate_request` calls `resolve_string_stops(.., token_only_wire = true)` and `fold_tokenizer_eos_backstop` (`engine_zmq_adapter/src/eos.rs`, `stops.rs`); EOS ids come from `EosTokenIds` (local model dir at connect, else `adopt_tokenizer_eos`). Multimodal tensors become per-item `mm_features` in `engine_zmq_adapter/src/multimodal.rs::build_mm_features`.
Verify: `cargo test -p smg zmq`
Trap: a stop string sent over the wire never fires (the engine has no tokenizer) and generation runs to the context window.

### C1. New dialect: wire and adapter

File: `crates/engine_zmq_client/src/protocol/<engine>/` — Do: a zero-sized `EngineProtocol` impl (`add_frame`, `abort_frame`, `request_id`, `data_parallel_rank`, `validate`, `encode_add`, `encode_abort`, `encode_start_wave`, `decode_batch`), a `Client<P>` alias in `connector.rs`, re-exports in `lib.rs`; map the engine's scheduler stats onto `EngineLoad` or the connector cannot balance its ranks. File: `crates/engine_zmq_adapter/src/<engine>.rs` + a `ZmqDialect` variant + a `RuntimeType` → dialect arm in `ZmqEngineClient::connect` (`client.rs`); the compiler lists every `match` to extend because none has a wildcard.
Verify: `cargo test -p engine-zmq-client && cargo test -p engine-zmq-adapter`

### C2. New dialect: gateway, servicer, launcher

File: `model_gateway/src/routers/grpc/backend_client.rs` — Do: a `ProtoGenerateRequest` variant and `ZmqBuilders` arms, then the other `ZmqDialect` matches (`routers/grpc/harmony/stages/request_building.rs`, `routers/grpc/multimodal/assemble.rs`). File: `workflow/steps/local/create_worker.rs` (runtime allowlist beside `validate_zmq_worker_type`), `detect_backend.rs` (the `ConnectionMode::Zmq` default), `discover_metadata.rs` (`zmq_model_labels`: the handshake reports no model labels, so the gateway derives labels and sampling defaults from the model directory). File: `grpc_servicer/smg_grpc_servicer/<engine>/` — Do: the engine-side plugin or shim that performs the handshake, and the Rust servicer module in `crates/engine_servicer/src/<engine>/` (@engine-servicer.md). File: `bindings/python/src/smg/serve.py` (`_build_zmq_command`), `e2e_test/infra/worker.py`, `e2e_test/fixtures/hooks.py` (`_filter_zmq_items`), the path filters in `.github/workflows/pr-test-rust.yml` and `e2e-gpu-job.yml`.
Verify: `cargo test -p smg zmq && cd bindings/python && pytest -q tests/test_serve.py` and `PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra`
Trap: a dialect without a mock arm in `crates/mock_worker` never runs in the CPU lanes.

### D1. Lifecycle knobs

File: `model_gateway/src/workflow/steps/local/create_worker.rs` — Do: new validation beside `validate_zmq_handshake_override`, `validate_zmq_handshake_address`, `validate_zmq_worker_type`, `validate_zmq_dp`: reject at registration. Per-worker `WorkerSpec.zmq_handshake_address` (`tcp://` only) overrides the port `derive_handshake_port` (`routers/grpc/zmq_client.rs`) folds out of the `ipc://` path; `dp_size` on a ZMQ spec means a grouped worker (one socket set, N engines dialing in). Gateway-wide knobs (`--zmq-engine-count`, `--backend <runtime>`) are stamped on startup workers by `job_queue.rs::apply_startup_worker_config` (@config-plumbing.md, @bindings-update.md).
Verify: `cargo test -p smg` and `cd bindings/python && pytest -q tests/test_serve.py` (pins `_zmq_handshake_port` against `derive_handshake_port`)
Trap: a connect-time rejection strands the worker in `Pending` forever; promotion is the `WorkerConnected` signal from `spawn_zmq_connect_driver` (`worker/basic.rs`) to `manager.rs::apply_connect_signal`, and `update_worker_properties.rs` must keep the backend client.

### E. Gate

Run `smg:contribute`. Lanes: `e2e-1gpu-chat-zmq`, `e2e-2gpu-chat-zmq-dp` (`E2E_CONNECTION_MODE=zmq`, `E2E_ZMQ_ENGINE_COUNT=2`), `e2e-1gpu-chat-rust-servicer`. Without a GPU: `cargo run -p mock-worker -- --zmq-handshake tcp://127.0.0.1:<port> --zmq-count 2` with `--model-path`, `--backend vllm`, `--zmq-engine-count 2` on the gateway; in-process `mock_engine::{connect_to_frontend, MockEngine, default_ready_response}` under the `mock-engine` feature; a real engine with `crates/engine_zmq_client/examples/live_probe.rs`.

## Rules

- Never await the handshake on a request, probe or load-poll path: `get_backend_client` peeks the `OnceCell`, kicks the driver and returns unavailable.
- Health checks stay on (`resolve_zmq_health_config`): the probe is the only path that reconnects a restarted engine; liveness is latched on `ENGINE_CORE_DEAD_SENTINEL`.
- `n > 1` fans out into single-sample engine requests (`fanout.rs`) merged by `SelectAll`.
- The lane serves no `GetTokenizer` bundle: the gateway needs `--model-path` (`workflow/tokenizer_registration.rs`).
- What a dialect supports beyond chat (embeddings `embed.rs`, structured outputs `structured_outputs.rs`, admin calls `admin.rs`) is decided in the adapter; unsupported admin calls return `zmq_admin_unsupported` (`worker/basic.rs`).

---
recipe: engine-servicer
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/engine_servicer/src/
  - bindings/python/src/servicer.rs
  - bindings/python/src/smg/servicer.py
  - bindings/python/tests/test_servicer_args.py
  - grpc_servicer/smg_grpc_servicer/rust_lifecycle.py
exemplars:
  - e5583a3019c4b2efbdae0116727e8186272dbcd6   # a Rust servicer for the TensorRT-LLM contract, with its binding and launcher
  - 8f5b4e32a18891cbd28685cd669ae3fe9cbb9c2f   # StartProfile/StopProfile on the vLLM wire, both servicers
  - a35c0fa3641682b82ce77e475f66acd748436e5f   # the TokenSpeed servicer's control RPCs ride the wire's control call
---

# Add an engine servicer

`crates/engine_servicer` (package `engine-servicer`) serves an engine's own gRPC proto, the contract the Router speaks to the Python servicer in `grpc_servicer/`, on the engine's node over the same-host msgpack ZMQ wire through `engine-zmq-adapter`'s `ZmqEngineClient`; the Router cannot tell the two servicers apart.
One module per engine (`vllm/`, `sglang/`, `tokenspeed/`, `trtllm/`) adds its proto and model facts on top of the engine-neutral `Shared` state and `Server` lifecycle in `crates/engine_servicer/src/servicer.rs`; the shared config block is `ServicerConfig` (`crates/engine_servicer/src/servicer_config.rs`).
Python keeps the lifecycle only: the launcher, a `RustLauncher` subclass in `grpc_servicer/smg_grpc_servicer/<engine>/rust.py` chosen by `--servicer-impl rust` or `SMG_<ENGINE>_SERVICER_IMPL=rust`, constructs the PyO3 class from `bindings/python/src/servicer.rs`, starts the headless engine against the server's handshake, polls `engine_ready` and `last_error`, drains with `set_serving(False)`, then calls `stop`.

Not this recipe:
- A wire struct, a new `ZmqDialect` with its `EngineProtocol`, or a translation in `crates/engine_zmq_adapter/src/`: @zmq-backend.md (Recipes A to C). The servicer translates nothing; step 1 only confirms the dialect exists.
- The engine's proto in `crates/grpc_client/proto/` and the Router's tonic client: @grpc-backend.md.
- The gateway's own direct-ZMQ lane (`BackendClient`, `model_gateway/src/routers/grpc/zmq_client.rs`): @zmq-backend.md. The servicer is the adapter's other consumer.

## Inputs

| Input | Example | Used in |
|---|---|---|
| Engine word: module name, `WIRE` metrics label, server thread name | `trtllm`, `smg-trtllm-servicer` | 2 |
| Service name as the health service reports it | `trtllm.TrtllmService` (`SERVICE_NAME`) | 2 |
| Generated tonic server and the engine's `RuntimeType` variant | `trtllm_proto::trtllm_service_server::TrtllmServiceServer`, `RuntimeType::Trtllm` | 2, 3 |
| The dialect's adapter entrypoints | `generate_trtllm_streams`, `to_trtllm_response`, `TrtllmGenerateStream` | 1, 4 |
| Launcher facts: what the engine's Python servicer reads off its arguments | `TrtllmModelInfo` (`max_seq_len`, `guided_decoding_backend`, `kv_events_endpoint`) | 2, 5, 6 |
| Binding class and the engine's switch variable | `TrtllmGrpcServer`, `SMG_TRTLLM_SERVICER_IMPL` | 5, 6, 8 |

## Steps

### 1. Confirm the adapter dialect it rides on

File: `crates/engine_zmq_adapter/src/client.rs` — Do: check the `ZmqDialect` variant, its `RuntimeType` arm in `ZmqEngineClient::connect`, a `generate_<engine>_streams` method and the `ZmqModelInfo` / `ZmqServerInfo` variants exist; the dialect module (`crates/engine_zmq_adapter/src/trtllm.rs` for TensorRT-LLM) holds the request translation and the output mapping. Anything missing is @zmq-backend.md Recipe C, done first.
Verify: `grep -n "fn generate_<engine>" crates/engine_zmq_adapter/src/client.rs` → the one-shot and the `_streams` form
Trap: `RuntimeType::Unspecified` maps to `ZmqDialect::Vllm` there; a servicer that passes it completes the shared handshake and decodes the wrong wire.

### 2. Create the per-engine module

File: `crates/engine_servicer/src/<engine>/mod.rs` — Do: copy `crates/engine_servicer/src/trtllm/mod.rs` (the smallest): `SERVICE_NAME`, `WIRE`, `HEALTHY` (the Python servicer's own health word), `<Engine>ModelInfo` (launcher facts; 0 or empty falls back to the handshake), `<Engine>ServicerConfig { servicer: ServicerConfig, model }`, `State { model, shared: Shared }` with `impl WireState` and `impl RankLoads` (`rank_load`, `engine_link`), and `<Engine>ServicerServer::start`: `config.servicer.validate()`, `KvEventRelay::for_publisher`, `ServicerMetrics::new`, `Shared::new`, the tonic server in `Routes::new`, then `servicer::Server::start` with the thread name, `SERVICE_NAME`, the routes and `move |inputs| engine::connect_engine(connect_state, inputs)`. Keep every lifecycle delegation of `TrtllmServicerServer` (`address`, `engine_ready`, `note_engine_alive`, `set_serving`, `set_ready`, `kv_relay_subscribed`, `active_requests`, `last_error`, `stop`): the binding calls each. Register in `crates/engine_servicer/src/lib.rs` (`pub mod <engine>;` plus the `pub use` of the three types) and add the engine's `<ENGINE>_DISABLED_MESSAGE` beside `TRTLLM_DISABLED_MESSAGE` in `crates/engine_servicer/src/kv_events.rs`.
Verify: `cargo check -p engine-servicer` → clean
Trap: `Identity { matches_string_stops, processes_media, .. }` (`crates/engine_servicer/src/metrics.rs`) decides which metric families register; a wrong flag exports series the servicer never increments, or none, and nothing fails.

### 3. Connect the engine

File: `crates/engine_servicer/src/<engine>/engine.rs` — Do: `connect_engine(state, inputs)` calls `engine_link::connect_engine` (`crates/engine_servicer/src/engine_link.rs`) with `&state.shared.engine`, the `model_path`, the `eos_token_ids`, `RuntimeType::<Engine>`, `PeerWords { peer, party }` (the engine's own words for the log lines), the `ConnectInputs` and a `configure` closure that runs on the connected `ZmqEngineClient` before it is published (TensorRT-LLM: `set_structured_outputs_support` from the launcher's `guided_decoding_backend`). Nothing here retries: a failure gates health and lands in `last_error`, and the launcher restarts the pair.
Verify: `cargo check -p engine-servicer` → clean

### 4. Serve the RPCs

File: `crates/engine_servicer/src/<engine>/service.rs` — Do: `#[tonic::async_trait]` impl of the generated trait over `Arc<State>`, one handler module per RPC family: `Generate` in `generate.rs` (`shared.registry.register` before the submit, `generate_<engine>_streams` with the `trace_headers`, one `ChoiceStream` per sub implementing `Choice` and `HeldTerminal` over `poll_engine_item`, merged by `RequestStream::new`); `HealthCheck` / `GetModelInfo` / `GetServerInfo` in `info.rs` (`health_message`, launcher facts with `shared.ready()` as the fallback, `engine_version`); `Abort` through `shared.registry.abort`; `GetTokenizer` through `tokenizer_bundle::get_tokenizer`; `SubscribeKvEvents` through `shared.kv_relay`, else `Status::unimplemented` with the engine's `<ENGINE>_DISABLED_MESSAGE`; `FlushCache` / `StartProfile` / `StopProfile` through `crate::admin` (`crates/engine_servicer/src/admin.rs`) on a control-call wire, or the engine's own `admin.rs` (vLLM's `profile_vllm` utility call). An RPC the Python servicer does not serve answers UNIMPLEMENTED naming the reason. Extending an engine (8f5b4e32) is the RPC in the proto, an arm here, its handler, the adapter call, and the same RPC in `grpc_servicer/smg_grpc_servicer/<engine>/`, in one change.
Verify: `cargo check -p engine-servicer` → clean
Trap: `generate` must `inspect_err` into `request_not_started` on `shared.metrics`; without it a refused request is missing from the metrics and every test passes.

### 5. Bind it for Python

File: `bindings/python/src/servicer.rs` — Do: a `#[pyclass(name = "<Engine>GrpcServer")]` over `<Engine>ServicerServer` modelled on `PyTrtllmGrpcServer`: the `#[new]` takes `bind_address`, `ipc_base_url`, `handshake_address`, `model_path` positionally, then keyword-only model facts and the shared knobs under the names and defaults `SHARED_DEFAULTS` lists (`bindings/python/tests/test_servicer_args.py`), converted by `startup_timeout` / `startup_ceiling` / `silence_timeout` / `prefill_tokens_per_sec`, starts the server under `py.detach`, and exposes the same getters and methods. Register it with `add_class` in the `smg_rs` module of `bindings/python/src/lib.rs` and re-export it (and `__all__`) in `bindings/python/src/smg/servicer.py`.
Verify: `make python-dev && python -c "from smg.servicer import <Engine>GrpcServer"` → imports
Trap: a shared knob renamed or defaulted differently compiles and runs; only `SERVERS` in `test_servicer_args.py` (step 7) pins it, and only for the classes listed there.

### 6. Write the launcher

File: `grpc_servicer/smg_grpc_servicer/<engine>/rust.py` — Do: subclass `RustLauncher` (`grpc_servicer/smg_grpc_servicer/rust_lifecycle.py`): the class attributes (`engine`, `server_class`, `ipc_prefix`, the `*_env` names) and the hooks `facts` (the `<Engine>ModelInfo` fields as the Python servicer computes them), `tokenizer_dir`, `kv_events_default`, `launch` (the headless engine or shim, dialing the handshake port); `serve_rust`, `serve_rust_from_engine` and `resolve_servicer_impl` (`servicer_switch`: flag, else variable, else python). `SERVICER_IMPL_ENV`, `METRICS_PORT_ENV` and `METRICS_HOST_ENV` go in the package `__init__.py` (stdlib only: the engine's plugin imports it), `--servicer-impl` via `add_servicer_impl_argument` (`grpc_servicer/smg_grpc_servicer/servicer_impl_flag.py`) on the package's `__main__.py`, and the engine's section in `grpc_servicer/README.md`.
Verify: `python -m smg_grpc_servicer.<engine> --help` → `--servicer-impl {python,rust}` and `--metrics-port` listed
Trap: an engine entrypoint that never consults the switch starts the Python servicer with `SMG_<ENGINE>_SERVICER_IMPL=rust` exported and says nothing; vLLM guards this with `require_upstream_hook` (`grpc_servicer/smg_grpc_servicer/vllm/rust.py`).

### 7. Test every layer

File: `crates/engine_servicer/src/<engine>/tests.rs` — Do: copy the `Harness` of `crates/engine_servicer/src/trtllm/tests.rs`: `testing::servicer_config`, a mock engine from `connect_to_frontend` (the `mock-engine` feature, a dev-dependency) answering the wire's records, a tonic client over `grpc_channel`; cover streaming and non-streaming generate, abort, duplicate ids, `n > 1` fan-out, the health drain, the info RPCs (launcher facts plus handshake) and `the_unimplemented_rpcs_say_why`. Python: `grpc_servicer/tests/test_<engine>_rust_servicer.py` with a fake `smg.servicer` class injected (as `test_trtllm_rust_servicer.py` does), the launcher added to `LAUNCHERS` in `grpc_servicer/tests/test_servicer_switch.py`, and the binding class added to `SERVERS` in `bindings/python/tests/test_servicer_args.py`.
Verify: `cargo test -p engine-servicer <engine>::`, `cd bindings/python && pytest -q tests/test_servicer_args.py`, `pytest -q grpc_servicer/tests -rs` → all pass; `SERVERS` fails on a shared argument whose name, default or refusal message differs
Trap: `SERVERS` pins only the classes it lists (`TrtllmGrpcServer` is absent today); a class left out passes every run unchecked.

### 8. Put it on the CI lane

File: `.github/workflows/pr-test-rust.yml` — Do: `e2e-1gpu-chat-rust-servicer` runs the chat suite once per engine row with `servicer_impl: rust`; `.github/workflows/e2e-gpu-job.yml` turns that into `E2E_<ENGINE>_SERVICER_IMPL`, which the harness (`SERVICER_IMPL_VARIABLES` in `e2e_test/infra/constants.py`, exported to the gRPC worker's environment in `e2e_test/infra/worker.py`) hands to the launcher as `SMG_<ENGINE>_SERVICER_IMPL`. Add the engine's row and its variable in both files, and, where the Rust path does not serve a case the Python one does, a deselection filter in `e2e_test/fixtures/hooks.py` so the row's `min_selected` floor stays honest. `crates/engine_servicer/**` already selects the `chat-completions` lanes and the `rust-engine` test set.
Verify: `PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra e2e_test/fixtures` → the servicer-implementation cases pass
Trap: a worker whose engine ignores the variable runs Python while the lane reports Rust coverage; `rust_servicer_needs_hook` in `worker.py` names the engines that must fail up front instead.

### 9. Gate

Run `smg:contribute`.

## Rules

- The Router cannot tell the servicers apart: a fact, a refusal or an RPC added on the Rust side lands in `grpc_servicer/smg_grpc_servicer/<engine>/` too, and the reverse.
- A translation fix belongs in `crates/engine_zmq_adapter/src/<engine>.rs`, where the gateway's direct lane gets it as well; TensorRT-LLM alone is servicer-only (`DIRECT_LANE_NOT_FOR_TRTLLM` in `model_gateway/src/routers/grpc/backend_client.rs`).
- `ServicerConfig` is the one block every engine takes, validated before anything binds with the field at fault named; engine facts come from the launcher and never from the engine's config at request time.
- Nothing in the crate retries or restarts an engine: `note_engine_alive` resets the handshake's silence bound, failures gate health and surface in `last_error`, and the launcher's supervision loop restarts the pair.
- `set_serving(false)` is the drain switch (health NOT_SERVING, admission closed, in-flight streams run until `stop`); `set_ready(false)` holds readiness while admitting the launcher's warm-up requests (`smg-warmup-<n>`) alone.
- Tests bound every wait with `Bounded::bounded()` (`crates/engine_servicer/src/testing.rs`) and put the `ipc://` handshake under the test's own directory, so a stalled servicer fails at the line and parallel tests never share a port.
- A servicer feature that changes what crosses the wire also lands in `crates/engine_zmq_client/src/protocol/` (@zmq-backend.md, step A1); five of the six recent servicer commits touched both crates.

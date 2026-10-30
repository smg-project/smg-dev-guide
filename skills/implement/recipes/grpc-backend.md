---
recipe: grpc-backend
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/grpc_client/src/
  - crates/grpc_client/proto/
  - crates/mock_worker/src/grpc.rs
  - model_gateway/src/routers/grpc/client.rs
  - model_gateway/src/routers/grpc/pipeline.rs
  - model_gateway/src/routers/grpc/common/stages/
  - model_gateway/src/workflow/steps/local/detect_backend.rs
  - model_gateway/src/workflow/steps/local/discover_metadata.rs
exemplars:
  - 1b511e6f   # vLLM FlushCache RPC: proto, client macro, GrpcClient arm, Python servicer, e2e test
  - 8f5b4e32   # vLLM StartProfile/StopProfile: both servicers, every test that implements the tonic trait
  - 916c374e   # constrained_decoding worker label: proto, protocols, mock worker, builder, workflow steps, servicer binding
---

# Add a gRPC engine client

Engine clients live in the `smg-grpc-client` crate (`crates/grpc_client/src/`, package v1.15.0, tonic 0.14 with `tonic-prost`/`tonic-prost-build`), one file per engine (`sglang_scheduler.rs`, `vllm_engine.rs`, `trtllm_service.rs`, `mlx_engine.rs`, `tokenspeed_scheduler.rs`): each wraps its generated tonic client plus a `BoxedTraceInjector` and gets connect/health/info/tokenizer/admin from four macros in `lib.rs`.
The router layer (`model_gateway/src/routers/grpc/`) wraps every generative engine behind the `GrpcClient` enum (`client.rs`) and owns request building, streaming and tool/reasoning parsing; the client crate parses no output. Model a new engine on `vllm_engine.rs`.
No new engine client has landed since August 2026; the exemplars are RPC and label additions to existing engines, which step 7 covers.

Not this recipe:
- A worker URL of `ipc://` is the direct-ZMQ backend (no proto, no probe, no metadata RPC): @zmq-backend.md. `BackendClient` (`routers/grpc/backend_client.rs`, `enum BackendClient { Grpc(GrpcClient), Zmq(ZmqEngineClient) }`) is the gRPC-vs-ZMQ seam, what `acquire_clients` yields and what a worker holds (`BasicWorkerBuilder::backend_client`); never add ZMQ arms to `GrpcClient`, and a gRPC engine adds no arms there.
- `TokenSpeedEncoderClient` (`tokenspeed_encoder.rs`, proto `tokenspeed.grpc.encoder`) is the EPD encode client, not an enum variant: no `impl_engine_client_basics!`, a pooled `connect_cached` round-robin over `ENCODE_CONNS_PER_ENDPOINT` channels, one `encode()` RPC called from `common/stages/encode.rs`, still via `connect_channel` with trace injection.
- The Mode-parameterized pipeline is engine-agnostic; an engine adds arms, never stages. `GrpcRouter` (`router.rs`: `struct GrpcRouter { mode: Mode, .. }`, `GrpcRouter::new(ctx, mode)`, one `impl RouterTrait`; `embedding_pipeline`/`classify_pipeline` are `Some` only in `Mode::Regular`, `harmony_pipeline`/`responses_context`/`harmony_responses_context` are `None` only in EPD, those endpoints 501); `Mode` (`mode.rs`: `Regular`, `PrefillDecode`, `EncodePrefillDecode`; `grpc_mode(&RouterConfig)` is `Some` for `ConnectionMode::Grpc | ConnectionMode::Zmq`; each maps to a `WorkerSelectionMode`, an `ExecutionPlanKind`, `inject_pd_metadata()` and `router_type()` `"grpc"`/`"grpc_pd"`/`"grpc_epd"`); `RouterFactory::create_router` derives `mode = grpc_mode(cfg)` and calls `create_grpc_router(ctx, mode)`; `RequestPipeline::build(endpoint, mode, deps)` (`pipeline.rs`) composes the stages per endpoint, `EncodeStage` only for EPD, and `execute_chat` runs them; shared stages in `common/stages/` (`PipelineStage`/`BuildStage`/`ProcessStage` traits in `mod.rs`, `RateLimitReserveStage` in `rate_limit.rs` for every endpoint, `WorkerSelectionStage` in `worker_selection.rs`, `acquire_clients` in `client_acquisition.rs`, `prepare_dispatch_metadata` in `dispatch_metadata.rs`, `execute_plan` in `request_execution.rs`, `context_length.rs`, `pd_protocol.rs`, `EncodeStage` in `encode.rs`); endpoint stages in `regular/stages/` (`chat|completion|generate|messages|decisions|embedding|classify|transcription/` plus `preparation.rs`, `reading.rs`, `rendered_prompt.rs`, `request_building.rs`, `backed_plan.rs`, `response_processing.rs`), `regular/processor.rs`, `regular/streaming.rs`; `regular/` backs all modes. There is no gRPC `pd_router.rs`; the HTTP `routers/http/pd_router.rs:PDRouter` (`router_type() == "pd"`) is unrelated.

## Inputs

| Input | Example | Used in |
|---|---|---|
| `<engine>` | `vllm` | file `crates/grpc_client/src/<engine>_engine.rs` (or `_scheduler`/`_service`), client `<Engine>EngineClient`, runtime key `"<engine>"` |
| proto package | `vllm.grpc.engine` | `tonic::include_proto!`; generated client under `proto::<engine>_engine_client::...`; file `crates/grpc_client/proto/<engine>_engine.proto` |
| RPCs | `generate`, `embed`, `abort` | engine RPCs beyond the shared `health_check`/`get_model_info`/`get_server_info` |

## Steps

### 1. Add the proto and register it

File: `crates/grpc_client/build.rs` — Do: add `crates/grpc_client/proto/<engine>_engine.proto` to the engine pass (`build_server(true)`/`build_client(true)`, `extern_path(".smg.grpc.common", "crate::common_proto")`) and a `rerun-if-changed` line; `common.proto` is compiled first with no service codegen.
Verify: `cargo build -p smg-grpc-client` → the generated client and server modules exist.

### 2. Create the client file

File: `crates/grpc_client/src/<engine>_engine.rs` — Do: model on `vllm_engine.rs`:

```rust
#[expect(clippy::allow_attributes)]
pub mod proto {
    #![allow(clippy::all, clippy::absolute_paths, unused_qualifications)]
    tonic::include_proto!("<engine>.grpc.engine");
}
#[derive(Clone)]
pub struct <Engine>EngineClient { client: proto::<engine>_engine_client::<Engine>EngineClient<Channel>, trace_injector: BoxedTraceInjector }
impl <Engine>EngineClient {
    crate::impl_engine_client_basics!(proto::<engine>_engine_client::<Engine>EngineClient<Channel>, "<Engine>");
    crate::impl_get_tokenizer!(); crate::impl_subscribe_kv_events!(); crate::impl_admin_ops!();   // only those the proto has
    pub async fn generate(&self, req: proto::GenerateRequest) -> Result<tonic::Streaming<proto::GenerateResponse>, tonic::Status> {
        let mut request = Request::new(req);
        if let Err(e) = self.trace_injector.inject(request.metadata_mut()) { warn!("Failed to inject trace context: {}", e); }
        Ok(self.client.clone().generate(request).await?.into_inner())
    }
}
```

The macros (`crates/grpc_client/src/lib.rs`): `impl_engine_client_basics!($proto_client, $display_name)` gives the two `connect` constructors, `with_trace_injector`, `health_check`/`get_model_info`/`get_server_info` and needs the proto's `HealthCheckRequest`/`GetModelInfoRequest`/`GetServerInfoRequest` and responses; `impl_get_tokenizer!()` (`get_tokenizer() -> StreamBundle`) and `impl_subscribe_kv_events!()` (`subscribe_kv_events(start_sequence_number)`) use `common_proto`; `impl_admin_ops!()` gives `flush_cache(timeout_s)`, `start_profile(req)`, `stop_profile()` under `FLUSH_RPC_DEADLINE_MARGIN`/`PROFILE_RPC_DEADLINE`. sglang, vllm and tokenspeed use all four; trtllm skips `impl_admin_ops!`; mlx uses basics and `impl_get_tokenizer!` only. Either module naming works: `proto` re-exported as `<engine>_proto`, or a named module (`tokenspeed_proto` in `tokenspeed_scheduler.rs`, re-exported without alias). The proto-level builders the router calls (`build_generate_request_from_{chat,messages,completion}`, `build_plain_generate_request`, `build_generate_request_from_responses`, `build_embed_request`) belong in this file. For a streaming `generate` return `crate::AbortOnDropStream<proto::GenerateResponse, Self>`, `impl AbortOnDropClient` (its `abort_for_drop` calls your `abort_request`; `impl_abort_for_drop_with_reason!` does it for a reasoned abort), build with `AbortOnDropStream::new(stream, request_id, self.clone())`; the router calls `mark_completed()`, `defer_abort_until_first_item()` exists, and the detached drop-abort is bounded by `ABORT_RPC_DEADLINE` (10s). See `abort_on_drop.rs`.
Verify: `cargo clippy -p smg-grpc-client --all-targets --all-features -- -D warnings` → clean.
Trap: `#[expect(clippy::allow_attributes)]` is load-bearing: the workspace sets `allow_attributes = "warn"` and the generated service code carries outer `#[allow(...)]`; `common_proto` has no service codegen, so no `#[expect]` there (an unfulfilled `#[expect]` is itself a warning).

### 3. Export from the crate root

File: `crates/grpc_client/src/lib.rs` — Do: `pub mod <engine>_engine;` and `pub use <engine>_engine::{proto as <engine>_proto, <Engine>EngineClient};` beside the vLLM/SGLang lines (or the no-alias form `pub use tokenspeed_scheduler::{tokenspeed_proto, TokenSpeedSchedulerClient};`). Shared infrastructure stays here and in `channel.rs` (`connect_channel`, `DEFAULT_CONNECT_TIMEOUT` 10s, `connect_channel_with_timeout`, `normalize_grpc_endpoint`), `abort_on_drop.rs`, `tokenizer_bundle.rs`, and the `TraceInjector` trait with `NoopTraceInjector` and the `BoxedTraceInjector` alias.
Verify: `cargo check -p smg-grpc-client` → compiles.
Trap: a free trace-injection function compiles and bypasses the trait; injection goes through `self.trace_injector.inject(request.metadata_mut())`.

### 4. Wire the `GrpcClient` enum

File: `model_gateway/src/routers/grpc/client.rs` — Do: add the `<Engine>(<Engine>EngineClient)` variant, the `connect()` arm `"<engine>" => Ok(Self::<Engine>(<Engine>EngineClient::connect(url).await?))` (trtllm also answers to `"tensorrt-llm"`), and arms in every exhaustive match: `health_check()`, `get_model_info()`, `get_server_info()`, `runtime_type()`, `get_tokenizer()`, `build_{chat,messages,completion,generate}_request()`, the `ModelInfo`/`ServerInfo` `to_labels()`. Opt-in RPCs: `get_loads()` (sglang/vllm/tokenspeed; a `_ =>` unimplemented default, compiles without an arm), `flush_cache()`/`start_profile()`/`stop_profile()` (sglang/vllm/tokenspeed; `Self::Trtllm(_) | Self::Mlx(_)` is one explicit unimplemented arm, no wildcard), `subscribe_kv_events(start_seq)` (sglang/vllm/trtllm/tokenspeed; `Self::Mlx(_)` explicit; consumer `model_gateway/src/worker/kv_event_monitor.rs`).
Verify: `cargo check -p smg` → every exhaustive match names the variant.
Trap: `generate()`/`embed()` are tuple matches on `(Self, ProtoGenerateRequest)`/`(Self, ProtoEmbedRequest)` ending in `_ => panic!(...)`: a missing arm compiles and panics on the first request.

### 5. Add the arms the enum drags in

File: `crates/protocols/src/worker.rs` — Do: a `RuntimeType` variant with `as_str()` and `FromStr` arms (its lowercase string is the runtime key `GrpcClient::connect` and `detect_grpc_backend` pass around; `GrpcClient::runtime_type()`, `common/stages/request_execution.rs` and `routers/grpc/multimodal/capability.rs` match on it). `routers/grpc/proto_wrapper.rs`: variants and arms in `ProtoGenerateRequest`, `ProtoGenerateResponse`, `ProtoGenerateStreamChunk`, `ProtoGenerateComplete`, `ProtoStream`, `ProtoEmbedRequest`/`ProtoEmbedComplete` for each surface the engine supports (`MultimodalData` only when multimodal; MLX is absent there). `routers/grpc/harmony/stages/request_building.rs`: the `(BackendClient::Grpc(GrpcClient::…), HarmonyBody::{Chat,Responses})` match has no engine wildcard; add Chat and Responses arms or one body-generic arm as vllm/tokenspeed do. `routers/grpc/regular/stages/embedding/request_building.rs`: a `build_embed_request` arm or an explicit `not_implemented`.
Verify: `cargo check -p smg --all-targets` → no non-exhaustive match.

### 6. Register detection and metadata

File: `model_gateway/src/workflow/steps/local/detect_backend.rs` — Do: add `"<engine>"` to the `["sglang", "vllm", "trtllm", "tokenspeed", "mlx"]` array `detect_grpc_backend` probes in order through `do_grpc_health_check` for `DetectBackendStep`. In `discover_metadata.rs`, `fetch_grpc_metadata` connects with `GrpcClient::connect`, merges `get_model_info()`/`get_server_info()` through `to_labels()`, and `normalize_grpc_keys` canonicalises engine spellings (`tensor_parallel_size -> tp_size`, `attn_tp_size -> tp_size`) and drops transient keys; the engine must surface `served_model_name`, `model_path`, `context_length`; SGLang's picked keys are `SGLANG_GRPC_KEYS` in `client.rs`.
Verify: `cargo test -p smg discover_metadata` (the `#[ignore]` cases need a live engine).
Trap: an engine missing from the array is reachable only with an explicit `runtime_type`; nothing fails.

### 7. Add an RPC or a worker label to an existing engine

File: `crates/grpc_client/proto/<engine>_engine.proto` — Do: an RPC edits the proto and regenerates the tonic service trait (`proto::vllm_engine_server::VllmEngine`), so every test that implements it needs a stub: `crates/grpc_client/tests/common/mod.rs`, `crates/grpc_client/tests/kv_event_decode_limit.rs`, `model_gateway/tests/grpc_pd_ttft_phases_test.rs`, `model_gateway/tests/grpc_pd_side_failure_codes_test.rs`, `model_gateway/tests/grpc_pd/*.rs`, `model_gateway/tests/grpc/tenant_rate_limiting_grpc_test.rs`, plus `crates/mock_worker/src/grpc.rs` and both servicer sides, `grpc_servicer/smg_grpc_servicer/<engine>/` (Python, tests in `grpc_servicer/tests/`) and `crates/engine_servicer/src/<engine>/` (Rust, its `tests.rs`); an admin RPC also joins `e2e_test/router/test_admin_ops.py` and its `GrpcClient` arm in step 4. A new worker label (`constrained_decoding`, `ConstrainedDecoding::LABEL` in `crates/protocols/src/worker.rs`) also lands in `model_gateway/src/worker/builder.rs`, `workflow/steps/local/create_worker.rs` (`validate_constrained_decoding_label`), `workflow/steps/local/update_worker_properties.rs`, `crates/mock_worker/src/grpc.rs` and `bindings/python/src/servicer.rs`.
Verify: `cargo test --workspace --no-run` → every trait implementation compiles.
Trap: `cargo test -p smg-grpc-client` passes while the `model_gateway/tests/*` stubs are still missing.

### 8. Tests

File: `crates/grpc_client/src/<engine>_engine.rs` — Do: a `#[cfg(test)] mod tests` like `vllm_engine.rs`'s (`test_generate_request_construction`, `test_sampling_params_defaults`, abort request construction); a refused or malformed endpoint is covered in `channel.rs` (`refused_endpoint`). Metadata tests live in `discover_metadata.rs`. gRPC routing passes `SelectWorkerInfo { tokens: Option<&[u32]>, .. }` (a struct, not an enum variant); cover token-aware policies there if relevant.
Verify: `cargo test -p smg-grpc-client` and `cargo test -p smg`.

### 9. Gate

Run `smg:contribute`.

## Rules

- One file and one client type per engine, never one generic file for several engines; use the macros for whatever they cover.
- Inject trace context on every outbound RPC; log and continue on failure.
- Connect only through `connect_channel` (`grpc://`/`grpcs://` normalisation, keep-alive); never build a raw `Channel`.
- Tool and reasoning parsing is a router concern (`routers/grpc/regular/` and `utils/parsers.rs`), not the client crate's.
- DP-rank pinning: the rank is set on the worker spec (`BasicWorkerBuilder::dp_config(rank, size)` in `model_gateway/src/worker/builder.rs`) and read via `worker.dp_rank()`.
- An RPC or label the ZMQ lane must also answer lands in `crates/engine_zmq_adapter/src/<engine>.rs` (@zmq-backend.md, step B1); the adapter is shared with the Rust servicer, so the servicer gets it too.

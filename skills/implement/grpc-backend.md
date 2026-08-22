# Adding a gRPC Backend Client to SMG

gRPC clients live in the `smg-grpc-client` crate (one file per engine) and talk to an inference backend (SGLang, vLLM, TRT-LLM, MLX, TokenSpeed — model a fresh engine on `vllm_engine.rs`; TokenSpeed is the odd one out, see the proto-naming note in Step 1). Each engine wraps its generated tonic client and shares connection/health/tokenizer/admin logic via four macros (see Step 1). The router layer (`model_gateway/src/routers/grpc/`) wraps all *generative* engines behind the `GrpcClient` enum and owns request building, streaming, and tool/reasoning parsing — the client crate does NOT parse output.

**Not this recipe:** a worker URL of `ipc://` is the direct-ZMQ backend (no proto, no probe, no metadata RPC) — see @zmq-backend.md. `BackendClient` (`routers/grpc/backend_client.rs`) is the gRPC-vs-ZMQ seam; never add ZMQ arms to `GrpcClient`.

> **Exception — `TokenSpeedEncoderClient` (`tokenspeed_encoder.rs`, proto `tokenspeed.grpc.encoder`).** A special-purpose EPD *encode* client that does **not** fit the engine pattern: it is not a `GrpcClient` enum variant, uses no `impl_engine_client_basics!`, and exposes a bespoke pooled `connect_cached` (round-robin over `ENCODE_CONNS_PER_ENDPOINT` channels) plus a single `encode()` RPC. It is called directly from the EPD encode stage (`routers/grpc/common/stages/encode.rs`), still injects trace context, and connects via `connect_channel`. If you are adding a generative engine, follow the enum pattern below; the encoder is its own thing.

## Inputs to gather first

| Input | Example | Notes |
|-------|---------|-------|
| `ENGINE` | `myengine` | Snake case. File name `{ENGINE}_engine.rs` (or `_scheduler`/`_service`), client `MyengineEngineClient`, runtime key `"myengine"` |
| Proto package | `myengine.grpc.engine` | The `tonic::include_proto!` path. Generated client type lives under `proto::myengine_engine_client::...` |
| RPCs | `generate`, `embed`, `abort` | Engine-specific RPCs beyond the shared `health_check`/`get_model_info`/`get_server_info` |

## Steps

### Step 1: Create the client file

**File:** `crates/grpc_client/src/{ENGINE}_engine.rs`

Model this on `vllm_engine.rs`. Pull the generated client in via a `proto` module, hold it plus a `BoxedTraceInjector`, and call `impl_engine_client_basics!` for the connect/health/info boilerplate.

```rust
use tonic::{transport::Channel, Request};
use tracing::warn;

use crate::BoxedTraceInjector;

#[expect(clippy::allow_attributes)]
pub mod proto {
    #![allow(clippy::all, clippy::absolute_paths, unused_qualifications)]
    tonic::include_proto!("myengine.grpc.engine");
}

#[derive(Clone)]
pub struct MyengineEngineClient {
    client: proto::myengine_engine_client::MyengineEngineClient<Channel>,
    trace_injector: BoxedTraceInjector,
}

impl MyengineEngineClient {
    // connect / connect_with_trace_injector / with_trace_injector +
    // health_check / get_model_info / get_server_info
    crate::impl_engine_client_basics!(
        proto::myengine_engine_client::MyengineEngineClient<Channel>,
        "MyEngine"
    );

    crate::impl_get_tokenizer!();        // get_tokenizer() -> StreamBundle      (if supported)
    crate::impl_subscribe_kv_events!();  // subscribe_kv_events(start_seq)        (if supported)
    crate::impl_admin_ops!();            // flush_cache / start_profile / stop_profile (if supported)

    pub async fn generate(
        &self,
        req: proto::GenerateRequest,
    ) -> Result<tonic::Streaming<proto::GenerateResponse>, tonic::Status> {
        let mut client = self.client.clone();
        let mut request = Request::new(req);
        // Inject W3C trace context; failures are logged, not fatal.
        if let Err(e) = self.trace_injector.inject(request.metadata_mut()) {
            warn!("Failed to inject trace context: {}", e);
        }
        Ok(client.generate(request).await?.into_inner())
    }
}
```

The `#[expect(clippy::allow_attributes)]` is load-bearing, not decoration: the workspace sets `allow_attributes = "warn"`, CI runs `cargo clippy --all-targets --all-features -- -D warnings`, and the *service* code tonic generates for your proto (register it in `crates/grpc_client/build.rs`, whose engine pass uses `build_server(true)`/`build_client(true)`) carries outer `#[allow(...)]` attributes that trip the lint. Every engine file carries it; `common_proto` — messages only, no service codegen — does not, and an unfulfilled `#[expect]` is itself a warning.

`impl_engine_client_basics!` requires the macro's `proto::HealthCheckRequest` / `GetModelInfoRequest` / `GetServerInfoRequest` / response types to exist in your `proto` module. `impl_get_tokenizer!`/`impl_subscribe_kv_events!` use `common_proto` types and need the matching RPCs on the generated client.

**Proto module naming — two conventions.** Older engines name the module `proto` and re-export it aliased: `pub mod proto { include_proto!(...) }` then `pub use {engine}_engine::{proto as {engine}_proto, ...}` (see `vllm_engine.rs` + `lib.rs`). The TokenSpeed pattern names the module `tokenspeed_proto` directly and re-exports it **without** an alias (see `tokenspeed_scheduler.rs` + `lib.rs`). Either naming works for the three `common_proto` macros, but `impl_engine_client_basics!` expands those `proto::*` paths *unqualified*, resolved at the call site — name the module `proto` if you want that macro. TokenSpeed did not, which is exactly why it hand-rolls connect/health/info.

**Four shared macros — use whichever your engine's proto supports** (all defined in `crates/grpc_client/src/lib.rs`):
- `impl_engine_client_basics!($proto_client, $display_name)` — the two `connect` constructors, `with_trace_injector`, and `health_check` / `get_model_info` / `get_server_info`.
- `impl_get_tokenizer!()` — `get_tokenizer() -> StreamBundle` (uses `common_proto`).
- `impl_subscribe_kv_events!()` — `subscribe_kv_events(start_sequence_number)` (uses `common_proto`).
- `impl_admin_ops!()` — `flush_cache(timeout_s)` (FlushCache RPC), `start_profile(req)`, `stop_profile()`, with local deadlines from `FLUSH_RPC_DEADLINE_MARGIN` / `PROFILE_RPC_DEADLINE`.

Macro use is per-engine/partial — pick only the ones whose RPCs exist on your generated client: sglang uses all four; vllm and trtllm use basics + `impl_get_tokenizer!` + `impl_subscribe_kv_events!`; mlx uses basics + `impl_get_tokenizer!` only (no kv_events); TokenSpeed uses `impl_get_tokenizer!` + `impl_admin_ops!` + `impl_subscribe_kv_events!` and **hand-rolls** connect/health/info (no `impl_engine_client_basics!` — see the proto-naming note above).

If `generate` is streaming, prefer the auto-abort wrapper: return `crate::AbortOnDropStream<proto::GenerateResponse, Self>`, `impl AbortOnDropClient for MyengineEngineClient` (its `abort_for_drop` calls your `abort_request`), and build it with `AbortOnDropStream::new(stream, request_id, self.clone())`. The router calls `mark_completed()` on success. See `abort_on_drop.rs`.

### Step 2: Export from the crate root

**File:** `crates/grpc_client/src/lib.rs`

Add `pub mod {ENGINE}_engine;` and re-export: `pub use {ENGINE}_engine::{proto as myengine_proto, MyengineEngineClient};` (mirror the existing vLLM/SGLang lines), or, if you named the proto module after the engine, the no-alias TokenSpeed form (e.g. `pub use tokenspeed_scheduler::{tokenspeed_proto, TokenSpeedSchedulerClient};`). The four shared macros (`impl_engine_client_basics!`, `impl_get_tokenizer!`, `impl_subscribe_kv_events!`, `impl_admin_ops!`) and the deadline constants `FLUSH_RPC_DEADLINE_MARGIN` / `PROFILE_RPC_DEADLINE` / `ABORT_RPC_DEADLINE` (10s bound on the detached drop-abort RPC) are defined here. Shared infra also lives here: `channel.rs` (`connect_channel` — applies `DEFAULT_CONNECT_TIMEOUT` = 10s — plus `connect_channel_with_timeout`, `normalize_grpc_endpoint`), `abort_on_drop.rs` (`AbortOnDropStream`, incl. `defer_abort_until_first_item()`), `tokenizer_bundle.rs`, and the `TraceInjector` trait (with `NoopTraceInjector` default + `BoxedTraceInjector` alias). Do not add a free trace-injection function — injection goes through the trait.

### Step 3: Wire into the router's GrpcClient enum

**File:** `model_gateway/src/routers/grpc/client.rs`

Add a `Myengine(MyengineEngineClient)` variant, an arm in `connect()` (`"myengine" => Ok(Self::Myengine(MyengineEngineClient::connect(url).await?))`), and arms in every exhaustive match: `health_check()`, `get_model_info()`, `get_server_info()`, `runtime_type()`, `get_tokenizer()`, `build_{chat,messages,completion,generate}_request()`, and the `ModelInfo`/`ServerInfo` `to_labels()` matches. `generate()`/`embed()` are tuple matches on `(Self, ProtoGenerateRequest)` / `(Self, ProtoEmbedRequest)` ending in `_ => panic!(...)` — a missing arm compiles and panics on the first request, so add them by hand. Opt-in RPCs — add a supported arm, or join the existing unsupported branch:
- `get_loads()` — GetLoads RPC; sglang/vllm/tokenspeed. Falls through a `_ =>` unimplemented default, so it compiles without an arm.
- `flush_cache()` / `start_profile()` / `stop_profile()` — sglang/tokenspeed only; vllm/trtllm/mlx share one explicit `unimplemented` arm (no wildcard).
- `subscribe_kv_events(start_seq)` — sglang/vllm/trtllm/tokenspeed; MLX is an explicit unsupported arm (no wildcard). The consumer is `model_gateway/src/worker/kv_event_monitor.rs`.

**More files the enum drags in:**
- `crates/protocols/src/worker.rs` — add a `Myengine` variant to `RuntimeType` plus arms in `as_str()` and its `FromStr` chain. Its lowercase string is the runtime key `GrpcClient::connect` and `detect_grpc_backend` pass around; `GrpcClient::runtime_type()`, `common/stages/request_execution.rs`, and `multimodal/capability.rs` match on the enum.
- `routers/grpc/proto_wrapper.rs` — `ProtoGenerateRequest`, `ProtoGenerateResponse`, `ProtoGenerateStreamChunk`, `ProtoGenerateComplete`, `ProtoStream`, and `ProtoEmbedRequest`/`ProtoEmbedComplete` are matched exhaustively; add a variant plus arms to each surface your engine supports (`MultimodalData` only if it is multimodal — MLX is absent there).
- `routers/grpc/harmony/stages/request_building.rs` — exhaustive `(BackendClient::Grpc(GrpcClient::…), HarmonyBody::{Chat,Responses})` match, no engine wildcard; add Chat and Responses arms, or one body-generic arm delegating to a helper (as vllm/tokenspeed do).
- `routers/grpc/regular/stages/embedding/request_building.rs` — exhaustive per-engine match; add a `build_embed_request` arm or an explicit `not_implemented` one.

The `build_*_request` arms delegate to proto-level builders on the engine client itself (`build_generate_request_from_{chat,messages,completion}`, `build_plain_generate_request`), while the harmony and embedding stages call `build_generate_request_from_responses` and `build_embed_request` — all of them belong in your Step 1 file (see `vllm_engine.rs`). Tool/reasoning parsing stays a router concern under `routers/grpc/regular/` + `utils/parsers.rs` — see the architecture note below.

## gRPC router architecture (Mode-parameterized pipeline)

Regular, PD (prefill/decode), and EPD (encode/prefill/decode) serving were **unified into one `Mode`-parameterized router** — there is no longer a separate gRPC `pd_router.rs` (the HTTP PD router, `routers/http/pd_router.rs:PDRouter`, `router_type() == "pd"`, still exists and is unrelated to this recipe). Understand this shape before touching request handling:

- **`GrpcRouter` (`router.rs`)** — a single `struct GrpcRouter { mode: Mode, .. }` with `GrpcRouter::new(ctx, mode)` and one `impl RouterTrait`. `new()` builds one `RequestPipeline` per endpoint up front and stores it: `embedding_pipeline`/`classify_pipeline` are `Some` only in `Mode::Regular`; `harmony_pipeline`, `responses_context`, and `harmony_responses_context` are `Some` in Regular **and** PD and `None` only in EPD (those endpoints 501). `RouterFactory::create_router` derives `mode = grpc_mode(cfg)` and calls `create_grpc_router(ctx, mode)`.
- **`Mode` (`mode.rs`)** — `enum Mode { Regular, PrefillDecode, EncodePrefillDecode }` + `grpc_mode(&RouterConfig) -> Option<Mode>`, which returns `Some` for `ConnectionMode::Grpc | ConnectionMode::Zmq` (ZMQ reuses this pipeline). Each `Mode` maps to a `WorkerSelectionMode`, an `ExecutionPlanKind`, an `inject_pd_metadata()` flag, and a `router_type()` label (`"grpc"` / `"grpc_pd"` / `"grpc_epd"`).
- **`RequestPipeline` (`pipeline.rs`)** — `RequestPipeline::build(endpoint, mode, deps)` composes a `Vec<Box<dyn PipelineStage>>` per endpoint, inserting `EncodeStage` only for EPD mode. A route method (e.g. `route_chat_impl`) picks the regular or harmony pipeline and calls `execute_chat`, which runs the ordered stages.
- **Shared stages (`common/stages/`)** — the `PipelineStage` trait plus `RateLimitReserveStage` (`rate_limit.rs`; tenant token reserve, inserted right after the preparation stage for chat/messages/completion/harmony only), `WorkerSelectionStage`, `ClientAcquisitionStage`, `DispatchMetadataStage`, `RequestExecutionStage`, and `EncodeStage` (the relocated EPD encode, formerly `epd_encode.rs`).
- **`BackendClient` (`backend_client.rs`)** — `enum BackendClient { Grpc(GrpcClient), Zmq(ZmqEngineClient) }`: what `ClientAcquisitionStage` yields and what a worker holds (`BasicWorkerBuilder::backend_client`). `GrpcClient` stays pure gRPC and `BackendClient::Grpc` delegates to it, so a new gRPC engine adds no arms here.
- **Endpoint stages (`regular/`)** — per-endpoint request-building stages (`stages/chat|completion|generate|messages|embedding|classify/`), `processor.rs`, and `streaming.rs`. Despite the module name, `regular/` now backs **all** modes (Regular/PD/EPD).

**When adding an engine (this recipe) you do not touch the `Mode`/pipeline machinery** — it is engine-agnostic — but you do add every per-engine arm listed in Step 3.

### Step 4: Register in runtime detection

**File:** `model_gateway/src/workflow/steps/local/detect_backend.rs`

`detect_grpc_backend` tries `["sglang", "vllm", "trtllm", "tokenspeed", "mlx"]` in order via `do_grpc_health_check`. Add `"myengine"` to that array so `DetectBackendStep` recognizes the backend when no `runtime_type` is configured.

### Step 5: Add metadata discovery

**File:** `model_gateway/src/workflow/steps/local/discover_metadata.rs`

`fetch_grpc_metadata` connects via `GrpcClient::connect`, calls `get_model_info()`/`get_server_info()`, and merges `to_labels()`. `normalize_grpc_keys` renames engine fields to canonical label keys (e.g. `tensor_parallel_size -> tp_size`) and drops transient keys. Ensure your engine surfaces `served_model_name`, `model_path`, `context_length`, etc.; for SGLang-style configs the picked keys live in `SGLANG_GRPC_KEYS` in `client.rs`.

### Step 6: Tests

`vllm_engine.rs` keeps a `#[cfg(test)] mod tests` covering proto construction, defaults, and `connect("invalid://endpoint")` returning `Err`. Backend metadata tests live in `discover_metadata.rs` (the `#[ignore]` ones hit a live server). gRPC routing passes `SelectWorkerInfo { tokens: Option<&[u32]>, .. }` (a struct, not an enum variant) — cover token-aware policies there if relevant.

**Verify:** `cargo test -p smg-grpc-client` and `cargo test -p smg`

## Key Rules

- One file + one client type per engine; never a generic `mybackend.rs`. Reuse whichever of the four macros apply to your engine's proto (`impl_engine_client_basics!`, `impl_get_tokenizer!`, `impl_subscribe_kv_events!`, `impl_admin_ops!`) — don't hand-roll what a macro covers.
- Inject trace context through `self.trace_injector.inject(request.metadata_mut())` on every outbound RPC; log-and-continue on error.
- Connect only via `connect_channel` (handles `grpc://`/`grpcs://` normalization + keep-alive); don't build a raw `Channel`.
- Tool/reasoning parsing is a ROUTER concern (`routers/grpc/...`), not the client crate.
- gRPC routing supports DP-rank pinning: a worker's data-parallel rank is set on the worker spec (`BasicWorkerBuilder::dp_config(rank, size)` in `model_gateway/src/worker/builder.rs`) and read via `worker.dp_rank()`.
- Targets tonic 0.14 (`tonic-prost` / `tonic-prost-build` were split out of tonic's prost codegen in 0.14), package `smg-grpc-client`.

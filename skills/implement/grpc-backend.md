# Adding a gRPC Backend Client to SMG

gRPC clients live in the `smg-grpc-client` crate (one file per engine) and talk to an inference backend (SGLang, vLLM, TRT-LLM, MLX, TokenSpeed — TokenSpeed is the newest and a good template for a fresh engine). Each engine wraps its generated tonic client and shares connection/health/tokenizer/admin logic via four macros (see Step 1). The router layer (`model_gateway/src/routers/grpc/`) wraps all engines behind the `GrpcClient` enum and owns request building, streaming, and tool/reasoning parsing — the client crate does NOT parse output.

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

`impl_engine_client_basics!` requires the macro's `proto::HealthCheckRequest` / `GetModelInfoRequest` / `GetServerInfoRequest` / response types to exist in your `proto` module. `impl_get_tokenizer!`/`impl_subscribe_kv_events!` use `common_proto` types and need the matching RPCs on the generated client.

**Proto module naming — two conventions.** Older engines name the module `proto` and re-export it aliased: `pub mod proto { include_proto!(...) }` then `pub use {engine}_engine::{proto as {engine}_proto, ...}` (see `vllm_engine.rs` + `lib.rs`). The newer TokenSpeed pattern names the module `tokenspeed_proto` directly and re-exports it **without** an alias: `pub mod tokenspeed_proto { include_proto!("tokenspeed.grpc.scheduler") }` then `pub use tokenspeed_scheduler::{tokenspeed_proto, TokenSpeedSchedulerClient};` (see `tokenspeed_scheduler.rs` + `lib.rs`). Either works; pick one and stay consistent.

**Four shared macros — use whichever your engine's proto supports** (all defined in `crates/grpc_client/src/lib.rs`):
- `impl_engine_client_basics!($proto_client, $display_name)` — the two `connect` constructors, `with_trace_injector`, and `health_check` / `get_model_info` / `get_server_info`.
- `impl_get_tokenizer!()` — `get_tokenizer() -> StreamBundle` (uses `common_proto`).
- `impl_subscribe_kv_events!()` — `subscribe_kv_events(start_sequence_number)` (uses `common_proto`).
- `impl_admin_ops!()` — `flush_cache(timeout_s)` (FlushCache RPC), `start_profile(req)`, `stop_profile()`, with local deadlines from `FLUSH_RPC_DEADLINE_MARGIN` / `PROFILE_RPC_DEADLINE`.

Macro use is per-engine/partial — pick only the ones whose RPCs exist on your generated client: sglang uses all four; vllm and trtllm use basics + `impl_get_tokenizer!` + `impl_subscribe_kv_events!`; mlx uses basics + `impl_get_tokenizer!` only (no kv_events); TokenSpeed uses only `impl_admin_ops!` + `impl_subscribe_kv_events!` and **hand-rolls** connect/health/info (no `impl_engine_client_basics!`) with no tokenizer.

If `generate` is streaming, prefer the auto-abort wrapper: return `crate::AbortOnDropStream<proto::GenerateResponse, Self>`, `impl AbortOnDropClient for MyengineEngineClient` (its `abort_for_drop` calls your `abort_request`), and build it with `AbortOnDropStream::new(stream, request_id, self.clone())`. The router calls `mark_completed()` on success. See `abort_on_drop.rs`.

### Step 2: Export from the crate root

**File:** `crates/grpc_client/src/lib.rs`

Add `pub mod {ENGINE}_engine;` and re-export: `pub use {ENGINE}_engine::{proto as myengine_proto, MyengineEngineClient};` (mirror the existing vLLM/SGLang lines), or, if you named the proto module after the engine, the no-alias TokenSpeed form (e.g. `pub use tokenspeed_scheduler::{tokenspeed_proto, TokenSpeedSchedulerClient};`). The four shared macros (`impl_engine_client_basics!`, `impl_get_tokenizer!`, `impl_subscribe_kv_events!`, `impl_admin_ops!`) and the deadline constants `FLUSH_RPC_DEADLINE_MARGIN` / `PROFILE_RPC_DEADLINE` are defined here. Shared infra also lives here: `channel.rs` (`connect_channel`, `normalize_grpc_endpoint`), `abort_on_drop.rs`, `tokenizer_bundle.rs`, and the `TraceInjector` trait (with `NoopTraceInjector` default + `BoxedTraceInjector` alias). Do not add a free trace-injection function — injection goes through the trait.

### Step 3: Wire into the router's GrpcClient enum

**File:** `model_gateway/src/routers/grpc/client.rs`

Add a `Myengine(MyengineEngineClient)` variant, an arm in `connect()` (`"myengine" => Ok(Self::Myengine(MyengineEngineClient::connect(url).await?))`), and arms in `health_check()`, `get_model_info()`, `get_server_info()`, and the `ModelInfo`/`ServerInfo` `to_labels()` matches. Also add arms (or fall through to the existing error default) in:
- `get_loads()` — GetLoads RPC; currently supported for sglang/vllm/tokenspeed (those clients expose `get_loads`), and returns `Status::unimplemented` for the rest.
- `subscribe_kv_events(start_seq)` — supported for sglang/vllm/trtllm/tokenspeed; MLX is explicitly unsupported. The KV-events consumer that drives this is `model_gateway/src/worker/kv_event_monitor.rs`.

Request building, streaming, and tool/reasoning parsing live under `routers/grpc/regular/` and `utils/parsers.rs` — extend those, not the client crate.

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

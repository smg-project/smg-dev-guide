# Adding a Provider-Compatible API Surface to SMG

A "provider API" is a router that speaks a vendor's wire protocol on a dedicated route — Anthropic's Messages API on `/v1/messages`, Gemini's Interactions API on `/v1/interactions`. Each is a `RoutingMode` variant + a `RouterTrait` impl + a factory wiring + a mounted route. **Model new work on the Anthropic router** (`routers/anthropic/`): it is a flat module (`router.rs`, `streaming.rs`, `non_streaming.rs`, `sse.rs`, `mcp.rs`, `context.rs`, `worker.rs`, `utils.rs`), simpler than Gemini's step/driver design (`routers/gemini/{driver,state,steps/}`).

The gateway picks **one** router per process (`RouterFactory::create_router` in `routers/factory.rs`), keyed on `connection_mode` then `mode`. Every other `RouterTrait` method falls through to a `501 NOT_IMPLEMENTED` default (the trait `RouterTrait` in `routers/mod.rs` defaults every route method to 501), so a provider router only implements the one route method it serves (e.g. `route_messages` on `RouterTrait` in `routers/mod.rs`).

> Worth checking first: is the surface already a `RouterTrait` method? `route_messages`, `route_interactions`, `route_responses`, `route_embeddings`, etc. already exist on the trait. If yes, you only implement that method on a router; you do **not** add a new trait method or route.

---

## The flow (Anthropic, end to end)

```
CLI --backend anthropic        →  RoutingMode::Anthropic { worker_urls }    (main.rs to_router_config, types.rs enum RoutingMode)
config validation              →  Anthropic mode: HTTP only, no discovery    (validation.rs validate_mode + validate_discovery)
RouterFactory::create_router   →  HTTP + Anthropic → create_anthropic_router (factory.rs create_router)
create_anthropic_router        →  AnthropicRouter::new(ctx)                  (factory.rs create_anthropic_router)
server route  /v1/messages     →  v1_messages handler → route_messages(...)  (server.rs v1_messages)
route_messages                 →  select worker, then streaming|non_streaming (anthropic/router.rs route_messages)
```

---

## Step 1: Add the `RoutingMode` variant

**File:** `model_gateway/src/config/types.rs` — `enum RoutingMode` (`#[serde(tag = "type")]`). Add a variant mirroring `Anthropic`:

```rust
#[serde(rename = "myprovider")]
MyProvider { worker_urls: Vec<String> },
```

Adding a variant breaks every exhaustive match — the compiler lists them. Patch each like the `Anthropic` arm already present:
- `types.rs` `RoutingMode::worker_count`, and `RoutingMode::mode_type` (the mode-name `&'static str`).
- `config/validation.rs` `validate_mode` (validate URLs; allow empty for dynamic workers) and `validate_discovery` (reject service discovery, as Anthropic/Gemini do).
- `config/builder.rs` — optional ergonomic helper like `gemini_mode()`; Anthropic has none and relies on the generic `mode()`.

## Step 2: Add the CLI backend + config→mode mapping

**File:** `model_gateway/src/main.rs` — `enum Backend`. Add `#[value(name = "myprovider")] Myprovider` and its `Display` arm (`impl Display for Backend`). Map it to the mode in `to_router_config`, next to the `Backend::Anthropic` branch:

```rust
} else if matches!(self.backend, Some(Backend::Myprovider)) {
    RoutingMode::MyProvider { worker_urls: self.worker_urls.clone() }
}
```

Then add a `RoutingMode::MyProvider { worker_urls } =>` arm to the `all_urls` match (also in `to_router_config`). `determine_connection_mode` returns `Http` unless a URL is `grpc://`/`grpcs://` (→ `Grpc`) or `ipc://` (→ `Zmq`), per `ConnectionMode::from_url` in `crates/protocols/src/worker.rs` — provider routers need HTTP (see Step 4). YAML config users select via `type: myprovider` (the serde tag); see @config-plumbing.md.

## Step 3: Implement the router

**Model file:** `model_gateway/src/routers/anthropic/router.rs`. Create `routers/myprovider/` with a `mod.rs` exporting the router (Anthropic's `mod.rs` re-exports `pub use router::AnthropicRouter;`, keeps `router` private, rest `pub(crate)`).

The router holds `Arc<AppContext>` plus a `RouterContext` of shared infra (`struct RouterContext` in `anthropic/context.rs`: `mcp_orchestrator`, `mcp_format_registry`, `http_client`, `worker_registry`, `request_timeout`). `new()` returns `Result<Self, String>` and fails fast if a required dependency is absent (`AnthropicRouter::new` errors when `mcp_orchestrator` is unset).

Implement `RouterTrait` (`#[async_trait]`) overriding **only** your route method + `as_any` + `router_type`. Shape (`AnthropicRouter`'s `impl RouterTrait` in `anthropic/router.rs`):

```rust
#[async_trait]
impl RouterTrait for MyProviderRouter {
    fn as_any(&self) -> &dyn Any { self }

    async fn route_messages(            // or route_interactions, etc.
        &self,
        headers: Option<&HeaderMap>,
        tenant_meta: &TenantRequestMeta,
        body: CreateMessageRequest,     // by value — from openai_protocol::messages (struct CreateMessageRequest in crates/protocols/src/messages.rs)
        model_id: &str,
    ) -> Response {
        // 1. (optional) MCP: if header_utils::is_smg_mcp_enabled(headers) && body.has_mcp_toolset()
        //    → mcp_utils::ensure_mcp_servers(...); 502 via routers::error::bad_gateway on failure
        // 2. select a worker for this provider
        // 3. dispatch streaming vs non-streaming
    }

    fn router_type(&self) -> &'static str { "myprovider" }
}
```

Every typed-JSON route method takes the body **by value** — `route_generate`, `route_chat`, `route_completion`, `route_responses`, `route_embeddings`, `route_classify`, `route_rerank`, `route_messages`, `route_interactions` — so the dispatching router owns it and can free it once the upstream bytes exist. Writing `&CreateMessageRequest` will not match the trait. Only `route_audio_transcriptions` and the realtime session-create methods still take `&body` (`route_realtime_ws`/`route_realtime_webrtc` take a raw `Request<Body>`); `route_interactions` takes `model_id: Option<&str>`.

Worker selection (in `AnthropicRouter::route_messages`): `WorkerSelector::new(&registry, &client).select_worker(&SelectWorkerRequest { model_id, headers, provider: Some(ProviderType::Anthropic), ..Default::default() })`. `ProviderType` lives in `crates/protocols/src/worker.rs` (`enum ProviderType`: `OpenAI | XAI | Anthropic | Gemini | Custom(String)`) — add a dedicated variant only if your provider needs distinct request shaping; otherwise `ProviderType::Custom("myprovider".into())` covers passthrough providers without touching the enum.

Streaming split (also in `route_messages`): take ownership once (`let request = body;`), then `let is_streaming = request.stream.unwrap_or(false);` and call into separate modules. Anthropic's `streaming::execute` / `non_streaming::execute` take `(&RouterContext, RequestContext)` (`execute` in `anthropic/streaming.rs` and `anthropic/non_streaming.rs`); `RequestContext` (`struct RequestContext` in `anthropic/context.rs`) carries that owned request, headers, `model_id`, `tenant_request_meta`, connected `mcp_servers`, and the pre-selected `worker`.

**Provider concerns** (split into sibling modules, like Anthropic):
- **SSE:** use the **shared SSE codec** in `routers/common/sse.rs` rather than hand-rolling framing. Encode downstream via `SseEncoder` (`encode_data(value)`, `encode_event(event_type, value)`, `SseEncoder::done()` for `data: [DONE]`); decode upstream via `SseDecoder` (`push(chunk)` then drain `next_frame()` to `None`, then `compact()`; `flush()` at end-of-stream). `SseFrame` is the parsed `{ event_type, data }` (with `decode_data::<T>()` / `is_done()`), and `parse_block(&str)` parses a single already-extracted block. Both the Anthropic router (`anthropic/sse.rs`, `anthropic/streaming.rs`) and the OpenAI Responses router (`openai/responses/streaming.rs`) now stream **through** this codec. Event **names** stay vendor-specific (match the vendor exactly), but framing/parsing is shared and DoS-bounded (≈1 MB default decode buffer, `DEFAULT_MAX_BUFFER_SIZE` in `sse.rs`). `build_sse_response` still sets the `text/event-stream` headers (the shared `build_sse_response` in `common/sse.rs` builds from the **bounded** receiver of `sse_channel()` — `SSE_CHANNEL_BUFFER` = 32 frames, for backpressure; never hand-roll an unbounded channel. Anthropic keeps its own `build_sse_response` in `anthropic/sse.rs` to forward upstream headers).
- **MCP tool interception:** when the request carries MCP toolsets, run an agentic tool loop instead of a plain proxy — Anthropic branches to `execute_mcp_streaming` (in `anthropic/streaming.rs`) / the MCP path in `anthropic/non_streaming.rs`, capping at `mcp_utils::DEFAULT_MAX_ITERATIONS`. Per-server allowed tools come from `mcp::collect_allowed_tools_per_server` (`collect_allowed_tools_per_server` in `anthropic/mcp.rs`). See @mcp-feature.md.

## Step 4: Wire the factory

**File:** `model_gateway/src/routers/factory.rs`.
1. Add a `RouterId` const in the `router_ids` module, e.g. `pub const HTTP_MYPROVIDER: RouterId = RouterId::new("http-myprovider");`.
2. Add a `create_myprovider_router` mirroring `create_anthropic_router`: `Ok(Box::new(MyProviderRouter::new(ctx.clone())?))`.
3. In `create_router`, add a `RoutingMode::MyProvider { .. } =>` arm under **both** connection-mode arms: the `ConnectionMode::Grpc | ConnectionMode::Zmq` arm returns `Err("MyProvider mode requires HTTP connection_mode")`; the `ConnectionMode::Http` arm calls your factory.
4. Add the router to `create_igw_routers` so multi-router IGW mode serves it.

Import your router in the `super::{...}` block at the top of `factory.rs`.

## Step 5: Mount the route (only if it is a new endpoint)

`/v1/messages` and `/v1/interactions` are **already** mounted (`server.rs` route builder) and dispatch via existing trait methods. For a genuinely new path:
1. Add an axum handler beside `v1_messages` (the `v1_messages` fn in `server.rs`): `State<Arc<AppState>>`, `HeaderMap`, `Extension<TenantRequestMeta>`, a `PreemptionGuard`, and `ValidatedJson(body)`. Clone the model id out first (`let model = body.model.clone();`), then call `state.router.route_*(Some(&headers), &tenant_meta, body, &model)` inside `cancel.guard(...)` — `body` is moved into the call.
2. Register it in the router builder next to `.route("/v1/messages", post(v1_messages))`: `.route("/v1/mypath", post(v1_mypath))`.
3. Leave `--stream-request-bodies-over` (`RouterConfig::stream_request_bodies_over`, default 0 = off — streamed pass-through of large bodies) alone: `stream_large_request_bodies` (`model_gateway/src/routers/http/router.rs`) matches the path, then downcasts to the **regular** HTTP `Router` and declines otherwise (it also declines when IGW has more than one router), so a provider router never receives a streamed body. Add your path to its `match req.uri().path()` list only if the regular router serves it too — that is why `/v1/messages` is listed.

The body type must be a request struct from the protocols crate (e.g. `CreateMessageRequest`, `InteractionsRequest`) with `Deserialize` so `ValidatedJson` can parse it. That crate lives at `crates/protocols/` but its package is `openai-protocol` (Rust crate path `openai_protocol`).

**Protocol fidelity:** the protocols crate uses `#[serde(flatten)]` to preserve unknown vendor fields and keep `type` discriminators on content/system blocks, so proxied requests round-trip losslessly (`messages.rs`). Tool-call routers must keep the `function_call` / `function_call_output` rename pairing (`responses.rs`). Mirror these patterns when extending a request struct; never drop unknown fields.

---

## Verify

```bash
cargo check -p smg          # smg == the model_gateway package
cargo test -p smg routers   # router-scoped tests
```

Then invoke `smg:contribute` for fmt → clippy → test → commit.

**Anti-patterns:** implementing many `RouterTrait` methods (override only what you serve — the rest 501 by design); allowing gRPC/ZMQ for an HTTP-only provider (return the `Err` in the `ConnectionMode::Grpc | ConnectionMode::Zmq` arm of `create_router`); inlining streaming + SSE + MCP in `route_messages` (keep them in sibling modules as Anthropic does); inventing a request struct in the router instead of using/extending the protocols crate; hand-rolling SSE framing instead of going through `SseEncoder`/`SseDecoder`.

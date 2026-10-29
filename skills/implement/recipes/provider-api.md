---
recipe: provider-api
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/external_router/src/
  - model_gateway/src/routers/external.rs
  - model_gateway/src/routers/factory.rs
  - model_gateway/src/routers/provider_support.rs
  - model_gateway/src/routers/gateway.rs
  - crates/protocols/src/worker.rs
---

# Routing to Third-Party Providers (external routers)

Two different things carry the word "provider" in SMG — be sure which one you are changing:

1. **SMG exposing a provider-shaped API** to self-hosted engines — Anthropic Messages on `/v1/messages`, Gemini Interactions on `/v1/interactions`. Those routes are mounted in `server.rs` (`v1_messages`, `v1_interactions`) and served by the gRPC pipeline's per-endpoint stages (`routers/grpc/regular/stages/messages/`, `pipeline.rs::execute_messages`). Extending them is a pipeline change: see the architecture section of @grpc-backend.md.
2. **SMG forwarding to a third-party provider** — OpenAI, Anthropic, Gemini, xAI, or any OpenAI-compatible endpoint. That is the `smg-external-router` crate (`crates/external_router/`). **This recipe.**

## The shape

- **Contract:** `ExternalRouter` (`crates/external_router/src/router.rs`: `route_chat`, `route_responses`, `route_messages`, `route_interactions`, the realtime session methods, `health_generate`, `get_server_info`, `as_any`, `router_type`) and `ExternalContext` (`src/context.rs`: the gateway's `reqwest::Client` (built by the gateway's client factory — never `reqwest::Client::new`), `request_timeout`, `RetryConfig`, `workers: Arc<dyn WorkerSource>`, the MCP orchestrator and format registry, response/conversation/item storage, the realtime registry, WebRTC settings).
- **Families:** `openai/` (also serves xAI and `Custom` OpenAI-compatible vendors through `openai/provider/`), `anthropic/` (flat module: `router.rs`, `streaming.rs`, `non_streaming.rs`, `sse.rs`, `mcp.rs`, `context.rs`, `worker.rs`, `utils.rs`), `gemini/` (`driver.rs`, `state.rs`, `steps/`). Each sits behind a Cargo feature — `openai`, `anthropic`, `gemini` in `crates/external_router/Cargo.toml`, forwarded by `provider-openai`, `provider-anthropic`, `provider-gemini` in `model_gateway/Cargo.toml`. CI lints four legs (`all-features`, `self-hosted` with no provider, `anthropic-only`, `default-build`; `bash scripts/ci_rust_tests.sh lint <leg>`), so provider code must compile out cleanly.
- **Spec table:** `ExternalRouterSpec` (`router.rs`) — `router_id`, `backend` (the `--backend` value), `label`, `feature`, `serves: fn(&ProviderType) -> bool`, `fallback`, `compiled`, `build`. `ExternalRouterSpec::all()` returns `[OPENAI, ANTHROPIC, GEMINI]`; `takes(provider)` says which router a worker's `ProviderType` goes to (`openai_serves` covers `OpenAI | XAI | Custom(_)`); `not_compiled()` is the error a build without the feature returns.
- **Gateway side:** `RouterFactory::create_external_router(backend, ctx)` (`model_gateway/src/routers/factory.rs`) finds the spec for the backend and calls `ExternalRouterAdapter::mount(spec, ctx)` (`routers/external.rs`), which builds the `ExternalContext` (`external_context`) and exposes the gateway's workers as `GatewayWorkers`. `routers/provider_support.rs` refuses to admit a worker that targets a provider no compiled router takes (`MissingRouter`). In IGW mode `routers/gateway.rs` hands a request whose worker is external to the provider router that takes it.
- **Shared glue** every family reuses, re-exported by the gateway at its old `routers::common` paths: `sse.rs` (the SSE codec), `retry.rs` + `retry_config.rs`, `mcp_utils.rs` (request-scoped MCP), `openai_bridge/` (the MCP-to-OpenAI bridge), `header_utils.rs`, `persistence_utils.rs`, `realtime/` (the realtime proxy), `upstream_body.rs`, `tenant.rs`, `metrics.rs`, `error.rs`.
- **Config:** `RoutingMode::{OpenAI, Anthropic, Gemini}` (`config/types.rs`), `--backend openai|anthropic|gemini` (`Backend` in `main.rs`), `ProviderType::{OpenAI, XAI, Anthropic, Gemini, Custom(String)}` (`crates/protocols/src/worker.rs`).

## Task A: Add an OpenAI-compatible vendor (the common case)

1. **File:** `crates/external_router/src/openai/provider/<vendor>.rs` — implement `Provider` (`openai/provider/provider_trait.rs`): `provider_type()` and `transform_request(payload, endpoint)`, rewriting the outgoing JSON for the vendor's quirks. Model on `xai.rs`: it strips SGLang-only fields (`strip_sglang_fields`, `src/sglang_fields.rs`) and normalises Responses input items per `Endpoint`.
2. `ProviderType` (`crates/protocols/src/worker.rs`): add a variant only when the vendor needs shaping that `Custom(String)` cannot express; then `openai_serves` (`router.rs`) must list it, and the `ProviderType` matches the compiler flags get an arm.
3. Register it in `ProviderRegistry::new` (`openai/provider/registry.rs`; `get_arc` / `default_provider_arc` resolve a worker's `ProviderType` to its provider) and add the module to `openai/provider/mod.rs`.
4. Tests in `openai/provider/tests.rs`: the request transform per `Endpoint`, and that an unknown vendor still gets the default provider.

**Verify:** `cargo test -p smg-external-router --features openai`

**Anti-pattern:** a new router family for an OpenAI-compatible API. Everything OpenAI-shaped goes through `openai/` and a `Provider`.

## Task B: Add a router family (rare)

1. **Module:** `crates/external_router/src/<family>/` implementing `ExternalRouter` for the routes the provider serves (the rest keep the trait defaults). Model Anthropic's flat module; take the shared glue (`sse.rs`, `retry.rs`, `mcp_utils.rs`, `header_utils.rs`, `upstream_body.rs`) instead of hand-rolling framing or retries. Worker selection comes from `ExternalContext::workers`.
2. **Spec:** a `pub const <FAMILY>: ExternalRouterSpec` in `router.rs` with a `<family>_serves` and a feature-gated `<family>_build` whose `#[cfg(not(feature = ...))]` twin returns `Err(<FAMILY>.not_compiled())`; grow `all()` to `[ExternalRouterSpec; 4]`.
3. **Features:** `<family> = []` in `crates/external_router/Cargo.toml`; `provider-<family> = ["smg-external-router/<family>"]` in `model_gateway/Cargo.toml`; a lint leg in `scripts/ci_rust_tests.sh` if the family needs one.
4. **Config:** a `RoutingMode` variant (`config/types.rs`; patch `worker_count`, `mode_type`, and `validate_mode` / `validate_discovery` in `config/validation.rs` — provider modes are HTTP-only and reject service discovery), a `Backend` value in `main.rs` with its `to_router_config` branch, a `ProviderType` variant covered by `serves`. See @config-plumbing.md.
5. **Routes:** mount a new path only when the provider speaks a protocol SMG does not yet expose — an axum handler beside `v1_messages` in `server.rs` (`State<Arc<AppState>>`, `HeaderMap`, `Extension<TenantRequestMeta>`, a `PreemptionGuard`, `ValidatedJson(body)`) and a `.route(...)` next to `/v1/messages`. The body type must be a request struct from `crates/protocols/` (package `openai-protocol`) with `Deserialize`; its `#[serde(flatten)]` fields preserve unknown vendor fields so proxied requests round-trip losslessly.

**Verify:** `cargo check -p smg --features provider-<family>`, then `bash scripts/ci_rust_tests.sh lint self-hosted` to prove the feature compiles out.

## Verify

```bash
cargo test -p smg-external-router --all-features
cargo check -p smg                       # default build
cargo test -p smg routers                # router-scoped gateway tests
```

Then invoke `smg:contribute`.

## Anti-patterns

- Provider-specific code in the gateway (`model_gateway/src/routers/`) instead of the crate — the gateway only mounts specs.
- Code outside its Cargo feature: the `self-hosted` and `anthropic-only` legs fail.
- A `_ =>` arm over `ProviderType`; `provider_support.rs` relies on `serves` being exhaustive about what a build can take.
- Hand-rolled SSE framing or an unbounded channel instead of `sse.rs`.
- Inventing a request struct in the router instead of using or extending `crates/protocols/`.

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
exemplars:
  - 4e5a385e   # feat: per-provider Cargo features (how routers compile out)
  # no new vendor or router family since 2026-08-20; provider profiles are in protocols-profile.md
---

# Route to a third-party provider

"Provider" means three things in SMG. (1) SMG exposing a provider-shaped API (`/v1/messages`, `/v1/interactions`) to self-hosted engines: the gRPC pipeline's endpoint stages, @http-endpoint.md. (2) Vendor request rules a profile enforces: `crates/protocols/src/profile/`, @protocols-profile.md. (3) SMG forwarding to OpenAI, Anthropic, Gemini, xAI or an OpenAI-compatible endpoint: `crates/external_router` (package `smg-external-router`), **this recipe**. The contract is `ExternalRouter` (`src/router.rs`) plus `ExternalContext` (`src/context.rs`: the gateway's HTTP client, timeout, `RetryConfig`, `workers: Arc<dyn WorkerSource>`, MCP, storage, realtime). The gateway only mounts specs: `RouterFactory::create_external_router(backend, ctx)` (`routers/factory.rs`) → `ExternalRouterAdapter::mount` (`routers/external.rs`); `routers/provider_support.rs` refuses a worker no compiled router takes (`MissingRouter`); `routers/gateway.rs` hands an external worker's request to the router whose spec `takes` it.

Not this recipe: (1) and (2) above; a `RoutingMode` knob end to end (@config-plumbing.md).

## Inputs

| Input | Example | Used in |
|---|---|---|
| OpenAI-compatible vendor or new wire protocol | xAI (compatible) vs Anthropic (own protocol) | A or B |
| `ProviderType` | `Custom("vendor")` or a new variant (`crates/protocols/src/worker.rs`) | A2, B4 |
| request quirks | strip SGLang-only fields, rewrite Responses input items | A1 |
| features | `openai` / `anthropic` / `gemini` in `crates/external_router/Cargo.toml`; `provider-*` in `model_gateway/Cargo.toml` | B3 |

## Steps

### A1. OpenAI-compatible vendor: provider

File: `crates/external_router/src/openai/provider/<vendor>.rs` — Do: implement `Provider` (`openai/provider/provider_trait.rs`: `provider_type()`, `transform_request(payload, endpoint)`), modelled on `xai.rs` (`strip_sglang_fields` from `src/sglang_fields.rs`, Responses-input normalisation per `Endpoint`).
Verify: `cargo test -p smg-external-router --features openai`

### A2. OpenAI-compatible vendor: registry and type

File: `crates/external_router/src/openai/provider/registry.rs` — Do: register it in `ProviderRegistry::new` (`get_arc` / `default_provider_arc` resolve a worker's `ProviderType`); add the module to `openai/provider/mod.rs`; tests in `openai/provider/tests.rs`. Add a `ProviderType` variant only when `Custom(String)` cannot express the shaping, then `openai_serves` (`router.rs`) must list it.
Verify: `cargo test -p smg-external-router --features openai`
Trap: a vendor shipped as a new router family duplicates the SSE, retry and MCP glue for nothing.

### B1. Router family: module

File: `crates/external_router/src/<family>/` — Do: implement `ExternalRouter` for the routes the provider serves (`route_chat`, `route_responses`, `route_messages`, `route_interactions`, realtime; the rest keep the trait defaults), modelled on `anthropic/` (flat: `router.rs`, `streaming.rs`, `non_streaming.rs`, `sse.rs`, `mcp.rs`, `context.rs`, `worker.rs`, `utils.rs`), using `sse.rs`, `retry.rs`, `mcp_utils.rs`, `header_utils.rs`, `upstream_body.rs` from the crate root.
Verify: `cargo check -p smg-external-router --all-features`

### B2. Router family: spec

File: `crates/external_router/src/router.rs` — Do: a `pub const <FAMILY>: ExternalRouterSpec` (`router_id`, `backend`, `label`, `feature`, `serves`, `fallback`, `compiled`, `build`) with a `<family>_serves` and a feature-gated `<family>_build` whose `#[cfg(not(feature = ...))]` twin returns `Err(<FAMILY>.not_compiled())`; grow `all()` to four.
Verify: `cargo test -p smg-external-router --all-features`

### B3. Router family: features

File: `crates/external_router/Cargo.toml` (`<family> = []`) and `model_gateway/Cargo.toml` (`provider-<family> = ["smg-external-router/<family>"]`) — Do: gate everything family-specific; add a lint leg in `scripts/ci_rust_tests.sh` if the family needs one.
Verify: `bash scripts/ci_rust_tests.sh lint self-hosted` (compiles with no provider)
Trap: provider code outside its feature breaks the `self-hosted` and `anthropic-only` lint legs in CI.

### B4. Router family: config

File: `model_gateway/src/config/types.rs` — Do: a `RoutingMode` variant (patch `worker_count`, `mode_type`, `validate_mode` / `validate_discovery` in `config/validation.rs`: provider modes are HTTP-only and reject discovery); a `Backend` value in `main.rs` and its `to_router_config` branch; a `ProviderType` variant covered by `serves` (@config-plumbing.md).
Verify: `cargo check -p smg --features provider-<family>`

### B5. Routes

Already mounted: `/v1/messages`, `/v1/interactions`. A protocol SMG does not expose yet is a new endpoint: @http-endpoint.md.

### C. Gate

Run `smg:contribute`.

## Rules

- Everything OpenAI-shaped goes through `openai/` and a `Provider`; `openai_serves` covers `OpenAI | XAI | Custom(_)`.
- `ExternalContext` carries the gateway's HTTP client; never `reqwest::Client::new` in a router.
- No `_ =>` over `ProviderType`: `provider_support.rs` relies on `serves` being exhaustive about what a build can take.
- Request types come from `crates/protocols/` (package `openai-protocol`), whose `#[serde(flatten)]` keeps unknown vendor fields so proxied requests round-trip.

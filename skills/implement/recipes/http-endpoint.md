---
recipe: http-endpoint
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - model_gateway/src/server.rs
  - model_gateway/src/routers/mod.rs
  - model_gateway/src/routers/gateway.rs
  - model_gateway/src/routers/http/router.rs
  - model_gateway/src/routers/grpc/pipeline.rs
  - model_gateway/src/routers/grpc/utils/metrics.rs
  - crates/external_router/src/metrics.rs
  - clients/openapi-gen/src/main.rs
exemplars:
  - a7e28280   # native System One API: /v1/systemone on the regular HTTP router
  - 1418d358   # Decisions on the regular HTTP router, with a per-worker adapter
  - 6d2799d1   # Decisions over SGLang gRPC: the pipeline side of the same endpoint
---

# Add an HTTP API endpoint

An endpoint is one `RouterTrait` method with a 501 default (`model_gateway/src/routers/mod.rs`), an axum handler and `.route(...)` in `model_gateway/src/server.rs`, a match arm in `routers/gateway.rs` that picks a router family able to serve it, and an implementation per serving family: `routers/http/router.rs` forwards the typed body to an HTTP worker, `routers/grpc/router.rs` runs a `RequestPipeline` of per-endpoint stages. The body type lives in `crates/protocols/` (package `openai-protocol`) and reaches the handler through `ValidatedJson`.

Not this recipe:
- a third-party provider serving an endpoint SMG already mounts: @provider-api.md
- a flag or config field the endpoint reads: @config-plumbing.md
- a new engine operation the endpoint needs (an RPC in `crates/grpc_client/proto/sglang_scheduler.proto`, `grpc_servicer/`, `crates/engine_servicer/`, the ZMQ wire in `crates/engine_zmq_adapter/` and `crates/engine_zmq_client/`): @grpc-backend.md, @zmq-backend.md

## Inputs

| Input | Example | Used in |
|---|---|---|
| Path | `/v1/systemone` | the `.route(...)`, `route_to_endpoint`, the upstream route in `route_typed_request`, tests |
| Request type | `SystemOneRequest` | `crates/protocols/src/systemone.rs`, the handler, the trait method |
| Trait method | `route_systemone` | `RouterTrait`, `Gateway`, every family router that serves it |
| Metrics label | `ENDPOINT_SYSTEMONE` = `"systemone"` | `metrics_labels`, `route_to_endpoint`, `init_startup_series` |
| Serving families | regular HTTP only; regular HTTP and SGLang gRPC | the gateway's pool filter, which routers implement the method |

## Steps

### 1. Define the request type

File: `crates/protocols/src/<endpoint>.rs`, listed in `crates/protocols/src/lib.rs` — Do: a `<Endpoint>Request` deriving `Serialize`, `Deserialize` and `schemars::JsonSchema` with `pub model: String`, field names as the spec spells them (`#[serde(rename_all = "snake_case")]` on tagged enums) and a trailing `#[serde(flatten)] pub other: Map<String, Value>` so vendor extensions round-trip; implement `Normalizable` (empty unless the body takes defaults), `Validate` (the spec's invariants) and `GenerationRequest` (`is_stream`, `get_model`, `extract_text_for_routing`). Model: `crates/protocols/src/systemone.rs`.
Verify: `cargo test -p openai-protocol --test protocol_tests <endpoint>` → the round-trip and rejection tests you add in `crates/protocols/tests/protocol/<endpoint>.rs` (a `mod` line in `crates/protocols/tests/protocol/mod.rs`) pass.
Trap: `ValidatedJson` refuses only what `validate()` refuses; an invariant you leave out reaches the worker and comes back as its error, not a gateway 400.

### 2. Add the trait method with its 501 default

File: `model_gateway/src/routers/mod.rs` — Do: `async fn route_<endpoint>(&self, _headers: Option<&HeaderMap>, _tenant_meta: &TenantRequestMeta, _body: <Endpoint>Request, _model_id: &str) -> Response` returning `error::not_implemented("<endpoint>_not_supported", ...)`, and a row for it in the `answers` table of `every_default_answer_is_the_json_error_object_under_its_code`.
Verify: `cargo test -p smg --lib every_default_answer_is_the_json_error_object_under_its_code` → passes with the new row.

### 3. Mount the handler

File: `model_gateway/src/server.rs` — Do: a `v1_<endpoint>` handler taking `State<Arc<AppState>>`, `HeaderMap`, `Extension<TenantRequestMeta>`, a `PreemptionGuard` and `ValidatedJson<<Endpoint>Request>`, which clones `body.model` and awaits `cancel.guard(state.router.route_<endpoint>(Some(&headers), &tenant_meta, body, &model))` (model: `v1_systemone`); its `.route("/v1/<endpoint>", post(v1_<endpoint>))` goes in the `typed_routes` group of `build_app`, above that group's `.route_layer(...)`.
Verify: `cargo check -p smg` → compiles; Step 8's tests then drive the route.
Trap: `typed_routes` is the group that carries the Messages error envelope, WASM hooks, serving auth, tenant resolution, admission, SSE keep-alive, the buffer-vs-stream `StreamBodyState` and the body timeouts; a route added below the `.route_layer(...)`, or in `plain_protected_routes` (no stream and body layers), `realtime_routes` (no WASM) or `public_routes` (nothing), serves with fewer layers and no error.

### 4. Dispatch in the gateway

File: `model_gateway/src/routers/gateway.rs` — Do: in `impl RouterTrait for Gateway`, refuse `UNKNOWN_MODEL_ID` before and after `resolve_model_alias` with `model_not_found`; under `enable_igw` take `get_routing_snapshot(model_id)` and pick a router from the pools whose family serves the endpoint (`RoutingPool::HttpRegular` → `router_ids::HTTP_REGULAR`, or `pick_router_by_weights` over the serving pools as `route_decisions` does), otherwise `select_router_for_request(Some(model_id))`; no router → `not_implemented("<endpoint>_not_supported", ...)`. Copy the stub-router tests beside `systemone_uses_only_regular_http_workers_in_mixed_fleets`.
Verify: `cargo test -p smg --lib gateway::tests::<endpoint>` → the mixed-fleet and single-router cases pass.
Trap: without the pool filter, IGW's weighted dispatch lands some requests on a PD or gRPC router whose default answers 501, so the endpoint works for a share of requests that depends on the fleet.

### 5. Serve it on the HTTP router

File: `model_gateway/src/routers/http/router.rs` — Do: in `impl RouterTrait for Router`, `route_<endpoint>` calls `self.route_typed_request(headers, body, "/v1/<endpoint>", model_id)`. When the worker must see the body as sent (vendor extensions, explicit `false` or `null`), add the path to the `matches!(route, "/v1/decisions" | "/v1/systemone")` arm so `serialize_request_body_preserving_fields` runs instead of `serialize_request_body`, which calls `strip_default_sglang_fields`; a worker speaking another wire shape gets an adapter like `SglangDecisionAdapter` (`routers/common/decisions.rs`).
Verify: `cargo test -p smg --test http_tests <endpoint>` → Step 8's tests pass.
Trap: the PD router (`routers/http/pd_router.rs`) keeps the trait default and answers 501; that is correct unless the endpoint has a prefill/decode protocol.

### 6. Serve it on the gRPC pipeline (only when gRPC workers serve it)

File: `model_gateway/src/routers/grpc/pipeline.rs` — Do: an `Endpoint` variant with its `RequestPipeline::build` arm composing `routers/grpc/regular/stages/<endpoint>/` (preparation, request building, response processing and a `supports_worker` predicate), a `RequestType` variant and `RequestContext::for_<endpoint>` in `routers/grpc/context.rs`, a `FinalResponse` variant, and `execute_<endpoint>` modelled on `execute_decisions`; in `routers/grpc/router.rs` a `<endpoint>_pipeline: Option<RequestPipeline>` built in `GrpcRouter::new` and a `route_<endpoint>_impl` that answers 501 when the pipeline is `None` or no worker in `RoutingPool::GrpcPipelineRegular` passes `supports_worker`. Then widen Step 4's pool filter.
Verify: `cargo test -p smg --lib routers::grpc::pipeline` → the endpoint-by-mode parity test (extend its endpoint list) passes.

### 7. Label the metrics

File: `crates/external_router/src/metrics.rs` — Do: `pub const ENDPOINT_<NAME>: &str = "<endpoint>"` in `metrics_labels`; the `"/v1/<endpoint>"` arm of `route_to_endpoint` (`model_gateway/src/routers/grpc/utils/metrics.rs`); the label in the endpoint list of `init_startup_series` (`model_gateway/src/observability/metrics.rs`).
Verify: add `("endpoint", "<endpoint>")` rows to `protection_retry_and_breaker_families_start_at_zero`, then `cargo test -p smg --test metrics_eager_registration_test` → the series exist at zero.
Trap: `route_to_endpoint` falls through to `"other"` and `init_startup_series` is a hand-written list, so a missing arm compiles and the endpoint's retries are counted under `other`.

### 8. Test through the production app

File: `model_gateway/tests/http/<endpoint>_http_test.rs`, a `mod` line in `model_gateway/tests/http/mod.rs` — Do: an axum upstream recording `(path, headers, body)`, a worker registered through `create_test_app_context` and `create_test_app_with_context` (`model_gateway/test_harness/src/test_app.rs`), and cases for: body and headers reach `/v1/<endpoint>` unchanged, an alias resolves, a missing model is a 400 before dispatch, an unsupported router is a 501. Model: `model_gateway/tests/http/systemone_http_test.rs`.
Verify: `cargo test -p smg --test http_tests <endpoint>` → all cases pass.

### 9. Add the e2e file and its CI lane

File: `e2e_test/router/test_<endpoint>.py` — Do: the `engine`, `gpu`, `e2e` and `model` markers (`e2e_test/fixtures/hooks.py`) and `setup_backend` parametrized over `"http"` and `"grpc"` as in `e2e_test/router/test_decisions.py`; name the file in a lane's `test_dirs` in `.github/workflows/pr-test-rust.yml` (`e2e-1gpu-chat-rust-servicer` runs `test_decisions.py`).
Verify: `E2E_ENGINE=sglang E2E_RUNTIME=sglang pytest e2e_test/router/test_<endpoint>.py -v` on a GPU host → passes.
Trap: router e2e files run only where a lane's `test_dirs` names them; `e2e_test/router/test_systemone.py` is named by none and never runs in CI.

### 10. Providers and generated clients (when they apply)

File: `crates/external_router/src/router.rs` — Do: when a third-party provider serves the endpoint, a defaulted `route_<endpoint>` on `ExternalRouter`, forwarded by `ExternalRouterAdapter` in `model_gateway/src/routers/external.rs` (see @provider-api.md); for SDK types, `collect_schema` of the request and response and a `paths.insert` for `/v1/<endpoint>` in `clients/openapi-gen/src/main.rs`.
Verify: `make generate-openapi` → the spec it writes under clients/openapi/ lists the path; `make generate-clients` regenerates the Python and Java types.
Trap: the generator's path table is hand-written; neither exemplar added its route, so the generated clients know neither `/v1/decisions` nor `/v1/systemone`.

### 11. Gate

Run `smg:contribute`.

## Rules

- Every answer a router writes itself is the JSON error object under a code: `error::not_implemented`, `error::model_not_found`, `error::bad_request` (`crates/external_router/src/error.rs`), never a bare status tuple.
- The handler moves the body into the trait method; read `model` before the move, and the method owns the body from there.
- `streamable_route` (`routers/http/router.rs`) lists the typed routes whose bodies may bypass `ValidatedJson` and stream to the worker; a new route is buffered until you add it, which is the safe default.
- Vendor profiles (`crates/protocols/src/profile/`) are applied by `ChatCompletionRequest::normalize`; a new request type gets none unless its `Normalizable` impl calls them.

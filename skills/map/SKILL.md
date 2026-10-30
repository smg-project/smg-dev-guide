---
name: map
description: Orient in the SMG codebase before changing it. Use for "where does X live", "how does Y flow", or before a change that touches more than one file. Gives a live crate map read from the checkout, the invariants a change must respect, and the area table that names each path's recipe and review checklist.
---

# SMG Codebase Map

SMG is a Rust gateway in front of LLM engines (SGLang, vLLM, TensorRT-LLM, TokenSpeed, MLX) and cloud providers (OpenAI, Anthropic, Gemini, xAI). It owns worker lifecycle, routing, admission, tenancy, parsing of model output, chat-history storage, MCP tooling and observability behind OpenAI-, Anthropic- and Gemini-compatible APIs. Workers attach over HTTP, gRPC, or same-host ZMQ.

## Live map

Generated from the checkout you are in, so it cannot go stale:

!`bash "${CLAUDE_PLUGIN_ROOT}/scripts/map_live.sh"`

If the command shows instead of its output, run `scripts/map_live.sh <any dir inside SMG>` from the guide checkout.

## Invariants

1. **Layering.** `crates/protocols` holds the API types every consumer reads; a field only one crate writes belongs in `model_gateway`, never there. Library crates live under `crates/`.
2. **Config has two paths.** `to_router_config` builds `RouterConfig` through the hand-written builder in `config/builder.rs`; `to_server_config` returns a `ServerConfig` literal that carries the whole `RouterConfig` nested. A listener-level setting needs the top-level copy in every `ServerConfig` literal (`main.rs`, `bindings/python/src/lib.rs`, the `server.rs` test helper). Validation in `config/validation.rs` runs inside `RouterConfigBuilder::build()` for the CLI and Python alike; Python mirrors the chain in `lib.rs` and `router_args.py`.
3. **Request flow.** handler (`server.rs`) → WASM OnRequest → auth → tenant resolution → admission (priority scheduler or `ConcurrencyLimitLayer`, chosen once by `AdmissionMode::from_config`) → `routers/gateway.rs` picks the family router → HTTP proxy, or the gRPC/ZMQ `Mode`-parameterized pipeline (`routers/grpc/pipeline.rs`), or a provider router in `crates/external_router` → WASM OnResponse. Middleware order is the reverse of the `route_layer` calls in `server.rs`. Non-routing handlers live in `model_gateway/src/endpoints/`.
4. **Workers.** Providers in `service_discovery/` emit `DiscoveredWorker`s; one reconciler diffs them (labels `smg.ai/discovery-*`) into `Job::AddWorker` / `Job::RemoveWorker`; registration is the step DAG under `workflow/steps/`; every piece of metadata flows as a label into `ModelCard`, never as a parallel field. ZMQ workers skip the probes and stay Pending until `WorkerConnected`.
5. **Parsing.** Symphony (`crates/symphony`) is the default parser: one format table per model family, typed events. `--parser legacy` selects `crates/tool_parser` and `crates/reasoning_parser`; a model outside Symphony's registry falls back to them. New model support is a Symphony table.
6. **Three transports.** HTTP (own router), gRPC (`crates/grpc_client`), same-host ZMQ (`crates/engine_zmq_client` wire + `crates/engine_zmq_adapter` translation, surfaced as `BackendClient::Zmq`). gRPC and ZMQ share the pipeline. A cross-cutting feature supports all three or rejects loudly at registration.
7. **Vocabulary.** A disaggregated dispatch has two **sides**; a worker has a **role**; the workers of one role are a **pool**. "Leg" is not used (CONTRIBUTING.md). More in `smg:craft`.

## Where things live

<!-- render:where-things-live -->
| Area | Go to | Recipe |
|---|---|---|
| Config and CLI | `model_gateway/src/config/`, `model_gateway/src/main.rs`, `model_gateway/src/cli/`: flag groups in main.rs (`CliArgs` flattens `RoutingArgs`, `WorkerArgs`, `DiscoveryArgs`, `ServingArgs`, `ModelArgs`, `IntegrationArgs`), value parsers in cli/, RouterConfig types, builder and validation | `recipes/config-plumbing.md` |
| Protocol types | `crates/protocols/`: shared OpenAI, Anthropic and Gemini API types for every consumer; vendor profiles under src/profile/ | `recipes/protocols-profile.md` |
| App wiring and server | `model_gateway/src/app_context.rs`, `model_gateway/src/server.rs`, `model_gateway/src/server/`, `model_gateway/src/health.rs`: AppContext construction, the axum router and middleware stacks, TLS, connection limits, auth posture, health probes | `recipes/http-endpoint.md` |
| Routing policies | `model_gateway/src/policies/`: load-balancing policies, factory and registry; cache-aware selection pipeline in cost/ | `recipes/routing-policy.md` |
| Routers and dispatch | `model_gateway/src/routers/`: the gateway front (gateway.rs), factory, HTTP proxy router, the Mode-parameterized gRPC pipeline, external-router mounting, shared dispatch in common/ | `recipes/http-endpoint.md` |
| Non-routing endpoints | `model_gateway/src/endpoints/`: tokenize/detokenize, parse, conversations, stored responses, model inventory | `recipes/http-endpoint.md` |
| Admission | `model_gateway/src/middleware/scheduler/`, `model_gateway/src/middleware/concurrency.rs`, `model_gateway/src/middleware/token_bucket.rs`: priority scheduler (classes, queues, slots, preemption) and the legacy concurrency cap | `recipes/scheduler-feature.md` |
| Per-tenant rate limiting | `model_gateway/src/rate_limit/`, `model_gateway/src/routers/grpc/common/stages/rate_limit.rs`: token and request budgets per tenant, reserve/settle in the gRPC pipeline | `recipes/rate-limit-feature.md` |
| Tenancy and serving auth | `model_gateway/src/tenant/`, `model_gateway/src/middleware/tenant_resolution.rs`, `model_gateway/src/middleware/auth.rs`: tenant identity, per-request resolution, serving-path API keys | `recipes/tenancy-feature.md` |
| Control-plane auth | `crates/auth/`: JWT/OIDC and API keys for the control plane, roles, audit | `recipes/auth-feature.md` |
| Service discovery | `model_gateway/src/service_discovery/`: kubernetes, consul, file and slurm providers behind one reconciler | `recipes/discovery-provider.md` |
| Workers and registration | `model_gateway/src/worker/`, `model_gateway/src/workflow/`: worker registry, health, load, circuit breaking, KV event monitor; registration DAG steps and job queue | `recipes/discovery-feature.md` |
| Workflow engine | `crates/workflow/`: the wfaas step engine the registration DAG runs on | none yet (read the code; `smg:learn` afterwards) |
| Symphony (default parser) | `crates/symphony/`: format tables, registry and checkpoint groups, call-syntax assemblers, grammars, API adapters | `recipes/symphony-format.md` |
| Legacy parsers | `crates/tool_parser/`, `crates/reasoning_parser/`, `crates/response_template/`: per-model tool and reasoning parsers for --parser legacy; the HF response-template port | `recipes/tool-parser.md` |
| Tokenizer | `crates/tokenizer/`, `model_gateway/src/workflow/tokenizer_registration.rs`, `model_gateway/src/endpoints/tokenize/`: HF and tiktoken backends, chat templates and native renderers, stop/EOS decoding, encode cache; gateway-side registration per worker | `recipes/tokenizer.md` |
| KV-cache index | `crates/kv_index/`, `crates/radix_tree/`, `model_gateway/src/worker/kv_event_monitor.rs`, `model_gateway/src/worker/kv_index_backend.rs`: radix trees for routing-side prefix matching, the event-driven chain index, the generic prefix core | `recipes/kv-index-feature.md` |
| gRPC engine clients | `crates/grpc_client/`, `model_gateway/src/routers/grpc/client.rs`: per-engine gRPC clients and protos; the GrpcClient enum | `recipes/grpc-backend.md` |
| ZMQ direct backend | `crates/engine_zmq_client/`, `crates/engine_zmq_adapter/`, `model_gateway/src/routers/grpc/zmq_client.rs`, `model_gateway/src/routers/grpc/backend_client.rs`: same-host ipc:// wire, the per-engine adapter, the gateway seam | `recipes/zmq-backend.md` |
| Engine servicers | `crates/engine_servicer/`, `grpc_servicer/`: the Rust and Python servicers that serve each engine's gRPC proto on the engine node | `recipes/engine-servicer.md` |
| Third-party provider routers | `crates/external_router/`, `model_gateway/src/routers/external.rs`, `model_gateway/src/routers/provider_support.rs`: OpenAI, Anthropic, Gemini and xAI routers and the shared glue (SSE, retry, MCP utils, realtime) | `recipes/provider-api.md` |
| MCP | `crates/mcp/`: MCP client: inventory, approval policy, transports | `recipes/mcp-feature.md` |
| Storage | `crates/data_connector/`: conversation and response storage backends, migrations, hooks, bounds | `recipes/storage-backend.md` |
| Multimodal | `crates/multimodal/`, `crates/mm_rdma/`, `model_gateway/src/routers/grpc/multimodal/`: vision and audio processors, model specs, media fetching; gateway planning and the capability matrix | `recipes/multimodal-feature.md` |
| WASM plugins | `crates/wasm/`, `examples/wasm/`, `model_gateway/src/wasm/`, `model_gateway/src/middleware/wasm.rs`: the WASM host, the WIT world, middleware guests | `recipes/wasm-plugin.md` |
| Mesh HA | `crates/mesh/`, `model_gateway/src/mesh/`: SWIM gossip, CRDT namespaces, gateway wiring | `recipes/mesh-feature.md` |
| Observability | `model_gateway/src/observability/`, `model_gateway/src/middleware/metrics.rs`, `model_gateway/src/middleware/logging.rs`: metrics, OTel tracing, structured logging, runtime self-metrics | `recipes/observability-feature.md` |
| RL control plane | `crates/rl/`: worker discovery, engine-route passthrough and fan-out; inert unless --enable-rl | none yet (read the code; `smg:learn` afterwards) |
| Bindings | `bindings/`: Python PyO3 Router and launcher, servicer bindings, Go SDK | `recipes/bindings-update.md` |
| Generated clients | `clients/`: the OpenAPI spec and Python/Java clients generated from protocol types; the Rust client | `recipes/protocols-profile.md` |
| E2E harness and CI | `e2e_test/`, `scripts/`, `.github/workflows/`: e2e suites, fixtures and launchers, CI tooling and workflows | `recipes/e2e-lane.md` |
| Mock workers and test harness | `crates/mock_worker/`, `model_gateway/test_harness/`: mock HTTP/gRPC/ZMQ workers and the in-process app builders every wire feature needs an arm in | none yet (read the code; `smg:learn` afterwards) |
| Helm chart | `deploy/`: the chart; its arguments are pinned to RouterArgs by a bindings test | `recipes/config-plumbing.md` |
<!-- /render -->

## Commands

`cargo +nightly fmt --all` · `cargo clippy --workspace --all-targets --all-features -- -D warnings` (drop `--all-features` without system OpenCV) · `cargo test -p <package>` · `make python-dev` after config, protocol or binding changes · `bash "${CLAUDE_PLUGIN_ROOT}/scripts/gate.sh"` for the whole pre-PR gate.

## Next

`smg:implement` to build with a recipe · `smg:craft` before writing non-trivial code · `smg:review-pr` · `smg:contribute` to ship · `smg:learn` when this map is wrong. Deeper notes (subsystem types, CI lanes, policy eligibility, tokenizer registration, ZMQ constraints, e2e markers): `reference.md` in this directory.

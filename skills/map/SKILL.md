---
name: map
description: Orient in the SMG (Shepherd Model Gateway) codebase before changing it — which crate or gateway module owns a subsystem, how config, requests and workers flow, and the invariants a change must respect. Use for "where does X live", "how does Y work", or before any change that touches more than one file.
---

# SMG Codebase Map

SMG is a Rust gateway in front of LLM inference engines (SGLang, vLLM, TensorRT-LLM, TokenSpeed, MLX) and cloud providers (OpenAI, Anthropic, Gemini, xAI). It owns worker lifecycle, routing, admission, tenancy, parsing of model output, chat-history storage, MCP tooling and observability behind OpenAI-, Anthropic- and Gemini-compatible APIs (plus Responses, Conversations and Realtime). Workers attach over HTTP, gRPC, or same-host ZMQ.

## Live map

The block below is generated from the checkout you are in, so crate names, descriptions, the policy list and parser counts cannot go stale:

!`bash "${CLAUDE_PLUGIN_ROOT}/scripts/map_live.sh"`

If you see the command above instead of its output, your runtime does not expand dynamic context: run `scripts/map_live.sh` from the smg-dev-guide checkout yourself, passing any directory inside the SMG checkout.

## Invariants

Slow to change, but still read the code when a change depends on one of them.

### Layering

```
crates/protocols   shared OpenAI/Anthropic/Gemini types — every consumer reads them
    ↑
model_gateway      implementation — one consumer writes each field
    ↑
bindings/*         Python (PyO3) and Go SDKs wrap model_gateway + protocols
```

Library crates live under `crates/`; `model_gateway/`, `bindings/`, `clients/` and `grpc_servicer/` sit at the repo root. **Rule:** a field only one crate writes does not belong in `crates/protocols/`. K8s-, runtime- or gateway-specific fields stay in `model_gateway`.

### Config propagation (two paths)

CLI flags are `CliArgs` fields in `model_gateway/src/main.rs` (shared value parsers in `model_gateway/src/cli/value.rs`). `to_router_config` assembles `RouterConfig` through the hand-written `RouterConfig::builder()` (`config/builder.rs`; types in `config/types.rs`; invariants in `config/validation.rs`, which runs inside `RouterConfigBuilder::build()` for the CLI and the Python bindings alike). `to_server_config` returns a `ServerConfig` struct literal that carries the whole `RouterConfig` nested, so a RouterConfig-only field needs nothing there, while a listener-level setting read off `ServerConfig` by `server::startup` needs a top-level copy in every `ServerConfig` literal. Python re-implements the chain in `bindings/python/src/lib.rs` (`Router::new`, its own `to_router_config`) plus `bindings/python/src/smg/router_args.py`. Recipe: `smg:implement` → `recipes/config-plumbing.md`.

### Request flow

```
Client → axum handler (server.rs)
  → WASM OnRequest → auth → tenant resolution (RouteRequestMeta)
  → admission: priority scheduler OR legacy ConcurrencyLimitLayer (AdmissionMode::from_config, chosen once)
  → routers/gateway.rs picks the family router (single-router mode: the one the config built;
    IGW mode: per request from the model's routing snapshot)
      HTTP workers   → routers/http (proxy; bodies over --stream-request-bodies-over stream verbatim)
      gRPC + ZMQ     → one Mode-parameterized pipeline (routers/grpc/pipeline.rs): worker selection →
                       per-tenant rate-limit reserve → client acquisition → request building →
                       execution → response processing (Symphony or legacy parsers)
      providers      → crates/external_router (OpenAI, Anthropic, Gemini, xAI)
  → WASM OnResponse → Client
```

Middleware order is the reverse of the `route_layer` calls in `server.rs` (last added = outermost). Endpoints that route nothing (tokenize/detokenize, parse, conversations, stored responses, model inventory) live in `model_gateway/src/endpoints/`. Overload-vetoed workers are excluded from selection; an all-overloaded pool sheds 503 + `Retry-After` (`routers/common/overload.rs`).

### Worker lifecycle

Discovery providers (`model_gateway/src/service_discovery/{kubernetes,consul,file,slurm}.rs`) each produce `DiscoveredWorker`s. A level-triggered `reconcile` (`service_discovery/reconciler.rs`) diffs the `DesiredState` against the workers it owns (labels `smg.ai/discovery-provider`, `smg.ai/discovery-id`, `smg.ai/discovery-spec-hash`) into `Job::AddWorker` / `Job::RemoveWorker` (`workflow/job_queue.rs`). Registration is a DAG of steps under `workflow/steps/{local,shared,external}/`, assembled in `steps/mod.rs`:

```
classify → detect_connection (http/grpc/ipc:// honoured, else probe) → detect_backend
  → discover_metadata (flattened into labels) → discover_dp → create_worker (labels → ModelCard)
  → ensure_harmony_encoding → register → { update_policies | submit_tokenizer_job | activate }
```

All worker metadata flows as labels (backend probe → config overrides → `ModelCard`); never add a parallel `_override` field. ZMQ workers skip the probes and stay Pending until the `WorkerConnected` signal (`worker/basic.rs`). gRPC/ZMQ workers are tokenized in the gateway (`workflow/tokenizer_registration.rs`); `/readiness` holds 503 until their tokenizers are registered unless `--disable-tokenizer-autoload`.

### Parsing model output

Symphony (`crates/symphony`) is the default parser: one format table per model family (`src/formats/*.rs`, registry `src/formats/registry.rs`, checkpoint groups `src/formats/groups.json`) turns a model's stream into typed content / reasoning / tool-call events. `--parser legacy` selects the per-model `crates/tool_parser` and `crates/reasoning_parser`; a model outside Symphony's registry uses a table named by worker labels or `--tool-call-parser` / `--reasoning-parser`, else the legacy parsers. `crates/response_template` compiles Hugging Face `chat_parsing` templates into tables. New model support is a Symphony table (`recipes/symphony-format.md`), not a legacy parser.

### Three transports

HTTP (its own router), gRPC (`crates/grpc_client` to the Python `grpc_servicer` or the Rust `crates/engine_servicer`), and same-host ZMQ (`crates/engine_zmq_client` wire + `crates/engine_zmq_adapter` per-engine translation, surfaced as `BackendClient::Zmq`). gRPC and ZMQ share the pipeline (`ConnectionMode::uses_grpc_pipeline()`). A cross-cutting feature supports all three or rejects loudly at registration.

## Where things live

| I need to… | Go to |
|---|---|
| Add a CLI flag | `model_gateway/src/main.rs` (`CliArgs`), parsers in `model_gateway/src/cli/value.rs` |
| Change config types / builder / validation | `model_gateway/src/config/{types,builder,validation}.rs` |
| Change API types | `crates/protocols/src/` (shared by every crate and SDK) |
| Add a routing policy | `model_gateway/src/policies/` (`factory.rs`, `registry.rs`); cache-aware selection pipeline in `policies/cost/` |
| Change admission / scheduling | `model_gateway/src/middleware/scheduler/`, legacy cap in `middleware/concurrency.rs` + `token_bucket.rs` |
| Change tenancy | `model_gateway/src/tenant/`, `middleware/tenant_resolution.rs` |
| Per-tenant rate limits | `model_gateway/src/rate_limit/` (reserve stage `routers/grpc/common/stages/rate_limit.rs`) |
| Change service discovery | `model_gateway/src/service_discovery/` (one file per provider + `reconciler.rs`) |
| Change worker creation / health / registry | `model_gateway/src/worker/` (`basic.rs`, `manager.rs`, `registry.rs`), steps in `workflow/steps/` |
| gRPC pipeline / stages | `model_gateway/src/routers/grpc/` (`pipeline.rs`, `common/stages/`, `regular/stages/`) |
| HTTP proxy router / PD | `model_gateway/src/routers/http/` |
| Third-party provider routers | `crates/external_router/src/` (gateway side `routers/external.rs`, `routers/provider_support.rs`) |
| Add a gRPC engine client | `crates/grpc_client/src/` + `routers/grpc/client.rs` |
| ZMQ direct backend | wire `crates/engine_zmq_client/src/protocol/` (append-only field order), translation `crates/engine_zmq_adapter/src/`, seam `routers/grpc/zmq_client.rs` + `backend_client.rs` |
| Rust engine servicer (gRPC on the engine node) | `crates/engine_servicer/src/` |
| New model's tool-call / reasoning format | `crates/symphony/src/formats/` (+ `registry.rs`, `groups.json`) |
| Legacy parsers | `crates/tool_parser/src/parsers/`, `crates/reasoning_parser/src/parsers/` |
| Tokenizer backends / chat-template renderers | `crates/tokenizer/src/` (`factory.rs`, `encoders/`, `registry.rs`); gateway `workflow/tokenizer_registration.rs`, `endpoints/tokenize/` |
| KV-cache index | `crates/kv_index/src/` (chain index, trees), `crates/radix_tree/`, consumer `policies/cache_aware.rs`, feed `worker/kv_event_monitor.rs` |
| Multimodal | `crates/multimodal/src/` (processors + `registry/`), gateway `routers/grpc/multimodal/` |
| Storage backend | `crates/data_connector/src/` (flat files per backend, `factory.rs`, `versioning.rs`) |
| MCP | `crates/mcp/src/`; request-scoped glue `crates/external_router/src/mcp_utils.rs` |
| WASM middleware | `crates/wasm/src/` (host) + `examples/wasm/` (guests); `middleware/wasm.rs` |
| Auth | serving path `middleware/auth.rs`; control plane `crates/auth/src/` |
| Metrics / tracing / logging | `model_gateway/src/observability/` |
| Mesh HA | `crates/mesh/src/` + gateway glue `model_gateway/src/mesh/` |
| RL control plane | `crates/rl/src/` (inert unless `--enable-rl`) |
| Python bindings / Go SDK | `bindings/python/src/lib.rs` + `bindings/python/src/smg/`; `bindings/golang/` |
| Generated client SDKs | `clients/openapi-gen/` (`make generate-clients`) |
| Mock workers without GPUs | `crates/mock_worker/` (`cargo run -p mock-worker -- --help`), `model_gateway/test_harness/` |
| E2E tests | `e2e_test/` (markers in `e2e_test/fixtures/hooks.py`, harness in `e2e_test/infra/`) |
| User / contributor docs | the separate `smg-project/smg-docs` repository; root `README.md`, `CONTRIBUTING.md`, `REVIEW.md` here |

Per-subsystem detail (policy eligibility and shedding, tokenizer registration, e2e lanes and markers, ZMQ constraints, mesh namespaces): read `reference.md` in this skill's directory.

## Essential commands

```bash
cargo +nightly fmt --all                                           # format (rustfmt.toml: StdExternalCrate, Crate granularity)
cargo clippy --workspace --all-targets --all-features -- -D warnings   # lint (opencv-video needs system OpenCV: bash scripts/install_opencv.sh)
cargo test                                                         # tests (cargo test -p <package> to scope)
make python-dev                                                    # rebuild the Python wheel after config/protocol changes
make generate-clients                                              # regenerate OpenAPI spec + Python/Java SDK types
bash scripts/gate.sh                                               # (this plugin) the whole pre-PR gate, see smg:contribute
```

## Next

- Building something → `smg:implement` picks the recipe for the subsystem and walks you through it with verification steps.
- Shipping → `smg:contribute` runs the pre-PR gate.
- Reviewing → `smg:review-pr` maps changed files to a checklist.
- Found this map wrong → `smg:learn`.

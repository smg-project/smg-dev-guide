# SMG subsystem reference

On-demand notes behind `SKILL.md`. Tables marked as rendered come from `data/subsystems.json`; edit the data, then run `python3 scripts/render.py`.

## Areas and key types

<!-- render:subsystems -->
| Area | Paths | Key types |
|---|---|---|
| Config and CLI | `model_gateway/src/config/`, `model_gateway/src/main.rs`, `model_gateway/src/cli/` | `CliArgs`, `RouterConfig`, `RouterConfigBuilder`, `ConfigValidator`, `PolicyConfig`, `RoutingMode`, `DiscoveryConfig` |
| Protocol types | `crates/protocols/` | `ChatCompletionRequest`, `CreateMessageRequest`, `WorkerSpec`, `ModelCard`, `ConnectionMode`, `ProviderType` |
| App wiring and server | `model_gateway/src/app_context.rs`, `model_gateway/src/server.rs`, `model_gateway/src/server/`, `model_gateway/src/health.rs` | `AppContext`, `AppState`, `ServerConfig` |
| Routing policies | `model_gateway/src/policies/` | `LoadBalancingPolicy`, `PolicyFactory`, `PolicyRegistry`, `SelectWorkerInfo` |
| Routers and dispatch | `model_gateway/src/routers/` | `RouterTrait`, `RouterFactory`, `RequestPipeline`, `BackendClient`, `RequestLease` |
| Non-routing endpoints | `model_gateway/src/endpoints/` |  |
| Admission | `model_gateway/src/middleware/scheduler/`, `model_gateway/src/middleware/concurrency.rs`, `model_gateway/src/middleware/token_bucket.rs` | `PriorityScheduler`, `SchedulerPermit`, `AdmissionMode`, `ConcurrencyLimitLayer`, `TokenBucket` |
| Per-tenant rate limiting | `model_gateway/src/rate_limit/`, `model_gateway/src/routers/grpc/common/stages/rate_limit.rs` | `RateLimitManager`, `RateLimitYaml`, `CompiledPolicySet`, `ReserveRequest` |
| Tenancy and serving auth | `model_gateway/src/tenant/`, `model_gateway/src/middleware/tenant_resolution.rs`, `model_gateway/src/middleware/auth.rs` | `TenantIdentity`, `TenantKey`, `RouteRequestMeta`, `DataPlaneCaller` |
| Control-plane auth | `crates/auth/` | `JwtConfig`, `Principal`, `Role` |
| Service discovery | `model_gateway/src/service_discovery/` | `DiscoveredWorker`, `DesiredState`, `PodInfo`, `RuntimeDiscoveryConfig` |
| Workers and registration | `model_gateway/src/worker/`, `model_gateway/src/workflow/` | `WorkerManager`, `WorkerRegistry`, `LoadSnapshot`, `WorkerConnected`, `Job` |
| Workflow engine | `crates/workflow/` | `WorkflowEngine`, `StepExecutor`, `StepResult` |
| Symphony (default parser) | `crates/symphony/` | `Parser`, `Table`, `Format`, `Event` |
| Legacy parsers | `crates/tool_parser/`, `crates/reasoning_parser/`, `crates/response_template/` | `ToolParser`, `ReasoningParser`, `ParserFactory` |
| Tokenizer | `crates/tokenizer/`, `model_gateway/src/workflow/tokenizer_registration.rs`, `model_gateway/src/endpoints/tokenize/` | `Tokenizer`, `TokenizerRegistry`, `StopSequenceDecoder` |
| KV-cache index | `crates/kv_index/`, `crates/radix_tree/`, `model_gateway/src/worker/kv_event_monitor.rs`, `model_gateway/src/worker/kv_index_backend.rs` | `StringTree`, `TokenTree`, `ChainIndex`, `ShardedChainIndex`, `ReferenceIndexer` |
| gRPC engine clients | `crates/grpc_client/`, `model_gateway/src/routers/grpc/client.rs` | `GrpcClient`, `TraceInjector` |
| ZMQ direct backend | `crates/engine_zmq_client/`, `crates/engine_zmq_adapter/`, `model_gateway/src/routers/grpc/zmq_client.rs`, `model_gateway/src/routers/grpc/backend_client.rs` | `ZmqEngineClient`, `ZmqDialect`, `BackendClient` |
| Engine servicers | `crates/engine_servicer/`, `grpc_servicer/` |  |
| Third-party provider routers | `crates/external_router/`, `model_gateway/src/routers/external.rs`, `model_gateway/src/routers/provider_support.rs` | `ExternalRouter`, `ExternalRouterSpec`, `ExternalContext` |
| MCP | `crates/mcp/` | `McpOrchestrator`, `PolicyEngine`, `McpTransport` |
| Storage | `crates/data_connector/` | `ConversationStorage`, `ResponseStorage`, `StorageBundle`, `Migration` |
| Multimodal | `crates/multimodal/`, `crates/mm_rdma/`, `model_gateway/src/routers/grpc/multimodal/` | `ModelProcessorSpec`, `VisionPreProcessor`, `MediaConnector` |
| WASM plugins | `crates/wasm/`, `examples/wasm/`, `model_gateway/src/wasm/`, `model_gateway/src/middleware/wasm.rs` | `WasmModule`, `MiddlewareAttachPoint` |
| Mesh HA | `crates/mesh/`, `model_gateway/src/mesh/` | `MeshKV`, `CrdtNamespace`, `ClusterState` |
| Observability | `model_gateway/src/observability/`, `model_gateway/src/middleware/metrics.rs`, `model_gateway/src/middleware/logging.rs` | `Metrics` |
| RL control plane | `crates/rl/` |  |
| Bindings | `bindings/` | `Router`, `RouterArgs` |
| Generated clients | `clients/` |  |
| E2E harness and CI | `e2e_test/`, `scripts/`, `.github/workflows/` |  |
| Mock workers and test harness | `crates/mock_worker/`, `model_gateway/test_harness/` |  |
| Helm chart | `deploy/` |  |
<!-- /render -->

## Areas without a recipe yet

Read the code with the live map, follow the general pattern (implement → test → verify → `smg:contribute`), and leave a lesson (`smg:learn`, kind `new-subsystem`) with the steps you had to discover.

<!-- render:no-recipe-areas -->
- **Workflow engine** (`crates/workflow/`): the wfaas step engine the registration DAG runs on
- **RL control plane** (`crates/rl/`): worker discovery, engine-route passthrough and fan-out; inert unless --enable-rl
- **Mock workers and test harness** (`crates/mock_worker/`, `model_gateway/test_harness/`): mock HTTP/gRPC/ZMQ workers and the in-process app builders every wire feature needs an arm in
<!-- /render -->

## CI lanes

Which lanes a change triggers: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.py" <changed files>` (the gate prints it too).

<!-- render:lanes -->
| Lane | What it runs |
|---|---|
| `pre-commit` | pr-test-rust.yml: codespell, whitespace, yaml/toml, ruff, rustfmt, clippy hooks |
| `python-lint` | pr-test-rust.yml: ruff + mypy over e2e_test/, bindings/python/, scripts/ |
| `grpc-proto-build-check` | pr-test-rust.yml: the protos still build |
| `build-wheel` | pr-test-rust.yml: maturin wheel, Go FFI library, generated client types, WASM fixtures |
| `python-unit-tests` | pr-test-rust.yml: bindings/python tests at 80% coverage, scripts/tests |
| `rust-lint` | pr-test-rust.yml: clippy -D warnings in four feature legs (all-features, self-hosted, anthropic-only, default-build) |
| `rust-tests` | pr-test-rust.yml: cargo test, sharded; Postgres and WASM fixtures; vision goldens regenerate |
| `cargo-audit` | pr-test-rust.yml: advisory audit |
| `rust-aarch64` | pr-test-rust.yml: cross-build |
| `benchmarks` | pr-test-rust.yml: genai-bench against mock workers, all policies |
| `e2e-1gpu-chat` | pr-test-rust.yml: chat suite per engine on one GPU |
| `e2e-1gpu-chat-symphony` | pr-test-rust.yml: chat suite under the default parser |
| `e2e-1gpu-chat-rust-servicer` | pr-test-rust.yml: chat suite through crates/engine_servicer |
| `e2e-1gpu-chat-mm-worker` | pr-test-rust.yml: multimodal worker chat |
| `e2e-1gpu-chat-zmq` | pr-test-rust.yml: single-worker chat replayed over ipc:// |
| `e2e-2gpu-chat-zmq-dp` | pr-test-rust.yml: grouped ZMQ engines |
| `e2e-2gpu-pd` | pr-test-rust.yml: prefill/decode disaggregation |
| `e2e-4gpu-epd` | pr-test-rust.yml: encode/prefill/decode |
| `e2e-cpu-mock` | pr-test-rust.yml: the mock-engine CPU job |
| `e2e-vendor` | pr-test-rust.yml: cloud provider routers |
| `go-unit-tests` | pr-test-rust.yml: bindings/golang |
| `go-bindings-e2e` | pr-test-rust.yml: Go SDK against a gateway |
| `e2e-discovery` | e2e-discovery.yml: kind, consul, file and slurm discovery |
| `e2e-mcp-mock` | e2e-mcp-mock.yml: MCP against a mock server |
| `benchmark-radix-tree` | benchmark-radix-tree.yml: on crates/kv_index changes |
| `radix-tree-fuzz` | radix-tree-fuzz.yml |
| `symphony-fuzz` | symphony-fuzz.yml |
| `benchmark-tool-parser` | benchmark-tool-parser.yml |
| `benchmark-tokenizer` | benchmark-tokenizer.yml |
| `ci-tooling-tests` | ci-tooling-tests.yml: scripts/tests |
| `bellwether-fixtures` | bellwether-fixtures.yml: recorded parser corpora |
<!-- /render -->

## Policies: eligibility and shedding

- `LoadBalancingPolicy` (`policies/mod.rs`) is synchronous, `Send + Sync + Debug`; `select_worker` returns an **index** into the worker slice. Filter with `get_healthy_worker_indices`, which applies `Worker::is_available()` (health, circuit breaker, the overload veto latched by the load monitor). Ring policies (`consistent_hashing.rs`, `prefix_hash.rs`) use `is_healthy_and_eligible()` to keep ring membership stable.
- Load-aware policies take the monitor's feed through `set_load_receiver(Option<LoadReceiver>)` and answer `needs_backend_loads() == true`; `remove_worker` and `reconcile_in_flight` keep their tallies honest under churn.
- Routers call `PolicyRegistry::select_worker` (per-model policies, sticky routing-key override through a shared `ManualPolicy`), never a policy directly. Shedding: `overload::shed_if_all_overloaded` on the pool, `shed_if_worker_overloaded` on the pick (`routers/common/overload.rs`); terminal responses call `retry::mark_non_retryable`.
- Dispatch memory: route methods take the parsed body by value; nothing outlives `RequestLease::release_dispatch()` (`routers/common/request_lease.rs`); upstream bodies go through `attach_sized_body` / `serialize_json_sized` and reads through `read_worker_body_capped` (`routers/common/mod.rs`). No per-token `clone()` in `routers/grpc/regular/streaming.rs`.

## Tokenizer registration

gRPC/ZMQ workers are tokenized in the gateway. Each non-HTTP local worker submits `Job::AddTokenizer` (path chain: label `tokenizer_path` → label `model_path` → `--tokenizer-path` → `--model-path`, `workflow/steps/local/submit_tokenizer_job.rs`); `LoadTokenizerStep` loads locally, else streams a healthy gRPC worker's `GetTokenizer` bundle (the ZMQ lane serves none, so `--model-path` is required there). `/readiness` returns 503 until every healthy gRPC/ZMQ worker's tokenizer is registered (`health.rs`) unless `--disable-tokenizer-autoload`. Crate: `crates/tokenizer` (package `llm-tokenizer`): HF and tiktoken backends, Jinja chat templates plus native renderers in `encoders/` picked from `config.json::architectures`, EOS/stop decoding, an L0/L1 encode cache.

## ZMQ direct backend constraints

- SMG binds the `tcp://` handshake and `ipc://` data sockets; the engine dials in. `ConnectionMode::from_url` classifies `ipc://` as `Zmq`; `uses_grpc_pipeline()` is true for gRPC and ZMQ.
- Dialects (`crates/engine_zmq_adapter/src/client.rs::ZmqDialect`): `Vllm`, `TokenSpeed`, `Sglang`, `Trtllm`, a closed set; every match writes all arms, no wildcard.
- Wire structs in `crates/engine_zmq_client/src/protocol/` are positional msgpack: field order is the contract, append only.
- The handshake is never awaited on a request or probe path: `spawn_zmq_connect_driver` (`worker/basic.rs`) connects in the background and the `WorkerConnected` signal promotes the worker; misconfiguration is rejected in `create_worker.rs` (`validate_zmq_*`), not at connect time.
- Token-only wire: string stops and EOS are resolved frontend-side (`engine_zmq_adapter/src/{stops,eos}.rs`, `fold_tokenizer_eos_backstop`); `n > 1` is fanned out (`fanout.rs`). Metrics label `connection_mode="zmq"`.

## E2E markers

- Suites under `e2e_test/`: `chat_completions`, `completions`, `embeddings`, `messages`, `responses`, `realtime`, `router`, `discovery` (`kind`, `consul`, `file`, `slurm`), `bindings_go`, `mlx`, `benchmarks`; CPU-only harness tests in `e2e_test/infra/` and `e2e_test/fixtures/` (`PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra e2e_test/fixtures`).
- Markers are registered in `e2e_test/fixtures/hooks.py::pytest_configure`: `engine`, `vendor`, `gpu`, `model`, `skip_for_runtime`, `gateway(...)`, `workers(...)`, `storage`, `external`, `e2e`, `slow`, `slowtest`, `nightly`; `kind` in `e2e_test/pyproject.toml`. GPU lanes export `E2E_ENGINE` / `E2E_GPU_TIER` and deselect tests without a matching `engine` marker; a missing `gpu` marker defaults to `gpu(1)`.
- Lane knobs: `E2E_CONNECTION_MODE=zmq`, `E2E_PARSER=legacy|symphony` (`e2e_test/infra/constants.py::get_parser`), `SMG_KIND_E2E=1 pytest e2e_test/discovery/kind -m kind`.

## Mesh

`crates/mesh` (package `smg-mesh`): SWIM-style gossip + CRDT replication, application-agnostic (opaque bytes keyed by prefix). Namespaces by key prefix (`worker:`, `policy:`, `rl:`, `config:`); a new replicated value picks a `MergeStrategy` and a prefix, never a new engine. Gateway glue in `model_gateway/src/mesh/` (`wiring.rs` is where replicated knobs land). ZMQ workers are host-local and not published to the mesh.

# SMG subsystem reference

Deeper notes behind the invariants in `SKILL.md`. Each row names the owning code so you can verify it; when a path here is wrong, run `/smg:learn`.

## Gateway subsystems inside `model_gateway/src/`

| Subsystem | Location | Key types |
|---|---|---|
| CLI | `main.rs` (`CliArgs`, `to_router_config`, `to_server_config`), `cli/{url_port,value,secrets}.rs` | `CliArgs`, `Backend`, `TransportMode` |
| Config | `config/{types,builder,validation}.rs` | `RouterConfig`, `RouterConfigBuilder`, `ConfigValidator`, `PolicyConfig`, `RoutingMode`, `DiscoveryConfig` |
| App wiring | `app_context.rs`, `server.rs`, `server/{posture,tls,connection_limit,connection_timeouts}.rs` | `AppContext`, `AppState`, `ServerConfig` |
| Routing policies | `policies/` (`factory.rs`, `registry.rs`, one file per policy, `cost/` for cache-aware selection, `cache_namespace.rs`) | `LoadBalancingPolicy`, `PolicyFactory`, `PolicyRegistry`, `SelectWorkerInfo` |
| Family routers | `routers/gateway.rs` (front), `routers/factory.rs`, `routers/http/`, `routers/grpc/`, `routers/external.rs`, `routers/provider_support.rs`, shared `routers/common/` | `RouterTrait`, `RouterFactory`, `BackendClient`, `RequestLease` |
| Non-routing endpoints | `endpoints/{tokenize,parse,conversations,responses}/`, `endpoints/models.rs` | |
| Admission | `middleware/scheduler/` (priority classes, queues, slots, preemption), `middleware/concurrency.rs` + `middleware/token_bucket.rs` (legacy cap) | `PriorityScheduler`, `SchedulerPermit`, `AdmissionMode`, `ConcurrencyLimitLayer`, `TokenBucket`, `AdmissionQueue` |
| Tenancy | `tenant/mod.rs`, `middleware/tenant_resolution.rs`, `middleware/auth.rs` | `TenantIdentity`, `TenantKey`, `RouteRequestMeta`, `DataPlaneCaller` |
| Per-tenant rate limiting | `rate_limit/` (`manager.rs`, `policy.rs`, `backend.rs`, `local_backend.rs`, `bucket.rs`, `reservation.rs`), stage `routers/grpc/common/stages/rate_limit.rs` | `RateLimitManager`, `RateLimitYaml`, `CompiledPolicySet`, `ReserveRequest` |
| Service discovery | `service_discovery/{mod,provider,reconciler,snapshot,runtime}.rs`, providers `kubernetes.rs`, `consul.rs`, `file.rs`, `slurm.rs` | `DiscoveredWorker`, `DesiredState`, `ServiceDiscoveryConfig`, `PodInfo`, `PodType`, `RuntimeDiscoveryConfig` |
| Workers | `worker/` (`basic.rs`, `builder.rs`, `manager.rs`, `registry.rs`, `monitor.rs`, `load_state.rs`, `overload.rs`, `circuit_breaker.rs`, `kv_event_monitor.rs`, `kv_index_backend.rs`, `pd_pairing.rs`) | `Worker`, `WorkerManager`, `WorkerRegistry`, `LoadSnapshot`, `LoadReceiver`, `WorkerConnected` |
| Registration DAG | `workflow/{job_queue,engines,tokenizer_registration,mcp_registration,wasm_module_registration}.rs`, `workflow/steps/{local,shared,external}/`, `steps/mod.rs` | `Job`, `CreateLocalWorkerStep`, `LoadTokenizerStep` |
| Observability | `observability/` (`metrics.rs`, `otel_trace.rs`, `logging.rs`, `runtime_metrics.rs`, `gauge_histogram.rs`, `inflight_tracker.rs`), `middleware/{metrics,logging,request_id}.rs` | `Metrics` |
| Mesh glue | `mesh/{wiring,adapters,discovery}` (bridges `crates/mesh` namespaces to local registries) | |
| WASM glue | `wasm/{mod,route}.rs`, `middleware/wasm.rs` | |

## Policies: eligibility and shedding

- `LoadBalancingPolicy` (`policies/mod.rs`) is synchronous, `Send + Sync + Debug`; `select_worker` returns an **index** into the worker slice. Filter with `get_healthy_worker_indices`, which applies `Worker::is_available()` (health + circuit breaker + the overload veto latched by the load monitor); ring policies (`consistent_hashing.rs`, `prefix_hash.rs`) use `is_healthy_and_eligible()` to keep ring membership stable.
- Load-aware policies take the monitor's feed through `set_load_receiver(Option<LoadReceiver>)` and answer `needs_backend_loads() == true`; `remove_worker` and `reconcile_in_flight` keep their per-worker tallies honest under churn.
- Routers call `PolicyRegistry::select_worker` (per-model policies, sticky routing-key override via a shared `ManualPolicy`), never a policy directly. Shedding: `overload::shed_if_all_overloaded` on the pool, `overload::shed_if_worker_overloaded` on the pick (`routers/common/overload.rs`); terminal responses call `retry::mark_non_retryable`.
- Dispatch memory: route methods take the parsed body by value; nothing outlives `RequestLease::release_dispatch()` (`routers/common/request_lease.rs`); upstream bodies go through `attach_sized_body` / `serialize_json_sized` and reads through `read_worker_body_capped` (`routers/common/mod.rs`). No per-token `clone()` in `routers/grpc/regular/streaming.rs`.

## Tokenizer registration

gRPC/ZMQ workers are tokenized in the gateway. Each non-HTTP local worker submits `Job::AddTokenizer` (path chain: label `tokenizer_path` → label `model_path` → `--tokenizer-path` → `--model-path`, `workflow/steps/local/submit_tokenizer_job.rs`); `LoadTokenizerStep` loads locally, else streams a healthy gRPC worker's `GetTokenizer` bundle (the ZMQ lane serves none, so `--model-path` is required there). `/readiness` returns 503 until every healthy gRPC/ZMQ worker's tokenizer is registered (`health.rs`) unless `--disable-tokenizer-autoload`. Crate: `crates/tokenizer` (package `llm-tokenizer`): HF and tiktoken backends, Jinja chat templates plus native renderers in `encoders/` picked from `config.json::architectures`, EOS/stop decoding, an L0/L1 encode cache.

## ZMQ direct backend constraints

- SMG binds the `tcp://` handshake and `ipc://` data sockets; the engine dials in. `ConnectionMode::from_url` classifies `ipc://` as `Zmq`; `uses_grpc_pipeline()` is true for gRPC and ZMQ.
- Dialects (`crates/engine_zmq_adapter/src/client.rs::ZmqDialect`): `Vllm`, `TokenSpeed`, `Sglang`, `Trtllm` — a closed set; every match writes all arms, no wildcard.
- Wire structs in `crates/engine_zmq_client/src/protocol/` are positional msgpack: field order is the contract, append only.
- The handshake is never awaited on a request or probe path: `spawn_zmq_connect_driver` (`worker/basic.rs`) connects in the background and the `WorkerConnected` signal promotes the worker; misconfiguration is rejected in `create_worker.rs` (`validate_zmq_*`), not at connect time.
- Token-only wire: string stops and EOS are resolved frontend-side (`engine_zmq_adapter/src/{stops,eos}.rs`, `fold_tokenizer_eos_backstop`); `n > 1` is fanned out (`fanout.rs`).
- Metrics label `connection_mode="zmq"`; CI lanes `e2e-1gpu-chat-zmq` and `e2e-2gpu-chat-zmq-dp` replay single-worker chat cases with `E2E_CONNECTION_MODE=zmq`.

## E2E lanes and markers

- Suites under `e2e_test/`: `chat_completions`, `completions`, `embeddings`, `messages`, `responses`, `realtime`, `router`, `discovery` (`kind`, `consul`, `file`, `slurm`), `bindings_go`, `mlx`, `benchmarks`; CPU-only harness tests in `e2e_test/infra/` and `e2e_test/fixtures/` (`PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra e2e_test/fixtures`).
- Markers are registered in `e2e_test/fixtures/hooks.py::pytest_configure`: `engine`, `vendor`, `gpu`, `model`, `skip_for_runtime`, `gateway(...)`, `workers(...)`, `storage`, `external`, `e2e`, `slow`, `slowtest`, `nightly`; `kind` in `e2e_test/pyproject.toml`. GPU lanes export `E2E_ENGINE` / `E2E_GPU_TIER` and deselect tests without a matching `engine` marker; a missing `gpu` marker defaults to `gpu(1)`.
- Lane knobs: `E2E_CONNECTION_MODE=zmq` (ZMQ replay), `E2E_PARSER=legacy|symphony` (`e2e_test/infra/constants.py::get_parser`), `SMG_KIND_E2E=1 pytest e2e_test/discovery/kind -m kind` (needs kind/kubectl; `.github/workflows/e2e-discovery.yml`).
- PR Rust CI (`.github/workflows/pr-test-rust.yml`): `pre-commit`, `python-lint`, `grpc-proto-build-check`, `build-wheel`, `python-unit-tests`, `rust-lint` (legs `all-features`, `self-hosted`, `anthropic-only`, `default-build` via `scripts/ci_rust_tests.sh lint <leg>`), `rust-tests` (sharded), `cargo-audit`, `rust-aarch64`, `benchmarks`, then path-filtered e2e lanes (`e2e-1gpu-chat`, `-amd`, `-symphony`, `-rust-servicer`, `-mm-worker`, `-zmq`, `e2e-2gpu-chat-zmq-dp`, …). `benchmark-radix-tree.yml` runs on `crates/kv_index/` changes; `symphony-fuzz.yml` and `radix-tree-fuzz.yml` fuzz their crates.

## Mesh

`crates/mesh` (package `smg-mesh`): SWIM-style gossip + CRDT replication, application-agnostic (opaque bytes keyed by prefix). Namespaces by key prefix (`worker:`, `policy:`, `rl:`, `config:`); a new replicated value picks a `MergeStrategy` and a prefix, never a new engine. Gateway glue in `model_gateway/src/mesh/` bridges `MeshKV` namespaces to local registries. ZMQ workers are host-local and not published to the mesh.

## Other crates worth knowing

- `crates/response_template` (`smg-response-template`): Rust port of transformers' `chat_parsing` response templates; a checkpoint's template can compile into a Symphony table (`--tool-call-parser hf`).
- `crates/radix_tree` (`smg-radix-tree`): generic prefix-membership index with a differential-test referee (`tests/differential.rs`); `crates/kv_index` holds the gateway-facing `ChainIndex` / `ShardedChainIndex` (event-driven) and the `StringTree` / `TokenTree` radix trees (routing-side prefix matching).
- `crates/rl` (`smg-rl`): RL control plane (worker discovery, engine-route passthrough, label-selected fan-out), compiled in but inert unless `--enable-rl`.
- `crates/engine_servicer` (`engine-servicer`): Rust servicers for the per-engine gRPC proto, served over the same-host ZMQ adapter — the Rust replacement for the Python `grpc_servicer`; lane `e2e-1gpu-chat-rust-servicer`.
- `crates/mock_worker` (`mock-worker`) and `model_gateway/test_harness` (`smg-test-harness`): multi-port mock HTTP/gRPC/ZMQ workers and app builders for in-process tests (`scripts/scale_test.sh`, `scripts/sim_ab.sh`).

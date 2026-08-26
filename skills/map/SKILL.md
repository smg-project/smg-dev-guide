---
name: map
description: Use when you need to understand the SMG codebase structure, find which crate owns a subsystem, or understand how crates depend on each other before making changes
---

# SMG Codebase Map

## What Is SMG?

High-performance Rust gateway for LLM inference backends. Routes requests to workers running vLLM, SGLang, TensorRT-LLM, MLX (and more) with 10 routing policies, KV cache optimization, K8s service discovery, WASM plugins, MCP tool execution, and mesh HA. Exposes OpenAI-, Anthropic-, and Gemini-compatible APIs (plus Responses, Conversations, and Realtime/WebSocket), with a priority admission scheduler, multi-tenancy, and rate limiting. Workers attach over HTTP, gRPC, or direct ZMQ (`ConnectionMode::{Http, Grpc, Zmq}`).

## Crate Map

| Crate | Role | Key Types |
|-------|------|-----------|
| `model_gateway` | Main binary. HTTP/gRPC handlers, routing engine, service discovery, observability, CLI | `RouterConfig`, `ServerConfig`, `CliArgs` |
| `protocols` | OpenAI-compatible types shared by ALL consumers (config, bindings, API). Sacred — no impl-specific fields. `ConnectionMode::from_url` is the single scheme→mode classifier (`ipc://` = ZMQ) | `WorkerSpec`, `ModelCard`, `WorkerModels`, `ConnectionMode`, `ChatCompletionRequest/Response` |
| `kv_index` | KV cache-aware routing. Radix trees (String for HTTP, Token for gRPC), positional indexer | `StringTree`, `TokenTree`, `RadixTree` trait, `PositionalIndexer` |
| `auth` | API key (SHA-256 hashed), JWT/OIDC, role-based access (Admin/User), audit logging | `JwtConfig`, `ApiKeyEntry`, `Principal`, `Role` |
| `mesh` | HA cluster via SWIM gossip. CRDT KV store, partition detection, consistent hashing | `ClusterState`, `WorkerState`, `NodeStatus` |
| `wasm` | WebAssembly plugin system. WIT interface, middleware hooks (OnRequest/OnResponse), LRU cache | `WasmModule`, `Action` (Continue/Reject/Modify) |
| `mcp` | MCP protocol client. Tool discovery, execution, approval workflows, response format translation | `McpConfig`, `McpOrchestrator`, `ToolAnnotations` |
| `grpc_client` | Per-engine gRPC clients for backends. Macros for shared logic; trace injection via `TraceInjector` | `SglangSchedulerClient`, `VllmEngineClient`, `TrtllmServiceClient`, `MlxEngineClient`, `TokenSpeedSchedulerClient` |
| `engine_zmq_client` | Direct ZMQ transport to a same-host engine (crate `engine-zmq-client`), bypassing the Python gRPC servicer: `tcp://` handshake + `ipc://` data plane, gateway binds and engines dial in. Generic over `EngineProtocol`, with two dialects — vLLM EngineCore (clean-room port of vLLM's `vllm-engine-core-client`) and TokenSpeed. Feature `mock-engine` exposes a mock EngineCore | `EngineProtocol`, `Client<P>` (`EngineCoreClient`/`TokenSpeedClient`), `RequestStream`, `connect_handshake`, `EngineId` |
| `data_connector` | Pluggable storage: PostgreSQL, Oracle, Redis, in-memory. Hook system for interception | `ConversationStorage`/`ConversationItemStorage`/`ResponseStorage` traits, `StorageHook` |
| `tool_parser` | 17 tool call parsers (JSON, Mistral, Qwen, DeepSeek, Pythonic, Kimi-K2/K3, Inkling, Sarashina, etc.). Streaming with incremental JSON | `ToolParser` trait, `ParserFactory`, `StreamingParseResult` |
| `reasoning_parser` | Reasoning extraction from 9 model families (DeepSeek-R1, Qwen3, Kimi/Kimi-K3, GLM, Step3, MiniMax, Cohere, Nano, Inkling). Streaming | `ReasoningParser` trait, `ParserFactory`, `ParserResult` |
| `tokenizer` | LLM tokenization (crate `llm-tokenizer`): HF / tiktoken backends (Kimi-K2/K2.5/K2.6 is a tiktoken specialization, `kimi_k2_tokenizer.rs`), Jinja chat templates plus native renderers in `encoders/`, picked from `config.json::architectures` (DeepSeek-V3.2/V4 by `huggingface.rs:detect_renderer_from_config`, Kimi-K2.5 tools / Kimi-K3 XTML by `tiktoken.rs:detect_renderer_from_config`); EOS + stop-sequence decoding, L0/L1 encode cache, and the id+name registry the gateway loads into | `Tokenizer`, `TokenizerRegistry`, `StopSequenceDecoder`, `CachedTokenizer` |
| `multimodal` | Image/audio processing (crate `llm-multimodal`). Per-model specs in `registry/` (LLaVA/LLaVA-Next, Qwen-VL/Qwen3-VL/Qwen3-Omni, Llama4, Phi3-V, Kimi-K2.5/K3, Inkling, Qwen3-ASR audio), processors under `vision/processors/` + `audio/processors/`, media fetching | `ImageFrame`, `MediaContentPart`, `MediaConnector` |
| `mm_rdma` | Multimodal pixel RDMA (NIXL) transport for the gateway (crate `smg-mm-rdma`) | |
| `workflow` | Step-based async DAG workflow engine (crate `wfaas`); the gateway wraps it in `model_gateway/src/workflow/engines.rs` and feeds it from `workflow/job_queue.rs` (`Job::{AddWorker, RemoveWorker, UpdateWorker, AddTokenizer, ...}`). A step returning `StepResult::Skip` does NOT persist its context mutations — decide to skip before writing `context.data` | `WorkflowEngine`, `WorkflowDefinition`, `StepDefinition`, `StepExecutor`, `WorkflowContext`, `StepResult` |
| `bindings/python` | PyO3 bindings. `Router` class with ~140 constructor params, enum mapping | `Router`, `PolicyType` |
| `bindings/golang` | Go SDK via FFI (cgo). OpenAI-style API, streaming, tool calling | `Client`, `ChatCompletionRequest` |
| `clients/rust` | Rust client library | |
| `clients/python`, `clients/java` | Client SDKs generated from the OpenAPI spec | |
| `clients/openapi-gen` | Generates the OpenAPI spec + Python/Java client SDKs from protocol types (`make generate-clients`) | |
| `mock_worker` | Multi-port mock HTTP/gRPC/ZMQ inference-worker harness (package `mock-worker`, lib `mock_worker` + binary, so in-process tests can drive it). gRPC side speaks the TokenSpeed scheduler; `--zmq-handshake <addr> --zmq-count N` runs mock vLLM EngineCore ranks that dial the gateway (via `engine-zmq-client`'s `mock-engine` feature); `--engine realistic` adds a continuous-batching simulator. Rigs: `scripts/scale_test.sh`, `scripts/sim_ab.sh` | `Config`, `http::serve`/`grpc::serve`/`zmq::serve` |
| `grpc_servicer` | Python gRPC servicer wrapping vLLM/SGLang/MLX/TokenSpeed backends | |

## Subsystems Inside `model_gateway`

Beyond the crates, `model_gateway/src/` hosts several gateway-only subsystems. **There is no longer a `model_gateway/src/core/` directory** — routing and worker code moved to the locations below.

| Subsystem | Location | Role | Key Types |
|-----------|----------|------|-----------|
| Routing policies | `policies/` | 10 load-balancing policies + factory + per-model registry | `LoadBalancingPolicy`, `PolicyFactory`, `PolicyRegistry`, `SelectWorkerInfo` |
| Provider routers | `routers/` | OpenAI, Anthropic, Gemini APIs + Responses, Conversations, Realtime/WebSocket, gRPC | `RouterManager` |
| Priority scheduler | `middleware/scheduler/` | Priority-aware admission, per-class queues, slots, preemption, capacity reservations, autoscaling metrics | `PriorityScheduler`, `SchedulerPermit`, `Class`, `AdmitOutcome`, `TenantPolicy` |
| Multi-tenancy | `tenant.rs` + `middleware/tenant_resolution.rs` | Canonical tenant identity + per-request resolution | `TenantIdentity`, `TenantKey`, `DataPlaneCaller`, `RouteRequestMeta` |
| Rate limiting | `rate_limit/` + `middleware/token_bucket.rs`, `middleware/concurrency.rs` | Per-tenant token/request budgets (`--tenant-rate-limit-enabled`, `--tenant-rate-limit-config`; reserve/settle runs in the gRPC pipeline stage `routers/grpc/common/stages/rate_limit.rs`) + the global token-bucket concurrency cap | `RateLimitManager`, `RateLimitYaml`, `CompiledPolicySet`, `ReserveRequest`, `TokenBucket` |
| Worker lifecycle | `worker/` + `workflow/steps/local/` | Worker registry, health/circuit breaking, and the discovery→create DAG | `WorkerManager`, `CreateLocalWorkerStep` |
| ZMQ direct backend | `routers/grpc/{backend_client,zmq_client,zmq_multimodal}.rs` + `worker/worker.rs` (handshake driver) | Same-host `ipc://` workers ride the gRPC router pipeline behind `BackendClient::Zmq`; `ZmqEngineClient` translates the engine proto request to the `engine-zmq-client` wire and back, fans out `n`, folds tokenizer EOS ids into `stop_token_ids`, and drops string `stop` (the wire is token-only; the router's stop decoder trims them). Workers stay Pending until the detached handshake lands, then the `WorkerConnected` signal promotes them. No admin RPCs, KV events, PD/EPD legs, or mesh publication over ZMQ | `BackendClient`, `ZmqEngineClient`, `ZmqDialect`, `ZmqGenerateStream` |
| Tokenizer registration | `workflow/tokenizer_registration.rs`, `workflow/steps/local/submit_tokenizer_job.rs`, `routers/tokenize/` | gRPC/ZMQ workers are tokenized in the gateway: each non-HTTP local worker submits `Job::AddTokenizer` (path chain: label `tokenizer_path` → label `model_path` → `--tokenizer-path` → `--model-path`); `LoadTokenizerStep` loads locally, else streams a healthy gRPC worker's `GetTokenizer` bundle (the ZMQ backend serves none). `/readiness` holds at 503 until every healthy gRPC/ZMQ worker's tokenizer is registered (`health.rs`), unless `--disable-tokenizer-autoload` | `TokenizerRegistry`, `TokenizerConfigRequest`, `LoadTokenizerStep`, `SubmitTokenizerJobStep` |

## Layering Rule

```
crates/protocols (shared types — ALL consumers)
    ↑
model_gateway (implementation — ONE consumer writes each field)
    ↑
bindings/* (language SDKs — wrap model_gateway + protocols)
```

**Directory layout**: Library crates live under `crates/` (e.g. `crates/mcp/`, `crates/mesh/`). `model_gateway/`, `bindings/`, `clients/`, and `grpc_servicer/` remain at repo root.

**Iron law**: If only one crate writes a field, it doesn't belong in `crates/protocols/`. K8s-specific, runtime-specific, or gateway-specific fields stay in `model_gateway`.

## Config Propagation (3-Stage)

```
CLI args (main.rs CliArgs) + YAML file (RouterConfig)
    ↓ merge (CLI overrides file)
DiscoveryConfig / RouterConfig (config/types.rs) — serde-friendly, user-facing
    ↓ convert in main.rs (TWO paths: to_router_config + to_server_config)
ServiceDiscoveryConfig / ServerConfig — typed, runtime
```

**Both conversion paths** in main.rs must stay in sync. Miss one = CLI flag or config file silently ignored.

## Request Flow

```
Client → HTTP/gRPC handler (OpenAI / Anthropic / Gemini router)
  → WASM OnRequest → Auth → Tenant resolution
  → Admission (priority scheduler OR legacy concurrency/token-bucket — never both)
  → (gRPC pipeline only: per-tenant rate-limit reserve)
  → Routing policy selects worker → Proxy to backend
  → Stream response → Tool/reasoning parsing → WASM OnResponse → Client

Realtime (WebSocket):
Client → WS upgrade → Realtime session registry → Proxy to backend WS
```

**Middleware order is the reverse of the `route_layer` calls** in `server.rs` (last added = outermost), which is why WASM runs before auth. `with_admission_layer` installs either the priority scheduler or the legacy concurrency limiter, not a chain of both.

**gRPC and ZMQ workers share one pipeline** (`ConnectionMode::uses_grpc_pipeline()`), differing only in `BackendClient::Grpc` vs `BackendClient::Zmq` (metrics label `connection_mode="zmq"`); HTTP workers are proxied by their own router. Overload-vetoed workers are excluded from selection, and an all-overloaded fleet sheds 503 + `Retry-After` (`routers/common/overload.rs`). On the HTTP path, bodies over `--stream-request-bodies-over` bypass the typed path entirely — streamed verbatim, never parsed, never retried.

## Worker Lifecycle (Discovery DAG)

Steps live under `model_gateway/src/workflow/steps/` (branches `local/`, `shared/`, `external/`, assembled in `steps/mod.rs`) — a DAG, not a fixed 5-step list. Discovery itself is level-triggered (a reconcile pass over a kube reflector store), not edge-triggered — there is no `handle_pod_event`:

```
K8s pod store → reconcile_workers() (service_discovery.rs)
  → compute_desired_state() [PodInfo::from_pod() per pod; one worker per port in
      the `smg.ai/worker-ports` annotation] → compute_actions()
  → Job::AddWorker / Job::RemoveWorker (workflow/job_queue.rs)

  classify_worker_type (waits worker_startup_delay_secs)
  → detect_connection_mode (explicit http/grpc/ipc:// scheme honored, else probe
      HTTP+gRPC every worker_startup_check_interval_secs)
  → detect_backend (sglang/vllm/trtllm/tokenspeed/mlx; unidentified OpenAI-compatible
      HTTP → `generic`; ZMQ defaults to vLLM unless runtime_type is set)
  → discover_metadata (flattens into labels HashMap) → discover_dp_info (rank/size)
  → create_local_worker (merge labels, resolve model_id, build ModelCard)
  → ensure_harmony_encoding (gpt-oss gRPC/ZMQ only) → register_workers
  → { update_policies | submit_tokenizer_job (non-HTTP) | activate_workers }
```

**ZMQ workers short-circuit the probes**: `detect_connection_mode` is a no-op (SMG binds, the engine dials), `discover_metadata` yields no labels, `discover_dp_info` takes `dp_size` from the spec. `create_local_worker` requires `--model-path` (EngineCore reports no served model name), forces health checks on, and rejects Prefill/Decode/Encode worker types, dp-aware expansion, runtimes other than vllm/tokenspeed, and handshake-port collisions. `activate_workers` leaves them Pending until the `WorkerConnected` signal arrives.

## The Label Pipeline

Central integration pattern. All worker metadata flows as key-value labels:
- **Source**: Backend HTTP endpoints (flattened JSON → HashMap)
- **Override**: WorkerSpec.labels from config (takes precedence)
- **Consumed**: create_worker.rs reads labels to build ModelCard
- **To inject metadata**: add as label — pipeline handles merging

## Essential Commands

```bash
cargo +nightly fmt --all                                      # Format
cargo clippy --all-targets --all-features -- -D warnings      # Lint
cargo test                                                     # Test
make python-dev                                                # Python bindings
make generate-clients                                          # Regenerate OpenAPI spec + Python/Java SDKs
make pre-commit                                                # All checks
```

## Next Steps

- **Implementing?** Use `smg:implement` — detects the subsystem and loads step-by-step recipes with verification.
- **Preparing to ship?** Use `smg:contribute` — enforces quality gates before PR.
- **Reviewing a PR?** Use `smg:review-pr` — systematic checklist mapped to changed subsystems.

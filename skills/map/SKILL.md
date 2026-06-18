---
name: map
description: Use when you need to understand the SMG codebase structure, find which crate owns a subsystem, or understand how crates depend on each other before making changes
---

# SMG Codebase Map

## What Is SMG?

High-performance Rust gateway for LLM inference backends. Routes requests to workers running vLLM, SGLang, TensorRT-LLM, MLX (and more) with 9 routing policies, KV cache optimization, K8s service discovery, WASM plugins, MCP tool execution, and mesh HA. Exposes OpenAI-, Anthropic-, and Gemini-compatible APIs (plus Responses, Conversations, and Realtime/WebSocket), with a priority admission scheduler, multi-tenancy, and rate limiting.

## Crate Map

| Crate | Role | Key Types |
|-------|------|-----------|
| `model_gateway` | Main binary. HTTP/gRPC handlers, routing engine, service discovery, observability, CLI | `RouterConfig`, `ServerConfig`, `CliArgs` |
| `protocols` | OpenAI-compatible types shared by ALL consumers (config, bindings, API). Sacred — no impl-specific fields. | `WorkerSpec`, `ModelCard`, `WorkerModels`, `ChatCompletionRequest/Response` |
| `kv_index` | KV cache-aware routing. Radix trees (String for HTTP, Token for gRPC), positional indexer | `StringTree`, `TokenTree`, `RadixTree` trait, `PositionalIndexer` |
| `auth` | API key (SHA-256 hashed), JWT/OIDC, role-based access (Admin/User), audit logging | `JwtConfig`, `ApiKeyEntry`, `Principal`, `Role` |
| `mesh` | HA cluster via SWIM gossip. CRDT KV store, partition detection, consistent hashing | `ClusterState`, `WorkerState`, `NodeStatus` |
| `wasm` | WebAssembly plugin system. WIT interface, middleware hooks (OnRequest/OnResponse), LRU cache | `WasmModule`, `Action` (Continue/Reject/Modify) |
| `mcp` | MCP protocol client. Tool discovery, execution, approval workflows, response format translation | `McpConfig`, `McpOrchestrator`, `ToolAnnotations` |
| `grpc_client` | Per-engine gRPC clients for backends. Macros for shared logic; trace injection via `TraceInjector` | `SglangSchedulerClient`, `VllmEngineClient`, `TrtllmServiceClient` |
| `data_connector` | Pluggable storage: PostgreSQL, Oracle, Redis, in-memory. Hook system for interception | `ConversationStorage`/`ConversationItemStorage`/`ResponseStorage` traits, `StorageHook` |
| `tool_parser` | 14 tool call parsers (JSON, Mistral, Qwen, DeepSeek, Pythonic, etc.). Streaming with incremental JSON | `ToolParser` trait, `ParserFactory`, `StreamingParseResult` |
| `reasoning_parser` | Reasoning extraction from 8 model families (DeepSeek-R1, Qwen3, Kimi, GLM, Step3, MiniMax, Cohere, Nano). Streaming | `ReasoningParser` trait, `ParserFactory`, `ParserResult` |
| `tokenizer` | LLM tokenization, chat templates | `Tokenizer` |
| `multimodal` | Image/audio processing (crate `llm-multimodal`). Per-model vision specs (LLaVA, Qwen-VL, Llama4, Phi3/4-V, Pixtral, Kimi-VL), media fetching | `ImageFrame`, `MediaContentPart`, `MediaConnector` |
| `workflow` | Step-based async workflow engine (wfaas) | `StepExecutor`, `WorkflowContext` |
| `bindings/python` | PyO3 bindings. `Router` class with ~110 constructor params, enum mapping | `Router`, `PolicyType` |
| `bindings/golang` | Go SDK via FFI (cgo). OpenAI-style API, streaming, tool calling | `Client`, `ChatCompletionRequest` |
| `clients/rust` | Rust client library | |
| `clients/python`, `clients/java` | Client SDKs generated from the OpenAPI spec | |
| `clients/openapi-gen` | Generates the OpenAPI spec + Python/Java client SDKs from protocol types (`make generate-clients`) | |
| `mock_worker` | Multi-port mock HTTP/gRPC inference-worker harness (package `mock-worker`, supports the TokenSpeed engine). Runs many fake workers in one process for routing/scale testing | (binary) |
| `grpc_servicer` | Python gRPC servicer wrapping vLLM/SGLang backends | |

## Subsystems Inside `model_gateway`

Beyond the crates, `model_gateway/src/` hosts several gateway-only subsystems. **There is no longer a `model_gateway/src/core/` directory** — routing and worker code moved to the locations below.

| Subsystem | Location | Role | Key Types |
|-----------|----------|------|-----------|
| Routing policies | `policies/` | 9 load-balancing policies + factory + per-model registry | `LoadBalancingPolicy`, `PolicyFactory`, `PolicyRegistry`, `SelectWorkerInfo` |
| Provider routers | `routers/` | OpenAI, Anthropic, Gemini APIs + Responses, Conversations, Realtime/WebSocket, gRPC | `RouterManager` |
| Priority scheduler | `middleware/scheduler/` | Priority-aware admission, per-class queues, slots, preemption, capacity reservations, autoscaling metrics | `PriorityScheduler`, `SchedulerPermit`, `Class`, `AdmitOutcome`, `TenantPolicy` |
| Multi-tenancy | `tenant.rs` + `middleware/tenant_resolution.rs` | Canonical tenant identity + per-request resolution | `TenantIdentity`, `TenantKey`, `DataPlaneCaller`, `RouteRequestMeta` |
| Rate limiting | `middleware/token_bucket.rs`, `middleware/concurrency.rs` | Token-bucket rate limiting + concurrency caps | |
| Worker lifecycle | `worker/` + `workflow/steps/local/` | Worker registry, health/circuit breaking, and the discovery→create DAG | `WorkerManager`, `CreateLocalWorkerStep` |

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
  → Auth → Tenant resolution → Rate limit → Scheduler admission → WASM OnRequest
  → Routing policy selects worker → Proxy to backend
  → Stream response → Tool/reasoning parsing → WASM OnResponse → Client

Realtime (WebSocket):
Client → WS upgrade → Realtime session registry → Proxy to backend WS
```

## Worker Lifecycle (Discovery DAG)

Steps live under `model_gateway/src/workflow/steps/` (branches `local/`, `shared/`, `external/`, assembled in `steps/mod.rs`) — a DAG, not a fixed 5-step list:

```
K8s Pod → PodInfo::from_pod() (service_discovery.rs) → handle_pod_event() → AddWorker
  classify_worker_type → detect_connection_mode → detect_backend (sglang/vllm/trt/tokenspeed/mlx)
  → discover_metadata (flattens into labels HashMap) → discover_dp_info (rank/size)
  → create_local_worker (merge labels, resolve model_id, build ModelCard)
```

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

---
name: implement
description: Build or change anything in the SMG repository — features, fixes, flags, parsers, routing policies, backends, bindings. Routes the task to the matching step-by-step recipe (21 subsystems, each with file paths, code shapes and verification commands) and records what the recipe got wrong so the guide improves.
---

# SMG Implementation Workflow

## The rule

```
NO IMPLEMENTATION CODE BEFORE THE MATCHING RECIPE IS LOADED
```

Recipes exist because people who know the subsystem still miss the two-path config rule, the Python builder chain, the append-only wire structs, and the Symphony registry row. Identify what you are building, load the recipe, follow its steps, run its verification commands.

<HARD-GATE>
Do NOT write implementation code until you have:
1. Matched the request to the detection table below
2. Read the matching recipe file(s) in `recipes/`
3. Created a task for each recipe step
</HARD-GATE>

**Escape hatch:** a single-file change under 20 lines that touches none of `config/types.rs`, `crates/protocols/`, `main.rs` (`CliArgs` or the conversion functions), `bindings/`, `crates/symphony/src/formats/registry.rs`, or `crates/engine_zmq_client/src/protocol/` (positional msgpack: field order is the wire contract) may skip the recipe. It must still chain to `smg:contribute` before a PR.

## Detection table

| Signal in the request | Recipe |
|---|---|
| CLI flag, config field, YAML config, `RouterConfig`, `ServerConfig` | `recipes/config-plumbing.md` |
| Routing policy, load balancing, worker selection | `recipes/routing-policy.md` |
| A model's tool-call or reasoning format, `<think>`, chat template parsing, Symphony table, "support model X" | `recipes/symphony-format.md` (the default parser) |
| Legacy tool parser (`--parser legacy`, `crates/tool_parser`) | `recipes/tool-parser.md` |
| Legacy reasoning parser (`--parser legacy`, `crates/reasoning_parser`) | `recipes/reasoning-parser.md` |
| Python binding, Go SDK, FFI, PyO3, maturin | `recipes/bindings-update.md` |
| K8s / Consul / Slurm / file discovery, pod, worker lifecycle, label pipeline | `recipes/discovery-feature.md` |
| gRPC engine client, tonic, backend streaming (an `ipc://` worker is ZMQ, next row) | `recipes/grpc-backend.md` |
| ZMQ, `ipc://` worker, direct backend, EngineCore, headless vLLM/TokenSpeed/SGLang, handshake, msgpack wire | `recipes/zmq-backend.md` |
| Storage, database, PostgreSQL, Oracle, Redis, data connector, chat history | `recipes/storage-backend.md` |
| WASM, WebAssembly plugin, middleware hook | `recipes/wasm-plugin.md` |
| Auth, API key, JWT, OIDC, role, control plane | `recipes/auth-feature.md` |
| Metrics, tracing, logging, Prometheus, OTEL | `recipes/observability-feature.md` |
| Mesh, gossip, CRDT, cluster, partition, SWIM | `recipes/mesh-feature.md` |
| MCP, tool execution, approval policy, MCP transport | `recipes/mcp-feature.md` |
| KV cache, cache-aware routing, radix tree, chain index, prefix matching | `recipes/kv-index-feature.md` |
| Image, audio, video, vision processor, multimodal | `recipes/multimodal-feature.md` |
| Third-party provider upstream (OpenAI, Anthropic, Gemini, xAI, an OpenAI-compatible vendor), `--backend anthropic`, `RoutingMode::{OpenAI,Anthropic,Gemini}`, `crates/external_router` | `recipes/provider-api.md` |
| Priority scheduler, admission, preemption, queue, reservation, service class | `recipes/scheduler-feature.md` |
| Multi-tenancy, tenant key, tenant resolution, per-tenant state | `recipes/tenancy-feature.md` |
| Rate limit, token bucket, concurrency cap, per-tenant quota, reserve/settle | `recipes/rate-limit-feature.md` |

**Several match:** load all of them. `recipes/config-plumbing.md` co-applies to almost every feature (most need a config field), and `recipes/bindings-update.md` to every new `RouterConfig` field.

### Subsystems without a dedicated recipe yet

Read the code with `smg:map` (its `reference.md` has the owning files), then follow the general pattern: implement → test → verify → `smg:contribute`. `config-plumbing.md` usually co-applies. When you finish, consider leaving a lesson (`smg:learn`, kind `new-subsystem`) with the steps you had to discover.

| Signal | Where it lives |
|---|---|
| Responses / Conversations / stored-response endpoints, tokenize, parse, model inventory | `model_gateway/src/endpoints/`; the gRPC pipeline's `routers/grpc/regular/stages/`, Harmony in `routers/grpc/harmony/` |
| Realtime (WebSocket / WebRTC) | `crates/external_router/src/realtime/` (re-exported at `routers/common`), `server.rs` realtime routes |
| Tokenizer backend, chat-template renderer, stop/EOS decoding | `crates/tokenizer/src/` (`factory.rs`, `encoders/`, `registry.rs`); gateway `workflow/tokenizer_registration.rs`, `endpoints/tokenize/`; `cargo test -p llm-tokenizer` |
| Workflow engine, registration step, DAG, job queue | `crates/workflow/` (`wfaas`: `StepExecutor`, `StepDefinition`, `StepResult`; a step returning `StepResult::Skip` does not persist its context writes) + `model_gateway/src/workflow/steps/{local,shared,external}/`, `steps/mod.rs`, `workflow/job_queue.rs` |
| Rust engine servicer (per-engine gRPC proto served over the ZMQ adapter on the engine node) | `crates/engine_servicer/src/`; lane `e2e-1gpu-chat-rust-servicer` |
| Response templates (HF `chat_parsing` port) | `crates/response_template/src/` |
| Generic prefix-membership index | `crates/radix_tree/src/` (every implementation must equal `tests/differential.rs`) |
| RL control plane (`--enable-rl`) | `crates/rl/src/` (`discovery.rs`, `proxy.rs`, `fanout.rs`, `selector.rs`) |
| Cost-function worker selection inside cache-aware routing | `model_gateway/src/policies/cost/` (`catalog.rs` registers filters, scorers and pickers by name; `selection_policy` knob) |
| Cache namespaces (engine prefix-cache partitions) | `model_gateway/src/policies/cache_namespace.rs` |
| Server posture, TLS, connection limits | `model_gateway/src/server/` |
| E2E test, pytest harness, CI lane | `e2e_test/` (markers in `fixtures/hooks.py`, backends `fixtures/setup_backend.py`, launchers `infra/worker.py`); CPU gate `PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra e2e_test/fixtures` |
| Client SDK generation | `clients/openapi-gen/` (`make generate-clients`; Go SDK is hand-maintained) |

## Process

```
1. DETECT   match the request to the detection table
2. LOAD     read the recipe file(s); note its front matter (below)
3. PLAN     one task per recipe step
4. EXECUTE  per step: follow the file path and code shape → run the verification command →
            confirm the expected output → fix before moving on
5. LEARN    a recipe step cited a path or symbol that does not exist, a verification command
            failed for a reason the recipe did not predict, or a step was missing?
            → run smg:learn now (or fix the recipe directly if you are in the smg-dev-guide repo).
            Do not route around it silently; the next agent gets the same wrong step.
6. CHAIN    all steps done → smg:contribute (the pre-PR gate), then self-review with smg:review-pr
```

## Reading a recipe's front matter

Every recipe starts with:

```yaml
recipe: config-plumbing     # file stem
verified: <smg commit sha>  # the SMG commit its paths and symbols were last checked against
level: anchors              # full = steps re-walked against the code; anchors = every cited
                            # path/symbol confirmed to exist, step semantics not re-walked
watch:                      # SMG paths whose churn means this recipe needs re-verification
  - model_gateway/src/config/
```

Treat `level: anchors` as "the names are right, confirm the shape": run the recipe's `cargo check` step early. When your SMG checkout is far past `verified`, `bash "${CLAUDE_PLUGIN_ROOT}/scripts/upstream_digest.sh"` shows how many commits touched each recipe's `watch` paths since.

## Rationalization prevention

| Excuse | Reality |
|---|---|
| "I know this subsystem, I don't need the recipe" | The recipe exists because people who know the subsystem still miss the two-path config rule, the alphabetical `RouterArgs` order in `router_args.py`, and the `create_by_name` factory arm. |
| "This is a trivial change" | Check the escape hatch. Config, protocols, bindings, Symphony registry or ZMQ wire structs are never trivial. |
| "I'll read the recipe after I write the code" | That is not following the recipe. Load first. |
| "The recipe is wrong, so I'll wing it" | Fix or record it (`smg:learn`), then follow the corrected step. Winging it is how the two-path bug ships. |

## Red flags — stop

- Writing implementation code before loading a recipe
- Skipping a recipe's verification command
- Not checking whether `config-plumbing.md` and `bindings-update.md` co-apply
- Adding a legacy tool/reasoning parser for a model Symphony's registry already reads
- Marking the implementation complete without chaining to `smg:contribute`

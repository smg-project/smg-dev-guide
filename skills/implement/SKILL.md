---
name: implement
description: Use when implementing a feature, adding functionality, fixing a bug, or modifying behavior in the SMG repository — routes to subsystem-specific recipes and enforces step-by-step execution
---

# SMG Implementation Workflow

## The Iron Law

```
NO IMPLEMENTATION WITHOUT FOLLOWING THE SUBSYSTEM-SPECIFIC RECIPE
```

Identify what you're building. Load the recipe. Follow the steps. Verify at each step.

## The Hard Gate

<HARD-GATE>
Do NOT write implementation code until you have:
1. Identified the implementation type from the detection table below
2. Loaded the matching recipe file(s)
3. Created a task for each step in the recipe
</HARD-GATE>

**Escape hatch:** Single-file changes under 20 lines that don't touch `config/types.rs`, `crates/protocols/`, `main.rs` (CliArgs or conversion functions), `bindings/`, or `crates/engine_zmq_client/src/protocol/` (positional msgpack — field order is the wire contract, append only) may skip the full recipe. You MUST still chain to `smg:contribute` before PR.

## Detection Table

| Signal in User Request | Recipe to Load |
|------------------------|----------------|
| CLI flag, config field, YAML config, RouterConfig | @config-plumbing.md |
| Routing policy, load balancing, worker selection | @routing-policy.md |
| Tool call, function call, parser format | @tool-parser.md |
| Reasoning, thinking, chain-of-thought parser | @reasoning-parser.md |
| Python binding, Go SDK, FFI, PyO3, maturin | @bindings-update.md |
| K8s, service discovery, pod, worker lifecycle, label | @discovery-feature.md |
| gRPC, backend client, tonic, streaming (an `ipc://` worker is ZMQ, next row) | @grpc-backend.md |
| ZMQ, `ipc://` worker, direct backend, EngineCore, headless vLLM/TokenSpeed, handshake, msgpack wire, `zmq_engine_count`, grouped engine worker | @zmq-backend.md |
| Storage, database, PostgreSQL, Oracle, Redis, data connector | @storage-backend.md |
| WASM, WebAssembly, plugin, middleware hook | @wasm-plugin.md |
| Auth, API key, JWT, OIDC, role, permission | @auth-feature.md |
| Metrics, tracing, logging, Prometheus, OTEL | @observability-feature.md |
| Mesh, gossip, CRDT, cluster, partition, SWIM | @mesh-feature.md |
| MCP, tool execution, approval workflow | @mcp-feature.md |
| KV cache, radix tree, prefix matching, positional indexer | @kv-index-feature.md |
| Image, audio, vision, multimodal, media | @multimodal-feature.md |
| Provider-compatible API router (Anthropic /v1/messages, Gemini /v1/interactions), RoutingMode variant, new API surface | @provider-api.md |
| Priority scheduler, admission, preemption, queue, reservation, autoscaling | @scheduler-feature.md |
| Multi-tenancy, tenant, tenant policy, tenant resolution | @tenancy-feature.md |
| Rate limit, token bucket, concurrency cap, per-tenant token/request quota, reserve/settle | @rate-limit-feature.md |

### Subsystems without a dedicated recipe yet

These are real, actively-developed subsystems that don't yet have a step-by-step recipe. Read the listed code with `smg:map`, then follow the general pattern (implement → test → verify → `smg:contribute`). `config-plumbing.md` usually co-applies.

| Signal in User Request | Where it lives |
|------------------------|----------------|
| Provider API: Responses, Conversations, Realtime (for Anthropic/Gemini-style API routers see @provider-api.md) | `model_gateway/src/routers/{responses,conversations,common/realtime}/` |
| Tokenizer, chat template, prompt renderer/encoder, stop sequence, EOS | `crates/tokenizer/src/` (`encoders/`, `huggingface.rs::detect_renderer_from_config`, `stop.rs`, `eos.rs`, `registry.rs`); gateway side `model_gateway/src/workflow/tokenizer_registration.rs`, `routers/tokenize/`; `cargo test -p llm-tokenizer` |
| Workflow engine, registration step, DAG, job queue | `crates/workflow/` (the `wfaas` crate: `StepExecutor`, `StepDefinition`, `StepResult`) plus `model_gateway/src/workflow/steps/{local,shared,external}/` wired in `steps/mod.rs`, and `workflow/job_queue.rs` |
| E2E test, pytest harness, CI lane, kind discovery | `e2e_test/` — markers and filtering in `fixtures/hooks.py`, backends in `fixtures/setup_backend.py`, launchers in `infra/worker.py`; harness units `PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra e2e_test/fixtures`; `SMG_KIND_E2E=1 pytest e2e_test/kind_discovery -m kind` |
| Client SDK generation | `clients/openapi-gen/` (`make generate-clients`) |

**If multiple match:** Load all matching recipes. `config-plumbing.md` almost always co-triggers with other recipes (most features need a config field).

**If none match:** This is a novel change. Read the codebase architecture with `smg:map` first, then follow the general pattern: implement → test → verify → chain to `smg:contribute`.

All recipes were rewritten and verified against the codebase (2026-06; re-verified against HEAD 732a42bf, post-v1.9.0, 2026-08-22). They reflect current trait/type names and paths; still run each recipe's `cargo check`/`cargo test` step as you go.

## Process

```
1. DETECT:  Match user request to detection table
2. LOAD:    Read the matching recipe file(s)
3. PLAN:    Create tasks from recipe steps
4. EXECUTE: For each step:
            a) Follow the step's instructions (file path, code pattern)
            b) Run the verification command
            c) Confirm expected output
            d) If verification fails: fix before proceeding
5. CHAIN:   When all steps complete, invoke smg:contribute
```

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "I know this subsystem, I don't need the recipe" | The recipe exists because people who know the subsystem still miss the two-path config rule and bindings update. |
| "This is a trivial change" | Check the escape hatch conditions. If it touches config/protocols/bindings, it's not trivial. |
| "I'll check the recipe after I write the code" | That's not following the recipe. That's post-hoc rationalization. Load first. |

## Red Flags — STOP

- Writing implementation code before loading a recipe
- Skipping verification steps within a recipe
- Not checking whether config-plumbing.md co-applies
- Marking implementation complete without chaining to `smg:contribute`
- Assuming a change is trivial without checking the escape hatch criteria

## Skill Chaining

When implementation is complete: **invoke `smg:contribute`** to run the 6-step quality gate before PR.

Before submitting: self-review with `smg:review-pr`.

---
name: implement
description: Build or change anything in the SMG repository (a feature, a fix, a flag, a parser table, a policy, a backend, a binding). Routes the request to the step-by-step recipe for its subsystem, each step with a file, a verify command and the silent trap, and records what the recipe got wrong.
---

# SMG Implementation Workflow

**Rule:** load the recipe for the subsystem before writing implementation code. Exception: a single-file change under 20 lines that touches none of `config/types.rs`, `crates/protocols/`, `main.rs`, `bindings/`, `crates/symphony/src/formats/registry.rs` or `crates/engine_zmq_client/src/protocol/` may skip it. Both paths end in `smg:contribute`.

## Detection table

| Signal in the request | Recipe |
|---|---|
| CLI flag, config field, YAML config, `RouterConfig`, `ServerConfig` | `recipes/config-plumbing.md` |
| Routing policy, load balancing, worker selection | `recipes/routing-policy.md` |
| A model's tool-call or reasoning format, `<think>`, chat template, Symphony table, "support model X" | `recipes/symphony-format.md` |
| Legacy tool parser or reasoning parser (`--parser legacy`) | `recipes/tool-parser.md`, `recipes/reasoning-parser.md` |
| Tokenizer backend, chat-template renderer, stop/EOS decoding | `recipes/tokenizer.md` |
| Python binding, Go SDK, PyO3, maturin, launcher parity | `recipes/bindings-update.md` |
| A new HTTP API endpoint or route | `recipes/http-endpoint.md` |
| Vendor profile, request validation rule, protocol type change | `recipes/protocols-profile.md` |
| A new discovery provider (Consul, Slurm, file, …) | `recipes/discovery-provider.md` |
| Worker metadata, labels, pod annotations through the pipeline | `recipes/discovery-feature.md` |
| gRPC engine client, proto RPC, tonic | `recipes/grpc-backend.md` |
| ZMQ, `ipc://` worker, EngineCore, headless engine, handshake, msgpack wire | `recipes/zmq-backend.md` |
| Rust engine servicer, Python servicer | `recipes/engine-servicer.md` |
| Storage, PostgreSQL, Oracle, Redis, chat history | `recipes/storage-backend.md` |
| WASM plugin, middleware hook | `recipes/wasm-plugin.md` |
| Control-plane auth, JWT, OIDC, role | `recipes/auth-feature.md` |
| Metrics, tracing, logging | `recipes/observability-feature.md` |
| Mesh, gossip, CRDT, cluster | `recipes/mesh-feature.md` |
| MCP approval policy, MCP transport | `recipes/mcp-feature.md` |
| KV cache, cache-aware routing, radix tree, chain index | `recipes/kv-index-feature.md` |
| Image, audio, video, vision processor | `recipes/multimodal-feature.md` |
| Third-party provider upstream (OpenAI, Anthropic, Gemini, xAI, an OpenAI-compatible vendor) | `recipes/provider-api.md` |
| Priority scheduler, admission, preemption, service class | `recipes/scheduler-feature.md` |
| Tenant key, tenant resolution, per-tenant state | `recipes/tenancy-feature.md` |
| Rate limit, token bucket, per-tenant quota | `recipes/rate-limit-feature.md` |
| E2E test, marker, CI lane | `recipes/e2e-lane.md` |

Several match → load all. `config-plumbing.md` co-applies to almost every feature and `bindings-update.md` to every new `RouterConfig` field. Nothing matches → `smg:map` names the area (its `reference.md` lists areas without a recipe); work from the code and leave a lesson afterwards.

## Process

```
DETECT   match the request to the table; size it: python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lanes.py" <files you expect to touch>
LOAD     read the recipe; its front matter says when it was verified (level: full | anchors) and lists exemplar commits — `git show --stat <sha>` shows the full file set a real change touched
CRAFT    read skills/craft/SKILL.md once per session; its references when the change is hot-path, a flag, a metric, an endpoint, or new vocabulary
PLAN     one task per recipe step
EXECUTE  per step: file → do → run the Verify command → confirm the signal → fix before moving on
LEARN    a cited path or symbol does not exist, a Verify fails for an unpredicted reason, or a step is missing → smg:learn now; do not route around it silently
GATE     smg:contribute, then self-review with smg:review-pr
```

## Non-negotiables

Failures that compile and pass tests, so feedback will not catch them:

- A `RouterConfig` field without its builder call in `bindings/python/src/lib.rs` silently runs the Rust default in Python.
- A `PolicyConfig` variant with only the `create_from_config` arm silently falls back to the default policy for a worker `policy_hint`.
- A Symphony table without its `groups.json` line is never selected; the model keeps the legacy parsers.

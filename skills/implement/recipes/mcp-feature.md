---
recipe: mcp-feature
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/mcp/src/
  - crates/external_router/src/mcp_utils.rs
exemplars:
  # none since 2026-08-20 — the only non-test change, 98d6aea7 (inventory refresh fix), touched core/orchestrator.rs and inventory/index.rs
---

# Customize MCP approval or add a transport

`smg-mcp` (`crates/mcp/`) is the Model Context Protocol client: it discovers tools on external servers, gates calls behind an approval policy and proxies them. The crate is OpenAI-protocol-free — response-format adapters live in the `smg-external-router` crate (`crates/external_router/src/openai_bridge/`, re-exported as `model_gateway::routers::common::openai_bridge`), not here (`lib.rs` crate doc). `McpOrchestrator` (`core/orchestrator.rs`) owns the `ToolInventory` (`inventory/index.rs`), the connection pool (`core/pool.rs`) and an `Arc<ApprovalManager>` built from `McpConfig` (`core/config.rs`). Built on `rmcp` ^1.7 (`Cargo.toml`; the committed `Cargo.lock` resolves 1.8.0), which dropped the standalone SSE client transport.

Not this recipe:
- Builtin tools: `BuiltinToolType` (`core/config.rs`: `WebSearchPreview | CodeInterpreter | FileSearch | ImageGeneration`, the `image_generation` builtin). A server with a `builtin_type` is filtered out of the visible tool list and routed as a builtin (`core/session.rs`, `is_builtin_tool`, `mcp_servers`); a new variant extends `BuiltinToolType::all()`, whose `_exhaustive` closure makes the compiler flag every site.
- The inventory refresh (`spawn_refresh_handler`, `load_server_inventory`; 98d6aea7 keeps a server's tools when its listing fails and clears each kind only after its own listing succeeded — `clear_server_tool_entries`, `clear_server_prompts`, `clear_server_resources`).

## Inputs

| Input | Example | Used in |
|---|---|---|
| Server or tool to govern | `"dangerous_server:delete_all"` | A1 |
| Rule shape | regex on the tool name + an annotation condition | A2 |
| New transport protocol | `protocol: websocket` | B1–B5 |

## Steps

Task A — customize the approval policy. `PolicyEngine` (`approval/policy.rs`) decides per call; `evaluate()` checks, in order: 1. the explicit tool policy (`tool_policies`, keyed `QualifiedToolName`); 2. the server policy with its `TrustLevel` (`evaluate_with_trust`) — short-circuits only when the server is `Trusted` or the result is not `Allow`; an `Allow` from a non-`Trusted` server falls through; 3. pattern `rules` (`Vec<PolicyRule>`, insertion order); 4. the annotation default (read-only → Allow, destructive → deny, else `default_policy`). `PolicyDecision` is `Allow | Deny | DenyWithReason(Arc<str>)`; `TrustLevel` is `Trusted | Standard (default) | Untrusted | Sandboxed`.

### A1. Add a config-driven server or tool policy

File: the MCP YAML, no code — Do: `from_yaml_config` reads `default`, `servers` and `tools` (`PolicyConfig`, `core/config.rs`); mirror the `policy:` block of `test_policy_config_yaml_full`:

```yaml
policy:
  default: allow
  servers:
    untrusted_server: { trust_level: untrusted, default: deny }
  tools:
    "dangerous_server:delete_all": deny
    "risky_server:format_disk": { deny_with_reason: "too dangerous" }
```

The config enums are the `*Config` mirrors (`TrustLevelConfig`, `PolicyDecisionConfig`) with `From` impls in `policy.rs`.
Verify: `cargo test -p smg-mcp test_policy_config_yaml_full`
Trap: a tool key that is not `server:tool` is logged and skipped by `from_yaml_config`'s `else` branch — the policy silently never applies.

### A2. Add a pattern rule (code only)

File: `crates/mcp/src/approval/policy.rs` — Do: `PolicyRule::new(name, pattern, condition, decision)` with `RulePattern` = `Server(Regex) | Tool(Regex) | Qualified(Regex) | Any` and `RuleCondition` = `Always | HasAnnotation(AnnotationType) | LacksAnnotation(AnnotationType)` (`AnnotationType` = `Destructive | ReadOnly | Idempotent | OpenWorld`, `annotations.rs`). Add it through the builder `with_rule`, as `test_pattern_rule` and `impl Default for PolicyEngine` (the `allow_read_only` rule) do:

```rust
let engine = PolicyEngine::new(audit_log).with_rule(PolicyRule::new(
    "block_delete", RulePattern::Tool(Regex::new("^delete_").unwrap()),
    RuleCondition::Always, PolicyDecision::Deny,
));
```

To reach it from config, extend `PolicyConfig` and `from_yaml_config` (see @config-plumbing.md); today it is wired only through the constructor.
Verify: `cargo test -p smg-mcp policy`
Trap: `PolicyRule` holds a `Regex` and has no serde derive, so `from_yaml_config` never populates `rules` — a rule can only come from code.

Task B — add a transport. `McpTransport` (`core/config.rs`) is `#[serde(tag = "protocol", rename_all = "lowercase")]`: `Stdio { command, args, envs } | Sse { url, token, headers } | Streamable { url, token, headers }`. Adding one means adding a variant, then patching every exhaustive `match` the compiler lists.

### B1. Add the variant

File: `crates/mcp/src/core/config.rs` — Do: add the variant with its serde fields and extend `impl fmt::Debug for McpTransport` so secrets stay redacted.
Verify: `cargo test -p smg-mcp test_transport_` (`test_transport_stdio` / `test_transport_sse` / `test_transport_streamable` show the parsing shape).

### B2. Connect static servers

File: `crates/mcp/src/core/orchestrator.rs`, `connect_server_impl` — Do: build the rmcp transport and call `handler.serve(transport)`. Model on the `Streamable` arm: proxy via `super::proxy::resolve_proxy_config`, client via `build_http_client`, transport from `rmcp::transport::*` (`StreamableHttpClientTransport::with_client`). The `Sse` arm is not a template — it returns `Err(sse_unsupported(..))`.
Verify: `cargo test -p smg-mcp orchestrator` → the connect tests pass for the new arm

### B3. Connect dynamic servers

File: `core/orchestrator.rs`, `connect_dynamic_server_with_tenant` — Do: the request-supplied path; `Stdio` is rejected here ("Stdio not supported for dynamic connections").
Verify: `cargo test -p smg-mcp dynamic` → the dynamic-connection tests cover the new transport

### B4. Derive the pool key

File: `core/orchestrator.rs` `server_key` and `core/pool.rs` `PoolKey::from_config` — Do: url + `hash_auth(token, headers)` for HTTP transports.
Verify: `cargo test -p smg-mcp pool` → two configs differing only in auth get distinct keys

### B5. Route the gateway's construction site

File: `crates/external_router/src/mcp_utils.rs`, `connect_mcp_servers` (re-exported as `model_gateway::routers::common::mcp_utils`) — Do: the gateway builds an `McpTransport` from a request's `server_url` here (`/sse` → `Sse`, else `Streamable`); add your scheme.
Verify: `cargo test -p smg-mcp`
Trap: this is a construction, not a `match`, so the compiler never flags it and a new protocol stays unreachable from requests.

### Gate

Run `smg:contribute`.

## Rules

- SMG does not implement the `rmcp::Transport` trait: it matches `McpTransport` and hands an rmcp-provided transport (`StreamableHttpClientTransport`, `TokioChildProcess`) to `handler.serve()`.
- `ToolAnnotations { read_only, destructive, idempotent, open_world }` come from rmcp with conservative defaults (`from_rmcp`: destructive = true, open_world = true); `should_require_approval()` = `destructive && !read_only`.
- Tests sharing process env (proxy vars) use `#[serial]` from `use serial_test::serial;` (`test_proxy_from_env_*`, `core/config.rs`), not `#[serial_test]`; policy tests build `PolicyEngine::new(Arc::new(AuditLog::new()))` (`test_engine`).
- Layout: `annotations.rs` (`ToolAnnotations`, `AnnotationType`), `error.rs` (`McpError`, `McpResult`, `ApprovalError`), `tenant.rs` (`TenantContext`, `TenantId`, `SessionId`), `core/{orchestrator,session,config,pool,handler,proxy,reconnect,metrics}.rs`, `approval/{manager,policy,audit}.rs`, `inventory/{index,types}.rs`.

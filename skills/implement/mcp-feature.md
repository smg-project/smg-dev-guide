# Adding MCP Features to SMG

`smg-mcp` (`crates/mcp/`) is the Model Context Protocol client: it discovers tools on external servers, gates execution behind an approval policy, and proxies calls. The crate is **OpenAI-protocol-free** — response-format adapter logic lives in `model_gateway::routers::common::openai_bridge`, not here (`lib.rs` crate doc). Built on `rmcp` ^1.7 (`Cargo.toml`, `[dependencies] rmcp`; the committed `Cargo.lock` resolves 1.8.0). Note: rmcp 1.7 **dropped the standalone SSE client transport** — the `Sse` variant now returns an error (see Task B).

Central type: `McpOrchestrator` (`core/orchestrator.rs`) owns the inventory, connection pool, and an `Arc<ApprovalManager>` built from `McpConfig` (`core/config.rs`).

```
crates/mcp/src/
  annotations.rs     → ToolAnnotations, AnnotationType
  error.rs           → McpError, McpResult, ApprovalError
  tenant.rs          → TenantContext, TenantId, SessionId
  core/  orchestrator.rs (central) · session.rs · config.rs · pool.rs
         handler.rs · proxy.rs · reconnect.rs · metrics.rs
  approval/  manager.rs · policy.rs · audit.rs
  inventory/ index.rs · types.rs
```

The two realistic tasks are **customizing the approval policy** and **adding a transport**. Pick the matching section.

---

## Task A: Customize the approval policy

`PolicyEngine` (`approval/policy.rs`, `struct PolicyEngine`) decides per call. `evaluate()` checks, in order:
1. Explicit tool policy (`tool_policies`, keyed `QualifiedToolName`)
2. Server policy + `TrustLevel` (`evaluate_with_trust`) — short-circuits only when the server is `Trusted` or the result is not `Allow`; an `Allow` from a non-`Trusted` server falls through to steps 3-4
3. Pattern `rules` (`Vec<PolicyRule>`, evaluated in insertion order)
4. Annotation default (read_only→Allow, destructive→deny, else `default_policy`)

`PolicyDecision` (`enum PolicyDecision`) is `Allow | Deny | DenyWithReason(Arc<str>)`. `TrustLevel` (`enum TrustLevel`) is `Trusted | Standard (default) | Untrusted | Sandboxed`.

### Add a config-driven server/tool policy

Edit YAML — no code. `from_yaml_config` (`policy.rs`) reads `default`, `servers`, and `tools` into the engine. Mirror the `policy:` block in `config.rs` tests (`core/config.rs`, `test_policy_config_yaml_full`):

```yaml
policy:
  default: allow
  servers:
    untrusted_server: { trust_level: untrusted, default: deny }
  tools:
    "dangerous_server:delete_all": deny
    "risky_server:format_disk": { deny_with_reason: "too dangerous" }
```

Config enums are the `*Config` mirrors (`TrustLevelConfig`, `PolicyDecisionConfig` in `config.rs`) with `From` impls in `policy.rs` (`impl From<PolicyDecisionConfig>`, `impl From<TrustLevelConfig>`). Tool keys MUST be `"server:tool"` — a bad key is logged and skipped (`policy.rs`, `from_yaml_config`'s `else` branch).

**Anti-pattern:** expecting pattern `rules` from YAML. `PolicyRule` holds a `Regex` and has **no** serde derive; `from_yaml_config` never populates `rules`. Pattern rules are code-only (below).

### Add a pattern rule (regex / annotation-conditioned)

`PolicyRule { name, pattern: RulePattern, condition: RuleCondition, decision: PolicyDecision }` (`policy.rs`, `struct PolicyRule`). `RulePattern` (`enum RulePattern`) = `Server(Regex) | Tool(Regex) | Qualified(Regex) | Any`; `RuleCondition` (`enum RuleCondition`) = `Always | HasAnnotation(AnnotationType) | LacksAnnotation(AnnotationType)`. Add via the builder `with_rule`, modeled on the `test_pattern_rule` test and the `Default` impl (`impl Default for PolicyEngine`):

```rust
use smg_mcp::approval::{PolicyDecision, PolicyEngine, PolicyRule, RuleCondition, RulePattern};
use regex::Regex;

let engine = PolicyEngine::new(audit_log)
    .with_rule(PolicyRule::new(
        "block_delete",
        RulePattern::Tool(Regex::new("^delete_").unwrap()),
        RuleCondition::Always,
        PolicyDecision::Deny,
    ));
```

To make this reachable from config you'd extend `from_yaml_config` and `PolicyConfig` (see @config-plumbing.md) — currently it is wired only through the constructor.

`AnnotationType` (`annotations.rs`, `enum AnnotationType`) = `Destructive | ReadOnly | Idempotent | OpenWorld`. `ToolAnnotations { read_only, destructive, idempotent, open_world }` (`struct ToolAnnotations`) come from rmcp with conservative defaults (destructive=true, open_world=true; `from_rmcp`). `should_require_approval()` = `destructive && !read_only`.

**Verify:** `cargo test -p smg-mcp policy`

---

## Task B: Add a transport

Transports are the enum `McpTransport` (`core/config.rs`, `enum McpTransport`), tagged by `protocol` in YAML — `Stdio | Sse | Streamable`. Adding one = **add a variant, then patch every exhaustive `match` on it** (the compiler lists them):

1. `core/config.rs` `enum McpTransport` — add the variant (with `#[serde]` fields).
2. `core/orchestrator.rs` `connect_server_impl` — build the rmcp transport and call `handler.serve(transport)`. Model on the **`Streamable` arm** (the working reference): proxy via `super::proxy::resolve_proxy_config`, client via `build_http_client`, transport from `rmcp::transport::*` (`StreamableHttpClientTransport::with_client`). The `Sse` arm is **not** a template — it now returns `Err(sse_unsupported(..))` since rmcp 1.7 dropped the SSE client transport.
3. `core/orchestrator.rs` `connect_dynamic_server_with_tenant` — dynamic path (Stdio is rejected here, "Stdio not supported for dynamic connections").
4. `core/orchestrator.rs` `server_key` and `core/pool.rs` `PoolKey::from_config` — derive the pool key (url + `hash_auth(token, headers)`).
5. (Dynamic/request-supplied servers only) `model_gateway/src/routers/common/mcp_utils.rs` `connect_mcp_servers` — the gateway builds an `McpTransport` from the request's `server_url` here (`/sse` → `Sse`, else `Streamable`). This is a **construction, not a match**, so the compiler will not flag it.

**Anti-pattern:** implementing an `rmcp::Transport` trait. SMG does not define transports as trait impls — it matches the `McpTransport` enum and hands an rmcp-provided transport (`StreamableHttpClientTransport`, `TokioChildProcess`) to `handler.serve()`. Also update the `Debug` impl (`config.rs`, `impl fmt::Debug for McpTransport`) so secrets stay redacted.

**Verify:** `cargo test -p smg-mcp` (transport parsing tests `test_transport_stdio` / `_sse` / `_streamable` live in `config.rs`).

---

## Builtin-tool classification

`BuiltinToolType` (`core/config.rs`, `enum BuiltinToolType`) has 4 variants — `WebSearchPreview`, `CodeInterpreter`, `FileSearch`, `ImageGeneration` (the `image_generation` builtin). A server configured with a `builtin_type` is filtered out of the visible tool list and routed as a builtin instead of a normal MCP tool (`core/session.rs`, `is_builtin_tool` / `mcp_servers` filtering). Adding a builtin variant means extending `BuiltinToolType::all()`'s exhaustive match (`core/config.rs`, `all()`) — the inner `_exhaustive` closure forces the compiler to flag every site when a variant is added.

---

## Testing

Tests sharing process env (proxy vars) use `#[serial]` from `use serial_test::serial;` (`config.rs`, `test_proxy_from_env_*`) — **not** `#[serial_test]`. Approval/policy tests construct `PolicyEngine::new(Arc::new(AuditLog::new()))` (`policy.rs`, `test_engine` helper).

**Verify:** `cargo test -p smg-mcp`, then invoke `smg:contribute` for fmt → clippy → test → commit.

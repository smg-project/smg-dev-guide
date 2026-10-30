# Checklist: layering and separation of concerns

- [ ] No new field in `crates/protocols/` that only one crate sets; K8s-, runtime- or gateway-specific data stays in `model_gateway`.
- [ ] Config types at the right layer: user-facing → `config/types.rs`, runtime → the owning module.
- [ ] Strings parsed at the boundary, typed at runtime.
- [ ] Provider, WASM and MCP concerns stay in their crates (`crates/external_router`, `crates/wasm`, `crates/mcp`) and are re-exported, not re-implemented in the gateway.
- [ ] `serde(rename)` names match the OpenAI / Anthropic / Gemini spec field names; `#[serde(flatten)]` keeps unknown vendor fields.
- [ ] A new middleware or admission path is `Send + Sync` and installed in the right order (`server.rs` layers are applied bottom-up).

| Anti-pattern | Consequence | Look for |
|---|---|---|
| K8s-specific data in `crates/protocols/` | couples every deployment to K8s | namespaces, pods, selectors in protocol types |
| Glue copied into the gateway instead of re-exported | two implementations drift | SSE, retry or MCP helpers under `model_gateway/src/routers/common/` that duplicate `crates/external_router/src/` |
| A wildcard arm over a closed enum (`ZmqDialect`, `BackendClient`, `ProviderType`) | a new variant silently takes the wrong path | `_ =>` in a `match` on one of them |

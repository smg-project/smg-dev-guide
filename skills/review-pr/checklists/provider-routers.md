# Checklist: third-party provider routers (`crates/external_router`)

- [ ] An OpenAI-compatible vendor is a `Provider` impl under `openai/provider/` registered in `ProviderRegistry`, not a new router family.
- [ ] A new family: `ExternalRouterSpec` in `router.rs` (`all()` grows), Cargo feature in both crates, `RoutingMode` + `Backend` variants, `serves` covers its `ProviderType`; builds without the feature return `not_compiled()`.
- [ ] Shared glue reused (`sse.rs`, `retry.rs`, `mcp_utils.rs`, `openai_bridge/`, `header_utils.rs`, `upstream_body.rs`); no hand-rolled SSE framing or unbounded channel.
- [ ] Vendor request rules belong in `crates/protocols/src/profile/`, not in the router.

| Anti-pattern | Consequence | Look for |
|---|---|---|
| Provider code outside its Cargo feature | the `self-hosted` and `anthropic-only` lint legs break | missing `#[cfg(feature = ...)]` |
| `_ =>` over `ProviderType` | `provider_support.rs` admits a worker no router takes | wildcard arms |

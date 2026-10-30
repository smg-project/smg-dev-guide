---
recipe: tenancy-feature
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - model_gateway/src/tenant/
  - model_gateway/src/middleware/tenant_resolution.rs
  - model_gateway/src/middleware/auth.rs
  - crates/external_router/src/tenant.rs
  - crates/data_connector/src/core.rs
exemplars:
  - b39f784e   # fix: stored responses and conversations are scoped to the tenant that created them
---

# Add a tenant-aware feature

Every serving request carries a `RouteRequestMeta` (alias `TenantRequestMeta`, `middleware/mod.rs`) whose `TenantKey` (`Arc<str>` newtype) is the `Display` of a `TenantIdentity` (`model_gateway/src/tenant/mod.rs`): `auth:<id>`, `header:<id>`, `ip:<addr>`, `anonymous`, or an `Explicit(key)` passed through verbatim for admin targets. `TenantKey`, `RouteRequestMeta` and `storage_tenant` are defined in `crates/external_router/src/tenant.rs` and re-exported by `tenant/mod.rs`. `auth_middleware` (`middleware/auth.rs`) runs first and inserts `DataPlaneCaller`; `middleware/tenant_resolution.rs` then resolves the key. Features read the resolved key — never a header.

Not this recipe:
- Per-tenant API keys: `TenantApiKeyEntry { tenant_id, key }` in `RouterConfig.tenant_api_keys` (`config/types.rs`; CLI `--tenant-api-key <id>:<key>`, repeatable, or `--tenant-api-keys-file`, `main.rs::parse_tenant_api_key`; builder `.tenant_api_keys(..)`) already resolves to `auth:<tenant_id>` through `AuthConfig::with_tenant_keys`, validated by `config/validation.rs::validate_tenant_api_keys`; `server.rs` passes it as `serving_auth_config` and a shared-key-only `admin_auth_config` to `build_app`, so tenant keys never reach admin or worker routes.
- Tenant rate-limit policy (`rate-limit-feature`) and the scheduler's `max_class` clamp (`scheduler-feature`).

## Inputs

| Input | Example | Used in |
|---|---|---|
| Where the feature runs | middleware / handler / `RouterTrait` method | A1 |
| Per-tenant state | `HashMap<TenantKey, Quota>` with a default | A2 |
| Stored records touched | responses, conversations, conversation items | A3 |
| New identity source | mTLS → `mtls:<id>` | B1–B3 |

## Steps

Task A — consume the tenant key.

### A1. Read the key where you already hold the request

File: your middleware, handler or `RouterTrait` method — Do: in a middleware, `req.extensions().get::<RouteRequestMeta>().map(|m| m.tenant_key().clone())` with an `unwrap_or_else(|| TenantKey::new("anonymous"))` fallback (`priority_admission_middleware`, `middleware/scheduler/admission.rs`); in a handler, `Extension(tenant_meta): Extension<middleware::TenantRequestMeta>` and forward `&tenant_meta` (`server.rs`, `generate`; typed bodies are passed by value so clone `body.model` first — `route_audio_transcriptions` and the realtime methods still take `&body`); in a `RouterTrait` method you already receive `tenant_meta: &TenantRequestMeta`: read `tenant_meta.tenant_key().as_str()`, or forward it as `routers/gateway.rs` does (`route_generate`).
Verify: `cargo check -p smg`
Trap: reading `x-smg-tenant-id` (`DEFAULT_TENANT_HEADER_NAME`) yourself bypasses auth precedence and the `trust_tenant_header` gate; the resolved key may differ from the header.

### A2. Key state on `TenantKey`; attach derived data as an extension

File: your module — Do: `TenantKey` is `Hash + Eq + Clone`: use `HashMap<TenantKey, T>` with a default for unknown keys, built once at startup and looked up through a sync trait, as `StaticTenantPolicyResolver` does (`middleware/scheduler/policy.rs`, `unwrap_or(self.default)`). Derived per-request data goes on the meta with `RouteRequestMeta::with_extension` / `insert_extension` and comes back with `.extension::<T>()`; `RequestId` (attached by `resolve_route_request_meta` when `RequestIdLayer` set one, read by `routers/grpc/common/stages/helpers.rs::middleware_request_id`) and `AcceptedAt` are the in-tree examples. The only public fields are `tenant_key` and `request_charge_id` (`Uuid::now_v7()` in `new()`, read via `request_charge_id()`); `PartialEq` compares those two and ignores `extensions`.
Verify: `cargo test -p smg --lib tenant_resolution` → `request_meta_carries_middleware_request_id`.
Trap: consumers must tolerate every key, `anonymous` included — admin paths build the meta from an explicit id (`resolve_admin_target_tenant_id` → `TenantIdentity::Explicit`) and never pass through `resolve_raw_tenant_key`.

### A3. Scope stored state to the tenant

File: `crates/external_router/src/tenant.rs` (`storage_tenant`), `crates/data_connector/src/core.rs`, `crates/external_router/src/persistence_utils.rs`, `model_gateway/src/endpoints/conversations/handlers.rs` — Do: `storage_tenant(&meta) -> Option<String>` yields the key only for a vouched identity (`auth:` / `header:`); IP and anonymous give `None`. Pass it as the `tenant: Option<&str>` of every storage call: `NewConversation`, `ConversationItem` and `StoredResponse` carry `tenant: Option<String>`, and every read goes through `is_visible_to(tenant)` / `tenant_scope_allows(record, caller)` so another tenant's id answers like an unknown one (`ensure_conversation_exists` in `conversations/handlers.rs`, `visible_response` in `endpoints/responses/handlers.rs`, `create_and_link_item` / `persist_conversation_items` in `persistence_utils.rs`, the `storage_tenant` callers under `routers/grpc/`). A new column reaches every backend (`memory.rs`, `postgres.rs`, `oracle.rs`, `redis.rs`) and its migrations (`postgres_migrations.rs`, `oracle_migrations.rs`, `scripts/oracle_flyway/sql/`).
Verify: `cargo test -p smg --test responses_tests history_tenant_scope` → `another_tenant_cannot_read_continue_write_into_or_delete_stored_state` and `without_tenant_identity_stored_state_is_shared_as_before` (`model_gateway/tests/responses/history_tenant_scope_test.rs`); `cargo test -p data-connector tenant`.
Trap: a record stored with no tenant is served to everyone (`tenant_scope_allows`), and deriving the tenant from `tenant_key()` instead of `storage_tenant` scopes records to an IP — `storage_tenant_is_the_canonical_key_of_a_vouched_identity_only` pins the rule.

Task B — add a `TenantIdentity` source. Only for a genuinely new principal type: two coordinated edits plus config.

### B1. Add the variant and its disjoint prefix

File: `model_gateway/src/tenant/mod.rs` — Do: add a `TenantIdentity` variant and an `into_key` arm with a new prefix (`Mtls(id) => format!("mtls:{id}")`); `canonical_tenant_key(identity)` is just `identity.into_key()`. Teach `is_canonical_serving_tenant_key` the prefix and extend `canonical_forms_accepted` / `non_canonical_forms_rejected`.
Verify: `cargo test -p smg --lib tenant::`
Trap: skipping `is_canonical_serving_tenant_key` compiles, but `rate_limit/config.rs::RateLimitYaml::validate` then rejects the new keys as `RateLimitConfigError::NonCanonicalTenantKey`, so no tenant rate-limit policy can target them; a duplicate prefix silently merges tenants.

### B2. Emit it during resolution

File: `model_gateway/src/middleware/tenant_resolution.rs` — Do: add a branch to `resolve_raw_tenant_key(state, request) -> Result<TenantKey, Response>` at the right priority — it returns on the first match: `DataPlaneCaller` (auth) > trusted header (behind `state.trust_tenant_header`; longer than `MAX_TENANT_ID_LEN` = 200 → 400 `invalid_tenant_header`) > `ConnectInfo<SocketAddr>` → `ip:` > `anonymous`. Construct with `canonical_tenant_key(TenantIdentity::Mtls(..))`. Header-sourced identities stay behind the trust gate (a client can spoof a header); auth-derived ones belong in `auth_middleware`, which matches the token hash in `AuthConfig.keys` and inserts `DataPlaneCaller::new(TenantKey)` (`auth:<tenant_id>` for a tenant key, `auth:<sha256-hex>` for the shared key via `authenticated_tenant_key_from_sha256`). The layer is `TenantResolutionState::layer()` (`RouteRequestMetaLayer`), stacked in `server.rs::build_apps` right after the serving auth layer in one `tower::ServiceBuilder`, so auth runs first; `route_request_meta_middleware` and `ordinary_tenant_resolution_middleware` are the same code for `from_fn_with_state` users — never apply two.
Verify: `cargo test -p smg --lib tenant_resolution` → drive the layer with `from_fn_with_state` + `oneshot` and assert the `auth:` / `header:` / `ip:` / `anonymous` key (`request_meta_prefers_authenticated_data_plane_identity`, `request_meta_falls_back_to_client_ip`).
Trap: a branch placed after the IP fallback is unreachable for any client with a socket address, and every existing test still passes.

### B3. Config for a gated or named source

File: `model_gateway/src/config/types.rs` — Do: add a `#[serde(default)]` field to `TenantResolutionConfig { trust_tenant_header, tenant_header_name }` (flags `--trust-tenant-header`, `--tenant-header-name` in `main.rs`), plumb it per @config-plumbing.md, read it in `TenantResolutionState::from_config` and validate in `config/validation.rs::validate_tenant_resolution`.
Verify: `cargo test -p smg config::validation tenant`

### Gate

Run `smg:contribute`.

## Rules

- Precedence in `resolve_raw_tenant_key` is fixed: auth > trusted header > client IP > anonymous. Adding a source means choosing its place, not appending.
- Resolution can refuse: `resolve_route_request_meta` returns `Err(Response)` for an unusable trusted header (`an_over_long_trusted_tenant_header_is_refused`); every other request gets a key, `anonymous` at worst.
- A new `TenantIdentity` variant without an `into_key` arm fails to compile (non-exhaustive match).
- The in-tree test helper for a meta is `routers/gateway.rs::test_tenant_meta` (`RouteRequestMeta::new(TenantKey::from("auth:acme"))`).
- Tenant knobs are launcher flags too: `--tenant-api-key` and the tenant-resolution settings reach `bindings/python/src/lib.rs` and `bindings/python/src/smg/router_args.py` (@bindings-update.md); storage-side tenant scoping is pinned across backends by `crates/data_connector/tests/conformance.rs`.

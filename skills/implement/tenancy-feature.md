# Adding a Tenant-Aware Feature to SMG

Every serving request carries a canonical `TenantKey` (`Arc<str>` newtype, `model_gateway/src/tenant.rs`). To make a feature per-tenant you **read** the key that resolution already computed — never re-derive it from headers in your handler. To add a new identity source you extend the resolution flow, not consumers.

A `TenantKey` is the `Display` of a `TenantIdentity` variant with a prefix: `auth:<id>`, `header:<id>`, `ip:<addr>`, or `anonymous` (`TenantIdentity::into_key`, tenant.rs). `Explicit(key)` is passed through verbatim (admin target path).

## Resolution pipeline

```
auth_middleware (auth.rs)
    ↓ hashes the Bearer token, looks it up in AuthConfig.keys (AuthConfig::with_tenant_keys:
    ↓   shared --api-key → auth:<sha256hex>, each tenant_api_keys entry → auth:<tenant_id>)
    ↓ inserts DataPlaneCaller::new(tenant_key) into request extensions
route_request_meta_middleware (tenant_resolution.rs)
    ↓ resolve_route_request_meta = RouteRequestMeta::new(resolve_raw_tenant_key(...)),
    ↓   plus .with_extension(RequestId) when RequestIdLayer already set one
    ↓ resolve_raw_tenant_key, in priority order (tenant_resolution.rs::resolve_raw_tenant_key):
    ↓   1. DataPlaneCaller extension → its TenantKey (auth wins)
    ↓   2. trusted header (only if config.trust_tenant_header) → header:<id>
    ↓   3. ConnectInfo<SocketAddr> → ip:<addr>
    ↓   4. else → anonymous
    ↓ inserts RouteRequestMeta into extensions (infallible)
handler: Extension<TenantRequestMeta> → passes &TenantRequestMeta into RouterTrait methods
```

Layers in `server.rs` (`build_app`) apply **bottom-up**: `auth_middleware` is added after `route_request_meta_middleware`, so auth runs **first** and its `DataPlaneCaller` is present when resolution runs. `TenantRequestMeta` is a type alias for `RouteRequestMeta` (`middleware/mod.rs`).

`route_request_meta_middleware` and `ordinary_tenant_resolution_middleware` are the **same code** — the latter is a thin async wrapper kept for backward-compatible naming (`tenant_resolution.rs::ordinary_tenant_resolution_middleware`). Use `route_request_meta_middleware`.

## Task A: consume the tenant key in a feature

### Step 1: Read the key where you already have the request

In a **middleware**, pull it from extensions (model on `priority_admission_middleware`, `middleware/scheduler/admission.rs`):
```rust
use crate::middleware::RouteRequestMeta;
use crate::tenant::TenantKey;

let tenant = req
    .extensions()
    .get::<RouteRequestMeta>()
    .map(|m| m.tenant_key().clone())
    .unwrap_or_else(|| TenantKey::new("anonymous"));
```
In a **handler**, take it as an extractor (`server.rs`, the `generate` handler) and forward it. Typed-JSON bodies are passed **by value** so the router can free them after upstream dispatch, so clone the model id out first (`route_audio_transcriptions` and the realtime methods still take `&body`):
```rust
Extension(tenant_meta): Extension<middleware::TenantRequestMeta>,
// ...
let model = body.model.clone();
state.router.route_generate(Some(&headers), &tenant_meta, body, &model)
```
In a **RouterTrait method**, you already receive `tenant_meta: &TenantRequestMeta`; read `tenant_meta.tenant_key().as_str()` (`router_manager.rs` route methods, e.g. `route_generate`, forward it to the underlying router).

**Anti-pattern:** reading `x-smg-tenant-id` (or any auth header) directly in your handler. That bypasses the auth precedence and the `trust_tenant_header` gate; the resolved key may differ from the raw header.

### Step 2: Key your per-tenant state on `TenantKey`

`TenantKey` is `Hash + Eq + Clone`, so use it directly as a map key. Model on `StaticTenantPolicyResolver` (`middleware/scheduler/policy.rs`): a `HashMap<TenantKey, T>` with a default fallback for unknown keys, built once at startup from config and looked up synchronously via a `Resolver` trait.

```rust
fn limit_for(&self, tenant: &TenantKey) -> Quota {
    self.per_tenant.get(tenant).copied().unwrap_or(self.default)
}
```

If you need to attach **derived per-request data** (not just read the key), append it to the meta with `RouteRequestMeta::with_extension` and read it back with `.extension::<T>()` (tenant.rs). `RequestId` is the in-tree example: `resolve_route_request_meta` attaches it and `routers/grpc/common/stages/helpers.rs::middleware_request_id` reads it back to derive backend request ids. Prefer this typemap over new public fields: `RouteRequestMeta` already exposes two public fields — `tenant_key: TenantKey` and `request_charge_id: Uuid` (set via `Uuid::now_v7()` in `new()`, read via `request_charge_id()`) — and you should not add more.

**Verify:** `cargo check -p smg`

### Step 3: Tests

Build a `RouteRequestMeta::new(TenantKey::from("auth:acme"))` (`router_manager.rs::test_tenant_meta` shows the test helper) and assert your feature reads the right key. For middleware, drive it with `from_fn_with_state` + `oneshot` and assert on the `auth:` / `header:` / `ip:` / `anonymous` key (`tenant_resolution.rs` tests module).

**Verify:** `cargo test -p smg`

## Task B: add a new `TenantIdentity` source

Only when a new principal type must produce keys. **Not** for per-tenant API keys — those already resolve to `auth:<tenant_id>` with no new variant: `TenantApiKeyEntry { tenant_id, key }` in `RouterConfig.tenant_api_keys` (`config/types.rs`), CLI `--tenant-api-key tenant_id:key` (repeatable, `main.rs::parse_tenant_api_key`), builder `.tenant_api_keys(..)`, validated by `config/validation.rs::validate_tenant_api_keys`. `server.rs` passes `AuthConfig::with_tenant_keys(api_key, &tenant_api_keys)` to `build_app` as the `serving_auth_config` and a shared-key-only `admin_auth_config`, so tenant keys never reach admin/worker routes.

For a genuinely new source, two coordinated edits:

### Step 1: Add the variant + its key mapping

**File:** `model_gateway/src/tenant.rs` — add a variant to `TenantIdentity` and a matching arm in `into_key` with a **new unique prefix** (e.g. `mtls:`):
```rust
Mtls(Arc<str>) => format!("mtls:{id}"),
```
Keep prefixes disjoint so two sources can never collide on one key string. `canonical_tenant_key(identity)` (tenant.rs) is just `identity.into_key()`.

Then teach `is_canonical_serving_tenant_key` (tenant.rs) the new prefix and add a case to its `canonical_forms_accepted` test. `rate_limit/config.rs::RateLimitYaml::validate` rejects any per-tenant `tenant_key` that fails it (`RateLimitConfigError::NonCanonicalTenantKey`), so a prefix added only to `into_key` compiles but can never be targeted by a tenant rate-limit policy.

### Step 2: Emit it during resolution

**File:** `model_gateway/src/middleware/tenant_resolution.rs` — add a branch in `resolve_raw_tenant_key`, placed at the right **priority** (the function returns on the first match; `DataPlaneCaller` must stay first). Construct via `canonical_tenant_key(TenantIdentity::Mtls(Arc::from(value)))`.

Header-sourced identities must stay behind the `state.trust_tenant_header` gate (`resolve_raw_tenant_key`) — an untrusted client can spoof a header. Auth-derived identities belong upstream instead: `auth_middleware` (`auth.rs`) matches the token hash in `AuthConfig.keys` and inserts `DataPlaneCaller::new(TenantKey)`.

### Step 3: Config (if gated/named)

A new trusted source usually needs a `TenantResolutionConfig` field (`config/types.rs`, `#[serde(default)]`). Plumb it per @config-plumbing.md and wire it through `TenantResolutionState::from_config` (`tenant_resolution.rs`). Validation lives in `config/validation.rs::validate_tenant_resolution`.

**Verify:** `cargo test -p smg`

## Step: contribute

Invoke `smg:contribute` to run fmt -> clippy -> test -> bindings -> commit.

## Critical Rules

- Read the resolved `TenantKey`; never re-parse `x-smg-tenant-id` (`DEFAULT_TENANT_HEADER_NAME`, tenant.rs) in a handler. Header trust is gated by `trust_tenant_header` and overridden by auth (`DataPlaneCaller`).
- Precedence in `resolve_raw_tenant_key` is fixed: `DataPlaneCaller` (auth) > trusted header > client IP > anonymous. Adding a source means choosing where it sits, not appending blindly.
- Consumers must tolerate **any** key, including `anonymous` — always have a default-tenant fallback (`policy.rs` `unwrap_or(self.default)`; `admission.rs` `unwrap_or_else(|| TenantKey::new("anonymous"))`). Resolution is **infallible** — `resolve_route_request_meta` always produces a key and never errors (no alias store, no fallible step).
- `route_request_meta_middleware` == `ordinary_tenant_resolution_middleware` (alias). Don't apply both.
- New `TenantIdentity` variant ⇒ new `into_key` arm with a **disjoint prefix**, plus a branch in `is_canonical_serving_tenant_key`. Forgetting the arm fails to compile (non-exhaustive match); a duplicate prefix silently merges tenants; skipping `is_canonical_serving_tenant_key` compiles but leaves the new tenants un-targetable by tenant rate-limit policy.
- Extend per-request data via `RouteRequestMeta::with_extension`/`.extension::<T>()`, not new public fields (the existing public fields are `tenant_key` and `request_charge_id`). The struct's `PartialEq` compares `tenant_key` and `request_charge_id`; it ignores `extensions` (tenant.rs).
- Admin/control-plane paths build the meta directly from an explicit id (`resolve_admin_target_tenant_id` → `TenantIdentity::Explicit`, tenant.rs); they do not flow through `resolve_raw_tenant_key`.

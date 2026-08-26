# Adding Auth Features to SMG

Two independent auth layers — know which one you are touching.

**Serving path** (`/v1/*`) — `model_gateway/src/middleware/auth.rs`. `AuthConfig::with_tenant_keys(api_key, &tenant_api_keys)` SHA-256-hashes every key into a map; `auth_middleware` resolves the Bearer token and inserts a `DataPlaneCaller` extension carrying a `TenantKey` (`auth:<tenant_id>` for `--tenant-api-key tenant_id:key`, hash-derived for the shared `--api-key`). Config: `RouterConfig.tenant_api_keys: Vec<TenantApiKeyEntry>`, checked by `ConfigValidator::validate_tenant_api_keys` (non-empty tenant_id/key, no surrounding whitespace, no duplicate credential incl. collision with `api_key`). Tenant keys never reach the control plane (`admin_auth_config = AuthConfig::new(api_key)`; tenant-keys-only → `deny_all_middleware`), and `/v1/models` short-circuits on `AuthConfig::contains_token` so a tenant key is never forwarded as a BYOK credential.

**Control plane** (`admin_routes` + `worker_routes`) — crate `smg-auth`. Two methods, either one suffices: JWT/OIDC is tried first, then API key (`--control-plane-api-keys id:name:role:key`, SHA-256). A 3-segment token that fails JWT validation is rejected outright, not retried as an API key. Roles: `Admin` (control plane) and `User` (data plane). **The rest of this skill covers this layer.**

## Steps

### Adding a New Role

1. Extend `Role` in `crates/auth/src/config.rs` — including its `Display`, `FromStr` and `is_admin()` impls
2. Update the hard-coded `"admin" | "user"` matches that bypass `FromStr`: `parse_control_plane_api_key` and `parse_role_mapping` in `model_gateway/src/main.rs`, and `PyRole` + the `role_mapping` match in `bindings/python/src/lib.rs`. A variant added only to the enum is silently dropped there (warn + skip, or default to `User`)
3. Update `check_admin_role` in `crates/auth/src/middleware.rs`
4. Update `JwtValidator::extract_role` in `crates/auth/src/jwt.rs`

### Adding a New OIDC Provider

1. Configure `JwtConfig`: `--jwt-issuer` and `--jwt-audience` (env `JWT_ISSUER` / `JWT_AUDIENCE`) are BOTH required — one without the other prints a warning and disables JWT entirely. `--jwt-jwks-uri` is optional; without it `JwksProvider::from_issuer` discovers via `<issuer>/.well-known/openid-configuration`.
2. Every JWKS/discovery URL passes `validate_url` (`crates/auth/src/jwks.rs`): HTTPS only (plain http for `localhost` / `127.0.0.1` / `::1` only), literal private/link-local/CGNAT/metadata IPs and `metadata` / `*.internal` / `*.local` hostnames rejected (no DNS resolution — the check is on the literal host), response capped at 1 MiB. A JWKS on an internal network fails at startup.
3. Set `--jwt-role-claim` to the provider's claim name (default `roles`; if absent, `extract_role` falls back to `role` / `roles` / `groups` / `group`)
4. Map IDP roles to gateway roles via repeatable `--jwt-role-mapping idp_role=gateway_role`, or `JwtConfig::with_role_mapping`:
   ```rust
   role_mapping: HashMap::from([
       ("admin".to_string(), Role::Admin),
       ("reader".to_string(), Role::User),
   ])
   ```
5. Test: Token validation, claim extraction, role mapping

### Adding a Custom Auth Method

1. Implement validation logic in `crates/auth/src/`
2. Extract `Principal` from request (via `PrincipalExt`, `crates/auth/src/middleware.rs`)
3. Integrate via the `apply_control_plane_auth` closure in `model_gateway/src/server.rs:build_app`, which layers `control_plane_auth_middleware` on BOTH `admin_routes` (`/flush_cache`, `/get_loads`, `/parse/*`, `/wasm*`, `/v1/tokenizers*` — no literal `/admin` prefix) and `worker_routes` (`/workers*`). With no control-plane auth configured the closure falls back to `auth_middleware` with the shared `--api-key`, or to `deny_all_middleware` when only tenant keys exist.
4. Emit the matching `AuditLogger` call inside `crates/auth` (see below)

### JWT Flow (7 Steps)

1. Decode header → extract `kid`
2. Fetch signing key from JWKS (cached, TTL 1hr)
3. Verify algorithm matches key
4. Validate: expiry, issuer, audience
5. *(Opt-in, off by default)* Check JTI cache for replay (10k-entry LRU, `DEFAULT_JTI_CACHE_SIZE`). `JwtValidator::from_config` passes `enable_jti_check = false`; only `from_config_with_options(config, true)` enables it. Runs BEFORE subject/role extraction, not last.
6. Extract role from `role_claim` (falls back to `role` / `roles` / `groups` / `group`)
7. Map via `role_mapping`; with an empty mapping the value is parsed directly as `admin` / `user`. Anything unmatched → `Role::User` with a warn — never an error.

## Audit Events

Audit logging is per-request and lives in `control_plane_auth_middleware` (`crates/auth/src/middleware.rs`): `log_success` on authenticated admin access, `log_denied` for a non-admin principal, `log_auth_failure` for a missing/invalid token. Handlers in `model_gateway` emit nothing. Add an auth path inside `crates/auth` → build an `AuditContext` and call the matching `AuditLogger` method. `AuditContext` is NOT re-exported from `lib.rs`, so from outside the crate only `AuditLogger::log(&AuditEvent)` and `log_auth_failure` are callable:
```rust
// AuditEvent fields (audit.rs), all pub: timestamp, principal, auth_method, role,
//   method, path, resource, outcome (Success | Denied), request_id, details
```

## Key Rules

- API keys: SHA-256 hash at load time, constant-time comparison; `find_api_key` scans every entry with no early return
- JWT: Always validate expiry, issuer, audience
- Audit: emitted once per request by `control_plane_auth_middleware`, never by a handler
- Never store plaintext keys — `TenantApiKeyEntry`'s `Debug` impl redacts `key`

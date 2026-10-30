---
recipe: auth-feature
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/auth/src/
  - model_gateway/src/middleware/auth.rs
  - model_gateway/src/server/posture.rs
  - model_gateway/tests/security/control_plane_roles_test.rs
exemplars:
  - 8b60634b   # fix: the JWKS provider bounds a response body as it reads it, key set and discovery alike
  - 4ba5a73a   # fix: OIDC discovery refuses a document whose issuer is not the configured issuer
  - 759b4088   # fix: a gateway API key ends at the auth middleware and is never forwarded upstream
---

# Add an auth feature

Two independent layers. Serving path (`/v1/*`): `model_gateway/src/middleware/auth.rs` — `AuthConfig::with_tenant_keys(api_key, &tenant_api_keys)` SHA-256-hashes every key into a map and `auth_middleware` resolves the Bearer token into a `DataPlaneCaller` carrying a `TenantKey` (`auth:<tenant_id>` for `--tenant-api-key tenant_id:key`, hash-derived for the shared `--api-key`). Control plane (`admin_routes`, `worker_routes`, `/v1/rl`): crate `smg-auth` (`crates/auth/src/`), where `control_plane_auth_middleware` tries JWT/OIDC first, then API keys (`--control-plane-api-keys id:name:role:key`, SHA-256); roles are `Admin` and `User`. Tasks A–C are the control plane; the serving-path rules close the recipe.

Not this recipe:
- Consuming the tenant identity (`tenancy-feature`).
- Listener posture and mTLS (`model_gateway/src/server/posture.rs`, `tests/security/mtls_test.rs`).

## Inputs

| Input | Example | Used in |
|---|---|---|
| New role | `auditor` | A1–A3 |
| OIDC provider | issuer, audience, JWKS URI, role claim, role mapping | B1–B3 |
| Custom method | an mTLS principal | C1–C2 |

## Steps

Task A — add a role.

### A1. Extend `Role` and the hard-coded matches

File: `crates/auth/src/config.rs` — Do: add the variant and update its `Display`, `FromStr` and `is_admin()` impls. Then the matches that bypass `FromStr`: `model_gateway/src/cli/value.rs` (`parse_control_plane_api_key`, `parse_role_mapping`), the `"admin" | "user"` guard on `--jwt-role-mapping` in `model_gateway/src/main.rs`, and `PyRole` plus its `role_mapping` match in `bindings/python/src/lib.rs`. The CLI parsers fail closed with `ConfigError::InvalidValue` (`jwt_role_mapping_entries_fail_closed`); the Python match maps anything but `admin` to `User`.
Verify: `cargo test -p smg-auth config::` (`test_role_parsing`) and `cargo test -p smg jwt_role_mapping`.
Trap: a variant added only to the enum is refused by every CLI flag and silently becomes `User` through the Python binding.

### A2. Update the role gate

File: `crates/auth/src/middleware.rs`, `crates/auth/src/jwt.rs` — Do: `role_allows(role, method)` admits `is_admin()` plus read-only `GET` / `HEAD` for any authenticated principal (`check_role` logs `log_denied` otherwise); `JwtValidator::extract_role` parses or maps claim values.
Verify: `cargo test -p smg-auth middleware::` → `user_may_only_read`, `admin_may_use_every_method`.

### A3. Pin the route matrix

File: `model_gateway/tests/security/control_plane_roles_test.rs` — Do: add the role's routes to `READ_ROUTES` (`user`) or `WRITE_ROUTES` (`admin`); the test runs them on the production route table.
Verify: `cargo test -p smg --test security_tests control_plane_role_matrix`
Trap: a control-plane route without a row here is unpinned — this matrix is what fails when the gate regresses; A2's unit tests cover only the function.

Task B — add an OIDC provider.

### B1. Configure `JwtConfig`

File: `model_gateway/src/main.rs` (`build_control_plane_auth_config`), `crates/auth/src/config.rs` — Do: `--jwt-issuer` and `--jwt-audience` (env `JWT_ISSUER` / `JWT_AUDIENCE`) are both required: one without the other is `ConfigError::IncompatibleConfig` (`jwt_issuer_and_audience_are_required_together`). `--jwt-jwks-uri` is optional; without it `JwksProvider::from_issuer` discovers `<issuer>/.well-known/openid-configuration`. `--jwt-role-claim` (`JwtConfig.role_claim`) names the claim (default `roles`; when absent `extract_role` falls back to `role` / `roles` / `groups` / `group`); map IdP roles with repeatable `--jwt-role-mapping idp_role=gateway_role` or `JwtConfig::with_role_mapping(idp_role, Role::Admin)`. With an empty mapping the value is parsed directly as `admin` / `user`; anything unmatched is `Role::User` with a warn, never an error.
Verify: `cargo run -p smg --bin smg -- --help | rg jwt`; `cargo test -p smg-auth jwt::`

### B2. Meet the JWKS rules

File: `crates/auth/src/jwks.rs` — Do: every JWKS and discovery URL passes `validate_url`: HTTPS only (plain `http` for `localhost`, `127.0.0.1`, `::1`), literal private/link-local/CGNAT/metadata IPs rejected (`is_private_ip`, IPv4-mapped IPv6 included) as are `metadata`, `*.internal` and `*.local` hosts — on the literal host, no DNS. Both bodies stream through `bounded_body` and are refused past `MAX_JWKS_RESPONSE_SIZE` (1 MiB) as they are read (8b60634b); the discovery document's `issuer` must equal the configured issuer exactly, trailing slash included (4ba5a73a). Keys are cached for `jwks_cache_ttl_secs` (default 3600) and an unknown `kid` refetches at most once per `UNKNOWN_KID_REFRESH_INTERVAL` (60 s).
Verify: `cargo test -p smg-auth jwks::` → `a_chunked_key_set_past_the_limit_is_refused_as_it_is_read`, `a_discovery_document_for_another_issuer_is_refused`, `test_validate_url_blocks_private_ips`.
Trap: a JWKS on an internal network fails at startup; `ControlPlaneAuthState::try_init` then keeps auth required instead of opening the control plane (`failed_jwt_initialization_retains_required_authentication`).

### B3. Test the flow end to end

Do: token validation, claim extraction, role mapping. `JwtValidator::validate` decodes the header for `kid`, fetches the key (`get_key`), refuses an algorithm mismatch, validates `exp`, `nbf` (`validate_nbf = true`), issuer and audience, checks the JTI cache when enabled — opt-in: `from_config` passes `enable_jti_check = false`, `from_config_with_options(config, true)` enables the `DEFAULT_JTI_CACHE_SIZE` (10k) LRU, and it runs before subject/role extraction — then extracts and maps the role.
Verify: `cargo test -p smg-auth` → `nbf_in_the_past_or_within_the_leeway_is_accepted` among them.

Task C — add a custom auth method.

### C1. Validate inside the crate and join the single admission path

File: `crates/auth/src/middleware.rs` (plus a new module under `crates/auth/src/`) — Do: produce a `Principal` (`PrincipalExt` reads it from request extensions) inside `control_plane_auth_middleware` → `admit`: JWT first, then `find_api_key` (scans every entry with no early return; `ApiKeyEntry::verify` compares hashes with `ct_eq`); a 3-segment token that fails JWT validation is refused outright, not retried as a key. `model_gateway/src/server.rs::build_app` applies the middleware through the `apply_control_plane_auth` closure to `admin_routes` (`/inflight`, `/flush_cache`, `/get_loads`, `/parse/*`, `/wasm*`, `/v1/tokenizers*`, profiling — no `/admin` prefix), `worker_routes` (`/workers*`) and `/v1/rl`; with no control-plane auth it falls back to `auth_middleware` with the shared `--api-key`, or `deny_all_middleware` when only tenant keys exist.
Verify: `cargo test -p smg-auth middleware::` → `an_api_key_caller_is_refused_forbidden_or_admitted_through_one_path`.

### C2. Emit the audit event

File: `crates/auth/src/middleware.rs`, `crates/auth/src/audit.rs` — Do: audit logging is per request and lives in the middleware only: `log_success` on admitted access, `log_denied` for a role refusal, `log_auth_failure` for a missing or invalid token; build an `AuditContext` for your path. `AuditContext` is not re-exported from `lib.rs`, so outside the crate only `AuditLogger::log(&AuditEvent)` and `log_auth_failure` are callable. `AuditEvent` fields are all pub: `timestamp`, `principal`, `auth_method`, `role`, `method`, `path`, `resource`, `outcome` (`AuditOutcome::Success | Denied`), `request_id`, `details`.
Trap: a `model_gateway` handler that writes its own audit line double-counts — handlers emit nothing.
Verify: `cargo test -p smg-auth audit` → the audit tests in `crates/auth/src/audit.rs` pass, and `cargo test -p smg --test security_tests` still admits read-only routes to `User`

### Gate

Run `smg:contribute`.

## Rules

- Serving config: `RouterConfig.tenant_api_keys: Vec<TenantApiKeyEntry>` is checked by `ConfigValidator::validate_tenant_api_keys` (non-empty `tenant_id` / `key`, no surrounding whitespace, no duplicate credential including a collision with `api_key`); `TenantApiKeyEntry`'s `Debug` redacts `key` — never store plaintext keys.
- Tenant keys never reach the control plane: `admin_auth_config = AuthConfig::new(api_key)`, and tenant-keys-only means `deny_all_middleware`.
- A matched gateway key ends at `auth_middleware`: it removes `Authorization` and any `x-api-key` / `x-goog-api-key` (`PROVIDER_KEY_HEADERS`) that carries a gateway key, so a key is never forwarded upstream as the caller's credential (`a_matched_gateway_key_does_not_travel_past_the_middleware`); `/v1/models` short-circuits on `AuthConfig::contains_token` (`endpoints/models.rs`) so a tenant key is never a BYOK credential.
- JWT always validates expiry, `nbf`, issuer and audience; API keys are SHA-256 hashed at load time and compared in constant time.

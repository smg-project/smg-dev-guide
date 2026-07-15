# Adding Auth Features to SMG

Two-factor auth: API key (SHA-256) + JWT/OIDC. Roles: Admin (control plane) and User (data plane).

## Steps

### Adding a New Role

1. Extend `Role` enum in `crates/auth/src/config.rs`
2. Update permission checks in middleware
3. Update role mapping for JWT claims
4. Add audit logging for new role actions

### Adding a New OIDC Provider

1. Configure `JwtConfig` with provider's JWKS URI
2. Set `role_claim` to match provider's claim name (default: `"roles"`)
3. Map IDP roles to gateway roles via `role_mapping`:
   ```rust
   role_mapping: HashMap::from([
       ("admin".to_string(), Role::Admin),
       ("reader".to_string(), Role::User),
   ])
   ```
4. Test: Token validation, claim extraction, role mapping

### Adding a Custom Auth Method

1. Implement validation logic in `crates/auth/src/`
2. Extract `Principal` from request (via `PrincipalExt`, `crates/auth/src/middleware.rs`)
3. Integrate via `control_plane_auth_middleware` on the merged `admin_routes` router (control-plane endpoints like `/wasm`, `/parse/*` — there is no literal `/admin` URL prefix)
4. Add audit event for the new method

### JWT Flow (7 Steps)

1. Decode header → extract `kid`
2. Fetch signing key from JWKS (cached, TTL 1hr)
3. Verify algorithm matches key
4. Validate: expiry, issuer, audience
5. Extract role from `role_claim`
6. Map via `role_mapping`
7. *(Opt-in, off by default)* Check JTI cache for replay (10k token cache, `DEFAULT_JTI_CACHE_SIZE`). `JwtValidator::from_config` sets `enable_jti_check = false`, so the default control-plane path skips this — it runs only when JTI replay protection is explicitly enabled (`from_config_with_options`).

## Audit Events

All control plane mutations must be logged. Emit via `AuditLogger` (`log_success` / `log_denied` / `log_auth_failure`) — don't construct `AuditEvent` by hand:
```rust
// AuditEvent fields (audit.rs): timestamp, principal, auth_method, role,
//   method, path, resource, outcome (Success | Denied), request_id, details
```

## Key Rules

- API keys: SHA-256 hash at load time, constant-time comparison
- JWT: Always validate expiry, issuer, audience
- Audit: Log all admin operations (add/remove modules, config changes)
- Never store plaintext keys

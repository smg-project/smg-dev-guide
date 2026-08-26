# Adding a Config Field to SMG

The #1 contributor mistake is wiring only one of two conversion paths. Follow every step.

## Steps

### Step 1: Add to DiscoveryConfig / RouterConfig

**File:** `model_gateway/src/config/types.rs`

```rust
#[serde(default, skip_serializing_if = "Option::is_none")]
pub my_field: Option<MyType>,
```

**Verify:** `cargo build`
**Anti-pattern:** Missing `#[serde(default)]` — already-serialized configs that lack the field stop deserializing (the `serde_json` backward-compat tests in `types.rs` `mod tests` catch it). A non-`Option` field with a non-zero default takes `#[serde(default = "default_my_field")]` plus a `fn default_my_field()` that the `Default` impl reuses (cf. `default_job_queue_capacity`, `default_stream_body_stall_timeout_secs`).

### Step 2: Update Default impl

**File:** `model_gateway/src/config/types.rs`

Add `my_field: None` (or `my_field: default_my_field()`) to the `Default` impl for the struct.

**Verify:** `cargo build`

### Step 2b: Add a builder setter

**File:** `model_gateway/src/config/builder.rs`

`RouterConfigBuilder` is hand-written, not derived — `.my_field(..)` does not exist until you write it. Add a setter beside the existing ones:

```rust
pub fn my_field(mut self, my_field: Option<MyType>) -> Self {
    self.config.my_field = my_field;
    self
}
```

cf. `RouterConfigBuilder::health_check_port`; for an `Option`-of-string use the `maybe_api_key(Option<impl Into<String>>)` shape. `RouterConfigBuilder::new()` starts from `RouterConfig::default()`, so Step 2's default is the builder's base.

**Verify:** `cargo build`

### Step 3: Add CLI flag

**File:** `model_gateway/src/main.rs` (`CliArgs` struct)

```rust
#[arg(long, value_parser = parse_my_type, help_heading = "Worker Configuration")]
my_field: Option<String>,
```

`CliArgs` fields are private (no `pub`), and nearly every flag carries `help_heading = "..."` to group `--help` output (cf. `health_check_port`). Renaming an existing flag keeps the old spelling alive via `visible_alias = "old-name"` (cf. `--cache-match-threshold`, test `alias_flags_parse_identically_to_canonical`).

Add a validation function — return the typed value when the field is typed (cf. `parse_transport_mode -> Result<TransportMode, String>`):
```rust
fn parse_my_type(s: &str) -> Result<String, String> {
    MyType::parse(s).map_err(|e| e.to_string())?;
    Ok(s.to_string())
}
```

**Verify:** `cargo build`
**Anti-pattern:** No `value_parser` — invalid values accepted, crash at runtime instead of parse time.

### Step 4: Wire BOTH conversion paths (CRITICAL)

**File:** `model_gateway/src/main.rs`

Both are `CliArgs` methods sourcing from `self` — there is no config-file loader for `RouterConfig`.

- `to_router_config(&self, prefill_urls, encode_urls) -> ConfigResult<RouterConfig>` assembles via `RouterConfig::builder()....build()`. Add the Step 2b setter to the chain.
- `to_server_config(&self, router_config: RouterConfig) -> ConfigResult<ServerConfig>` returns a `ServerConfig { .. }` literal whose `router_config` field carries the whole `RouterConfig`. A RouterConfig-only field needs **nothing** here — it rides along nested.

```rust
// to_router_config
let builder = RouterConfig::builder()
    // ...
    .my_field(self.my_field);          // cf. .health_check_port(self.health_check_port)
```

Only a listener/runtime-level setting that `server::startup` (or `main` around it) reads directly off `ServerConfig` (e.g. `config.host`, `config.port`, `config.health_check_port`, `config.runtime_worker_threads`, `config.max_payload_size`, `config.request_timeout_secs`, `config.shutdown_grace_period_secs`, `config.webrtc_bind_addr`, `config.control_plane_auth`) also needs a top-level copy. For those, add the field to `pub struct ServerConfig` in `model_gateway/src/server.rs` and set it in ALL THREE literals — `main.rs:to_server_config`, `bindings/python/src/lib.rs` (`Router::start`), and the `server.rs` test helper `minimal_server_config`:

```rust
Ok(ServerConfig {                      // main.rs:to_server_config
    // ...
    my_field: self.my_field,           // cf. health_check_port: self.health_check_port,
})
```

`to_server_config` also derives `ServiceDiscoveryConfig` from `router_config.discovery`: only `model_id_source` merges CLI (`--model-id-from`) over config with `.or_else(...)`; `router_selector` and `router_mesh_port_annotation` are copied straight out with no CLI override.

**Verify:** add `my_field_flows_into_both_configs` to `main.rs` `mod tests` — `cli_args_from(&["--my-field", ..])`, then `to_router_config(vec![], vec![])`, then `to_server_config(router_config)`. Assert `server_config.my_field` for a top-level field (cf. `health_check_port_flows_into_both_configs`) or `server_config.router_config.my_field` for a nested one (cf. `engine_metrics_flows_into_both_configs`).
**Anti-pattern:** Wiring only the builder for a top-level `ServerConfig` field. `server::startup` reads the `ServerConfig` copy and silently sees the default — no error, just ignored.

### Step 4b: Add config validation (if the field has invariants)

**File:** `model_gateway/src/config/validation.rs`

Add the check to the matching `ConfigValidator::validate_*` (`validate_server_settings`, `validate_policy`, `validate_discovery`, `validate_compatibility`, ...), returning `ConfigError::InvalidValue { field, value, reason }`. This gate runs from `RouterConfigBuilder::build()` for BOTH the CLI and the Python bindings; the Step 3 `value_parser` only guards the CLI.

**Verify:** `cargo test`
**Anti-pattern:** Range or cross-field invariants enforced only by `value_parser` — Python callers reach the builder directly and bypass clap entirely.

### Step 5: Update Python bindings

**File:** `bindings/python/src/lib.rs`

The `Router` constructor is `#[new]` with a flat `#[pyo3(signature = (...))]`, and `RouterConfig` is assembled via `RouterConfig::builder()` in `to_router_config()` — there is NO `RouterConfig` struct literal. Append `my_field` to the signature, store it on the `Router` pyclass, thread it through the builder chain, and mirror it in `src/smg/router_args.py`. Full procedure: @bindings-update.md.

**Verify:** `make python-dev`, then `cd bindings/python && pytest -q tests` (what CI runs; `make python-test` runs `e2e_test/` instead). Append the new field to the END of the `RouterArgs` dataclass — after the `# Append new fields here` marker — and to the end of `EXPECTED_FIELD_SEQUENCE` in `bindings/python/tests/test_arg_parser.py`. Positional field order is a public contract; the snapshot test fails on any mid-list insertion.
**Anti-pattern:** Grepping for a `RouterConfig {` literal — none exists; add the field to the `builder()` chain instead. But `ServerConfig {` and `DiscoveryConfig {` literals DO exist in `lib.rs` (`Router::start`, `to_router_config`) as well as in `main.rs`; a field on either of those structs must be added to every literal or the bindings stop compiling.

### Step 6: Go SDK — no change

`bindings/golang/` is a gRPC client SDK plus a tokenizer/parser cdylib; it carries no `RouterConfig`/`ServerConfig` surface. Skip.

### Step 7: Add tests

- Serde backward-compat test in `config/types.rs` `mod tests`: `serde_json` round-trip with and without the field (cf. `test_health_check_port_serde_roundtrip_and_backward_compat`) — not YAML
- `main.rs` `mod tests`, the established trio per flag: `my_field_flows_into_both_configs`, `my_field_defaults_to_none_in_both_configs`, `my_field_..._rejected_at_parse_time`, all built on `cli_args_from(&[..])`
- Update full struct literals of the modified type. `RouterConfig` test literals are all `..Default::default()` spreads (nothing to do); `DiscoveryConfig` has a full literal in `types.rs` tests plus production literals in `main.rs:to_router_config` and `lib.rs:to_router_config`; `ServerConfig` has the three from Step 4

**Verify:** `cargo test`

## Common Mistakes

| Mistake | Consequence | Prevention |
|---------|-------------|------------|
| Only wiring `to_router_config()` for a `ServerConfig`-level field | `server::startup` reads the default off `ServerConfig` | Add a `*_flows_into_both_configs` test in `main.rs` |
| Adding `my_field: self.my_field` to the `ServerConfig` literal for a RouterConfig-only field | Does not compile — it rides in `ServerConfig.router_config` | Only top-level `ServerConfig` fields get a literal entry |
| Calling `.my_field(..)` without writing the setter | Does not compile — no such method on `RouterConfigBuilder` | It is hand-written, not derived: add the setter in `config/builder.rs` first |
| Missing `#[serde(default)]` | Serialized configs without the field break on deserialize | Every `Option<T>` field needs it |
| Invariants only in clap `value_parser` | Python bindings bypass clap and accept the bad value | Put the check in `config/validation.rs` |
| Inserting a `RouterArgs` field mid-list | `EXPECTED_FIELD_SEQUENCE` snapshot fails; positional callers rebind | Append at the tail and to the snapshot list |
| String instead of typed enum at runtime | Re-parsing on every request | Parse at boundary, store typed |

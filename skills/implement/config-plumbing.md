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
**Anti-pattern:** Missing `#[serde(default)]` — existing YAML configs will fail to deserialize.

### Step 2: Update Default impl

**File:** `model_gateway/src/config/types.rs`

Add `my_field: None` (or appropriate default) to the `Default` impl for the struct.

**Verify:** `cargo build`

### Step 3: Add CLI flag

**File:** `model_gateway/src/main.rs` (CliArgs struct)

```rust
#[arg(long, value_parser = parse_my_type)]
pub my_field: Option<String>,
```

Add validation function:
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

Both are `CliArgs` methods taking `&self` — `self` (the parsed CLI args) is the single source, there is no separate config object to `.or()` against. Find BOTH and add the field, but note they build differently:

```rust
// to_router_config: assembles via RouterConfig::builder()....build()
let builder = RouterConfig::builder()
    // ...
    .my_field(self.my_field);          // or .maybe_my_field(self.my_field.as_ref()) for an Option
//  cf. .health_check_port(self.health_check_port), .enable_wasm(self.enable_wasm)

// to_server_config: returns a ServerConfig { ... } struct literal
Ok(ServerConfig {
    // ...
    my_field: self.my_field,           // cf. health_check_port: self.health_check_port,
})
```

**Verify:** `grep -n "my_field" model_gateway/src/main.rs` — must show assignments in BOTH functions.
**Anti-pattern:** Only wiring one path. CLI flag works but config file doesn't (or vice versa). This is silent — no error, just ignored.

### Step 5: Update Python bindings

**File:** `bindings/python/src/lib.rs`

The `Router` constructor is `#[new]` with a flat `#[pyo3(signature = (...))]`, and `RouterConfig` is assembled via `RouterConfig::builder()` in `to_router_config()` — there is NO `RouterConfig` struct literal. Append `my_field` to the signature, store it on the `Router` pyclass, thread it through the builder chain, and mirror it in `src/smg/router_args.py`. Full procedure: @bindings-update.md.

**Verify:** `make python-dev`
**Anti-pattern:** Grepping for a `RouterConfig {` literal — none exists; add the field to the `builder()` chain instead.

### Step 6: Update Go SDK (if exposed)

**Files:** `bindings/golang/` — add to Go struct + FFI bridge if the field is user-facing.

**Verify:** Go tests pass.

### Step 7: Add tests

- Config deserialization test: YAML with and without the new field
- Validation test: invalid value rejected at parse time
- Update existing test struct literals that construct the modified config type

**Verify:** `cargo test`

## Common Mistakes

| Mistake | Consequence | Prevention |
|---------|-------------|------------|
| Only wiring `to_router_config()` | Config file value silently ignored | Always grep for BOTH functions |
| Missing `#[serde(default)]` | Existing configs break on deserialize | Every `Option<T>` field needs it |
| String instead of typed enum at runtime | Re-parsing on every request | Parse at boundary, store typed |
| Looking for a `RouterConfig {` literal | None exists — it's `builder()...build()` | Add to the builder chain + `router_args.py` (see @bindings-update.md) |

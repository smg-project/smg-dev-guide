# Updating SMG Language Bindings

Required whenever config types or public APIs change. The #2 contributor mistake after the config two-path rule. Python is a flat keyword API on `Router`; Go is a cgo FFI bridge plus gRPC.

## Python Bindings (PyO3 + maturin)

`bindings/python/src/lib.rs` exposes ONE pyclass `Router`. There is no `__init__`: the constructor is a `#[new] fn new(...)` with a flat `#[pyo3(signature = (...))]` of ~110+ params (the `fn new` inside `impl Router`'s `#[pymethods]` block). `RouterConfig` is NOT a struct literal — it is assembled in `to_router_config()` via `RouterConfig::builder()....build()`. A new field is threaded through four spots.

> **Keep `PolicyType` in sync with `PolicyConfig`.** The Python `enum PolicyType` (`bindings/python/src/lib.rs`) must mirror `PolicyConfig` (`model_gateway/src/config/types.rs`) — both currently list the same 9 policies (`Random`, `RoundRobin`, `CacheAware`, `PowerOfTwo`, `LeastLoad`, `Bucket`, `Manual`, `ConsistentHashing`, `PrefixHash`). Adding a policy means updating both plus the `convert_policy` mapping below.

### Step 1: Add to the `#[new]` signature + store on the pyclass

**File:** `bindings/python/src/lib.rs`

1. Add a default to the `#[pyo3(signature = (...))]` list (the `#[new]` block in `impl Router`). APPEND at the end — new params MUST go last so positional `_Router(...)` callers don't break (see the "Appended last to match the `#[pyo3(signature)]` order" comment in `fn new`, next to `health_check_port`).
2. Add the typed arg to `fn new(...)` (the `Router` constructor) and set it in the returned `Router { ... }`.
3. Add the field to the `struct Router` pyclass.

```rust
// signature (append last):  my_field = None,
// fn new param:             my_field: Option<String>,
// returned struct:          my_field,
// struct Router field:      my_field: Option<String>,
```

### Step 2: Thread it through `to_router_config()` builder

**File:** `bindings/python/src/lib.rs` (the `to_router_config` method)

Add a builder call in the `RouterConfig::builder()...` chain (the `config::RouterConfig::builder()` call near the end of `to_router_config`). Use `maybe_*` for `Option` fields:

```rust
.maybe_my_field(self.my_field.as_ref())
```

If it belongs to discovery, add it to the `DiscoveryConfig { .. }` literal instead (the `Some(DiscoveryConfig { .. })` block in `to_router_config`). For a new enum, mirror the `convert_policy` closure (the `let convert_policy = |policy: &PolicyType| -> ...` closure in `to_router_config`): `match` on the variant, return `config::ConfigError::InvalidValue` on a bad string.

**Anti-pattern:** grepping for `RouterConfig {` — there is no such literal. The only struct literals here are `DiscoveryConfig`, `MetricsConfig`, `RetryConfig`, etc.

### Step 3: Mirror in the Python arg surface

**File:** `bindings/python/src/smg/router_args.py`

`RouterArgs` (the `@dataclasses.dataclass class RouterArgs` in `router_args.py`) is a dataclass; `router.py`'s `Router.from_args` calls `_Router(**args_dict)`. A param missing here is never passed.

1. Add the dataclass field (with default) to `RouterArgs`.
2. Add the matching `--my-field` in `RouterArgs.add_cli_args(...)` under the right `add_argument_group`.

**Verify:** field name matches the `#[new]` param exactly (underscores).

### Step 4: Build and smoke-test

```bash
make python-dev   # Makefile -> maturin develop in bindings/python
python -c "from smg import Router; Router(worker_urls=['http://127.0.0.1:8000'], my_field='x')"
```

**Verify:** build succeeds AND import + construction work (package is `smg`; native ext is `smg.smg_rs`).

## Go SDK (cgo FFI + gRPC)

Two layers. Rust FFI exports live in `bindings/golang/src/*.rs` (client.rs, policy.rs, tokenizer.rs, preprocessor.rs, postprocessor.rs, stream.rs, grpc_converter.rs, tool_parser.rs, memory.rs) as `#[no_mangle] pub unsafe extern "C" fn sgl_*`. `src/lib.rs` only re-exports + wires modules (its `pub use` / `mod` block). The Go cgo bridge lives in `internal/ffi/*.go` (those `import "C"`); top-level wrappers (`multi_client.go`, `client.go`) do NOT import C — they delegate to `internal/ffi` and `internal/grpc`. Module path: `github.com/lightseek/smg/go-grpc-sdk`.

### Step 1: Add the Rust FFI export

**File:** the relevant `bindings/golang/src/*.rs` (e.g. `client.rs` for client ops)

```rust
#[no_mangle]
pub unsafe extern "C" fn sgl_my_function(
    handle: *mut SglangClientHandle,
    arg: *const c_char,
    error_out: *mut *mut c_char,
) -> SglErrorCode {
    // null-check, CStr::from_ptr(...).to_str(), set_error_message on failure
}
```

Re-export it from `src/lib.rs` (in the `pub use` block): `pub use client::sgl_my_function;`. Follow `sgl_client_create` (in `src/client.rs`) for the null-check + error-out contract.

**Anti-pattern:** adding the `extern "C" fn` to `src/lib.rs` — it only does `pub use` + `mod`.

### Step 2: Add the cgo bridge + high-level wrapper

**File:** `bindings/golang/internal/ffi/<file>.go` (e.g. `client.go`)

1. Declare the C signature in the `/* ... */` cgo header block, then call it.

```go
result := C.sgl_my_function(h.handle, cArg, &errorPtr)
if ErrorCode(result) != ErrorSuccess { /* GoString(errorPtr); C.sgl_free_string(errorPtr) */ }
```

2. Surface it from the top-level wrapper that already imports `internal/ffi` (e.g. `multi_client.go`, which imports `github.com/lightseek/smg/go-grpc-sdk/internal/ffi`), NOT raw `C.` calls in top-level code.

```go
func (c *MultiClient) MyFunction(arg string) error { return c.ffiClient.MyFunction(arg) }
```

**Anti-pattern:** calling `C.sgl_*` from top-level `client.go`/`multi_client.go` — they have no `import "C"`.

### Step 3: Test

```bash
cd bindings/golang && go test ./...
```

## Common Mistakes

| Mistake | Consequence |
|---------|-------------|
| Looking for a `RouterConfig {` literal | None exists — it's `builder()...build()` in `to_router_config()` |
| Inserting a `#[new]` param mid-list | Breaks positional `_Router(...)` callers |
| Skipping `router_args.py` | CLI/serve path never passes the new param |
| Putting `extern "C" fn` in golang `src/lib.rs` | Wrong file — exports live in `src/*.rs`, lib.rs only re-exports |
| `C.sgl_*` in top-level Go wrapper | No `import "C"` there — bridge belongs in `internal/ffi` |
| Go/Rust FFI type mismatch | Segfault or data corruption |

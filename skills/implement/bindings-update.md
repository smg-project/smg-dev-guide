# Updating SMG Language Bindings

Required whenever config types or public APIs change. The #2 contributor mistake after the config two-path rule. Python is a flat keyword API on `Router`; Go is a cgo FFI bridge plus gRPC.

## Python Bindings (PyO3 + maturin)

`bindings/python/src/lib.rs` exposes the router as a single pyclass `Router`, alongside enum/config helper pyclasses (`PolicyType`, `BackendType`, `HistoryBackendType`, `PyRole`, `Py*Config`, `PyApiKeyEntry`) — all registered in `#[pymodule] fn smg_rs`. There is no `__init__`: the constructor is a `#[new] fn new(...)` with a flat `#[pyo3(signature = (...))]` of 140+ params (the `fn new` inside `impl Router`'s `#[pymethods]` block). `RouterConfig` is NOT a struct literal — it is assembled in `to_router_config()` via `RouterConfig::builder()....build()`. A new field is threaded through four spots.

> **Keep `PolicyType` in sync with `PolicyConfig`.** The Python `enum PolicyType` (`bindings/python/src/lib.rs`) must mirror `PolicyConfig` (`model_gateway/src/config/types.rs`) — both currently list the same 10 policies (`Random`, `RoundRobin`, `Passthrough`, `CacheAware`, `PowerOfTwo`, `LeastLoad`, `Bucket`, `Manual`, `ConsistentHashing`, `PrefixHash`). Adding a policy means updating both, the `convert_policy` mapping below, the `policy_map` dict in `router.py`'s `policy_from_str` (an unknown name raises `KeyError`), and the `COMMON_POLICY_CHOICES` / `PREFILL_POLICY_CHOICES` / `ENCODE_POLICY_CHOICES` lists at the top of `router_args.py` (argparse `choices=`).

### Step 1: Add to the `#[new]` signature + store on the pyclass

**File:** `bindings/python/src/lib.rs`

1. Add a default to the `#[pyo3(signature = (...))]` list (the `#[new]` block in `impl Router`). APPEND after the last entry before the closing `))]` — new params MUST go last so positional `_Router(...)` callers don't break (see the "Appended last (not inserted mid-list)" comment there). Read the actual tail before editing; the list grows every release.
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

Add a builder call in the `RouterConfig::builder()...` chain (the `config::RouterConfig::builder()` call near the end of `to_router_config`). `RouterConfigBuilder` (`model_gateway/src/config/builder.rs`) is hand-written — use whichever setter it actually exposes, and add one there first if the field has none:

```rust
.maybe_my_field(self.my_field.as_ref())   // maybe_* setter (Option<String> / sub-config fields)
.zmq_engine_count(self.zmq_engine_count)  // plain setter that takes the Option directly
```

If it belongs to discovery, add it to BOTH the `Some(DiscoveryConfig { .. })` literal in `to_router_config` AND the `Some(service_discovery::ServiceDiscoveryConfig { .. })` literal in `Router::start` (passed as `server::ServerConfig.service_discovery_config`) — different types, and a field added to only the first never reaches the k8s watcher. For a new enum, mirror the `convert_policy` closure (the `let convert_policy = |policy: &PolicyType| -> ...` closure in `to_router_config`): `match` on the variant, return `config::ConfigError::InvalidValue` on a bad string.

**Anti-pattern:** grepping for `RouterConfig {` — there is no such literal. The only struct literals here are `DiscoveryConfig`, `MetricsConfig`, `RetryConfig`, etc.

### Step 3: Mirror in the Python arg surface

**File:** `bindings/python/src/smg/router_args.py`

`RouterArgs` (the `@dataclasses.dataclass class RouterArgs` in `router_args.py`) is a dataclass; `router.py`'s `Router.from_args` calls `_Router(**args_dict)`. A param missing here is never passed. Conversely, a `RouterArgs` field that is NOT a `#[new]` param must be popped in `from_args`'s `fields_to_remove` list (as the `oracle_*`/`postgres_*`/`redis_*`/`jwt_*` fields are) or `_Router(**args_dict)` raises `TypeError`.

1. APPEND the dataclass field (with default) at the tail of `RouterArgs` — field order is a public contract (positional `RouterArgs(...)`) frozen by `bindings/python/tests/test_arg_parser.py::TestRouterArgsFieldOrder`; add the name to the end of its `EXPECTED_FIELD_SEQUENCE` too.
2. Add the matching `--my-field` in `RouterArgs.add_cli_args(...)` under the right `add_argument_group`. List-valued flags use `action="extend"` (or `"append"`) so repeated occurrences accumulate like the Rust CLI.

**Verify:** field name matches the `#[new]` param exactly (underscores) — `from_cli_args` copies values by dataclass field name, so the argparse dest must equal the field name.

### Step 4: Build and smoke-test

```bash
make python-dev   # Makefile -> maturin develop in bindings/python
python -c "from smg.smg_rs import Router; Router(worker_urls=['http://127.0.0.1:8000'], my_field='x')"
cd bindings/python && pytest -q tests   # CI gate (field-order + argparse tests)
```

**Verify:** build succeeds AND import + construction work. The flat-kwarg class is the native `smg.smg_rs.Router` — `smg/__init__.py` exports only `__version__`, and `smg.router.Router` merely wraps a prebuilt handle (`from_args`).

## Go SDK (cgo FFI + gRPC)

Two layers. Rust FFI exports live in `bindings/golang/src/*.rs` (client.rs, policy.rs, tokenizer.rs, preprocessor.rs, postprocessor.rs, stream.rs, grpc_converter.rs, tool_parser.rs, memory.rs) as `#[no_mangle] pub unsafe extern "C" fn sgl_*`. `src/lib.rs` only re-exports + wires modules (its `pub use` / `mod` block). The Go cgo bridge lives in `internal/ffi/*.go` (those `import "C"`); top-level wrappers (`multi_client.go`, `client.go`) do NOT import C — they delegate to `internal/ffi` and `internal/grpc`. Module path: `github.com/lightseek/smg/go-grpc-sdk`.

`policy.rs` also carries its own `impl Worker for GrpcWorker` plus a `WorkerMetadata { .. }` literal: any change to the `Worker` trait or to `WorkerMetadata` in `model_gateway/src/worker/` must be mirrored there. `bindings/golang` is a root workspace member, so `cargo check --manifest-path bindings/golang/Cargo.toml` (a CI gate) fails until it is.

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

### Step 3: Test

```bash
cargo check --manifest-path bindings/golang/Cargo.toml  # CI gate for the Rust side (from repo root)
cd bindings/golang && make test                         # cargo build --release, then go test ./...
```

Bare `go test ./...` cannot link: `internal/ffi` declares `#cgo LDFLAGS: -lsmg_go -ldl` with no `-L`, and the `make test` target builds the `libsmg_go` cdylib and exports `CGO_LDFLAGS` + `LD_LIBRARY_PATH`/`DYLD_LIBRARY_PATH` first.

## Common Mistakes

| Mistake | Consequence |
|---------|-------------|
| Looking for a `RouterConfig {` literal | None exists — it's `builder()...build()` in `to_router_config()` |
| Inserting a `#[new]` param mid-list | Breaks positional `_Router(...)` callers |
| Inserting a `RouterArgs` field mid-list | `TestRouterArgsFieldOrder` fails in CI |
| Skipping `router_args.py` | CLI/serve path never passes the new param |
| `from smg import Router` | `smg/__init__.py` exports only `__version__` — the flat-kwarg class is `smg.smg_rs.Router` |
| Discovery field added to only one literal | k8s watcher never sees it — `Router::start` builds a second config |
| Putting `extern "C" fn` in golang `src/lib.rs` | Wrong file — exports live in `src/*.rs`, lib.rs only re-exports |
| `C.sgl_*` in top-level Go wrapper | No `import "C"` there — bridge belongs in `internal/ffi` |
| Bare `go test ./...` | Link failure — use `make test`, which builds the cdylib and sets the paths |
| Go/Rust FFI type mismatch | Segfault or data corruption |

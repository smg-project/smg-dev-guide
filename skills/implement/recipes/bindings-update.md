---
recipe: bindings-update
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - bindings/python/src/lib.rs
  - bindings/python/src/smg/
  - bindings/python/tests/
  - bindings/python/src/servicer.rs
  - bindings/golang/
  - model_gateway/src/config/builder.rs
exemplars:
  - 9411f19f   # --admin-port/--admin-host: lib.rs four lists, router_args.py, test_arg_parser.py, test_router_config.py
  - 3f12f121   # power_of_two load metric: a new enum-valued knob through lib.rs and router_args.py
  - da9f4d06   # PD prefill admission: also router.py, test_startup_sequence.py and golang/src/policy.rs
---

# Update the language bindings

Python: `bindings/python/src/lib.rs` is one pyclass `Router` (registered in `#[pymodule] fn smg_rs`, cdylib `smg_rs`) plus the helper pyclasses `PolicyType`, `BackendType`, `HistoryBackendType`, `PyRole`, `PyApiKeyEntry`, `Py*Config`; there is no `__init__`, the constructor is `#[new] fn new(...)` with a flat `#[pyo3(signature = (...))]` of about 215 parameters, and `RouterConfig` is assembled in `to_router_config()` via `RouterConfig::builder()....build()`, never as a struct literal.
The launcher side is the `RouterArgs` dataclass (`bindings/python/src/smg/router_args.py`) and `Router.from_args` in `router.py`, which calls `_Router(**args_dict)`; `smg/__init__.py` exports only `__version__`, the flat-kwarg class is `smg.smg_rs.Router`.
A second Python surface, `bindings/python/src/servicer.rs` (pyclasses `VllmGrpcServer`, `TokenSpeedGrpcServer`, `TrtllmGrpcServer`, `SglangGrpcServer`, `init_servicer_tracing`) wrapped by `smg/servicer.py` (`serve_rust`), binds the Rust engine servicers of `crates/engine_servicer`.
Go: Rust FFI exports live in `bindings/golang/src/*.rs` (`client.rs`, `policy.rs`, `tokenizer.rs`, `preprocessor.rs`, `postprocessor.rs`, `stream.rs`, `grpc_converter.rs`, `tool_parser.rs`, `memory.rs`) as `#[no_mangle] pub unsafe extern "C" fn sgl_*`; `src/lib.rs` only re-exports and wires modules; the cgo bridge is `internal/ffi/*.go` (the files with `import "C"`); `multi_client.go` and `client.go` delegate to `internal/ffi` and `internal/grpc`; module `github.com/lightseek/smg/go-grpc-sdk`.

Not this recipe:
- The gateway side of a config field (`config/types.rs`, `main.rs`, `builder.rs`): @config-plumbing.md. This recipe starts once the Rust field and its builder setter exist.
- A history backend's Python surface (`HistoryBackendType`, `PyRedisConfig`): @storage-backend.md step 5.

## Inputs

| Input | Example | Used in |
|---|---|---|
| `<field>` | `admin_port` | the four lists in `lib.rs`, the builder call in `to_router_config`, the `RouterArgs` field, the `--admin-port` flag |
| builder setter | `admin_port` (plain) / `maybe_redis` (`maybe_*`) | `model_gateway/src/config/builder.rs` (hand-written; 22 `maybe_*` setters) |
| Go operation | `sgl_client_create` | `bindings/golang/src/client.rs`, `internal/ffi/client.go`, `multi_client.go` |

## Steps

### 1. Add the parameter to the four Rust lists

File: `bindings/python/src/lib.rs` — Do: the signature binds `worker_urls, policy, host, port` by position, then `*,` and every other parameter keyword-only in alphabetical order; put `<field> = None` at its alphabetical place in the `#[pyo3(signature = (...))]` list, the `fn new(...)` parameters, the `Router { .. }` literal in `new` and the `struct Router` fields (the comment on `struct Router` states the rule), never at the tail.
Verify: `cargo check --manifest-path bindings/python/Cargo.toml` → compiles; `cd bindings/python && pytest -q tests/test_router_args_parity.py` → the Rust constructor and `RouterArgs` take the same names.
Trap: a tail append compiles; it only collides with the next contributor's tail append and breaks the alphabetical reading the comment promises.

### 2. Thread it through `to_router_config()`

File: `bindings/python/src/lib.rs` (`to_router_config`) — Do: add one call to the `config::RouterConfig::builder()` chain, `.maybe_<field>(self.<field>.as_ref())` for an `Option` or sub-config, a plain setter such as `.zmq_engine_count(self.zmq_engine_count)` otherwise; add the setter to `RouterConfigBuilder` first when none exists. For a new enum mirror the `convert_policy` closure (`match` on the variant, `config::ConfigError::InvalidValue` on a bad string).
Discovery has one source: `service_discovery=True` builds the single `DiscoveryConfig::Kubernetes(KubernetesDiscoveryConfig { .. })` literal, a `discovery` mapping (`Option<Bound<PyAny>>`) goes through `parse_discovery` and `config::deserialize_discovery`, both reach `.maybe_discovery(discovery)`, and `Router::start` derives `service_discovery_config` with `service_discovery::RuntimeDiscoveryConfig::from_config` and `mesh_discovery_config` with `mesh::discovery::MeshDiscoveryConfig::from_discovery` from `router_config.discovery`; there is no second literal to keep in sync.
Verify: `cargo check --manifest-path bindings/python/Cargo.toml` → compiles.
Trap: grepping for `RouterConfig {` finds nothing; the only struct literals here are `DiscoveryConfig`, `MetricsConfig`, `RetryConfig` and the like.

### 3. Mirror it in `RouterArgs` and the CLI

File: `bindings/python/src/smg/router_args.py` — Do: add the field with a default at its alphabetical place after the `_: dataclasses.KW_ONLY` marker (never at the tail, never before the frozen positional prefix `worker_urls`, `host`, `port`), and `--<field>` in `RouterArgs.add_cli_args(...)` under the right `add_argument_group`; list-valued flags use `action="extend"` (or `"append"`) so repeats accumulate like the Rust CLI. The argparse dest must equal the field name, which `from_cli_args` copies by name. A `RouterArgs` field that is not a `#[new]` parameter is popped in `from_args`'s `fields_to_remove` list (as the `oracle_*`/`postgres_*`/`redis_*`/`jwt_*` fields are) or `_Router(**args_dict)` raises `TypeError`.
Verify: `cd bindings/python && pytest -q tests/test_arg_parser.py tests/test_cli_parity.py` → `TestRouterArgsFieldOrder` (`test_the_positional_prefix_is_frozen`, `test_every_other_field_is_keyword_only`, `test_the_keyword_only_fields_are_in_alphabetical_order`) passes and the flag matches `struct CliArgs` in `main.rs`.
Trap: skipping `router_args.py` compiles and the CLI/serve path never passes the parameter; a flag spelled differently from the Rust CLI passes locally and fails `test_cli_parity.py`.

### 4. Update the tests the exemplars touch

File: `bindings/python/tests/` — Do: extend `test_router_config.py` (validation of `RouterArgs` combinations) and `test_startup_sequence.py` (launch flow) for the new field; `test_helm_chart_args.py` renders the chart's `smg.routerArgs` and requires every emitted flag to be an exact `RouterArgs` option (needs `helm`, skipped without it); `test_cli_parity.py` keeps exception lists that fail when an entry no longer holds.
Verify: `cd bindings/python && pytest -q tests` → the CI gate passes.

### 5. Build and smoke-test

File: `Makefile` — Do: `make python-dev` (maturin develop in `bindings/python`), then `python -c "from smg.smg_rs import Router; Router(worker_urls=['http://127.0.0.1:8000'], <field>=...)"`.
Verify: import and construction succeed.
Trap: `from smg import Router` imports nothing useful; `smg.router.Router` only wraps a prebuilt handle (`from_args`).

### 6. Go: FFI export, cgo bridge, wrapper

File: `bindings/golang/src/client.rs` (or the matching `src/*.rs`) — Do: add `#[no_mangle] pub unsafe extern "C" fn sgl_<op>(handle: *mut SglangClientHandle, arg: *const c_char, error_out: *mut *mut c_char) -> SglErrorCode` with the null-check, `CStr::from_ptr(...).to_str()` and `set_error_message` contract of `sgl_client_create`; re-export it from `src/lib.rs` (`pub use client::sgl_<op>;`). In `internal/ffi/client.go` declare the C signature in the `/* ... */` cgo header, call `C.sgl_<op>`, and on `ErrorCode(result) != ErrorSuccess` read the message and free it with `C.sgl_free_string`. Surface it from `multi_client.go` through `c.ffiClient`, not with raw `C.` calls.
Verify: `cargo check --manifest-path bindings/golang/Cargo.toml` (the `default-build` lint leg of `scripts/ci_rust_tests.sh`) and `cd bindings/golang && make test` (`cargo build --release`, then `go test ./...`).
Trap: bare `go test ./...` cannot link: `internal/ffi` declares `#cgo LDFLAGS: -lsmg_go -ldl` with no `-L`; `make test` builds the `libsmg_go` cdylib and exports `CGO_LDFLAGS` plus `LD_LIBRARY_PATH`/`DYLD_LIBRARY_PATH` first.

### 7. Servicer bindings

File: `bindings/python/src/servicer.rs` — Do: a servicer-side setting (a worker label such as `constrained_decoding`, an engine fact) goes into the `#[new]` signature of each affected pyclass (`PyTokenSpeedGrpcServer` and its peers) and into `smg/servicer.py`; the shared servicer-args block lives in `crates/engine_servicer`.
Verify: `cd bindings/python && pytest -q tests/test_servicer_args.py` → the three constructors take the same parameter names and defaults.

### 8. Gate

Run `smg:contribute`.

## Rules

- `PolicyType` (`lib.rs`) mirrors `PolicyConfig` (`model_gateway/src/config/types.rs`); both list the same 10 policies (`Random`, `RoundRobin`, `Passthrough`, `CacheAware`, `PowerOfTwo`, `LeastLoad`, `Bucket`, `Manual`, `ConsistentHashing`, `PrefixHash`). A new policy edits both, `convert_policy`, the `policy_map` dict in `router.py`'s `policy_from_str` (an unknown name raises `KeyError`), and `COMMON_POLICY_CHOICES`/`PREFILL_POLICY_CHOICES`/`ENCODE_POLICY_CHOICES` at the top of `router_args.py`.
- `bindings/golang/src/policy.rs` carries its own `impl Worker for GrpcWorker` and a `WorkerMetadata { .. }` literal: a change to the `Worker` trait or `WorkerMetadata` in `model_gateway/src/worker/` is mirrored there, or the `cargo check` of step 6 fails (`bindings/golang` is a root workspace member).
- No `extern "C" fn` in golang `src/lib.rs` (exports live in `src/*.rs`); no `C.sgl_*` outside `internal/ffi` (top-level wrappers have no `import "C"`).
- A Go/Rust FFI type mismatch is a segfault or silent data corruption, not a compile error.
- The Python wheel's two surfaces compile in one crate (`smg-python`): `lib.rs` registers `servicer.rs`'s classes in the same `#[pymodule]`.

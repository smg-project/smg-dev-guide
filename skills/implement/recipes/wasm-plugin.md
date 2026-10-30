---
recipe: wasm-plugin
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/wasm/src/
  - examples/wasm/
  - model_gateway/src/middleware/wasm.rs
  - model_gateway/src/wasm/
exemplars:
  # none since 2026-08-20 (13b81df6 and e7a2e029 are a fix and a refactor, not a feature)
---

# Add a WASM middleware guest

Plugins are WebAssembly components run by Wasmtime against the WIT world `smg` (`crates/wasm/src/interface/spec.wit`, `package smg:gateway;`): a guest exports `middleware-on-request` and `middleware-on-response`, each returning an `action` — `Continue` passes through, `Reject(u16)` blocks with that HTTP status, `Modify(ModifyAction)` sets/adds/removes headers and replaces the body (`modify.status` applies on OnResponse only; OnRequest ignores it).
The host crate `smg-wasm` (`crates/wasm/`) loads the component (`WasmModuleManager`, `module_manager.rs`), attaches it at a `MiddlewareAttachPoint` (`crates/wasm/src/module.rs`: `OnRequest` before routing for auth, rate limiting, request rewrite; `OnResponse` after a non-streaming backend response for logging, response rewrite; `OnError` declared but not implemented) and runs it under `WasmRuntimeConfig` limits (`crates/wasm/src/config.rs`) from `model_gateway/src/middleware/wasm.rs`.
Most "plugins" are new guests in `examples/wasm/` against the existing world; touch the host only for a new hook or a WIT change (step 6).

Not this recipe:
- Storage hooks are a separate world: `crates/wasm/src/interface/storage/storage-hooks.wit` (`package smg:storage; world storage-hook`, exports `storage-hook-before` + `storage-hook-after`), bridged by `WasmStorageHook` (`crates/wasm/src/storage_hook.rs`); model a guest on `examples/wasm/wasm-guest-storage-hook/` (its `generate!` uses `path: ".../interface/storage", world: "storage-hook"`). It is not uploaded through `POST /wasm` and needs no `--enable-wasm`: pass `--storage-hook-wasm-path /abs/guest.wasm` (Rust CLI, `bindings/python/src/smg/router_args.py`, Helm `router.wasm.path`) and `app_context.rs` `with_storage` compiles it once. The gateway always builds `smg-wasm` with the `storage-hooks` feature (`model_gateway/Cargo.toml`); the flag only matters for `cargo test -p smg-wasm --features storage-hooks` (fixtures via `crates/wasm/tests/fixtures/build_fixtures.sh`).
- `/v1/realtime`, `/v1/realtime/calls` and `/v1/audio/transcriptions` are mounted without the WASM layer (`model_gateway/src/server.rs`): no guest of any kind runs on them.

## Inputs

| Input | Example | Used in |
|---|---|---|
| Guest name | `wasm-guest-<name>` (crate dir; artifact `wasm_guest_<name>.component.wasm`) | steps 1-4 |
| Hooks | `OnRequest`, `OnResponse` (both traits are implemented either way) | steps 2, 4 |
| Action | `Continue` / `Reject(401)` / `Modify` with `ModifyAction { status, headers_set, headers_add, headers_remove, body_replace }` (see `wasm-guest-logging`) | step 2 |

## Steps

### 1. Scaffold the guest crate

File: `examples/wasm/wasm-guest-<name>/Cargo.toml` — Do: `crate-type = ["cdylib"]`, `wit-bindgen = { version = "0.21", features = ["macros"] }`, and an empty `[workspace]` table. Model the code on `examples/wasm/wasm-guest-auth/` (on-request only) or `wasm-guest-logging/` (both hooks, `Modify`), but neither manifest carries `[workspace]`; only the `wasm-guest-storage-hook*` manifests do.
Verify: `cargo metadata --manifest-path examples/wasm/wasm-guest-<name>/Cargo.toml` → no "current package believes it's in a workspace when it's not".
Trap: `examples/wasm/*` are neither members nor `exclude`d in the root workspace; without `[workspace]` cargo refuses the build, and with it the target dir stays under the guest.

### 2. Implement both export interfaces

File: `examples/wasm/wasm-guest-<name>/src/lib.rs` — Do: the `path` argument is required (it points at the host crate's WIT dir):
```rust
wit_bindgen::generate!({ path: "../../../crates/wasm/src/interface", world: "smg" });
use exports::smg::gateway::{middleware_on_request::Guest as OnRequestGuest,
                            middleware_on_response::Guest as OnResponseGuest};
use smg::gateway::middleware_types::{Action, Request, Response};
struct Middleware;
// req: method, path, query, headers (list<header>), body (list<u8>), request_id, now_epoch_ms
impl OnRequestGuest for Middleware { fn on_request(req: Request) -> Action { Action::Continue } }
// resp: status, headers, body — no request parameter
impl OnResponseGuest for Middleware { fn on_response(_resp: Response) -> Action { Action::Continue } }
export!(Middleware);
```
Verify: `cargo build --target wasm32-wasip2 --release` (in the guest dir) → `target/wasm32-wasip2/release/wasm_guest_<name>.wasm` exists.
Trap: both traits are required even for a no-op hook (the world exports both); `on_response` takes only `resp`; there is no single `Guest` trait; `generate!` without `path` cannot find the WIT. WIT identifiers are kebab-case and generate snake_case fields (`now-epoch-ms` → `now_epoch_ms`) and PascalCase types (`modify-action` → `ModifyAction`).

### 3. Build the component

File: `examples/wasm/wasm-guest-<name>/build.sh` — Do: copy `examples/wasm/wasm-guest-auth/build.sh`: it installs the `wasm32-wasip2` target, runs `cargo build --target wasm32-wasip2 --release`, and wraps only a core module — `wit-bindgen` 0.21+ on `wasm32-wasip2` already emits a component, which `wasm-tools component new` rejects, so it checks `wasm-tools print` for `(component` first and then just copies the file to `*.component.wasm`.
Verify: `wasm-tools print target/wasm32-wasip2/release/wasm_guest_<name>.component.wasm | head -1` → `(component`

### 4. Upload through the admin API

File: `model_gateway/src/wasm/route.rs` (`add_wasm_module`, `list_wasm_modules`, `remove_wasm_module`; mounted in `model_gateway/src/server.rs` on the admin router with control-plane / API-key auth but no `/admin` prefix: `POST /wasm`, `GET /wasm`, `DELETE /wasm/{module_uuid}`, never `/admin/wasm`) — Do: run SMG with `--enable-wasm` and POST a `WasmModuleAddRequest` (`crates/wasm/src/module.rs`): `{"modules": [{"name": "<name>", "file_path": "/abs/wasm_guest_<name>.component.wasm", "module_type": "Middleware", "attach_points": [{"Middleware": "OnRequest"}, {"Middleware": "OnResponse"}]}]}`.
Verify: `curl -s http://localhost:3000/wasm` → the module is listed with its uuid.
Trap: the host rejects a duplicate by SHA-256 (`check_duplicate_sha256_hash`, `module_manager.rs`), but validation only runs `Component::new`, so a storage-hook guest POSTed here is accepted and then skipped on every request. Order across modules at one attach point is not guaranteed (`WasmModuleManager` holds `HashMap<Uuid, WasmModule>` and `get_modules_by_attach_point` iterates it unsorted): never write a guest that depends on another running first. A `Reject` short-circuits the remaining modules for that phase.

### 5. Gate

Run `smg:contribute`.

### 6. Add a hook or change the WIT (host crate)

File: `crates/wasm/src/interface/spec.wit` — Do: edit the types/interfaces/world; host bindings regenerate through `wasmtime::component::bindgen!` in `crates/wasm/src/spec.rs` (`path: "src/interface"`, `world: "smg"`). Extend `MiddlewareAttachPoint` (`crates/wasm/src/module.rs`), add input/output variants in `crates/wasm/src/types.rs` (`WasmComponentInput` / `WasmComponentOutput`), dispatch the new export in `crates/wasm/src/runtime.rs` (`WasmThreadPool::execute_component_in_worker`, `match attach_point`), and add the phase in `model_gateway/src/middleware/wasm.rs` (`run_request_hook` / `run_response_hook`). `module_manager.rs` only forwards `attach_point`; touch `execute_module_for_attach_point` only for a new `WasmComponentOutput` variant. Tune limits in `crates/wasm/src/config.rs`.
Verify: `cargo test -p smg-wasm && cargo test -p smg middleware::wasm`
Trap: `OnError` shows the failure mode — the enum variant exists, the WIT world has no `middleware-on-error` interface, and dispatching it returns "OnError attach point not yet implemented" at runtime, not at compile time. Do not attach modules there.

## Rules

- Guest failures fail open: a trap, timeout or failed instantiation makes `execute_module_for_attach_point` return `None`, which `middleware/wasm.rs` handles as `continue` — the module is skipped and the request proceeds as if it returned `Continue`. An auth or rate-limit guest must never rely on a trap to block a request.
- Default limits (`WasmRuntimeConfig`): `max_memory_pages` 1024 (64 MB) and `max_execution_time_ms` 1000 trap the guest (store limiter / epoch deadline). `max_body_size` (10 MB) is a host cap: `axum::body::to_bytes` fails before any guest runs and the gateway answers in its error envelope — 413 for a request body over the limit, 400 `wasm_request_body_unreadable` for an unreadable one, 500 on the response phase (`wasm_response_body_too_large`, `wasm_response_body_unreadable`) (13b81df6).
- `OnResponse` is non-streaming only: SSE, ndjson and chunked responses skip the whole phase (`is_streaming`); a WebSocket upgrade would lose its extensions, which is why the realtime routes carry no WASM layer.
- `--enable-wasm` is exposed in the Rust binary, the Python launcher (`bindings/python/src/smg/router_args.py`) and the Helm chart (`deploy/helm/`, `router.wasm.enabled`); with it off the middleware layer is not installed at all (`wasm_layer` in `server.rs`).
- Execution counters live on `WasmModuleManager` alone (`record_execution`, e7a2e029); `GET /wasm` reports them.

# Adding a WASM Plugin (Guest) to SMG

Plugins are WebAssembly components run by Wasmtime against the WIT world `smg` (`crates/wasm/src/interface/spec.wit`, `package smg:gateway;`). A middleware guest exports two interfaces — `middleware-on-request` and `middleware-on-response` — each returning an `action`. The host loads the component, attaches it at a hook, and runs it inside memory/time limits.

Most "plugins" are new **guests** in `examples/wasm/` against the existing world. You only touch the host crate (`smg-wasm`) when adding a new hook or changing the WIT.

## Attachment points (`MiddlewareAttachPoint`, `crates/wasm/src/module.rs`)

| Variant | When | Typical use |
|---------|------|-------------|
| `OnRequest` | Before routing | Auth, rate limiting, request rewrite |
| `OnResponse` | After backend response | Logging, response rewrite |
| `OnError` | On error path | **Not yet implemented** — the enum variant exists but dispatching it returns a runtime error, and the WIT world has no `middleware-on-error` interface. Don't attach modules here. |

## Actions (`action` variant in `spec.wit`)

| Action | Effect |
|--------|--------|
| `Continue` | Pass through unchanged |
| `Reject(u16)` | Block with that HTTP status |
| `Modify(ModifyAction)` | Set/add/remove headers, replace body, override status |

## Steps (new middleware guest — the common case)

### Step 1: Scaffold the guest crate

**Dir:** `examples/wasm/wasm-guest-{name}/`. Model this on `examples/wasm/wasm-guest-auth/` (on-request only) or `wasm-guest-logging/` (on-request + on-response with `Modify`).

`Cargo.toml`:

```toml
[package]
name = "wasm-guest-myplugin"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
wit-bindgen = { version = "0.21", features = ["macros"] }
```

### Step 2: Implement both export interfaces

**File:** `examples/wasm/wasm-guest-{name}/src/lib.rs`. The `path` arg is REQUIRED — it points at the host crate's WIT dir.

```rust
wit_bindgen::generate!({
    path: "../../../crates/wasm/src/interface",
    world: "smg",
});

use exports::smg::gateway::{
    middleware_on_request::Guest as OnRequestGuest,
    middleware_on_response::Guest as OnResponseGuest,
};
use smg::gateway::middleware_types::{Action, Request, Response};

struct Middleware;

// req: method, path, query, headers (list<header>), body (list<u8>), request_id, now_epoch_ms
impl OnRequestGuest for Middleware {
    fn on_request(req: Request) -> Action { Action::Continue }
}

// resp: status, headers, body — NO request param
impl OnResponseGuest for Middleware {
    fn on_response(_resp: Response) -> Action { Action::Continue }
}

export!(Middleware);
```

You MUST implement both traits even if a hook is a no-op; the world exports both. For `Modify`, build a `ModifyAction { status, headers_set, headers_add, headers_remove, body_replace }` (see `wasm-guest-logging`).

### Step 3: Build the component

Target `wasm32-wasip2`, then wrap into a component. Copy `build.sh` from `wasm-guest-auth/` (handles target install + `wasm-tools component new`):

```bash
cargo build --target wasm32-wasip2 --release
wasm-tools component new \
  target/wasm32-wasip2/release/wasm_guest_myplugin.wasm \
  -o target/wasm32-wasip2/release/wasm_guest_myplugin.component.wasm
```

### Step 4: Upload via the admin API

Routes live on the admin router (control-plane / API-key auth) but the URL has **no** `/admin` prefix — `POST /wasm`, `GET /wasm`, `DELETE /wasm/{module_uuid}` (`model_gateway/src/server.rs`). Run SMG with `--enable-wasm`. The host rejects a duplicate by SHA-256 (`check_duplicate_sha256_hash`, `module_manager.rs`).

```bash
curl -X POST http://localhost:3000/wasm -H 'Content-Type: application/json' -d '{
  "modules": [{
    "name": "myplugin",
    "file_path": "/abs/path/wasm_guest_myplugin.component.wasm",
    "module_type": "Middleware",
    "attach_points": [{"Middleware": "OnRequest"}, {"Middleware": "OnResponse"}]
  }]
}'
```

Modules execute in upload order; a `Reject` short-circuits the rest.

## Adding a NEW hook or changing the WIT (host crate)

Only when the existing world is insufficient:

1. Edit `crates/wasm/src/interface/spec.wit` (types/interfaces/world).
2. Host bindings regenerate via `wasmtime::component::bindgen!` in `crates/wasm/src/spec.rs` (`path: "src/interface"`, `world: "smg"`).
3. Extend `MiddlewareAttachPoint` in `crates/wasm/src/module.rs` and its handling in `module_manager.rs`.
4. Tune limits in `crates/wasm/src/config.rs` (`WasmRuntimeConfig`).

## Storage hooks are a SEPARATE world

DB-layer interception is a different WIT world: `crates/wasm/src/interface/storage/storage-hooks.wit` (`package smg:storage; world storage-hook`, exports `storage-hook-before` + `storage-hook-after`), bridged by `WasmStorageHook` (`crates/wasm/src/storage_hook.rs`) and gated by the `storage-hooks` cargo feature. Model a storage guest on `examples/wasm/wasm-guest-storage-hook/` — note its `generate!` uses `path: ".../interface/storage", world: "storage-hook"`, not the gateway world.

## Step: Quality gate

Invoke `smg:contribute` to run fmt -> clippy -> test -> bindings -> commit.

## Critical Rules

- Two traits, exact method names: `on_request(req)` and `on_response(resp)`. `on_response` takes ONLY `resp`. There is no single `Guest` trait.
- `generate!` and `bindgen!` both need the `path` arg; omitting it on the guest fails to find the WIT.
- Default limits: `max_memory_pages: 1024` (= 64MB), `max_execution_time_ms: 1000`, plus `max_body_size: 10MB` (`config.rs` `Default`). A guest exceeding them is killed.
- Upload URL is `/wasm`, not `/admin/wasm`, despite living on the admin router.
- `--enable-wasm` is exposed in the Rust binary, the Python launcher (`bindings/python/src/smg/router_args.py`), and the Helm chart (`deploy/helm/`). With it off, the WASM middleware is skipped entirely (`model_gateway/src/middleware/wasm.rs`).
- WIT identifiers are kebab-case; generated Rust is snake_case (`now-epoch-ms` -> `now_epoch_ms`) and PascalCase types (`modify-action` -> `ModifyAction`).

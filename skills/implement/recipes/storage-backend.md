---
recipe: storage-backend
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/data_connector/src/
  - crates/data_connector/tests/
  - model_gateway/src/app_context.rs
exemplars:
  - 4d02b12f   # one contract on every backend: conformance.rs, the four backends, ci_rust_tests.sh
  - af59ba47   # a bound on every store call: bounded.rs, factory.rs bounded(), redis_integration.rs, tests/common
  - b39f784e   # tenant scope: a tenant column in every migration, core.rs, README
---

# Add a history storage backend

Backends are flat files in `crates/data_connector/src/` (`memory.rs`, `redis.rs`, `postgres.rs`, `oracle.rs`, `noop.rs`), never a directory. There is no single `StorageBackend` trait: a backend implements three traits from `core.rs`, `ConversationStorage`, `ConversationItemStorage`, `ResponseStorage`, as three structs sharing one store handle.
`create_storage` (`factory.rs`) builds the `StorageBundle`, wraps a remote store's three handles in `Bounded*Storage` (`bounded.rs`) under the backend's `op_timeout_secs`, and wraps everything in `Hooked*` (`hooked.rs`) when a hook is configured; a backend writes no hook or bound code. Model on `redis.rs`.
Package `data-connector` v2.4.0, depended on from the workspace as `smg-data-connector`.

Not this recipe:
- Hook logic belongs in `hooks.rs`/`hooked.rs`; column renames and skips in `schema.rs` (`SchemaConfig`, `TableConfig`).

## Inputs

| Input | Example | Used in |
|---|---|---|
| `<backend>` | `redis` | file `<backend>.rs`; structs `<Backend>ConversationStorage`, `<Backend>ConversationItemStorage`, `<Backend>ResponseStorage` |
| config struct | `RedisConfig` | `config.rs`: connection URL, `pool_max`, `op_timeout_secs`, `schema: Option<SchemaConfig>`, `validate()` and `validate_bounds()` |
| store handle | `RedisStore` | a `Clone` pool plus `Arc<SchemaConfig>`, shared by the three structs; `contact(bound)` for the start-up round trip |

## Steps

### 1. Create the backend file

File: `crates/data_connector/src/<backend>.rs` — Do: a `Clone` store (`pool`, `pub(crate) schema: Arc<SchemaConfig>`; `new(config)` validates the schema) and three structs each taking `store`. Honor schema overrides per table: `col`/`is_skipped` are methods on `TableConfig`, so `let s = &self.store.schema.conversations;` then `s.col("field")`/`s.is_skipped("field")`. On every write append the hook columns, `current_extra_columns().unwrap_or_default()` (`context.rs`) resolved by `resolve_extra_column_values(s, &hook_extra)` (`common.rs`), and persist `tenant` (`NewConversation`, `Conversation`, `StoredResponse` carry `tenant: Option<String>`; `tenant_scope_allows`/`is_visible_to` in `core.rs` decide reads).

```rust
#[async_trait]
impl ConversationStorage for <Backend>ConversationStorage {
    async fn create_conversation(&self, input: NewConversation) -> ConversationResult<Conversation> {
        let conv = Conversation::new(input);   // id + created_at
        // persist; map driver errors with ConversationStorageError::StorageError(e.to_string())
        Ok(conv)
    }
    // get_conversation, update_conversation, delete_conversation
}
// ConversationItemStorage: create_item, link_item, list_items, get_item, is_item_linked, delete_item
//   (link_items and ResponseStorage::get_response_chain have default impls; override for efficiency)
// ResponseStorage: store_response, get_response, delete_response, list_identifier_responses, delete_identifier_responses
```

Errors are per domain: `ConversationStorageError`, `ConversationItemStorageError`, `ResponseStorageError`, each with `StorageError(String)`, `SerializationError(#[from] serde_json::Error)` and a not-found variant; `?` covers serde, `.map_err(|e| ...StorageError(e.to_string()))` covers the driver. `ListParams { limit, order: SortOrder, after: Option<String> }` is cursor-based (`after` is an item-id cursor).
Verify: `cargo test -p data-connector` → the module's own tests pass.
Trap: offset pagination compiles; the `after` cursor is what callers send. A write that skips `resolve_extra_column_values` or `tenant` compiles and the tenant-scope cases of `tests/redis_integration.rs`/`tests/postgres_integration.rs` are the only thing that notices.

### 2. Add the config struct

File: `crates/data_connector/src/config.rs` — Do: `<Backend>Config` mirroring `RedisConfig` (connection field, `#[serde(default)] pool_max`, `op_timeout_secs` with `op_timeout()`, `schema`, `validate()`, `validate_bounds()`), a `<Backend>` variant on `HistoryBackend` (`Memory` is `#[default]`, then `None`, `Oracle`, `Postgres`, `Redis`), and the re-export in `lib.rs` (`pub use config::{HistoryBackend, MemoryConfig, OracleConfig, PostgresConfig, RedisConfig}`).
Verify: `cargo check -p data-connector` → compiles.

### 3. Migrations (SQL backends only)

File: `crates/data_connector/src/<backend>_migrations.rs` — Do: key-value backends need none. A SQL backend adds `pub(crate) static <BACKEND>_HISTORY_MIGRATIONS: [Migration; N]` (`versioning::Migration`, cf. `POSTGRES_HISTORY_MIGRATIONS`/`ORACLE_HISTORY_MIGRATIONS`, both at 4 with the v4 tenant column on responses, conversations and conversation items), creates tables at start-up (Postgres: `PostgresStore::bootstrap()` in `postgres.rs` creates them and runs `run_postgres_migrations`; Oracle: per-struct `init_schema(conn, schema)` passed to `OracleStore::new`, then `run_oracle_migrations` in `oracle.rs`), with both runners in `versioning.rs` recording versions in `_schema_versions` (`VERSIONS_TABLE`). A new dialect adds its own runner.
Verify: `cargo test -p data-connector migrations` → the up statements are asserted.
Trap: a table without the nullable `tenant` column stores every tenant's rows as unscoped; nothing fails until a cross-tenant read.

### 4. Wire the factory

File: `crates/data_connector/src/factory.rs` — Do: a `HistoryBackend::<Backend> => { .. }` arm in `create_storage` that reads `config.<backend>.ok_or(...)`, calls `validate_bounds()`, builds one store, `store.contact(bound)` once, then the three structs into a `StorageBundle { response_storage, conversation_storage, conversation_item_storage }` and, for a remote store, `bounded(bundle, CallBound::new("<backend>", cfg.op_timeout()))` as the Postgres and Redis arms do (Oracle is not wrapped). Leave the hook block at the end alone. Add `<backend>: Option<&'a <Backend>Config>` to `StorageFactoryConfig` (fields `backend`, `oracle`, `postgres`, `redis`, `memory`, `hook`) and update every literal: the `factory.rs` tests, `tests/conformance.rs`, `tests/postgres_integration.rs`, and `model_gateway/src/app_context.rs`.
Verify: `cargo test -p data-connector` → compiles the `#[ignore]` suites too.
Trap: `app_context.rs` is the only production literal; `<backend>: None` there compiles and the backend is unreachable.

### 5. Register the module and wire the gateway and bindings

File: `crates/data_connector/src/lib.rs` — Do: `mod <backend>;`. The crate enum alone is unreachable; the gateway selects the backend outside `data_connector`: `model_gateway/src/config/types.rs` gets `<backend>: Option<<Backend>Config>` on `RouterConfig` beside `oracle`/`postgres`/`redis`/`memory`, `config/builder.rs` a `maybe_<backend>` setter like `maybe_redis`; `model_gateway/src/main.rs` adds `"<backend>"` to the `--history-backend` `value_parser = ["memory", "none", "oracle", "postgres", "redis"]`, a `"<backend>" => HistoryBackend::<Backend>` arm in the string `match`, a `build_<backend>_config` arm in the `(oracle, postgres, redis)` tuple match, and `.maybe_<backend>(..)` in the builder chain; `app_context.rs` passes `config.<backend>.as_ref()`. Python: a `<Backend>` variant on `HistoryBackendType` in `bindings/python/src/lib.rs` with its `=> config::HistoryBackend::<Backend>` arm, a `Py<Backend>Config` with `to_config_<backend>` threaded like `redis_config: Option<PyRedisConfig>`/`to_config_redis`, the name in `choices=["memory", "none", "oracle", "postgres", "redis"]` of `--history-backend` in `router_args.py`, and a branch in `router.py:history_backend_from_str` (an unknown name raises `ValueError`); follow @bindings-update.md.
Verify: `cargo run -p smg --bin smg -- --help | grep history-backend` → lists the name; `cd bindings/python && pytest -q tests/test_arg_parser.py`.
Trap: clap rejects an unlisted value, but the `_` arm of the string `match` silently means `Memory`.

### 6. Tests

File: `crates/data_connector/tests/conformance.rs` — Do: the contract every backend keeps, one scenario per store: memory always (`the_memory_store_keeps_the_item_contract`), Redis, Postgres and Oracle opt-in `#[ignore]` when `DATA_CONNECTOR_TEST_REDIS_URL`/`DATA_CONNECTOR_TEST_POSTGRES_URL`/`DATA_CONNECTOR_TEST_ORACLE_URL` is set; add the new store there. Add `#[cfg(test)] mod tests` to `<backend>.rs` (round-trip each trait, cursor pagination via `ListParams`, not-found returns `Ok(None)`), a `create_storage` smoke test and a missing-config test in `factory.rs` mirroring `test_create_storage_redis_missing_config`, and for a live-server backend `tests/<backend>_integration.rs` modeled on `tests/redis_integration.rs`/`tests/postgres_integration.rs` (`tests/common/mod.rs` has the `Relay` that holds, delays or cuts a connection for the bound tests). Add the backend to the Supported Backends table of `crates/data_connector/README.md`.
Verify: `cargo test -p data-connector --test conformance`; the `agentic` shard of `scripts/ci_rust_tests.sh` (run by `pr-test-rust.yml`) runs `cargo test -p data-connector --test postgres_integration --test conformance -- --ignored --test-threads=1` against the job's database.
Trap: a backend missing from `conformance.rs` passes CI with its own tests only.

### 7. Gate

Run `smg:contribute`.

## Rules

- Three structs, three traits, never a single `StorageBackend`; hooks are wrapped by `create_storage`, the old `hooks.on_write/on_delete` calls do not exist.
- Per-domain error enums; there is no unified `StorageError` type.
- Every call to a remote store runs under `op_timeout_secs` through `Bounded*Storage`; the gateway answers 503 when the bound is exceeded, so a backend never adds its own timeout layer.
- `StoredResponse` and `Conversation` carry `tenant`; a record stored under a tenant is served only to that tenant, one stored under none to everyone (`tenant_scope_allows`).

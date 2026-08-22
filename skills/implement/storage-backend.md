# Adding a Storage Backend to SMG

Storage backends live in `crates/data_connector/src/` as FLAT files (`memory.rs`, `redis.rs`, `postgres.rs`, `oracle.rs`, `noop.rs`) — never a directory. There is NO single `StorageBackend` trait: a backend implements three traits from `core.rs` — `ConversationStorage`, `ConversationItemStorage`, `ResponseStorage` — as three separate structs sharing one store handle. Hooks are applied by `create_storage` wrapping your structs in `Hooked*` decorators — a backend writes NO hook code itself. Model this on `redis.rs`.

## Inputs to gather first

| Input | Example | Notes |
|-------|---------|-------|
| `BACKEND` | `mybackend` | File `mybackend.rs`; structs `MybackendConversationStorage`, `MybackendConversationItemStorage`, `MybackendResponseStorage` |
| Config struct | `MybackendConfig` | Lives in `config.rs`; holds connection URL, `pool_max`, optional `schema: Option<SchemaConfig>` |
| Store handle | `MybackendStore` | `Clone`-able pool + `Arc<SchemaConfig>`, shared by all three structs |

## Steps

### Step 1: Create the backend file

**File:** `crates/data_connector/src/mybackend.rs`

Define a `Clone` store handle, then three structs each taking `store: MybackendStore`. Implement the three async traits. Honor schema overrides PER TABLE — `col` / `is_skipped` are methods on `TableConfig`, not on `SchemaConfig`: `let s = &self.store.schema.conversations;` then `s.col("field")` / `s.is_skipped("field")`. Append hook-provided columns from `current_extra_columns().unwrap_or_default()` + `resolve_extra_column_values(s, &hook_extra)` on every write (see `redis.rs` create paths).

```rust
use std::sync::Arc;
use async_trait::async_trait;
use chrono::{DateTime, Utc};

use crate::{
    config::MybackendConfig,
    core::{
        Conversation, ConversationId, ConversationItem, ConversationItemId,
        ConversationItemResult, ConversationItemStorage, ConversationMetadata,
        ConversationResult, ConversationStorage, ListParams, NewConversation,
        NewConversationItem, ResponseId, ResponseResult, ResponseStorage, StoredResponse,
    },
    schema::SchemaConfig,
};

#[derive(Clone)]
pub(crate) struct MybackendStore {
    pool: MyPool,
    pub(crate) schema: Arc<SchemaConfig>,
}

impl MybackendStore {
    pub fn new(config: MybackendConfig) -> Result<Self, String> {
        let schema = config.schema.clone().unwrap_or_default();
        schema.validate()?;
        Ok(Self { pool: build_pool(&config)?, schema: Arc::new(schema) })
    }
}

pub(super) struct MybackendConversationStorage { store: MybackendStore }
impl MybackendConversationStorage { pub fn new(store: MybackendStore) -> Self { Self { store } } }

#[async_trait]
impl ConversationStorage for MybackendConversationStorage {
    async fn create_conversation(&self, input: NewConversation) -> ConversationResult<Conversation> {
        let conv = Conversation::new(input); // generates id + created_at
        // ...persist; map driver errors with ConversationStorageError::StorageError(e.to_string())
        Ok(conv)
    }
    async fn get_conversation(&self, id: &ConversationId) -> ConversationResult<Option<Conversation>> { todo!() }
    async fn update_conversation(&self, id: &ConversationId, metadata: Option<ConversationMetadata>) -> ConversationResult<Option<Conversation>> { todo!() }
    async fn delete_conversation(&self, id: &ConversationId) -> ConversationResult<bool> { todo!() }
}

// Likewise: impl ConversationItemStorage for MybackendConversationItemStorage
//   create_item, link_item, list_items, get_item, is_item_linked, delete_item
//   (link_items + ResponseStorage::get_response_chain have default impls — override for efficiency)
// And:     impl ResponseStorage for MybackendResponseStorage
//   store_response, get_response, delete_response,
//   list_identifier_responses, delete_identifier_responses
```

Errors are PER-DOMAIN, not unified: `ConversationStorageError`, `ConversationItemStorageError`, `ResponseStorageError`. Each has `StorageError(String)`, `SerializationError(#[from] serde_json::Error)`, and a not-found variant. `?` covers serde; wrap driver errors via `.map_err(|e| ...StorageError(e.to_string()))`.

`ListParams { limit, order: SortOrder, after: Option<String> }` is cursor-based (`after` = item-id cursor) — page from it, don't offset-paginate.

### Step 2: Add the config struct

**File:** `crates/data_connector/src/config.rs`

Add `MybackendConfig` (mirror `RedisConfig`: connection field, `#[serde(default)] pool_max`, `schema: Option<SchemaConfig>`, plus a `validate()`). Add a `Mybackend` variant to the `HistoryBackend` enum (variants: `Memory` (default), `None`, `Oracle`, `Postgres`, `Redis`) and re-export the new config from `lib.rs`.

### Step 3: Migrations (SQL backends only)

Key-value backends (redis) need none. SQL backends add a `mybackend_migrations.rs` (`static MYBACKEND_HISTORY_MIGRATIONS: [versioning::Migration; N]`) and create tables at startup — either in each struct's `async fn new(store) -> Result<Self, _>` (Postgres style) or via per-struct `init_schema(conn, schema)` fns passed to the store constructor (Oracle style) — then a `run_migrations()` on the store that the factory awaits once tables exist (see `create_postgres_storage` in `factory.rs`, which also re-runs `ensure_response_indexes()` when migrations applied). The runners in `versioning.rs` are dialect-specific (`run_postgres_migrations` / `run_oracle_migrations`); a new dialect adds its own.

### Step 4: Wire into the factory

**File:** `crates/data_connector/src/factory.rs`

Add a `HistoryBackend::Mybackend => { ... }` arm in `create_storage`. Build all three structs from one shared store and return a `StorageBundle { response_storage, conversation_storage, conversation_item_storage }` (exactly those three handles). Do NOT touch the hook-wrapping block at the end — it already wraps your structs in `Hooked*` when a `hook` is configured.

```rust
HistoryBackend::Mybackend => {
    let cfg = config.mybackend.ok_or("mybackend configuration is required ...")?;
    let store = MybackendStore::new(cfg.clone())?;
    StorageBundle {
        response_storage: Arc::new(MybackendResponseStorage::new(store.clone())),
        conversation_storage: Arc::new(MybackendConversationStorage::new(store.clone())),
        conversation_item_storage: Arc::new(MybackendConversationItemStorage::new(store)),
    }
}
```

Also add a `mybackend: Option<&'a MybackendConfig>` field to `StorageFactoryConfig` and update every existing `StorageFactoryConfig { .. }` literal: the `factory.rs` tests, `crates/data_connector/tests/postgres_integration.rs` (compiled by `cargo test -p data-connector` even though its tests are `#[ignore]`), and `model_gateway/src/app_context.rs` — that last one is the only production literal and must pass `config.mybackend.as_ref()`, not `None`.

### Step 5: Register the module + gateway/bindings wiring

Add `mod mybackend;` to `lib.rs`. The crate enum alone is unreachable — the gateway selects the backend outside `data_connector`, so wire it too:

- `model_gateway/src/config/types.rs`: `mybackend: Option<MybackendConfig>` on `RouterConfig`, beside `oracle` / `postgres` / `redis`; `config/builder.rs`: a `maybe_mybackend` setter mirroring `maybe_redis`.
- `model_gateway/src/main.rs`: add `"mybackend"` to the `--history-backend` `value_parser = [...]` (clap rejects anything else), a `"mybackend" => HistoryBackend::Mybackend` arm in the string `match` (its `_` arm silently means `Memory`), a `build_mybackend_config` arm in the `(oracle, postgres, redis)` tuple match, and `.maybe_mybackend(mybackend)` in the builder chain.
- `model_gateway/src/app_context.rs`: `mybackend: config.mybackend.as_ref()` in its `StorageFactoryConfig` literal.
- Python: a `Mybackend` variant on `HistoryBackendType` in `bindings/python/src/lib.rs` with its `=> config::HistoryBackend::Mybackend` arm, plus a `PyMybackendConfig` / `to_config_mybackend` threaded like `redis_config: Option<PyRedisConfig>`; add `"mybackend"` to the `--history-backend` `choices=[...]` in `bindings/python/src/smg/router_args.py` and a branch in `router.py:history_backend_from_str` (follow @bindings-update.md).

### Step 6: Tests

Add `#[cfg(test)] mod tests` to `mybackend.rs` (round-trip each trait; cursor pagination via `ListParams`; not-found returns `Ok(None)`). Add a `create_storage` smoke test arm in `factory.rs` and a missing-config error test, mirroring `test_create_storage_redis_missing_config`. A backend needing a live server gets an opt-in `#[ignore]` suite in `crates/data_connector/tests/mybackend_integration.rs` gated on an env URL — model on `tests/postgres_integration.rs` (`DATA_CONNECTOR_TEST_POSTGRES_URL`; `cargo test -p data-connector --test postgres_integration -- --ignored --test-threads=1`, which CI runs in `pr-test-rust.yml`).

**Verify:** `cargo test -p data-connector`

## Key Rules

- Three structs / three traits, never a single `StorageBackend`. Hooks are wrapped by `create_storage`; the old `hooks.on_write/on_delete` calls do not exist.
- Per-domain error enums — there is no unified `StorageError` type.
- Respect the per-table `TableConfig` (`col`/`is_skipped`) and append `resolve_extra_column_values` on writes so tenancy/hook columns persist.
- The crate enum is not enough — a backend is unreachable until `model_gateway` (`main.rs` value_parser + match, `RouterConfig`, `builder.rs`, `app_context.rs`) and the Python launcher know its name.
- Package `data-connector` (v2.3.3; depended on from the workspace as `smg-data-connector`).

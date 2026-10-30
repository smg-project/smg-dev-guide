# Checklist: storage / data connector

- [ ] Three structs implementing `ConversationStorage`, `ConversationItemStorage`, `ResponseStorage`; wrapped by `create_storage` in the `Hooked*` decorators and bounded by `bounded()`; no hook code in the backend.
- [ ] SQL backends: versioned migrations through `versioning.rs` (`run_postgres_migrations` / `run_oracle_migrations`); tenant columns in every migration; per-table `TableConfig` honoured.
- [ ] `crates/data_connector/tests/conformance.rs` runs the backend (the one scenario every store keeps); integration suites gated on `DATA_CONNECTOR_TEST_*_URL`.
- [ ] Gateway wiring: `HistoryBackend` variant, `--history-backend` value_parser, `RouterConfig` field, `app_context.rs` `StorageFactoryConfig` literal, Python `HistoryBackendType`.

| Anti-pattern | Consequence | Look for |
|---|---|---|
| Backend handed out unwrapped | audit trail gaps, unbounded stores | `create_storage` missing `Hooked*` / `Bounded*` |
| Schema change without a versioned migration | data loss on upgrade | no new `Migration` in `postgres_migrations.rs` / `oracle_migrations.rs` |
| Offset pagination | cursor contract broken | ignoring `ListParams.after` |

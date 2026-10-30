---
recipe: kv-index-feature
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/kv_index/src/
  - crates/radix_tree/src/
  - model_gateway/src/policies/cache_aware.rs
  - model_gateway/src/policies/cost/
  - model_gateway/src/worker/kv_event_monitor.rs
  - model_gateway/src/worker/kv_index_backend.rs
exemplars:
  - fad0f553   # feat: chain index + KV-event relay
  - f237e228   # feat: crates/radix_tree
  - 89b3c99e   # feat: KV capacity / block-size gauges
---

# Add a KV-cache index feature

Cache-aware routing tracks which worker holds which prompt prefix. `crates/kv_index` (package `kv-index`) holds two families: the radix trees `StringTree` (alias of `string_tree::Tree`) and `TokenTree`, fed by the router's own inserts on each decision (`cache_index = tree`), and the event-driven `ChainIndex` (`chain_index.rs`, sharded as `ShardedChainIndex`, per-worker `ChainBlockMap`), fed by the engines' KV events through `model_gateway/src/worker/kv_event_monitor.rs` and `worker/kv_index_backend.rs`. `crates/radix_tree` (package `smg-radix-tree`) is the generic prefix core with its differential referee (`tests/differential.rs`); `ReferenceIndexer` (`kv_index/src/reference.rs`) is the model `ChainIndex` must equal.

Not this recipe: a routing policy (@routing-policy.md); the gRPC `subscribe_kv_events` RPC itself (@grpc-backend.md).

## Inputs

| Input | Example | Used in |
|---|---|---|
| family | tree (routing-side) or chain index (event-driven) | A or B |
| key | text (HTTP without token ids) or tokens (gRPC/ZMQ, pre-tokenized HTTP) | A1 |
| event producer | gRPC `subscribe_kv_events`, the Rust servicer (`crates/engine_servicer/src/kv_wire.rs`, `kv_state.rs`), the mock (`crates/mock_worker/src/kv_zmq.rs`) | B2 |
| knob | `cache_threshold`, `max_tree_size`, `eviction_interval_secs`, `selection_policy` (@config-plumbing.md) | A3 |

## Steps

### A1. Tree feature

File: `crates/kv_index/src/string_tree.rs`, `token_tree.rs`, shared pieces in `common.rs` — Do: implement for both key types where applicable; token-tree code reads the runtime `page_size` (`TokenTree::with_config(page_size, policy)`), never the `PAGE_SIZE` const (`CacheAwarePolicy::new_token_tree` sizes trees to the backend KV page, `--block-size`). Match results carry `tenant` and `matched_tenants` (capped at `common.rs:MATCHED_TENANTS_CAP`); the hot path is the fused `match_and_insert` / `match_and_insert_with` (one descent), called from `select_worker_with_tokens` / `select_worker_with_text` in `cache_aware.rs`.
Verify: `cargo test -p kv-index && cargo test -p smg cache_aware`
Trap: a match path that leaves `matched_tenants` empty disables cache hits without an error.

### A2. Eviction and purge

File: `crates/kv_index/src/string_tree.rs`, `token_tree.rs` — Do: size-based `evict_tenant_by_size(max_tree_size)` runs every `eviction_interval_secs` over every model's trees (the budget is per tree, shared by its tenants; leaves go in LRU order); extend `remove_tenant_all` (on `Tree` / `TokenTree`, deliberately not on the `RadixTree` trait), which `CacheAwarePolicy::remove_worker_by_url` calls.
Verify: `cargo test -p kv-index evict`
Trap: size eviction never fires for a tenant whose count stopped growing; state not purged in `remove_tenant_all` leaks for the life of the process.

### A3. Selection

File: `model_gateway/src/policies/cache_aware.rs`, `policies/cost/` — Do: on a hit above `cache_threshold`, the candidates are `matched_tenants` and the pick runs the cost pipeline (`cost/catalog.rs`: filters, additive scorers, one picker, registered by name; `default_policy` = `cache-aware-default`; chosen by `selection_policy`) over per-worker inputs (overlap, decayed affinity via `overlap_decay` / `selection_temperature`, optimistic placement with `selection_accounting_ttl_ms`); `balance_*` thresholds move a request off a saturated holder (`balances_load_against_affinity() == true`); `--cache-index hash` (`CacheIndexKind::Hash`) uses `select_worker_hash` and no trees.
Verify: `cargo test -p smg cost`

### B1. Chain index feature

File: `crates/kv_index/src/chain_index.rs`, `sharded.rs`, `lane_map.rs` — Do: `ChainIndex` answers, for a request's per-block content hashes, how many leading blocks each worker holds; run-compressed, lock-free for readers, bounded. New state must be covered by `apply_stored`, `apply_removed`, `apply_cleared` and `remove_worker`, and stay exact against `ReferenceIndexer`.
Verify: `cargo test -p kv-index --test exactness_chain && cargo test -p kv-index --test concurrency_chain`
Trap: `intern_worker` returns `Result<WorkerId, WorkerIdExhausted>` and runs inside per-worker subscription tasks; a panic there silently stops indexing for that worker.

### B2. Producers and the gateway owner

File: `model_gateway/src/worker/kv_index_backend.rs` (wraps `ShardedChainIndex`), `worker/kv_event_monitor.rs` (drives it from each worker's event stream; `Metrics::set_kv_index_chain_stats`) — Do: wire new state there; on the producer side the Rust servicer (`crates/engine_servicer/src/kv_wire.rs`, `kv_state.rs`, `kv_history.rs`, `engine_hash.rs`), the proto (`crates/grpc_client/proto/common.proto`) and the mock producer (`crates/mock_worker/src/kv_zmq.rs`) carry the same event shape.
Verify: `cargo test -p smg kv_event && cargo test -p engine-servicer`
Trap: an event the mock never emits is untested in every CPU lane.

### C. Measure

File: `crates/kv_index/benches/` (`throughput_bench.rs`, `match_insert.rs`, `churn.rs`) — Do: extend the bench that covers the path; `.github/workflows/benchmark-radix-tree.yml` runs on `crates/kv_index/` changes and `radix-tree-fuzz.yml` fuzzes the core.
Verify: `cargo bench -p kv-index --bench throughput_bench`

### D. Gate

Run `smg:contribute`.

## Rules

- All state is `Send + Sync`; the trees use `DashMap` and `parking_lot::RwLock`, the chain index is lock-free for readers.
- Token ids win over text: `GenerationRequest::routing_tokens()` (`crates/protocols/src/common.rs`) and the `x-smg-routing-tokens` hint (`header_utils::parse_routing_tokens_hint`) feed `SelectWorkerInfo { tokens, .. }`; text is materialized only without tokens.
- The old `--kv-index`, `--kv-indexer-ttl-secs`, `--kv-indexer-max-entries` flags belong to the removed positional indexer; `main.rs` pins how the CLI treats them now.
- Test concurrent access from several routing tasks, not one.

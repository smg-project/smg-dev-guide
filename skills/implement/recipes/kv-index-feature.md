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
---

# Adding KV-Cache Index Features to SMG

Cache-aware routing tracks which worker holds which prompt prefix. Two index families live in `crates/kv_index/` (package `kv-index`):

| Index | Fed by | Used for |
|---|---|---|
| `StringTree` (a re-export alias of `string_tree::Tree`) and `TokenTree` (`token_tree.rs`), both implementing the `RadixTree` trait (`lib.rs`) | the router's own inserts on each routing decision | the default `cache_index = tree` mode of `cache_aware`: text for HTTP requests carrying no token ids, tokens for gRPC/ZMQ and pre-tokenized HTTP |
| `ChainIndex` (`chain_index.rs`), sharded as `ShardedChainIndex` (`sharded.rs`), with the per-worker `ChainBlockMap` (`lane_map.rs`) | the engines' KV events (stored / removed / cleared block hashes) through `model_gateway/src/worker/kv_event_monitor.rs` and `worker/kv_index_backend.rs` | event-driven block-level routing (`cache_aware.rs::select_worker_event_driven`) for a model whose policy has an event monitor set (`set_kv_event_monitor`) |

`crates/radix_tree/` (package `smg-radix-tree`) is the generic prefix-membership core with its own differential referee (`tests/differential.rs`: every implementation must equal the reference model). `ReferenceIndexer` (`crates/kv_index/src/reference.rs`) is the single-threaded model of what `ChainIndex` promises; `tests/exactness_chain.rs` and `tests/concurrency_chain.rs` hold the implementation to it.

Token ids win over text. `GenerationRequest::routing_tokens()` (`crates/protocols/src/common.rs`; `input_ids` Single, or a Batch's first sequence; empty falls back to text) and the `x-smg-routing-tokens` header hint (`header_utils::parse_routing_tokens_hint`, which wins over the body) both feed `SelectWorkerInfo { tokens, .. }`; the request text is only materialized when there are no tokens.

Match results carry `tenant` **plus** `matched_tenants` — every holder of the deepest matched node, capped at `common.rs:MATCHED_TENANTS_CAP`, empty on a miss. `CacheAware` selects from `matched_tenants`, so a new match path that leaves it empty silently disables cache hits.

### Match+insert (the routing hot path)

`cache_aware.rs` does not call `insert_*` then `match_prefix_with_counts` separately (two tree descents). It calls the FUSED `match_and_insert(key, tenant)` / `match_and_insert_with(key, select)` on both `Tree` (`string_tree.rs`) and `TokenTree` (`token_tree.rs`): one descent does longest-prefix-match, then inserts the unmatched remainder. Prefer `match_and_insert*` for any read-then-populate path (call sites: `select_worker_with_tokens` / `select_worker_with_text` in `cache_aware.rs`).

## Steps

### Adding a tree feature

1. Implement in `crates/kv_index/src/` (`string_tree.rs` / `token_tree.rs`, shared pieces in `common.rs`).
2. Ensure `Send + Sync` (accessed from the routing hot path; the trees use `DashMap` and `parking_lot::RwLock`).
3. Support both String and Token variants when applicable. Token-tree code reads the tree's runtime `page_size` (`TokenTree::with_config(page_size, policy)` / `page_size()`), never the `PAGE_SIZE` const — it is only the `new()` default, and `CacheAwarePolicy::new_token_tree` sizes each tree to the backend KV page (`block_size`, CLI `--block-size`).
4. Add eviction/cleanup (unbounded trees OOM): size-based `evict_tenant_by_size(max_tree_size)` runs every `eviction_interval_secs` (`--eviction-interval`, default 120) over every model's string and token tree; `max_tree_size` (`--max-tree-size`) is a budget shared by all tenants of one tree (`total_char_size()` / `total_token_size()`), removing leaves in LRU order across tenants.
5. Purge per-tenant state on worker removal — extend `remove_tenant_all` (on `Tree` / `TokenTree`, deliberately not on the `RadixTree` trait), which `CacheAwarePolicy::remove_worker_by_url` calls for every model's trees. Size eviction never fires for a tenant whose count stops growing, so anything not purged there leaks forever.
6. Consider mesh sync if the state should be cluster-wide.

**Verify:** `cargo test -p kv-index && cargo test -p smg cache_aware`

### Adding an event-driven (chain index) feature

`ChainIndex` answers one question: for a request given as its per-block content hashes, how many leading blocks does each worker hold, where "holds" means the worker stored, at every position up to there, the block on the request's chain. It is run-compressed, lock-free and allocation-free for readers, bounded in memory, and fed only by engine events.

1. The gateway owner is `worker/kv_index_backend.rs` (wraps `ShardedChainIndex`: `intern_worker`, `worker_id`, `apply_stored`, …), driven by `worker/kv_event_monitor.rs` from each gRPC worker's `subscribe_kv_events` stream; it publishes `Metrics::set_kv_index_chain_stats` (`ChainIndexStats`).
2. New indexer state must be covered by `apply_removed`, `apply_cleared` and `remove_worker` (the contract is spelled out by `ReferenceIndexer`), and must stay exact against the reference under `tests/exactness_chain.rs` and `tests/concurrency_chain.rs`.
3. `intern_worker` returns `Result<WorkerId, WorkerIdExhausted>` and must never panic: it runs inside per-worker subscription tasks.
4. The old `--kv-index`, `--kv-indexer-ttl-secs` and `--kv-indexer-max-entries` flags belong to the removed positional indexer; `main.rs` keeps a test pinning how the CLI treats them now — do not resurrect them.

**Verify:** `cargo test -p kv-index && cargo test -p smg kv_event`

## CacheAware integration

The `CacheAware` policy keeps per-model trees in the default `cache_index = tree` mode:

```
DashMap<model_id, Arc<StringTree>>   // text-keyed (no token ids)
DashMap<model_id, Arc<TokenTree>>    // token-keyed (gRPC/ZMQ + pre-tokenized HTTP)
```

Under `--cache-index hash` (`CacheIndexKind::Hash`, `--cache-ttl-secs` default 180, `--cache-boundaries`) `select_worker_hash` uses a TTL'd exact-match placement map keyed on request heads and the radix trees are neither consulted nor populated. Token requests for a model with a populated event monitor bypass the trees too: `select_worker_event_driven` scores block overlap from the chain index.

Tree selection (`select_worker` → `select_worker_with_tokens` / `select_worker_with_text`): one `match_and_insert_with` descent → if `matched/input > cache_threshold` (CLI `--cache-threshold` default 0.3; `CacheAwareConfig::default()` is 0.5), the candidates are `result.matched_tenants` and the pick goes through the **selection policy** in `model_gateway/src/policies/cost/`: once per request the policy gathers each candidate's inputs (prefix overlap, the decayed affinity score tuned by `overlap_decay` / `selection_temperature`, the placement predicted by optimistic accounting with `selection_accounting_ttl_ms`) and runs a pipeline of filters, additive cost scorers and one picker, registered by name in `cost/catalog.rs` (`build`, `default_policy` = `cache-aware-default`) and chosen with the `selection_policy` knob. The balance thresholds (`balance_abs_threshold`, `balance_rel_threshold`, `balance_prefix_margin_tokens`, `balance_uncached_credit`) move a request off a saturated holder — this is why cache-aware answers `balances_load_against_affinity() == true`. Backend KV pressure (`balance_token_usage_threshold`, `overload_token_usage_threshold`, from the workers' `token_usage`) abandons affinity fleet-wide. On a miss the request goes to the least-loaded worker and is inserted for it.

## Key rules

- All state `Send + Sync`; the trees use `DashMap` and `parking_lot::RwLock`; the chain index is lock-free for readers.
- Support both String and Token variants for HTTP/gRPC dual mode.
- Always add eviction **and** a purge path in `remove_tenant_all` — size eviction alone never reclaims a departed worker.
- Chain-index changes stay exact against `ReferenceIndexer`; tree changes keep `matched_tenants` populated.
- Test concurrent access from multiple routing tasks.
- Any change under `crates/kv_index/` triggers `.github/workflows/benchmark-radix-tree.yml` on the PR; `.github/workflows/radix-tree-fuzz.yml` fuzzes the core.

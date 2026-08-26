# Adding KV-Cache Index Features to SMG

Radix trees for cache-aware routing. Tracks which workers have which prompt prefixes cached.

## Core Data Structures

| Tree | Key Type | Used By |
|------|----------|---------|
| `StringTree` | `&str` (characters) | HTTP requests carrying no token ids — prompt text prefix matching |
| `TokenTree` | `&[u32]` (token IDs) | gRPC **and** pre-tokenized HTTP — token sequence prefix matching |

Token ids win over text. `GenerationRequest::routing_tokens()` (`crates/protocols/src/common.rs`, implemented in `generate.rs`: `input_ids` Single, or a Batch's first sequence; empty falls back to text) and the `x-smg-routing-tokens` header hint (`model_gateway/src/routers/common/header_utils.rs:parse_routing_tokens_hint`, which wins over the body) both feed `SelectWorkerInfo { tokens, .. }`; `extract_text_for_routing` is only materialized when there are no tokens.

`StringTree` is a re-export alias of `string_tree::Tree` (`crates/kv_index/src/lib.rs`).

Both implement the `RadixTree` trait (`crates/kv_index/src/lib.rs`): prefix insertion, longest-prefix-match (`prefix_match`/`prefix_match_with_counts`), per-tenant eviction (`evict(tenant, max_units)`), concurrent access (`DashMap` **and** `parking_lot::RwLock`). Match results carry `tenant` **plus** `matched_tenants` — every holder of the deepest matched node, capped at `common.rs:MATCHED_TENANTS_CAP` (8), empty on a miss. `CacheAware` selects from `matched_tenants`, so a new match path that leaves it empty silently disables cache hits.

### Match+insert (the routing hot path)

`cache_aware.rs` does not call `insert_text`/`insert_tokens` then `match_prefix_with_counts` separately (two tree descents). It calls the FUSED `match_and_insert(key, tenant)` / `match_and_insert_with(key, select)` on both `Tree` (`string_tree.rs`) and `TokenTree` (`token_tree.rs`): one descent does longest-prefix-match, then inserts the unmatched remainder. The legacy two-descent `insert_*` + `match_prefix_with_counts` pair still exists. Prefer `match_and_insert*` for any read-then-populate path (call sites: `select_worker_with_tokens` / `select_worker_with_text` in `model_gateway/src/policies/cache_aware.rs`; `select_worker_min_load` uses `match_and_insert` only when the mesh hash index is populated, plain `insert_*` otherwise).

## Steps

### Adding Index Features

1. Implement in `crates/kv_index/src/`
2. Ensure `Send + Sync` (accessed from routing hot path)
3. Support both String and Token variants if applicable. Token-tree code must read the tree's runtime `page_size` (`TokenTree::with_config(page_size, policy)` / `page_size()`), never the `PAGE_SIZE` const — `PAGE_SIZE = 16` is only the `new()`/`with_policy()` default, and `CacheAwarePolicy::new_token_tree` sizes each tree to the backend KV page (`block_size`, CLI `--block-size`). Children are keyed by `TokenPageKey`, a `u64` digest of the edge's first page
4. Add eviction/cleanup mechanism (prevent unbounded memory)
5. Purge per-tenant state on worker removal — extend `remove_tenant_all` (on `Tree`/`TokenTree`, deliberately not on the `RadixTree` trait), which `CacheAwarePolicy::remove_worker_by_url` calls for every model's trees. Size-based eviction never fires for a tenant whose count stops growing, so anything not purged there leaks forever
6. Consider mesh sync if state should be cluster-wide

### PositionalIndexer

Event-driven cache-aware routing at block level — finer granularity than tree-level prefix matching. Tracks which worker has which token blocks cached.

There is no longer a 2048-worker cap (removed): `PositionalIndexer`/`TreeSizes` (`crates/kv_index/src/event_tree.rs`) use a segmented growable array supporting unbounded worker counts (2048 is just the first segment). `intern_worker` returns `Result<WorkerId, WorkerIdExhausted>` — erroring only on u32 id-space exhaustion — and must NEVER panic, because it runs inside per-worker subscription tasks (a panic would silently stop KV event indexing for that worker). KV subscription failures are now surfaced rather than swallowed.

Bounding: the indexer is unbounded by default. `PositionalIndexer::prune(ttl_secs, max_entries) -> PruneStats { scanned, evicted_ttl, evicted_capacity, remaining }` runs a last-touch TTL pass plus a capacity pass that evicts oldest-touched entries down to 90% of the ceiling; `None`/`Some(0)` disables each pass. Driven by `KvEventMonitor::start_prune_task` (`model_gateway/src/worker/kv_event_monitor.rs`) from `kv_indexer_ttl_secs` / `kv_indexer_max_entries` (CLI `--kv-indexer-ttl-secs`, `--kv-indexer-max-entries`; unset or 0 = off). New indexer state must be covered by `prune`, `remove_worker` and `apply_cleared`.

## CacheAware Integration

The `CacheAware` routing policy maintains per-model trees:
```
DashMap<model_id, Arc<StringTree>>   // text-keyed (no token ids)
DashMap<model_id, Arc<TokenTree>>    // token-keyed (gRPC + pre-tokenized HTTP)
```

Only in the default `cache_index = tree` mode. Under `--cache-index hash` (`CacheIndexKind::Hash`, `--cache-ttl-secs` default 180, `--cache-boundaries`) `select_worker_hash` uses a TTL'd exact-match placement map keyed on request heads and the radix trees are **neither consulted nor populated** — tree features are invisible there, and untokenized requests stay load-balanced.

Token requests also bypass the trees when the model has a populated `PositionalIndexer`: `select_worker` checks `has_event_indexer` (indexer present, `current_size() > 0`) before the tree paths and routes them to `select_worker_event_driven`, which scores block overlap and neither consults nor populates the token tree.

Tree selection (`select_worker` → `select_worker_with_tokens` / `select_worker_with_text`): one `match_and_insert_with` descent → if `matched/input > cache_threshold` (CLI `--cache-threshold` default 0.3; `CacheAwareConfig::default()` is 0.5), `select_matched_candidate` pressure-selects among `result.matched_tenants` (least-loaded holder by default; `overlap_decay` / `selection_temperature` tune it), then `gate_selected_candidate` spills that pick to the min-load worker when its load exceeds **both** `avg_load * balance_rel_threshold` **and** `avg_load + balance_abs_threshold`, inserting the spill target as a new tenant → on a miss, route to the least-loaded worker and insert for it. Backend KV pressure (`is_kv_imbalanced`, from `token_usage`) abandons affinity fleet-wide for `select_worker_min_load`. There is no prefix-length weighting.

## Eviction

Size-based, not time-based. Every `eviction_interval_secs` (`CacheAwareConfig`, CLI `--eviction-interval`, default 120) a `PeriodicTask` calls `evict_tenant_by_size(max_tree_size)` on every model's string and token tree. `max_tree_size` (CLI `--max-tree-size`) is a budget **shared by all tenants of one tree**, not per-tenant: eviction returns immediately unless the tree-wide total (`total_char_size()` / `total_token_size()`) exceeds it, then removes leaves in LRU order across all tenants until it is back under budget. The trees have no access-time window — TTL exists only for the `PositionalIndexer` (`kv_indexer_ttl_secs`) and the hash placement index (`cache_ttl_secs`).

## Key Rules

- All state must be `Send + Sync` — the trees use both `DashMap` and `parking_lot::RwLock`
- Support both String and Token variants for HTTP/gRPC dual mode
- Always add eviction (unbounded trees cause OOM) **and** a purge path in `remove_tenant_all` — size eviction alone never reclaims a departed worker
- Test concurrent access from multiple routing tasks
- Any change under `crates/kv_index/` (tests excluded) triggers `.github/workflows/benchmark-radix-tree.yml` on the PR; sanity-check locally with `cargo bench --bench radix_tree_benchmark -- benchmark_summary` (trees) or `cargo bench -p kv-index --bench throughput_bench` (PositionalIndexer)

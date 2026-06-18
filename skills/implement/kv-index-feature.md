# Adding KV-Cache Index Features to SMG

Radix trees for cache-aware routing. Tracks which workers have which prompt prefixes cached.

## Core Data Structures

| Tree | Key Type | Used By |
|------|----------|---------|
| `StringTree` | `&str` (characters) | HTTP routing — prompt text prefix matching |
| `TokenTree` | `&[u32]` (token IDs) | gRPC routing — token sequence prefix matching |

`StringTree` is a re-export alias of `string_tree::Tree` (`crates/kv_index/src/lib.rs`).

Both implement the `RadixTree` trait (`crates/kv_index/src/lib.rs`): prefix insertion, longest-prefix-match (`prefix_match`/`prefix_match_with_counts`), per-tenant eviction (`evict(tenant, max_units)`), concurrent access (`DashMap` **and** `parking_lot::RwLock`).

### Match+insert (the routing hot path)

`cache_aware.rs` does not call `insert_text`/`insert_tokens` then `match_prefix_with_counts` separately (two tree descents). It calls the FUSED `match_and_insert(key, tenant)` / `match_and_insert_with(key, select)` on both `Tree` (`string_tree.rs`) and `TokenTree` (`token_tree.rs`): one descent does longest-prefix-match, then inserts the unmatched remainder. The legacy two-descent `insert_*` + `match_prefix_with_counts` pair still exists. Prefer `match_and_insert*` for any read-then-populate path (see `match_and_insert` in `model_gateway/src/policies/cache_aware.rs`).

## Steps

### Adding Index Features

1. Implement in `crates/kv_index/src/`
2. Ensure `Send + Sync` (accessed from routing hot path)
3. Support both String and Token variants if applicable
4. Add eviction/cleanup mechanism (prevent unbounded memory)
5. Consider mesh sync if state should be cluster-wide

### PositionalIndexer

Event-driven cache-aware routing at block level — finer granularity than tree-level prefix matching. Tracks which worker has which token blocks cached.

There is no longer a 2048-worker cap (removed): `PositionalIndexer`/`TreeSizes` (`crates/kv_index/src/event_tree.rs`) use a segmented growable array supporting unbounded worker counts (2048 is just the first segment). `intern_worker` returns `Result<WorkerId, WorkerIdExhausted>` — erroring only on u32 id-space exhaustion — and must NEVER panic, because it runs inside per-worker subscription tasks (a panic would silently stop KV event indexing for that worker). KV subscription failures are now surfaced rather than swallowed.

## CacheAware Integration

The `CacheAware` routing policy maintains per-model trees:
```
DashMap<model_id, Arc<StringTree>>   // HTTP
DashMap<model_id, Arc<TokenTree>>    // gRPC
```

Selection: longest-prefix-match → prefer cached worker (weighted by prefix length) → fall back to least-loaded.

## Eviction

Configurable interval (`cache_aware.eviction_interval_secs`). Entries not accessed within window are pruned via LRU.

## Key Rules

- All state must be `Send + Sync` — the trees use both `DashMap` and `parking_lot::RwLock`
- Support both String and Token variants for HTTP/gRPC dual mode
- Always add eviction — unbounded trees cause OOM
- Test concurrent access from multiple routing tasks

---
recipe: mesh-feature
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/mesh/src/
  - model_gateway/src/mesh/
exemplars:
  - fad0f553   # a new cache-aware knob lands in mesh/wiring.rs's PolicyConfig literal (no CRDT value since 2026-08-20)
  - 6bd1b773   # same route: balance_prefix_margin_tokens / balance_uncached_credit reach mesh/wiring.rs
  - 0e805235   # --mesh-tls-ca-cert/--mesh-tls-cert/--mesh-tls-key: main.rs, server/posture.rs, server.rs, bindings
---

# Add a mesh-replicated value

Crate `smg-mesh` (`crates/mesh/`): SWIM-style gossip plus CRDT replication of opaque bytes keyed by prefix (`worker:`, `policy:`, `rl:`, `config:`); the transport never interprets a value. Optional: it only matters with several gateway nodes.
Gossip: `service.rs` (`MeshServerBuilder`, `MeshServerHandler`, `ClusterState = Arc<RwLock<BTreeMap<String, NodeState>>>`), `gossip_controller.rs` / `gossip_service.rs` (per-round send + ack), `partition.rs` (`PartitionDetector`: quorum, split-brain), `mtls.rs` (`MTLSManager`), `proto/gossip.proto` (`NodeStatus`, `StreamMessage`, `CrdtBatch` / `CrdtAck`; `NodeStatus` is `INIT → ALIVE → SUSPECTED → DOWN` plus `LEAVING`, not a Joining/Healthy/Suspect/Dead machine).
KV: `kv.rs` (`MeshKV`, `CrdtNamespace`, `StreamNamespace`, `Subscription`, `DrainHandle`), `crdt_kv/` (`CrdtOrMap` router, `OperationLog`, `MergeStrategy`, `CrdtWatermark`, `ReplicaId`; engines `engine/lww.rs`, `engine/rate_limit.rs`), `transport/` (`sync_stream.rs`, `crdt_batch.rs`, `chunk_assembler.rs`, `chunking.rs`, `limits.rs`), `types.rs` (`WorkerState`, the opaque value type).
The gateway owns the adapters: `model_gateway/src/mesh/wiring.rs` (`MeshAdapters::start`, the single composition root), `adapters/` (`worker_sync.rs`, `rate_limit_sync.rs`, `tree_sync.rs`), `discovery/` (router-peer discovery, `start_mesh_discovery`).

Not this recipe:
- Ephemeral or lossy traffic (tenant deltas, tree repair) belongs in `StreamNamespace`: dropped under backpressure, not retried.
- A new `MergeStrategy` is rare, only when neither `LastWriterWins` nor `EpochMaxWins` fits (step 6).

## Inputs

| Input | Example | Used in |
|---|---|---|
| Prefix | `<prefix>:` (every key must start with it) | steps 1-3 |
| Strategy | `LastWriterWins` (higher `(timestamp, replica_id)` wins; `worker:`, `policy:`, `config:`) or `EpochMaxWins` (`rl:` counters) | step 1 |
| Payload | opaque bytes serialized at the edge (`bincode` for `types.rs::WorkerState`); `EpochMaxWins` needs exactly 16 bytes `(epoch u64-be, count i64-be)` from `smg_mesh::encode_epoch_count(epoch, count)` | step 2 |
| Owner | the adapter in `model_gateway/src/mesh/adapters/` that writes and subscribes | steps 2-4 |

## Steps

### 1. Configure the prefix once

File: `model_gateway/src/mesh/wiring.rs` — Do: in `MeshAdapters::start(mesh_kv, node_name, worker_registry, cluster_state, policy_registry)` add `let ns = mesh_kv.configure_crdt_prefix("<prefix>:", MergeStrategy::LastWriterWins);` beside `worker:` and `rl:` (the shared `MeshKV` comes from `handle.mesh_kv()`); a stream uses `configure_stream_prefix` with `StreamConfig { max_buffer_bytes, routing }`. `config:` is auto-registered in `MeshKV::new`: reach it through `mesh_kv.configs()`, never re-configure it.
Verify: `cargo test -p smg mesh::wiring` → `start_panics_on_second_call` still passes.
Trap: configuring a prefix twice panics (fail-closed), while an engine registered after gossip starts merges its first inbound batch under the default strategy without a word; register where `start` does, before any adapter loop and before gossip.

### 2. Read and write through the namespace

File: `model_gateway/src/mesh/adapters/<name>_sync.rs` — Do: hold the `CrdtNamespace` handle (`kv.rs`): `ns.put(key, bytes)` (opaque), `ns.get(key)`, `ns.delete(key)` (tombstone). React to remote changes with `ns.subscribe(sub_prefix)` → `Subscription { receiver }`; events are `(key, Option<Vec<Bytes>>)`, `None` = delete, delivered for local writes and remote merges with the canonical post-merge value. `EpochMaxWins` payloads: `encode_epoch_count` / `decode_epoch_count` (`adapters/rate_limit_sync.rs`).
Verify: `cargo test -p smg-mesh crdt_integration` → the LWW `worker:` and EpochMaxWins `rl:` scenarios in `crates/mesh/src/tests/crdt_integration.rs` are the model.
Trap: app code that reaches `MeshKV` or `CrdtOrMap` directly compiles; only the `CrdtNamespace` / `StreamNamespace` handles enforce the prefix.

### 3. Start the adapter before gossip

File: `model_gateway/src/mesh/wiring.rs` — Do: build the adapter in `MeshAdapters::start` and start its inbound loop there, as `WorkerSyncAdapter::start` / `RateLimitSyncAdapter::start` (`adapters/worker_sync.rs`, `adapters/rate_limit_sync.rs`) and `TreeSyncAdapter` (`adapters/tree_sync.rs`, built over a `ClusterState`-backed `PeerList` and a `PolicyRegistry`-backed `TreeHandle`: `td:` Broadcast tenant deltas, `tree:req:` / `tree:page:` Targeted repair, a stream not a CRDT) do, and only then `policy_registry.set_mesh_tree_sync(Some(tree))`, which propagates to every existing and future `CacheAwarePolicy` and flips `populate_hash_index` (`None` detaches). Replication itself needs no wiring: each round `collect_round_batch()` snapshots the op-log, `transport/crdt_batch.rs` (`build_crdt_batches`) frames it under `MAX_STREAM_CHUNK_BYTES` (`transport/limits.rs`: `MAX_MESSAGE_SIZE` minus a 64 KiB envelope margin), and the peer's `dispatch_crdt_batch` merges through `MeshKV::merge_crdt_ops`, idempotent by op-id.
Verify: `cargo test -p smg mesh::` → `start_wires_worker_inbound_end_to_end` passes.
Trap: a `td:` delta arriving before its subscription is dropped silently; the order inside `start` is the only guard.

### 4. Publish outbound state through one gate

File: `model_gateway/src/mesh/adapters/worker_sync.rs` — Do: model an outbound loop on `WorkerSyncAdapter::start`: it consumes the registry's `WorkerEvent` stream, publishes each locally owned worker as `worker:<id>` under single-writer ownership, tombstones on `Removed`, and on broadcast lag re-publishes every local worker and tombstones any it published that no longer exists. One `is_publishable` gate covers every outbound path: mesh-imported workers (registration origin) and `ConnectionMode::Zmq` workers (host-local `ipc://`) are never published; a `Replaced` event that turns a published worker non-publishable tombstones it.
Verify: `cargo test -p smg worker_sync`

### 5. Expose a mesh flag

File: `model_gateway/src/main.rs` — Do: as 0e805235 did for `--mesh-tls-ca-cert` / `--mesh-tls-cert` / `--mesh-tls-key` (`requires_all`; folded into `MeshServerConfig` by `build_mesh_server_config` / `mesh_mtls_config`), then `model_gateway/src/server/posture.rs` (`open_posture_warning` names a plaintext mesh), `model_gateway/src/server.rs` (hands `mesh_server_config` to the posture; `warn_if_private_key_is_shared`) and the bindings: `bindings/python/src/lib.rs`, `bindings/python/src/smg/router_args.py`, `bindings/python/tests/test_arg_parser.py` (`test_parse_mesh_tls_args`). See @config-plumbing.md and @bindings-update.md.
Verify: `cargo test -p smg mesh_tls && make python-dev`

### 6. Add a merge strategy (rare)

File: `crates/mesh/src/crdt_kv/merge_strategy.rs` — Do: add the `MergeStrategy` variant; implement `NamespaceCrdtEngine` (`crdt_kv/engine/mod.rs`: byte-oriented `put_local` / `delete_local` / `get` / `contains_key` / `keys` / `len` / `apply_remote_ops` / `export_ops` / `gc_tombstones` / `generation` / `op_generation`), owning your live state, per-key locks, an `OpLogKeeper` (`engine/op_log.rs`, over `OperationLog`) and the shared `Arc<LamportClock>`, modelled on `engine/lww.rs` (simplest) or `engine/rate_limit.rs` (typed state); wire the variant in `CrdtOrMap::register_merge_strategy` (`crdt_kv/crdt.rs`). Strategy logic stays in the engine; the router is strategy-agnostic.
Verify: `cargo test -p smg-mesh`
Trap: `apply_remote_ops` must emit a `CrdtChange` only when `get` actually changes, or subscribers get spurious events on idempotent re-applies. Compaction is `OperationLog::compact_by_key` with your per-key fold; `truncate_oldest_over_threshold` (past `AUTO_COMPACT_THRESHOLD`, 10_000) is the local-write path only — on the remote-merge path it sheds remotely learned keys.

### 7. Gate

Run `smg:contribute`.

## Rules

- The send watermark is per peer, per key (`crdt_kv/watermark.rs`, `CrdtWatermark`): the sender filters the op-log with `acked.allows(op)` ((ts, replica_id) above the ack, op-id tie-break) before batching (`gossip_controller.rs` / `gossip_service.rs` send loops); the receiver answers `CrdtWatermark::from_ops` of what it merged as a `CrdtAck` (`watermark_to_crdt_ack`); the sender advances with `merge_max`. Un-acked keys are resent next round, so one lost op delays one key, not a replica.
- Op-id `(replica_id, timestamp)` must be globally unique per node: every engine shares one `LamportClock`.
- A knob on a `PolicyConfig` variant reaches `mesh/wiring.rs` too: fad0f553 and 6bd1b773 edited its test module's `CacheAware` literal, which at HEAD is the `PolicyConfig::cache_aware(...)` constructor.
- `cargo test -p smg-mesh` covers the crate; the adapters' tests run under `cargo test -p smg`.
- A mesh flag or wiring change carries an integration test under `model_gateway/tests/` (the mTLS flag commit 0e805235 added one); extend the group that owns the surface rather than a new top-level file.

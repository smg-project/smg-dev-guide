# Checklist: routing, dispatch and the hot path

- [ ] Works for HTTP, gRPC and ZMQ (`SelectWorkerInfo`; `ConnectionMode` in `crates/protocols/src/worker.rs`; `BackendClient` in `routers/grpc/backend_client.rs`).
- [ ] State is `Send + Sync` (DashMap, atomics; no bare `Mutex` on the hot path); no `.unwrap()` on worker slices.
- [ ] Eligibility via `get_healthy_worker_indices` / `w.is_available()` (health + circuit breaker + overload veto); ring policies use `is_healthy_and_eligible()`.
- [ ] Load-aware policy: `set_load_receiver`, `needs_backend_loads() == true`, `remove_worker`, `reconcile_in_flight`.
- [ ] New dispatch path sheds (`overload::shed_if_all_overloaded`, `shed_if_worker_overloaded`) and marks terminal responses `retry::mark_non_retryable`.
- [ ] Dispatch memory: bodies by value; nothing outlives `RequestLease::release_dispatch()`; sized bodies (`attach_sized_body`, `serialize_json_sized`, `read_worker_body_capped`); no per-token `clone()` in `routers/grpc/regular/streaming.rs`.
- [ ] A tunable on a fielded `PolicyConfig` variant updates every full literal (`routers/factory.rs`, `app_context.rs`, `mesh/wiring.rs`, the test files).
- [ ] KV index: chain-index changes stay exact against `ReferenceIndexer` (`crates/kv_index/tests/exactness_chain.rs`); tree changes keep `matched_tenants` populated and a purge path in `remove_tenant_all`.
- [ ] Multimodal: a spec ships its golden test under `crates/multimodal/tests/preprocess/` and its row in the capability matrix (`routers/grpc/multimodal/capability.rs`).

| Anti-pattern | Consequence | Look for |
|---|---|---|
| Tests with only HTTP workers | gRPC/ZMQ regress | all `ConnectionMode::Http` in router tests |
| `RwLock` or `Mutex` on the hot path | contention | locks in policy structs |
| Eligibility re-derived | routes to overload-vetoed workers | `is_healthy() && circuit_breaker_can_execute()` |
| Overload computed per request | extra fleet walk per request | anything but reading `Worker::is_overloaded()` (latched in `worker/overload.rs`) |
| Request memory held past the lease | memory doubles under load | clones out of `RequestLease` into streaming tasks |
| `create_from_config` arm without `create_by_name` | a worker `policy_hint` silently falls back | `policies/factory.rs` |
| Load-aware policy without `remove_worker` / `reconcile_in_flight` | tallies grow under churn | overrides missing in the policy file |

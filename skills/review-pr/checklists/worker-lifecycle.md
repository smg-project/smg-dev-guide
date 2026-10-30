# Checklist: worker lifecycle and the label pipeline

- [ ] New metadata flows as a label (provider → `DiscoveredWorker` labels → `create_worker.rs` → `ModelCard`), not a parallel `_override` field on `WorkerSpec`.
- [ ] Model-id resolution chain not bypassed; no `ModelCard` mutation after `build_model_card`.
- [ ] A discovery change works for every provider sharing the reconciler (`kubernetes.rs`, `consul.rs`, `file.rs`, `slurm.rs`) or is scoped to one on purpose; `service_discovery/reconciler.rs` stays provider-neutral.
- [ ] A new provider follows the whole shape (`DiscoveryKind`, `RuntimeDiscoveryConfig::from_config`, config variant + validation, recorded fixtures under `service_discovery/testdata/`, launcher mapping, parity and startup tests, an e2e package, the `e2e-discovery.yml` job).
- [ ] A new worker label is read in `worker/builder.rs` and re-applied by `workflow/steps/local/update_worker_properties.rs`.
- [ ] ZMQ: the handshake is never awaited on a request or probe path (`spawn_zmq_connect_driver` + `WorkerConnected`); misconfiguration is rejected in `create_worker.rs`; `update_worker_properties` preserves the backend client.
- [ ] Workflow engine (`crates/workflow`): a step returning `StepResult::Skip` does not persist its context writes; completion signals go out inside the tracker lock.

| Anti-pattern | Consequence | Look for |
|---|---|---|
| `_override` field on `WorkerSpec` | parallel data path around the label pipeline | new fields in `crates/protocols/src/worker.rs` |
| `ModelCard` mutated after `build_model_card()` | stale routing data, races | field writes after the build in `workflow/steps/local/create_worker.rs` |
| Provider-specific checks in the reconciler | breaks the other providers | provider names in `service_discovery/reconciler.rs` |
| Handshake awaited inline | request or probe blocks for the connect timeout | `connect_handshake` reached from a request path |

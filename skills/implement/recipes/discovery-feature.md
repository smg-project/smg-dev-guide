---
recipe: discovery-feature
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - model_gateway/src/service_discovery/
  - model_gateway/src/workflow/steps/local/create_worker.rs
  - model_gateway/src/workflow/steps/local/discover_metadata.rs
  - model_gateway/tests/discovery/
exemplars: []   # no label-pipeline feature since 2026-08-20; provider additions are in discovery-provider.md
---

# Flow new worker metadata through discovery

Providers under `model_gateway/src/service_discovery/` (`kubernetes.rs`, `consul.rs`, `file.rs`, `slurm.rs`) emit `DiscoveredWorker`s (`mod.rs`, with labels and a `fingerprint()`); one reconciler (`reconciler.rs`: `DesiredState::from_workers`, `compute_actions`, `reconcile`) diffs them against the workers it owns (labels `smg.ai/discovery-provider`, `smg.ai/discovery-id`, `smg.ai/discovery-spec-hash`) into `Job::AddWorker` / `Job::RemoveWorker`. Downstream, `DiscoverMetadataStep` probes the backend and `CreateLocalWorkerStep` merges config labels over probe labels, resolves the model id and builds the `ModelCard`. New metadata is a label; nothing else.

Not this recipe: a new provider (@discovery-provider.md); a discovery config knob end to end (@config-plumbing.md).

## Inputs

| Input | Example | Used in |
|---|---|---|
| source | pod annotation, Consul meta, manifest field | step 2 |
| label key | `my_key` | steps 2–3 |
| consumer | `create_worker.rs`, a policy, a router | step 3 |
| config override | `WorkerSpec.labels` from config wins over the probe | step 3 |

## Steps

### 1. Config

File: `model_gateway/src/config/types.rs` — Do: a `DiscoveryConfig` field per @config-plumbing.md, mirrored on the runtime struct the provider reads (`ServiceDiscoveryConfig` in `service_discovery/kubernetes.rs` for K8s, the provider's own config otherwise) and threaded through `RuntimeDiscoveryConfig::from_config` (`service_discovery/runtime.rs`). Typed enum, not `String`.
Verify: `cargo check -p smg`
Trap: `main.rs::to_server_config` builds the K8s `ServiceDiscoveryConfig` only; a Consul, file or Slurm knob goes through `RuntimeDiscoveryConfig::from_config`.

### 2. Stamp the label in the provider

File: `model_gateway/src/service_discovery/kubernetes.rs` (or the provider you extend) — Do: read the value in `PodInfo::from_pod(pod, Some(config))` into a `PodInfo` field; in `compute_desired_state()` insert it into the `DiscoveredWorker`'s labels (`labels.insert("my_key".to_string(), value)`). The reconciler needs nothing: `DesiredState::from_workers` and `compute_actions` compare `fingerprint()`s, so a changed label re-registers the worker on the next pass.
Verify: `cargo test -p smg service_discovery`
Trap: a provider-specific check in `reconciler.rs` breaks the other providers; the `smg.ai/discovery-` prefix is the reconciler's.

### 3. Consume

File: `model_gateway/src/workflow/steps/local/create_worker.rs` — Do: read the merged labels in `CreateLocalWorkerStep` (`labels.get("my_key")`); the `served_model_name` / `model_id` path is the template.
Verify: `cargo check -p smg`
Trap: a field on `WorkerSpec` bypasses the pipeline; a `ModelCard` write after `build_model_card()` races with routing.

### 4. Bindings

@bindings-update.md for the config field.

### 5. Tests

File: `model_gateway/src/service_discovery/kubernetes.rs` `mod tests` — Do: a `test_compute_desired_state_*` case that the label is stamped (multi-port pods, IPv6 brackets, unready and terminating pods excluded are the existing ones). File: `model_gateway/tests/discovery/k8s_discovery_test.rs` — Do: a case through the scripted fake API server (`start_service_discovery_with_client`) asserting the label reaches the model card; config override wins over the probe; missing metadata degrades gracefully.
Verify: `cargo test -p smg service_discovery && cargo test -p smg --test discovery_tests`; real cluster `SMG_KIND_E2E=1 pytest e2e_test/discovery/kind -m kind`

### 6. Gate

Run `smg:contribute`.

## Rules

- Discovery is level-triggered (a reconcile pass, no per-event handler); make a change idempotent across passes.
- `PodType` (`kubernetes.rs`): `Regular` (`--selector`), `Prefill`, `Decode`, `Encode`; `Roles::of(&RoutingMode)` (`mod.rs`) says which worker types a mode admits. Mesh peers come from `--router-selector`, not a `PodType`.
- gRPC backend detection lives in `workflow/steps/local/detect_backend.rs`; an unidentified OpenAI-compatible HTTP backend registers as `generic`.
- `--model-alias alias=canonical` adds client-facing aliases; `resolve_model_id()` ignores them.

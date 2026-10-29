---
recipe: discovery-feature
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - model_gateway/src/service_discovery/
  - model_gateway/src/workflow/steps/local/create_worker.rs
  - model_gateway/src/workflow/steps/local/discover_metadata.rs
  - model_gateway/tests/discovery/
  - e2e_test/discovery/
---

# Adding a Discovery Feature to SMG

All worker metadata must flow through the label pipeline. Never add `_override` fields to `WorkerSpec`.

## The shape

Service discovery is a set of **providers** behind one shared **reconciler**, all under `model_gateway/src/service_discovery/`:

| File | Role |
|---|---|
| `kubernetes.rs` | pods → workers: `ServiceDiscoveryConfig`, `PodType` (`Encode`, `Prefill`, `Decode`, `Regular`), `PodInfo::from_pod` / `should_include` / `is_healthy`, `compute_desired_state`, `start_service_discovery_with_client`, `ModelIdSource` |
| `consul.rs` | the healthy instances of one Consul service |
| `file.rs` | the workers listed in a JSON manifest on disk |
| `slurm.rs` | a worker on every node of each running Slurm job |
| `mod.rs` | the provider-neutral vocabulary: `DiscoveredWorker` (what a provider emits — endpoint, type, labels — with a `fingerprint()`), `DiscoveryKind`, `Roles` (which `WorkerType`s a `RoutingMode` admits, and the default type), `endpoint_at` |
| `reconciler.rs` | `DesiredState::from_workers`, `compute_actions` (diff against the `OwnedWorker`s the reconciler stamped with `smg.ai/discovery-provider`, `smg.ai/discovery-id`, `smg.ai/discovery-spec-hash`), `reconcile` → `Job::AddWorker` / `Job::RemoveWorker` |
| `snapshot.rs` | last-good snapshots and skip logging when a provider read fails |
| `runtime.rs` | `RuntimeDiscoveryConfig::from_config` and `start_service_discovery`: which provider the config enables |
| `provider.rs` | the provider contract the reconciler drives |

Discovery is level-triggered: a reconcile pass over the provider's current view, not per-event handling (there is no `handle_pod_event`). The reconciler only removes workers carrying its own `smg.ai/discovery-*` labels, so it never touches workers registered another way.

## The label pipeline (downstream of discovery)

```
provider emits DiscoveredWorker { labels, .. }              service_discovery/<provider>.rs
    ↓ reconcile → Job::AddWorker { spec }                    reconciler.rs, workflow/job_queue.rs
DiscoverMetadataStep: backend probe → discovered labels     workflow/steps/local/discover_metadata.rs
    ↓
CreateLocalWorkerStep: merge config.labels over probe labels (config wins)   steps/local/create_worker.rs
    ↓ extract special keys (kv_connector, kv_role, kv_engine_id)
    ↓ resolve_model_id(): config.models.primary() → labels["served_model_name"]
    ↓                      → labels["model_id"] → labels["model_path"] → UNKNOWN_MODEL_ID
    build_model_card(model_id, config, &labels, &router_config.model_aliases) → ModelCard
```

**To inject new metadata:** put it in the `DiscoveredWorker`'s labels. The pipeline handles the rest. `--model-alias alias=canonical` attaches client-facing aliases to discovered cards; `resolve_model_id()` deliberately ignores them. gRPC backend detection (sglang/vllm/trtllm/tokenspeed/mlx) lives in `workflow/steps/local/detect_backend.rs`; an OpenAI-compatible HTTP backend matching no fingerprint registers as `generic`.

## Steps

### Step 1: Add the config field

Follow @config-plumbing.md for `DiscoveryConfig` (`config/types.rs`), then mirror the field on the runtime struct the provider reads — for K8s `ServiceDiscoveryConfig` in `service_discovery/kubernetes.rs` (plus its `Default` impl; `main.rs::to_server_config` builds it from `router_config.discovery`), for Consul/file/Slurm the provider's own config — and thread it through `RuntimeDiscoveryConfig::from_config` (`service_discovery/runtime.rs`). Use a typed enum, not a `String`.

**Verify:** `cargo check -p smg`

### Step 2: Read it in the provider and stamp a label

**File:** `model_gateway/src/service_discovery/kubernetes.rs` (or the provider you extend)

1. `PodInfo::from_pod(pod, Some(config))` — read the pod label/annotation into a new `PodInfo` field (it also reads the `smg.ai/worker-ports` multi-port annotation).
2. `compute_desired_state()` — one `DiscoveredWorker` per pod data port; insert your value into its labels: `labels.insert("my_key".to_string(), value)`.
3. Nothing in `reconciler.rs`: `DesiredState::from_workers` and `compute_actions` are provider-neutral and compare `fingerprint()`s, so a changed label re-registers the worker on the next pass.

Use the existing `served_model_name` / `model_id` label path as the template. The `smg.ai/discovery-` prefix is reserved for the reconciler.

**Verify:** `cargo test -p smg service_discovery`

**Anti-pattern:** a provider-specific check in `reconciler.rs` (it breaks Consul/file/Slurm), a new field on `WorkerSpec`, or a label under the reserved prefix.

### Step 3: Consume it in worker creation (if needed)

**File:** `model_gateway/src/workflow/steps/local/create_worker.rs` — read from the merged labels in `CreateLocalWorkerStep`:

```rust
let my_value = labels.get("my_key");
```

**Anti-pattern:** a `WorkerSpec` field (bypasses the pipeline, creates a parallel data path); mutating `ModelCard` after `build_model_card()` (races, stale routing data).

### Step 4: Bindings

Follow @bindings-update.md for the new config field.

### Step 5: Tests

- Unit: `compute_desired_state` stamps the label — copy the `test_compute_desired_state_*` tests in `kubernetes.rs` (multi-port pods, IPv6 brackets, unready and terminating pods excluded, PD prefill bootstrap alignment).
- Reconciler: `compute_actions` adds, updates and removes on label changes — tests in `reconciler.rs`.
- Integration: `model_gateway/tests/discovery/k8s_discovery_test.rs` (a scripted fake K8s API server driving the real reconciler, job queue and registry through `start_service_discovery_with_client`; `file_discovery_test.rs` sits beside it): `cargo test -p smg --test discovery_tests`.
- Config label override wins over the discovered label; missing metadata → graceful default.
- Real cluster: `SMG_KIND_E2E=1 pytest e2e_test/discovery/kind -m kind` (needs kind and kubectl); the Consul, file and Slurm suites live next to it under `e2e_test/discovery/`; CI runs them from `.github/workflows/e2e-discovery.yml`.

**Verify:** `cargo test -p smg service_discovery && cargo test -p smg --test discovery_tests`

## Pod types and roles

`PodType` (`kubernetes.rs`) has four variants, each selected by a label-selector flag:

| `PodType` | Selector flag | Purpose |
|---|---|---|
| `Regular` | `--selector` | standard workers |
| `Prefill` | `--prefill-selector` | PD disaggregation: prefill |
| `Decode` | `--decode-selector` | PD disaggregation: decode |
| `Encode` | `--encode-selector` | EPD disaggregation: encode |

`Roles::of(&RoutingMode)` (`mod.rs`) says which worker types a routing mode admits (`allows`) and its default type (`default_type`), so a Regular-mode gateway rejects prefill pods loudly instead of routing to them. Mesh HA peers are found through the separate `--router-selector`; a router is not a `PodType`.

## Key rules

- Labels in, `ModelCard` out. No parallel fields, no post-hoc card mutation.
- Provider logic stays in the provider file; the reconciler is shared.
- Discovery is a reconcile loop: make a change idempotent across passes (the `fingerprint()` decides whether a worker is re-registered).
- Every provider that shares the reconciler must still work after your change — run the file-discovery test even for a K8s feature.

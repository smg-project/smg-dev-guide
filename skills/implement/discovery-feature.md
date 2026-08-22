# Adding a Discovery Feature to SMG

All metadata must flow through the label pipeline. Never add `_override` fields to WorkerSpec.

## The Label Pipeline

```
DiscoverMetadataStep: Backend probe → discovered_labels HashMap
    ↓
CreateLocalWorkerStep: Merge with config.labels (config wins)
    ↓ Extract special keys (kv_connector, kv_role, kv_engine_id)
    ↓ Resolve model_id (`resolve_model_id()` priority chain):
    ↓   1. config.models.primary()
    ↓   2. labels["served_model_name"]
    ↓   3. labels["model_id"]
    ↓   4. labels["model_path"]
    ↓   5. UNKNOWN_MODEL_ID
    ↓
    build_model_card(model_id, config, &labels, &router_config.model_aliases)
        → ModelCard with full metadata
```

**To inject new metadata:** Add it as a label. The pipeline handles the rest.

Note: `--model-alias alias=canonical` attaches client-facing aliases to discovered cards. Aliases never change the canonical id — `resolve_model_id()` deliberately ignores them.

Note: gRPC backend detection (sglang/vllm/trtllm/tokenspeed/mlx) lives in `workflow/steps/local/detect_backend.rs`; an OpenAI-compatible HTTP backend matching no fingerprint registers as `generic` rather than being rejected.

## Steps

### Step 1: Add config field

Follow @config-plumbing.md for `DiscoveryConfig` (`config/types.rs`), then mirror the field on the runtime `ServiceDiscoveryConfig` (`service_discovery.rs`, plus its `Default` impl) — these are two distinct structs, and `main.rs` `to_server_config` builds the second one. `worker_ports_annotation` shows all four sites.

Use typed enum, not String:
```rust
pub my_source: Option<MySourceType>,  // NOT Option<String>
```

### Step 2: Extract in discovery and stamp as a label

**File:** `model_gateway/src/service_discovery.rs`

Discovery is a level-triggered reconcile, not per-event handling (`handle_pod_event()` no longer exists):

```
PodInfo::from_pod(pod, Some(config))   per-pod parse; also reads the
    ↓                                  worker_ports_annotation multi-port list
compute_desired_state()                one DesiredWorker per pod data port
    ↓
compute_actions()                      diff vs k8s_owned_workers()
    ↓
build_worker_spec() → Job::AddWorker { registration_mode: Upsert } / Job::RemoveWorker
```

Thread the value through that chain:

1. `PodInfo::from_pod()` — read the pod label/annotation into a new `PodInfo` field.
2. `compute_desired_state()` — copy it onto `DesiredWorker`.
3. `build_worker_spec()` — inject as a label; the pipeline merges automatically:
```rust
spec.labels.insert("my_key".to_string(), desired.my_value.clone());
```

Use the existing `model_id_override` → `served_model_name` path as the template. `smg.ai/pod-name` / `smg.ai/pod-uid` (`POD_NAME_LABEL` / `POD_UID_LABEL`) are reserved — the reconciler identifies the workers it owns by pod uid.

### Step 3: Consume in worker creation (if needed)

**File:** `model_gateway/src/workflow/steps/local/create_worker.rs`

Read from merged labels in `CreateLocalWorkerStep`:
```rust
let my_value = labels.get("my_key");
```

**Anti-pattern:** Adding a field to `WorkerSpec` struct → bypasses label pipeline, creates parallel data path. Mutating `ModelCard` after `build_model_card()` → race conditions.

### Step 4: Update bindings

Follow @bindings-update.md.

### Step 5: Write tests

- Unit: `build_worker_spec()` stamps the label from `DesiredWorker` — copy `test_build_worker_spec_stamps_ownership_labels` / `test_compute_desired_state_carries_model_id_override` in `service_discovery.rs`
- Integration: add a case to `model_gateway/tests/k8s_discovery_test.rs` — scripted fake K8s API server driving the real reconciler, JobQueue and registry via `start_service_discovery_with_client` (`test-util` feature) — assert the label reaches the model card
- Config label override wins over discovered label
- Missing metadata → graceful default

**Verify:** `cargo test -p smg service_discovery && cargo test -p smg --test k8s_discovery_test`. Real cluster: `SMG_KIND_E2E=1 pytest e2e_test/kind_discovery -m kind` (manual workflow `.github/workflows/e2e-kind-discovery.yml`).

## Pod Types

The `PodType` enum (`service_discovery.rs`) has four variants — `Encode`, `Prefill`, `Decode`, `Regular` — each selected by a label-selector flag:

| `PodType` | Selector Flag | Purpose |
|-----------|--------------|---------|
| Regular | `--selector` | Standard workers |
| Prefill | `--prefill-selector` | PD disaggregation: prefill |
| Decode | `--decode-selector` | PD disaggregation: decode |
| Encode | `--encode-selector` | EPD disaggregation: encode |

Note: **Router is not a `PodType`** — it's a separate `is_router` overlay flag (`--router-selector` marks Mesh HA peer nodes), orthogonal to the compute pod type above.

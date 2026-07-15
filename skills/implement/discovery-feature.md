# Adding a Discovery Feature to SMG

All metadata must flow through the label pipeline. Never add `_override` fields to WorkerSpec.

## The Label Pipeline

```
DiscoverMetadataStep: Backend probe → discovered_labels HashMap
    ↓
CreateLocalWorkerStep: Merge with config.labels (config wins)
    ↓ Extract special keys (kv_connector, kv_role, kv_engine_id)
    ↓ Resolve model_id (priority chain):
    ↓   1. config.models.primary()
    ↓   2. labels["served_model_name"]
    ↓   3. labels["model_id"]
    ↓   4. labels["model_path"]
    ↓   5. UNKNOWN_MODEL_ID
    ↓
    build_model_card() → ModelCard with full metadata
```

**To inject new metadata:** Add it as a label. The pipeline handles the rest.

Note: gRPC backend detection (sglang/vllm/trtllm/tokenspeed/mlx — `tokenspeed` is new) lives in `workflow/steps/local/detect_backend.rs`.

## Steps

### Step 1: Add config field

Follow @config-plumbing.md to add the field to `ServiceDiscoveryConfig`.

Use typed enum, not String:
```rust
pub my_source: Option<MySourceType>,  // NOT Option<String>
```

### Step 2: Use in pod handling

**File:** `model_gateway/src/service_discovery.rs`

Extract from pod metadata in `PodInfo::from_pod()` or `handle_pod_event()`:
```rust
// Inject as label — the pipeline merges automatically
worker_spec.labels.insert("my_key".to_string(), extracted_value);
```

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

- Pod with metadata → label injected → model card reflects it
- Config label override wins over discovered label
- Missing metadata → graceful default

**Verify:** `cargo test`

## Pod Types

The `PodType` enum (`service_discovery.rs`) has four variants — `Encode`, `Prefill`, `Decode`, `Regular` — each selected by a label-selector flag:

| `PodType` | Selector Flag | Purpose |
|-----------|--------------|---------|
| Regular | `--selector` | Standard workers |
| Prefill | `--prefill-selector` | PD disaggregation: prefill |
| Decode | `--decode-selector` | PD disaggregation: decode |
| Encode | `--encode-selector` | EPD disaggregation: encode |

Note: **Router is not a `PodType`** — it's a separate `is_router` overlay flag (`--router-selector` marks Mesh HA peer nodes), orthogonal to the compute pod type above.

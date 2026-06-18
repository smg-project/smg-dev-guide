# Adding a Routing Policy to SMG

A routing policy implements `LoadBalancingPolicy` (`model_gateway/src/policies/mod.rs`): a **synchronous** `Send + Sync + Debug` trait whose `select_worker` returns the **index** of the chosen worker (`Option<usize>`), not the worker itself. Live in `model_gateway/src/policies/`, registered via `PolicyConfig` + `PolicyFactory`, owned at runtime by `PolicyRegistry`.

Note: `dp_min_token.rs` implements a *different* trait, `DPRankLoadPolicy` (selects a DP rank within one worker, not a worker). If you need that, don't follow this recipe.

## Inputs to gather first

| Input | Example | Notes |
|-------|---------|-------|
| `POLICY_NAME` | `my_policy` | Snake case. File name, `name()` return, factory key |
| Struct name | `MyPolicy` | PascalCase + `Policy` suffix |
| State | `AtomicUsize`, `RwLock<HashMap<..>>`, none | Must be `Send + Sync`. Stateless policies are unit structs (see `random.rs`) |
| Routing input | none / `info.tokens` / `info.request_text` / `info.headers` | What drives selection (see Critical Rules) |
| Config params | `load_factor: f64` | If tunable, needs a `PolicyConfig` variant — see @config-plumbing.md |

## Steps

### Step 1: Create the policy file

**File:** `model_gateway/src/policies/{POLICY_NAME}.rs`

Model this on `random.rs` (stateless) or `power_of_two.rs` (cached load state). Required methods: `select_worker`, `name`, `as_any`. Default methods you may override: `on_request_complete`, `needs_request_text`, `update_loads`, `remove_worker`, `reset`. Always filter via the `get_healthy_worker_indices` helper — it applies `is_healthy() && circuit_breaker_can_execute()` per worker.

```rust
use std::sync::Arc;

use super::{get_healthy_worker_indices, LoadBalancingPolicy, SelectWorkerInfo};
use crate::worker::Worker;

#[derive(Debug, Default)]
pub struct MyPolicy;

impl MyPolicy {
    pub fn new() -> Self {
        Self
    }
}

impl LoadBalancingPolicy for MyPolicy {
    fn select_worker(
        &self,
        workers: &[Arc<dyn Worker>],
        _info: &SelectWorkerInfo,
    ) -> Option<usize> {
        let healthy_indices = get_healthy_worker_indices(workers);
        if healthy_indices.is_empty() {
            return None;
        }

        // Return an INDEX into `workers`, never an Arc<dyn Worker>.
        healthy_indices
            .into_iter()
            .min_by_key(|&idx| workers[idx].load())
    }

    fn name(&self) -> &'static str {
        "my_policy"
    }

    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
}
```

**Verify:** `cargo check -p smg`

**Anti-pattern:** Adding `#[async_trait]` / `async fn`, or returning `Option<Arc<dyn Worker>>`. The trait is sync and returns `Option<usize>` — both fail to compile. Also: hand-rolling `w.circuit_breaker().can_execute()`. The method is `w.circuit_breaker_can_execute()`; just use `get_healthy_worker_indices`.

### Step 2: Export the policy

**File:** `model_gateway/src/policies/mod.rs` — add `mod {POLICY_NAME};` to the module block and `pub use {POLICY_NAME}::MyPolicy;` to the re-exports.

**Verify:** `cargo check -p smg`

### Step 3: Add a config variant

**File:** `model_gateway/src/config/types.rs` — add a variant to the `PolicyConfig` enum (with a `#[serde(rename = "my_policy")]`), and a match arm in `PolicyConfig::name()`.

```rust
#[serde(rename = "my_policy")]
MyPolicy,
```

Stateless policies are fieldless like `Random`/`RoundRobin`. For tunables, give the variant fields (`#[serde(default = "...")]`) and plumb them per @config-plumbing.md.

**Verify:** `cargo check -p smg`

### Step 4: Register in the factory

**File:** `model_gateway/src/policies/factory.rs` — add `MyPolicy` to the `use super::{...}` list, then add a match arm to **both** functions:

```rust
// in create_from_config(config: &PolicyConfig)
PolicyConfig::MyPolicy => Arc::new(MyPolicy::new()),

// in create_by_name(name: &str)  -- matched lowercased
"my_policy" | "mypolicy" => Some(Arc::new(MyPolicy::new())),
```

`PolicyRegistry` (`policies/registry.rs`) calls these to build the default/prefill/decode/per-model policies, so both arms are required: `create_from_config` for the configured policy, `create_by_name` for per-worker policy hints.

**Verify:** `cargo test -p smg`

**Anti-pattern:** Updating only `create_from_config`. A worker that sends a `policy_hint` routes through `create_by_name`, which would silently fall back to the default policy on a miss.

### Step 5: Quality gate

Invoke `smg:contribute` to run fmt -> clippy -> test -> bindings -> commit.

## Critical Rules

- The trait is `LoadBalancingPolicy`, sync, `Send + Sync + Debug`. No `#[async_trait]`. `select_worker` returns `Option<usize>` (index into the `workers` slice).
- Always filter with `get_healthy_worker_indices(workers)` and return `None` when it is empty. Index back into `workers` to read load/url or call `increment_processed()`.
- `SelectWorkerInfo` is a **struct**, not an enum — there are no `Http`/`Grpc` variants. Branch on its fields: `info.tokens: Option<&[u32]>` (token path) vs `info.request_text: Option<&str>` (text path); `cache_aware.rs::select_worker` does exactly this. If your policy reads request text/tokens, override `needs_request_text()` to return `true`.
- Header-based routing reads `info.headers: Option<&http::HeaderMap>` (e.g. `X-SMG-Target-Worker`, `X-SMG-Routing-Key`); consistent-hash policies use the prebuilt `info.hash_ring: Option<Arc<HashRing>>` rather than rebuilding per request.
- State must be `Send + Sync`. Prefer `AtomicUsize` (round_robin) or `DashMap`; `power_of_two.rs` uses `RwLock<HashMap<..>>` for cached loads updated via `update_loads`. Never `.unwrap()` on worker access or hold a lock across `select_worker`.
- Load-aware policies (those overriding `update_loads` — both `power_of_two` and `least_load`) are fed by the registry only if discoverable. `PolicyRegistry::get_all_load_aware_policies()` (`policies/registry.rs`) gathers them by name via an internal `is_load_aware(name)` check (currently `name == "power_of_two" || name == "least_load"`); a new load-aware policy must be added to that `is_load_aware()` name check to receive periodic `update_loads`.
- Load-aware policies should also override `remove_worker(&self, url)` to prune cached per-worker load when a worker is removed; the registry's `remove_worker_from_load_aware` calls it on each load-aware policy under worker churn so caches don't grow unbounded (see `least_load.rs` / `power_of_two.rs`).
- There are 9 `LoadBalancingPolicy` impls (random, round_robin, power_of_two, cache_aware, least_load, bucket, manual, consistent_hashing, prefix_hash). Match an existing one rather than inventing API.

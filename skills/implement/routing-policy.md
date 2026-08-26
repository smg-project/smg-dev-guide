# Adding a Routing Policy to SMG

A routing policy implements `LoadBalancingPolicy` (`model_gateway/src/policies/mod.rs`): a **synchronous** `Send + Sync + Debug` trait whose `select_worker` returns the **index** of the chosen worker (`Option<usize>`), not the worker itself. Live in `model_gateway/src/policies/`, registered via `PolicyConfig` + `PolicyFactory`, owned at runtime by `PolicyRegistry`.

Note: `dp_min_token.rs` implements a *different* trait, `DPRankLoadPolicy` (selects a DP rank within one worker, not a worker). If you need that, don't follow this recipe.

## Inputs to gather first

| Input | Example | Notes |
|-------|---------|-------|
| `POLICY_NAME` | `my_policy` | Snake case. File name, `name()` return, factory key |
| Struct name | `MyPolicy` | PascalCase + `Policy` suffix |
| State | `AtomicUsize`, `RwLock<HashMap<..>>`, none | Must be `Send + Sync`. Stateless policies are unit structs (see `random.rs`) |
| Routing input | none / `info.tokens` / `info.routing_key` / `info.request_text` / `info.headers` | What drives selection (see Critical Rules) |
| Config params | `load_factor: f64` | If tunable, needs a `PolicyConfig` variant — see @config-plumbing.md |

## Steps

### Step 1: Create the policy file

**File:** `model_gateway/src/policies/{POLICY_NAME}.rs`

Model this on `random.rs` (stateless) or `least_load.rs` (cached load state; `power_of_two.rs` just wraps a `LeastLoadPolicy` scorer). Required methods: `select_worker`, `name`, `as_any`. Default methods you may override: `on_request_complete`, `needs_request_text`, `update_loads`, `needs_backend_loads` (must return `true` if you override `update_loads`), `remove_worker`, `reset`. Always filter via the `get_healthy_worker_indices` helper — it applies `Worker::is_available()` per worker (`is_healthy() && circuit_breaker_can_execute() && !is_overloaded()`).

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

**Anti-pattern:** Adding `#[async_trait]` / `async fn`, or returning `Option<Arc<dyn Worker>>`. The trait is sync and returns `Option<usize>` — both fail to compile. Also: hand-rolling `is_healthy() && circuit_breaker_can_execute()` — that skips the overload veto the load monitor latches. Just use `get_healthy_worker_indices` (or `w.is_available()`).

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

Also add an arm to the exhaustive `match` in `ConfigValidator::validate_policy` (`model_gateway/src/config/validation.rs`) — fieldless variants join the `PolicyConfig::Random | ... => {}` arm; tunables get their range checks there. Without it `cargo check` fails with a non-exhaustive-patterns error.

**Verify:** `cargo check -p smg`

### Step 4: Register in the factory

**File:** `model_gateway/src/policies/factory.rs` — add `MyPolicy` to the `use super::{...}` list, then add a match arm to **both** functions:

```rust
// in create_from_config(config: &PolicyConfig)
PolicyConfig::MyPolicy => Arc::new(MyPolicy::new()),

// in create_by_name(name: &str)  -- matched lowercased
"my_policy" | "mypolicy" => Some(Arc::new(MyPolicy::new())),
```

`PolicyRegistry` (`policies/registry.rs`) calls these to build the default/prefill/decode/encode/per-model policies, so both arms are required: `create_from_config` for the configured policy (and for a worker `policy_hint` naming the default policy's type, which then inherits the operator's tunables), `create_by_name` for any other per-worker hint.

**Verify:** `cargo test -p smg`

**Anti-pattern:** Updating only `create_from_config`. A worker that sends a `policy_hint` routes through `create_by_name`, which would silently fall back to the default policy on a miss.

### Step 4b: Expose the name on the CLI and bindings

**File:** `model_gateway/src/main.rs` — add `"my_policy"` to the `--policy` (and `--prefill-policy` / `--decode-policy`) `value_parser = [...]` lists and an arm to `CliArgs::parse_policy`; its `_ => PolicyConfig::RoundRobin` fallback silently turns an unmapped name into round_robin. `--encode-policy` is deliberately restricted — leave it alone.

**Python:** add the `PolicyType` variant and its `convert_policy` arm in `bindings/python/src/lib.rs`, the `policy_from_str` entry in `bindings/python/src/smg/router.py`, and the name in `COMMON_POLICY_CHOICES` (`bindings/python/src/smg/router_args.py`). See @bindings-update.md.

**Verify:** `cargo check -p smg && make python-dev`

### Step 5: Quality gate

Invoke `smg:contribute` to run fmt -> clippy -> test -> bindings -> commit.

## Critical Rules

- The trait is `LoadBalancingPolicy`, sync, `Send + Sync + Debug`. No `#[async_trait]`. `select_worker` returns `Option<usize>` (index into the `workers` slice).
- Always filter with `get_healthy_worker_indices(workers)` — it is `Worker::is_available()` (`is_healthy() && circuit_breaker_can_execute() && !is_overloaded()`; the overload veto is latched by the load monitor) — and return `None` when it is empty. Index back into `workers` to read load/url or call `increment_processed()`. (Only the ring policies differ: `consistent_hashing.rs` / `prefix_hash.rs` filter on `is_healthy_and_eligible()` — health plus the overload veto, no circuit breaker — to keep ring membership stable.)
- `SelectWorkerInfo` is a **struct**, not an enum — there are no `Http`/`Grpc` variants. Branch on its fields: `info.tokens: Option<&[u32]>` (token path) vs `info.request_text: Option<&str>` (text path); `cache_aware.rs::select_worker` does exactly this. If your policy reads request text/tokens, override `needs_request_text()` to return `true`. It derives `Default`, so tests write `SelectWorkerInfo { tokens: Some(&toks), ..Default::default() }`.
- Key-based routing reads the pre-validated `info.routing_key: Option<&str>` (non-empty UTF-8, <= 128 bytes, taken from the configured header names `routing_key_override.headers` / `--routing-key-headers`, default `x-smg-routing-key`) — never re-parse the header yourself. `consistent_hashing.rs` does `info.routing_key.or_else(|| extract_routing_key_hint(info.headers))`; `prefix_hash.rs` checks `info.routing_key` first. `info.rid_key` is the lineage-stripped body `rid`, `info.leg: WorkerLeg` (`Single`/`Prefill`/`Decode`) says which PD leg is being selected, and `info.tokens` may be an `x-smg-routing-tokens` hint that wins over body tokens. `X-SMG-Target-Worker` still comes from `info.headers`; consistent-hash policies use the prebuilt `info.hash_ring: Option<Arc<HashRing>>` rather than rebuilding per request.
- Routers call `PolicyRegistry::select_worker(&policy, workers, info)`, not your policy directly. With `routing_key_override.enabled`, keyed requests (`info.rid_key`, else the routing key) go to a shared sticky `ManualPolicy` for every policy except `manual`/`consistent_hashing` (`routing_key_override_applies`); only in the default `delegate` assignment mode is yours consulted at all — to place a first-seen/stale key, or to respill past the per-key in-flight cap (`STICKY_INFLIGHT_CAP = 2`). Keep `name()` identical to the serde rename; the registry matches it literally.
- State must be `Send + Sync`. Prefer `AtomicUsize` (round_robin) or `DashMap`; `least_load.rs` uses `RwLock<HashMap<..>>` for cached loads and since-poll in-flight tallies updated via `update_loads` (`power_of_two` delegates to it). Never `.unwrap()` on worker access or hold a lock across `select_worker`.
- Load-aware policies (those overriding `update_loads`) must also override `needs_backend_loads()` to return `true` — the trait default is `false`. `PolicyRegistry::get_all_load_aware_policies()` (`policies/registry.rs`) gathers policies by that method, not by a name list, and `WorkerMonitor` pushes `update_loads` only to what it returns (under `--disable-load-monitoring` an empty result also skips load polling entirely). `power_of_two`/`least_load` always return `true`; `cache_aware` only when a pressure knob is configured.
- Load-aware policies should also override `remove_worker(&self, url)` to prune cached per-worker load when a worker is removed; the registry's `remove_worker_from_load_aware` calls it on each load-aware policy under worker churn so caches don't grow unbounded (see `least_load.rs` / `power_of_two.rs`).
- There are 10 `LoadBalancingPolicy` impls (random, round_robin, passthrough, power_of_two, cache_aware, least_load, bucket, manual, consistent_hashing, prefix_hash). Match an existing one rather than inventing API. (`passthrough` is a single-backend routing policy; `dp_min_token.rs` is not counted — different trait.)

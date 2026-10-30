---
recipe: routing-policy
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - model_gateway/src/policies/
  - model_gateway/src/worker/load_state.rs
  - model_gateway/src/config/validation.rs
exemplars:
  - 3f12f121   # power_of_two gains a load_metric tunable: config variant, every literal, factory, CLI, Python
  - 6bd1b773   # cache_aware spill pricing: new knobs through config, factory, registry, routers, bindings
  - a78ec4ab   # cache-aware affinity keyed under the request's cache partition (cache_namespace.rs)
---

# Add a routing policy

A policy implements `LoadBalancingPolicy` (`model_gateway/src/policies/mod.rs`): a synchronous `Send + Sync + Debug` trait whose `select_worker` returns the index of the chosen worker (`Option<usize>`), never the worker itself.
It lives in `model_gateway/src/policies/`, is named by a `PolicyConfig` variant (`model_gateway/src/config/types.rs`) and built by `PolicyFactory` (`policies/factory.rs`).
`PolicyRegistry` (`policies/registry.rs`) owns the instances at runtime: the default, prefill, decode, encode and per-model policies, plus the sticky routing-key override.
Routers never call a policy directly; they go through the registry (Rules).

Not this recipe:
- `dp_min_token.rs` implements `DPRankLoadPolicy` (`MinimumTokensPolicy`): it selects a DP rank inside one worker, not a worker.
- `policies/cost/` is cache-aware's internal selection pipeline (filters, scorers and a picker, chosen by the `selection_policy` knob).
- `cache_namespace.rs` mirrors an engine's prefix-cache partitions so cache-aware keys its affinity under them (a78ec4ab).

## Inputs

| Input | Example | Used in |
|---|---|---|
| Name | `<name>` (snake_case: file name, `name()` return, serde rename, factory key, CLI and Python spelling) | steps 1-5 |
| State | none (unit struct, `random.rs`); `AtomicUsize` (`round_robin.rs`) or `RwLock<HashMap<..>>`; a `LoadReceiver` plus per-worker tally (`least_load.rs`) | step 1 |
| Selection input | none / `info.tokens` / `info.request_text` / `info.routing_key` / `info.headers` | step 1 |
| Tunables | `load_metric: PowerOfTwoLoadMetric` (3f12f121); fields on the `PolicyConfig` variant | step 3 |

## Steps

### 1. Write the policy

File: `model_gateway/src/policies/<name>.rs` — Do: model on `random.rs` (stateless) or `least_load.rs` (cached load state; `power_of_two.rs` wraps a `LeastLoadPolicy` scorer). Implement `select_worker`, `name`, `as_any`; override the defaults you need (`on_request_complete`, `needs_request_text`, `needs_request_text_with_tokens`, `set_load_receiver`, `needs_backend_loads`, `balances_load_against_affinity`, `remove_worker`, `reconcile_in_flight`, `reset`). Filter with `get_healthy_worker_indices(workers, info)` (two arguments) and return `None` when it is empty; index back into `workers` to read `load()` or call `increment_processed()`. Unit tests build workers with `make_worker` / `make_workers` / `fed_pair` from `policies/test_support.rs` (`#[cfg(test)]`).
Verify: `cargo check -p smg` → compiles; `#[async_trait]`, `async fn` or `Option<Arc<dyn Worker>>` fail here because the trait is sync and returns an index.
Trap: a hand-rolled `is_healthy() && circuit_breaker_can_execute()` compiles but drops the overload veto that `Worker::is_available()` adds (`is_healthy() && circuit_breaker_can_execute() && !is_overloaded()`, plus no stall reason); `get_healthy_worker_indices_honors_the_overload_veto` in `policies/mod.rs` shows the expected behaviour.

### 2. Export it

File: `model_gateway/src/policies/mod.rs` — Do: add `mod <name>;` to the module block and `pub use <name>::<Name>Policy;` to the re-exports.
Verify: `cargo check -p smg`

### 3. Add the config variant

File: `model_gateway/src/config/types.rs` — Do: add a `#[serde(rename = "<name>")]` variant to `PolicyConfig` (fieldless like `Random` / `RoundRobin`; tunables get fields with `#[serde(default)]`, plumbed per @config-plumbing.md) and an arm in `PolicyConfig::name()` returning the same string. File: `model_gateway/src/config/validation.rs` — Do: add the arm in `ConfigValidator::validate_policy`; fieldless variants join the `PolicyConfig::Random | ... => {}` arm, tunables get their range checks there.
Verify: `cargo check -p smg` → no non-exhaustive-patterns error from `validate_policy`.
Trap: a new field on a fielded variant forces every full struct literal to change: at HEAD `PolicyConfig::PowerOfTwo {` is written out in `config/types.rs`, `config/builder.rs`, `config/validation.rs`, `main.rs`, `policies/factory.rs`, `policies/registry.rs`, `routers/factory.rs`, `bindings/python/src/lib.rs` and `model_gateway/tests/routing/test_pd_routing.rs` (3f12f121 touched all of them); `CacheAware` literals also sit in `app_context.rs` and `worker/monitor.rs`, while the `PolicyConfig::cache_aware(...)` constructor (`mesh/wiring.rs`, router tests) absorbs a knob in its default tail. `cargo check` names each site; `..` hides a field only where it is really unused.

### 4. Register in the factory

File: `model_gateway/src/policies/factory.rs` — Do: import the type, then add an arm to both `create_from_config` (`PolicyConfig::<Name> => Arc::new(<Name>Policy::new())`, passing tunables) and `create_by_name` (`"<name>" | "<name without underscores>" => Some(...)`, matched lowercased).
Verify: `cargo test -p smg`
Trap: only `create_from_config` compiles on its own; a worker `policy_hint` naming another policy goes through `create_by_name`, and on a miss `PolicyRegistry` silently falls back to the default policy. A hint naming the default policy's type reuses `create_from_config`, so it inherits the operator's tunables.

### 5. Expose the name

File: `model_gateway/src/main.rs` — Do: add `"<name>"` to the `value_parser = [...]` lists of `--policy`, `--prefill-policy` and `--decode-policy` and an arm to `CliArgs::parse_policy`; leave `--encode-policy` alone (deliberately restricted to `random`, `round_robin`, `consistent_hashing`).
File: `bindings/python/src/lib.rs` — Do: add the `PolicyType` variant and its `convert_policy` arm; add the `policy_from_str` entry in `bindings/python/src/smg/router.py` and the name in `COMMON_POLICY_CHOICES` (`bindings/python/src/smg/router_args.py`; `PREFILL_POLICY_CHOICES` extends it with `bucket`). See @bindings-update.md.
Verify: `cargo check -p smg && make python-dev`
Trap: `parse_policy` ends in `_ => PolicyConfig::RoundRobin`, so a name missing from its arms silently becomes round_robin.

### 6. Gate

Run `smg:contribute`.

## Rules

- `SelectWorkerInfo` is a struct, not an enum (no `Http` / `Grpc` variants); it derives `Default`, so tests write `SelectWorkerInfo { tokens: Some(&toks), ..Default::default() }`. Fields: `request_text: Option<&str>`, `tokens: Option<&[u32]>` (an `x-smg-routing-tokens` hint wins over body tokens), `headers`, `routing_key: Option<&str>` (validated `x-smg-routing-key`: non-empty UTF-8, <= 128 bytes, header names from `routing_key_override.headers` / `--routing-key-headers`), `cache_namespace`, `rid_key` (lineage-stripped body `rid`), `hash_ring: Option<Arc<HashRing>>` (prebuilt; never rebuild per request), `role: WorkerRole` (`Single` / `Prefill` / `Decode`), `overload_lifted`. `cache_aware.rs` branches on `info.tokens` then `info.request_text`; a policy that reads either overrides `needs_request_text()`. `consistent_hashing.rs` does `info.routing_key.or_else(|| extract_routing_key_hint(info.headers))`; `X-SMG-Target-Worker` still comes from `info.headers`.
- Load-aware policies take the worker monitor's feed through `set_load_receiver(Option<LoadReceiver>)`: `LoadReceiver` is `watch::Receiver<Arc<LoadSnapshot>>` (`model_gateway/src/worker/load_state.rs`), published per poll tick; keep the receiver and read the current snapshot per decision (one `Arc` clone, no copy). Also return `true` from `needs_backend_loads()`: `PolicyRegistry::needs_backend_loads()` ORs every policy, and with load monitoring disabled the `WorkerMonitor` polls a group only while something needs the data (`power_of_two` / `least_load` always, `cache_aware` only with a pressure knob).
- Override `remove_worker(&self, url)` to drop per-worker state: `PolicyRegistry::remove_worker_from_policies` calls every policy under worker churn (`least_load.rs` pins it with `remove_worker_prunes_its_tally`). A policy that books in-flight counts also implements `reconcile_in_flight(worker_url, in_flight)`; the worker monitor calls it once per load poll with the router's live count, so a completion that never arrived is released.
- Routers select through `PolicyRegistry::select_worker_for_model`. With `routing_key_override.enabled`, keyed requests (`rid_key`, else the routing key) go to a shared sticky `ManualPolicy` for every policy except `manual` / `consistent_hashing` (`routing_key_override_applies`); only in the default `delegate` assignment mode is yours consulted, to place a first-seen or stale key or to respill past `STICKY_INFLIGHT_CAP` (2). The registry matches `name()` literally against the serde rename.
- `placement.rs` (`routers/common/`) pre-filters unavailable workers unless `policy_filters_unavailable_workers` (`policies/mod.rs`) lists your type; join that allowlist only if you apply `is_available()` yourself (`allowlisted_policies_reject_unavailable_workers` pins it). The ring policies `consistent_hashing.rs` / `prefix_hash.rs` filter on `is_healthy_and_eligible()` instead — health plus the overload veto, no circuit breaker — to keep ring membership stable.
- State must be `Send + Sync` (`AtomicUsize`, `DashMap`); never `.unwrap()` on worker access or hold a lock across `select_worker`. 10 impls match the 10 `PolicyConfig` variants (random, round_robin, passthrough, power_of_two, cache_aware, least_load, bucket, manual, consistent_hashing, prefix_hash); copy an existing one rather than inventing API.

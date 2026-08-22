# Configuring & Extending the Priority Scheduler in SMG

The priority admission scheduler (`model_gateway/src/middleware/scheduler/`, package `smg`) is an axum middleware that admits, queues, or rejects requests per service `Class`. Most tasks are **configuration** (YAML classes + per-tenant policies, CLI flags); extension means swapping the per-class queue discipline (`ClassQueue`) or the tenant lookup (`TenantPolicyResolver`).

It is **off by default**: `priority_scheduler_enabled = false` keeps the legacy `concurrency_limit_middleware` wired (`state.rs::AdmissionMode::from_config`). A startup error (bad YAML, reservations exceed capacity) logs at ERROR and falls back to `Legacy` — it never aborts the gateway.

## Inputs to gather first

| Input | Example | Notes |
|-------|---------|-------|
| Classes touched | `interactive`, `bulk` | Four fixed: `bulk`/`default`/`interactive`/`system` (`class.rs::Class`, `#[repr(u8)]`, ascending priority). You don't add classes |
| Per-class knobs | `reserved_floor`, `queue_size`, `can_preempt` | All of `ClassConfig` (`config.rs`) |
| Tenant clamp | `auth:acme -> interactive` | `max_class` ceiling; effective = `min(header_class, max_class)` (`admission.rs::resolve_priority`) |
| Default ceiling | `default` | `--priority-scheduler-default-max-class`; applied to tenants not in the YAML |
| Extending? | custom `ClassQueue` / `TenantPolicyResolver` | Only if FIFO + static map don't fit. See Steps 3-4 |

## Steps

### Step 1: Enable + configure via CLI

**File:** none — runtime flags are `CliArgs` fields (the `Priority Scheduler` `help_heading` group in `model_gateway/src/main.rs`), parsed into `RouterConfig` (`config/types.rs`).

```
--priority-scheduler-enabled \
--priority-scheduler-config /etc/smg/scheduler.yaml \
--priority-scheduler-default-max-class default \
--priority-scheduler-tenant-metric-top-n 32
```

These four are the only scheduler knobs not in the YAML (`enabled`, `default_max_class`, `tenant_metric_top_n` are CLI-only; see `SchedulerSettings::from_cli_and_yaml`). `--priority-scheduler-config` is optional: an empty/absent file means every class uses `ClassConfig::default_for`.

**Verify:** `cargo run -p smg --bin smg -- --help | rg priority-scheduler` (`--bin smg` is required — the package declares two bins, `smg` and `amg`, and no `default-run`)

**Anti-pattern:** Setting `--max-concurrent-requests 0` and expecting the scheduler to use it as capacity. It only feeds the `WorkerCapacity` tier-4 fallback (`state.rs::try_build_priority`); real capacity is read live from `WorkerCapacity`.

### Step 2: Write the YAML config

**File:** the path passed to `--priority-scheduler-config`. Shape = `PrioritySchedulerYaml` (`config.rs`): two optional maps, `classes` (keyed by lowercase `Class`) and `tenant_policies` (keyed by tenant string). Both absent-as-empty.

```yaml
# Class keys are lowercase (serde rename_all). Omitted classes keep built-in defaults.
classes:
  interactive:
    reserved_floor: 128          # u16, absolute min slots; never drops below this
    reserved_per_slot: 0.25      # f64 >= 0, finite; effective = max(floor, ceil(share * capacity))
    queue_size: 256              # u32, per-class queue depth -> 429 when full
    queue_timeout_secs: 30       # u64 > 0; waiter past this -> 503 + Retry-After: 2
    starvation_threshold_secs: 5 # u64 > 0; head-of-queue age the dispatcher promotes past
    can_preempt: true            # may cancel a lower-class pre-TTFT request
  bulk:
    reserved_floor: 0
    reserved_per_slot: 0.0
    queue_size: 1024
    queue_timeout_secs: 300
    starvation_threshold_secs: 120
    can_preempt: false

tenant_policies:
  "auth:acme":
    max_class: interactive       # ceiling; a header asking for `system` clamps down
  "auth:internal-cron":
    max_class: system
```

Every field of `ClassConfig` is required when a class appears (only `reserved_per_slot` has `#[serde(default)]`). Tenant keys must match `RouteRequestMeta::tenant_key()` (`model_gateway/src/tenant.rs`). A readable `auth:<id>` only exists for per-tenant keys (`--tenant-api-key <id>:<secret>`, `middleware/auth.rs::AuthConfig::with_tenant_keys`); the shared `--api-key` yields `auth:<sha256-hex>`, a trusted tenant header yields `header:<id>`, otherwise `ip:<addr>` or `anonymous` (`middleware/tenant_resolution.rs::resolve_raw_tenant_key`). Scheduler keys are never validated at startup — a typo silently never matches.

**Verify:** `cargo test -p smg scheduler::config` (the `PrioritySchedulerYaml` serde + `SchedulerSettings::from_cli_and_yaml` validation tests cover this exact shape).

**Anti-pattern:** Capitalized class keys (`System:`) or an unknown `max_class` value — both are hard serde errors (`test_yaml_unknown_class_value_is_serde_error`). Also: trying to encode capacity-vs-reservation limits in YAML; reservations are clamped to live capacity priority-ordered, so there is nothing to reject there (`SettingsValidationError` only flags a zero `queue_timeout_secs`/`starvation_threshold_secs` and a non-finite or negative `reserved_per_slot`).

### Step 3 (extension): Custom `ClassQueue` discipline

**File:** `model_gateway/src/middleware/scheduler/queue.rs` — add an impl beside `FifoClassQueue`. The trait is **sync** `Send + Sync`; model the new type on `FifoClassQueue` (it guards a `VecDeque<Waiter>` with `parking_lot::Mutex` — the queue is a hot contention point, so no async mutex).

```rust
pub struct LifoClassQueue {
    waiters: Mutex<VecDeque<Waiter>>,
    max: usize,
}

impl ClassQueue for LifoClassQueue {
    fn try_enqueue(&self, waiter: Waiter) -> Result<(), Waiter> {
        let mut g = self.waiters.lock();
        if g.len() >= self.max {
            return Err(waiter); // caller turns this into a 429 QueueFull
        }
        g.push_back(waiter);
        Ok(())
    }
    fn pop_eligible(&self) -> Option<Waiter> { self.waiters.lock().pop_back() }
    fn head_age(&self) -> Option<Duration> {
        self.waiters.lock().back().map(|w| w.queued_at.elapsed())
    }
    fn depth(&self) -> usize { self.waiters.lock().len() }
    fn capacity(&self) -> usize { self.max }
    fn drop_cancelled_head(&self) {
        let mut g = self.waiters.lock();
        while g.back().is_some_and(|w| w.cancel.is_cancelled()) { g.pop_back(); }
    }
}
```

Then swap the single construction site — `engine.rs::queue_for`, the only place a `ClassQueue` is built:

```rust
fn queue_for(settings: &SchedulerSettings, class: Class) -> Arc<dyn ClassQueue> {
    Arc::new(LifoClassQueue::new(settings.class_config(class).queue_size as usize))
}
```

**Verify:** `cargo test -p smg scheduler::queue`

**Anti-pattern:** Returning `Err(waiter)` only on cancellation, or making `pop_eligible`/`drop_cancelled_head` inconsistent about which end is the "head". `head_age` and `drop_cancelled_head` must address the *same* end `pop_eligible` pops, or the dispatcher's starvation override and walkaway-GC act on the wrong waiter.

### Step 4 (extension): Custom `TenantPolicyResolver`

**File:** `model_gateway/src/middleware/scheduler/policy.rs` — add an impl beside `StaticTenantPolicyResolver`. The trait is one sync method `fn policy(&self, tenant: &TenantKey) -> TenantPolicy` (a store-backed resolver must cache so this stays sync — that is why the trait exists).

```rust
pub struct CachingTenantPolicyResolver {
    cache: DashMap<TenantKey, TenantPolicy>,
    default: TenantPolicy,
}

impl TenantPolicyResolver for CachingTenantPolicyResolver {
    fn policy(&self, tenant: &TenantKey) -> TenantPolicy {
        self.cache.get(tenant).map(|e| *e).unwrap_or(self.default)
    }
}
```

Then build it where `StaticTenantPolicyResolver::from_settings` is called — `state.rs::try_build_priority`, assigning to `resolver: Arc<dyn TenantPolicyResolver>` in `SchedulerState`. `admission.rs` reads it as `state.resolver.policy(tenant).max_class`.

**Verify:** `cargo test -p smg scheduler::policy`

**Anti-pattern:** Returning a `max_class` *above* the requested header class and expecting promotion. The resolver only sets a ceiling; admission always takes `requested.min(max_class)` (`Ord` on `Class`). You cannot promote a request from the resolver.

### Step 5: Quality gate

Invoke `smg:contribute` to run fmt -> clippy -> test -> bindings -> commit.

## Critical Rules

- **Four fixed classes**, never add one — `Class` is `#[repr(u8)]` with numeric values packed into an `AtomicU64` slot count and indexed `class as usize` across `slots`, `engine.class_queues[4]`, and `SchedulerSettings.classes[4]`. Adding a variant breaks all four-element arrays.
- The tenant clamp is `min(header_class, max_class)` (`admission.rs::resolve_priority`); a low-tier tenant cannot self-promote via `X-SMG-Priority`. An unknown header value silently degrades to `Class::Default` (`class.rs::parse_header`).
- `ClassQueue` and `TenantPolicyResolver` are both **sync** `Send + Sync` traits. No `#[async_trait]`, no `async fn` — they run on the admission hot path. Queue state uses `parking_lot::Mutex`, not `tokio::sync::Mutex`.
- `admit(class, request_id, cancel) -> AdmitOutcome` (`engine.rs`) is the entry point: `Admitted(SchedulerPermit)` or `Rejected(RejectionReason)`. The four `RejectionReason` variants map 1:1 to HTTP in `error.rs`: `QueueFull`->429 + `Retry-After: 2`, `QueueTimeout`->503 + `Retry-After: 2` (both `middleware::SHED_RETRY_AFTER_SECS`; 408 was dropped because proxies retry it instantly), `Preempted`->503 (`X-SMG-Preempted: true` + `Retry-After: 1`), `ClientCancelled`->499. Don't add a reason without an `error.rs` arm.
- `SchedulerPermit` is RAII — dropping it releases the slot, deregisters the inflight handle, and notifies the dispatcher. `admission.rs` wraps the response body in `SchedulerGuardBody` so the permit lives exactly as long as the response stream.
- Reservation math is `effective = max(reserved_floor, ceil(reserved_per_slot * capacity))`, recomputed on every capacity change; capacity is read live from `WorkerCapacity`, never stored in `SchedulerSettings`. Don't hardcode capacity assumptions in YAML.
- Settings are built once at startup and read-only. Editing the YAML requires a restart.

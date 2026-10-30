---
recipe: scheduler-feature
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - model_gateway/src/middleware/scheduler/
  - model_gateway/src/config/validation.rs
  - model_gateway/src/workflow/steps/shared/activate.rs
  - model_gateway/tests/startup/priority_scheduler_config_startup_test.rs
exemplars:
  - 9406c342   # fix: an unknown YAML key or default max class name refuses to start
  - ea6c8d13   # fix: a small pool is shared by every class, capacity counts every activated worker
---

# Configure or extend the priority scheduler

The priority admission scheduler (`model_gateway/src/middleware/scheduler/`, package `smg`) is an axum layer (`priority_admission_middleware`, `admission.rs`) that admits, queues or rejects each request by `Class` (`class.rs`: `bulk` / `default` / `interactive` / `system`, `#[repr(u8)]`, ascending). `AdmissionMode::from_config` (`state.rs`) picks it or the legacy `ConcurrencyLimitLayer` (`middleware/concurrency.rs`) once at startup in `server.rs`; it is off by default (`priority_scheduler_enabled = false`). `PriorityScheduler` (`engine.rs`) owns the `SlotPool`, four `ClassQueue`s and the inflight registry; `SchedulerState` holds it beside a `TenantPolicyResolver`. Most work is configuration (YAML + four CLI flags); extension means a new `ClassQueue` or `TenantPolicyResolver`.

Not this recipe:
- A fifth class: `Class` is indexed `class as usize` into four-element arrays (`class_queues`, `SchedulerSettings.classes`) and packed into an `AtomicU64` slot count.
- Prefill admission (`worker/prefill_admission.rs`), which `config/validation.rs` refuses to combine with `--priority-scheduler-enabled`; tenant rate limits (`rate-limit-feature`).

## Inputs

| Input | Example | Used in |
|---|---|---|
| Classes touched | `interactive`, `bulk` | 2 |
| Per-class knobs | `reserved_floor`, `queue_size`, `can_preempt` — all of `ClassConfig` (`config.rs`) | 2 |
| Tenant ceiling | `auth:acme` → `max_class: interactive`; effective = `min(header_class, max_class)` | 2 |
| Default ceiling for unlisted tenants | `default` | 1 |
| Queue discipline / tenant lookup | custom `ClassQueue` / `TenantPolicyResolver`, only when FIFO + static map do not fit | 3, 4 |

## Steps

### 1. Enable and configure via CLI

File: none — the flags are `CliArgs` fields under the `Priority Scheduler` `help_heading` in `model_gateway/src/main.rs`, parsed into `RouterConfig` (`config/types.rs`): `--priority-scheduler-enabled`, `--priority-scheduler-config /etc/smg/scheduler.yaml`, `--priority-scheduler-default-max-class default`, `--priority-scheduler-tenant-metric-top-n 32`. These four are the only knobs outside the YAML (`SchedulerSettings::from_cli_and_yaml`); `--priority-scheduler-config` is optional, and an absent or empty file leaves every class on `ClassConfig::default_for`.
Verify: `cargo run -p smg --bin smg -- --help | rg priority-scheduler` (`--bin smg` is required: the package declares two bins, `smg` and `amg`, and no `default-run`).
Trap: `--max-concurrent-requests` only seeds the `WorkerCapacity` tier-4 fallback (`state.rs::try_build_priority`, `CapacityTrackerSettings`); capacity is read live from the fleet. `--priority-scheduler-config` without `--priority-scheduler-enabled` is a start-up warning, not an error.

### 2. Write the YAML

File: the path given to `--priority-scheduler-config`. Shape = `PrioritySchedulerYaml` (`config.rs`): optional maps `classes` (lowercase `Class` keys) and `tenant_policies` (tenant key strings), all `deny_unknown_fields`.

```yaml
classes:
  interactive:
    reserved_floor: 128          # u16 absolute minimum slots
    reserved_per_slot: 0.25      # f64 >= 0, finite; effective = max(floor, ceil(share * capacity)); the only optional field
    queue_size: 256              # u32 depth; full -> 429
    queue_timeout_secs: 30       # u64 > 0; waiter past it -> 503 + Retry-After: 2
    starvation_threshold_secs: 5 # u64 > 0; head-of-queue age the dispatcher promotes past
    can_preempt: true            # may cancel a lower-class pre-TTFT request
tenant_policies:
  "auth:acme": { max_class: interactive }   # ceiling; a `system` header clamps down to it
```

Tenant keys must equal `RouteRequestMeta::tenant_key()` (`model_gateway/src/tenant/mod.rs`): `auth:<id>` for `--tenant-api-key <id>:<secret>` (`middleware/auth.rs::AuthConfig::with_tenant_keys`), `auth:<sha256-hex>` for the shared `--api-key`, `header:<id>` for a trusted header, else `ip:<addr>` or `anonymous` (`middleware/tenant_resolution.rs::resolve_raw_tenant_key`). A shape change is pinned in three places — the `scheduler::config` serde tests, `ConfigValidator::validate_priority_scheduler` (`config/validation.rs`, through `settings_from_config`) and the process-level `model_gateway/tests/startup/priority_scheduler_config_startup_test.rs` — so update all three.
Verify: `cargo test -p smg scheduler::config` (`test_yaml_unknown_key_is_serde_error_naming_it`, `test_yaml_unknown_class_value_is_serde_error`); `cargo test -p smg config::validation priority_scheduler` (`a_priority_scheduler_config_with_an_unknown_key_is_a_configuration_error`); `cargo test -p smg --test startup_tests priority_scheduler` (`an_unknown_key_or_default_max_class_name_refuses_to_start`).
Trap: tenant keys are never validated — a typo silently never matches; and reservations above capacity are not a YAML error (they are clamped proportionally at runtime): `SettingsValidationError` only flags a zero `queue_timeout_secs` / `starvation_threshold_secs` or a non-finite or negative `reserved_per_slot`.

### 3. Custom `ClassQueue` discipline (extension)

File: `model_gateway/src/middleware/scheduler/queue.rs` — Do: implement the sync `ClassQueue: Send + Sync` trait (`try_enqueue`, `pop_eligible`, `head_age`, `depth`, `capacity`, `drop_cancelled_head`) beside `FifoClassQueue`, guarding a `VecDeque<Waiter>` with `parking_lot::Mutex` (the queue is a hot contention point: no async mutex, no `#[async_trait]`). `try_enqueue` returns `Err(waiter)` when full and the caller answers 429 `QueueFull`. Then swap the single construction site, `engine.rs::queue_for` (`fn queue_for(settings: &SchedulerSettings, class: Class) -> Arc<dyn ClassQueue>`, called for `Class::ALL` in `PriorityScheduler::new`). A LIFO variant pops, ages and garbage-collects the same end:

```rust
fn pop_eligible(&self) -> Option<Waiter> { self.waiters.lock().pop_back() }
fn head_age(&self) -> Option<Duration> { self.waiters.lock().back().map(|w| w.queued_at.elapsed()) }
fn drop_cancelled_head(&self) {
    let mut g = self.waiters.lock();
    while g.back().is_some_and(|w| w.cancel.is_cancelled()) { g.pop_back(); }
}
```

Verify: `cargo test -p smg scheduler::queue`, then `cargo test -p smg --test serial_tests scheduler_admission` (`starvation_override_promotes_aged_bulk_request`, `queue_full_returns_429`).
Trap: `head_age` and `drop_cancelled_head` must address the end `pop_eligible` pops; otherwise the starvation override and the walk-away GC act on the wrong waiter while every unit test still passes.

### 4. Custom `TenantPolicyResolver` (extension)

File: `model_gateway/src/middleware/scheduler/policy.rs` — Do: implement the one sync method `fn policy(&self, tenant: &TenantKey) -> TenantPolicy` beside `StaticTenantPolicyResolver`, with a default for unknown keys (`unwrap_or(self.default)`); a store-backed resolver must cache so the method stays sync — that is why the trait exists. Build it where `StaticTenantPolicyResolver::from_settings` is called, `state.rs::try_build_priority`, as the `resolver: Arc<dyn TenantPolicyResolver>` of `SchedulerState`; `admission.rs` reads `state.resolver.policy(tenant).max_class`.
Verify: `cargo test -p smg scheduler::policy` (`test_resolver_trait_object_dispatches`, `test_clamp_via_min_with_resolved_policy`); `tenant_clamp_strips_system_header_of_preemption_power` in `tests/serial/scheduler_admission_test.rs`.
Trap: a `max_class` above the requested class does not promote — admission takes `requested.min(max_class)` (`Ord` on `Class`), so a resolver can only cap.

### 5. Gate

Run `smg:contribute`.

## Rules

- Start-up: `ConfigValidator::validate_priority_scheduler` calls `settings_from_config` (`state.rs`), so an unreadable, unparsable or invalid file, an unknown key, or an unknown `--priority-scheduler-default-max-class` name (`Class::parse_name` → `UnknownClassName`) is a `SchedulerConfigError` the gateway refuses to start on; only reservations exceeding the fleet's initial capacity (`SchedulerInitError::ReservationsExceedCapacity`) still log at ERROR and fall back to `Legacy`.
- The clamp is `min(header_class, max_class)` (`admission.rs::resolve_priority`): a low tenant cannot self-promote via `X-SMG-Priority` (`PRIORITY_HEADER`), and an unknown header value degrades to `Class::Default` (`Class::parse_header`), unlike `parse_name`.
- `admit(class, request_id, cancel) -> AdmitOutcome` (`engine.rs`) is `Admitted(SchedulerPermit)` or `Rejected(RejectionReason)`; `error.rs` maps `QueueFull` → 429 + `Retry-After: 2`, `QueueTimeout` → 503 + `Retry-After: 2` (both `middleware::SHED_RETRY_AFTER_SECS`; 408 was dropped because proxies retry it instantly), `Preempted` → 503 + `Retry-After: 1` + `X-SMG-Preempted: true` (`HEADER_X_SMG_PREEMPTED`), `ClientCancelled` → 499. A new reason needs an `error.rs` arm.
- `SchedulerPermit` is RAII: dropping it frees the slot, deregisters the inflight handle and wakes the dispatcher; `admission.rs::carry_permit` ties it to the response body (`slot_frees_after_response_drains`).
- Capacity is live: `effective = max(reserved_floor, ceil(reserved_per_slot * capacity))` is recomputed on every `WorkerCapacity` change (`apply_new_capacity`), and on a pool smaller than the sum of reservations every class keeps the same fraction while the rest is shared. A worker counts once the activation step (`workflow/steps/shared/activate.rs`) flips it Ready through `WorkerRegistry::transition_status`, which publishes the `StatusChanged` event the tracker recomputes on — a direct `set_status` is not counted (`activating_a_registered_worker_publishes_its_status_transition`).
- Settings are built once at start-up and are read-only; a YAML edit needs a restart.

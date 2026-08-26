# Rate Limiting & Concurrency in SMG

One bucket, two knobs. A single **global** (per-process) `TokenBucket` (`model_gateway/src/middleware/token_bucket.rs`) backs both the in-flight concurrency cap and the optional request rate limit. It is **not** per-tenant or per-route: `app_state.context.rate_limiter: Option<Arc<TokenBucket>>` is one bucket, and `concurrency_limit_middleware` acquires exactly `1.0` token per request regardless of tenant (`concurrency.rs::concurrency_limit_middleware`). Two *other* admission layers exist — the priority scheduler (`AdmissionMode::Priority`, `middleware/scheduler/`) and per-tenant token/request limits (`rate_limit/`, below). Don't conflate the three.

The bucket's two parameters map straight to config (`app_context.rs::maybe_rate_limiter`):

| `TokenBucket::new` arg | RouterConfig field | Meaning |
|---|---|---|
| `capacity` | `max_concurrent_requests: i32` | Burst size / max in-flight. `<= 0` disables the bucket entirely (`rate_limiter = None`). |
| `refill_rate` | `rate_limit_tokens_per_second: Option<i32>`, coerced via `.filter(\|&t\| t > 0).unwrap_or(0)` | Tokens/sec. **Unset or `0` ⇒ refill `0`, a pure semaphore**: tokens only come back when a response body drops. Negative is rejected earlier by `config/validation.rs`. Set `> 0` to add a steady admission rate on top of the burst cap. |

A token is **not** returned when the handler returns — the acquired `TokenPermit` is moved into `TokenGuardBody`, which wraps the response body, and `TokenPermit::drop` calls `return_tokens_sync(tokens)`. That fires only after the whole (possibly streamed) body is delivered, or the request is cancelled (`concurrency.rs::TokenPermit`). So `capacity` genuinely bounds concurrent *streams*, not just handler invocations.

When the bucket is empty, the request takes a slot on the bounded `AdmissionQueue` (a `Semaphore` of `queue_size` slots, `concurrency.rs::AdmissionQueue`) and parks on the bucket via `TokenPermit::acquire_timeout(bucket, 1.0, queue_timeout)` — no background processor. With `refill_rate == 0` (the default shape) it joins the bucket's FIFO waiter list and `try_acquire` cannot barge past it (`token_bucket.rs::acquire_fifo`); with `refill_rate > 0` there is no waiter list — `acquire` polls under its own `tokens_needed / refill_rate` timeout, so a fresh `try_acquire` can barge. Queue disabled (`queue_size == 0` ⇒ `AppState.admission_queue == None`) or queue full → `429 TOO_MANY_REQUESTS` (`admission_queue_full`); timing out (`queue_timeout_secs`, or `acquire`'s own wait, whichever fires first) → `503 SERVICE_UNAVAILABLE` (`admission_queue_timeout`). Every shed carries `Retry-After: 2` (`middleware/mod.rs::SHED_RETRY_AFTER_SECS`).

## Primary task: tune the limits

These are plain `RouterConfig` fields with CLI flags already wired in `main.rs` (`--max-concurrent-requests`, `--queue-size`, `--queue-timeout-secs`, `--rate-limit-tokens-per-second`, all under `help_heading = "Rate Limiting"` on `CliArgs`). No code change needed to *set* them — set via CLI or YAML. Defaults: `max_concurrent_requests: -1` (disabled), `queue_size: 100`, `queue_timeout_secs: 60`, `rate_limit_tokens_per_second: None` (`config/types.rs`, `RouterConfig`'s `Default`).

Common configurations:

- **Pure concurrency cap (the default shape):** `max_concurrent_requests=64`, leave `rate_limit_tokens_per_second` unset (or `0`). Refill is `0`: at most 64 in-flight responses, and a slot frees only when a response body drops.
- **Rate limit + burst:** `max_concurrent_requests=200` (burst), `rate_limit_tokens_per_second=50` (steady 50 req/s on top of the 200 cap).

## Adding a new knob

If the task needs a *new* tunable (e.g. per-token cost instead of `1.0`, or a separate read/write bucket), it is a config field — follow the **two-path rule** in @config-plumbing.md (add to `config/types.rs` `RouterConfig` + its `Default`, the CLI flag in `main.rs`, **both** `RouterConfigBuilder` setters in `config/builder.rs` and the `to_router_config` wiring, then Python/Go bindings). The rate-limit fields are good templates: `rate_limit_tokens_per_second` (`config/types.rs`), builder `rate_limit_tokens_per_second`/`maybe_rate_limit_tokens_per_second` (`builder.rs`).

### Step 1: Plumb the field

Mirror `rate_limit_tokens_per_second` end to end per @config-plumbing.md.

**Verify:** `cargo check -p smg`

### Step 2: Consume it where the bucket is built or acquired

Construction lives in `maybe_rate_limiter` (`app_context.rs`). Per-request behavior (token cost, branching) lives in `concurrency_limit_middleware` (`concurrency.rs`). The `TokenBucket` API you have: `try_acquire(f64) -> Result<(),()>`, `acquire_timeout(f64, Duration)`, `return_tokens_sync(f64)`, `available_tokens() -> f64`. In the middleware go through `TokenPermit`, not the bucket directly — it pairs acquire with return and moves the admission gauges.

```rust
// in concurrency_limit_middleware, if cost is configurable:
let cost = app_state.context.router_config.rate_limit_cost as f64;
if let Ok(permit) = TokenPermit::try_acquire(token_bucket.clone(), cost) {
    Metrics::record_http_rate_limit(metrics_labels::RATE_LIMIT_ALLOWED);
    // the permit carries `cost`; its Drop returns exactly that when the body drops
    return run_with_permit(next, request, permit).await;
}
// ...and pass the same `cost` to TokenPermit::acquire_timeout on the queued path.
```

**Verify:** `cargo check -p smg`

**Anti-pattern:** acquiring a different amount on the immediate vs. queued path. The `1.0` literal appears in **two** non-test places in `concurrency.rs` (`TokenPermit::try_acquire`, `TokenPermit::acquire_timeout`); the permit returns whatever it acquired, so the body guard cannot drift — only those two sites can.

### Step 3: Record the outcome metric

Both admit/reject paths already call `Metrics::record_http_rate_limit(...)` with `metrics_labels::RATE_LIMIT_ALLOWED` / `RATE_LIMIT_REJECTED` (`observability/metrics.rs::record_http_rate_limit`). Queue depth, in-flight and rejection reason are covered too — `record_admission_queue_entered/exited` (`smg_admission_queue_depth`), `record_admission_inflight_acquired/released` (`smg_admission_inflight`), `record_admission_rejected(ADMISSION_REJECTED_FULL|ADMISSION_REJECTED_TIMEOUT)` (`smg_admission_queue_rejected_total{reason}`). The gauge pairs are owned by `QueueDepthGuard` and `TokenPermit`; `record_admission_rejected` fires inline in `concurrency_limit_middleware`, on the queue-full and timeout arms only (not the queue-disabled 429). Reuse them and keep the pairs balanced; don't add a parallel counter. See @observability-feature.md for hot-path label rules.

**Verify:** `cargo check -p smg`

### Step 4: Test

`token_bucket.rs`'s `#[cfg(test)]` module covers refill, `refill_rate=0` FIFO order, no-barge, cancelled and timed-out waiters — extend it. For middleware behavior extend `concurrency.rs`'s own test module (helpers `test_app_state`, `echo_app`, `stream_app`) and assert the 429-on-full-queue / 503-on-timeout paths plus `Retry-After`.

**Verify:** `cargo test -p smg`

## Per-tenant token/request limits (`rate_limit/`)

A separate subsystem with its own config file, wired only into the gRPC pipeline. Don't extend the global bucket to do per-tenant work.

- Enable: `--tenant-rate-limit-enabled --tenant-rate-limit-config <yaml>` (`RouterConfig.tenant_rate_limit_enabled` / `tenant_rate_limit_config`, `help_heading = "Tenant Rate Limit"`). Disabled is `Ok(None)`; enabled with missing or invalid YAML **fails startup** (`app_context.rs::maybe_rate_limit_manager` -> `manager.rs::RateLimitManager::from_config`). No Python/Go binding fields yet.
- YAML (`rate_limit/config.rs::RateLimitYaml`, `deny_unknown_fields`): `default_policy: TenantPolicySpec` plus `tenants: [TenantPolicySpec]`, each `{tenant_key, tokens_per_minute, requests_per_minute, model_rules: [ModelRuleSpec]}` with `matcher: {type: exact|prefix, value}`. `tenant_key` must be canonical (`auth:<id>`, `header:<id>`, `ip:<addr>`, `anonymous`) and `header:` keys additionally require `tenant_resolution.trust_tenant_header`. `CompiledPolicySet::compile` (`policy.rs`): exact beats prefix, longest prefix wins, rules never stack.
- Engine: `RateLimitBackend` (`backend.rs` — `reserve`/`settle_success`/`close_reserved_only`/`abandon`, keyed by `request_charge_id`) implemented by `LocalRateLimitBackend` (`local_backend.rs`, per-instance only, `ScopeBucket` in `bucket.rs`). `RateLimitManager::reserve(ReserveRequest) -> Reservation::{Admitted(Arc<SharedReservationHandle>), Denied { retry_after_secs }}`; denial → `rejection_response(retry_after_secs)` = `429` + `tenant_rate_limit_exceeded` (`rejection.rs`).
- Lifecycle: reserve once per *logical* request, before any retry loop; resolve the handle exactly once (CAS-guarded, first resolution wins). Streaming defers resolution by attaching `ReservationAttachment` to the body via `AttachedBody::wrap_response` (`routers/grpc/common/stages/helpers.rs`), so a disconnect abandons instead of leaking a reservation.
- Wiring: `RateLimitReserveStage` sits right after the preparation stage in `routers/grpc/pipeline.rs` (Chat/Messages/Completion/Harmony) and no-ops unless the caller threads in a `RateLimitCell` (`router.rs`: `route_chat_impl`, `route_generate_impl`, `route_messages_impl`, `route_completion_impl`). Responses/embeddings/classify and the whole HTTP router are **not** covered.

## Wiring reference (cite, don't reinvent)

- Bucket built once at startup: `app_context.rs::maybe_rate_limiter`, stored on `AppContext.rate_limiter`.
- Queue built in `server.rs::startup`: `Arc::new(AdmissionQueue::new(queue_size, Duration::from_secs(queue_timeout_secs)))`, only when `rate_limiter.is_some() && queue_size > 0`; lands on `AppState.admission_queue: Option<Arc<AdmissionQueue>>`. No background task — waiters park on the bucket itself.
- Middleware installed as a `route_layer` on protected/realtime/multipart routes via `server.rs::with_admission_layer`. That function is **always** called for those routes and switches internally on `AdmissionMode`: `concurrency_limit_middleware` in `Legacy`, `priority_admission_middleware` in `Priority`. Under `priority_scheduler_enabled` the scheduler owns concurrency and the bucket's cap is ignored — but when `rate_limit_tokens_per_second > 0` the same bucket survives on `SchedulerState.rate_limiter` as a pre-admission RPS check (`scheduler/admission.rs`: `try_acquire(1.0)`, never returned). Verify which path your deployment uses.
- Re-exported from `middleware` (`middleware/mod.rs`): `concurrency_limit_middleware, AdmissionQueue, TokenGuardBody, TokenBucket`. `TokenPermit`, `QueueDepthGuard` and `run_with_permit` are private to `concurrency.rs`.

## Critical rules

- One global bucket, cost `1.0` per request. Per-tenant limiting is `rate_limit/`; priority admission is `middleware/scheduler/`.
- `max_concurrent_requests <= 0` ⇒ the bucket is `None` and the middleware passes through. The `-1` sentinel is the disable signal, not a value.
- Unset or `0` `rate_limit_tokens_per_second` ⇒ `refill_rate == 0.0`, and `acquire` then waits **indefinitely** in FIFO order for a returned token (`token_bucket.rs::acquire_fifo`); always use `acquire_timeout` (the middleware does).
- Acquire and return amounts must match — hold the `TokenPermit` for as long as the work lasts instead of returning tokens by hand. The permit rides in the response body, so streaming and client disconnects are both covered.
- Bucket math uses `f64`; `try_acquire`/`return_tokens` `debug_assert` finite, non-negative inputs.

## Quality gate

Invoke `smg:contribute` to run fmt -> clippy -> test -> bindings -> commit.

---
recipe: rate-limit-feature
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - model_gateway/src/rate_limit/
  - model_gateway/src/middleware/concurrency.rs
  - model_gateway/src/middleware/token_bucket.rs
  - model_gateway/src/routers/grpc/common/stages/rate_limit.rs
  - model_gateway/src/routers/grpc/pipeline.rs
  - model_gateway/tests/grpc/tenant_rate_limiting_grpc_test.rs
exemplars:
  - 7af2759f   # usage settlement in pipeline.rs carries cached and reasoning counts
  - b3b9e900   # embeddings, classify, transcription take the reservation every other gRPC endpoint takes
  - 5249d338   # every iteration of a Responses request reserves under its own charge id
---

# Change admission or rate limiting

Three admission layers, not one. A single per-process `TokenBucket` (`model_gateway/src/middleware/token_bucket.rs`), built by `app_context.rs::maybe_rate_limiter` into `AppContext.rate_limiter: Option<Arc<TokenBucket>>`, backs the in-flight cap and the optional request rate through `ConcurrencyLimitLayer`/`ConcurrencyLimitService` (`middleware/concurrency.rs`), which acquires exactly `1.0` token per request whatever the tenant.
The priority scheduler (`AdmissionMode::Priority`, `middleware/scheduler/`) is the second layer; per-tenant token and request limits (`rate_limit/`) are the third, reserved by `RateLimitReserveStage` (`routers/grpc/common/stages/rate_limit.rs`) in every gRPC endpoint and settled in `routers/grpc/pipeline.rs`.

Not this recipe:
- Plumbing a new config field end to end: @config-plumbing.md. Hot-path label rules: @observability-feature.md.

## Inputs

| Input | Example | Used in |
|---|---|---|
| knob | `rate_limit_tokens_per_second` | `config/types.rs` (`RouterConfig` + `Default`), `main.rs` flag, `builder.rs` setters, `to_router_config` |
| tenant policy | `tenant_key: auth:<id>` | the YAML behind `--tenant-rate-limit-config` |

## Steps

### 1. Tune the limits without code

File: `model_gateway/src/main.rs` — Do: set `--max-concurrent-requests`, `--queue-size`, `--queue-timeout-secs`, `--rate-limit-tokens-per-second` (all under `help_heading = "Rate Limiting"` on `CliArgs`, which also holds `--max-background-responses`) or the YAML. Defaults: `max_concurrent_requests: -1` (an `i32`), `queue_size: 100`, `queue_timeout_secs: 60`, `rate_limit_tokens_per_second: None` (an `Option<i32>`) in `RouterConfig`'s `Default`. `effective_max_concurrent_requests` (`app_context.rs`) reads the sentinels: `0` disables admission control (`rate_limiter = None`, the middleware passes through), `< 0` (the default) takes `default_max_concurrent_requests()`, `DEFAULT_INFLIGHT_PER_CORE` (1024) per available core with floor `DEFAULT_INFLIGHT_FLOOR` (4096), a positive value is the cap. `refill_rate` is `rate_limit_tokens_per_second.filter(|&t| t > 0).unwrap_or(0)`: unset or `0` is a pure semaphore (tokens return only when a response body drops), negative is rejected by `config/validation.rs`, `> 0` adds a steady admission rate on top of the burst cap. Shapes: cap only, `max_concurrent_requests=64`; cap plus rate, `max_concurrent_requests=200` and `rate_limit_tokens_per_second=50`.
Verify: the start-up log says `Admission bound: at most N in-flight requests` or `Admission bound disabled (max_concurrent_requests = 0)`.
Trap: `-1` is not "off"; since 55316b19 it is the host-derived bound.

### 2. Plumb a new knob

File: `model_gateway/src/config/types.rs` — Do: a new tunable (per-token cost instead of `1.0`, a separate read/write bucket) is a config field; mirror `rate_limit_tokens_per_second` end to end per @config-plumbing.md: `RouterConfig` + `Default`, the `CliArgs` flag, both `RouterConfigBuilder` setters (`rate_limit_tokens_per_second`/`maybe_rate_limit_tokens_per_second` in `config/builder.rs`), the `to_router_config` wiring, then the bindings.
Verify: `cargo check -p smg`.

### 3. Consume it where the bucket is built or acquired

File: `model_gateway/src/middleware/concurrency.rs` — Do: construction lives in `maybe_rate_limiter` (`TokenBucket::new(capacity, refill_rate)`); per-request behavior in `ConcurrencyLimitService::call` and `admit_from_queue`, always through `TokenPermit` (`TokenPermit::try_acquire(bucket, 1.0)` on the immediate path, `TokenPermit::acquire_timeout(bucket, 1.0, queue_timeout)` on the queued path), never the bucket directly: the permit pairs acquire with return and moves the admission gauges. The bucket API is `try_acquire(f64)`, `try_take(f64)`, `acquire_timeout(f64, Duration)`, `return_tokens_sync(f64)`, `available_tokens()`.

```rust
// in ConcurrencyLimitService::call, if cost becomes configurable:
let cost = app_state.context.router_config.<cost_field> as f64;
if let Ok(permit) = TokenPermit::try_acquire(token_bucket.clone(), cost) {
    Metrics::record_http_rate_limit(metrics_labels::RATE_LIMIT_ALLOWED);
    // hand_permit(response, permit): the permit rides on the body and its Drop returns exactly `cost`
}
// pass the same `cost` to TokenPermit::acquire_timeout in admit_from_queue
```

A token is not returned when the handler returns: `hand_permit` attaches the `TokenPermit` to the response body and `TokenPermit::drop` calls `return_tokens_sync(tokens)` once the whole (possibly streamed) body is delivered or the request is cancelled, so `capacity` bounds concurrent streams.
Verify: `cargo check -p smg`.
Trap: the `1.0` literal appears in exactly two non-test places (`try_acquire`, `acquire_timeout`); acquiring different amounts on the two paths compiles, and only those two sites can drift.

### 4. Keep the queue and its metrics balanced

File: `model_gateway/src/server.rs` — Do: an empty bucket parks the request on the bounded `AdmissionQueue` (a `Semaphore` of `queue_size` slots; `server.rs::startup` builds `Arc::new(AdmissionQueue::new(queue_size, Duration::from_secs(queue_timeout_secs)))` only when `rate_limiter.is_some() && queue_size > 0`, stored on `AppState.admission_queue: Option<Arc<AdmissionQueue>>`), no background task. With `refill_rate == 0` a waiter joins the bucket's FIFO list and `try_acquire` cannot barge past it (`token_bucket.rs::acquire`); with `refill_rate > 0` `acquire` polls under its own `tokens_needed / refill_rate` timeout and a fresh `try_acquire` can barge. Queue disabled or full: `429 TOO_MANY_REQUESTS` (`admission_queue_full`); timed out: `503 SERVICE_UNAVAILABLE` (`admission_queue_timeout`); every shed carries `Retry-After: 2` (`middleware/mod.rs::SHED_RETRY_AFTER_SECS`). The metrics exist (`observability/metrics.rs`): `Metrics::record_http_rate_limit(metrics_labels::RATE_LIMIT_ALLOWED|RATE_LIMIT_REJECTED)`, `record_admission_queue_entered/exited` (`smg_admission_queue_depth`), `record_admission_inflight_acquired/released` (`smg_admission_inflight`), `record_admission_rejected(ADMISSION_REJECTED_FULL|ADMISSION_REJECTED_TIMEOUT)` (`smg_admission_queue_rejected_total{reason}`, on the queue-full and timeout arms only, not the queue-disabled 429); the constants are in `crates/external_router/src/metrics.rs::metrics_labels`, the gauge pairs are owned by `QueueDepthGuard` and `TokenPermit`.
Verify: `cargo test -p smg concurrency` → the 429-on-full and 503-on-timeout tests (`test_app_state`, `echo_app`, `stream_app` helpers) and `Retry-After` pass.
Trap: a parallel counter or an unpaired gauge call compiles; reuse these and keep the pairs balanced.

### 5. Test the bucket

File: `model_gateway/src/middleware/token_bucket.rs` — Do: extend the `#[cfg(test)]` module (`test_fifo_waiters_served_in_arrival_order`, `test_try_acquire_cannot_barge_past_waiters`, cancelled and timed-out waiters, refill) for bucket semantics and `concurrency.rs`'s module for middleware behavior.
Verify: `cargo test -p smg token_bucket`.

### 6. Configure per-tenant limits

File: `model_gateway/src/rate_limit/config.rs` — Do: enable with `--tenant-rate-limit-enabled --tenant-rate-limit-config <yaml>` (`RouterConfig.tenant_rate_limit_enabled`/`tenant_rate_limit_config`, `help_heading = "Tenant Rate Limit"`; the Python binding has both in `bindings/python/src/lib.rs` and `router_args.py`). Disabled is `Ok(None)`; enabled with missing or invalid YAML fails start-up (`app_context.rs::maybe_rate_limit_manager` → `manager.rs::RateLimitManager::from_config`). `RateLimitYaml` (`deny_unknown_fields`): `default_policy: TenantPolicySpec` plus `tenants: [TenantPolicySpec]`, each `{tenant_key, tokens_per_minute, requests_per_minute, model_rules: [ModelRuleSpec]}` with `matcher: {type: exact|prefix, value}`; `tenant_key` is canonical (`auth:<id>`, `header:<id>`, `ip:<addr>`, `anonymous`) and `header:` keys need `tenant_resolution.trust_tenant_header`. `CompiledPolicySet::compile` (`policy.rs`): exact beats prefix, longest prefix wins, rules never stack. Engine: `RateLimitBackend` (`backend.rs`: `reserve`, `settle_success(request_charge_id, UsageSettlement)`, `close_reserved_only`, `abandon`, keyed by `request_charge_id`) implemented by `LocalRateLimitBackend` (`local_backend.rs`, per instance, `ScopeBucket` in `bucket.rs`); `RateLimitManager::reserve(ReserveRequest) -> Reservation::{Admitted(Arc<SharedReservationHandle>), Denied { retry_after_secs }}`; denial answers `rejection_response(retry_after_secs)`, `429` with `tenant_rate_limit_exceeded` (`rejection.rs`).
Verify: `cargo test -p smg rate_limit` (`test_support.rs`'s `RecordingBackend` records what the request paths settle).

### 7. Reserve once, settle once, in every gRPC endpoint

File: `model_gateway/src/routers/grpc/pipeline.rs` — Do: `GrpcRouter::execute_reserved` (`router.rs`) makes one `RateLimitCell` per logical request for every typed route (`route_chat_impl`, `route_generate_impl`, `route_messages_impl`, `route_completion_impl`, `route_embeddings_impl`, `route_classify_impl`, `route_decisions_impl`, `route_responses_impl`) and calls `close_unsettled` on a non-2xx answer; `RateLimitReserveStage` is the `rate_limit` field of `PipelineStages`, run right after preparation for every endpoint and a no-op unless the caller set `rate_limit_cell`; a Responses request reserves per iteration under `iteration_charge(meta)` (a fresh `request_charge_id`). Settlement lives here, not in the stage: `settle_reservation(cell, usage)` with `recorded_settlement`, `completion_settlement`, `generate_settlement`, `prompt_only_settlement` (embeddings, classify) and `decisions_settlement` building `UsageSettlement { actual_input_tokens, completion_tokens, cached_input_tokens, reasoning_tokens }` from the engine's counts. Streaming defers: `RateLimitCell::take_for_streaming_handoff` hands the `SharedReservationHandle` to the stream, which carries it as a `ReservationAttachment` (`rate_limit/reservation.rs`) in `worker::GuardedStream` (`worker/stream.rs`), so an aborted or disconnected stream still releases it; the cell's `Drop` abandons an un-handed-off reservation (CAS-guarded, first resolution wins). The HTTP router is not covered.
Verify: `cargo test -p smg --test grpc_tests tenant_rate_limiting` → `denial_returns_429_with_retry_after`, `non_streaming_settle_uses_real_usage_not_just_the_estimate`, `embeddings_denial_reaches_the_client`, `embeddings_settle_the_engine_prompt_count`, `a_failed_embeddings_request_keeps_its_reservation_debit` pass.
Trap: a new gRPC endpoint that skips `execute_reserved` or never calls `settle_reservation` compiles and leaks or under-charges; the tenant test's per-endpoint pairs are the pattern to copy.

### 8. Gate

Run `smg:contribute`.

## Rules

- One global bucket at cost `1.0`; per-tenant limiting is `rate_limit/`, priority admission is `middleware/scheduler/`.
- `server.rs` calls `middleware::scheduler::AdmissionMode::from_config` once and layers either `priority_admission_middleware` (`Priority`) or `ConcurrencyLimitLayer::new(app_state)` (`Legacy`, only with a rate limiter) innermost of the protective layers, after tenant resolution. Under `priority_scheduler_enabled` the scheduler owns concurrency and the cap is ignored, but with `rate_limit_tokens_per_second > 0` the bucket survives on `SchedulerState.rate_limiter` as a pre-admission check (`scheduler/admission.rs`: `try_take(1.0)`, never returned).
- With `refill_rate == 0`, `acquire` waits indefinitely in FIFO order for a returned token (`token_bucket.rs::acquire`); always use `acquire_timeout`, as the middleware does.
- Acquire and return amounts must match: hold the `TokenPermit` for as long as the work lasts instead of returning tokens by hand.
- Bucket math is `f64`; `try_acquire`/`return_tokens` `debug_assert` finite, non-negative inputs.
- Re-exported from `middleware/mod.rs`: `AdmissionQueue`, `ConcurrencyLimitLayer`, `TokenBucket`; `TokenPermit` is public in `concurrency.rs`; `QueueDepthGuard`, `admit_from_queue` and `hand_permit` are private to it.

# Rate Limiting & Concurrency in SMG

One mechanism, two knobs. A single **global** (per-process) `TokenBucket` (`model_gateway/src/middleware/token_bucket.rs`) backs both the in-flight concurrency cap and the request rate limit. It is **not** per-tenant or per-route: `app_state.context.rate_limiter: Option<Arc<TokenBucket>>` is one bucket, and `concurrency_limit_middleware` acquires exactly `1.0` token per request regardless of tenant (`concurrency.rs::concurrency_limit_middleware`). Per-tenant admission is a *separate* subsystem — the priority scheduler (`AdmissionMode::Priority`, `server.rs::with_admission_layer`); don't conflate them.

The bucket's two parameters map straight to config (`app_context.rs::maybe_rate_limiter`):

| `TokenBucket::new` arg | RouterConfig field | Meaning |
|---|---|---|
| `capacity` | `max_concurrent_requests: i32` | Burst size / max in-flight. `<= 0` disables rate limiting entirely (`rate_limiter = None`). |
| `refill_rate` | `rate_limit_tokens_per_second: Option<i32>`, coerced via `.filter(|&t| t > 0).unwrap_or(max_concurrent_requests)` | Tokens/sec. **`None`, `0`, or negative all fall back to `max_concurrent_requests`** — a configured `0` behaves identically to leaving the field unset, so semaphore mode is *not* reachable through this config path. |

A token is **not** returned when the handler returns — `TokenGuardBody` wraps the response body and calls `return_tokens_sync(1.0)` on `Drop`, i.e. only after the whole (possibly streamed) body is delivered (`concurrency.rs`, `TokenGuardBody::drop`). So `capacity` genuinely bounds concurrent *streams*, not just handler invocations.

When the bucket is empty, the request is enqueued on a bounded `mpsc` channel (`queue_size`); `QueueProcessor::run` drains it, granting a token or returning `408 REQUEST_TIMEOUT` after `queue_timeout_secs`. A full queue → `429 TOO_MANY_REQUESTS`; queue disabled (`queue_size == 0`) → `429` immediately (`concurrency.rs::concurrency_limit_middleware`).

## Primary task: tune the limits

These are plain `RouterConfig` fields with CLI flags already wired in `main.rs` (`--max-concurrent-requests`, `--queue-size`, `--queue-timeout-secs`, `--rate-limit-tokens-per-second`, all under `help_heading = "Rate Limiting"` on `CliArgs`). No code change needed to *set* them — set via CLI or YAML. Defaults: `max_concurrent_requests: -1` (disabled), `queue_size: 100`, `queue_timeout_secs: 60` (`config/types.rs`, `RouterConfig`'s `Default`).

Common configurations:

- **Burst == steady rate (the closest to a pure concurrency cap):** `max_concurrent_requests=64`, leave `rate_limit_tokens_per_second` unset (or any `<= 0`, which coerces to the same). 64-burst + 64 req/s refill. Note: there is **no** config value that yields a true semaphore (refill_rate 0) via `maybe_rate_limiter` — a configured `0` is filtered out and falls back to `max_concurrent_requests`.
- **Rate limit + burst:** `max_concurrent_requests=200` (burst), `rate_limit_tokens_per_second=50` (steady 50 req/s).
- **Default (field unset):** refill rate falls back to `max_concurrent_requests`, so it acts as both a 64-burst and a 64 req/s limit.

## Adding a new knob

If the task needs a *new* tunable (e.g. per-token cost instead of `1.0`, or a separate read/write bucket), it is a config field — follow the **two-path rule** in @config-plumbing.md (add to `config/types.rs` `RouterConfig` + its `Default`, the CLI flag in `main.rs`, **both** `RouterConfigBuilder` setters in `config/builder.rs` and the `to_router_config` wiring, then Python/Go bindings). The rate-limit fields are good templates: `rate_limit_tokens_per_second` (`config/types.rs`), builder `rate_limit_tokens_per_second`/`maybe_rate_limit_tokens_per_second` (`builder.rs`).

### Step 1: Plumb the field

Mirror `rate_limit_tokens_per_second` end to end per @config-plumbing.md.

**Verify:** `cargo check -p smg`

### Step 2: Consume it where the bucket is built or acquired

Construction lives in `maybe_rate_limiter` (`app_context.rs`). Per-request behavior (token cost, branching) lives in `concurrency_limit_middleware` (`concurrency.rs`). The `TokenBucket` API you have: `try_acquire(f64) -> Result<(),()>`, `acquire_timeout(f64, Duration)`, `return_tokens_sync(f64)`, `available_tokens() -> f64`. Acquire and return amounts **must match** or the bucket drifts.

```rust
// in concurrency_limit_middleware, if cost is configurable:
let cost = app_state.context.router_config.rate_limit_cost as f64;
if token_bucket.try_acquire(cost).is_ok() {
    let response = next.run(request).await;
    let (parts, body) = response.into_parts();
    // TokenGuardBody MUST return the SAME amount on drop:
    let guarded = TokenGuardBody::new(body, token_bucket, cost);
    Response::from_parts(parts, Body::new(guarded))
}
```

**Verify:** `cargo check -p smg`

**Anti-pattern:** `try_acquire(cost)` but `TokenGuardBody::new(.., 1.0)` — tokens leak/accumulate and the limiter silently stops working. The `1.0` literal appears in **three** places in `concurrency.rs` (immediate path, queued path, guard); keep them consistent.

### Step 3: Record the outcome metric

Both admit/reject paths already call `Metrics::record_http_rate_limit(...)` with `metrics_labels::RATE_LIMIT_ALLOWED` / `RATE_LIMIT_REJECTED` (`observability/metrics.rs::record_http_rate_limit`). Reuse it; don't add a parallel counter. See @observability-feature.md for hot-path label rules.

**Verify:** `cargo check -p smg`

### Step 4: Test

`token_bucket.rs` has a `#[cfg(test)]` module covering refill, `refill_rate=0`, and notify-on-return — extend it. For middleware behavior, assert the 429-on-full-queue / 408-on-timeout paths.

**Verify:** `cargo test -p smg`

## Wiring reference (cite, don't reinvent)

- Bucket built once at startup: `app_context.rs::maybe_rate_limiter`, stored on `AppContext.rate_limiter`.
- Limiter + queue processor created and spawned in `server.rs::startup` — `ConcurrencyLimiter::new(rate_limiter.clone(), queue_size, Duration::from_secs(queue_timeout_secs))` returns `(ConcurrencyLimiter, Option<QueueProcessor>)`; `proc.run()` is spawned for the server's lifetime. `limiter.queue_tx` lands on `AppState.concurrency_queue_tx`.
- Middleware installed as a `route_layer` on protected/realtime/multipart routes via `with_admission_layer` (`server.rs::with_admission_layer`). That function is **always** called for those routes and switches internally on `AdmissionMode`: it installs `concurrency_limit_middleware` in `Legacy` mode and `priority_admission_middleware` in `Priority` mode. So when `priority_scheduler_enabled`, the token bucket is **bypassed** entirely in favor of the priority scheduler — verify which path your deployment uses before assuming the token bucket runs.
- All types re-exported from `middleware`: `ConcurrencyLimiter, QueueProcessor, QueuedRequest, TokenGuardBody, concurrency_limit_middleware, TokenBucket` (`middleware/mod.rs`).

## Critical rules

- One global bucket. Per-request cost is `1.0`. No per-tenant/per-route limiting here — that's the priority scheduler (`middleware/scheduler/`).
- `max_concurrent_requests <= 0` ⇒ rate limiting fully off (`None`, pass-through). The `-1` sentinel is the disable signal, not a value.
- `refill_rate == 0.0` ⇒ `acquire` waits **indefinitely** for a returned token (`token_bucket.rs`); always pair with `acquire_timeout` (the queue processor does, `concurrency.rs::QueueProcessor::run`).
- Acquire amount must equal the `TokenGuardBody` return amount. The guard returns on body-drop, not handler-return — required for streaming correctness.
- Bucket math uses `f64`; `try_acquire`/`return_tokens` `debug_assert` finite, non-negative inputs.

## Quality gate

Invoke `smg:contribute` to run fmt -> clippy -> test -> bindings -> commit.

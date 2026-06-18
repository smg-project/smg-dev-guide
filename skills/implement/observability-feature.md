# Adding Observability Features to SMG

Three pillars: Prometheus metrics (40+), OpenTelemetry tracing, structured logging via `tracing` crate.

## Adding Metrics

### Step 1: Describe at startup

```rust
describe_counter!("my_metric_total", "Description of what this counts");
describe_histogram!("my_latency_ms", "Description of what this measures");
```

### Step 2: Record on hot path with string interning

```rust
use crate::observability::metrics::intern_string;

// Dynamic labels MUST use intern_string to avoid allocation per request
let model = intern_string(&model_id);
counter!("my_metric_total", "model" => model).increment(1);
histogram!("my_latency_ms").record(elapsed_ms as f64);
```

**Anti-pattern:** Using raw strings for labels on hot paths — unbounded allocations, label cardinality explosion.

**Anti-pattern:** interning dynamic per-request path segments. The HTTP metrics layer labels by the matched axum route *template* (`matched_path_label` / `MatchedPath` in `model_gateway/src/middleware/metrics.rs`), with an `"other"` fallback when no route matched, to bound cardinality — the interner never evicts.

Static values for common cases (zero allocation):
```rust
status_code_to_static_str(200)  // → Some("200")
bool_to_static_str(true)        // → "true"
```

### Step 3: Verify exposure

Metrics exposed via Prometheus `/metrics` endpoint (served on port **29000** by default, set via `--prometheus-port`).

**Verify:** `curl localhost:29000/metrics | grep my_metric`

## Adding Tracing

The codebase records fields on the current span manually — it does NOT use `#[instrument]`, and `tracing::Span` has no `set_attribute` (that is OTel-only). See `model_gateway/src/middleware/logging.rs`.

```rust
use tracing::Span;

let span = Span::current();
// Fields must be declared (as Empty) when the span is created, then filled in:
span.record("model_id", req.model_id.as_str());
span.record("worker_url", url.as_str());
```

- OTel context is bridged in `model_gateway/src/observability/otel_trace.rs`; trace context propagates through gRPC metadata (see @grpc-backend.md)
- Runtime self-observability lives in `model_gateway/src/observability/runtime_metrics.rs`: a background observer task (`spawn_observer`) runs an event-loop canary (sleeps 10ms in a loop, records `smg_tokio_event_loop_delay_seconds`, increments `smg_tokio_event_loop_stalls_total` when wake drift exceeds the threshold) plus a ~1s `RuntimeMetrics` sampler (queue depth, alive tasks, worker count, per-worker busy ratio, parks) — all exposed on the Prometheus `/metrics` endpoint.

## Logging Rules

**Use `tracing`, NEVER `println!`/`eprintln!`** (clippy warns).

```rust
use tracing::{debug, info, warn, error};
info!(worker_url = %url, model_id = %id, "Worker registered");
warn!(error = %e, "Health check failed");
```

Module-specific levels:
```bash
RUST_LOG=smg::routing=trace cargo run
```

## Key Rules

- `intern_string()` for all dynamic label values
- `tracing` crate only, no `println!`
- Structured fields on spans, not string interpolation
- GaugeHistogram for in-flight tracking (see `gauge_histogram.rs`)

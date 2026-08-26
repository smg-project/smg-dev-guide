# Adding Observability Features to SMG

Three pillars: Prometheus metrics (90+ described, `smg_`-prefixed except the legacy `router_*` names in `crates/mesh/src/metrics.rs`), OpenTelemetry tracing, structured logging via `tracing` crate.

## Adding Metrics

### Step 1: Describe in `init_metrics()`

**File:** `model_gateway/src/observability/metrics.rs::init_metrics` (called by `start_prometheus`; it also calls `runtime_metrics::describe`, `smg_mesh::init_mesh_metrics`, `middleware/scheduler/metrics.rs::describe` and `metrics.rs::allocator_stats::describe`).

```rust
describe_counter!("smg_my_metric_total", "Description of what this counts");
describe_histogram!("smg_my_stage_duration_seconds", "Description of what this measures");
```

`start_prometheus` attaches histogram buckets **by name**: `Matcher::Suffix("duration_seconds")`, `Matcher::Suffix("ttft_seconds")`, `Matcher::Suffix("tpot_seconds")`, plus a `Matcher::Full` for the event-loop canary. Any other histogram name renders as a summary (quantile lines only) unless you add a `Matcher` there — so name duration histograms `_duration_seconds` and record `as_secs_f64()`, never milliseconds.

### Step 2: Record on hot path with the right interner

```rust
use crate::observability::metrics::intern_string;

// intern_string is for SERVER-controlled labels only (worker URLs, matched
// route templates, gateway-set error codes). Interned strings are never freed.
let worker = intern_string(worker_url);
counter!("smg_my_metric_total", "worker" => worker).increment(1);
histogram!("smg_my_stage_duration_seconds").record(elapsed.as_secs_f64());
```

**Client-controlled labels** (request `model` IDs, MCP tool names) must NOT go through `intern_string`. They use the bounded interners in `observability/metrics.rs`: `intern_model_label` / `intern_tool_label`, both over `intern_bounded_label(map, cap, s)` — 1024 distinct values per kind, everything past the cap collapses to the `"other"` sentinel. All three are **private**, so a metric with a client-controlled label is added as a `Metrics::` method inside `metrics.rs` (pattern: `Metrics::record_router_request`); a new label kind needs its own `DashMap` + cap constant passed to `intern_bounded_label`.

**Anti-pattern:** `intern_string(&model_id)` or any other raw client input — the interner never evicts, so it is an unbounded memory and Prometheus series leak.

**Anti-pattern:** interning dynamic per-request path segments. The HTTP metrics layer labels by the matched axum route *template* (`matched_path_label` / `MatchedPath` in `model_gateway/src/middleware/metrics.rs`), with an `"other"` fallback when no route matched.

Static values for common cases (zero allocation):
```rust
status_code_to_static_str(200)  // → Some("200")
bool_to_static_str(true)        // → "true"
```

### Step 3: Verify exposure

Metrics exposed via Prometheus `/metrics` endpoint (served on port **29000** by default, set via `--prometheus-port`).

**Verify:** `curl localhost:29000/metrics | grep smg_my_metric`

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
- Runtime self-observability: `observability/runtime_metrics.rs::spawn_observer` runs an event-loop canary (10ms sleep loop, records `smg_tokio_event_loop_delay_seconds`, increments `smg_tokio_event_loop_stalls_total` past the drift threshold) plus a ~1s `RuntimeMetrics` sampler (queue depth, alive tasks, worker count, per-worker busy ratio, parks).

## Logging Rules

**Use `tracing`, NEVER `println!`/`eprintln!`** (clippy warns).

```rust
use tracing::{debug, info, warn, error};
info!(worker_url = %url, model_id = %id, "Worker registered");
warn!(error = %e, "Health check failed");
```

Probe routes (`/health`, `/readiness`, `/liveness`) attach the `ProbeResponse` marker via `health.rs::mark_probe`; `ResponseLogger` (`middleware/logging.rs`) then logs them at DEBUG. Any new probe route must do the same or its 503 ERROR-floods once per poll.

Module-specific levels — targets are module paths under the `smg` crate, and a set `RUST_LOG` replaces the default workspace filter entirely (`observability/logging.rs::init_logging` / `build_workspace_filter`), so always include a base level:
```bash
RUST_LOG=info,smg::policies=debug cargo run -p smg --bin smg -- <args>
```
`--bin smg` is required: the package declares two bin targets (`smg`, `amg`) and no `default-run`. Routing decisions log at DEBUG from `policies/registry.rs` ("Sticky routing decision") and `policies/cache_aware.rs::log_tree_decision` ("Cache-aware selection").

## Key Rules

- `intern_string()` for server-controlled label values only; client-controlled ones go through the bounded `intern_model_label`/`intern_tool_label` (cap 1024, then `"other"`)
- `tracing` crate only, no `println!`
- Structured fields on spans, not string interpolation
- GaugeHistogram for in-flight tracking (see `gauge_histogram.rs`)

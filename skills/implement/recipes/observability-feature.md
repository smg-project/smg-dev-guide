---
recipe: observability-feature
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - model_gateway/src/observability/
  - model_gateway/src/middleware/metrics.rs
  - model_gateway/src/middleware/logging.rs
  - crates/external_router/src/metrics.rs
  - model_gateway/tests/security/control_plane_roles_test.rs
  - model_gateway/src/server/posture.rs
exemplars:
  - 1f3ac2b3   # TTFT/TPOT histograms with their own Matcher::Full bucket edges, render-on-scrape tests
  - c3965743   # a per-worker request counter: describe, record in the dispatch stage, worker registry
  - ce30f50d   # POST /heap_profile: a control-plane route joins WRITE_ROUTES and the posture text
---

# Add a metric, span field or log line

Three pillars: Prometheus metrics (about 160 `describe_*!` calls in `model_gateway/src/observability/metrics.rs`, `smg_`-prefixed except the legacy `router_*` names in `crates/mesh/src/metrics.rs`), OpenTelemetry tracing bridged in `observability/otel_trace.rs`, and structured logging through the `tracing` crate.
Label constants and the bounded interners live in `crates/external_router/src/metrics.rs` (`metrics_labels`, `intern_model_label`, `intern_tool_label`, `bool_to_static_str`); `Metrics::` methods in `observability/metrics.rs` are the recording surface.

Not this recipe:
- Admission and rate-limit counters already exist (`record_http_rate_limit`, `record_admission_*`): @rate-limit-feature.md.

## Inputs

| Input | Example | Used in |
|---|---|---|
| metric name | `smg_<stage>_duration_seconds` | `init_metrics`, `histogram_bucket_overrides`, the hot path |
| label source | server-controlled (worker URL) or client-controlled (model id) | `intern_string` vs `Metrics::interned_model_label` |
| route | `POST /heap_profile` | `READ_ROUTES`/`WRITE_ROUTES`, `server/posture.rs` |

## Steps

### 1. Describe the metric

File: `model_gateway/src/observability/metrics.rs` — Do: add `describe_counter!("smg_<thing>_total", "...")` or `describe_histogram!("smg_<stage>_duration_seconds", "...")` to `init_metrics()` (`pub(crate)`; it also calls `allocator_stats::describe`, `runtime_metrics::describe`, `history_metrics::describe`, `smg_mesh::init_mesh_metrics` and `scheduler_metrics::describe` from `middleware/scheduler/metrics.rs`). `start_prometheus` calls it last, after `set_global_recorder`.
Verify: `curl localhost:29000/metrics | grep "# HELP smg_<thing>"` → the help text is present.
Trap: a `describe_*!` that runs before the recorder is installed is kept by the no-op recorder: `/metrics` shows `# TYPE` with no `# HELP`.

### 2. Give a histogram its buckets

File: `model_gateway/src/observability/metrics.rs` (`histogram_bucket_overrides`) — Do: the exporter renders a histogram only for a name that matches one of the 15 `Matcher`s and a summary (quantile lines only) for every other name. `Matcher::Suffix` covers `duration_seconds`, `ttft_seconds` and `tpot_seconds` with the request-latency buckets (`--prometheus-duration-buckets` replaces those); `Matcher::Full` covers `TIME_TO_FIRST_TOKEN_SECONDS` (`smg_router_time_to_first_token_seconds`) and `REQUEST_TIME_PER_OUTPUT_TOKEN_SECONDS` with their own edges, `EVENT_LOOP_DELAY_SECONDS`, `smg_cache_aware_match_ratio`, `smg_kv_event_lag_seconds`, `smg_kv_index_lookup_seconds`, `smg_kv_event_apply_seconds`, `smg_worker_retry_backoff_seconds`, `symphony_telemetry::MALFORMED_BYTES`, `smg_mm_processing_seconds`, `smg_mm_media_fetch_seconds`, `smg_mm_media_per_request`. Name a duration `_duration_seconds` and record `as_secs_f64()`, or add a `Matcher::Full` with its own edges.
Verify: `curl localhost:29000/metrics | grep "smg_<name>_bucket"` → `le` buckets, not `quantile` lines.
Trap: a histogram ending in `_seconds` but not `duration_seconds` compiles, scrapes, and renders as a summary.

### 3. Record on the hot path with the right interner

File: `model_gateway/src/observability/metrics.rs` — Do: `intern_string(worker_url)` (`pub(crate)`, never freed) is for server-controlled values only: worker URLs, matched route templates, gateway-set error codes. A client-controlled label (request `model` ids, MCP tool names) goes through the bounded `Metrics::interned_model_label(model_id)`, which caps the distinct values and collapses the rest into `metrics_labels::MODEL_OTHER` (`"other"`); such a metric is a `Metrics::` method in `metrics.rs` (pattern `Metrics::record_router_request`, `Metrics::record_mm_processing`), and a new client-controlled label kind gets its own bounded interner beside it (`intern_tool_label` is the model). The HTTP layer labels by the matched axum route template (`matched_path_label`/`MatchedPath` in `model_gateway/src/middleware/metrics.rs`, `"other"` when nothing matched). Static values cost nothing: `status_code_to_static_str(200)`, `bool_to_static_str(true)`.
Verify: `cargo test -p smg metrics` → the interner tests pass.
Trap: `intern_string(&model_id)` or any raw client input is an unbounded memory and series leak; a bare `counter!(..., "model" => model_id)` compiles.

### 4. Register at zero and test the scrape

File: `model_gateway/src/observability/metrics/tests.rs` — Do: a family that must be visible before its first event is initialised to zero in `init_startup_series` (`metrics.rs`; `tests/metrics_eager_registration_test.rs` scrapes it through `start_metrics_server`), a per-table one in `regular/symphony/telemetry.rs::init_table_series` (called from `create_worker.rs` once the worker is registered; `server.rs` calls that module's `init_startup_series`). Add a render test with `test_support::render_with_recorder` asserting the rendered lines (cf. `encode_path_activity_registers_every_path_and_reason_on_scrape`, `record_engine_load_sets_core_gauges_per_dp_rank`).
Verify: `cargo test -p smg --test metrics_eager_registration_test` and `cargo test -p smg observability::metrics::tests`.
Trap: a counter first created on its first event is absent from every earlier scrape, so `rate()` and alerts on it start late.

### 5. Record span fields

File: `model_gateway/src/middleware/logging.rs` — Do: fields are declared `Empty` when the span is created (`request_id = Empty`, `trace_id`, `status_code`) and filled with `span.record("field", value)` on `Span::current()`; the codebase uses no `#[instrument]`, and `tracing::Span` has no `set_attribute` (OTel only). Trace context reaches engines through gRPC metadata (@grpc-backend.md). Runtime self-observability: `observability/runtime_metrics.rs::spawn_observer` runs the event-loop canary (10ms sleep loop recording `smg_tokio_event_loop_delay_seconds`, incrementing `smg_tokio_event_loop_stalls_total` past the drift threshold) and a ~1s `RuntimeMetrics` sampler (queue depth, alive tasks, worker count, per-worker busy ratio, parks).
Verify: `cargo check -p smg` → an undeclared field is a runtime no-op, so check the span macro too.

### 6. Log through `tracing`

File: `model_gateway/src/observability/logging.rs` — Do: `info!(worker_url = %url, model_id = %id, "Worker registered")`, `warn!(error = %e, "Health check failed")`; never `println!`/`eprintln!` (`print_stdout`/`print_stderr` are `warn` in the workspace `Cargo.toml`). Probe routes (`/health`, `/readiness`, `/liveness`) call `health.rs::mark_probe`, which attaches the `ProbeResponse` marker so `ResponseLogger` (`middleware/logging.rs`) logs them at DEBUG. Targets are module paths under the `smg` crate, and a set `RUST_LOG` replaces the workspace filter (`init_logging`/`build_workspace_filter`), so include a base level: `RUST_LOG=info,smg::policies=debug cargo run -p smg --bin smg -- <args>`; `--bin smg` is required (bins `smg` and `amg`, no `default-run`). Routing decisions log at DEBUG from `policies/registry.rs` ("Sticky routing decision") and `policies/cache_aware.rs::log_tree_decision` ("Cache-aware selection").
Verify: `cargo clippy -p smg -- -D warnings` → no print lints.
Trap: a new probe route without `mark_probe` floods ERROR with its 503 once per poll.

### 7. Register a control-plane route

File: `model_gateway/tests/security/control_plane_roles_test.rs` — Do: a new control-plane route joins `READ_ROUTES` (`user` role reaches it) or `WRITE_ROUTES` (`admin` only), and the posture text in `model_gateway/src/server/posture.rs` (`open_posture_warning`; its test asserts every route string). `POST /heap_profile` (`observability/heap_profile.rs`, handler `dump_heap_profile` in `server.rs`, `tests/heap_profile_test.rs`) is the model.
Verify: `cargo test -p smg --test security_tests control_plane_roles` → the role matrix covers the route.
Trap: a route added to `server.rs` alone is served without a role check and no test notices.

### 8. Expose

File: `model_gateway/src/main.rs` — Do: nothing new; `/metrics` is served on `--prometheus-port` (default 29000).
Verify: `curl localhost:29000/metrics | grep smg_<thing>`.

### 9. Gate

Run `smg:contribute`.

## Rules

- `intern_string()` for server-controlled label values only; client-controlled ones go through the bounded `Metrics::interned_model_label` (capped, then `"other"`).
- `tracing` crate only, no `println!`; structured fields on spans and events, not string interpolation.
- In-flight tracking uses `GaugeHistogramVec` (`observability/gauge_histogram.rs`), not a hand-rolled gauge pair.
- Histograms record seconds (`as_secs_f64()`), never milliseconds.

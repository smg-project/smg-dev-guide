---
recipe: config-plumbing
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - model_gateway/src/config/
  - model_gateway/src/main.rs
  - model_gateway/src/cli/
  - model_gateway/src/server.rs
  - bindings/python/src/lib.rs
  - bindings/python/src/smg/router_args.py
  - bindings/python/tests/
exemplars:
  - 0e08a253   # feat: --max-connections
  - 9411f19f   # feat: --admin-port / --admin-host
  - c6db769e   # feat: PD readiness thresholds
  - 3766d720   # feat: media fetch timeouts (also reaches grpc_servicer)
---

# Add a config field or CLI flag

`RouterConfig` (`model_gateway/src/config/types.rs`) is assembled through the hand-written `RouterConfigBuilder` (`config/builder.rs`) in `CliArgs::to_router_config` (`main.rs`); `to_server_config` returns a `ServerConfig` literal that carries the whole `RouterConfig` nested. `RouterConfigBuilder::build()` runs `ConfigValidator` (`config/validation.rs`) for the CLI and the Python bindings alike. Python rebuilds the chain in `bindings/python/src/lib.rs` and exposes it in `router_args.py`.

Not this recipe: a provider `RoutingMode` variant (@provider-api.md); a discovery provider's config (@discovery-provider.md); a flag the engine servicer owns (@engine-servicer.md).

## Inputs

| Input | Example | Used in |
|---|---|---|
| name and type | `max_connections: Option<u32>` | steps 1–6 |
| flag group | `ServingArgs` (listener), `WorkerArgs`, `RoutingArgs`, `DiscoveryArgs`, `ModelArgs`, `IntegrationArgs` | step 3 |
| default and the disabling zero | `None`; `0` disables | steps 1, 3 |
| invariants | range, cross-field | step 5 |
| who reads it | `server::startup` (top-level `ServerConfig`) or a module (nested in `RouterConfig`) | step 4 |
| launcher and chart twins | `--max-connections` in `router_args.py`, Helm value | step 6 |

## Steps

### 1. Field

File: `model_gateway/src/config/types.rs` — Do: add `#[serde(default, skip_serializing_if = "Option::is_none")] pub <field>: Option<T>` (a non-`Option` field with a non-zero default takes `#[serde(default = "default_<field>")]` and a `fn default_<field>()` the `Default` impl reuses, cf. `default_job_queue_capacity`); add it to the `Default` impl.
Verify: `cargo build`
Trap: without `#[serde(default)]` already-serialized configs stop deserializing; the backward-compat tests in `types.rs` `mod tests` catch it.

### 2. Builder setter

File: `model_gateway/src/config/builder.rs` — Do: add `pub fn <field>(mut self, v: Option<T>) -> Self` beside the existing setters (cf. `RouterConfigBuilder::health_check_port`; `maybe_api_key` for an `Option<impl Into<String>>`). The builder is hand-written: `.field(..)` does not exist until you write it.
Verify: `cargo build`

### 3. CLI flag

File: `model_gateway/src/main.rs` — Do: add the `#[arg(long, value_parser = ..., help_heading = "...")]` field to the flattened group it belongs to (`CliArgs` flattens `RoutingArgs`, `WorkerArgs`, `DiscoveryArgs`, `ServingArgs`, `ModelArgs`, `IntegrationArgs`; the value is read as `self.serving.<field>`). Shared value parsers live in `model_gateway/src/cli/value.rs`; a flag-specific one may stay in `main.rs`. A rename keeps the old spelling with `visible_alias` (cf. `--cache-match-threshold`, test `alias_flags_parse_identically_to_canonical`).
Verify: `cargo build`
Trap: no `value_parser` → an invalid value is accepted and crashes at runtime instead of parse time.

### 4. Wire both paths

File: `model_gateway/src/main.rs` — Do: add `.<field>(self.<group>.<field>)` to the `RouterConfig::builder()` chain in `to_router_config`. A RouterConfig-only field needs nothing in `to_server_config`: it rides nested. A listener-level setting read by `server::startup` off `ServerConfig` (`host`, `port`, `max_connections`, timeouts, …) is a field on `pub struct ServerConfig` (`server.rs`) and is set in all three literals: `main.rs:to_server_config`, `bindings/python/src/lib.rs` (`Router::start`), and the `server.rs` test helper.
Verify: a `<field>_flows_into_router_config` (or `_both_configs`) test in `main.rs` `mod tests` built on `cli_args_from(&[..])` (cf. `health_check_port_flows_into_both_configs`); `cargo test -p smg flows_into`
Trap: a `ServerConfig`-level field wired only through the builder compiles and `server::startup` silently reads the default.

### 5. Validation

File: `model_gateway/src/config/validation.rs` — Do: add the check to the matching `ConfigValidator::validate_*` (`validate_server_settings`, `validate_policy`, `validate_discovery`, `validate_compatibility`, …) returning `ConfigError::InvalidValue { field, value, reason }`.
Verify: `cargo test -p smg validation`
Trap: an invariant only in the clap `value_parser` is bypassed by Python callers, who reach the builder directly.

### 6. Python launcher

File: `bindings/python/src/lib.rs` — Do: append the parameter last in the `#[pyo3(signature = (...))]` of `Router::new` (positional callers keep their binding), store it on the pyclass, add `.<field>(..)` to the builder chain in `to_router_config`. File: `bindings/python/src/smg/router_args.py` — Do: add a keyword-only field at its alphabetical place after the `_: dataclasses.KW_ONLY` marker (never at the tail; the positional prefix `worker_urls`, `host`, `port` is frozen) and one argparse option with the same name, default and second spelling. Full procedure: @bindings-update.md.
Verify: `make python-dev && cd bindings/python && pytest -q tests` — `tests/test_cli_parity.py` fails on a flag without a launcher option, `tests/test_router_args_parity.py` on a constructor parameter the launcher never sets, `tests/test_arg_parser.py` on field order, `tests/test_helm_chart_args.py` on a chart argument that drifted.
Trap: a missing builder call in `lib.rs` compiles; Python launches silently run the Rust default.

### 7. Twins outside the gateway

File: `deploy/helm/smg/` — Do: expose a chart-facing flag in the chart (pinned by `test_helm_chart_args.py`). File: `grpc_servicer/` and `bindings/python/src/servicer.rs` — Do: when the engine servicer mirrors the flag (timeouts, media limits), add it there too (@engine-servicer.md).
Verify: `cd bindings/python && pytest -q tests/test_helm_chart_args.py tests/test_servicer_args.py`

### 8. Tests

File: `model_gateway/src/config/types.rs` `mod tests` — Do: a `serde_json` round-trip with and without the field (cf. `test_health_check_port_serde_roundtrip_and_backward_compat`). File: `model_gateway/tests/` — Do: a `*_startup_test.rs` for a listener-level setting. Update full struct literals of a changed struct: `DiscoveryConfig` is an enum whose `Kubernetes(..)` literal appears in `main.rs:to_router_config` and `bindings/python/src/lib.rs`; `ServerConfig` has the three literals from step 4; `RouterConfig` test literals are `..Default::default()` spreads.
Verify: `cargo test -p smg`

### 9. Gate

Run `smg:contribute`.

## Rules

- The Go SDK (`bindings/golang/`) carries no `RouterConfig` surface; skip it.
- Deprecated flags are kept and tested rather than deleted (the `--kv-indexer-*` test in `main.rs`); retire a flag by alias, not by removal.
- Parse at the boundary, store typed; a `String` re-parsed on every request is a smell.
- `--help` is grouped by `help_heading`; a flag without one lands in the unsorted tail.

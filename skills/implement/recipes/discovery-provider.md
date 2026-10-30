---
recipe: discovery-provider
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - model_gateway/src/service_discovery/
  - model_gateway/src/config/types.rs
  - model_gateway/src/main.rs
  - bindings/python/src/smg/router.py
  - e2e_test/discovery/
  - .github/workflows/e2e-discovery.yml
  - deploy/helm/smg/
exemplars:
  - 2fae47be   # file provider (#2897)
  - b2dabeb4   # Slurm provider (#4013)
  - 1a696593   # Consul provider (#4137)
---

# Add a service-discovery provider

A provider reads one source and publishes `DiscoveredWorker`s; the shared reconciler (`reconciler.rs`) owns registration, the `smg.ai/discovery-*` ownership labels and removal, and never learns the source.
The contract is `provider.rs` (`DiscoveredWorker`, `DiscoveryKind`); `snapshot.rs` keeps the last good read (`LastGood`) and counts what a read left out (`SkipLog`); `runtime.rs` turns a `DiscoveryConfig` into the running provider.
Model on `consul.rs` (the full shape: blocking reads, skips, credentials) or `file.rs` (the smallest provider).
Every surface below is one the file, Slurm and Consul providers all touched.

Not this recipe:
- A field every provider emits, or anything a discovered worker carries into registration: @discovery-feature.md (`fingerprint()` decides what re-registers a worker).
- Mesh router-peer discovery under `model_gateway/src/mesh/discovery/`: @mesh-feature.md.
- The RL control plane's worker discovery (`crates/rl/src/discovery.rs`): a different subsystem.

## Inputs

| Input | Example | Used in |
|---|---|---|
| `<provider>` | `consul` | the file name, `DiscoveryKind::as_label`, the `--discovery-provider` value, the `provider:` tag, `DISCOVERY_PROVIDER_CHOICES`, Helm `router.discovery.provider` |
| `<Provider>DiscoveryConfig` | `ConsulDiscoveryConfig` | `model_gateway/src/config/types.rs`: the `DiscoveryConfig` variant, which the Python `discovery` mapping also reads |
| `<Provider>ProviderConfig` | `ConsulProviderConfig` | the provider file; the `RuntimeDiscoveryConfig` variant |
| `--<provider>-*` flags | `--consul-service` | `DiscoveryArgs` in `main.rs`; `RouterArgs` fields such as `consul_service`; the Helm values block |
| `DISCOVERY_<PROVIDER>` | `DISCOVERY_CONSUL` | `metrics_labels` in `crates/external_router/src/metrics.rs` |
| `SMG_<PROVIDER>_E2E` | `SMG_CONSUL_E2E` | the e2e lane's gate and its job in `e2e-discovery.yml` |

## Steps

### 1. Write the provider

File: `model_gateway/src/service_discovery/<provider>.rs` — Do: a `pub struct <Provider>ProviderConfig` with `new(&<Provider>DiscoveryConfig, &RoutingMode)` that refuses a mode `Roles::of` returns `None` for; a read of the source into `Vec<DiscoveredWorker>` plus the `Skip`s it left out (one bad record is skipped alone; a read that fails is a `SnapshotError`); `start_<provider>_discovery(config, app_context)` spawning a loop that feeds `LastGood::update` and calls `LastGood::reconcile` on every read and every `check_interval` tick, as `start_consul_discovery` does. The `discovery_id` is the source's own stable identity of the instance; endpoints come from `endpoint_at`.
Verify: `cargo test -p smg service_discovery::<provider>` → the module's tests pass against a scripted source (`consul.rs` replays answers; `slurm.rs` fakes a `SlurmClient`), never the real one.
Trap: a failed read handed to `LastGood::update` as an empty `Ok` removes every worker; as `Err` it keeps the last good snapshot and counts on `smg_discovery_snapshot_errors_total`.

### 2. Register the kind

File: `model_gateway/src/service_discovery/provider.rs`, `model_gateway/src/service_discovery/mod.rs`, `crates/external_router/src/metrics.rs` — Do: a `DiscoveryKind::<Provider>` with its `as_label` (the value stamped on every worker it registers) and `metric_label`, backed by a new `metrics_labels::DISCOVERY_<PROVIDER>`; `mod <provider>;` and `pub use <provider>::<Provider>ProviderConfig;` in `mod.rs`.
Verify: `cargo check -p smg` → every `match` on `DiscoveryKind` is exhaustive, so the compiler lists what is still missing.
Trap: `as_label` is an identity, not a display name: changing it later orphans every worker stamped with the old value.

### 3. Add the configuration

File: `model_gateway/src/config/types.rs`, `model_gateway/src/config/validation.rs` — Do: a `<Provider>DiscoveryConfig` (serde defaults; `check_interval_secs` through `default_discovery_check_interval_secs`), a `DiscoveryConfig::<Provider>` variant (the enum is tagged `provider`, `snake_case`; `deserialize_discovery` needs no change) and its `From` impl; a `validate_discovery` arm calling `validate_<provider>_discovery`, which reuses `validate_record_discovery` when records name their own worker type.
Verify: `cargo test -p smg config::` → a test shaped like `tagged_consul_discovery_reads_with_defaults` and one like `test_validate_consul_discovery` pass for the new variant.

### 4. Resolve it at runtime

File: `model_gateway/src/service_discovery/runtime.rs` — Do: a `RuntimeDiscoveryConfig::<Provider>(<Provider>ProviderConfig)` variant, its `from_config` arm (the one conversion the CLI and the Python binding share) and its `start_service_discovery` arm.
Verify: `cargo test -p smg service_discovery::runtime` → a `<provider>_settings_reach_the_runtime` test beside `consul_settings_reach_the_runtime` passes.

### 5. Expose it on the CLI

File: `model_gateway/src/main.rs` — Do: a `DiscoveryProvider::<Provider>` variant (`#[value(name = "<provider>")]`, `flag_value`); the `--<provider>-*` flags in `DiscoveryArgs` under `help_heading = "Service Discovery (<Provider>)"`; the arm in `discovery_config()` that builds the config, a `MissingRequired` error naming the flag the provider cannot run without, and a `has_<provider>_flags()` guard that makes the flags without their provider an `IncompatibleConfig`.
Verify: `cargo test -p smg --bin smg provider` → tests shaped like `discovery_provider_consul_builds_a_consul_config` and `consul_flags_need_the_consul_provider` pass.
Trap: without the guard, `--<provider>-*` flags given without `--discovery-provider` are read as nothing: the gateway starts with no discovery and no error.

### 6. Teach the Python launcher

File: `bindings/python/src/smg/router_args.py`, `bindings/python/src/smg/router.py` — Do: the name in `DISCOVERY_PROVIDER_CHOICES`; `<provider>_*` dataclass fields (kept alphabetical) and an argparse group `Service Discovery (<Provider>)` with the CLI's spellings; a `_MappedProvider("<provider>", {field: mapping key}, required=(...))` in `_MAPPED_PROVIDERS`. Nothing changes in `bindings/python/src/lib.rs`: the tagged mapping goes through `parse_discovery` into `deserialize_discovery`.
Verify: `pytest bindings/python/tests/test_cli_parity.py bindings/python/tests/test_router_args_parity.py bindings/python/tests/test_startup_sequence.py` → with a `<PROVIDER>_DISCOVERY` `RouterArgs` added to the parity parametrize and a `test_from_args_passes_the_<provider>_provider_as_a_discovery_mapping`, all pass.
Trap: `test_every_discovery_field_is_routed` checks only the field prefixes it names (`slurm_`, `consul_`, `discovery_`); add `<provider>_` or a field left out of `_MappedProvider.fields` passes it and reaches `_Router` as an unknown keyword at launch.

### 7. Test against recordings and the real reconciler

File: `model_gateway/src/service_discovery/testdata/<provider>/`, `model_gateway/tests/discovery/<provider>_discovery_test.rs` — Do: record the real API's or command's answers per supported release with a `README.md` saying what was run and what the recordings showed (`model_gateway/src/service_discovery/testdata/consul/README.md`), `include_str!` them in the provider's tests and parse each one. When the source can be faked in-process, drive the real registry and job queue through `start_service_discovery` as `file_discovery_test.rs` does (add, update in place, remove, broken source keeps the fleet) and add the `mod` to `model_gateway/tests/discovery/mod.rs`; a source that needs a real system (Slurm, Consul) gets `live_app_context` tests in its module instead.
Verify: `cargo test -p smg service_discovery::<provider> && cargo test -p smg --test discovery_tests` → one parse test per recorded release, and the integration scenarios pass.
Trap: a hand-written fixture passes against the shape you assumed; `Service.Meta` being `null` and catalog nodes having an empty `Node.ID` came out of the recordings.

### 8. Add the e2e lane

File: `e2e_test/discovery/<provider>/` (`conftest.py`, `harness.py`, `test_<provider>_discovery.py`), `.github/workflows/e2e-discovery.yml` — Do: a `<provider>_gateway()` returning `common.Gateway` with the flags that select the provider (`consul_gateway` is the model; subclass `Gateway` when the gateway must run elsewhere, as `ControllerGateway` does); a `pytest_collection_modifyitems` that skips the lane unless `SMG_<PROVIDER>_E2E=1`; a job after `build` that downloads `discovery-binaries` and runs the lane with `--confcutdir`.
Verify: `cargo build -p smg -p mock-worker` then `SMG_<PROVIDER>_E2E=1 pytest e2e_test/discovery/<provider> --confcutdir e2e_test/discovery/<provider>` → add, remove, an invalid record skipped alone, a lost source keeping the fleet, and a gateway restart all converge.
Trap: every `conftest.py` sees the whole session's items; a skip not limited to `item.path.is_relative_to(HERE)` marks the other lanes skipped whenever yours is off.

### 9. Offer it in the Helm chart

File: `deploy/helm/smg/values.yaml`, `deploy/helm/smg/values.schema.json`, `deploy/helm/smg/templates/_helpers.tpl`, `deploy/helm/smg/README.md` — Do: a `router.discovery.<provider>` block and the name in the schema's `provider` enum; in `_helpers.tpl`, render the flags in `smg.routerArgs` beside the `slurm` and `consul` arms and refuse a provider without what it cannot start with in `smg.validateDiscovery`; mounts or variables in `deploy/helm/smg/templates/deployment-router.yaml` only when the provider reads files or the environment (Consul's token and TLS); a row in the README's Worker Discovery table and an example under `deploy/helm/smg/examples/`.
Verify: `pytest bindings/python/tests/test_helm_chart_args.py` (needs `helm`) → with the provider added to `PROVIDERS`, `test_each_provider_reaches_the_launcher_as_that_provider` renders it and parses it back.

### 10. Gate

Run `smg:contribute`.

## Rules

- The reconciler never changes for a provider: ownership is `DISCOVERY_PROVIDER_LABEL`, identity `DISCOVERY_ID_LABEL`, configuration `DISCOVERY_SPEC_HASH_LABEL`; the worker API refuses the `smg.ai/discovery-*` prefix.
- One bad record is a `Skip` (counted on `smg_discovery_skipped_total`, logged when it first appears) and the rest of the read applies; a read that cannot be trusted whole is an error.
- `validation.rs` checks only what the config alone can tell; what the source says is checked on every read, because the source changes while the gateway runs.
- Credentials never arrive as flags: Consul reads `CONSUL_HTTP_TOKEN` and the TLS files from Consul's own variables, keeps them out of `Debug`, and refuses a variable it does not implement rather than ignore it.
- A name in `DISCOVERY_PROVIDER_CHOICES` without a `_MappedProvider` makes `Router.from_args` raise (`test_from_args_rejects_a_provider_it_cannot_pass`), so a half-wired provider never starts the router without discovery.
- A new metric family in `model_gateway/src/observability/metrics.rs` only for a new kind of event; a provider is a new `source` label value on the existing discovery metrics.

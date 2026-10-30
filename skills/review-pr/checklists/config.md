# Checklist: config plumbing and bindings

- [ ] `RouterConfig` field: `#[serde(default)]`, in the `Default` impl, a hand-written setter in `config/builder.rs`, used in `to_router_config` (`main.rs`); invariants in `config/validation.rs`, not only in a clap `value_parser`.
- [ ] Top-level `ServerConfig` field (read by `server::startup`): set in all three literals (`main.rs:to_server_config`, `bindings/python/src/lib.rs`, the `server.rs` test helper).
- [ ] The flag sits in the right flattened group of `CliArgs` (`RoutingArgs`, `WorkerArgs`, `DiscoveryArgs`, `ServingArgs`, `ModelArgs`, `IntegrationArgs`) with a `help_heading`; a renamed flag keeps `visible_alias`.
- [ ] A `*_flows_into_*_config` test in `main.rs` for a new flag; a startup test for a listener-level setting.
- [ ] Python threaded end to end: `Router::new` pyo3 signature (appended last) → pyclass field → builder call in `lib.rs::to_router_config` → a keyword-only `RouterArgs` field at its alphabetical place in `router_args.py` with its argparse option. `bindings/python/tests/test_cli_parity.py`, `test_router_args_parity.py`, `test_arg_parser.py` and `test_helm_chart_args.py` pin the parity.
- [ ] New `PolicyConfig` variant: `factory.rs` **both** `create_from_config` and `create_by_name`, `validate_policy`, the `--policy` value_parser lists, `PolicyType` in `lib.rs`, `policy_from_str` in `router.py`, `COMMON_POLICY_CHOICES` in `router_args.py`.
- [ ] ZMQ knobs reach `router_args.py` and `smg serve`; `derive_handshake_port` and `_zmq_handshake_port` (`bindings/python/src/smg/serve.py`) stay in sync.
- [ ] A flag the engine servicer mirrors also lands in `grpc_servicer/` and `bindings/python/src/servicer.rs`.

| Anti-pattern | Consequence | Look for |
|---|---|---|
| Builder chain updated, `ServerConfig` literals not | `server::startup` reads the default | the field missing from one of the three literals |
| Missing setter in `config/builder.rs` | does not compile; the builder is hand-written | `RouterConfigBuilder` without `.field()` |
| Missing `#[serde(default)]` | existing serialized configs stop deserializing | new fields in `config/types.rs` |
| Invariant only in clap | Python bypasses clap | `config/validation.rs` lacks the check |
| `RouterArgs` field appended at the tail or made positional | the field-order tests fail | not alphabetical after `KW_ONLY` |
| Missing Python builder call | compiles; Python runs the Rust default | `lib.rs::to_router_config` chain |
| `ServerConfig` literal in `lib.rs` missing the field | `maturin develop` fails | `Router::start` |

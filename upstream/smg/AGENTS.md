# Working in SMG with a coding agent

SMG (Shepherd Model Gateway) is a Rust gateway in front of LLM inference engines (SGLang, vLLM, TensorRT-LLM, TokenSpeed, MLX) and cloud providers. This file is the orientation an agent needs before touching code. The detailed guides are linked; the `smg` plugin (`smg-project/smg-dev-guide`) adds per-subsystem recipes, a review checklist and a one-command gate.

## Read first

- `CONTRIBUTING.md`: the pre-PR gate, commits, PRs, the PD vocabulary, the three rules for code agents. `REVIEW.md`: severity markers and focus areas. smg-docs `contributing/development.md` and `contributing/code-style.md`.
- The module map: `model_gateway/src/lib.rs` lists the gateway's modules; each crate's `src/lib.rs` opens with what it owns; `crates/symphony/docs/architecture.md` is the model for crate documentation.

## Invariants stated nowhere else

1. **Config has two paths.** `to_router_config` (`main.rs`) builds `RouterConfig` through the hand-written builder in `config/builder.rs`; `to_server_config` returns a `ServerConfig` literal. A listener-level setting read by `server::startup` needs the top-level copy in every `ServerConfig` literal (`main.rs`, `bindings/python/src/lib.rs`, the `server.rs` test helper); a `RouterConfig` field rides nested. Validation in `config/validation.rs` runs in `RouterConfigBuilder::build()` for the CLI and Python alike. Python repeats the chain in `bindings/python/src/lib.rs` and `bindings/python/src/smg/router_args.py` (keyword-only, alphabetical); `bindings/python/tests/test_cli_parity.py` and `test_router_args_parity.py` pin it.
2. **Worker metadata flows as labels.** Discovery providers emit `DiscoveredWorker`s; one reconciler (`service_discovery/reconciler.rs`) registers them; labels become the `ModelCard` in `workflow/steps/local/create_worker.rs`. Never a parallel `_override` field on `WorkerSpec`, never a `ModelCard` write after `build_model_card`.
3. **Symphony is the default parser.** `crates/symphony` reads a model's output through a format table per family (`src/formats/`, `registry.rs`, `groups.json`). `--parser legacy` selects `crates/tool_parser` and `crates/reasoning_parser`. New model support is a table, not a legacy parser.
4. **`ipc://` is ZMQ.** `BackendClient` (`routers/grpc/backend_client.rs`) is the transport seam between gRPC and the same-host ZMQ lane (`crates/engine_zmq_client` wire, `crates/engine_zmq_adapter` translation, shared with `crates/engine_servicer`). Wire structs are positional msgpack: append only. `ZmqDialect`, `BackendClient` and `ProviderType` are closed sets: every `match` writes every arm.
5. **Protocol types are shared.** `crates/protocols` holds the types every consumer reads, spelled as the OpenAI, Anthropic and Gemini specs spell them; a field only one crate writes belongs in `model_gateway`.
6. **The hot path owns nothing twice.** Request bodies move by value and die with the `RequestLease` (`routers/common/request_lease.rs`); upstream bodies are sized and capped (`routers/common/mod.rs`); per-token work in `routers/grpc/regular/streaming.rs` clones nothing; metric labels are interned and bounded; overload is a latched flag (`worker/overload.rs`), not a per-request walk.
7. **Vocabulary.** A disaggregated dispatch has two **sides** (`PdSide`, `PrefillBound`, `DecodeBound`); a worker has a **role** (`WorkerRole`); the workers of one role are a **pool**. Nothing is called a "leg" or a dispatch "arm". Metric names keep their published spelling.

## Commands

```
cargo +nightly fmt --all
cargo clippy --workspace --all-targets --all-features -- -D warnings   # drop --all-features without system OpenCV (bash scripts/install_opencv.sh)
cargo test -p <package>                                                  # the workspace is large; scope it
make python-dev                                                          # after config/, crates/protocols/ or bindings/ changes
cargo run -p smg --bin smg -- --help                                     # two bins, no default-run
cargo run -p mock-worker -- --help                                       # routing without GPUs
```

## CI rejects

A commit without `git commit -s` (the trailer must match `git config user.name <user.email>`); a `Co-authored-by` or `Signed-off-by` line naming Claude or `noreply@anthropic.com`; `--no-verify`; a branch outside `<type>/<description>` or `<username>/<description>`; a PR title outside `type(scope): summary`; a `Cargo.toml` change without its `Cargo.lock`; `#[allow]` where `#[expect(lint, reason = "...")]` is meant; `reqwest::Client::new` instead of the crate's client factory; `tokio::spawn` without a justification at the call site; a PR body missing the template headers.

## Agents

Install the plugin: `claude plugin marketplace add smg-project/smg-dev-guide && claude plugin install smg@smg-dev-guide`. Then `/smg:map` to orient, `/smg:implement` to build with a recipe, `/smg:craft` for the house style, `/smg:review-pr` to review (what `REVIEW.md` asks for), `/smg:contribute` to run the gate. The three rules from `CONTRIBUTING.md`: you own the PR, not the agent; paste real gate output; no AI attribution anywhere.

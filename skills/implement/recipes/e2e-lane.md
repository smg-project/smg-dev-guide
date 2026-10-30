---
recipe: e2e-lane
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - e2e_test/fixtures/
  - e2e_test/infra/constants.py
  - e2e_test/infra/worker.py
  - e2e_test/pyproject.toml
  - .github/workflows/pr-test-rust.yml
  - .github/workflows/e2e-gpu-job.yml
exemplars:
  - b90b0282   # a chat case with engine/gpu/model markers, its harness module and the CPU tests that pin it
  - 7ac5b4d1   # the e2e-cpu-mock lane: inline job, finish gate, marker and MODEL_SPECS edits
  - a52b43f6   # a lane knob end to end: e2e-gpu-job.yml input, E2E_PARSER getter, gateway flag, test_parser_lane.py
---

# Add an e2e test or CI lane

A lane is one pytest run over `e2e_test/` with lane variables in its environment. `pytest_collection_modifyitems` (`e2e_test/fixtures/hooks.py`) keeps the items whose `engine` marker names `E2E_ENGINE` and whose `gpu` marker equals `E2E_GPU_TIER`, applies the wire filters (`_filter_zmq_items` under `E2E_CONNECTION_MODE=zmq`, the Rust-servicer filters), sorts the rest by `(backend, model)` for the worker pool and exits the run below the `E2E_MIN_SELECTED` floor.
The class-scoped `setup_backend` fixture (`e2e_test/fixtures/setup_backend.py`) starts the class's workers and gateway from its markers; `e2e_test/infra/worker.py` builds each engine's command in `Worker._build_cmd`.
GPU lanes are jobs of `.github/workflows/pr-test-rust.yml` that call the reusable `.github/workflows/e2e-gpu-job.yml`, chosen per pull request by the tier table in `detect-changes`; CPU lanes are inline jobs (`e2e-cpu-mock`, `e2e-vendor`) or workflows of their own (`e2e-discovery.yml`, `e2e-mcp-mock.yml`).

Not this recipe:
- Rust unit and integration tests under `model_gateway/tests/` and `crates/*/tests/` (the subsystem's own recipe)
- the discovery suites under `e2e_test/discovery/` and `e2e-discovery.yml` (discovery-feature)
- the nightly and benchmark workflows (`nightly-*.yml`, `e2e_test/benchmarks/`)

## Inputs

| Input | Example | Used in |
|---|---|---|
| Suite directory | `e2e_test/chat_completions` | the module's home, the lane's `test_dirs`, its `TIERS` row |
| Engines and GPU tier | `@pytest.mark.engine("sglang", "vllm")`, `@pytest.mark.gpu(1)` | the lane rows that select the class: an engine's row of a lane whose `gpu_tier` matches |
| Model id | `meta-llama/Llama-3.2-1B-Instruct` | `@pytest.mark.model`; a key of `MODEL_SPECS` (`e2e_test/infra/model_specs.py`) |
| Backend param | `grpc`, `http`, `pd_grpc`, `("epd_grpc", (1, 1, 1))`, `openai` | the `setup_backend` parametrize value; the wire filters read it |
| Lane id and area | `e2e-1gpu-chat-symphony`, `chat-completions` | the job key in `pr-test-rust.yml`; the `skip-chat-completions` output its `if:` reads |
| Lane knob | `E2E_PARSER` | an `e2e-gpu-job.yml` input, its `env:` line, a getter in `e2e_test/infra/constants.py` |

## Steps

### 1. Put the case in the suite its lane runs

File: `e2e_test/<suite>/test_<name>.py` — Do: one class per backend configuration, decorated with `@pytest.mark.engine(...)`, `@pytest.mark.gpu(<n>)`, `@pytest.mark.model("<id>")` and `@pytest.mark.parametrize("setup_backend", ["grpc", "http"], indirect=True)`; the fixture yields `(backend_name, model_path, client, gateway)`. `@pytest.mark.workers(count=, prefill=, decode=, gpus=, extra_engine_args=)` and `@pytest.mark.gateway(policy=, extra_args=, env=)` shape the fleet, `@pytest.mark.skip_for_runtime("trtllm", reason=...)` skips one engine's gap, and a keyword of `model` (`tokenspeed="<id>"`, read by `model_id_for_engine`) swaps the model for one engine. Copy `e2e_test/chat_completions/test_function_calling.py` (a class on the fixture, two clients) or `test_servicer_warmup.py` (one worker started by hand with `start_workers`).
Verify: `make generate-python-types && pip install ./e2e_test clients/python && E2E_ENGINE=<engine> E2E_GPU_TIER=<n> pytest --collect-only e2e_test/<suite>/test_<name>.py` → the `e2e selection:` line counts the class as selected, not under `deselected by engine`.
Trap: a class without an `engine` marker is deselected from every GPU lane and from `e2e-cpu-mock`, which all export `E2E_ENGINE` (a cloud class carries `@pytest.mark.vendor(...)` and `@pytest.mark.gpu(0)` for `e2e-vendor` instead); a missing `gpu` marker reads as `gpu(1)`, so a 2-GPU class lands in the 1-GPU lanes and fails there.

### 2. Keep the case right on the variant lanes

File: `e2e_test/fixtures/hooks.py` — Do: read the filters before adding a skip. A ZMQ lane keeps single-worker `grpc`/`http` items only and collapses the pair into one run (`_filter_zmq_items`, `_zmq_dedup_key`); a Rust-servicer lane drops what `_filter_sglang_rust_items` and `_filter_tokenspeed_rust_items` name (EPD; for TokenSpeed also `test_admin_ops.py` and plain fleets). A case a lane cannot serve belongs in those filters, counted in `_format_selection_line`, not behind a `pytest.skip` that passes green. A class for the mock engine (`@pytest.mark.engine("mock")`) names a tokenizer-only model (`mock=` keyword, a `MODEL_SPECS` entry with `skip_tier_download`) and states its answers through the `mock_answers` fixture.
Verify: `E2E_CONNECTION_MODE=zmq pytest --collect-only e2e_test/<suite>/test_<name>.py` → the `e2e selection:` line's `by zmq-dedup` count is your collapsed `http` twin alone, and nothing else of yours is dropped.
Trap: removing or deselecting cases can push a lane under its `min_selected` (`_enforce_selection_floor` exits the run); adding many leaves the floor stale: set the row's `min_selected` in `pr-test-rust.yml` to about 95 % of the new selected count.

### 3. Register a marker or a model

File: `e2e_test/fixtures/hooks.py` — Do: a new marker is one `config.addinivalue_line` in `pytest_configure`, read through `resolve_class_marker` so a child class overrides its parent (`e2e_test/pyproject.toml` registers only `e2e`, `slow`, `external`, `kind`, for the suites that run with `--confcutdir`). A new model is a `MODEL_SPECS` entry (`model`, `tp`, `features`, engine args); `scripts/ci_download_model.sh --gpu-tier <n>` fetches every spec with `tp` at most `<n>` unless it sets `skip_tier_download`, which then needs the lane's `extra_models`.
Verify: `pytest --collect-only -W error::pytest.PytestUnknownMarkWarning e2e_test/<suite>` → collects.
Trap: an unregistered marker only warns, and `_get_marker` returns None for a misspelt one: the class silently runs with the defaults.

### 4. Add a lane knob

File: `.github/workflows/e2e-gpu-job.yml` — Do: an `inputs` entry of `workflow_call` with a blank default, exported in the job's `env:` as the lane variable (the test step's `env:` for what only pytest reads, such as `E2E_MIN_SELECTED`); a getter beside `get_parser` in `e2e_test/infra/constants.py` where blank means the default and an unknown value raises; the consumer reads the getter (`Gateway._build_base_cmd` in `e2e_test/infra/gateway.py` for a gateway flag, `Worker._build_env` for a worker variable, `pytest_collection_modifyitems` for a selection rule); export it from `e2e_test/infra/__init__.py`.
Verify: a module like `e2e_test/infra/test_parser_lane.py` (unset, blank, each value, a bad value raises) passes in the step 7 run.
Trap: a knob the job never exports is unset on every lane, so CI only ever runs the getter's default branch.

### 5. Add the lane job

File: `.github/workflows/pr-test-rust.yml` — Do: copy the nearest sibling (`e2e-1gpu-chat-symphony` is a one-knob variant of `e2e-1gpu-chat`; `e2e-2gpu-pd` a matrix behind a prerequisite lane). Keep the `if:` shape: `always() && !cancelled()`, the prerequisite's `result == 'success'`, `needs.detect-changes.result == 'success'` on a pull request, and `needs.detect-changes.outputs.skip-<area> != 'true'`; `uses: ./.github/workflows/e2e-gpu-job.yml` with `engine`, `gpu_tier`, `runner` (`vars.SMG_RUNNER_GPU_1 || '1-gpu-h100'`), `timeout`, `test_timeout`, `test_dirs`, `min_selected`, `secrets: inherit`; a matrix row the paths do not reach passes `enabled: false`. A CPU lane is an inline job (`e2e-cpu-mock`) or a workflow of its own with `on.pull_request.paths` (`e2e-mcp-mock.yml`).
Verify: `python3 -c "import yaml, sys; yaml.safe_load(open(sys.argv[1]))" .github/workflows/pr-test-rust.yml` → no output; the pull request's run shows the job under its `name:`.
Trap: `timeout` caps the job and `test_timeout` the pytest step; a job cap under setup plus the step ends `cancelled` with its cases passing, and `finish` fails `cancelled` like `failure`.

### 6. Route paths to the lane and gate the merge on it

File: `.github/workflows/pr-test-rust.yml` — Do: in the `Decide the e2e lanes` step of `detect-changes`, give the suite a `TIERS` row (`("e2e_test/<suite>/**", "<area>")`; a path no row matches reaches every lane) and, for a new area, add it to `AREAS`, to the `skip-<area>` outputs of `detect-changes`, and to the `AREAS` tuple of `scripts/tests/test_ci_amd_path_filters.py`; then list the job in `finish.needs` and add its `needs.<job>.result` line to the `Check CI result` step.
Verify: `pytest -q scripts/tests/test_ci_amd_path_filters.py` → passes (it runs the step's Python on sample paths); on the next CI run the `Gate-integrity lint` step of `finish` prints `OK: all N e2e-*/rust-* jobs gate merge`.
Trap: that lint runs in CI only and matches job ids starting with `e2e-` or `rust-`; a lane named otherwise (`go-bindings-e2e`) is gated only by the lines you add by hand.

### 7. Pin the harness change with a CPU unit test

File: `e2e_test/fixtures/test_hooks_env_filter.py` for a selection rule (build `_FakeItem`s, call the filter, assert kept and deselected and the summary line) or `e2e_test/infra/test_<engine>_cmd_builder.py` for a launcher (`Worker._build_cmd` under a patched environment, as `e2e_test/infra/test_mock_cmd_builder.py` does) — Do: one test per branch of the new rule; the `--noconftest` run imports `fixtures` and `infra` directly, so no module may need a GPU or a running backend at import time.
Verify: `pip install ./e2e_test && PYTHONPATH=e2e_test pytest -q --noconftest e2e_test/infra e2e_test/fixtures` → all pass (the `python-unit-tests` job); `ruff check e2e_test/` and `mypy e2e_test/ --config-file mypy.ini` clean (the `python-lint` job).
Trap: `python-unit-tests` runs both directories whole, so a new module is collected; `scripts/ci_run_tooling_tests.py` runs a listed subset for stacked branches, so add a `REGRESSIONS` pair only when the suite must run there too.

### 8. Gate

Run `smg:contribute`.

## Rules

- Tests read lane variables through the `e2e_test/infra/constants.py` getters (`get_runtime`, `get_connection_mode_override`, `effective_parser`), not a bare `os.environ.get("E2E_...")`: blank means the default and a wrong value raises when first read.
- Every dropped item goes through `pytest_deselected` and a counter in the `e2e selection:` line; a filter that drops silently hides a shrinking lane.
- `test_dirs` is what the lane runs; `e2e-gpu-job.yml` adds `--ignore` for `e2e_test/benchmarks` and `e2e_test/bindings_go` and the lane's own `test_filter`, nothing else.
- The sglang row of `e2e-1gpu-chat`, `e2e-1gpu-chat-rust-servicer` and `e2e-1gpu-gateway` is the representative engine's: the `chat-one-engine` area runs it alone, `chat-completions` every row.
- A PD or EPD topology rides in the `setup_backend` param (`("pd_grpc", (p, d))`) or in `@pytest.mark.workers(prefill=, decode=)`; both are dropped from ZMQ lanes.
- `pr-test-rust.yml` runs on pull requests against `main` and `release/**` only; the path-triggered workflows (`ci-tooling-tests.yml`, `e2e-mcp-mock.yml`) also run on a pull request against a stacked branch.

# Writing in SMG: vocabulary, names, commits, docs

How SMG's maintainers write: one word per thing, names and commit subjects that state what holds, doc comments that define and promise, test names that read as sentences.
Every rule cites the file (SMG at 176ce3ae, v1.13.0; smg-docs at a16e8ec) or the commit it was read from; where the repositories are silent, this page says so.

## Vocabulary (use / avoid)

| term | meaning or replacement | source |
|---|---|---|
| worker | one serving process the gateway routes to; a worker, a stream or a call "is called what it is" | `CONTRIBUTING.md`:97 |
| side | one half of a disaggregated dispatch: the prefill side, the decode side (`PdSide`, `PrefillBound`, `DecodeBound`) | `CONTRIBUTING.md`:95; `model_gateway/src/routers/common/pd_failure.rs`:30 |
| role | a worker's prefill-decode function, `WorkerRole::{Single, Prefill, Decode}`; compared as a `WorkerType`, not as strings | `CONTRIBUTING.md`:96; `model_gateway/src/policies/mod.rs`:349; 496cc7bb |
| pool | the workers of one role (the encode pool, the decode pool); a router family's weight is the size of its pools | `CONTRIBUTING.md`:96; `model_gateway/src/routers/gateway.rs`:53-57 |
| fleet | every worker the gateway serves | `model_gateway/src/health.rs`:7; `model_gateway/src/routers/gateway.rs`:58 |
| family router | one of the five routers in `ROUTER_FAMILIES` (HTTP, gRPC, their PD forms, EPD); the gateway weighs them per request by pool size | `model_gateway/src/routers/gateway.rs`:1-9, 67-70 |
| lane | a transport the gateway speaks on: the direct ZMQ worker lane beside HTTP and gRPC; in `kv_index`, a thread that drains worker queues; in CI, one job of a matrix | `crates/engine_zmq_adapter/src/lib.rs`:14; `crates/kv_index/src/lane_pool.rs`:27; 47586f86 |
| table | a Symphony format: the terminals, states, transitions and call syntax of one model family ("the DeepSeek V4 table", "the json table") | `crates/symphony/src/format.rs`:1-5; 5847dceb |
| dialect | the engine protocol a ZMQ backend speaks, a closed set (`ZmqDialect`); in Symphony, the JSON variant a template writes | `crates/engine_zmq_adapter/src/client.rs`:97-103; `crates/symphony/src/shape/mod.rs`:272-276 |
| reservation | a tenant rate-limit claim taken once per logical request and settled with real usage: reserve, settle, close, abandon | `model_gateway/src/rate_limit/backend.rs`:1; `model_gateway/src/rate_limit/reservation.rs`:1-4; 5249d338 |
| lease | the single owner of a request's dispatch-phase memory and its release point (`RequestLease`) | `model_gateway/src/routers/common/request_lease.rs`:1, 51-57 |
| snapshot | a published, atomically swapped read of state: `ReadinessSnapshot` for probes, the routing snapshot a retry re-selects from | `model_gateway/src/health.rs`:16-19, 96 |
| posture | the authentication posture: the surfaces a start leaves open, named once in the log | `model_gateway/src/server/posture.rs`:1-8 |
| veto, room, rendezvous | a routing exclusion that steers selection, "never a refusal"; a place in a decode engine's running window that a PD dispatch claims; the prefill-decode bootstrap meeting, counted by side and phase | `model_gateway/src/worker/liveness.rs`:11-24; `model_gateway/src/routers/common/pd_admission.rs`:14-23; `model_gateway/src/observability/metrics.rs`:2417-2422 |
| bellwether, oracle, heal | the reference recorder whose fixtures the tokenizer, Symphony and render tests replay; the reference a test compares against (say which: the Oracle history backend shares the word); a fixture entry that passes again and leaves the unloaded list | smg-docs contributing/development.md:436; `crates/tokenizer/src/encoders/glm53.rs`:449; 6e9af442 |
| servicer, engine | the per-node gRPC server (Python or Rust) in front of an engine: vLLM, SGLang, TokenSpeed, TensorRT-LLM | `crates/engine_zmq_adapter/src/lib.rs`:3-8, 14-16 |
| avoid: leg | meant side, role and worker at once; replaced in code, comments, test names and log lines by six commits (5eea9545, 9f883c2c, dff19c8a, ebbdba7c, 0b553351, 9bdb2c44). Kept only where published: the `leg` metric label, CI matrix "legs", and `test_sole_leg_outage_is_reported_promptly`, which two workflows select by name. Residue at 176ce3ae: 48 Rust lines (the silence messages at `model_gateway/src/routers/grpc/common/stages/request_execution.rs`:1626, 1635 among them) and 119 uses in smg-docs concepts/routing/pd-disaggregation.md | `CONTRIBUTING.md`:91-99, 164; `model_gateway/src/observability/metrics.rs`:2420; `e2e_test/router/test_pd_topologies.py`:1038 |
| avoid: arm (for a side) | no written rule; in the source "arm" is a match arm ("one function per arm") or a verb ("arms a timer"), never a side | 1540b169; `model_gateway/src/middleware/token_bucket.rs`:34 |
| avoid: "Fixed!", "Ran cargo test", "probably passes" | a review reply carries a SHA and a one-line reason; a Test Plan names reproducible scenarios; gate output is pasted | `CONTRIBUTING.md`:60, 103-112 |
| avoid: AI attribution | `Co-authored-by` or `Signed-off-by` naming Claude or noreply@anthropic.com is rejected by hook and CI | .pre-commit-config.yaml:101-114; `.github/workflows/pr-naming-check.yml`:98-103 |
| absent: robust, seamless, leverage, comprehensive, delve, utilize, cutting-edge | 0 uses in 2,050 commit subjects and bodies since 2026-08-20 and 0 in smg-docs content; in SMG Markdown only "comprehensive" 4 (`bindings/golang/README.md`); "simply" 2 in smg-docs, 1 in SMG Markdown, 21 in all Rust doc comments (with 4 "comprehensive", 1 "robust"). Subjects saying improve, cleanup, misc, various or simple: 3 of 2,050 | grep counts at 176ce3ae |

Spelling is checked by codespell with a short allow list; a token cut on purpose is marked for it (.pre-commit-config.yaml:33-48; 8f568d6f).

## Naming

- Cases (smg-docs contributing/code-style.md:94-102): packages kebab (`smg-grpc-client`), crate directories and library names snake (`crates/grpc_client`), modules and functions snake (`get_healthy_worker_indices`), types Pascal, constants screaming (`MAX_TRACKED_SETS`).
- Constructors: `new()` for the plain case, `with_config` and other `with_*` for configured variants; builders validate in `build()` (code-style.md:106-122; `model_gateway/src/config/builder.rs`).
- No `_async` suffix unless the function is the async twin of a blocking one with the same name (`create_tokenizer_async`; code-style.md:124-138).
- A module file is named for what it holds and lives under its subsystem: `worker/worker.rs` became `worker/basic.rs` (2027d48d); the RL registry view moved under `worker/` and router-peer discovery under `mesh/`, "not at the crate root" (0ee3ce2e, 964e14d6).
- A new thing is kept apart from its legacy by an explicit or versioned name: the Mistral table is `mistral_v13`, "apart from the older mistral parser" (1605f789); `--parser legacy` and the `X-SMG-Parser` header keep the older parsers (a52b43f6).
- Flags are kebab, their config fields snake (`--health-check-port`, `health_check_port`: `model_gateway/src/health.rs`:27-28); CI variables are `SMG_`-prefixed screaming (`CONTRIBUTING.md`:154-164); metric names are `smg_`-prefixed snake and keep their published labels (`model_gateway/src/observability/metrics.rs`:2418-2421).
- Lints in code: `#[expect(lint, reason = "...")]`, never `#[allow]`; `Uuid::now_v7`, not `new_v4` (code-style.md:64, 74-86; `clippy.toml`:15).
- A test is named for what it proves and renamed when the name misstates it: "the demoted-worker test is named for the probe that promotes it" (aedfa383).

## Commit messages

- Form: `<type>(<scope>): <summary>` plus a DCO sign-off (`CONTRIBUTING.md`:70-87). The title check admits feat, fix, chore, docs, refactor, test, ci, perf, lint, style, revert, build, an optional lowercase scope and `!` (`.github/workflows/pr-naming-check.yml`:69-78). Since 2026-08-20, 2,002 of 2,050 commits carry a scope; the mix is fix 853, test 278, refactor 255, feat 253, perf 135, ci 103, docs 82.
- `main` takes squash merges only, so the PR title is the commit subject and every subject ends in "(#N)" (smg-docs contributing/index.md:143, 163).
- The summary is a declarative sentence in the present tense about what holds after the change: 62 % open with "the", "a", "an", "every" or "one"; 7 % with an imperative verb (dependabot's "bump" and outside contributions). The first word is lowercase unless a proper noun (Symphony, Kimi, Llama); no final period. Mean length 96 characters, 84 % over 72: the check sets no limit, and the subject says the whole fact.
- 211 subjects name the rejected behaviour with "not", "instead" or "no longer" ("X, not Y"); a docs subject says what the text now says (65b622b2, 8fc79c9d).
- Exemplars:
  - 5eea9545 `refactor(gateway): a worker's prefill-decode function is its role, not its leg`
  - ad80e9dc `fix(gateway): every log line and failure message that names a worker writes its address masked`
  - ff534808 `perf(gateway): a worker's constrained-decoding labels are parsed once at construction, not on every request`
  - 0fa476c1 `fix(gateway): a request with tool_choice none still renders its tools, as the engine's own server does`
  - a6c0a175 `test(gateway): the two Kubernetes watchers' tests share one labelled-pod fixture`
- Bodies: 2,049 of 2,050 commits have none; after the subject come `Signed-off-by` and `Co-authored-by` trailers only. The one body (897ef9a9) explains an enablement change and a review exception. The why lives in the PR body; the body shown in code-style.md:486-493 is the format's example, not the practice.
- Wording commits record rejected phrasing: "says media references, not multimodal requests" (1f24344b); "refused by name, not as an overflow" (6c8004b0); "name private items as code, not as links" (5be8993a, a34dc35f, 143bac0c, 4bc1780e); the series that "say side, role and pool where they said leg" (5eea9545 to 9bdb2c44).

## Pull requests

- The body follows `.github/PULL_REQUEST_TEMPLATE.md`: Description with Problem and Solution, Changes, Test Plan, then the checklist. The review workflow checks that each section is filled and posts a gap list (`.github/workflows/claude-code-review.yml`:98-135).
- The Test Plan names scenarios the reviewer can reproduce; "Ran `cargo test`" is not one (`CONTRIBUTING.md`:103-105).
- Aim for 400 changed lines or fewer; above that, split or agree with reviewers first. One concern per PR: a refactor or a feature, not both (`CONTRIBUTING.md`:106-108).
- Link the issue, `Closes #1234` or `Refs: #1234`; architecture, breaking API, new crates and deprecations start as an issue (`CONTRIBUTING.md`:109; smg-docs contributing/index.md:157).
- Branch `<type>/<desc>` or `<username>/<desc>`, lowercase, checked at push and by CI (.pre-commit-config.yaml:77-91; `.github/workflows/pr-naming-check.yml`:28).
- Merge needs two approvals including a code owner, every thread resolved, and the checks `finish`, `DCO` and `PR Title & Commit Messages`; a non-draft PR idle for 14 days is labelled stale (smg-docs contributing/index.md:158-167).
- Review comments: each inline comment opens with a REVIEW.md severity marker (Important, Nit, Pre-existing) and cites file:line; the summary counts findings per severity; a reply names the commit SHA and a one-line reason (`REVIEW.md`:14-26; `CONTRIBUTING.md`:110-112, 130-132).

## Doc comments

- A `//!` header opens with a one-line definition, "X: what it is", before any detail (first lines with a colon: 127 of 400 headers sampled): "Symphony: one parser for everything a model says." (`crates/symphony/src/lib.rs`:1); "Level-triggered worker reconciliation, shared by every discovery provider." (`model_gateway/src/service_discovery/reconciler.rs`:1); "Each engine's own gRPC-proto surface over the same-host ZMQ engine wire." (`crates/engine_zmq_adapter/src/lib.rs`:1).
- Then the why, with its issue: "# Why this exists (#1694)" and the failure it fixed (`model_gateway/src/health.rs`:5-12; code-style.md:273-283).
- Sections are named for the question they answer and used once each ("# Drain semantics", "# The per-model section", "# Producers", "# Lanes"); generic "# Architecture" and "# Key Features" headers survive only in older modules (`crates/multimodal/src/vision/processors/`, `crates/tokenizer/src/cache/mod.rs`).
- Terms are defined in bold on first use: "A **terminal** is a spelling the model writes" (`crates/symphony/src/format.rs`:7-26).
- Headers state promises and non-goals as plain negatives: "[`LanePool::enqueue`] never blocks and never drops" (`crates/kv_index/src/lane_pool.rs`:13); "Nothing here is specific to a provider" (reconciler.rs:8); "Not k8s-specific, though Kubernetes is the motivating consumer" (health.rs:2-3); "Admission is a *claim*, not a look" (`model_gateway/src/routers/common/pd_admission.rs`:20); "Neither owns the translation; this crate does." (engine_zmq_adapter lib.rs:16).
- Public items are linked, [`Event`]; private items are written as code spans, because `RUSTDOCFLAGS='-D warnings' cargo doc --workspace` runs in CI (`scripts/ci_rust_tests.sh`:220-222; 5be8993a, 9d4c792a).
- A `///` is a sentence saying what the item is and the invariant it keeps: "Only the first of [`Self::settle_success`], [`Self::close_reserved_only`], or `Self::abandon_if_open` takes effect; later calls are no-ops" (`model_gateway/src/rate_limit/reservation.rs`:24-28). `# Arguments` (44) and `# Returns` (21) sections are the older form, in 26 files among 67,623 `///` lines (code-style.md:287-298).
- Inline comments say why, not what (code-style.md:300-316); a silenced lint carries `reason = "..."` (code-style.md:74-86; `clippy.toml`:7-15).

## Tests

- Unit tests sit in a `#[cfg(test)] mod tests` block at the bottom of the file, after imports, constants, types, inherent impls and trait impls (code-style.md:146-184, 324). Integration tests under `model_gateway/tests/` group cases in nested modules named `*_tests` (`model_gateway/tests/routing/load_balancing_test.rs`; code-style.md:324-343).
- A test name is a sentence: subject, verb, outcome, and the condition when it matters. 75 % of 10,606 Rust test functions carry no `test_` prefix; the prefix is the older form (`model_gateway/src/policies/round_robin.rs`:261; code-style.md:347-363, where "test1" is the counter-example).
  - `a_connection_that_sends_nothing_is_closed_at_the_header_read_timeout` (`model_gateway/src/server/connection_timeouts.rs`:787)
  - `a_shared_key_file_warns_once_and_a_private_one_not_at_all` (`model_gateway/src/server/tls.rs`:130)
  - `settle_refills_before_charging_so_idle_time_cannot_erase_the_charge` (`model_gateway/src/rate_limit/local_backend.rs`:307)
  - `misspelled_field_is_rejected_not_silently_ignored` (`model_gateway/src/rate_limit/config.rs`:275)
  - `test_a_new_id_at_the_same_url_replaces_the_worker` (`e2e_test/discovery/file/test_file_discovery.py`:76); `test_passing_instances_are_workers_as_consul_reports_them` (`e2e_test/discovery/consul/test_consul_discovery.py`:42)
- Python: pytest collects `test_*.py`, `Test*` classes and `test_*` functions (`pytest.ini`); the e2e tree is split by API surface and discovery provider (`e2e_test/chat_completions/`, `e2e_test/discovery/kind/`); 58 of 97 files group cases in classes whose docstring says what is proved and what is not (`e2e_test/discovery/kind/test_kind_discovery.py`:468-475).
- Fixtures are shared through one helper or module per crate, not repeated per test (`model_gateway/src/test_support.rs`:1-4); the recent test commits are this move: "the hash policies' tests read the shared worker fixture" (4c09d3b4), "build their contexts through one module" (75020e00).
- Assertions carry a message that states the expectation (code-style.md:365-378). Tests may unwrap, expect and panic (`clippy.toml`:1-4). Fixture-replay tests named `bellwether_*` skip without `BELLWETHER_FIXTURES` (smg-docs contributing/development.md:436).

## Code agents

- `CONTRIBUTING.md`:116-124 sets three rules: you own the PR, not the agent, and read every line before opening it; the agent pastes real `cargo fmt`, `clippy` and `test` output, not "I have run the tests"; no AI attribution in commits, PR bodies or review replies. smg-docs contributing/index.md:173-179 repeats them.
- "Probably passes" is not passing: paste the gate output or re-run (`CONTRIBUTING.md`:48-60).
- The `no-ai-co-author` hook and the CI job reject `Co-authored-by` or `Signed-off-by` lines naming Claude or noreply@anthropic.com (.pre-commit-config.yaml:101-114; `.github/workflows/pr-naming-check.yml`:98-103).
- The vocabulary rule binds generated text too: "leg" does not come back "in code, comments, test names or log lines" (`CONTRIBUTING.md`:99).
- A reviewing agent runs `/smg:review-pr` first, uses the REVIEW.md markers with file:line, and skips a finding it cannot pin to a line (`REVIEW.md`:5-26; `CONTRIBUTING.md`:133-134; `.github/workflows/claude-code-review.yml`:82-88, 171).

## Review questions

1. Does any new name, comment, log line or test say "leg" (or "arm") where side, role, pool or worker is meant?
2. Does the PR title read as the squash commit on `main`: the right type, a lowercase scope, a sentence stating what now holds?
3. Does the Test Plan name scenarios a reviewer can reproduce, and does the gate output appear rather than a claim about it?
4. Does a new module's `//!` say in its first line what it is and then why it exists, with private items as code spans and no header a generic module could carry?
5. Does each test name state the behaviour and its condition, and does each assertion message state the expectation?
6. Does each review reply say what changed and where, or only "Fixed!"?

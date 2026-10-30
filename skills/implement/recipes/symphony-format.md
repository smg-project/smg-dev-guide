---
recipe: symphony-format
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/symphony/src/
  - crates/symphony/tests/
  - crates/symphony/docs/
  - model_gateway/src/routers/grpc/utils/aliases.rs
exemplars:
  - d391b140   # feat(symphony): Mistral list-of-calls table
  - 75a154c9   # feat(symphony): Kimi K2 table
  - 5847dceb   # feat(symphony): Llama 3.1/3.3 read with the json table (groups only)
---

# Add a model family's output format to Symphony

Symphony (`crates/symphony/`, package `smg-symphony`) is SMG's default parser: content, reasoning and tool calls come out as typed events from one `Parser::feed`. A new model family is a **format table** (markers, states, call syntax) that the shared engine runs; the engine does not change. `--parser legacy` (`model_gateway/src/main.rs`) selects the old per-model crates instead. Read `crates/symphony/docs/architecture.md` ("How to add a table") and `docs/tables.md` first.

Not this recipe: a model Symphony's registry does not know and that must keep a legacy parser name (@tool-parser.md, @reasoning-parser.md); a new call syntax (an assembler under `src/json/`, `src/tagged/`, `src/pythonic/` or `src/gemma.rs`, a `CallSyntax` variant in `src/format.rs`, a grammar under `src/grammar/`); a template the shaped syntax can run as data (`crates/response_template`).

## Inputs

| Input | Example | Used in |
|---|---|---|
| chat template | `tokenizer_config.json::chat_template` of the primary checkpoint | step 1 |
| turn opener | `<\|im_start\|>assistant` | step 1 (`opens_turn`), step 2 (`opener` in groups) |
| thought markers and whether the template pre-opens the thought | `<think>` … `</think>` | step 1 (`thinks_first`, `starts_in`) |
| call syntax and markers | JSON object in `<tool_call>` tags, `name(arg=value)`, keyed tags | step 1 (`calls`) |
| recorded outputs | bellwether recordings of the family | steps 1, 4 |
| checkpoints in the group | `org/Primary`, variants under `also` | steps 2, 5 |

## Steps

### 1. Table

File: `crates/symphony/src/formats/<family>.rs` — Do: `Format::new("<family>")` with `.terminal`, `.state(.., Emits::Content | Reasoning | Arguments | Wrapper)`, `.transition`, `.calls(CallSyntax::..)`, `.opens_turn`; `thinks_first`, `starts_in`, `closes_at_stop`, `framing` / `trims` / `keeps`, `stop_tokens`, `marker_tokens`, `with_thought_after`, `without_reasoning`, `without_calls` as the template demands (`src/format.rs`). Model on `olmo3.rs` or the nearest family. Unit tests in the file drive `Engine::new(<family>(), Declared::default())` with `testing::drive`: a thought, an answer, one call, two calls, a cut stream, a marker quoted in the user turn.
Verify: `cargo test -p smg-symphony formats::<family>`
Trap: a wrong terminal classifies calls as content without any error; take markers from the template and the recordings, not from memory.

### 2. Register

File: `crates/symphony/src/formats/registry.rs` — Do: a row in the `tables!` macro (`Variant => "<family>", <family>;`), which spells the variant, the operator-facing name and the builder once. File: `src/formats/mod.rs` — Do: `pub mod` + `pub use`. File: `src/formats/groups.json` — Do: one line per checkpoint group, `{"model": "org/Primary", "also": [...], "table": "<family>", "opener": ..., "after": ...}`; the build script compiles it into `GROUPS`.
Verify: `cargo test -p smg-symphony registry`
Trap: without a `groups.json` line `formats::for_model` never returns the table and the model keeps the legacy parsers. The lookup matches the repository name exactly, so a quantized or renamed checkpoint (`Qwen3-8B-FP8`) needs an `also` entry.

### 3. Contract subject and robustness

File: `crates/symphony/tests/parser/contract.rs` — Do: a `Subject { name, new, outputs, table: Some(Table::<Family>) }` with a handful of outputs in the family's syntax; `every_registry_table_has_a_subject` refuses a table without one. `tests/parser/robustness.rs` picks the table up on its own.
Verify: `cargo test -p smg-symphony --test parser_tests`

### 4. Corpus rows

File: `crates/symphony/tests/bellwether_parse_fixtures.rs` — Do: a `("<recorded-slug>", GenerationPrompt::Plain | OpensTheThought | ModelDecides)` row and, when the family's template writes its own opener, a `MEASURED_OPENERS` entry. Recordings come from `.github/workflows/bellwether-fixtures.yml`.
Verify: `cargo test -p smg-symphony --test bellwether_parse_fixtures`

### 5. Models table and docs

File: `crates/symphony/tests/readme.rs` — Do: a `Group { .. }` row in `GROUPS` for the group (slug, model, variants, release, table, status); then `SYMPHONY_WRITE_README=1 cargo test -p smg-symphony --test readme` regenerates `crates/symphony/README.md`. File: `crates/symphony/docs/tables.md` — Do: a section on what the table decides beyond the others and what it leaves open.
Verify: `cargo test -p smg-symphony --test readme` (a stale table fails)

### 6. Legacy names the table answers to

File: `model_gateway/src/routers/grpc/utils/aliases.rs` — Do: when the family had a legacy parser name (`--tool-call-parser qwen`), move it from `UNANSWERED` into `ALIASES` so the name reads with the table; the tests there (`every_unanswered_name_answers_to_no_table_and_says_why`) and the name tests under `model_gateway/src/routers/grpc/regular/symphony/` pin the pairing.
Verify: `cargo test -p smg aliases`
Trap: a table whose family name is still in `UNANSWERED` is unreachable through `--tool-call-parser`.

### 7. Gate

Run `smg:contribute`. The e2e lane `e2e-1gpu-chat-symphony` and `E2E_PARSER=symphony|legacy` (`e2e_test/infra/constants.py`) exercise the result; function-calling cases live in `e2e_test/chat_completions/test_function_calling.py`.

## Rules

- Every byte of output lands in exactly one event (`Content`, `Reasoning`, `ToolCallStart` / `ToolCallArguments` / `ToolCallEnd`, `Dropped` with a `DropReason`, `Malformed` with a `MalformedReason`, `Finish`); nothing vanishes silently.
- The name in `Format::new`, the `tables!` row and `groups.json` must agree; operators spell it in `--tool-call-parser` / `--reasoning-parser` and in worker labels.
- Do not add a legacy parser for a model Symphony reads.
- The public surface is pinned by `tests/parser/surface.rs`; adding to it is a deliberate API change.
- The fuzz workspace (`crates/symphony/fuzz`) is separate: `cargo +nightly fmt --manifest-path crates/symphony/fuzz/Cargo.toml --all` (the gate runs it; `.github/workflows/symphony-fuzz.yml` fuzzes).

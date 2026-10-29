---
recipe: symphony-format
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/symphony/src/
  - crates/symphony/tests/
  - crates/symphony/docs/
  - crates/response_template/src/
---

# Adding a Model Family's Output Format to Symphony

Symphony (`crates/symphony/`, package `smg-symphony`) is SMG's default parser for everything a model says: content, reasoning and tool calls come out as typed events from one `Parser::feed` entry point. The gateway runs it unless `--parser legacy` (`model_gateway/src/main.rs`; `legacy` selects the per-model `crates/tool_parser` and `crates/reasoning_parser`). Supporting a new model family therefore means a **format table** — a data description of the family's markers, states and call syntax that the shared engine runs — and no engine change.

Read `crates/symphony/docs/architecture.md` ("How to add a table") and `docs/tables.md` first; `crates/symphony/README.md` carries the models table and the public types.

## Decide which case you are in

| Case | What it costs |
|---|---|
| A known call syntax (JSON in tags, Python calls, keyed/XML tags, Gemma, …) with its own markers or template | a table plus evidence — this recipe |
| A checkpoint that reuses an existing family's template | one line in `formats/groups.json` (Step 2 only) |
| A genuinely new call syntax | an assembler under `src/json/`, `src/tagged/`, `src/pythonic/` or `src/gemma.rs`, a `CallSyntax` variant (`src/format.rs`), an arm in the engine's assembler factory, and a grammar module under `src/grammar/`, each with the same evidence. A syntax a response template writes as patterns costs none of that: it is a `shape::CallShape` the shaped syntax runs (`crates/response_template` compiles Hugging Face `chat_parsing` templates) |
| A model Symphony's registry does not know | nothing in Symphony: a worker label or `--tool-call-parser` / `--reasoning-parser` naming a table (`Table::name`) reads it with that table, `hf` reads it with its tokenizer's response template, and a legacy parser's name keeps the legacy crates (@tool-parser.md, @reasoning-parser.md) |

## Inputs to gather first

| Input | Where |
|---|---|
| The chat template | the checkpoint's `tokenizer_config.json` `chat_template`; vLLM / SGLang parsers for the family confirm the markers |
| Turn opener | the text the template writes before the assistant turn (`<|im_start|>assistant`, `<|start_header_id|>assistant<|end_header_id|>`, …) — the engine replays the prompt from it |
| Thought markers and whether the template pre-opens the thought | `<think>` / `</think>` and the like; decides `.thinks_first()` / `.starts_in(...)` |
| Call syntax and its markers | the wrapper tags and the body grammar (JSON object, JSON list, `name(arg=value)`, keyed tags, XML) |
| Recorded outputs | bellwether recordings of the family (a thought, an answer, one call, two calls, a cut stream) |

## Steps

### Step 1: Write the table

**File:** `crates/symphony/src/formats/<family>.rs` — model it on `olmo3.rs` (the smallest table) or the nearest family.

```rust
//! <Family>: what the table reads — the call wrapper, the thought markers, the turn opener,
//! and the checkpoint it was recorded as.

use crate::format::{CallSyntax, Emits, Format};

/// The <Family> table.
pub fn family() -> Format {
    Format::new("family")
        .terminal("calls_open", "<tool_call>")
        .terminal("calls_close", "</tool_call>")
        .state("content", Emits::Content)
        .state("calls", Emits::Arguments)
        .transition("content", "calls_open", "calls")
        .transition("calls", "calls_close", "content")
        .calls(CallSyntax::Json)
        .opens_turn("<|im_start|>assistant")
}
```

The builder on `Format` (`src/format.rs`): `terminal`, `ignores`, `structural_token`, `state` (`Emits::Content | Reasoning | Arguments | Wrapper`), `transition`, `calls(CallSyntax::...)`, `call_id`, `closes_at_stop`, `framing` / `trims` / `keeps`, `stop_tokens`, `marker_tokens`, `opens_turn`, `turn_anchor`, `starts_in`, `thinks_first`, `with_thought_after`, `without_reasoning`, `without_calls`; `validate()` checks the table's shape. Unit tests live in the same file, driving `Engine::new(family(), Declared::default())` with `testing::drive` over the recorded shapes: a thought, an answer, one call, two calls, a cut stream, and a marker quoted inside the user turn (the replay must start at the last turn opener).

**Verify:** `cargo test -p smg-symphony formats::<family>`

**Anti-pattern:** reading the markers from memory or from a vendor's blog post. The template and the recordings are the contract; a wrong terminal silently classifies calls as content.

### Step 2: Register the table

- `src/formats/registry.rs`: a row in the `tables!` macro — `Variant => "family", family;` — which spells the `Table` variant, its operator-facing name and its builder once; `Table::ALL`, `Table::name` and the lookups by name are written from that list.
- `src/formats/mod.rs`: `pub mod family;` and `pub use family::family;`.
- `src/formats/groups.json`: one line per checkpoint group that the table reads — `{"model": "org/Primary", "also": ["Other-Checkpoint"], "table": "family", "opener": null, "after": null}` (`opener` when the group's template writes a turn opener the table does not expect, `after` for text after the thought's close). The build script compiles the file into `GROUPS`; a group naming an unknown table fails the build, and the registry tests hold the names unique and every table buildable.

**Verify:** `cargo test -p smg-symphony registry`

**Anti-pattern:** a table without a `groups.json` line. `formats::for_model` then never returns it, and the gateway keeps reading the model with the legacy parsers.

### Step 3: Give it a contract subject

**File:** `crates/symphony/tests/parser/contract.rs` — add a `Subject { name: "family", new: family, outputs: FAMILY_OUTPUTS, table: Some(Table::Family) }` with a handful of outputs in the family's syntax. The contract checks each at every chunking; `tests/parser/robustness.rs` picks the table up on its own and scrambles its markers; `every_registry_table_has_a_subject` refuses a table without a subject.

**Verify:** `cargo test -p smg-symphony --test parser_tests`

### Step 4: Add a corpus row

**File:** `crates/symphony/tests/bellwether_parse_fixtures.rs` — `("<recorded-slug>", GenerationPrompt::Plain | OpensTheThought | ModelDecides)`: how the template ends the generation prompt. The replay reads the table and the opener from the registry; recordings are refreshed by `.github/workflows/bellwether-fixtures.yml`.

**Verify:** `cargo test -p smg-symphony --test bellwether_parse_fixtures`

### Step 5: Regenerate the README models table

```bash
SYMPHONY_WRITE_README=1 cargo test -p smg-symphony --test readme
```

A stale table fails the build (`tests/readme.rs` writes it from the same groups and checks they agree).

### Step 6: Format the fuzz workspace too

`crates/symphony/fuzz` is a workspace of its own that `cargo fmt --all` from the root does not reach: `cargo +nightly fmt --manifest-path crates/symphony/fuzz/Cargo.toml --all` (pre-commit hook `rustfmt-symphony-fuzz`). `.github/workflows/symphony-fuzz.yml` runs the fuzz targets.

### Step 7: Gateway and e2e

Nothing to wire in the gateway for a table: `formats::for_model` matches the repository name (the text after the last path separator) exactly and case-insensitively, so a quantized or renamed checkpoint (`Qwen3-8B-FP8`) needs an `also` entry or it falls back to the legacy parsers. Lanes: `e2e-1gpu-chat-symphony` runs the chat suite under the default parser; `E2E_PARSER=legacy|symphony` pins a lane (`e2e_test/infra/constants.py::get_parser`); function-calling cases live in `e2e_test/chat_completions/test_function_calling.py`.

**Verify:** `cargo test -p smg-symphony`, then `smg:contribute`.

## Critical rules

- Every byte of output lands in exactly one event — `Content`, `Reasoning`, `ToolCallStart` / `ToolCallArguments` / `ToolCallEnd`, `Dropped` (with a `DropReason`), `Malformed` (returned whole, with a `MalformedReason`), `Finish`. Nothing vanishes silently; a client can have the raw text back.
- The table's name in `Format::new`, the `tables!` row and `groups.json` must agree; operators spell it in `--tool-call-parser` / `--reasoning-parser` and in worker labels.
- Registry lookup is an exact repository-name match, unlike the legacy registries' substring patterns: list variants under `also`.
- Do not add a legacy parser for a model Symphony reads. The legacy crates serve `--parser legacy` and models outside the registry.
- The public surface is pinned by `tests/parser/surface.rs`; adding to it is a deliberate API change.

## Common mistakes

| Mistake | Consequence | Prevention |
|---|---|---|
| Table without a `groups.json` group | model keeps reading with legacy parsers | Step 2 |
| Group without a table of that name | build fails | the name in `tables!` and `groups.json` must match |
| No contract subject | `every_registry_table_has_a_subject` fails | Step 3 |
| README table not regenerated | `tests/readme.rs` fails | Step 5 |
| Fuzz workspace unformatted | pre-commit / CI rustfmt fails | Step 6 |

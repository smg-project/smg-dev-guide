---
recipe: tool-parser
verified: 176ce3ae88f7f857441853c7dc2e087e3277b5c0
level: anchors
watch:
  - crates/tool_parser/src/
exemplars:
  - 9d639713   # MiniMax-M3: parser, structural tag, src/tests.rs mapping test, chat_template.rs toggle, gateway arming
  - 81d43443   # DeepSeek-V4.1: a structural-tag constructor on an existing parser plus its tests/ coverage
  - f22e1067   # Hy4: parser with a streaming.rs sibling, structural tag + reasoning prefix, README row
---

# Add a legacy tool parser

A parser implements `ToolParser` (`crates/tool_parser/src/traits.rs`; `#[async_trait]`, `Send + Sync`): `parse_complete(&self, text)` returns `(String, Vec<ToolCall>)`, `parse_incremental(&mut self, chunk, tools)` returns `StreamingParseResult { normal_text, calls: Vec<ToolCallItem> }` (`types.rs`).
It lives in `crates/tool_parser/src/parsers/<name>.rs`; `ParserFactory::new()` (`crates/tool_parser/src/factory.rs`) registers it by key and maps model IDs to it.
The gateway creates parsers through the factory and pools them behind `Arc<Mutex<..>>` (`get_pooled_parser`), so no `Rc` / `RefCell` / non-`Send` fields.
This recipe is the common "JSON wrapped in tags" shape; check the table at the end before writing a file.

Not this recipe:
- Legacy lane only. At v1.13.0 the default parser is Symphony (`--parser symphony`, @symphony-format.md): new model support goes into a Symphony format table. Follow this recipe for `--parser legacy`, or for a model outside Symphony's registry that must keep a legacy name (`--tool-call-parser` / `--reasoning-parser`).
- A format in the table at the end: reuse or alias the parser named there.

## Inputs

| Input | Example | Used in |
|---|---|---|
| Key | `<name>` (factory key; `--tool-call-parser <name>`) | steps 2-6 |
| Markers | `<tool_call>` / `</tool_call>`; confirm against vLLM (`vllm/tool_parsers`), SGLang (`python/sglang/srt/function_call`) or the HF `tokenizer_config.json` `chat_template` | step 1 |
| Model stems | `<family>-*` (case-insensitive substring of the model ID; longest stem wins) | step 3 |
| Thinking toggle | the template kwarg (`enable_thinking`, `thinking`, `thinking_mode`, `reasoning_effort`), if the model thinks | step 5 |

## Steps

### 1. Write the parser

File: `crates/tool_parser/src/parsers/<name>.rs` — Do: copy the struct fields and the `parse_incremental` body of `parsers/mistral.rs` / `parsers/qwen.rs` verbatim (`PartialJson`, `buffer`, `prev_tool_call_arr`, `current_tool_id`, `current_tool_name_sent`, `streamed_args_for_tool`); only the marker constants and the `parse_complete` extraction change per model. Streaming: with no marker and no partial marker (`helpers::ends_with_partial_token`) flush the buffer as normal text, otherwise hand the text after the start marker to `helpers::handle_json_tool_streaming` with `helpers::get_tool_indices`. `get_unstreamed_tool_args` returns `helpers::get_unstreamed_args(&self.prev_tool_call_arr, &self.streamed_args_for_tool)`; `reset` calls `helpers::reset_parser_state`.
Verify: `cargo check -p tool-parser`
Trap: there is no `extract_tool_calls_from_value` helper (the build fails); build `ToolCall { function: FunctionCall { name, arguments } }` yourself as `mistral.rs::parse_single_object` does, with `arguments` as a JSON string.

### 2. Export it

File: `crates/tool_parser/src/parsers/mod.rs` — Do: add `pub mod <name>;` and `pub use <name>::<Name>Parser;`. File: `crates/tool_parser/src/lib.rs` — Do: add `<Name>Parser` to the `pub use parsers::{ ... }` block (tests import `tool_parser::<Name>Parser`).
Verify: `cargo check -p tool-parser`

### 3. Register and map models

File: `crates/tool_parser/src/factory.rs` — Do: import the type; in `ParserFactory::new()` call `registry.register_parser("<name>", || Box::new(<Name>Parser::new()))`, or `register_parser_with_structural_tag(name, ctor, <Name>Parser::build_structural_tag)` when the engine can constrain the format (eight do at HEAD: `mistral`, `deepseek_v41`, `glm47_moe`, `kimik2`, `kimi_k3`, `inkling`, `minimax_m3`, `hy_v4`; add `register_reasoning_prefix` when the model thinks before the call, as `glm47_moe` / `minimax_m3` / `hy_v4` do). In `register_default_mappings` add `registry.map_model("<family>-*", "<name>")` once: `resolve_model_to_parser` tries an exact match, then the pattern's stem (trailing `*` stripped) as a case-insensitive substring of the model ID, longest stem wins — `acme-*` already covers `Acme/Acme-7B` and `org/acme-7b`. Pick a stem that cannot occur inside another family's ID (`nemotron-3*`, not `nemotron*`); unmatched models fall back to `passthrough`. Pin the mapping in `crates/tool_parser/src/tests.rs` (9d639713: `test_minimax_m3_model_mappings` asserts `resolve_model_to_parser` for four spellings).
Verify: `cargo test -p tool-parser --lib`

### 4. Write the integration tests

File: `crates/tool_parser/tests/models/tool_parser_<name>.rs` — Do: declare it with `mod tool_parser_<name>;` in `crates/tool_parser/tests/models/mod.rs` (the binary is `crates/tool_parser/tests/models_tests.rs`; since 1afcd326 there is no per-parser file at the `tests/` root). Import `use crate::common::create_test_tools;` (`crates/tool_parser/tests/common/mod.rs`) and `tool_parser::{<Name>Parser, ToolParser}`. Cover a complete single call, no markers (text unchanged), parallel calls, empty `arguments`, chunked streaming and `reset()` between requests, as `crates/tool_parser/tests/models/tool_parser_mistral.rs` does.
Verify: `cargo test -p tool-parser --test models_tests tool_parser_<name>`
Trap: `handle_json_tool_streaming` validates names against the `tools` slice and silently drops unknown ones, so a streaming test with a name absent from `create_test_tools()` (`search`, `get_weather`, ...) emits nothing. Schema-aware parsers (`parsers/minimax_m2.rs`) override `parse_complete_with_tools`, coerce each argument by its declared type (`helpers::coerce_by_schema_type`, `helpers::param_types_for_function`) and forward unknown names; there `tools` supplies types, not an allow-list.

### 5. Arm the gateway

File: `crates/tokenizer/src/chat_template.rs` — Do: if the model's template exposes a thinking switch `detect_thinking_toggle` does not know, return its `ThinkingToggle` (`DefaultOn` / `DefaultOff`) and `ThinkingKeyName` (`EnableThinking`, `Thinking`, `ThinkingMode`, `ReasoningEffort`; 9d639713 added `thinking_mode`, f22e1067 the `reasoning_effort` on/off words). File: `model_gateway/src/routers/grpc/utils/parsers.rs` — Do: read the kwarg in `extract_thinking_from_kwargs`; `should_mark_reasoning_started` then arms the reasoning parser per request. A structural tag reaches the engine through `tool_constraints_for_worker` → `ParserRegistry::structural_tag_for_grammar_start`; step 3's registration is all it needs.
Verify: `cargo test -p llm-tokenizer chat_template && cargo test -p smg parsers`
Trap: a registered parser whose toggle is not detected still compiles; thinking is then never armed and reasoning streams as content.

### 6. Document

File: `crates/tool_parser/README.md` — Do: add a row (`Parser | Model Family | Format`) to the parser table, as f22e1067 does for `HyV4Parser`. A push touching `crates/tool_parser/**` also runs the `Benchmark - Tool Parser` workflow (`.github/workflows/benchmark-tool-parser.yml`: `cargo bench --bench tool_parser_benchmark`, `model_gateway/benches/tool_parser_benchmark.rs`); it benchmarks fixed formats and needs no edit for a new parser.
Verify: `grep <Name>Parser crates/tool_parser/README.md`

### 7. Gate

Run `smg:contribute`.

## Rules

- `parse_complete(&self, ...)` is immutable; `parse_incremental(&mut self, ...)` accumulates in `self.buffer`. Reset only between requests, never between chunks: a mid-stream `reset()` loses partial calls.
- Stream argument deltas, not full arguments each chunk: `handle_json_tool_streaming` tracks `streamed_args_for_tool` and sends the diff; `get_unstreamed_tool_args` (via `helpers::get_unstreamed_args`) recovers what the model emits in its last chunk.
- Field-name quirks are normalized, not hand-rolled: `helpers::normalize_tool_call_fields` maps Cohere `tool_name` → `name` and `parameters` → `arguments`, already inside `handle_json_tool_streaming`.
- 26 keys at HEAD: `passthrough`, `json`, `gemma4`, `mistral`, `qwen`, `qwen_xml`, `qwen_coder`, `nemotron`, `pythonic`, `llama`, `deepseek`, `deepseek31`, `deepseek32`, `deepseek_v4`, `deepseek_v41`, `glm45_moe`, `glm47_moe`, `step3`, `sarashina`, `kimik2`, `kimi_k3`, `inkling`, `minimax_m2`, `minimax_m3`, `hy_v4`, `cohere`.

## When not to use the JSON-with-tags shape

| Format | In repo | Approach |
|---|---|---|
| Pure JSON, no tags (OpenAI/Claude/Gemini) | `parsers/json.rs` (`json`) | reuse `JsonParser`: `map_model(..., "json")`, no new file |
| Pythonic `[func(arg=val)]` (Llama 4) | `parsers/pythonic.rs` (`pythonic`) | reuse `PythonicParser` |
| Unicode-delimited blocks (DeepSeek) | `parsers/deepseek.rs`, `deepseek31.rs`, `deepseek_dsml.rs` (`DeepSeekDsmlParser::v32()` / `::v4()` / `::v41()`) | custom token matching; a new DSML dialect is another constructor (81d43443) |
| XML with `<parameter>` children (Qwen3-Coder/3.5+, Nemotron-3) | `parsers/qwen_xml.rs` (`QwenXmlParser`; keys `qwen_xml` / `qwen_coder` / `nemotron`) | `map_model` or alias-register `QwenXmlParser`, no new file |
| XML `<arg_key>` / `<arg_value>` pairs (GLM-4.5/4.6 → `glm45_moe`, GLM-4.7/5 → `glm47_moe`) | `parsers/glm4_moe.rs` (`Glm4MoeParser::glm45()` / `::glm47()`) | one struct, two constructors differing only in the func-detail regex |
| Namespaced / pipe-delimited XML | `minimax_m2.rs` (`<minimax:tool_call>`), `minimax_m3.rs`, `step3.rs` (`steptml:`), `kimik2.rs` (`<\|tool_calls_section_begin\|>`) | read the parser for the exact framing tokens; they are fragile, do not retype them from memory |
| Channel / marker token streams (Kimi-K3 XTML, Inkling TML, Hy4) | `kimi_k3.rs` (`<\|open\|>tools<\|sep\|>…<\|open\|>call tool="NAME" index="N"<\|sep\|>`, compiled `Regex` marker set), `inkling.rs` (`<\|message_model\|>NAME<\|content_invoke_tool_json\|>{…}<\|end_message\|>`, a `StreamingState` machine), `hy_v4.rs` (+ `hy_v4/streaming.rs`) | all expose `build_structural_tag` |
| Python-literal list of dicts `[{'name': …, 'arguments': {…}}]`, optional `<\|tool_calls\|>` prefix | `sarashina.rs` (`sarashina`) | reuse `pythonic::{parse_python_expression, expression_to_json}`, not `serde_json`: a different grammar from `[func(arg=val)]` |
- The reasoning twin lands in the same change: `crates/reasoning_parser/src/parsers/<name>.rs` and `crates/reasoning_parser/tests/<name>.rs` (@reasoning-parser.md).

# Adding a Tool Parser to SMG

Implement the `ToolParser` trait, register it in the factory, map model IDs to it. For the common "JSON wrapped in tags" case, delegate streaming to `helpers::handle_json_tool_streaming` and model your code on `parsers/mistral.rs` / `parsers/qwen.rs`. There is NO `extract_tool_calls_from_value` helper — build `ToolCall { function: FunctionCall { name, arguments } }` yourself.

First find the format: check vLLM (`vllm/tool_parsers`) or SGLang (`python/sglang/srt/function_call`) for the model family, or its HF `tokenizer_config.json` `chat_template`. Then copy the closest existing SMG parser's shape.

## Steps

### Step 1: Create the parser

**File:** `crates/tool_parser/src/parsers/<name>.rs` (e.g. `acme.rs` → `AcmeParser`)

The struct fields and `parse_incremental` body are the shared streaming pattern (identical in `mistral.rs`/`qwen.rs`) — keep them verbatim; only the tokens and `parse_complete` extraction change per model.

```rust
use async_trait::async_trait;
use openai_protocol::common::Tool;
use serde_json::Value;

use crate::{
    errors::{ParserError, ParserResult},
    parsers::helpers,
    partial_json::PartialJson,
    traits::ToolParser,
    types::{FunctionCall, StreamingParseResult, ToolCall},
};

const START_TOKEN: &str = "<tool_call>";
const END_TOKEN: &str = "</tool_call>";

pub struct AcmeParser {
    partial_json: PartialJson,
    buffer: String,
    prev_tool_call_arr: Vec<Value>,
    current_tool_id: i32,
    current_tool_name_sent: bool,
    streamed_args_for_tool: Vec<String>,
}

impl AcmeParser {
    pub fn new() -> Self {
        Self {
            partial_json: PartialJson::default(),
            buffer: String::new(),
            prev_tool_call_arr: Vec::new(),
            current_tool_id: -1,
            current_tool_name_sent: false,
            streamed_args_for_tool: Vec::new(),
        }
    }
}

impl Default for AcmeParser {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl ToolParser for AcmeParser {
    async fn parse_complete(&self, text: &str) -> ParserResult<(String, Vec<ToolCall>)> {
        let Some(start) = text.find(START_TOKEN) else {
            return Ok((text.to_string(), vec![]));
        };
        let normal_text = text[..start].to_string();
        let after = &text[start + START_TOKEN.len()..];
        let json_str = after.split(END_TOKEN).next().unwrap_or(after).trim();

        // Build ToolCall yourself — no extract_tool_calls_from_value helper exists.
        let value: Value =
            serde_json::from_str(json_str).map_err(|e| ParserError::ParsingFailed(e.to_string()))?;
        let Some(name) = value.get("name").and_then(|v| v.as_str()) else {
            return Ok((text.to_string(), vec![]));
        };
        let empty = Value::Object(serde_json::Map::new());
        let args = value.get("arguments").unwrap_or(&empty);
        let arguments =
            serde_json::to_string(args).map_err(|e| ParserError::ParsingFailed(e.to_string()))?;
        Ok((normal_text, vec![ToolCall {
            function: FunctionCall { name: name.to_string(), arguments },
        }]))
    }

    async fn parse_incremental(
        &mut self,
        chunk: &str,
        tools: &[Tool],
    ) -> ParserResult<StreamingParseResult> {
        self.buffer.push_str(chunk);
        let current_text = self.buffer.clone();

        // No marker yet: flush as normal text unless a partial start token is forming.
        if !self.has_tool_markers(&current_text) {
            if helpers::ends_with_partial_token(&self.buffer, START_TOKEN).is_none() {
                let normal_text = std::mem::take(&mut self.buffer);
                return Ok(StreamingParseResult { normal_text, calls: vec![] });
            }
            return Ok(StreamingParseResult::default());
        }

        let tool_indices = helpers::get_tool_indices(tools);
        let start_idx = current_text.find(START_TOKEN).map(|p| p + START_TOKEN.len()).unwrap_or(0);
        helpers::handle_json_tool_streaming(
            &current_text,
            start_idx,
            &mut self.partial_json,
            &tool_indices,
            &mut self.buffer,
            &mut self.current_tool_id,
            &mut self.current_tool_name_sent,
            &mut self.streamed_args_for_tool,
            &mut self.prev_tool_call_arr,
        )
    }

    fn has_tool_markers(&self, text: &str) -> bool {
        text.contains(START_TOKEN)
    }

    // Same body in every JSON parser — copy verbatim.
    fn get_unstreamed_tool_args(&self) -> Option<Vec<crate::types::ToolCallItem>> {
        helpers::get_unstreamed_args(&self.prev_tool_call_arr, &self.streamed_args_for_tool)
    }
    fn reset(&mut self) {
        helpers::reset_parser_state(
            &mut self.buffer,
            &mut self.prev_tool_call_arr,
            &mut self.current_tool_id,
            &mut self.current_tool_name_sent,
            &mut self.streamed_args_for_tool,
        );
    }
}
```

**Verify:** `cargo check -p tool-parser`
**Anti-pattern:** `helpers::extract_tool_calls_from_value(...)` does not exist — the build fails. Build `ToolCall`/`FunctionCall` directly (see `mistral.rs::parse_single_object`).

### Step 2: Export the parser

**File:** `crates/tool_parser/src/parsers/mod.rs` — add `pub mod acme;` and `pub use acme::AcmeParser;`.
**File:** `crates/tool_parser/src/lib.rs` — add `AcmeParser` to the `pub use parsers::{ ... }` re-export block (tests import it as `tool_parser::AcmeParser`).

**Verify:** `cargo check -p tool-parser`

### Step 3: Register in the factory + map models

**File:** `crates/tool_parser/src/factory.rs`

Import it in the `use crate::parsers::{ ... }` list, then in `ParserFactory::new()`:
```rust
registry.register_parser("acme", || Box::new(AcmeParser::new()));
```
And in `register_default_mappings`:
```rust
registry.map_model("acme-*", "acme");
registry.map_model("Acme/Acme-*", "acme");
```
Model resolution (`resolve_model_to_parser`): exact match first, then the **longest** trailing-`*` prefix wins. Put more specific patterns alongside general ones; length, not order, decides. Unmatched models fall back to the `passthrough` default.

**Verify:** `cargo check -p tool-parser`

### Step 4: Write integration tests

**File:** `crates/tool_parser/tests/tool_parser_acme.rs` (model on `tests/tool_parser_mistral.rs`)

```rust
mod common;

use common::create_test_tools;
use tool_parser::{AcmeParser, ToolParser};

#[tokio::test]
async fn test_complete_single() {
    let parser = AcmeParser::new();
    let input = r#"hi <tool_call>{"name": "get_weather", "arguments": {"city": "Paris"}}</tool_call>"#;
    let (normal, tools) = parser.parse_complete(input).await.unwrap();
    assert_eq!(normal, "hi ");
    assert_eq!(tools[0].function.name, "get_weather");
    let args: serde_json::Value = serde_json::from_str(&tools[0].function.arguments).unwrap();
    assert_eq!(args["city"], "Paris");
}

#[tokio::test]
async fn test_streaming() {
    let mut parser = AcmeParser::new();
    let tools = create_test_tools(); // valid names: search, get_weather, calculate, ...
    let chunks = ["<tool_call>{\"na", "me\":\"search\",\"argu", "ments\":{\"query\":\"x\"}}</tool_call>"];
    let mut calls = Vec::new();
    for c in chunks {
        calls.extend(parser.parse_incremental(c, &tools).await.unwrap().calls);
    }
    assert!(calls.iter().any(|c| c.name.as_deref() == Some("search")));
}
```

Add cases for: no markers (returns text unchanged), multiple/parallel calls, empty `arguments`, and `reset()` between requests — see `tests/tool_parser_mistral.rs`.

**Verify:** `cargo test -p tool-parser --test tool_parser_acme`
**Anti-pattern:** Tool names absent from `create_test_tools()` — `handle_json_tool_streaming` validates against the `tools` slice and silently drops unknown names, so streaming emits nothing.

> Note: "silently drops unknown names" is specific to this JSON streaming path. Schema-aware parsers like MiniMax-M2 (`parsers/minimax_m2.rs`) override `parse_complete_with_tools`, coerce each argument by its declared schema type (`helpers::coerce_by_schema_type`), and **forward** unknown tool names (still emit a tool_call). `tools` there only supplies types via `helpers::param_types_for_function`, not an allow-list.

### Step 5: Quality gate

Invoke `smg:contribute` to run fmt → clippy → test → bindings → commit.

## Critical Rules

| Rule | Why |
|---|---|
| `parse_complete(&self, ...)` is immutable; `parse_incremental(&mut self, ...)` is stateful | Trait signatures in `traits.rs`; streaming accumulates in `self.buffer` etc. |
| Return type is `(String, Vec<ToolCall>)` for complete, `StreamingParseResult { normal_text, calls: Vec<ToolCallItem> }` for streaming | `types.rs` |
| Reset only between requests, never between chunks | `reset()` clears buffer/state; mid-stream reset loses partial calls |
| Stream argument **deltas**, not full args each chunk | `handle_json_tool_streaming` tracks `streamed_args_for_tool` and sends only the diff |
| Implement `get_unstreamed_tool_args` via `helpers::get_unstreamed_args` | Recovers final args the model emits in the last chunk |
| No `Rc`/`RefCell`/non-`Send` fields | `ToolParser: Send + Sync`; parsers are pooled behind `Arc<Mutex<…>>` |
| Field-name quirks: normalize, don't hand-roll | `helpers::normalize_tool_call_fields` maps Cohere `tool_name`→`name`, `parameters`→`arguments` (already called inside `handle_json_tool_streaming`) |

## When NOT to use this JSON-with-tags template

| Format | Example in repo | Approach |
|---|---|---|
| Pure JSON, no tags (OpenAI/Claude/Gemini) | `parsers/json.rs` (`json`) | Reuse `JsonParser`; just `map_model(... , "json")`, no new file |
| Pythonic `[func(arg=val)]` (Llama 4) | `parsers/pythonic.rs` (`pythonic`) | Reuse `PythonicParser` |
| Unicode-delimited blocks (DeepSeek) | `parsers/deepseek.rs`, `deepseek31.rs`, `deepseek_dsml.rs` | Custom token matching |
| XML with `<parameter>` children | `parsers/qwen_xml.rs` (`QwenXmlParser`, keys `qwen_xml`/`qwen_coder`), `glm4_moe.rs` | Custom XML extraction, not `handle_json_tool_streaming` |
| Namespaced/pipe-delimited XML | `minimax_m2.rs` (`<minimax:tool_call>`), `step3.rs` (`steptml:`), `kimik2.rs` (`<\|tool_calls_section_begin\|>…`) | Read the parser for exact framing tokens — they are fragile; don't retype from memory |

Current parsers (factory keys): `passthrough`, `json`, `mistral`, `qwen`, `qwen_xml`, `qwen_coder`, `pythonic`, `llama`, `deepseek`, `deepseek31`, `deepseek32`, `deepseek_v4`, `glm45_moe`, `glm47_moe`, `step3`, `kimik2`, `minimax_m2`, `cohere`.
